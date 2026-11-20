"""ODHAD mapování neznámého XML: návrh klientského mapování z názvů polí, rolí a tvaru hodnot."""
import pathlib

import pytest

from msgvalidator import idoc
from msgvalidator.guess import guess, name_score, norm
from msgvalidator.guess.shapes import date_format, kinds
from msgvalidator.idoc import editor
from msgvalidator.idoc import mapping as idoc_mapping
from msgvalidator.report import html
from msgvalidator.validate import validate

S = pathlib.Path(__file__).parent / "samples" / "guess"
CZ = (S / "cz_faktura.xml").read_bytes()
EN = (S / "en_invoice.xml").read_bytes()

CZ_EXPECTED = {
    ("doc", "BT-1"): "CisloFaktury", ("doc", "BT-2"): "DatumVystaveni", ("doc", "BT-9"): "DatumSplatnosti",
    ("doc", "BT-7"): "DUZP", ("doc", "BT-5"): "Mena", ("doc", "BT-13"): "CisloObjednavky", ("doc", "BT-83"): "VariabilniSymbol",
    ("doc", "BT-27"): "Nazev", ("doc", "BT-31"): "DIC", ("doc", "BT-30"): "ICO", ("doc", "BT-29"): "GLN",
    ("doc", "BT-44"): "Nazev", ("doc", "BT-48"): "DIC", ("doc", "BT-47"): "ICO", ("doc", "BT-84"): "Ucet",
    ("doc", "BT-109"): "CelkemBezDPH", ("doc", "BT-110"): "DPHCelkem", ("doc", "BT-112"): "CelkemSDPH",
    ("line", "BT-126"): "Poradi", ("line", "BT-153"): "Popis", ("line", "BT-129"): "Mnozstvi", ("line", "BT-130"): "MJ",
    ("line", "BT-146"): "CenaMJ", ("line", "BT-131"): "CenaCelkem", ("line", "BT-152"): "SazbaDPH", ("line", "BT-157"): "EAN",
    ("vat", "BT-119"): "Sazba", ("vat", "BT-116"): "Zaklad", ("vat", "BT-117"): "DPH",
}


def _g(data):
    return guess(idoc.parse(data).messages[0])


def test_shapes():
    assert date_format("3.11.2026") == "dmy" and date_format("2026-11-03") == "iso" and date_format("20261103") == "102"
    assert date_format("31.02.2026") is None
    assert {"num", "comma"} <= kinds("1 512,50") and "rate" in kinds("21")
    assert "iban" in kinds("CZ6508000000192000145399") and "iban" not in kinds("CZ6508000000192000145398")
    assert "vatid" in kinds("SK2020123456") and "vatid" not in kinds("Musterstrasse 5")
    assert "gln" in kinds("8594000000006") and "gln" not in kinds("8594000000004")
    assert norm("Datum vystavení") == norm("datum_vystaveni") == "datumvystaveni"
    assert name_score("datumvystaveni", {"datumvystaveni"})[0] == 1.0


def test_czech_custom_xml():
    g = _g(CZ)
    assert g.groups["BG-25"]["path"] == ("Doklad", "Polozky", "Polozka") and g.groups["BG-25"]["count"] == 2
    assert g.groups["BG-23"]["path"] == ("Doklad", "RekapitulaceDPH")
    got = {(p.level, p.bt): p for p in g.proposals}
    for key, fld in CZ_EXPECTED.items():
        assert key in got and got[key].field.name == fld, (key, got.get(key) and got[key].field.label)
    assert got[("doc", "BT-27")].field.path[-1] == "Dodavatel" and got[("doc", "BT-44")].field.path[-1] == "Odberatel"
    assert got[("doc", "BT-2")].rule["date"] == "dmy" and got[("line", "BT-131")].rule["decimal"] == ","
    assert got[("line", "BT-130")].rule["map"] == {"ks": "H87"}
    assert got[("doc", "BT-81")].rule["derive"] == "payment_means_from_account_at"  # from the IBAN
    assert got[("doc", "BT-3")].rule["const"] == "380" and got[("doc", "BT-3")].confidence < 0.6
    assert g.confidence > 0.85 and not g.unused


def test_english_erp_xml():
    g = _g(EN)
    got = {(p.level, p.bt): p.field.label if p.field else None for p in g.proposals}
    assert got[("doc", "BT-1")] == "ErpInvoice / InvoiceNo"
    assert got[("doc", "BT-31")] == "ErpInvoice > Seller / VatNumber"
    assert got[("doc", "BT-48")] == "ErpInvoice > BillTo / VatNumber"
    assert got[("doc", "BT-84")] == "ErpInvoice > Bank / IBAN" and got[("doc", "BT-86")] == "ErpInvoice > Bank / BIC"
    assert got[("line", "BT-146")] == "ErpInvoice > Lines > Line / UnitPrice"
    assert got[("doc", "BT-49")] == "ErpInvoice > BillTo / VatNumber"  # SK endpoint derived from the SK VAT id
    assert "BG-23" not in g.groups  # the format has no VAT breakdown


