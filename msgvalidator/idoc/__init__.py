"""SAP IDoc (XML form, e.g. INVOIC01 / INVOIC02): parsing, structure checks, segment tree.

Every IDoc segment (element with attribute SEGMENT) becomes an EDIFACT-like :class:`Segment`
whose elements are the segment's fields in a fixed order per segment type (dictionary order first,
then fields first seen in the file). Mappings address fields by name (``E1EDKA1[PARVW=RS]`` /
``NAME1``) and are resolved to positions per message, so the whole semantic pipeline (selector,
mapping, derivations, gap analysis, virtual UBL) is reused unchanged.

Segments with child segments become groups (``E1EDP01`` with its ``E1EDP19``, ``E1EDP26`` …).
A synthetic ``UNS`` separates the summary segments (``E1EDS01``) like in EDIFACT.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml
from lxml import etree

from ..edifact.parser import Segment
from ..edifact.structure import GroupInstance
from ..resources import data_path

SUMMARY_TAGS = {"E1EDS01"}
DATE_RE = re.compile(r"^\d{8}$")
NUM_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?[+-]?$")


@lru_cache(maxsize=1)
def dictionary() -> dict:
    d = yaml.safe_load(data_path("idoc", "invoic_dictionary.yaml").read_text(encoding="utf-8"))
    d["num"] = set(d["types"]["num"])
    d["date"] = set(d["types"]["date"])
    return d


def segment_info(tag: str) -> dict:
    return dictionary()["segments"].get(tag, {})


@dataclass
class IdocMessage:
    ref: str  # DOCNUM
    idoctyp: str
    mestyp: str
    control: dict[str, str]
    root: GroupInstance
    segments: list[Segment]
    fields: dict[str, list[str]]  # segment tag -> field names in element order
    issues: list[dict] = field(default_factory=list)
    # EDIFACT Message compatibility (extract() reads .version / .type)
    type: str = "INVOIC"
    version: str = ""
    assoc: str = "SAP IDoc"
    agency: str = ""
    generic: bool = False  # any XML read element-wise (no SAP IDoc semantics)
    root_tag: str = ""

    def records(self) -> dict:
        """Layout-like field registry for the mapping resolver (element k = field k+1)."""
        return {tag: {"fields": [{"n": 1, "name": "TAG"}] + [{"n": i + 2, "name": n} for i, n in enumerate(names)]}
                for tag, names in self.fields.items()}

    def first(self, tag: str) -> Segment | None:
        return next((s for s in self.segments if s.tag == tag), None)

    def value(self, tag: str, name: str) -> str | None:
        if tag == "ROOT":
            return self.root_tag or None
        seg = self.first(tag)
        names = self.fields.get(tag, [])
        if seg is None or name not in names:
            return None
        return seg.get(names.index(name) + 1)


@dataclass
class IdocFile:
    messages: list[IdocMessage] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)


def _issue(sev, code, msg, line=None, segment=None):
    return {"severity": sev, "code": code, "message": msg, "line": line, "segment": segment}


def is_idoc(root) -> bool:
    if root.find("IDOC") is not None and root.find("IDOC/EDI_DC40") is not None:
        return True
    return etree.QName(root).localname == "IDOC" and root.find("EDI_DC40") is not None


def _norm(v: str) -> str:
    """Trim padding; SAP trailing sign '10.000-' -> '-10.000'."""
    v = (v or "").strip()
    if NUM_RE.match(v) and v[-1] in "+-":
        v = v[-1].replace("+", "") + v[:-1]
    return v


def _tag(el) -> str:
    return etree.QName(el).localname


def _is_segment(el, generic: bool = False) -> bool:
    if not isinstance(el.tag, str):
        return False
    if generic:  # any XML: an element with child elements is a "segment", a leaf element is a field
        return any(isinstance(c.tag, str) for c in el)
    return el.get("SEGMENT") is not None or el.tag == "EDI_DC40"


def _fields_of(el, generic: bool) -> list[tuple[str, str | None, int | None]]:
    """(name, text, line) of the leaf fields of a segment; generic XML also exposes attributes."""
    out = []
    if generic:
        out += [(etree.QName(k).localname, v, el.sourceline) for k, v in el.attrib.items()]
    out += [(_tag(c), c.text, c.sourceline) for c in el if isinstance(c.tag, str) and not _is_segment(c, generic)]
    return out


TEXT_SEG_RE = re.compile(r"^(\s*)(EDI_DC40|[EZY][0-9][A-Z0-9_]+)\s*$")
TEXT_FIELD_RE = re.compile(r"^(\s*)([A-Z][A-Z0-9_]*)(?:\s+(.*?))?\s*$")


def is_idoc_text(data: bytes) -> bool:
    head = data[:400].lstrip(b"\xef\xbb\xbf \r\n\t")
    if not head.startswith(b"EDI_DC40"):
        return False
    first = head.split(b"\n", 1)[0].rstrip(b"\r")
    return len(first.strip()) <= 12  # 'EDI_DC40' alone; SAP fixed-width flat files have long records


def text_to_xml(data: bytes):
    """Indented text dump of an IDoc (segment name on its own line, then 'FIELD   value' lines) -> IDoc XML tree."""
    text = data.decode("utf-8-sig", errors="replace")
    root = etree.Element("IDOC_TEXT")
    idoc = etree.SubElement(root, "IDOC", BEGIN="1")
    stack = []  # (indent, segment element)
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        m = TEXT_SEG_RE.match(line)
        if m:
            ind = len(m.group(1).expandtabs())
            while stack and stack[-1][0] >= ind:
                stack.pop()
            parent = stack[-1][1] if stack else idoc
            el = etree.SubElement(parent, m.group(2), SEGMENT="1")
            el.sourceline = no
            stack.append((ind, el))
            continue
        m = TEXT_FIELD_RE.match(line)
        if m and stack:
            f = etree.SubElement(stack[-1][1], m.group(2))
            f.text = m.group(3) or ""
            f.sourceline = no
        else:
            raise ValueError(f"Řádek {no}: '{line.strip()[:40]}' není segment ani pole IDocu.")
    root.tag = root.findtext("IDOC/EDI_DC40/IDOCTYP") or "IDOC_TEXT"
    return root


def parse(data: bytes) -> IdocFile:
    """SAP IDoc in XML or as an indented text dump; any other XML is read generically (for client mappings)."""
    if is_idoc_text(data):
        root = text_to_xml(data)
    else:
        root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False))
    out = IdocFile()
    if not is_idoc(root):
        out.messages.append(_message(root, 1, generic=True))
        return out
    idocs = root.findall("IDOC") if _tag(root) != "IDOC" else [root]
    for n, idoc in enumerate(idocs, 1):
        out.messages.append(_message(idoc, n))
    return out


def _message(idoc, n: int, generic: bool = False) -> IdocMessage:
    dic = dictionary()
    # field registry: dictionary order first, then whatever the file carries
    fields: dict[str, list[str]] = {}
    for el in idoc.iter():
        if not _is_segment(el, generic):
            continue
        names = fields.setdefault(_tag(el), [] if generic else list(segment_info(el.tag).get("fields", {})))
        for f, _, _ in _fields_of(el, generic):
            if f not in names:
                names.append(f)

    issues: list[dict] = []
    segments: list[Segment] = []

    def make(el) -> Segment:
        tag = _tag(el)
        names = fields[tag]
        elements = [[""] for _ in names]
        shown = []
        for name, text, line in _fields_of(el, generic):
            v = _norm(text)
            if elements[names.index(name)] != [""]:
                continue  # repeated leaf element – keep the first
            elements[names.index(name)] = [v]
            if v:
                shown.append(f"{name}={v}")
                if generic:
                    continue
                where = f"{tag} {name}"
                if name in dic["num"] and not NUM_RE.match(v.replace(" ", "")):
                    issues.append(_issue("error", "IDOC-NUM", f"{where}: '{v}' není číslo.", line, tag))
                elif name in dic["date"] and not (DATE_RE.match(v) and v != "00000000"):
                    issues.append(_issue("error", "IDOC-DATE", f"{where}: '{v}' není datum RRRRMMDD.", line, tag))
        seg = Segment(tag, elements, el.sourceline or 0, len(segments) + 1,
                      f"{tag} #{len(segments) + 1}: " + "; ".join(shown[:4]))
        segments.append(seg)
        return seg

    def node(el):
        seg = make(el)
        kids = [c for c in el if _is_segment(c, generic)]
        if not kids:
            return seg
        return GroupInstance(_tag(el), [seg] + [node(c) for c in kids])

    root = GroupInstance("ROOT")
    summary_started = False
    for el in ([idoc] if generic else idoc):
        if not _is_segment(el, generic):
            continue
        if not generic and el.tag in SUMMARY_TAGS and not summary_started:
            root.children.append(Segment("UNS", [["S"]], el.sourceline or 0, 0, "UNS (souhrn)"))
            summary_started = True
        root.children.append(node(el))
    if not summary_started:
        root.children.append(Segment("UNS", [["S"]], 0, 0, "UNS (souhrn)"))

    msg = IdocMessage(ref=str(n), idoctyp="", mestyp="", control={}, root=root, segments=segments, fields=fields)
    if generic:
        msg.generic, msg.root_tag = True, _tag(idoc)
        msg.idoctyp, msg.version, msg.assoc = f"XML <{msg.root_tag}>", "", "XML"
        return msg
    dc = msg.first("EDI_DC40")
    if dc is not None:
        msg.control = {name: dc.get(i + 1) or "" for i, name in enumerate(fields["EDI_DC40"])}
    parent = idoc.getparent()
    msg.idoctyp = msg.control.get("IDOCTYP") or (_tag(parent) if parent is not None else "")
    msg.mestyp = msg.control.get("MESTYP", "")
    msg.version = msg.idoctyp
    msg.ref = msg.value("E1EDK01", "BELNR") or (msg.control.get("DOCNUM") or "").lstrip("0") or str(n)
    msg.issues = issues + check_structure(msg)
    return msg


def check_structure(msg: IdocMessage) -> list[dict]:
    issues = []
    tags = {s.tag for s in msg.segments}
    if "EDI_DC40" not in tags:
        issues.append(_issue("warning", "IDOC-CONTROL", "Chybí řídicí záznam EDI_DC40 (odesílatel, typ IDocu)."))
    if msg.mestyp and msg.mestyp != "INVOIC":
        issues.append(_issue("error", "IDOC-TYPE", f"Typ zprávy {msg.mestyp} – podporováno je jen INVOIC."))
    if msg.idoctyp and not msg.idoctyp.startswith("INVOIC"):
        issues.append(_issue("warning", "IDOC-TYPE", f"Základní typ {msg.idoctyp} – očekáván INVOIC01 / INVOIC02."))
    for tag, sev, what in (("E1EDK01", "error", "záhlaví dokladu"), ("E1EDP01", "warning", "žádná položka"),
                           ("E1EDS01", "warning", "součty dokladu")):
        if tag not in tags:
            issues.append(_issue(sev, "IDOC-MISSING-SEGMENT", f"Chybí segment {tag} ({what})."))
    known = dictionary()["segments"]
    for tag in sorted(tags - set(known) - {"UNS"}):
        first = next(s for s in msg.segments if s.tag == tag)
        kind = "zákaznický segment" if tag.startswith(("Z", "Y")) else "segment mimo slovník validátoru"
        issues.append(_issue("info", "IDOC-UNKNOWN-SEGMENT",
                             f"{tag}: {kind} – jeho pole lze použít v klientském mapování.", first.line, first.raw[:60]))
    return issues
