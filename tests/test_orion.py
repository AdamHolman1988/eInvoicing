"""ORION XML INVOIC – detection, structure checks, mapping to BTs, virtual UBL. Synthetic data only."""
import pytest

from msgvalidator.detect import detect
from msgvalidator.orion import mapping, structure
from msgvalidator.orion.reader import read
from msgvalidator.report import html
from msgvalidator.semantic.catalog import catalog
from msgvalidator.validate import validate

# Fictitious parties / GLNs / GTINs (valid check digits).
ORION = """<?xml version="1.0" encoding="utf-8"?>
<orion_message>
  <header>
    <message_type>INVOIC</message_type>
    <version>3.1.3</version>
    <message_id>1</message_id>
    <creation_date>2026-10-01</creation_date>
    <creation_time>10:00</creation_time>
    <receiver>8590000000022</receiver>
    <sender>8590000000015</sender>
    <test_flag>1</test_flag>
  </header>
  <body>
    <message_header>
      <doc_number>FV2026001</doc_number>
      <doc_type>{doc_type}</doc_type>
      <doc_function>9</doc_function>
      <issue_date>{issue_date}</issue_date>
      <tax_date>2026-10-01</tax_date>
      <despatch_date></despatch_date>
      <due_date>2026-10-15</due_date>
      <payment_means>42</payment_means>
      <currency_code>CZK</currency_code>
      <order_number>OBJ-1</order_number>
      <free_text_1>Testovací faktura</free_text_1>
      {reverse}
      <party>
        <party_qualifier>SU</party_qualifier>
        <party_id>8590000000015</party_id>
        <party_name>Dodavatel Test s.r.o.</party_name>
        <street>Testovací 1</street>
        <place>Praha</place>
        <postcode>110 00</postcode>
        <country_code>CZ</country_code>
        <company_id>12345678</company_id>
        <tax_id>CZ12345678</tax_id>
        <account_number>123456789</account_number>
        <bank_code>0100</bank_code>
        <variable_symbol>2026001</variable_symbol>
      </party>
      <party>
        <party_qualifier>BY</party_qualifier>
        <party_id>8590000000022</party_id>
        <party_name>Odběratel Test a.s.</party_name>
        <street>Zkušební 2</street>
        <place>Brno</place>
        <postcode>602 00</postcode>
        <country_code>CZ</country_code>
        <company_id>87654321</company_id>
        <tax_id>CZ87654321</tax_id>
      </party>
      <party>
        <party_qualifier>DP</party_qualifier>
        <party_id>8590000000039</party_id>
        <party_name>Prodejna Test</party_name>
      </party>
    </message_header>
    <line_items>
      <item>
        <item_number>1</item_number>
        <article_gtin>8590000000107</article_gtin>
        <article_id_supplier>A-1</article_id_supplier>
        <article_name>Zboží A</article_name>
        <item_type>Z</item_type>
        <quantity>10</quantity>
        <net_price>10.00</net_price>
        <total_price>100.00</total_price>
        <vat_rate>21.00</vat_rate>
        <unit>PCE</unit>
      </item>
      <item>
        <item_number>2</item_number>
        <article_gtin>8590000000114</article_gtin>
        <article_name>Zboží B</article_name>
        <item_type>Z</item_type>
        <quantity>2</quantity>
        <net_price>25.00</net_price>
        <total_price>50.00</total_price>
        <vat_rate>12.00</vat_rate>
        <unit>KGM</unit>
      </item>
    </line_items>
    <summary>
      <price_invoiced>177.00</price_invoiced>
      <items_price>150.00</items_price>
      <taxable_amount>150.00</taxable_amount>
      <remains_unsettled>177.00</remains_unsettled>
      <tax_details>
        <vat><vat_group>0</vat_group><vat_basis>0.00</vat_basis><vat_rate>0.00</vat_rate><vat_total>0.00</vat_total></vat>
        <vat><vat_group>1</vat_group><vat_basis>50.00</vat_basis><vat_rate>12.00</vat_rate><vat_total>6.00</vat_total></vat>
        <vat><vat_group>2</vat_group><vat_basis>100.00</vat_basis><vat_rate>21.00</vat_rate><vat_total>21.00</vat_total></vat>
        <vat_total>27.00</vat_total>
      </tax_details>
    </summary>
  </body>
</orion_message>
"""


