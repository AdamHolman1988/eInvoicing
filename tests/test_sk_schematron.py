"""SK CIUS Schematron as an extra step of the KoSIT scenarios (tools/build_sk_schematron.py)."""
import pathlib
import re

import pytest

from msgvalidator.xmlval import kosit

UBL = pathlib.Path(__file__).parent / "samples" / "ubl"
SK_INVOICE = "Peppol BIS Billing 3.0 + SK CIUS (UBL Invoice)"
SK_CREDIT_NOTE = "Peppol BIS Billing 3.0 + SK CIUS (UBL CreditNote)"
SK_STEP = "SK CIUS 1.13 UBL"


def slovakize(xml: bytes) -> bytes:
    """Peppol example -> Slovak seller and buyer (countries, VAT ids in SK format, IČO)."""
    s = xml.decode("utf-8")
    s = re.sub(r"(<cac:AccountingSupplierParty>.*?<cbc:IdentificationCode>)[A-Z]{2}(</cbc:IdentificationCode>)",
               r"\1SK\2", s, count=1, flags=re.S)
    s = re.sub(r"(<cac:AccountingCustomerParty>.*?<cbc:IdentificationCode>)[A-Z]{2}(</cbc:IdentificationCode>)",
               r"\1SK\2", s, count=1, flags=re.S)
    s = re.sub(r"(<cac:AccountingSupplierParty>.*?<cac:PartyTaxScheme>\s*<cbc:CompanyID>)[^<]*",
               r"\g<1>SK2020123456", s, count=1, flags=re.S)
    s = re.sub(r"(<cac:AccountingCustomerParty>.*?<cac:PartyTaxScheme>\s*<cbc:CompanyID>)[^<]*",
               r"\g<1>SK2021234567", s, count=1, flags=re.S)
    s = re.sub(r"(<cac:AccountingSupplierParty>.*?<cac:PartyLegalEntity>\s*<cbc:RegistrationName>[^<]*</cbc:RegistrationName>\s*<cbc:CompanyID)[^>]*>[^<]*",
               r'\1>12345678', s, count=1, flags=re.S)
    return s.encode("utf-8")


@pytest.fixture(scope="module")
def sk_invoice():
    return slovakize((UBL / "peppol_base-example.xml").read_bytes())


def sk_messages(r):
    return [m for m in r.messages if m.code.startswith("SK-CIUS-")]


def test_sk_invoice_selects_sk_scenario_and_is_accepted(sk_invoice):
    assert b"<cbc:IdentificationCode>SK</cbc:IdentificationCode>" in sk_invoice
    r = kosit.validate(sk_invoice, "peppol")
    assert r.scenario == SK_INVOICE
    assert [name for name, _ in r.steps][-1] == SK_STEP
    errors = [m for m in r.messages if m.level == "error"]
    assert errors == [] and r.accepted
    # conditional SK requirements are warnings only (e.g. no legal form BT-33, no IČO scheme BT-30-1)
    assert {m.code for m in sk_messages(r)} <= {"SK-CIUS-BT-33", "SK-CIUS-BT-30-1", "SK-CIUS-BT-47-1"}
    assert all(m.level == "warning" for m in sk_messages(r))


def test_sk_required_element_missing_fires_with_line(sk_invoice):
    # seller city (BT-37) is optional in Peppol but required by § 74 ods. 1 písm. a)
    bad = sk_invoice.replace(b"<cbc:CityName>London</cbc:CityName>", b"", 1)
    assert bad != sk_invoice
    r = kosit.validate(bad, "peppol")
    assert r.scenario == SK_INVOICE and not r.accepted
    hits = [m for m in r.messages if m.code == "SK-CIUS-BT-37"]
    assert len(hits) == 1
    m = hits[0]
    assert m.level == "error" and m.step == SK_STEP and "BT-37" in m.text
    # the rule context is the seller postal address (BG-5) -> line of <cac:PostalAddress>
    lines = bad.decode().splitlines()
    assert m.line and "<cac:PostalAddress>" in lines[m.line - 1]
    # nothing else broke: the only errors come from the SK step
    assert {x.code for x in r.messages if x.level == "error"} == {"SK-CIUS-BT-37"}


