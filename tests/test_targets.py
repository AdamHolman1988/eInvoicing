"""Target standards: Peppol vs. XRechnung – profiles drive both the gap analysis and the official rule sets."""
import pathlib

from msgvalidator.profiles.loader import available, load
from msgvalidator.validate import _own_target, rule_targets, validate

S = pathlib.Path(__file__).parent / "samples"
CCV = (S / "flat" / "orion_ccv_invoice.txt").read_bytes()
UBL = (S / "ubl" / "peppol_base-example.xml").read_bytes()
PDF = (S / "pdf" / "facturx_en16931.pdf").read_bytes()
ALL = ["peppol-bis3", "sk-cius", "xrechnung"]


def runs(m):
    return {r["target"]: r for r in m.rules_info["runs"]}


def errors(m, label):
    return {f.code for f in m.rules if f.severity == "error" and label in f.profiles}


def test_xrechnung_profile_from_br_de():
    x = load("xrechnung")
    assert x.rules == "xrechnung" and load("billa-sk").rules == "peppol"
    req = {k for k, r in x.requirements.items() if r.level == "required"}
    assert {"BG-6", "BG-16", "BT-10", "BT-41", "BT-42", "BT-43", "BT-37", "BT-38", "BT-52", "BT-53"} <= req
    assert x.requirements["BT-10"].unless == []  # Peppol's BT-13 alternative does not count
    assert [p["id"] for p in available() if p["group"] == "Standardy"][-1] == "xrechnung"


def test_targets_from_profiles():
    assert rule_targets([load("peppol-bis3"), load("billa-sk")]) == ["peppol"]
    assert rule_targets([load(p) for p in ALL]) == ["peppol", "xrechnung"]
    assert rule_targets([load("xrechnung")], forced="peppol") == ["peppol"]


def test_flat_file_checked_against_both_standards():
    m = validate(CCV, "ccv.txt", ALL).messages[0]
    r = runs(m)
    assert r["peppol"]["accepted"] and not r["xrechnung"]["accepted"]
    assert {"BR-DE-15", "BR-DE-2"} <= errors(m, "XRechnung 3.0 (DE)")
    assert not errors(m, "Peppol BIS 3.0 / EN 16931")
    gaps = {pid: {f.bt for f in fs if f.severity == "error"} for pid, fs in m.profiles.items()}
    assert gaps["peppol-bis3"] == set() and {"BG-6", "BT-10", "BT-43"} <= gaps["xrechnung"]


def test_only_peppol_selected_runs_only_peppol():
    m = validate(CCV, "ccv.txt", ["peppol-bis3", "sk-cius"]).messages[0]
    assert list(runs(m)) == ["peppol"]


def test_native_ubl_what_if_xrechnung():
    assert _own_target(UBL) == "peppol"
    m = validate(UBL, "u.xml", ALL).messages[0]
    r = runs(m)
    assert r["peppol"]["accepted"] and r["peppol"]["note"] is None
    assert not r["xrechnung"]["accepted"] and "co kdyby" in r["xrechnung"]["note"]
    assert "XRechnung" in r["xrechnung"]["scenario"]
    assert "BR-DE-2" in errors(m, "XRechnung 3.0 (DE)")


def test_pdf_embedded_cii_against_xrechnung():
    m = validate(PDF, "f.pdf", ALL).messages[0]
    r = runs(m)
    assert r["peppol"]["accepted"] and not r["xrechnung"]["accepted"]
    assert {"BR-DE-1", "BR-DE-2"} <= errors(m, "XRechnung 3.0 (DE)")
