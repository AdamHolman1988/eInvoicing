import pathlib
import re

import pytest

from msgvalidator.validate import validate
from msgvalidator.xmlval import kosit

UBL = pathlib.Path(__file__).parent / "samples" / "ubl"


@pytest.fixture(scope="module")
def base_invoice():
    return (UBL / "peppol_base-example.xml").read_bytes()


def test_peppol_invoice_accepted(base_invoice):
    r = kosit.validate(base_invoice, "peppol")
    assert r.scenario == "Peppol BIS Billing 3.0 (UBL Invoice)"
    assert r.accepted and r.valid
    assert [ok for _, ok in r.steps] == [True, True, True]


def test_peppol_credit_note_accepted():
    r = kosit.validate((UBL / "peppol_base-creditnote-correction.xml").read_bytes(), "peppol")
    assert r.scenario == "Peppol BIS Billing 3.0 (UBL CreditNote)" and r.accepted


def test_rules_fire_with_line_numbers(base_invoice):
    bad = re.sub(rb"<cbc:BuyerReference>.*?</cbc:BuyerReference>", b"", base_invoice)
    bad = bad.replace(b">1300</cbc:LineExtensionAmount>", b">1400</cbc:LineExtensionAmount>", 1)
    r = kosit.validate(bad, "peppol")
    codes = {m.code for m in r.messages}
    assert {"BR-CO-10", "BR-CO-13", "PEPPOL-EN16931-R003"} <= codes
    assert not r.accepted
    assert all(m.line for m in r.messages)


def test_xsd_error_blocks_schematron(base_invoice):
    bad = base_invoice.replace(b"<cbc:IssueDate>", b"<cbc:Foo>x</cbc:Foo><cbc:IssueDate>", 1)
    r = kosit.validate(bad, "peppol")
    assert not r.accepted
    assert r.steps and r.steps[0][1] is False
    assert any(m.step.startswith("UBL 2.1") for m in r.messages)


def test_not_wellformed():
    r = kosit.validate(b"<a><b></a>", "peppol")
    assert not r.accepted and r.messages[0].code == "XML-WELLFORMED"


def test_official_xrechnung_configuration_loads():
    repo = kosit.load("xrechnung")
    assert len(repo.scenarios) >= 10
    # a Peppol document is not an XRechnung document
    r = kosit.validate((UBL / "peppol_base-example.xml").read_bytes(), "xrechnung")
    assert r.scenario is None and not r.accepted


def test_validate_routes_xml_to_kosit(base_invoice):
    rep = validate(base_invoice, "inv.xml")
    m = rep.messages[0]
    assert m.rules_info["accepted"] is True
    assert rep.counts()["error"] == 0


def test_edifact_virtual_ubl_rules(d01b_example):
    rep = validate(d01b_example, "x.edi", ["peppol-bis3"])
    m = rep.messages[0]
    assert m.virtual_xml and m.rules_info["steps"][0] == ("UBL 2.1 Invoice XSD", True)  # writer output is XSD-valid
    codes = {f.code for f in m.rules}
    assert "BR-CL-17" in codes  # TAX category AA
    r = next(f for f in m.rules if f.code == "BR-CL-17")
    assert r.bt == "BT-95" and r.line and r.segment.startswith("TAX+")  # points back to the EDIFACT segment
    assert any(f.code == "UBL-CONVERSION" for f in m.rules)  # empty VAT groups dropped, notes merged


def test_all_mig_examples_produce_schema_valid_ubl():
    from msgvalidator.edifact import parser, structure
    from msgvalidator.semantic.extract import extract
    from msgvalidator.ubl.writer import write
    for f in sorted((pathlib.Path(__file__).parent / "samples" / "edifact").glob("*.edi")):
        msg = parser.parse(f.read_bytes()).messages[0]
        tree, _ = structure.match(msg)
        r = kosit.validate(write(extract(msg, tree, "edifact_invoic_eancom")).xml, "peppol")
        assert r.steps[0][1] is True, f.name


def test_ubl_reader_and_gap_analysis(base_invoice):
    from msgvalidator.ubl.reader import read
    sem = read(base_invoice)
    doc = sem.document
    assert doc.values["BT-1"][0].value == "Snippet1"
    assert doc.values["BT-31"][0].value == "GB1232434"  # VAT id discriminated from tax registration
    assert "BT-32" not in doc.values
    assert len(sem.groups["BG-25"]) == 2 and sem.groups["BG-25"][0].values["BT-130"][0].value
    rep = validate(base_invoice, "inv.xml", ["billa-sk"])
    gaps = {(f.code, f.bt) for f in rep.messages[0].gaps}
    assert ("GAP-MISSING", "BT-32") in gaps  # Billa needs the SK tax registration id


def test_ubl_reader_credit_note():
    from msgvalidator.ubl.reader import read
    sem = read((UBL / "peppol_base-creditnote-correction.xml").read_bytes())
    assert sem.doc_kind == "CreditNote" and sem.groups["BG-25"]
    assert sem.groups["BG-25"][0].values.get("BT-129")


def test_line_charge_recycling_fee(d01b_example):
    text = d01b_example.decode("utf-8").replace("\r\n", "\n").replace(
        "UNS+S'", "ALC+C+Recyklační poplatek+++AEO'\nMOA+8:15.00'\nRTE+2:1.50:1:PCE'\nUNS+S'", 1)
    m = validate(text.encode("utf-8"), "x.edi", ["peppol-bis3"]).messages[0]
    charges = m.semantic.groups["BG-28"]
    assert len(charges) == 1 and charges[0].parent.label == "řádek 2"
    assert charges[0].values["BT-145"][0].value == "AEO"
    assert m.semantic.groups["BG-25"][0].values["BT-147"][0].how == "explicit"  # ALC+A/MOA+204 = unit discount
    assert b"<cbc:ChargeIndicator>true</cbc:ChargeIndicator>" in m.virtual_xml
    assert m.rules_info["steps"][0][1] is True  # still XSD-valid
    # GS1 CZ line amount excludes the fee, Peppol requires it -> R120 on that line
    assert any(f.code == "PEPPOL-EN16931-R120" for f in m.rules)


def test_merge_keeps_every_location_of_same_rule():
    """Same official rule failing on two lines (e.g. PEPPOL-EN16931-R040) must report both places."""
    from msgvalidator.profiles.checker import Finding, merge
    msg = "[PEPPOL-EN16931-R040]-Allowance/charge amount must equal base amount * percentage/100"
    fs = [Finding("error", "PEPPOL-EN16931-R040", msg, line=213, segment="/Invoice/InvoiceLine[3]/AllowanceCharge"),
          Finding("error", "PEPPOL-EN16931-R040", msg, line=258, segment="/Invoice/InvoiceLine[4]/AllowanceCharge"),
          # same place reported again by another rule run → no duplicate location
          Finding("error", "PEPPOL-EN16931-R040", msg, line=258, segment="/Invoice/InvoiceLine[4]/AllowanceCharge")]
    out = merge(fs)
    assert len(out) == 1
    assert out[0].contexts == ["/Invoice/InvoiceLine[3]/AllowanceCharge (ř. 213)",
                               "/Invoice/InvoiceLine[4]/AllowanceCharge (ř. 258)"]
    # a single occurrence stays as it was (location only in line/segment)
    assert merge(fs[:1])[0].contexts == []
