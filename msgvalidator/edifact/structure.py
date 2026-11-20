"""Match a message's segments against a branching diagram (segment groups).

Produces a tree of GroupInstance objects (used by the mapping engine) and
structure findings (unexpected segment, missing mandatory, too many repeats).
The structure definitions are generated from the MIG PDFs by tools/parse_mig.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

from ..resources import data_path
from .parser import Message, Segment


@dataclass
class GroupInstance:
    name: str  # "SG2" or "ROOT"
    children: list = field(default_factory=list)  # Segment | GroupInstance

    @property
    def trigger(self) -> Segment | None:
        return self.children[0] if self.children and isinstance(self.children[0], Segment) else None

    def segments(self):
        for ch in self.children:
            if isinstance(ch, Segment):
                yield ch
            else:
                yield from ch.segments()


@lru_cache(maxsize=None)
def load_structure(message: str, version: str) -> dict | None:
    p = data_path("edifact", f"{message}_{version}.json")
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _first_tag(node: dict) -> str:
    return node["tag"] if "tag" in node else node["children"][0]["tag"]


class _Matcher:
    def __init__(self, segs: list[Segment], label: str, severity_unexpected: str, record_paths: bool):
        self.segs = segs
        self.issues: list[dict] = []
        self.label = label
        self.sev = severity_unexpected
        self.record = record_paths

    def issue(self, sev, code, seg, msg):
        self.issues.append({"severity": sev, "code": code, "line": seg.line if seg else None,
                            "segment": seg.raw if seg else None, "message": msg})

    def seq(self, nodes: list[dict], i: int, inst: GroupInstance, path: str, top: bool) -> int:
        k = 0
        while k < len(nodes):
            node = nodes[k]
            tag = _first_tag(node)
            count = 0
            while i < len(self.segs) and self.segs[i].tag == tag:
                seg = self.segs[i]
                count += 1
                if count == node["max"] + 1:
                    what = node.get("group") or tag
                    self.issue("error", "STRUCT-REPEAT", seg,
                               f"{what} se opakuje více než povolených {node['max']}× ({self.label}).")
                if "tag" in node:
                    if self.record:
                        seg.path = f"{path}/{tag}" if path else tag
                    inst.children.append(seg)
                    i += 1
                else:
                    g = GroupInstance(node["group"], [seg])
                    if self.record:
                        seg.path = f"{path}/{node['group']}" if path else node["group"]
                    inst.children.append(g)
                    i = self.seq(node["children"][1:], i + 1, g, f"{path}/{node['group']}" if path else node["group"], False)
            if count == 0 and i < len(self.segs):
                # Does the current segment belong somewhere later on this level?
                later = {_first_tag(n) for n in nodes[k + 1:]}
                if self.segs[i].tag not in later:
                    if top:
                        seg = self.segs[i]
                        self.issue(self.sev, "STRUCT-UNEXPECTED", seg,
                                   f"Segment {seg.tag} není na tomto místě podle {self.label} povolen "
                                   f"(skupina {path or 'záhlaví'}).")
                        i += 1
                        continue  # retry same node with the next segment
                    self._missing(nodes[k:], i, path)
                    return i
            if count == 0 and node["status"] == "M":
                what = node.get("group") or tag
                ref = self.segs[i] if i < len(self.segs) else self.segs[-1]
                self.issue("error", "STRUCT-MISSING", ref,
                           f"Chybí povinný {'segment' if 'tag' in node else 'skupina'} {what}"
                           f"{' (' + node.get('name', '') + ')' if node.get('name') else ''} ({self.label}).")
            k += 1
        return i

    def _missing(self, nodes, i, path):
        ref = self.segs[i] if i < len(self.segs) else self.segs[-1]
        for n in nodes:
            if n["status"] == "M":
                what = n.get("group") or n["tag"]
                self.issue("error", "STRUCT-MISSING", ref,
                           f"Chybí povinný {'segment' if 'tag' in n else 'skupina'} {what} ve skupině {path} ({self.label}).")


def match(msg: Message) -> tuple[GroupInstance | None, list[dict]]:
    """Return the group tree (built against the full UN structure) and structure findings."""
    st = load_structure(msg.type, msg.version)
    if st is None:
        return None, [{"severity": "warning", "code": "STRUCT-UNKNOWN", "line": None, "segment": None,
                       "message": f"Pro {msg.type} {msg.version} není k dispozici definice struktury – kontrola struktury přeskočena."}]
    root = GroupInstance("ROOT")
    m = _Matcher(msg.segments, f"UN/EDIFACT {msg.version}", "error", True)
    m.seq(st["full"], 0, root, "", True)
    issues = m.issues
    if st.get("subset"):
        sub = _Matcher(msg.segments, f"GS1 CZ subset {msg.version}", "warning", False)
        sub.seq(st["subset"], 0, GroupInstance("ROOT"), "", True)
        known = {(i["code"], i["line"]) for i in issues}
        for i in sub.issues:
            if (i["code"], i["line"]) in known:
                continue
            i = dict(i)
            i["severity"] = "warning"
            i["code"] = "MIG-" + i["code"]
            issues.append(i)
    issues += check_qualifiers(msg, st)
    return root, issues


def check_qualifiers(msg: Message, st: dict) -> list[dict]:
    """First data element (qualifier) of each segment against the codes listed in the GS1 CZ MIG."""
    allowed = st.get("qualifiers") or {}
    out = []
    for seg in msg.segments:
        if not seg.path:
            continue
        parts = seg.path.split("/")
        sg = parts[-2] if len(parts) > 1 else ""
        # a group's trigger segment carries the group name as last path element
        if parts[-1].startswith("SG"):
            sg = parts[-1]
        codes = allowed.get(f"{sg}/{seg.tag}")
        val = seg.get(1, 1)
        if codes and val and val not in codes:
            where = f"skupina {sg}" if sg else "záhlaví/sumace"
            out.append({"severity": "warning", "code": "MIG-QUALIFIER", "line": seg.line, "segment": seg.raw,
                        "message": f"{seg.tag}: kód '{val}' není v GS1 CZ MIG {msg.version} pro {where} uveden "
                                   f"(povoleno: {', '.join(codes)})."})
    return out
