import pathlib

import pytest

from msgvalidator import flat
from msgvalidator.detect import detect
from msgvalidator.flat import mapping as flat_mapping
from msgvalidator.validate import validate

S = pathlib.Path(__file__).parent / "samples" / "flat"
INV = (S / "inhouse_d01b_invoice.txt").read_bytes()
CN = (S / "inhouse_d01b_creditnote.txt").read_bytes()


def codes(findings):
    return {f.code for f in findings}


def test_detect_inhouse():
    d = detect(INV)
    assert d.family == "EDITEL-INHOUSE" and d.supported and d.details["layout"] == "editel_inhouse_invoic_d01b"
    # without SYS the file starts with HDR – still recognised (D01B assumed)
    no_sys = b"\r\n".join(INV.split(b"\r\n")[1:])
    assert detect(no_sys).supported


def test_number_normalisation():
    assert flat._norm_num("    100.0000") == "100.00"
    assert flat._norm_num("  10.1234") == "10.1234"
    assert flat._norm_num("12,5") == "12.5"
    assert flat._norm_num("12.50-") == "-12.50"
    assert flat._norm_num("0004") == "4"
    assert flat._norm_num("12a") is None


def test_parse_and_tree():
    ff = flat.parse(INV, "editel_inhouse_invoic_d01b")
    assert len(ff.messages) == 1 and ff.messages[0].ref == "FA2026001"
    assert not ff.messages[0].issues
    root = flat.build_tree(ff.messages[0], ff.layout)
    tags = [getattr(c, "tag", None) or c.name for c in root.children]
    assert tags.count("LIN") == 2 and "UNS" in tags
    vat = [c for c in root.children if getattr(c, "tag", None) == "VAT"]
    assert [v.get(1) for v in vat] == ["1", "2"]  # tax group 0 has zero base -> skipped


def test_invoice_semantic_and_rules():
    rep = validate(INV, "inv.txt", ["peppol-bis3", "sk-cius"])
    m = rep.messages[0]
    sem = m.semantic
    assert sem.document.values["BT-1"][0].value == "FA2026001"
    assert sem.document.values["BT-2"][0].value == "2026-11-02"
    assert sem.document.values["BT-31"][0].value == "SK2020000000"
    assert [c.values["BT-131"][0].value for c in sem.groups["BG-25"]] == ["100.00", "20.00"]
    assert {c.values["BT-119"][0].value for c in sem.groups["BG-23"]} == {"19.00", "23.00"}
    assert m.rules_info["accepted"]
    assert not [f for f in m.gaps if f.severity == "error"]


def test_creditnote_reference_and_billa():
    rep = validate(CN, "cn.txt", ["billa-sk"])
    m = rep.messages[0]
    assert m.semantic.doc_kind == "CreditNote"
    assert m.semantic.document.values["BT-25"][0].value == "FA2025999"
    assert "BT-25" not in {f.bt for f in m.gaps}


def test_structure_errors():
    lines = INV.decode("cp1250").split("\r\n")
    bad = list(lines)
    bad.insert(3, "XYZ nic")                                       # unknown record
    bad = [l for l in bad if not l.startswith("SUM")]              # missing SUM
    lin = next(i for i, l in enumerate(bad) if l.startswith("LIN"))
    bad[lin] = bad[lin][:85] + "     1x0.000" + bad[lin][97:]     # quantity is not a number
    rep = validate("\r\n".join(bad).encode("cp1250"), "bad.txt", ["peppol-bis3"], virtual_rules=False)
    found = codes(rep.messages[0].structure)
    assert {"FLAT-UNKNOWN-RECORD", "FLAT-MISSING-RECORD", "FLAT-NUM"} <= found


def test_mapping_names_resolve_and_fail():
    mp = flat_mapping.load("flat_editel_inhouse_invoic_d01b")
    assert mp["terms"]["BT-31"][0]["path"] == "NAD[1.1=SU]"
    assert mp["terms"]["BT-31"][0]["value"] == "15.1"
    with pytest.raises(flat_mapping.MappingError):
        flat_mapping.resolve({"layout": "editel_inhouse_invoic_d01b", "terms": {"BT-1": [{"path": "HDR", "value": "NEEXISTUJE"}]}},
                             "editel_inhouse_invoic_d01b")


CCV = (S / "orion_ccv_invoice.txt").read_bytes()


def test_detect_picks_matching_layout():
    d = detect(CCV)
    assert d.family == "ORION-FLAT" and d.details["layout"] == "orion_ccv_invoic" and d.details["fit_errors"] == 0
    no_sys = b"\r\n".join(INV.split(b"\r\n")[1:])
    assert detect(no_sys).details["layout"] == "editel_inhouse_invoic_d01b"


def test_ccv_invoice_accepted():
    rep = validate(CCV, "ccv.txt", ["peppol-bis3", "sk-cius"])
    m = rep.messages[0]
    d = m.semantic.document.values
    assert m.ref == "FV2026100"
    # HDR92/93 follow HDR90 (the specification has no field 91) – element positions must follow field numbers
    assert d["BT-31"][0].value == "SK2020000000" and d["BT-48"][0].value == "SK2021111111"
    assert d["BT-40"][0].how == "explicit" and "BT-80" not in d  # no delivery address -> no derived country
    assert m.rules_info["accepted"]
    assert not [f for f in m.gaps + m.structure + m.values if f.severity == "error"]


