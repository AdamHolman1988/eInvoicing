"""Slovak IČO / DIČ / IČ DPH shape checks and plain-language explanations."""
from msgvalidator.profiles.checker import Finding
from msgvalidator.report import explain
from msgvalidator.semantic import skids
from msgvalidator.semantic.model import Context, Semantic, Value


def sem(**bts):
    d = Context(None, "doklad", None)
    for bt, v in bts.items():
        scheme = None
        if isinstance(v, tuple):
            v, scheme = v
        d.add(Value(bt.replace("_", "-"), v, scheme=scheme))
    return Semantic("UBL", "x", d, {}, set(), {}, {})


def codes(s):
    return sorted(f.code for f in skids.check(s, Finding))


def test_algorithms():
    assert skids.ico_ok("12345679") and skids.ico_ok("87654326")
    assert not skids.ico_ok("12345678")
    assert skids.dic_ok("2021000003") and not skids.dic_ok("2021000004")


def test_dic_in_ico_field():
    s = sem(BT_40="SK", BT_31="SK2021000003", BT_30="2021000003", BT_55="SK", BT_48="SK2022000002", BT_47="2022000002")
    assert codes(s) == ["VAL-SK-ICO-IS-DIC", "VAL-SK-ICO-IS-DIC"]


def test_valid_slovak_ids_pass():
    s = sem(BT_40="SK", BT_31="SK2021000003", BT_30="12345679", BT_32="2021000003", BT_34=("2021000003", "0245"),
            BT_55="SK", BT_48="SK2022000002", BT_47="87654326", BT_49=("2022000002", "0245"))
    assert codes(s) == []


def test_bad_values():
    s = sem(BT_40="SK", BT_31="SK2021000004", BT_30="12345678", BT_32="12345", BT_34=("123", "0245"))
    assert codes(s) == ["VAL-SK-DIC-FORMAT", "VAL-SK-ENDPOINT", "VAL-SK-ICDPH-CHECK", "VAL-SK-ICO-CHECK"]


def test_non_slovak_party_ignored():
    assert codes(sem(BT_40="CZ", BT_31="CZ12345678", BT_30="1234567890")) == []


def test_explanations():
    assert "§ 3a" in explain.rule("SK-CIUS-BT-33", "warning")
    assert "Podmíněně" in explain.rule("SK-CIUS-BT-999", "warning")
    assert "Bez ní faktura neprojde" in explain.rule("SK-CIUS-BT-999", "fatal")
    assert explain.rule("BR-CO-15", "error") and explain.rule("BR-CO-15", "error", "en")
    assert explain.rule("UNKNOWN-1", "warning") is None
    assert explain.severity("warning").startswith("Dokument projde")
