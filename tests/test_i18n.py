"""Czech / English output."""
import pathlib

from msgvalidator import i18n
from msgvalidator.report import html
from msgvalidator.ui.page import PAGE
from msgvalidator.ui.server import _page
from msgvalidator.validate import validate

S = pathlib.Path(__file__).parent / "samples"


def test_phrase_table_whole_words():
    assert i18n.tr("Bez chyb", "en") == "No errors"
    assert i18n.tr("doklad", "en") == "document" and i18n.tr("dokladový", "en") == "dokladový"  # whole words only
    assert i18n.tr("Bez chyb", "cs") == "Bez chyb"


def test_report_in_english_keeps_document_data():
    rep = validate((S / "flat" / "orion_ccv_invoice.txt").read_bytes(), "faktura.txt", ["peppol-bis3", "xrechnung"])
    i18n.localize(rep, "en")
    out = html.body(rep, "en")
    assert "Official rules by target standard" in out or "OFFICIAL RULES" in out.upper()
    assert "Kontrola hodnot" not in out and "Value checks" in out
    assert "faktura.txt" in out  # data (file name) untouched
    assert all(f.name_sk is None for m in rep.messages for f in m.gaps)
    cs = validate((S / "flat" / "orion_ccv_invoice.txt").read_bytes(), "faktura.txt", ["peppol-bis3"])
    assert "Kontrola hodnot" in html.body(cs)  # Czech stays Czech (cached profiles not mutated)


def test_pages_in_english():
    en = _page(PAGE, "check", "en")
    assert '<html lang="en">' in en and "Drop a file here" in en and "Přetáhněte" not in en
    assert "Přetáhněte" in _page(PAGE, "check", "cs")
