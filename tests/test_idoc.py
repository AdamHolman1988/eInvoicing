"""SAP IDoc INVOIC (XML) – detection, parsing, standard + client mappings. Synthetic data only."""
import pathlib

import pytest

from msgvalidator import idoc
from msgvalidator.detect import detect
from msgvalidator.idoc import mapping as idoc_mapping
from msgvalidator.validate import validate

S = pathlib.Path(__file__).parent / "samples" / "idoc"
INV = (S / "invoic02_invoice.xml").read_bytes()


@pytest.fixture
def mapdir(tmp_path, monkeypatch):
    monkeypatch.setenv("MSGVALIDATOR_MAPPINGS", str(tmp_path))
    return tmp_path


def vals(ctx):
    return {k: v[0].value for k, v in ctx.values.items()}


def test_detect():
    d = detect(INV)
    assert d.family == "SAP-IDOC" and d.supported and d.version == "INVOIC02"
    assert d.details["sender"] == "TSTCLNT100"


def test_parse_fields_tree_and_normalisation():
    f = idoc.parse(INV)
    m = f.messages[0]
    assert m.ref == "FV2026042" and m.idoctyp == "INVOIC02" and m.control["SNDPRN"] == "TSTCLNT100"
    assert m.fields["E1EDP01"][0] == "POSEX"  # dictionary order first
    p05 = m.first("E1EDP05")
    assert p05.get(m.fields["E1EDP05"].index("KPERC") + 1) == "-10.000"  # SAP trailing sign
    assert m.value("E1EDS01", "SUMME") == "15.00"  # padding trimmed
    tags = [getattr(c, "name", None) or c.tag for c in m.root.children]
    assert tags.index("UNS") == tags.index("E1EDS01") - 1
    assert any(i["code"] == "IDOC-UNKNOWN-SEGMENT" and "Z1TEST" in i["message"] for i in m.issues)


def test_number_and_date_errors():
    bad = INV.replace(b"<MENGE>1.000</MENGE>", b"<MENGE>1,000</MENGE>").replace(b"20261031", b"31.10.26")
    codes = {i["code"] for i in idoc.parse(bad).messages[0].issues}
    assert {"IDOC-NUM", "IDOC-DATE"} <= codes


def test_standard_mapping_values():
    m = validate(INV, "t.xml", ["peppol-bis3", "sk-cius"], client="standard").messages[0]
    d = vals(m.semantic.document)
    assert (d["BT-1"], d["BT-2"], d["BT-3"], d["BT-7"], d["BT-9"]) == ("FV2026042", "2026-10-01", "380", "2026-09-30", "2026-10-31")
    assert (d["BT-27"], d["BT-44"], d["BT-31"], d["BT-48"]) == ("Dodavatel Test s.r.o.", "Odběratel Test a.s.", "SK2020000000", "SK2021111111")
    assert d["BT-13"] == "OBJ-77" and "BT-25" not in d  # E1EDK02 011 = own number -> not a preceding invoice
    assert (d["BT-109"], d["BT-110"], d["BT-112"]) == ("15.00", "3.45", "18.45")
    vat = m.semantic.groups["BG-23"]
    assert len(vat) == 1 and vat[0].label == "DPH 23.000 % (kód A1)"
    base = vat[0].values["BT-116"][0]
    assert (base.value, base.how) == ("15.00", "derived")  # sum of lines with tax code A1
    l1, l2 = m.semantic.groups["BG-25"]
    assert vals(l1)["BT-146"] == "5.50"  # (10.00 + allowance 1.00) / 2
    assert vals(l1)["BT-157"] == "8590000000107" and vals(l1)["BT-130"] == "H87"
    assert [c.aux["item_type"].value for c in (l1, l2)] == ["Z", "S"]  # PSTYV TAN / TAD
    assert vals(m.semantic.groups["BG-27"][0]) == {"BT-136": "1.00", "BT-139": "Skonto"}
    assert m.rules_info["accepted"], [(f.code, f.message) for f in m.rules if f.severity == "error"]


