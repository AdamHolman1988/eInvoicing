"""EN 16931 syntax binding for UN/CEFACT CII (BT/BG -> XPath) from the KoSIT XRechnung visualization.

    python -I tools/build_cii_binding.py <path>/xsl/cii-xr.xsl [release tag]

The stylesheet is only *read*: every template `mode="BT-n"` / `mode="BG-n"` has an absolute `match` pattern on the
CII instance, which is exactly the syntax binding. Output: msgvalidator/data/peppol/cii_binding.json
(used by msgvalidator/cii/reader.py). Source: https://github.com/itplr-kosit/xrechnung-visualization (Apache 2.0).
"""
import json
import pathlib
import re
import sys

from lxml import etree

XSL = "http://www.w3.org/1999/XSL/Transform"
OUT = pathlib.Path(__file__).resolve().parents[1] / "msgvalidator" / "data" / "peppol" / "cii_binding.json"
PREFIXES = {"rsm", "ram", "qdt", "udt"}


def xpath1(m: str) -> str:
    """The few XPath 2.0 constructs used in the patterns -> XPath 1.0 (lxml)."""
    m = re.sub(r"exists\(([^()]+)\)", r"\1", m)
    m = re.sub(r"empty\(([^()]+)\)", r"not(\1)", m)
    # general comparison with a sequence: @x=('A', 'B') -> (@x='A' or @x='B')
    m = re.sub(r"(@\w+)\s*=\s*\(([^()]+)\)",
               lambda g: "(" + " or ".join(f"{g.group(1)}={v.strip()}" for v in g.group(2).split(",")) + ")", m)
    return m


def main(src: str, tag: str = ""):
    root = etree.parse(src).getroot()
    terms: dict[str, list[str]] = {}
    groups: dict[str, list[str]] = {}
    odd = []
    for t in root.iter(f"{{{XSL}}}template"):
        mode, match = t.get("mode") or "", t.get("match")
        if not match or not re.fullmatch(r"B[GT]-\d+", mode):
            continue
        m = xpath1(" ".join(match.split()))
        if not m.startswith("/rsm:CrossIndustryInvoice") or re.search(r"\b(exists|matches|tokenize|string-join)\(", m):
            odd.append((mode, m))
            continue
        (terms if mode.startswith("BT") else groups).setdefault(mode, [])
        dest = (terms if mode.startswith("BT") else groups)[mode]
        if m not in dest:
            dest.append(m)
    ns = {k: v for k, v in root.nsmap.items() if k in PREFIXES}
    OUT.write_text(json.dumps({"source": "KoSIT xrechnung-visualization cii-xr.xsl", "release": tag, "namespaces": ns,
                               "groups": groups, "terms": terms}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(OUT, len(terms), "BT,", len(groups), "BG;", "skipped:", odd)


if __name__ == "__main__":
    main(*sys.argv[1:3])
