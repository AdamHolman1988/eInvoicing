import pathlib

import pytest

from msgvalidator.edifact import parser, structure

SAMPLES = sorted((pathlib.Path(__file__).parent / "samples" / "edifact").glob("mig_*.edi"))


def test_release_character_and_una():
    ic = parser.parse(b"UNA:+.? 'UNH+1+INVOIC:D:01B:UN:EAN011'FTX+AAI+++Obch.reg.?:KOS?+X'UNT+3+1'")
    ftx = ic.messages[0].segments[1]
    assert ftx.get(4, 1) == "Obch.reg.:KOS+X"
    assert ic.issues == []


def test_unt_count_and_reference_checked():
    ic = parser.parse(b"UNH+1+INVOIC:D:01B:UN:EAN011'BGM+380+1+9'UNT+5+2'")
    codes = {i["code"] for i in ic.issues}
    assert {"ENV-UNT-COUNT", "ENV-UNT-REF"} <= codes


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_mig_examples_are_structurally_valid(path):
    ic = parser.parse(path.read_bytes())
    assert ic.messages
    for msg in ic.messages:
        tree, issues = structure.match(msg)
        assert tree is not None
        assert [i for i in issues if i["severity"] == "error"] == []


def _broken(d01b_example: bytes, transform) -> list[dict]:
    text = d01b_example.decode("utf-8").replace("\r\n", "\n")
    msg = parser.parse(transform(text).encode("utf-8")).messages[0]
    return structure.match(msg)[1]


def test_missing_mandatory_segment(d01b_example):
    issues = _broken(d01b_example, lambda t: t.replace("BGM+380+432097+9'\n", ""))
    assert any(i["code"] == "STRUCT-MISSING" and "BGM" in i["message"] for i in issues)


def test_segment_out_of_place(d01b_example):
    # PAI belongs to the header; after the line items it is not allowed
    issues = _broken(d01b_example, lambda t: t.replace("UNS+S'", "PAI+::42'\nUNS+S'"))
    assert any(i["code"] == "STRUCT-UNEXPECTED" and "PAI" in i["message"] for i in issues)


def test_segment_outside_gs1_subset_is_warning(d01b_example):
    # LOC (pos. 0080) is allowed in the UN D.01B header but not used in the GS1 CZ subset
    issues = _broken(d01b_example, lambda t: t.replace("RFF+CT", "LOC+27+CZ'\nRFF+CT", 1))
    assert not [i for i in issues if i["severity"] == "error"]
    assert any(i["code"] == "MIG-STRUCT-UNEXPECTED" for i in issues)


def test_mig_qualifier_check(d01b_example):
    issues = _broken(d01b_example, lambda t: t.replace("DTM+35:", "DTM+999:", 1))
    q = [i for i in issues if i["code"] == "MIG-QUALIFIER"]
    assert any("'999'" in i["message"] and i["severity"] == "warning" for i in q)
    # the MIG's own example uses NAD+II, which chapter 3 of the same MIG does not list
    assert any("'II'" in i["message"] for i in q)
