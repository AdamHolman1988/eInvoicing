"""XRechnung 3.0 requirement profile from the official KoSIT schematron (BR-DE rules).

    python tools/import_xrechnung_profile.py

Reads the BR-DE assertion texts of data/rules/xrechnung/resources/xrechnung/<ver>/xsl/XRechnung-UBL-validation.xsl:
  "Das Element "…" (BT-x) muss übermittelt werden."                  -> required
  "Die Gruppe "…" (BG-x) muss übermittelt werden." / "muss Angaben zu … (BG-x) enthalten" -> required
  "… (BT-x) muss übermittelt werden, wenn die Gruppe … (BG-y) …"   -> required inside the (optional) group
The base is the EN 16931 core cardinality (profile peppol-bis3 = same syntax binding); XRechnung only makes
requirements stricter, e.g. BT-10 Buyer reference is mandatory (Peppol accepts BT-13 instead).
"""
import html
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "msgvalidator" / "data"
XSL = sorted((ROOT / "rules" / "xrechnung" / "resources" / "xrechnung").glob("*/xsl/XRechnung-UBL-validation.xsl"))[-1]
OUT = ROOT / "profiles" / "xrechnung.json"



def main():
    text = html.unescape(XSL.read_text(encoding="utf-8"))
    rules = {}
    for m in re.finditer(r"\[(BR-DE-[0-9]+(?:-[a-z])?)\]([^<]*)", text):
        rules.setdefault(m.group(1), " ".join(m.group(2).split()))
    req = {}

    def add(term, rid, msg, level="required"):
        r = req.setdefault(term, {"level": level, "note": f"{rid}: {msg}", "rules": []})
        r["rules"].append(rid)

    for rid, msg in sorted(rules.items()):
        terms = re.findall(r"\((B[TG]-\d+)\)", msg)
        if not terms:
            continue
        if re.search(r"muss übermittelt werden\.?$", msg) and "wenn" not in msg:
            add(terms[0], rid, msg)
        elif "muss Angaben zu" in msg and "enthalten" in msg:
            add(terms[0], rid, msg)
        elif re.search(r"muss übermittelt werden, wenn die Gruppe", msg):
            add(terms[0], rid, msg)  # applicability inside the optional group is handled by the checker
    # BR-DE-15 makes BT-10 mandatory without the Peppol alternative (BT-13)
    if "BT-10" in req:
        req["BT-10"]["unless"] = []
    out = {
        "id": "xrechnung",
        "name": "XRechnung 3.0 (DE)",
        "description": f"Německá CIUS: jádro EN 16931 + povinná pravidla BR-DE (KoSIT, {XSL.parent.parent.name}). "
                       "Oficiální pravidla běží nad dokumentem jako XRechnung.",
        "source": str(XSL.relative_to(ROOT)).replace("\\", "/"),
        "extends": ["peppol-bis3"],
        "rules": "xrechnung",
        "requirements": dict(sorted(req.items(), key=lambda kv: (kv[0][:2], int(kv[0][3:])))),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT.name}: {len(req)} požadavků z {len(rules)} pravidel BR-DE ({XSL.parent.parent.name})")
    for k, v in out["requirements"].items():
        print(" ", k, v["rules"])


if __name__ == "__main__":
    main()
