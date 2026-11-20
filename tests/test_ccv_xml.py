"""CCV eBUS XML INVOIC -> ORION XML 3 (production converter) -> ORION checks. Synthetic sample."""
import pathlib

from msgvalidator.detect import detect
from msgvalidator.validate import validate

S = pathlib.Path(__file__).parent / "samples" / "orion" / "ccv_invoic.xml"


def test_detect_ccv_xml():
    d = detect(S.read_bytes())
    assert d.family == "XML-ORION-CCV" and d.supported


def test_ccv_xml_converted_and_checked():
    rep = validate(S.read_bytes(), "ccv.xml", ["peppol-bis3"], virtual_rules=False)
    assert rep.embedded_xml and b"<orion_message" in rep.embedded_xml and b"Not requested" in rep.embedded_xml
    m = rep.messages[0]
    assert m.semantic is not None and "CCV" in m.label
    assert not [f for f in rep.envelope if f.code == "CCV-CONVERT"]
