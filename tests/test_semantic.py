from msgvalidator.edifact import parser, structure
from msgvalidator.semantic.extract import extract
from msgvalidator.semantic.selector import select


def _sem(data):
    msg = parser.parse(data).messages[0]
    tree, _ = structure.match(msg)
    return extract(msg, tree, "edifact_invoic_eancom")


def first(ctx, bt):
    return ctx.values[bt][0]


def test_header_values(d01b_example):
    doc = _sem(d01b_example).document
    assert first(doc, "BT-1").value == "432097"
    assert first(doc, "BT-2").value == "2015-01-15"
    assert first(doc, "BT-5").value == "CZK"
    assert first(doc, "BT-31").value == "CZ66753252"
    assert first(doc, "BT-48").value == "CZ14999421"
    assert first(doc, "BT-84").value == "CZ5408000000000078078022"
    assert first(doc, "BT-24").how == "const"
    assert first(doc, "BT-34").how == "derived" and first(doc, "BT-34").scheme == "0088"


def test_line_values(d01b_example):
    sem = _sem(d01b_example)
    lines = sem.groups["BG-25"]
    assert [ln.label for ln in lines] == ["řádek 1", "řádek 2"]
    l1 = lines[0]
    assert first(l1, "BT-157").value == "18595226800071"
    assert first(l1, "BT-153").value == "Syreček STANDARD"
    assert first(l1, "BT-129").value == "100"
    assert first(l1, "BT-151").how == "derived" and first(l1, "BT-151").value == "S"
    assert first(l1, "BT-147").value == "5"


def test_vat_breakdown_reverse_charge(d96a_example):
    sem = _sem(d96a_example)
    labels = [c.label for c in sem.groups["BG-23"]]
    assert "DPH 15 % AE" in labels
    ae = next(c for c in sem.groups["BG-23"] if c.label == "DPH 15 % AE")
    assert first(ae, "BT-118").value == "AE"
    assert first(ae, "BT-117").how == "derived" and first(ae, "BT-117").value == "0"


def test_selector_conditions(d01b_example):
    msg = parser.parse(d01b_example).messages[0]
    tree, _ = structure.match(msg)
    assert len(select([tree], "NAD[1.1=BY] > RFF[1.1=VA]")) == 1
    assert select([tree], "NAD[1.1=XX]") == []


def test_service_reason_type_wins_over_name():
    from msgvalidator.profiles.checker import service_reason
    from msgvalidator.semantic.model import Context, Value
    ln = Context("BG-25", "řádek 1", 1)
    ln.add(Value("BT-153", "Dopravné"))
    assert service_reason(ln) == "podle názvu položky"
    ln.aux["item_type"] = Value("aux", "Z")
    assert service_reason(ln) is None  # explicit goods type beats the name
    ln.aux["item_type"] = Value("aux", "S")
    assert service_reason(ln) == "typ položky S"
    assert service_reason(Context(None, "doklad", 1)) is None