def test_ccv_service_line_gtin_warning():
    lines = CCV.decode("cp1250").split("\r\n")
    i = [n for n, l in enumerate(lines) if l.startswith("LIN")][1]
    ln = lines[i]
    lines[i] = ln[:9] + " " * 28 + ln[37:135] + "S  " + ln[138:]  # no EAN, item type S (field LIN8 = 136-138)
    rep = validate("\r\n".join(lines).encode("cp1250"), "ccv.txt", ["billa-sk"], virtual_rules=False)
    sem = rep.messages[0].semantic
    assert [c.aux["item_type"].value for c in sem.groups["BG-25"]] == ["Z", "S"]
    gtin = [(f.severity, f.code) for f in rep.messages[0].gaps if f.bt == "BT-157"]
    assert gtin == [("warning", "GAP-SERVICE")]


# ---------------------------------------------------------------- CCV úpravy vzoru (dobropis, BT-81, zaokrouhlení DPH)
def _ccv_edit(changes: dict) -> bytes:
    """changes: {(tag, field name): value} – applied to every record with that tag (numbers right-aligned)."""
    layout = flat.load_layout("orion_ccv_invoic")
    out = []
    for line in CCV.decode("cp1250").split("\r\n"):
        tag = line[:3]
        for (t, name), val in changes.items():
            if t != tag:
                continue
            f = next(f for f in layout.fields(tag) if f["name"] == name)
            width = f["end"] - f["start"] + 1
            v = val(line[f["start"] - 1:f["end"]].strip()) if callable(val) else val
            v = v.rjust(width) if f["type"] == "Num" else v.ljust(width)
            line = line[:f["start"] - 1] + v + line[f["end"]:]
        out.append(line)
    return "\r\n".join(out).encode("cp1250")


def _neg(v: str) -> str:
    return v if not v or float(v) == 0 else "-" + v


def test_ccv_negative_creditnote_flipped_in_ubl():
    neg = {("LIN", n): _neg for n in ("LIN9", "LIN14")}
    neg |= {("SUM", n): _neg for n in ("SUM3", "SUM4", "SUM5", "SUM8", "SUM9", "SUM10", "SUM13", "SUM30", "SUM34")}
    data = _ccv_edit({("HDR", "HDR5"): "381", ("HDR", "HDR23"): "FV2026001", **neg})
    rep = validate(data, "ccv.txt", ["peppol-bis3", "sk-cius"])
    m = rep.messages[0]
    assert m.semantic.doc_kind == "CreditNote"
    xml = m.virtual_xml.decode("utf-8")
    assert ">-" not in xml and 'PayableAmount currencyID="EUR">146.80<' in xml
    assert any(f.code == "UBL-CONVERSION" and "otočí znaménka" in f.message for f in m.rules)
    assert m.rules_info["accepted"]


def test_ccv_payment_means_derived_from_iban():
    rep = validate(_ccv_edit({("HDR", "HDR14"): ""}), "ccv.txt", ["peppol-bis3", "sk-cius"])
    m = rep.messages[0]
    v = m.semantic.document.values["BT-81"][0]
    assert (v.value, v.how) == ("58", "derived")
    assert m.rules_info["accepted"]


def test_writer_placeholder_payment_means_keeps_xsd_valid():
    from msgvalidator.ubl.writer import write
    rep = validate(_ccv_edit({("HDR", "HDR14"): ""}), "ccv.txt", ["peppol-bis3"], virtual_rules=False)
    sem = rep.messages[0].semantic
    del sem.document.values["BT-81"]
    vdoc = write(sem)
    assert b"<cbc:PaymentMeansCode>1</cbc:PaymentMeansCode>" in vdoc.xml
    assert any("BT-81" in n for n in vdoc.notes)


def test_ccv_vat_rounding_strict_warning():
    # 100.00 × 23 % = 23.00, file says 23.01 – BR-CO-17 tolerates ±1, our strict check must not
    data = _ccv_edit({("SUM", "SUM9"): "23.01", ("SUM", "SUM10"): "26.81",
                      ("SUM", "SUM30"): "146.81", ("SUM", "SUM34"): "146.81"})
    rep = validate(data, "ccv.txt", ["peppol-bis3", "sk-cius"])
    m = rep.messages[0]
    arith = [f for f in m.values if f.code.startswith("ARITH")]
    assert {(f.severity, f.code, f.bt) for f in arith} == {("warning", "ARITH-VAT", "BT-117"),
                                                           ("warning", "ARITH-VAT-TOTAL", "BT-110")}
    assert "správně 23.00" in next(f.message for f in arith if f.code == "ARITH-VAT")
    assert m.rules_info["accepted"]  # official rules let it through – that is the point
    # a correct document has no arithmetic finding
    assert not [f for f in validate(CCV, "ccv.txt", ["peppol-bis3"], virtual_rules=False).messages[0].values
                if f.code.startswith("ARITH")]