def test_sk_rule_only_for_present_optional_group(sk_invoice):
    # tax representative (BG-11) absent -> BT-64/66/67 do not fire; present without street -> BT-64 fires
    r = kosit.validate(sk_invoice, "peppol")
    assert not any(m.code in ("SK-CIUS-BT-64", "SK-CIUS-BT-66") for m in r.messages)
    rep = (b"<cac:TaxRepresentativeParty><cac:PartyName><cbc:Name>Zastupca s.r.o.</cbc:Name></cac:PartyName>"
           b"<cac:PostalAddress><cbc:CityName>Bratislava</cbc:CityName><cbc:PostalZone>81101</cbc:PostalZone>"
           b"<cac:Country><cbc:IdentificationCode>SK</cbc:IdentificationCode></cac:Country></cac:PostalAddress>"
           b"<cac:PartyTaxScheme><cbc:CompanyID>SK2022345678</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID>"
           b"</cac:TaxScheme></cac:PartyTaxScheme></cac:TaxRepresentativeParty>")
    doc = sk_invoice.replace(b"<cac:Delivery>", rep + b"<cac:Delivery>", 1)
    r = kosit.validate(doc, "peppol")
    codes = {m.code for m in r.messages if m.level == "error"}
    assert "SK-CIUS-BT-64" in codes and "SK-CIUS-BT-66" not in codes


def test_sk_credit_note():
    cn = slovakize((UBL / "peppol_base-creditnote-correction.xml").read_bytes())
    r = kosit.validate(cn, "peppol")
    assert r.scenario == SK_CREDIT_NOTE
    assert [m for m in r.messages if m.level == "error"] == [] and r.accepted


def test_non_sk_document_keeps_plain_peppol_scenario():
    r = kosit.validate((UBL / "peppol_base-example.xml").read_bytes(), "peppol")
    assert r.scenario == "Peppol BIS Billing 3.0 (UBL Invoice)"
    assert not sk_messages(r)


def test_generator_is_reproducible():
    """The committed .sch equals what tools/build_sk_schematron.py generates from the repo data."""
    import importlib.util
    path = pathlib.Path(__file__).parents[1] / "tools" / "build_sk_schematron.py"
    spec = importlib.util.spec_from_file_location("build_sk_schematron", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    prof, cat = mod.load()
    rules, _ = mod.collect(prof, cat)
    committed = (mod.OUT_DIR / f"{mod.SCH_NAME}.sch").read_text(encoding="utf-8")
    assert committed == mod.render(rules, prof)
    ids = {r["id"] for r in rules}
    assert {"SK-CIUS-BT-35", "SK-CIUS-BT-37", "SK-CIUS-BT-38", "SK-CIUS-BT-50", "SK-CIUS-BT-52",
            "SK-CIUS-BT-53"} <= ids
    # terms already mandatory in Peppol get no SK duplicate
    assert not ids & {"SK-CIUS-BT-1", "SK-CIUS-BT-27", "SK-CIUS-BT-153", "SK-CIUS-BT-84"}


def test_br_co_25_applies_to_invoice_not_credit_note():
    import pathlib
    import re
    from msgvalidator.xmlval import kosit
    ubl = pathlib.Path(__file__).parent / "samples" / "ubl"

    def sk_without_payment_terms(x: bytes) -> bytes:
        x = re.sub(rb"(<cac:AccountingSupplierParty>.*?<cbc:IdentificationCode>)\w\w", rb"\1SK", x, count=1, flags=re.S)
        x = re.sub(rb"<cbc:(Payment)?DueDate>.*?</cbc:(Payment)?DueDate>", b"", x)
        return re.sub(rb"<cac:PaymentTerms>.*?</cac:PaymentTerms>", b"", x, flags=re.S)

    inv = kosit.validate(sk_without_payment_terms((ubl / "peppol_base-example.xml").read_bytes()), "peppol")
    cn = kosit.validate(sk_without_payment_terms((ubl / "peppol_base-creditnote-correction.xml").read_bytes()), "peppol")
    assert "SK CIUS" in inv.scenario and "SK CIUS" in cn.scenario
    assert any(m.code == "SK-CIUS-BR-CO-25" and m.level == "error" for m in inv.messages)
    assert not any(m.code == "SK-CIUS-BR-CO-25" for m in cn.messages)  # context "Faktúra" only
