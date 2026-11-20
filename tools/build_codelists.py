"""Build msgvalidator/data/peppol/codelists.json from the OpenPEPPOL code lists
(structure/codelist/*.xml in peppol-bis-invoice-3).

Usage: python tools/build_codelists.py <path-to-peppol-bis-invoice-3 checkout>
"""
import json
import pathlib
import sys

from lxml import etree

NS = {"c": "urn:fdc:difi.no:2017:vefa:structure:CodeList-1"}
ALIASES = {"ISO3166-1_Alpha2": "ISO3166", "ISO4217_2015": "ISO4217", "VATEX": "vatex",
           "UNECERec20-11e": "UNECERec20", "eas": "EAS", "icd": "ICD"}


def main(root):
    out = {}
    for f in sorted((pathlib.Path(root) / "structure" / "codelist").glob("*.xml")):
        doc = etree.parse(str(f))
        codes = {c.findtext("c:Id", namespaces=NS).strip(): (c.findtext("c:Name", namespaces=NS) or "").strip()
                 for c in doc.findall(".//c:Code", NS)}
        out[ALIASES.get(f.stem, f.stem)] = {"title": doc.findtext("c:Title", namespaces=NS), "codes": codes}
    dst = pathlib.Path(__file__).resolve().parents[1] / "msgvalidator" / "data" / "peppol" / "codelists.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print({k: len(v["codes"]) for k, v in out.items()}, "->", dst)


if __name__ == "__main__":
    main(sys.argv[1])