def make(doc_type="380", issue_date="2026-10-01", reverse="", **replace) -> bytes:
    xml = ORION.format(doc_type=doc_type, issue_date=issue_date, reverse=reverse)
    for old, new in replace.items():
        xml = xml.replace(old, new)
    return xml.encode("utf-8")


def first(ctx, bt):
    return ctx.values[bt][0]


def codes(findings):
    return {(f.code, f.bt) for f in findings}


def test_detect_orion_supported():
    d = detect(make())
    assert d.family == "XML-ORION" and d.message == "INVOIC" and d.version == "3.1.3" and d.supported


def test_header_values_to_bts():
    sem = read(make())
    d = sem.document
    assert first(d, "BT-1").value == "FV2026001" and first(d, "BT-1").line == 15
    assert first(d, "BT-2").value == "2026-10-01"
    assert first(d, "BT-3").value == "380" and sem.doc_kind == "Invoice"
    assert first(d, "BT-5").value == "CZK"
    assert first(d, "BT-13").value == "OBJ-1"
    assert first(d, "BT-22").value == "Testovací faktura"
    assert first(d, "BT-27").value == "Dodavatel Test s.r.o."  # SU party
    assert first(d, "BT-31").value == "CZ12345678"
    assert first(d, "BT-44").value == "Odběratel Test a.s."  # BY party
    assert first(d, "BT-48").value == "CZ87654321"
    assert first(d, "BT-70").value == "Prodejna Test"  # DP party
    assert first(d, "BT-83").value == "2026001"
    ep = first(d, "BT-34")
    assert (ep.value, ep.scheme, ep.how) == ("8590000000015", "0088", "derived")
    assert first(d, "BT-24").how == "const" and first(d, "BT-23").how == "const"
    assert "party[2]/party_name" in first(d, "BT-44").segment


def test_lines_and_vat_breakdown():
    sem = read(make())
    lines = sem.groups["BG-25"]
    assert [first(ln, "BT-126").value for ln in lines] == ["1", "2"]
    assert first(lines[0], "BT-157").scheme == "0160"
    unit = first(lines[0], "BT-130")
    assert (unit.value, unit.raw, unit.how) == ("H87", "PCE", "mapped")
    assert first(lines[1], "BT-130").value == "KGM"
    assert (first(lines[0], "BT-151").value, first(lines[0], "BT-151").how) == ("S", "derived")
    vat = sem.groups["BG-23"]
    assert [first(v, "BT-119").value for v in vat] == ["12.00", "21.00"]  # empty group 0 dropped
    assert all(first(v, "BT-118").value == "S" for v in vat)
    assert any(n["code"] == "ORION-EMPTY-VAT" for n in sem.notes)
    assert sem.repeating["BT-116"] == "BG-23" and sem.repeating["BT-131"] == "BG-25"


def test_missing_mandatory_field_reported():
    fs = structure.check(make(**{"<doc_number>FV2026001</doc_number>": "<doc_number></doc_number>",
                                 "<article_name>Zboží B</article_name>": ""}))
    missing = [f for f in fs if f.code == "ORION-MISSING"]
    assert any("doc_number" in f.message and f.line == 15 and f.severity == "error" for f in missing)
    assert any("article_name" in f.message and f.contexts == ["položka 2"] for f in missing)


def test_format_code_length_unknown():
    fs = structure.check(make(issue_date="01.10.2026", **{
        "<vat_group>1</vat_group>": "<vat_group>7</vat_group>",
        "<order_number>OBJ-1</order_number>": "<order_number>OBJ-1-TOO-LONG-NUMBER</order_number><foo>x</foo>",
        "<net_price>25.00</net_price>": "<net_price>25,00</net_price>"}))
    got = {(f.code, f.severity) for f in fs}
    assert ("ORION-FORMAT", "error") in got  # date 01.10.2026, number 25,00
    assert ("ORION-CODE", "error") in got  # VAT group 7 not in the closed list
    assert ("ORION-LENGTH", "warning") in got  # order number > 15 chars
    assert ("ORION-UNKNOWN", "warning") in got  # <foo>
    assert any(f.code == "ORION-FORMAT" and "25,00" in f.message and f.hint for f in fs)


def test_clean_message_has_no_structure_errors():
    fs = structure.check(make())
    assert not [f for f in fs if f.severity == "error"], [f.message for f in fs]
    # empty <despatch_date/> is tolerated (XSD would reject it) – reported as info only
    assert any(f.code == "ORION-XSD" and f.severity == "info" for f in fs)


