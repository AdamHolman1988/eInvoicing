from msgvalidator.detect import detect
from msgvalidator.report import html, text
from msgvalidator.validate import validate


def codes(findings):
    return {(f.code, f.bt) for f in findings}


def test_sk_gaps_on_gs1_d01b(d01b_example):
    rep = validate(d01b_example, "x.edi", ["sk-cius"])
    gaps = codes(rep.messages[0].gaps)
    assert ("GAP-DERIVED", "BT-151") in gaps  # GS1 CZ does not carry the VAT category per line
    assert ("GAP-AMBIGUOUS", "BT-130") in gaps  # QTY without unit


def test_billa_requires_sk_tax_id(d01b_example):
    rep = validate(d01b_example, "x.edi", ["billa-sk"])
    assert ("GAP-MISSING", "BT-32") in codes(rep.messages[0].gaps)


def test_value_checks(d01b_example):
    rep = validate(d01b_example, "x.edi", ["peppol-bis3"])
    assert ("VAL-CODELIST", "BT-95") in codes(rep.messages[0].values)  # AA not allowed in EN 16931


SYNTHETIC = (
    b"UNH+1+INVOIC:D:96A:UN:EAN008'BGM+380+1+9'DTM+137:20240101:102'"
    b"NAD+SU+8594006820004::9'RFF+VA:055-47550562'NAD+BY+8594027401008::9'"
    b"CUX+2:CZK:4'LIN+1++8594006820226:EN'QTY+47:1:PCE'MOA+203:10'PRI+AAA:10'"
    b"TAX+7+VAT+++:::21'UNS+S'MOA+86:12.1'MOA+79:10'MOA+125:10'MOA+9:12.1'"
    b"TAX+7+VAT+++:::21+S'MOA+124:2.1'UNT+20+1'"
)


def test_synthetic_message():
    rep = validate(SYNTHETIC, "x.edi", ["sk-cius"])
    m = rep.messages[0]
    assert rep.envelope == []
    assert ("VAL-VATID", "BT-31") in codes(m.values)  # old Czech DIČ format without country prefix
    assert ("MAP-CONVERTED", "BT-130") in codes(m.values)  # PCE -> H87
    assert ("GAP-MISSING", "BT-40") in codes(m.gaps)  # NAD without country, VAT without prefix
    # BT-81 is required only once payment instructions (BG-16) are present – here they are not
    assert ("GAP-MISSING", "BT-81") not in codes(m.gaps)
    assert not [f for f in m.structure if f.severity == "error"]


def test_reports_render(d01b_example):
    rep = validate(d01b_example, "x.edi", ["peppol-bis3", "sk-cius", "billa-sk"])
    assert "Gap analýza" in text.render(rep)
    page = html.render(rep)
    assert page.startswith("<!doctype html>") and "BT-151" in page
    assert html.to_dict(rep)["counts"]["error"] >= 1


def test_detect_formats(d01b_example):
    d = detect(d01b_example)
    assert d.family == "EDIFACT" and d.version == "D01B" and d.supported
    assert detect(b"SYS8594027401008 ED  96AINVOICP\r\nHDR").family == "EDITEL-INHOUSE"
    assert detect(b"<?xml version='1.0'?><orion_message><header><message_type>INVOIC</message_type>"
                  b"<version>3.1.3</version></header></orion_message>").family == "XML-ORION"
    ubl = (b"<Invoice xmlns='urn:oasis:names:specification:ubl:schema:xsd:Invoice-2' "
           b"xmlns:cbc='urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2'>"
           b"<cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
           b"</cbc:CustomizationID></Invoice>")
    d = detect(ubl)
    assert d.family == "XML-UBL" and "Peppol" in d.label


def test_unsupported_format_is_reported():
    rep = validate(b"hello", "x.txt")
    assert rep.envelope and rep.envelope[0].code == "FMT-UNSUPPORTED"


def test_credit_note_requires_preceding_invoice_for_billa(d01b_example):
    data = d01b_example.replace(b"BGM+380+", b"BGM+381+")
    rep = validate(data, "cn.edi", ["billa-sk"])
    m = rep.messages[0]
    assert m.semantic.doc_kind == "CreditNote"
    assert ("DOC-CREDITNOTE", "BT-3") in codes(m.values)
    assert ("GAP-MISSING", "BT-25") in codes(m.gaps)
    # the same document as an invoice does not need BT-25
    assert ("GAP-MISSING", "BT-25") not in codes(validate(d01b_example, "i.edi", ["billa-sk"]).messages[0].gaps)


def test_placeholders_and_sk_tax_id():
    data = SYNTHETIC.replace(b"RFF+VA:055-47550562", b"RFF+VA:SK2020241146").replace(
        b"NAD+BY+8594027401008::9", b"NAD+BY+XXXXXXXXXXXX::9")
    m = validate(data, "x.edi", ["billa-sk"]).messages[0]
    assert ("VAL-PLACEHOLDER", "BT-46") in codes(m.values)
    assert ("VAL-CHECKDIGIT", "BT-46") not in codes(m.values)
    bt32 = m.semantic.document.values["BT-32"][0]
    assert bt32.value == "2020241146" and bt32.how == "derived"