def test_validate_reads_guessed_values():
    rep = validate(CZ, "f.xml", ["peppol-bis3"], virtual_rules=False)
    m = rep.messages[0]
    assert rep.envelope[0].code == "FMT-GUESSED" and "ODHAD" in m.label and m.guess["proposals"]
    d = {bt: vs[0].value for bt, vs in m.semantic.document.values.items()}
    assert d["BT-2"] == "2026-11-03" and d["BT-112"] == "1512.50" and d["BT-31"] == "CZ12345678"
    lines = m.semantic.groups["BG-25"]
    assert [c.values["BT-131"][0].value for c in lines] == ["1000.00", "250.00"]
    assert lines[0].values["BT-130"][0].value == "H87"
    assert not [f for f in m.gaps if f.code == "GAP-NOT-IN-FORMAT"]  # guessed: 'not found', not 'not carried'
    assert any(f.code == "GAP-NOT-GUESSED" and f.bt == "BT-49" for f in m.gaps)
    page = html.render(rep)
    assert "ODHAD" in page and "Odhad mapování" in page


def test_guessed_rules_pass_peppol_for_complete_file():
    rep = validate(CZ, "f.xml", ["peppol-bis3"])
    errs = [f.code for f in rep.messages[0].rules if f.severity == "error"]
    assert errs == ["PEPPOL-EN16931-R010"]  # only the buyer electronic address really is missing


@pytest.fixture
def mapdir(tmp_path, monkeypatch):
    monkeypatch.setenv("MSGVALIDATOR_MAPPINGS", str(tmp_path))
    return tmp_path


def test_editor_prefilled_and_saved_becomes_learned(mapdir):
    o = editor.open_file(CZ, ["peppol-bis3"])
    assert o["guess"] and o["client"]["terms"]["BT-1"] and o["client"]["groups"]["BG-25"]
    client = {**o["client"], "name": "Klient Doklad"}
    idoc_mapping.save_client(client)
    rep = validate(CZ, "f.xml", ["peppol-bis3"], virtual_rules=False)
    m = rep.messages[0]
    assert m.guess is None and "Klient Doklad" in m.label and "FMT-GUESSED" not in [f.code for f in rep.envelope]
    assert editor.open_file(CZ, ["peppol-bis3"])["guess"] is None


def test_cli_guess(tmp_path, capsys):
    from msgvalidator.__main__ import main
    out = tmp_path / "draft.yaml"
    assert main(["guess", str(S / "en_invoice.xml"), "-o", str(out)]) == 0
    assert "ODHAD" in capsys.readouterr().out and "BT-1" in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------
# slice 2 – arithmetic as evidence (msgvalidator/guess/arith.py) and the `computed:` mapping section
SAP = (S / "sap_like_invoice.xml").read_bytes()
IT = (S / "it_fattura.xml").read_bytes()


def _by(g):
    return {(p.level, p.bt): p for p in g.proposals}


def test_arith_overrides_misleading_names():
    g = _g(SAP)
    got = _by(g)
    # names say 'Price/TotalPrice' and 'ExchangeRate/Rate'; quantity x price = amount says otherwise
    assert got[("line", "BT-146")].field.label.endswith("Component > Rate / DecimalValue")
    assert any("1" in r and "×" in r for r in got[("line", "BT-146")].reasons)
    assert got[("line", "BT-152")].rule["derive"] == "rate_from_tax_at"  # rate = line tax / line amount
    assert got[("line", "BT-151")].rule["derive"] == "vat_category_from_ctx"
    # a single document-level VAT breakdown found by base x rate = total VAT; its 'Amount' (999.99) is refuted
    assert g.groups["BG-23"]["path"] == ("InvoiceRequest", "Invoice", "ProductTax")
    assert got[("vat", "BT-117")].rule["derive"] == "tax_from_base_rate"
    assert got[("doc", "BT-112")].field.name == "GrossAmount" and got[("doc", "BT-110")].field.path[-1] == "Price"
    assert all(c["ok"] for c in g.checks) and {c["rule"] for c in g.checks} >= {
        "množství × cena = částka řádku", "BT-109 + BT-110 = BT-112", "Σ částek řádků = BT-106"}
    assert any(r.startswith("✓ ověřeno") for r in got[("doc", "BT-112")].reasons)


def test_arith_values_after_extraction():
    m = validate(SAP, "f.xml", ["peppol-bis3"], virtual_rules=False).messages[0]
    lines = m.semantic.groups["BG-25"]
    assert [c.values["BT-146"][0].value for c in lines] == ["0.85", "2.35", "7.5"]
    assert {c.values["BT-152"][0].value for c in lines} == {"19.00"} and lines[0].values["BT-151"][0].value == "S"
    vat = m.semantic.groups["BG-23"]
    assert len(vat) == 1 and vat[0].values["BT-117"][0].value == "55.06"
    assert m.guess["checks"] and all(c["ok"] for c in m.guess["checks"])


