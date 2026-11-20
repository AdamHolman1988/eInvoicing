"""Hybrid PDF invoices (ZUGFeRD / Factur-X). Synthetic PDFs from tools/make_facturx_sample.py."""
import pathlib

import pytest

from msgvalidator import pdfinv
from msgvalidator.detect import detect
from msgvalidator.validate import validate

S = pathlib.Path(__file__).parent / "samples" / "pdf"


def codes(rep):
    return {f.code for f in rep.envelope}


def test_detect_pdf():
    assert detect((S / "facturx_en16931.pdf").read_bytes()).family == "PDF"


def test_facturx_embedded_xml_validated():
    rep = validate((S / "facturx_en16931.pdf").read_bytes(), "f.pdf", ["peppol-bis3"], virtual_rules=False)
    assert "Factur-X" in rep.detection.label and rep.detection.details["profile"] == "EN 16931"
    assert rep.detection.details["xmp"]["ConformanceLevel"] == "EN 16931" and rep.detection.details["xmp"]["pdfa"] == "3B"
    m = rep.messages[0]
    assert m.label.startswith("factur-x.xml (vloženo v PDF)")
    assert m.rules_info["accepted"] and "CII" in m.rules_info["scenario"]
    assert rep.embedded_xml.startswith(b"<?xml")
    assert not [f for f in rep.envelope if f.severity != "info"]


def test_container_problems():
    rep = validate((S / "facturx_mismatch.pdf").read_bytes(), "f.pdf", ["peppol-bis3"], virtual_rules=False)
    assert {"PDF-PROFILE-MISMATCH", "PDF-FILENAME"} <= codes(rep)
    assert rep.detection.details["profile"] == "BASIC"


def test_plain_pdf_has_no_invoice():
    rep = validate((S / "plain.pdf").read_bytes(), "f.pdf")
    assert "PDF-NO-XML" in codes(rep) and not rep.messages


@pytest.mark.parametrize("g,p", [
    ("urn:cen.eu:en16931:2017", "EN 16931"),
    ("urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic", "BASIC"),
    ("urn:factur-x.eu:1p0:basicwl", "BASIC WL"),
    ("urn:zugferd.de:2p0:minimum", "MINIMUM"),
    ("urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended", "EXTENDED"),
    ("urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0", "XRECHNUNG"),
])
def test_profile_of(g, p):
    assert pdfinv.profile_of(g) == p
