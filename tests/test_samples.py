"""Sample generator, CII reader/writer, Peppol envelope (SBDH) and document-type checks."""
import pytest

from msgvalidator import samples
from msgvalidator.cii.reader import read as read_cii
from msgvalidator.detect import detect
from msgvalidator.validate import validate


def errors(rep):
    out = [f for f in rep.envelope if f.severity == "error"]
    for m in rep.messages:
        out += [f for f in m.structure + m.rules + m.values if f.severity == "error"]
    return out


@pytest.mark.parametrize("scenario", list(samples.SCENARIOS))
@pytest.mark.parametrize("fmt", ["ubl", "cii"])
def test_sample_passes_official_rules(scenario, fmt):
    data, name = samples.render(scenario, fmt)
    rep = validate(data, name, ["peppol-bis3"])
    assert not errors(rep), [(f.code, f.message) for f in errors(rep)]
    assert all(r["accepted"] for m in rep.messages for r in m.rules_info["runs"])


def test_cii_roundtrip_keeps_terms():
    sem = samples.build("allowance-charge")
    back = read_cii(samples.cii(sem))
    for bt in ("BT-1", "BT-2", "BT-3", "BT-27", "BT-31", "BT-34", "BT-49", "BT-106", "BT-107", "BT-108", "BT-112", "BT-115"):
        assert back.document.values[bt][0].value == sem.document.values[bt][0].value, bt
    assert len(back.groups["BG-25"]) == 2 and len(back.groups["BG-20"]) == 1 and len(back.groups["BG-21"]) == 1
    assert back.groups["BG-25"][0].values["BT-157"][0].scheme == "0160"


def test_cii_gap_analysis_runs():
    data, _ = samples.render("invoice", "cii")
    rep = validate(data, "x.xml", ["peppol-bis3", "sk-cius"], virtual_rules=False)
    assert rep.detection.family == "XML-CII" and rep.messages[0].semantic is not None
    assert "sk-cius" in rep.messages[0].profiles


def test_sbdh_envelope_checked_and_unwrapped():
    data, _ = samples.render("invoice", "sbdh")
    assert detect(data).family == "SBDH"
    rep = validate(data, "x.xml", ["peppol-bis3"], virtual_rules=False)
    assert rep.embedded_xml and rep.messages[0].semantic is not None
    assert not [f for f in rep.envelope if f.code.startswith("SBDH")]
    bad = data.replace(b"<sh:Type>Invoice</sh:Type>", b"<sh:Type>CreditNote</sh:Type>")
    rep = validate(bad, "x.xml", ["peppol-bis3"], virtual_rules=False)
    assert "SBDH-DOCTYPE" in {f.code for f in rep.envelope}


def test_doctype_checks():
    sem = samples.build("credit-note")
    del sem.document.values["BT-25"]
    data = samples.cii(sem)
    rep = validate(data, "x.xml", ["peppol-bis3"], virtual_rules=False)
    assert "DOC-NO-PRECEDING" in {f.code for f in rep.messages[0].values}
    data, _ = samples.render("partial", "ubl")
    data = data.replace(b">DE<", b">CZ<")
    rep = validate(data, "x.xml", ["peppol-bis3"], virtual_rules=False)
    assert "DOC-PEPPOL-TYPE" in {f.code for f in rep.messages[0].values}


def test_charge_reason_uses_uncl7161():
    data, _ = samples.render("allowance-charge", "ubl")
    rep = validate(data, "x.xml", ["peppol-bis3"], virtual_rules=False)
    assert "VAL-CODELIST" not in {f.code for f in rep.messages[0].values}