def test_vat_breakdown_computed_from_lines():
    g = _g(EN)  # the format has no VAT breakdown and the totals have no category
    assert "BG-23" not in g.groups and g.computed["BG-23"]["from"] == "BG-25"
    assert "computed" in g.client and "BT-116" not in g.client["terms"]
    assert any(c["rule"] == "Σ DPH dopočtené z řádků = BT-110" and c["ok"] for c in g.checks)
    m = validate(EN, "f.xml", ["peppol-bis3"], virtual_rules=False).messages[0]
    vat = m.semantic.groups["BG-23"]
    assert [(c.values["BT-116"][0].value, c.values["BT-117"][0].value, c.values["BT-118"][0].value,
             c.values["BT-119"][0].value) for c in vat] == [("200.00", "40.00", "S", "20.00")]
    assert vat[0].values["BT-116"][0].how == "derived" and "BT-116" in m.semantic.mapped_terms


def test_missing_totals_computed_and_virtual_ubl_schema_valid():
    g = _g(IT)  # FatturaPA-like: VAT breakdown and grand total, no total VAT, no net total
    assert g.computed["BT-110"] == {"sum": "BT-117", "over": "BG-23", "note": g.computed["BT-110"]["note"]}
    assert g.computed["BT-109"]["sum"] == ["BT-112", "-BT-110"] and g.computed["BT-106"]["sum"] == "BT-131"
    rep = validate(IT, "f.xml", ["peppol-bis3"])
    m = rep.messages[0]
    d = {bt: vs[0].value for bt, vs in m.semantic.document.values.items()}
    assert (d["BT-110"], d["BT-109"], d["BT-106"], d["BT-112"]) == ("28.00", "160.00", "160.00", "188.00")
    assert not [f for f in m.rules if "xsd" in (f.message or "").lower()]  # the virtual UBL is schema-valid now
    assert not [f for f in m.rules if f.code.startswith("BR-CO-1") and f.severity == "error"]


def test_coincidence_is_not_evidence():
    # price / amount = 20 % on both lines by coincidence – must not be taken as the line VAT amount
    xml = b"""<Doc><InvoiceNumber>1</InvoiceNumber><InvoiceDate>2026-11-05</InvoiceDate><Currency>EUR</Currency>
    <Seller><Name>A</Name><TaxID>SK2020000003</TaxID></Seller>
    <Lines><Line><Qty>5.00</Qty><Price>100.00</Price><NetAmount>500.00</NetAmount></Line>
           <Line><Qty>5.00</Qty><Price>20.00</Price><NetAmount>100.00</NetAmount></Line></Lines>
    <Summary><TotalNet>600.00</TotalNet><TotalTax>114.00</TotalTax><TotalGross>714.00</TotalGross>
      <Tax><Line2><Base>600.00</Base><Rate>19.00</Rate><Amount>114.00</Amount></Line2></Tax></Summary></Doc>"""
    got = _by(_g(xml))
    assert ("line", "BT-152") not in got and got[("line", "BT-146")].field.name == "Price"
    # counters written without decimals ('1') never become amounts
    assert got[("doc", "BT-112")].field.name == "TotalGross"


def test_computed_section_semantics():
    from msgvalidator.semantic.extract import _compute
    from msgvalidator.semantic.model import Context, Value
    doc = Context(None, "doklad", None)
    doc.add(Value("BT-112", "121.00"))
    doc.add(Value("BT-110", "21.00"))
    lines = [Context("BG-25", "1", None), Context("BG-25", "2", None)]
    lines[0].add(Value("BT-131", "60.00"))
    groups = {"BG-25": lines}
    assert _compute("BT-109", {"sum": ["BT-112", "-BT-110"]}, doc, groups, {}) == {"BT-109"}
    assert doc.values["BT-109"][0].value == "100.00" and doc.values["BT-109"][0].how == "derived"
    assert _compute("BT-106", {"sum": "BT-131", "over": "BG-25"}, doc, groups, {}) == set()  # line 2 has no amount
    assert _compute("BT-112", {"sum": ["BT-109", "BT-110"]}, doc, groups, {}) == set()  # never overrides


def test_computed_survives_save(mapdir):
    o = editor.open_file(IT, ["peppol-bis3"])
    assert o["client"]["computed"]["BT-110"]
    path = idoc_mapping.save_client({**o["client"], "name": "Klient IT"})
    assert "computed:" in pathlib.Path(path).read_text(encoding="utf-8")
    m = validate(IT, "f.xml", ["peppol-bis3"], virtual_rules=False).messages[0]
    assert m.guess is None and m.semantic.document.values["BT-110"][0].value == "28.00"
