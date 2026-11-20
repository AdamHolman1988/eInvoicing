"""Slovak extended formats: GS1 SK FMCG (Additional Item Property vocabulary), Billa/COOP on top of it, Lidl SK values."""
from msgvalidator import samples
from msgvalidator.profiles.loader import available, load
from msgvalidator.validate import validate

PROPS = (b"<cac:AdditionalItemProperty><cbc:Name>item_type</cbc:Name><cbc:Value>S</cbc:Value></cac:AdditionalItemProperty>"
         b"<cac:AdditionalItemProperty><cbc:Name>delivery_date</cbc:Name><cbc:Value>26.06.2026</cbc:Value></cac:AdditionalItemProperty>"
         b"<cac:AdditionalItemProperty><cbc:Name>Delivery-Note-Number</cbc:Name><cbc:Value>DL1</cbc:Value></cac:AdditionalItemProperty>"
         b"<cac:AdditionalItemProperty><cbc:Name>my_prop</cbc:Name><cbc:Value>x</cbc:Value></cac:AdditionalItemProperty>"
         b"</cac:Item>")


def _gaps(profile_ids, data=None):
    data = data or samples.render("corrected", "ubl")[0]
    rep = validate(data, "x.xml", profile_ids, virtual_rules=False)
    return rep.messages[0].gaps


def test_extended_group_and_inheritance():
    ext = [p["id"] for p in available() if p["group"].startswith("Slovenská transpozice")]
    assert ext[0] == "gs1-sk-fmcg" and {"billa-sk", "coop-sk", "lidl-sk"} <= set(ext)
    assert load("billa-sk").item_properties and load("coop-sk").item_properties
    assert "item_type" in load("gs1-sk-fmcg").item_properties


def test_item_property_vocabulary():
    data = samples.render("corrected", "ubl")[0].replace(b"</cac:Item>", PROPS, 1)
    gaps = _gaps(["gs1-sk-fmcg"], data)
    codes = {(f.code, f.message.split("'")[1]) for f in gaps if f.code.startswith("PROP-")}
    assert ("PROP-TYPE", "delivery_date") in codes
    assert ("PROP-UNKNOWN", "my_prop") in codes
    hint = next(f.hint for f in gaps if f.code == "PROP-UNKNOWN" and "Delivery-Note-Number" in f.message)
    assert "delivery_note_number" in hint
    assert not any(f.code == "PROP-UNKNOWN" and "item_type" in f.message for f in gaps)


def test_item_property_findings_merge_across_profiles():
    data = samples.render("corrected", "ubl")[0].replace(b"</cac:Item>", PROPS, 1)
    gaps = _gaps(["gs1-sk-fmcg", "billa-sk"], data)
    unk = [f for f in gaps if f.code == "PROP-UNKNOWN" and "my_prop" in f.message]
    assert len(unk) == 1 and len(unk[0].profiles) == 2


def test_lidl_values_and_requirements():
    gaps = _gaps(["lidl-sk"])
    by = {(f.code, f.bt) for f in gaps}
    assert ("PROF-VALUE", "BT-48") in by  # sample buyer is not Lidl
    assert ("GAP-MISSING", "BT-16") in by  # delivery note number required
    buyer = next(f for f in gaps if f.code == "PROF-VALUE" and f.bt == "BT-48")
    assert "SK2020279415" in buyer.message
