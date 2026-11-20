"""Extract message structure (full UN/EDIFACT + GS1 CZ subset) and example messages
from an EDITEL / GS1 Czech Republic INVOIC MIG (PDF or pre-extracted text).

Usage: python tools/parse_mig.py <MIG.pdf|MIG.txt> <VERSION e.g. D96A>
Outputs:
  msgvalidator/data/edifact/INVOIC_<VERSION>.json   structure (full + subset)
  tests/samples/edifact/mig_<version>_example<N>.edi  example messages from chapter 6
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

GROUP_RE = re.compile(r"^(\d{4})\s+(?:[X*]\s+)?─+\s*Segment group (\d+)\s*─+\s*([MC])\s+(\d+)─*┐(│*)")
SEG_RE = re.compile(r"^(\d{4})\s+(?:[X*]\s+)?([A-Z]{3})\s+(.+?)\s+([MC])\s+(\d+)\s*([─┘┴│\s]*)$")


def read_text(path: pathlib.Path) -> str:
    if path.suffix.lower() == ".pdf":
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    return path.read_text(encoding="utf-8")


def parse_chart(lines):
    root = {"children": []}
    stack = [root]
    for raw in lines:
        line = raw.rstrip()
        m = GROUP_RE.match(line)
        if m:
            pos, num, st, rep, tail = m.groups()
            depth = len(tail)
            while len(stack) - 1 > depth:
                stack.pop()
            grp = {"group": f"SG{num}", "pos": pos, "status": st, "max": int(rep), "children": []}
            stack[-1]["children"].append(grp)
            stack.append(grp)
            continue
        m = SEG_RE.match(line)
        if m:
            pos, tag, name, st, rep, tail = m.groups()
            stack[-1]["children"].append({"tag": tag, "pos": pos, "name": name.strip(), "status": st, "max": int(rep)})
            for _ in range(tail.count("┘") + tail.count("┴")):
                if len(stack) > 1:
                    stack.pop()
    return root["children"]


def section(lines, start_pat, end_pat):
    out, on = [], False
    for ln in lines:
        if not on and re.match(start_pat, ln):
            on = True
            continue
        if on and re.match(end_pat, ln):
            break
        if on:
            out.append(ln)
    return out


def examples(text):
    # Example messages: from "UNA:" (or UNB+) up to the UNZ segment, page furniture removed.
    junk = re.compile(r"^(=====PAGE|Zpráva INVOIC|Implementační příručka|© EDITEL|Verze \d)")
    body = text[text.find("\n6. Příklady zprávy"):]
    res = []
    for m in re.finditer(r"(UNA:\+\.\? '|UNB\+).*?UNZ\+[^']*'", body, re.S):
        segs = [ln.strip() for ln in m.group(0).splitlines() if ln.strip() and not junk.match(ln.strip())]
        res.append("\n".join(segs) + "\n")
    return res


SEG_HEAD = re.compile(r"^([A-Z]{3}) - [MC] \d")
SG_HEAD = re.compile(r"^(SG\d+) - [MC] ")
ELEM = re.compile(r"^(\d{4}|C\d{3}) ")
CODE = re.compile(r"[“„\"]([^”“\"]{1,6})[”“\"]\s*=")
JUNK = re.compile(r"^(=====PAGE|Zpráva INVOIC|Implementační příručka|© EDITEL|Verze \d|EDIFACT Stat|Function :|Segment number|[A-Z]{3}(-[A-Z0-9]+)+|SG\d+-|\S*-SG\d+)")


def qualifiers(lines):
    """Allowed codes of the first simple data element of each segment, keyed '<innermost SG>/<TAG>'.

    Chapter 3 of the MIG prints every segment usage preceded by its segment-group heading(s); the codes
    are listed as “X” = description right after the first data element (the qualifier).
    """
    result: dict[str, set] = {}
    for i, ln in enumerate(lines):
        m = SEG_HEAD.match(ln)
        if not m:
            continue
        tag = m.group(1)
        sg = ""
        j = i - 1
        while j >= 0 and (SG_HEAD.match(lines[j]) or JUNK.match(lines[j]) or not lines[j].strip()):
            g = SG_HEAD.match(lines[j])
            if g:
                sg = g.group(1)
                break
            j -= 1
        codes, on = set(), False
        for k in range(i + 1, min(i + 80, len(lines))):
            ln2 = lines[k]
            if SEG_HEAD.match(ln2) or ln2.startswith("Poznámky k segmentu"):
                break
            e = ELEM.match(ln2)
            if e:
                if on:
                    break
                if not e.group(1).startswith("C"):
                    on = True
            if on:
                codes.update(c.strip() for c in CODE.findall(ln2))
        if codes:
            result.setdefault(f"{sg}/{tag}", set()).update(codes)
    return {k: sorted(v) for k, v in sorted(result.items())}


def main(src, version):
    text = read_text(pathlib.Path(src))
    lines = text.splitlines()
    full = parse_chart(section(lines, r"^2\.1 Struktura kompletní", r"^2\.2 Subset"))
    subset = parse_chart(section(lines, r"^2\.2 Subset", r"^3\. Rozvržení"))
    quals = qualifiers(section(lines, r"^3\. Rozvržení", r"^4\. Obálka"))
    out = ROOT / "msgvalidator" / "data" / "edifact" / f"INVOIC_{version}.json"
    out.write_text(json.dumps({"message": "INVOIC", "version": version, "source": pathlib.Path(src).name,
                               "full": full, "subset": subset, "qualifiers": quals},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    print("structure ->", out)
    for i, ex in enumerate(examples(text), 1):
        p = ROOT / "tests" / "samples" / "edifact" / f"mig_{version.lower()}_example{i}.edi"
        p.write_text(ex, encoding="utf-8")
        print("example  ->", p.name, len(ex.splitlines()), "segments")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2].upper())
