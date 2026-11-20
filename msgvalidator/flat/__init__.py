"""Fixed-width flat files (EDITEL INHOUSE and similar record-oriented text formats).

A *layout* (data/flat/<id>.json) describes the records: a tag at fixed positions, fields with
start/end (1-based, inclusive), type (Char / Num / Date), decimals and whether they are required.

Each line becomes an EDIFACT-like :class:`Segment` (tag + one single-component element per field,
element k = field k+1) so the whole semantic pipeline (selector, mapping, derivations, gap analysis,
virtual UBL, KoSIT rules) is reused unchanged. Mappings may use field *names* instead of positions;
see :mod:`msgvalidator.flat.mapping`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from ..edifact.parser import Segment
from ..edifact.structure import GroupInstance
from ..resources import data_path

NUM_RE = re.compile(r"^[+-]?\d*(?:[.,]\d+)?[+-]?$")


@dataclass
class Layout:
    id: str
    label: str
    raw: dict

    @property
    def records(self) -> dict:
        return self.raw["records"]

    def fields(self, tag: str) -> list[dict]:
        return self.raw["records"].get(tag, {}).get("fields", [])

    def field_index(self, tag: str, name: str) -> int | None:
        """Element index (1-based, after the tag) of a named field."""
        for f in self.fields(tag):
            if f["name"] == name:
                return f["n"] - 1
        return None

    def field_by_index(self, tag: str, idx: int) -> dict | None:
        for f in self.fields(tag):
            if f["n"] - 1 == idx:
                return f
        return None


@lru_cache(maxsize=None)
def load_layout(layout_id: str) -> Layout:
    raw = json.loads(data_path("flat", f"{layout_id}.json").read_text(encoding="utf-8"))
    return Layout(raw["id"], raw.get("label", raw["id"]), raw)


@dataclass
class FlatMessage:
    ref: str
    type: str
    version: str
    assoc: str
    segments: list[Segment] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    agency: str = ""


@dataclass
class FlatFile:
    layout: Layout
    encoding: str
    messages: list[FlatMessage] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)


def decode(data: bytes, default: str = "cp1250") -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8"
    try:
        text = data.decode("utf-8")
        if any(b > 127 for b in data):
            return text, "utf-8"
    except UnicodeDecodeError:
        pass
    return data.decode(default, errors="replace"), default


def _norm_num(v: str) -> str | None:
    """'   000012.50' -> '12.50', '12,5' -> '12.5', '12.50-' -> '-12.50'; None when not a number."""
    s = v.strip().replace(" ", "")
    if not s:
        return ""
    if not NUM_RE.match(s) or s in "+-.,":
        return None
    if s[-1] in "+-":
        s = s[-1] + s[:-1]
    s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if "." in s:
        # fixed-decimal padding ('100.0000') carries no meaning – keep significant digits, at least 2
        frac = s.split(".", 1)[1].rstrip("0")
        dec = max(len(frac), min(2, len(s.split(".", 1)[1])))
        return f"{d:.{dec}f}"
    return str(int(d))


def _valid_date(v: str) -> bool:
    import datetime as dt
    try:
        dt.datetime.strptime(v[:8], "%Y%m%d")
        return len(v) >= 8 and v.isdigit()
    except ValueError:
        return False


def _issue(sev, code, msg, line=None, segment=None):
    return {"severity": sev, "code": code, "message": msg, "line": line, "segment": segment}


def _record(line_text: str, lineno: int, tag: str, layout: Layout, issues: list[dict], index: int) -> Segment:
    rec = layout.records[tag]
    # element k = field number k+1 (numbering in specifications may have gaps, e.g. CCV HDR has no field 91)
    elements = [[""] for _ in range(max(f["n"] for f in rec["fields"]) - 1)]
    raw = line_text.rstrip()
    max_end = max(f["end"] for f in rec["fields"])
    if len(raw) > max_end:
        extra = raw[max_end:].strip()
        if extra:
            issues.append(_issue("warning", "FLAT-LENGTH",
                                 f"{tag}: záznam je delší ({len(raw)} znaků) než definice ({max_end}); "
                                 f"přebývá '{extra[:40]}'.", lineno, raw[:60]))
    for f in rec["fields"][1:]:
        value = line_text[f["start"] - 1:f["end"]] if len(line_text) >= f["start"] else ""
        value = value.strip()
        where = f"{tag} pole {f['n']} {f['name']} (poz. {f['start']}-{f['end']})"
        if value and f["type"] == "Num":
            n = _norm_num(value)
            if n is None:
                issues.append(_issue("error", "FLAT-NUM", f"{where}: '{value}' není číslo.", lineno, raw[:60]))
            else:
                if f.get("dec") is not None and "." in n and len(n.split(".")[1]) > f["dec"]:
                    issues.append(_issue("warning", "FLAT-DECIMALS",
                                         f"{where}: '{value}' má víc desetinných míst než {f['dec']}.", lineno, raw[:60]))
                value = n
        elif value and f["type"] == "Date" and not _valid_date(value):
            issues.append(_issue("error", "FLAT-DATE", f"{where}: '{value}' není platné datum YYYYMMDD.", lineno, raw[:60]))
        if not value and f.get("req") and not f.get("cond"):
            issues.append(_issue("error", "FLAT-MISSING", f"{where} – {f['label']}: povinné pole je prázdné.",
                                 lineno, raw[:60]))
        elements[f["n"] - 2] = [value]
    return Segment(tag, elements, lineno, index, raw[:120])


def parse(data: bytes, layout_id: str) -> FlatFile:
    layout = load_layout(layout_id)
    text, enc = decode(data, layout.raw.get("encoding", "cp1250"))
    ff = FlatFile(layout, enc)
    t0, t1 = layout.raw["tag"]["start"], layout.raw["tag"]["end"]
    starts = layout.raw.get("message_start", ["HDR"])
    cur: FlatMessage | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        tag = line[t0 - 1:t1]
        if tag not in layout.records:
            target = cur.issues if cur else ff.issues
            target.append(_issue("error", "FLAT-UNKNOWN-RECORD",
                                 f"Neznámý záznam '{tag}' (layout {layout.label}).", lineno, line[:60]))
            continue
        # a new message starts with SYS, or with HDR when the previous record was not SYS
        if tag in starts and (cur is None or tag == starts[0] or
                              (cur.segments and cur.segments[-1].tag != starts[0] and tag != starts[0])):
            cur = FlatMessage(str(len(ff.messages) + 1), layout.raw.get("message", ""),
                              layout.raw.get("version", ""), layout.raw.get("family", "FLAT"))
            ff.messages.append(cur)
        if cur is None:
            cur = FlatMessage("1", layout.raw.get("message", ""), layout.raw.get("version", ""),
                              layout.raw.get("family", "FLAT"))
            ff.messages.append(cur)
        cur.segments.append(_record(line, lineno, tag, layout, cur.issues, len(cur.segments) + 1))
    for m in ff.messages:
        m.issues += check_structure(m, layout)
        rtag, rname = layout.raw.get("ref_field", ["HDR", "CIS_DOKL"])
        hdr = next((s for s in m.segments if s.tag == rtag), None)
        idx = layout.field_index(rtag, rname)
        if hdr is not None and idx:
            m.ref = hdr.get(idx) or m.ref
    if not ff.messages:
        ff.issues.append(_issue("error", "FLAT-EMPTY", "Soubor neobsahuje žádný rozpoznaný záznam."))
    return ff


def _flat_structure(layout: Layout):
    """tag -> (position in message, min, max, parent tag or None)."""
    out = {}
    for i, s in enumerate(layout.raw["structure"]):
        out[s["tag"]] = (i, s["min"], s["max"], None)
        for c in s.get("children", []):
            out[c["tag"]] = (i, c["min"], c["max"], s["tag"])
    return out


def check_structure(msg: FlatMessage, layout: Layout) -> list[dict]:
    st = _flat_structure(layout)
    issues = []
    pos, parent_seen = -1, None
    counts: dict[str, int] = {}
    child_counts: dict[str, int] = {}
    for seg in msg.segments:
        if seg.tag not in st:
            continue
        i, _, mx, parent = st[seg.tag]
        if parent:
            if parent_seen != parent:
                issues.append(_issue("error", "FLAT-ORDER", f"Záznam {seg.tag} musí následovat za {parent}.",
                                     seg.line, seg.raw[:60]))
            child_counts[seg.tag] = child_counts.get(seg.tag, 0) + 1
            if child_counts[seg.tag] > mx:
                issues.append(_issue("error", "FLAT-REPEAT", f"{seg.tag}: víc než {mx}× pod jedním {parent}.",
                                     seg.line, seg.raw[:60]))
            continue
        if i < pos:
            issues.append(_issue("error", "FLAT-ORDER",
                                 f"Záznam {seg.tag} je na špatném místě (očekávané pořadí: "
                                 f"{', '.join(s['tag'] for s in layout.raw['structure'])}).", seg.line, seg.raw[:60]))
        pos, parent_seen = max(pos, i), seg.tag
        child_counts = {}
        counts[seg.tag] = counts.get(seg.tag, 0) + 1
        if counts[seg.tag] == mx + 1:
            issues.append(_issue("error", "FLAT-REPEAT", f"{seg.tag}: povoleno nejvýše {mx}×.", seg.line, seg.raw[:60]))
    first = msg.segments[0].line if msg.segments else None
    for s in layout.raw["structure"]:
        if counts.get(s["tag"], 0) < s["min"]:
            sev = "warning" if s["tag"] == "SYS" else "error"
            issues.append(_issue(sev, "FLAT-MISSING-RECORD",
                                 f"Chybí záznam {s['tag']} ({layout.records.get(s['tag'], {}).get('label', '')}), "
                                 f"požadováno min. {s['min']}×.", first))
    return issues


def _unpivot(segs: list[Segment], layout: Layout, parent_tag: str | None) -> list[Segment]:
    out = []
    for vtag, cfg in layout.raw.get("unpivot", {}).items():
        if cfg.get("parent") != parent_tag:
            continue
        for src in segs:
            if src.tag != cfg["from"]:
                continue
            for row in cfg["rows"]:
                vals = {}
                for name in cfg["fields"]:
                    spec = row.get(name)
                    if spec is None:
                        vals[name] = ""
                    elif spec.startswith("="):
                        vals[name] = spec[1:]
                    else:
                        idx = layout.field_index(src.tag, spec)
                        vals[name] = (src.get(idx) or "") if idx else ""
                zero = all(not vals.get(k) or _is_zero(vals[k]) for k in cfg.get("skip_if_zero", []))
                if zero:
                    continue
                elements = [[vals[n]] for n in cfg["fields"]]
                out.append(Segment(vtag, elements, src.line, src.index, src.raw))
    return out


def _is_zero(v: str) -> bool:
    try:
        return Decimal(v) == 0
    except InvalidOperation:
        return False


def virtual_records(layout: Layout) -> dict:
    """Layout records + virtual (unpivoted) records, for the name resolver."""
    recs = dict(layout.records)
    for vtag, cfg in layout.raw.get("unpivot", {}).items():
        recs[vtag] = {"label": cfg.get("label", vtag),
                      "fields": [{"n": 1, "name": "TAG"}] + [{"n": i + 2, "name": n} for i, n in enumerate(cfg["fields"])]}
    return recs


def build_tree(msg: FlatMessage, layout: Layout) -> GroupInstance:
    """Group records like the EDIFACT matcher does: parents with children become groups;
    a synthetic UNS separates the summary records (and the virtual VAT records) from the body."""
    st = layout.raw["structure"]
    parents = {s["tag"]: {c["tag"] for c in s.get("children", [])} for s in st if s.get("children")}
    summary_tags = {s["tag"] for s in st if s.get("summary")}
    root = GroupInstance("ROOT")
    summary: list[Segment] = []
    group: GroupInstance | None = None
    for seg in msg.segments:
        if seg.tag in summary_tags:
            summary.append(seg)
            group = None
            continue
        if group is not None and seg.tag in parents.get(group.trigger.tag, set()):
            group.children.append(seg)
            continue
        if group is not None:
            group.children += _unpivot(group.children[:1], layout, group.trigger.tag)
            group = None
        if seg.tag in parents:
            group = GroupInstance(seg.tag, [seg])
            root.children.append(group)
        else:
            root.children.append(seg)
    if group is not None:
        group.children += _unpivot(group.children[:1], layout, group.trigger.tag)
    line = summary[0].line if summary else (msg.segments[-1].line if msg.segments else 0)
    root.children.append(Segment("UNS", [["S"]], line, 0, "UNS (souhrn)"))
    root.children += summary
    root.children += [v for v in _unpivot(summary, layout, None)]
    return root


FIT_CODES = {"FLAT-NUM", "FLAT-DATE", "FLAT-UNKNOWN-RECORD", "FLAT-LENGTH"}


def fit_score(data: bytes, layout_id: str, max_lines: int = 60) -> int:
    """How badly does the file fit a layout? Number of type/record errors in the first lines (0 = perfect)."""
    head = b"\n".join(data.splitlines()[:max_lines])
    try:
        ff = parse(head, layout_id)
    except Exception:  # pragma: no cover - defensive
        return 10 ** 6
    issues = ff.issues + [i for m in ff.messages for i in m.issues]
    return sum(1 for i in issues if i["code"] in FIT_CODES)


def best_layout(data: bytes, candidates: list[str]) -> tuple[str, int]:
    scored = sorted((fit_score(data, c), c) for c in candidates)
    return scored[0][1], scored[0][0]
