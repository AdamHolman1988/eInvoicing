"""Generate the EN 16931 / Peppol BIS 3 business-term catalogue from the official
OpenPEPPOL syntax binding (structure/syntax/ubl-invoice.xml + parts).

Usage: python tools/build_bt_catalog.py <path-to-peppol-bis-invoice-3 checkout>
Output: msgvalidator/data/peppol/bt_catalog.json
"""
import json
import pathlib
import sys

from lxml import etree

NS = "{urn:fdc:difi.no:2017:vefa:structure-1}"


def card(el):
    c = el.get("cardinality", "1..1")
    lo, hi = c.split("..")
    return int(lo), hi


def resolve(el, base):
    """Return children with <Include> expanded."""
    out = []
    for ch in el:
        if ch.tag == NS + "Include":
            inc = etree.parse(str(base / ch.text.strip())).getroot()
            out.append(inc)
        elif ch.tag in (NS + "Element", NS + "Attribute"):
            out.append(ch)
    return out


def walk(el, base, xpath, parent_bt, path_min, terms, order):
    term = el.findtext(NS + "Term")
    name = el.findtext(NS + "Name")
    lo, hi = card(el) if el.tag == NS + "Element" else (
        (1 if el.get("usage", "Mandatory") == "Mandatory" else 0), "1")
    xp = f"{xpath}/@{term}" if el.tag == NS + "Attribute" else f"{xpath}/{term}"
    # one element can carry several terms, e.g. "BG-20, BG-21" (allowance / charge share the UBL element)
    refs = [x.strip() for r in el.findall(NS + "Reference") if r.get("type") == "BUSINESS_TERM"
            for x in r.text.split(",") if x.strip()]
    rules = [r.text.strip() for r in el.findall(NS + "Reference") if r.get("type") == "RULE"]
    # minimum relative to the nearest BT/BG ancestor (container elements without a BT are transparent)
    eff_min = min(path_min, lo)
    parents = parent_bt if isinstance(parent_bt, list) else [parent_bt]
    names = [x.strip() for x in (name or "").split(",")]
    if len(names) != len(refs):
        names = [name] * len(refs)
    for n, ref in enumerate(refs):
        # pair "BT-92,BT-99" with parents "BG-20, BG-21" positionally
        par = parents[n] if len(parents) == len(refs) else parents[0]
        if ref not in terms:
            order.append(ref)
            terms[ref] = {
                "id": ref,
                "name": names[n],
                "kind": "BG" if ref.startswith("BG") else "BT",
                "parent": par,
                "min": eff_min,
                "max": hi,
                "xpath": xp,
                "datatype": el.findtext(NS + "DataType"),
                "rules": rules,
                "default": next((v.text for v in el.findall(NS + "Value") if v.get("type") == "DEFAULT"), None),
                "codelist": next((v.text for v in el.findall(NS + "Reference") if v.get("type") == "CODE_LIST"), None),
            }
    me = refs if refs else parent_bt
    for ch in resolve(el, base):
        walk(ch, base, xp, me, 1 if refs else eff_min, terms, order)


def main(root):
    base = pathlib.Path(root) / "structure" / "syntax"
    doc = etree.parse(str(base / "ubl-invoice.xml")).getroot().find(NS + "Document")
    terms, order = {}, []
    for ch in resolve(doc, base):
        walk(ch, base, "/ubl:Invoice", None, 1, terms, order)
    out = pathlib.Path(__file__).resolve().parents[1] / "msgvalidator" / "data" / "peppol" / "bt_catalog.json"
    out.write_text(json.dumps({"source": "OpenPEPPOL peppol-bis-invoice-3 structure/syntax/ubl-invoice.xml",
                               "terms": [terms[k] for k in order]}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(order)} terms -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
