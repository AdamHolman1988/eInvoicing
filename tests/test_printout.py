"""Print layout (tisková sestava) rendered from the semantic model."""
import pytest

from msgvalidator import samples
from msgvalidator.report import printout
from msgvalidator.validate import validate


@pytest.mark.parametrize("fmt", ["ubl", "cii"])
def test_printout_has_header_lines_and_totals(fmt):
    data, name = samples.render(next(iter(samples.SCENARIOS)), fmt)
    rep = validate(data, name, ["peppol-bis3"], virtual_rules=False)
    page = printout.for_report(rep, "cs")
    sem = rep.messages[0].semantic
    d = sem.document
    assert d.values["BT-1"][0].value in page
    assert "Dodavatel" in page and "Odběratel" in page and "K úhradě" in page
    assert page.count("<tr>") >= len(sem.groups.get("BG-25", []))
    assert "Amount due" in printout.for_report(rep, "en")


def test_number_and_date_format():
    assert printout._num("1234.5") == "1\u00a0234,50"
    assert printout._num("-0.5") == "-0,50"
    assert printout._num("3.000", None) == "3"
    assert printout._date("2026-03-18") == "18. 3. 2026"


@pytest.mark.skipif(printout.browser() is None, reason="no Chromium browser")
def test_pdf_is_produced():
    data, name = samples.render(next(iter(samples.SCENARIOS)), "ubl")
    pdf = printout.to_pdf(printout.for_report(validate(data, name, ["peppol-bis3"], virtual_rules=False)))
    assert pdf[:5] == b"%PDF-"