def test_service_line_gtin_warning_for_billa():
    m = validate(INV, "t.xml", ["billa-sk"], virtual_rules=False).messages[0]
    assert [(f.severity, f.code) for f in m.gaps if f.bt == "BT-157"] == [("warning", "GAP-SERVICE")]


def test_preceding_invoice_when_different():
    cn = INV.replace(b"<BSART>INVO</BSART>", b"<BSART>CRME</BSART>").replace(
        b"<QUALF>011</QUALF><BELNR>FV2026042</BELNR>", b"<QUALF>011</QUALF><BELNR>FV2026001</BELNR>")
    m = validate(cn, "t.xml", ["peppol-bis3"], virtual_rules=False).messages[0]
    assert m.semantic.doc_kind == "CreditNote" and vals(m.semantic.document)["BT-25"] == "FV2026001"


def test_client_override_draft():
    client = {"id": "test", "name": "Test klient",
              "terms": {"BT-34": [{"derive": "gln_endpoint_at", "args": {"path": "E1EDKA1[PARVW=RS]", "value": "LIFNR"}}],
                        "BT-13": [],
                        "BT-118": [{"path": "@", "value": "MWSKZ", "map": {"A1": "S"}}]}}
    m = validate(INV, "t.xml", ["peppol-bis3"], virtual_rules=False, client=client).messages[0]
    d = m.semantic.document.values
    assert (d["BT-34"][0].value, d["BT-34"][0].scheme) == ("8590000000015", "0088")
    assert "BT-13" not in d and "BT-13" not in m.semantic.mapped_terms
    cat = m.semantic.groups["BG-23"][0].values["BT-118"][0]
    assert (cat.value, cat.raw, cat.how) == ("S", "A1", "mapped")
    assert "Test klient" in m.label


def test_saved_client_is_picked_by_sender(mapdir):
    path = idoc_mapping.save_client({"name": "Testovací Klient", "match": {"EDI_DC40.SNDPRN": "TSTCLNT100"},
                                     "terms": {"BT-27": [{"path": "E1EDKA1[PARVW=AG]", "value": "NAME1"}]}})
    assert pathlib.Path(path).name == "testovaci-klient.yaml"
    m = validate(INV, "t.xml", ["peppol-bis3"], virtual_rules=False).messages[0]
    assert vals(m.semantic.document)["BT-27"] == "Objednatel Eshop"
    other = INV.replace(b"TSTCLNT100", b"OTHER")
    m2 = validate(other, "t.xml", ["peppol-bis3"], virtual_rules=False).messages[0]
    assert vals(m2.semantic.document)["BT-27"] == "Dodavatel Test s.r.o." and "standardní" in m2.label


def test_suggest_match():
    msg = idoc.parse(INV).messages[0]
    assert idoc_mapping.suggest_match(msg) == {"EDI_DC40.SNDPRN": "TSTCLNT100", "E1EDK01.EIGENUINR": "SK2020000000"}


def test_editor_open_and_preview(mapdir):
    from msgvalidator.idoc import editor
    o = editor.open_file(INV, ["peppol-bis3", "sk-cius"])
    paths = {n["path"] for n in o["source"]}
    assert {"E1EDKA1[PARVW=RS]", "E1EDP01 > E1EDP19[QUALF=003]", "E1EDS01[SUMID=011]", "Z1TEST"} <= paths
    rs = next(n for n in o["source"] if n["path"] == "E1EDKA1[PARVW=RS]")
    assert rs["qualifier"]["label"].startswith("Fakturující") and any(f["name"] == "NAME1" and f["label"] for f in rs["fields"])
    assert o["picked"] is None and o["client"]["match"]["EDI_DC40.SNDPRN"] == "TSTCLNT100"
    draft = {"name": "Koncept", "terms": {"BT-27": [{"path": "E1EDKA1[PARVW=AG]", "value": "NAME1"}]},
             "groups": {"BG-23": {"each": "E1EDS01[SUMID=010]", "scope": "summary"}}}
    p = editor.preview(INV, draft, ["peppol-bis3"])
    assert p["values"]["BT-27"]["value"] == "Objednatel Eshop" and "Koncept" in p["label"]
    assert p["groups"]["BG-23"] == 0  # moved group without remapped terms -> empty instances skipped


