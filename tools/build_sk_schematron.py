"""Generate the Slovak CIUS Schematron (SK-CIUS-UBL.sch) and compile it with SchXslt2.

    python tools/build_sk_schematron.py [--cache DIR]

Input (all in the repo, the analyst spreadsheet is NOT needed at build time):
    msgvalidator/data/profiles/sk-cius.json   SK transposition v1.13 (tools/import_profiles.py sk <xlsx>)
    msgvalidator/data/peppol/bt_catalog.json  BT/BG catalogue with UBL XPaths (tools/build_bt_catalog.py)

Output:
    msgvalidator/data/rules/peppol/resources/sk/SK-CIUS-UBL.sch    ISO Schematron, queryBinding xslt2
    msgvalidator/data/rules/peppol/resources/sk/SK-CIUS-UBL.xslt   compiled with SchXslt2 (as Peppol .sch)

The Schematron runs as an extra step of the "Peppol BIS Billing 3.0 + SK CIUS" scenarios in
tools/templates/peppol-scenarios.xml (selected when seller or buyer country is SK).

Rules generated
---------------
1. Mechanical (flag="fatal"): every BT the SK transposition marks "vyžaduje sa" whose Peppol cardinality
   inside its parent group is 0..1 and that no CEN/Peppol rule already makes mandatory (PEPPOL_ENFORCED).
   The rule context is the BT's parent group, so the assert fires once per group instance and only when
   the group is present (e.g. seller/buyer postal address BG-5/BG-8).
2. "podmienene vyžadované" whose condition is just "the parent group is present" (GROUP_CONDITION):
   generated like 1. with flag="fatal".
3. Other "podmienene vyžadované" (CONDITIONAL): the condition is not mechanically decidable (e.g. "if the
   company has an IČO assigned"), so the assert is flag="warning" and its text quotes the SK condition.
4. Rules from the sheets "UBL Pravidlá" / "Obchodné pravidlá (legisl)" that are not enforced by the
   CEN 1.3.17 / Peppol 3.0.21 artefacts (EXTRA_RULES). Both sheets are Slovak translations of EN 16931
   rules; there are no SK-specific rule ids. Only BR-66, BR-67 and BR-CO-25 (removed from the current
   CEN artefacts) are missing from what we already run; they are re-instated here as SK-CIUS-BR-*.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import tempfile
from xml.sax.saxutils import escape, quoteattr

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / "msgvalidator" / "data" / "profiles" / "sk-cius.json"
CATALOG = ROOT / "msgvalidator" / "data" / "peppol" / "bt_catalog.json"
OUT_DIR = ROOT / "msgvalidator" / "data" / "rules" / "peppol" / "resources" / "sk"
SCH_NAME = "SK-CIUS-UBL"

NS = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

# SK-required terms that are optional by Peppol cardinality (or not in the catalogue), but already made
# mandatory by a CEN/Peppol rule we run anyway – no duplicate SK rule.
PEPPOL_ENFORCED = {
    "BG-23": "BR-CO-18 (aspoň jedno rozdelenie DPH)",
    "BT-34-1": "BR-62 (schemeID elektronickej adresy predávajúceho)",
    "BT-49-1": "BR-63 (schemeID elektronickej adresy kupujúceho)",
    "BT-125": "riadky xlsx = @mimeCode / @filename prílohy – UBL-DT-06 / UBL-DT-07",
    "BT-157": "riadok xlsx = identifikátor schémy (BT-157-1) – BR-64",
    "BT-158": "riadok xlsx = identifikátor schémy (BT-158-1) – BR-65",
    "BT-119": "BR-48 (sadzba povinná okrem kategórie O)",
}

# conditional terms whose SK condition is exactly "the parent group is present"
GROUP_CONDITION = {"BT-64", "BT-66", "BT-67"}  # "vyžaduje sa iba v prípade, ak sa transakcie zúčastňuje daňový zástupca"

SUP = "cac:AccountingSupplierParty/cac:Party"
BUY = "cac:AccountingCustomerParty/cac:Party"
VAT_TS = "cac:PartyTaxScheme[normalize-space(cac:TaxScheme/cbc:ID) = 'VAT']/cbc:CompanyID"
LINE = "cac:InvoiceLine"  # translated to cac:CreditNoteLine for CreditNote

# conditional terms that cannot be decided mechanically -> flag="warning" with the SK condition text.
# context is relative to the document root ('' = root); test is evaluated in that context.
CONDITIONAL = {
    "BT-6": ("", "normalize-space(cbc:DocumentCurrencyCode) = 'EUR' or exists(cbc:TaxCurrencyCode)",
             "ak sa mena faktúry líši od meny, v ktorej sa účtuje DPH (v SR EUR), uvádza sa Kód účtovnej meny DPH"),
    "BT-7": ("", "exists(cbc:TaxPointDate) or exists(cac:InvoicePeriod) or exists(cac:Delivery/cbc:ActualDeliveryDate)",
             "uvádza sa, ak je dátum dodania/prijatia platby známy a líši sa od dátumu vystavenia (BT-2); "
             "faktúra neobsahuje žiadny údaj o dátume dodania (BT-7, BG-14, BT-72)"),
    "BT-30": (SUP, "exists(cac:PartyLegalEntity/cbc:CompanyID)", "vyžaduje sa, ak bolo IČO subjektu pridelené"),
    "BT-30-1": (f"{SUP}/cac:PartyLegalEntity/cbc:CompanyID", "exists(@schemeID)", "vyžaduje sa, ak bolo IČO subjektu pridelené"),
    "BT-31": (SUP, f"exists({VAT_TS})", "vyžaduje sa, ak bolo IČ DPH subjektu pridelené"),
    "BT-33": (SUP, "exists(cac:PartyLegalEntity/cbc:CompanyLegalForm)",
              "§ 3a Obchodného zákonníka: právna forma, register a číslo zápisu"),
    "BT-47": (BUY, "exists(cac:PartyLegalEntity/cbc:CompanyID)", "vyžaduje sa, ak bolo IČO subjektu pridelené"),
    "BT-47-1": (f"{BUY}/cac:PartyLegalEntity/cbc:CompanyID", "exists(@schemeID)", "vyžaduje sa, ak bolo IČO subjektu pridelené"),
    "BT-48": (BUY, f"exists({VAT_TS})", "vyžaduje sa, ak bolo IČ DPH subjektu pridelené"),
    "BT-120": ("cac:TaxTotal/cac:TaxSubtotal[normalize-space(cac:TaxCategory/cbc:ID) = ('E', 'AE', 'K', 'G', 'O')]",
               "normalize-space(cac:TaxCategory/cbc:TaxExemptionReason) != ''",
               "§ 74 ods. 1 písm. h) a k): pri oslobodení / prenesení daňovej povinnosti sa uvádza slovná informácia "
               "(kód BT-121 nestačí)"),
    "BT-148": (f"{LINE}/cac:Price/cac:AllowanceCharge", "exists(cbc:BaseAmount)",
               "ak sa uvádza zľava z ceny za položku (BT-147), uvádza sa aj cena za položku brutto (BT-148)"),
}

# rules from "UBL Pravidlá" / "Obchodné pravidlá (legisl)" not enforced by CEN 1.3.17 / Peppol 3.0.21
EXTRA_RULES = [
    ("BR-66", "fatal", "", "count(cac:PaymentMeans/cac:CardAccount) <= 1",
     "Faktúra musí obsahovať maximálne jeden účet platobnej karty (BG-18)."),
    ("BR-67", "fatal", "", "count(cac:PaymentMeans/cac:PaymentMandate) <= 1",
     "Faktúra musí obsahovať maximálne jeden mandát na platbu (BG-19)."),
    # Context "Faktúra" (sheet "Obchodné pravidlá (legisl)"): applies to ubl:Invoice only, never to a
    # CreditNote, whose positive PayableAmount is money owed TO the buyer (advisor review 2026-11-02).
    ("BR-CO-25", "fatal", "",
     "exists(self::cn:CreditNote) or "
     "not(xs:decimal(cac:LegalMonetaryTotal/cbc:PayableAmount) > 0) or exists(cbc:DueDate) "
     "or exists(cac:PaymentMeans/cbc:PaymentDueDate) or normalize-space(string-join(cac:PaymentTerms/cbc:Note, '')) != ''",
     "V prípade, že je Splatná suma na úhradu (BT-115) kladná, musí byť uvedený Dátum splatnosti (BT-9) "
     "alebo Platobné podmienky (BT-20)."),
]


def load() -> tuple[dict, dict]:
    prof = json.loads(PROFILE.read_text(encoding="utf-8"))
    cat = {t["id"]: t for t in json.loads(CATALOG.read_text(encoding="utf-8"))["terms"]}
    return prof, cat


def rel(xpath: str) -> str:
    """'/ubl:Invoice/cac:X/cbc:Y' -> 'cac:X/cbc:Y' (relative to the document element)."""
    assert xpath.startswith("/ubl:Invoice"), xpath
    return xpath[len("/ubl:Invoice"):].lstrip("/")


def context_pattern(path: str) -> str:
    """Relative path under the root -> XSLT pattern matching it in Invoice and CreditNote."""
    if not path:
        return "/ubl:Invoice | /cn:CreditNote"
    cn = path.replace("cac:InvoiceLine", "cac:CreditNoteLine").replace("cbc:InvoicedQuantity", "cbc:CreditedQuantity")
    return f"/ubl:Invoice/{path} | /cn:CreditNote/{cn}"


def relative_test(group_path: str, term_path: str) -> str:
    assert term_path.startswith(group_path), (group_path, term_path)
    return term_path[len(group_path):].lstrip("/")


def collect(prof: dict, cat: dict) -> tuple[list[dict], list[tuple[str, str]]]:
    """-> (rules, skipped[(id, reason)])."""
    rules, skipped = [], []
    for tid, req in prof["requirements"].items():
        level = req["level"]
        if level == "optional":
            continue
        name = req.get("name_sk") or (cat.get(tid) or {}).get("name") or tid
        note = req.get("note")
        if tid in PEPPOL_ENFORCED:
            skipped.append((tid, "už vynucuje Peppol/CEN: " + PEPPOL_ENFORCED[tid]))
            continue
        if level == "conditional" and tid in CONDITIONAL:
            ctx, test, cond = CONDITIONAL[tid]
            rules.append(dict(id=f"SK-CIUS-{tid}", flag="warning", context=ctx, test=test,
                              text=f"{name} ({tid}) chýba – podmienene vyžadované: {cond}."))
            continue
        term = cat.get(tid)
        if term is None:
            skipped.append((tid, "nie je v katalógu BT/BG Peppol (bez vlastného XPath)"))
            continue
        if level == "conditional" and tid not in GROUP_CONDITION:
            skipped.append((tid, f"podmienka nie je strojovo overiteľná: {note}"))
            continue
        if term["min"] >= 1:
            continue  # mandatory in Peppol whenever its parent group is present
        if term["kind"] != "BT":
            skipped.append((tid, "skupina BG – povinnosť pokrývajú jej BT"))
            continue
        group = cat[term["parent"]] if term["parent"] else None
        gpath = rel(group["xpath"]) if group else ""
        test = relative_test(gpath, rel(term["xpath"]))
        why = (f"podmienene vyžadované: {note.rstrip('.')}" if level == "conditional"
               else "vyžaduje sa" + (f", {note}" if note else ""))
        where = f" v {group['id']}" if group else ""
        rules.append(dict(id=f"SK-CIUS-{tid}", flag="fatal", context=gpath,
                          test=f"normalize-space(string-join({test}, '')) != ''" if not test.startswith("@") else f"exists({test})",
                          text=f"Chýba {name} ({tid}){where} – SK CIUS: {why}."))
    for rid, flag, ctx, test, text in EXTRA_RULES:
        rules.append(dict(id=f"SK-CIUS-{rid}", flag=flag, context=ctx, test=test, text=f"{text} (SK CIUS: {rid})"))
    return rules, skipped


def render(rules: list[dict], prof: dict) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           "<!-- GENERATED by tools/build_sk_schematron.py – do not edit by hand.",
           f"     Source: {escape(prof.get('source', ''))} ({escape(prof.get('description', ''))}) -->",
           '<schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">',
           "  <title>SK CIUS – Slovak national requirements on top of Peppol BIS Billing 3.0 (UBL)</title>"]
    for p, uri in NS.items():
        out.append(f'  <ns prefix="{p}" uri="{uri}"/>')
    out.append('  <ns prefix="xs" uri="http://www.w3.org/2001/XMLSchema"/>')
    by_ctx: dict[str, list[dict]] = {}
    for r in rules:
        by_ctx.setdefault(r["context"], []).append(r)
    # one pattern per context: a node must not be swallowed by an earlier rule of the same pattern
    for i, (ctx, rs) in enumerate(by_ctx.items(), 1):
        out.append(f'  <pattern id="sk-{i}">')
        out.append(f"    <rule context={quoteattr(context_pattern(ctx))}>")
        for r in rs:
            out.append(f'      <assert id="{r["id"]}" flag="{r["flag"]}" test={quoteattr(r["test"])}>'
                       f'[{r["id"]}]-{escape(r["text"])}</assert>')
        out.append("    </rule>")
        out.append("  </pattern>")
    out.append("</schema>")
    return "\n".join(out) + "\n"


def build(out_dir: pathlib.Path, transpile: pathlib.Path | None) -> pathlib.Path:
    prof, cat = load()
    rules, skipped = collect(prof, cat)
    out_dir.mkdir(parents=True, exist_ok=True)
    sch = out_dir / f"{SCH_NAME}.sch"
    sch.write_text(render(rules, prof), encoding="utf-8", newline="\n")
    print(f"{sch.name}: {len(rules)} asserts "
          f"({sum(r['flag'] == 'fatal' for r in rules)} fatal, {sum(r['flag'] == 'warning' for r in rules)} warning)")
    for tid, why in skipped:
        print(f"  skipped {tid}: {why}")
    if transpile is not None:
        from saxonche import PySaxonProcessor
        with PySaxonProcessor(license=False) as proc:
            exe = proc.new_xslt30_processor().compile_stylesheet(stylesheet_file=str(transpile))
            exe.transform_to_file(source_file=str(sch), output_file=str(out_dir / f"{SCH_NAME}.xslt"))
        print("compiled ->", out_dir / f"{SCH_NAME}.xslt")
    return sch


def main(cache: pathlib.Path) -> None:
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import update_rules  # noqa: E402 – shares the pinned SchXslt2 download

    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        update_rules.fetch(update_rules.VERSIONS["schxslt2"]["url"], cache).extractall(pathlib.Path(tmp))
        build(OUT_DIR, next(pathlib.Path(tmp).rglob("transpile.xsl")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(pathlib.Path(tempfile.gettempdir()) / "msgvalidator-rules-cache"))
    main(pathlib.Path(ap.parse_args().cache))