def test_version_mismatch_info():
    data = make(**{"<version>3.1.3</version>": "<version>3.0.0</version>",
                   "</order_number>": "</order_number><orion_url>https://example.invalid/x</orion_url>"})
    fs = structure.check(data)
    assert any(f.code == "ORION-VERSION" and "orion_url" in f.message for f in fs)


def test_credit_note_and_code_mapping():
    sem = read(make(doc_type="83"))
    bt3 = first(sem.document, "BT-3")
    assert (bt3.value, bt3.raw, bt3.how) == ("381", "83", "mapped")
    assert sem.doc_kind == "CreditNote"


def test_reverse_charge_category():
    data = make(reverse="<reverse_charge>A</reverse_charge>")
    sem = read(data)
    assert {first(v, "BT-118").value for v in sem.groups["BG-23"]} == {"AE"}
    assert {first(v, "BT-121").value for v in sem.groups["BG-23"]} == {"VATEX-EU-AE"}
    assert first(sem.groups["BG-25"][0], "BT-151").value == "AE"


def test_validate_end_to_end_virtual_ubl_is_xsd_valid():
    rep = validate(make(), "orion.xml", ["peppol-bis3", "sk-cius", "billa-sk"])
    assert rep.detection.supported and not rep.envelope
    m = rep.messages[0]
    assert m.semantic is not None and m.virtual_xml
    assert m.rules_info["steps"][0][1] is True  # UBL 2.1 XSD
    assert ("GAP-DERIVED", "BT-151") in codes(m.gaps)
    assert ("GAP-MISSING", "BT-32") in codes(m.gaps)  # Billa: SK DIČ (vat_id) not sent
    assert not [f for f in m.rules if f.severity == "error"], [(f.code, f.message) for f in m.rules]
    assert "ORION XML – XSD + dokumentace" in html.render(rep)


def test_validate_reports_structure_errors():
    rep = validate(make(**{"<doc_type>380</doc_type>": "<doc_type></doc_type>"}), "orion.xml", ["peppol-bis3"])
    m = rep.messages[0]
    assert ("ORION-MISSING", None) in codes(m.structure)
    assert ("GAP-MISSING", "BT-3") in codes(m.gaps)


@pytest.mark.parametrize("bt", ["BT-1", "BT-2", "BT-3", "BT-27", "BT-44", "BT-112", "BT-116", "BT-131", "BT-153"])
def test_mapping_covers_core_terms(bt):
    mp = mapping()
    assert bt in mp["terms"]
    for r in mp["terms"][bt]:
        for fid in r.get("fields") or ([r["field"]] if "field" in r else []):
            assert fid in mp["by_id"]


def test_mapping_file_consistency():
    mp = mapping()
    cat = catalog()
    assert mp["version"] == "3.1.3"
    assert all(bt in cat for bt in mp["terms"])
    assert all(f["path"].startswith(("header/", "body/")) for f in mp["fields"])
    assert mp["by_id"]["SUMVAT01"]["group"] == "body/summary/tax_details/vat"
    assert mp["by_id"]["LIN1"]["mandatory"] == "yes" and mp["by_id"]["HDR1"]["bts_doc"] == ["BT-1"]


def test_service_line_without_gtin_is_warning_for_billa():
    sem = read(make())
    assert [ln.aux["item_type"].value for ln in sem.groups["BG-25"]] == ["Z", "Z"]
    service = make(**{"<article_gtin>8590000000114</article_gtin>": "",
                      "<article_name>Zboží B</article_name>\n        <item_type>Z</item_type>":
                      "<article_name>Zboží B</article_name>\n        <item_type>S</item_type>"})
    m = validate(service, "orion.xml", ["billa-sk"], virtual_rules=False).messages[0]
    gtin = [f for f in m.gaps if f.bt == "BT-157"]
    assert [(f.severity, f.code, f.contexts) for f in gtin] == [("warning", "GAP-SERVICE", ["řádek 2"])]
    assert "typ položky S" in gtin[0].message


def test_goods_line_without_gtin_stays_error():
    goods = make(**{"<article_gtin>8590000000114</article_gtin>": ""})
    m = validate(goods, "orion.xml", ["billa-sk"], virtual_rules=False).messages[0]
    assert ("error", "GAP-MISSING") in {(f.severity, f.code) for f in m.gaps if f.bt == "BT-157"}