def test_server_mapper_api(mapdir):
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from msgvalidator.ui.server import Handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path, body, headers=None):
        req = urllib.request.Request(base + path, data=body, headers=headers or {}, method="POST")
        return json.loads(urllib.request.urlopen(req).read())
    try:
        assert b"Mapov" in urllib.request.urlopen(base + "/mapper").read()
        o = post("/api/mapper/open", INV, {"X-Filename": "t.xml"})
        c = {"name": "API klient", "match": o["suggest_match"], "terms": {}}
        p = post("/api/mapper/preview", json.dumps({"token": o["token"], "client": c}).encode())
        assert p["values"]["BT-1"]["value"] == "FV2026042"
        s = post("/api/mapper/save", json.dumps({"client": c}).encode())
        assert s["id"] == "api-klient" and pathlib.Path(s["path"]).exists()
        assert post("/api/mapper/open", INV, {"X-Filename": "t.xml"})["picked"] == "api-klient"
    finally:
        httpd.shutdown()


TXT = (S / "invoic02_invoice.idoc").read_bytes()
GEN = (S / "generic_faktura.xml").read_bytes()


def test_text_dump_same_as_xml():
    d = detect(TXT)
    assert d.family == "SAP-IDOC" and "textový" in d.label and d.details["sender"] == "TSTCLNT100"
    a = validate(INV, "x.xml", ["peppol-bis3"], virtual_rules=False).messages[0].semantic
    b = validate(TXT, "x.idoc", ["peppol-bis3"], virtual_rules=False).messages[0].semantic
    assert vals(a.document) == vals(b.document)
    assert [vals(c) for c in a.groups["BG-25"]] == [vals(c) for c in b.groups["BG-25"]]
    assert idoc.parse(TXT).messages[0].first("E1EDP19") is not None  # nesting by indentation


def test_generic_xml_unmapped_then_client(mapdir):
    d = detect(GEN)
    assert d.family == "XML" and d.details["mappable"]
    rep = validate(GEN, "f.xml", guess=False)
    assert not rep.messages and rep.envelope[0].code == "FMT-UNMAPPED"
    rep = validate(GEN, "f.xml", virtual_rules=False)  # without a client mapping the format is guessed
    assert rep.envelope[0].code == "FMT-GUESSED" and rep.messages[0].guess and "ODHAD" in rep.messages[0].label
    idoc_mapping.save_client({
        "name": "Klient XML", "base": "xml_generic", "match": {"ROOT": "Faktura"},
        "groups": {"BG-25": {"each": "Faktura > Polozky > Polozka", "scope": "line"}},
        "terms": {"BT-1": [{"path": "Faktura > Hlavicka", "value": "Cislo"}],
                  "BT-2": [{"path": "Faktura > Hlavicka", "value": "Datum", "date": "102"}],
                  "BT-131": [{"path": "@", "value": "Celkem"}]}})
    m = validate(GEN, "f.xml", virtual_rules=False).messages[0]
    assert m.ref == "F-2026-77" and "Klient XML" in m.label
    d = vals(m.semantic.document)
    assert d["BT-1"] == "F-2026-77" and d["BT-2"] == "2026-11-01"  # ISO date accepted
    assert [vals(c)["BT-131"] for c in m.semantic.groups["BG-25"]] == ["10.00", "7.50"]
    assert "BT-27" not in m.semantic.mapped_terms  # generic base maps nothing by itself
