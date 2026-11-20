"""UN/EDIFACT tokenizer: interchange -> messages -> segments -> elements -> components.

Keeps source line numbers so every finding can point back to the file.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_UNA = {"comp": ":", "elem": "+", "dec": ".", "rel": "?", "rep": " ", "seg": "'"}


@dataclass
class Segment:
    tag: str
    elements: list[list[str]]  # elements[0] is the first data element after the tag
    line: int  # 1-based line in the source file where the segment starts
    index: int  # 1-based position inside the message (UNH = 1)
    raw: str
    path: str = ""  # filled by structure matching, e.g. "SG2/SG3/RFF"

    def get(self, elem: int, comp: int = 1) -> str | None:
        """1-based element/component access, None when absent or empty."""
        if elem < 1 or elem > len(self.elements):
            return None
        comps = self.elements[elem - 1]
        if comp < 1 or comp > len(comps):
            return None
        return comps[comp - 1] or None

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{self.raw} @L{self.line}>"


@dataclass
class Message:
    ref: str
    type: str  # e.g. INVOIC
    version: str  # e.g. D01B
    agency: str
    assoc: str  # association assigned code, e.g. EAN011
    segments: list[Segment] = field(default_factory=list)

    @property
    def body(self) -> list[Segment]:
        return self.segments


@dataclass
class Interchange:
    una: dict
    unb: Segment | None
    unz: Segment | None
    messages: list[Message]
    charset: str
    encoding: str
    issues: list[dict]


def decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1250"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def _split(text: str, sep: str, rel: str) -> list[str]:
    out, cur, i = [], [], 0
    while i < len(text):
        ch = text[i]
        if ch == rel and i + 1 < len(text):
            cur.append(text[i + 1])
            i += 2
            continue
        if ch == sep:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _segments(text: str, una: dict):
    """Yield (raw, line) for each segment, honouring the release character."""
    seg, rel = una["seg"], una["rel"]
    buf, line, start_line, i = [], 1, None, 0
    while i < len(text):
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch == "\r":
            i += 1
            continue
        if start_line is None:
            if ch.isspace():
                i += 1
                continue
            start_line = line
        if ch == rel and i + 1 < len(text):
            buf.append(ch)
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == seg:
            yield "".join(buf), start_line
            buf, start_line = [], None
        else:
            buf.append(ch)
        i += 1
    if buf and "".join(buf).strip():
        yield "".join(buf), start_line


def parse_segment(raw: str, una: dict, line: int, index: int) -> Segment:
    elems = _split_keep_release(raw, una["elem"], una["rel"])
    tag = elems[0].strip()
    elements = [[_unescape(c, una["rel"]) for c in _split_keep_release(e, una["comp"], una["rel"])] for e in elems[1:]]
    return Segment(tag=tag, elements=elements, line=line, index=index, raw=raw.strip())


def _split_keep_release(text: str, sep: str, rel: str) -> list[str]:
    """Split on sep but keep release sequences intact (unescaped later)."""
    out, cur, i = [], [], 0
    while i < len(text):
        ch = text[i]
        if ch == rel and i + 1 < len(text):
            cur.append(ch + text[i + 1])
            i += 2
            continue
        if ch == sep:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def _unescape(text: str, rel: str) -> str:
    return "".join(_split(text, "\x00", rel))


def parse(data: bytes | str) -> Interchange:
    if isinstance(data, bytes):
        text, encoding = decode(data)
    else:
        text, encoding = data, "str"
    text = text.lstrip("﻿")
    una = dict(DEFAULT_UNA)
    issues: list[dict] = []
    stripped = text.lstrip()
    if stripped.startswith("UNA"):
        spec = stripped[3:9]
        una = dict(zip(["comp", "elem", "dec", "rel", "rep", "seg"], spec))
        text = stripped[9:]

    unb = unz = None
    messages: list[Message] = []
    current: Message | None = None
    for raw, line in _segments(text, una):
        tag = raw.strip()[:3]
        if tag == "UNB":
            unb = parse_segment(raw, una, line, 0)
            continue
        if tag == "UNZ":
            unz = parse_segment(raw, una, line, 0)
            continue
        if tag in ("UNG", "UNE"):
            continue
        if tag == "UNH":
            seg = parse_segment(raw, una, line, 1)
            current = Message(
                ref=seg.get(1) or "",
                type=seg.get(2, 1) or "",
                version=((seg.get(2, 2) or "") + (seg.get(2, 3) or "")).upper(),
                agency=seg.get(2, 4) or "",
                assoc=seg.get(2, 5) or "",
                segments=[seg],
            )
            messages.append(current)
            continue
        if current is None:
            issues.append({"severity": "error", "code": "ENV-NO-UNH", "line": line,
                           "message": f"Segment {tag} mimo zprávu (chybí UNH)."})
            continue
        seg = parse_segment(raw, una, line, len(current.segments) + 1)
        current.segments.append(seg)
        if tag == "UNT":
            _check_unt(current, seg, issues)
            current = None

    if current is not None:
        issues.append({"severity": "error", "code": "ENV-NO-UNT", "line": current.segments[-1].line,
                       "message": f"Zpráva {current.ref} není ukončena segmentem UNT."})
    if unb is not None and unz is not None:
        cnt = unz.get(1)
        if cnt and cnt.isdigit() and int(cnt) != len(messages):
            issues.append({"severity": "error", "code": "ENV-UNZ-COUNT", "line": unz.line,
                           "message": f"UNZ uvádí {cnt} zpráv, nalezeno {len(messages)}."})
        if unz.get(2) != unb.get(5):
            issues.append({"severity": "error", "code": "ENV-UNZ-REF", "line": unz.line,
                           "message": f"Referenční číslo výměny v UNZ ({unz.get(2)}) neodpovídá UNB ({unb.get(5)})."})
    elif unb is not None and unz is None:
        issues.append({"severity": "warning", "code": "ENV-NO-UNZ", "line": None,
                       "message": "Výměna nemá segment UNZ."})
    charset = (unb.get(1, 1) if unb else None) or ""
    return Interchange(una=una, unb=unb, unz=unz, messages=messages, charset=charset,
                       encoding=encoding, issues=issues)


def _check_unt(msg: Message, unt: Segment, issues: list[dict]) -> None:
    cnt = unt.get(1)
    if cnt and cnt.isdigit() and int(cnt) != len(msg.segments):
        issues.append({"severity": "error", "code": "ENV-UNT-COUNT", "line": unt.line,
                       "message": f"UNT uvádí {cnt} segmentů, zpráva jich má {len(msg.segments)}."})
    if unt.get(2) != msg.ref:
        issues.append({"severity": "error", "code": "ENV-UNT-REF", "line": unt.line,
                       "message": f"Reference v UNT ({unt.get(2)}) neodpovídá UNH ({msg.ref})."})
