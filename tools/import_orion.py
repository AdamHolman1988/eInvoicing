"""Generate the ORION XML INVOIC mapping from the vendor documentation spreadsheet.

  python tools/import_orion.py "<...>/ORION3XML-1092026/INVOIC/Dokumentace INVOIC CZE ENG 3.1.3.xlsx"

Output: msgvalidator/data/mappings/orion_invoic.json

Sheet "INVOIC" (row 3 = headers): col 0 field id (SYS1, HDR1 …), col 1 Czech name, col 4 English name,
cols 6–12 XML tag nesting (indentation by column), col 13 mandatory (Yes / No / Optional / Orion / Z),
col 14 Peppol status, col 15 Peppol UBL element + BT id(s), col 16 length, col 17 type, col 18 occurrence.
Sheet "Code_list": code lists (heading row, code rows, "you can use other codes …" = open list).

The spreadsheet describes ORION fields; it cannot say *which* BT a party field means (that depends on the
party qualifier), which ORION fields only feed a derivation, or which BT ids in col 15 are just context.
Those hand fixes live in the clearly separated dicts below (TERMS_OVERRIDE, FIELD_FIXES, CODELIST_OF …).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import openpyxl

OUT = pathlib.Path(__file__).resolve().parents[1] / "msgvalidator" / "data" / "mappings" / "orion_invoic.json"
BT_RE = re.compile(r"\b(B[GT]-\d+(?:-\d+)?)\b")
TAG_RE = re.compile(r"^<(/?)([A-Za-z_][\w.-]*)\s*(/?)>")

# ---------------------------------------------------------------------------------------------------------------
# Hand fixes of the spreadsheet (3.1.3)
# ---------------------------------------------------------------------------------------------------------------

# Obvious typos in the datatype / length columns.
FIELD_FIXES = {
    "HDR49": {"type": "Char"},  # promotion_deal is documented as "Time" (copy-paste), it is a promo code
    "LIN49": {"type": "Char"},
    "LIN48": {"type": "Time", "length": 5},  # reference_number_time documented as Date/10
}

# Container occurrences missing / wrong in col 18.
CONTAINER_FIXES = {
    "body/message_header/skonto": "0-n",  # documented without occurrence (the "1-n" sits on the counter field)
}

# Elements that exist in the official XSD but are not documented in the spreadsheet.
EXTRA_ELEMENTS = {
    "body/line_items/item/allowances_and_charges/charge/charge_sequence": {"type": "Num", "since": "3.1.1",
                                                                          "note": "jen v XSD 3.1.1"},
}

# Version in which an element was introduced (sheet "Changelog"); used for an info finding when a message
# declares an older version than the elements it uses.
SINCE = {
    "recycling_fee": "3.0.1", "author_fee": "3.0.1",
    "id_add_yc1": "3.0.2",
    "skonto": "3.0.3",
    "orion_url": "3.0.4",
    "order_line": "3.0.5",
    "customs_tarif_number": "3.0.6", "total_weight": "3.0.6", "weight_unit": "3.0.6",
    "expiry_date": "3.0.8",
    "legislation_free_text": "3.1.0",
    "skonto_maturity_date_type": "3.1.1", "skonto_maturity_date_value": "3.1.1",
}
SINCE_PATHS = {  # same tag name exists elsewhere earlier – restrict to these paths
    "body/summary/allowances_and_charges/allowance/allowance_code": "3.1.2",
    "body/summary/allowances_and_charges/charge/charge_code": "3.1.2",
}

# Field id -> code list (section of sheet "Code_list", by Czech heading prefix) or an inline list.
CODELIST_OF = {
    "HDR2": "Druh dokladu", "HDR3": "Funkce zprávy", "HDR11": "Způsob úhrady",
    "HDR12": "Kód měny", "HDR13": "Kód měny",
    "HDR20": "Země původu", "LIN25": "Země původu", "HDRNAD8": "Země původu", "LINNAD8": "Země původu",
    "HDR39": "Význam referenčního", "LIN45": "Význam referenčního",
    "HDR50": "Speciální podmínky", "LIN26": "Speciální podmínky",
    "HDRNAD1": "Kvalifikátor obchodního", "LINNAD1": "Kvalifikátor obchodního",
    "LIN5": "Kód typu identifikace", "LIN9": "Typ položky", "LIN19": "Měrné jednotky",
    "SUMVAT01": "Daňové skupiny", "SUMALC01": "Daňové skupiny", "SUMALC11": "Daňové skupiny",
}
AN = {"name": "A/N", "codes": {"A": "ano", "N": "ne"}, "open": False}
INLINE_CODELISTS = {  # lists that are only described in the notes column / the XSD
    "SYS8": {"name": "Testovací příznak", "codes": {"0": "ostrá", "1": "testovací"}, "open": False},
    "HDR19": AN, "LIN24": AN, "SUMVAT05": AN, "SUMVAT06": AN,
    "LINLAC9": {"name": "Kód přirážky (UNCL 7161)", "codes": {"AEO": "recyklační příspěvek", "AEP": "autorský poplatek"},
                "open": True},
    "ADV3": {"name": "Typ zálohy", "codes": {"A": "záloha", "C": "storno zálohy"}, "open": False},
}
EXTRA_CODES = {"Typ položky": {"TAN": "(jen v XSD)"}}  # codes allowed by the XSD but missing in Code_list

# Repeating EN 16931 groups and where they live in ORION (paths relative to <orion_message>).
GROUPS = {
    "BG-20": {"each": "body/summary/allowances_and_charges/allowance"},
    "BG-21": {"each": "body/summary/allowances_and_charges/charge"},
    "BG-23": {"each": "body/summary/tax_details/vat"},
    "BG-25": {"each": "body/line_items/item"},
    "BG-27": {"each": "body/line_items/item/allowances_and_charges/allowance", "parent": "BG-25"},
    "BG-28": {"each": "body/line_items/item/allowances_and_charges/charge", "parent": "BG-25"},
}

# Helper facts outside EN 16931, read per group instance (checker uses item_type S = service).
AUX = {"item_type": {"group": "BG-25", "rules": [{"field": "LIN9"}]}}

SELLER, BUYER, DELIVERY = "SE|SU", "BY|IV", "DP"
CONST_23 = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
CONST_24 = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
UNITS = {"PCE": "H87", "PCS": "H87", "KS": "H87", "KAR": "CT", "CAR": "CT", "KRT": "CT", "BAL": "PK", "PAL": "PF",
         "KG": "KGM", "L": "LTR", "M": "MTR"}

# BT -> ordered rules (first rule that yields a value wins; 'fields' collects all of them).
# Fields with exactly one BT in col 15 and no entry here are mapped 1:1 automatically.
# Rule keys: field | fields | party (qualifiers, preference order) | scheme | map | derive | args | const | note
TERMS_OVERRIDE: dict[str, list[dict]] = {
    "BT-3": [{"field": "HDR2", "map": {"83": "381", "84": "383"},
              "note": "83/84 (finanční dobropis/vrubopis) převedeno na 381/383."}],
    "BT-6": [{"field": "HDR13"}],
    "BT-20": [{"derive": "payment_terms_text",
               "note": "Skonto (HDR52–54, HDR67–68, sekce skonto) Peppol nese jen jako text platebních podmínek."}],
    "BT-22": [{"fields": ["HDR18", "HDR51", "HDR55", "HDR56", "HDR57", "HDR58", "HDR59", "HDR60", "HDR61", "HDR62",
                          "HDR63", "HDR64"]}],
    "BT-23": [{"const": CONST_23, "note": "Doplní konverze (Profile ID)."}],
    "BT-24": [{"const": CONST_24, "note": "Doplní konverze (Customization ID)."}],
    "BT-73": [{"field": "HDR8"}],
    "BT-74": [{"field": "HDR9"}],
    # ---- seller (SE, else SU)
    "BT-27": [{"field": "HDRNAD4", "party": SELLER}],
    "BT-29": [{"field": "HDRNAD2", "party": SELLER, "scheme": "0088"}],
    "BT-30": [{"field": "HDRNAD10", "party": SELLER}],
    "BT-31": [{"field": "HDRNAD11", "party": SELLER}],
    "BT-32": [{"field": "HDRNAD12", "party": SELLER, "note": "SK DIČ (vat_id) prodávajícího."},
              {"derive": "sk_tax_id_from_vat", "args": {"party": SELLER},
               "note": "SK DIČ chybí (vat_id); odvozeno z IČ DPH bez prefixu SK."}],
    "BT-33": [{"field": "HDR17", "note": "Spisová značka (zápis v OR) – v Peppol 'Seller additional legal information'."}],
    "BT-34": [{"derive": "endpoint_from_party", "args": {"party": SELLER},
               "note": "Peppol endpoint ORION nenese; odvozeno z GLN (0088). V SK se typicky používá DIČ (0245) – ověřte SMP."}],
    "BT-35": [{"field": "HDRNAD5", "party": SELLER}],
    "BT-37": [{"field": "HDRNAD6", "party": SELLER}],
    "BT-38": [{"field": "HDRNAD7", "party": SELLER}],
    "BT-40": [{"field": "HDRNAD8", "party": SELLER},
              {"derive": "country_from_vat", "args": {"party": SELLER}, "note": "Kód země chybí; odvozeno z prefixu DIČ."}],
    "BT-41": [{"field": "HDRNAD14", "party": SELLER}],
    "BT-42": [{"field": "HDRNAD15", "party": SELLER}],
    "BT-43": [{"field": "HDRNAD17", "party": SELLER}],
    # ---- buyer (BY, else invoicee IV)
    "BT-44": [{"field": "HDRNAD4", "party": BUYER}],
    "BT-46": [{"field": "HDRNAD2", "party": BUYER, "scheme": "0088"}],
    "BT-47": [{"field": "HDRNAD10", "party": BUYER}],
    "BT-48": [{"field": "HDRNAD11", "party": BUYER}],
    "BT-49": [{"derive": "endpoint_from_party", "args": {"party": BUYER},
               "note": "Peppol endpoint ORION nenese; odvozeno z GLN (0088). Ověřte registraci kupujícího v SMP."}],
    "BT-50": [{"field": "HDRNAD5", "party": BUYER}],
    "BT-52": [{"field": "HDRNAD6", "party": BUYER}],
    "BT-53": [{"field": "HDRNAD7", "party": BUYER}],
    "BT-55": [{"field": "HDRNAD8", "party": BUYER},
              {"derive": "country_from_vat", "args": {"party": BUYER}, "note": "Kód země chybí; odvozeno z prefixu DIČ."}],
    "BT-56": [{"field": "HDRNAD14", "party": BUYER}],
    "BT-57": [{"field": "HDRNAD15", "party": BUYER}],
    "BT-58": [{"field": "HDRNAD17", "party": BUYER}],
    # ---- delivery (DP)
    "BT-70": [{"field": "HDRNAD4", "party": DELIVERY}],
    "BT-71": [{"field": "HDRNAD2", "party": DELIVERY, "scheme": "0088"}],
    "BT-75": [{"field": "HDRNAD5", "party": DELIVERY}],
    "BT-77": [{"field": "HDRNAD6", "party": DELIVERY}],
    "BT-78": [{"field": "HDRNAD7", "party": DELIVERY}],
    "BT-80": [{"field": "HDRNAD8", "party": DELIVERY}],
    # ---- payment (bank details of the seller party)
    "BT-83": [{"field": "HDRNAD24", "party": SELLER, "note": "Variabilní symbol."}],
    "BT-84": [{"field": "HDRNAD21", "party": SELLER},
              {"field": "HDRNAD18", "party": SELLER,
               "note": "Použito národní číslo účtu (ne IBAN) – pro kód úhrady 58 (SEPA) je vyžadován IBAN."}],
    "BT-86": [{"field": "HDRNAD22", "party": SELLER},
              {"field": "HDRNAD19", "party": SELLER, "note": "Použit směrový kód banky (ne BIC/SWIFT)."}],
    # ---- document allowances / charges (BG-20 / BG-21)
    "BT-95": [{"derive": "ac_category", "args": {"field": "SUMALC01"},
               "note": "ORION nese daňovou skupinu (0/1/1.2/2), ne kategorii DPH; odvozeno ze sazby skupiny."}],
    "BT-96": [{"derive": "ac_rate", "args": {"field": "SUMALC01"}, "note": "Sazba převzata z rozpisu DPH dané daňové skupiny."}],
    "BT-102": [{"derive": "ac_category", "args": {"field": "SUMALC11"},
                "note": "ORION nese daňovou skupinu (0/1/1.2/2), ne kategorii DPH; odvozeno ze sazby skupiny."}],
    "BT-103": [{"derive": "ac_rate", "args": {"field": "SUMALC11"}, "note": "Sazba převzata z rozpisu DPH dané daňové skupiny."}],
    # ---- VAT breakdown (BG-23)
    "BT-118": [{"derive": "vat_category",
                "note": "ORION nese daňovou skupinu a příznak přenesené povinnosti, ne kategorii DPH (UNCL5305); "
                        "odvozeno: reverse_charge=A → AE, sazba > 0 → S, sazba 0 / skupina 0 → E (nejednoznačné)."}],
    "BT-121": [{"derive": "vat_exemption_code",
                "note": "ORION nenese důvod osvobození; pro přenesenou daňovou povinnost (AE) konverze doplní VATEX-EU-AE."}],
    # ---- lines (BG-25)
    "BT-130": [{"field": "LIN19", "map": UNITS, "note": "Jednotka převedena z EANCOM kódu na UN/ECE Rec 20."}],
    "BT-151": [{"derive": "line_vat_category",
                "note": "Kategorie DPH řádku ORION nenese; odvozena ze sazby a příznaku přenesené povinnosti."}],
    "BT-155": [{"field": "LIN3"}, {"derive": "article_id_add", "args": {"type": "SA"}}],
    "BT-156": [{"field": "LIN4"}, {"derive": "article_id_add", "args": {"type": "IN"}}],
    "BT-157": [{"field": "LIN2", "scheme": "0160"}],
    "BT-158": [{"field": "LIN57", "scheme": "HS", "note": "Celní sazebník (HS)."}],
    # ---- line allowances (BG-27) / charges (BG-28)
    "BT-136": [{"field": "LINALC3"}], "BT-138": [{"field": "LINALC2"}], "BT-139": [{"field": "LINALC1"}],
    "BT-141": [{"field": "LINALC7"}], "BT-143": [{"field": "LINALC6"}], "BT-144": [{"field": "LINALC5"}],
    "BT-145": [{"field": "LINLAC9", "note": "AEO = recyklační poplatek, AEP = autorský poplatek (UNCL7161)."}],
    # ---- document allowances / charges amounts
    "BT-92": [{"field": "SUMALC04"}], "BT-94": [{"field": "SUMALC03"}], "BT-97": [{"field": "SUMALC02"}],
    "BT-98": [{"field": "SUMALC06"}], "BT-99": [{"field": "SUMALC14"}], "BT-101": [{"field": "SUMALC13"}],
    "BT-104": [{"field": "SUMALC12"}], "BT-105": [{"field": "SUMALC16"}],
}

# Fields whose col-15 BT ids are deliberately NOT mapped 1:1 (explanation shown in the mapping file).
NOT_MAPPED = {
    "HDR19": "Přenesená daňová povinnost – použito jen pro odvození kategorie DPH AE (BT-118/BT-151).",
    "LIN24": "Přenesená daňová povinnost na řádku – použito pro odvození kategorie AE (BT-151).",
    "SUMVAT05": "Přenesená daňová povinnost ve skupině DPH – použito pro odvození kategorie AE (BT-118).",
    "SUMVAT01": "Daňová skupina (0/1/1.2/2) není kategorie DPH – BT-118 se odvozuje.",
    "SUMVAT06": "Příznak DPH v místní měně – BT-111 ORION nenese jako částku.",
    "SUMALC01": "Daňová skupina slevy – BT-95/BT-96 se odvozují přes rozpis DPH.",
    "SUMALC11": "Daňová skupina přirážky – BT-102/BT-103 se odvozují přes rozpis DPH.",
    "LIN5": "Typ doplňkového čísla zboží (SA/IN/NB …) není klasifikace (BT-158); SA/IN použity pro BT-155/156.",
    "LIN6": "Doplňkové číslo zboží – viz LIN5.",
    "LIN9": "Typ položky Z/O/S není klasifikace dle UNCL7143 – nemapováno na BT-158.",
    "LIN12": "Procento slevy z ceny (BT-147-1) není v syntax bindingu Peppol UBL.",
    "HDR65": "orion_url (BT-124) obsahuje přihlašovací údaje (login/pwd) a v Peppol by vyžadoval BG-24 s BT-122 – nemapováno.",
    "LIN61": "Certifikace – v Peppol jen jako dvojice název/hodnota (BT-160/161), konverze by musela doplnit název.",
    "HDRNAD1": "Kvalifikátor partnera – určuje roli (SE/SU prodávající, BY/IV kupující, DP místo dodání).",
    "HDRNAD2": "GLN partnera – BT podle role (BT-29/BT-46/BT-71), endpoint BT-34/BT-49 se odvozuje.",
    "HDRNAD26": "Doplňková identifikace partnera (id v systému protistrany) – v Peppol bez jednoznačného BT.",
    "HDR52": "Skonto – jen textově v BT-20 (odvozeno).", "HDR53": "Skonto – jen textově v BT-20 (odvozeno).",
    "HDR54": "Skonto – jen textově v BT-20 (odvozeno).", "HDR67": "Skonto – jen textově v BT-20 (odvozeno).",
    "HDR68": "Skonto – jen textově v BT-20 (odvozeno).", "HDRSKT02": "Skonto – jen textově v BT-20 (odvozeno).",
    "HDRSKT03": "Skonto – jen textově v BT-20 (odvozeno).", "HDRSKT04": "Skonto – jen textově v BT-20 (odvozeno).",
}

MANDATORY = {"yes": "yes", "ano": "yes", "no": "no", "ne": "no", "optional": "no", "orion": "orion", "z": "agreement"}


def clean(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else None


def parse_codelists(ws) -> dict:
    lists, cur = {}, None
    for r in ws.iter_rows(min_row=3, values_only=True):
        c0, c1 = clean(r[0]), clean(r[1])
        if not c0 and not c1:
            cur = None
            continue
        if cur is None:
            cur = {"name": c0, "codes": {}, "open": False}
            lists[c0] = cur
            continue
        if c0 and c1 and len(c0) <= 4:
            cur["codes"][c0] = c1
        elif c0:  # "Lze použít i jiné kódy …", "Dle ISO 3166 …" – the list is only a selection
            cur["open"] = True
            cur.setdefault("note", c0)
    for name, extra in EXTRA_CODES.items():
        for k, cl in lists.items():
            if k.startswith(name):
                cl["codes"].update(extra)
    return lists


def parse_length(v):
    v = clean(v)
    if not v:
        return None, None
    whole, _, dec = v.partition(".")
    return (int(whole) if whole.isdigit() else None), (int(dec) if dec.isdigit() else None)


def main(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["INVOIC"]
    codelists = parse_codelists(wb["Code_list"])
    title = clean(ws.cell(1, 1).value) or ""
    changelog = [clean(r[0]) for r in wb["Changelog"].iter_rows(min_row=3, values_only=True) if clean(r[0])]
    version = changelog[-1] if changelog else None

    fields, containers = [], {}
    stack: list[tuple[int, str]] = []
    for r in ws.iter_rows(min_row=4, values_only=True):
        r = list(r) + [None] * 25
        cell = next(((i, clean(r[i])) for i in range(6, 13) if clean(r[i])), None)
        if not cell:
            continue
        depth, txt = cell[0] - 6, cell[1]
        m = TAG_RE.match(txt)
        if not m:
            continue
        closing, tag, selfclose = m.group(1), m.group(2), m.group(3)
        if closing:
            continue
        while stack and stack[-1][0] >= depth:
            stack.pop()
        parents = [t for _, t in stack]
        if tag == "orion_message":
            stack.append((depth, tag))
            continue
        rel = "/".join([p for p in parents if p != "orion_message"] + [tag])
        is_container = not selfclose and f"</{tag}>" not in txt and clean(r[0]) is None
        occ = clean(r[18])
        if is_container:
            occ = CONTAINER_FIXES.get(rel, occ)
            containers[rel] = {"path": rel, "occurrence": occ or "1",
                               "repeating": bool(occ and re.search(r"-(n|\d+)$", occ) and not occ.endswith("-1")),
                               "mandatory": MANDATORY.get((clean(r[13]) or "").lower())}
            stack.append((depth, tag))
            continue
        fid = clean(r[0])
        length, decimals = parse_length(r[16])
        f = {
            "id": fid, "path": rel, "tag": tag,
            "name_cs": clean(r[1]), "name_en": clean(r[4]),
            "mandatory": MANDATORY.get((clean(r[13]) or "").lower(), "no"),
            "mandatory_raw": clean(r[13]),
            "peppol": clean(r[14]), "peppol_mapping": clean(r[15]),
            "bts_doc": sorted({b for b in BT_RE.findall(clean(r[15]) or "") if b.startswith("BT")},
                              key=lambda b: [int(x) for x in b[3:].split("-")]),
            "length": length, "decimals": decimals, "type": clean(r[17]), "occurrence": occ,
        }
        f.update(FIELD_FIXES.get(fid, {}))
        fields.append(f)

    # repeating container membership + "since" versions + code lists
    rep = sorted((c for c in containers.values() if c["repeating"]), key=lambda c: -len(c["path"]))
    for f in fields:
        f["group"] = next((c["path"] for c in rep if f["path"].startswith(c["path"] + "/")), None)
        f["since"] = SINCE_PATHS.get(f["path"]) or SINCE.get(f["tag"])
        cl = INLINE_CODELISTS.get(f["id"])
        if cl is None and f["id"] in CODELIST_OF:
            cl = next((v for k, v in codelists.items() if k.startswith(CODELIST_OF[f["id"]])), None)
            if cl is None:
                raise SystemExit(f"Code list '{CODELIST_OF[f['id']]}' not found in sheet Code_list")
        if cl:
            f["codelist"] = cl["name"]
        if f["id"] in NOT_MAPPED:
            f["not_mapped"] = NOT_MAPPED[f["id"]]
    for c in containers.values():
        c["since"] = SINCE.get(c["path"].rsplit("/", 1)[-1])
    for p, extra in EXTRA_ELEMENTS.items():
        fields.append({"id": None, "path": p, "tag": p.rsplit("/", 1)[-1], "mandatory": "no", "bts_doc": [],
                       "length": None, "decimals": None, "occurrence": "0-1",
                       "group": next((c["path"] for c in rep if p.startswith(c["path"] + "/")), None), **extra})

    # terms: automatic 1:1 + overrides
    by_id = {f["id"]: f for f in fields if f["id"]}
    terms: dict[str, list[dict]] = {}
    overridden_fields = {r.get("field") for rules in TERMS_OVERRIDE.values() for r in rules} | \
                        {x for rules in TERMS_OVERRIDE.values() for r in rules for x in r.get("fields", [])}
    for f in fields:
        if not f["id"] or f["id"] in NOT_MAPPED or f["id"] in overridden_fields or f["group"] and "party" in f["group"]:
            continue
        if len(f["bts_doc"]) == 1:
            terms.setdefault(f["bts_doc"][0], []).append({"field": f["id"]})
    terms.update(TERMS_OVERRIDE)
    for bt, rules in terms.items():
        for r in rules:
            for fid in ([r["field"]] if "field" in r else []) + r.get("fields", []) + \
                       ([r["args"]["field"]] if "field" in r.get("args", {}) else []):
                if fid not in by_id:
                    raise SystemExit(f"{bt}: unknown field {fid}")
    for f in fields:
        if not f["id"]:
            f["bts"] = []
            continue
        f["bts"] = sorted({bt for bt, rules in terms.items() for r in rules
                           if r.get("field") == f["id"] or f["id"] in r.get("fields", [])},
                          key=lambda b: [int(x) for x in b[3:].split("-")])

    used_lists = {f["codelist"] for f in fields if f.get("codelist")}
    out = {
        "id": "orion-invoic",
        "format": "ORION XML",
        "message": "INVOIC",
        "source": pathlib.Path(path).name,
        "title": title,
        "version": version,
        "versions": [v for v in dict.fromkeys(changelog) if v.startswith("3.")],
        "generated_by": "tools/import_orion.py",
        "groups": GROUPS,
        "containers": sorted(containers.values(), key=lambda c: c["path"]),
        "fields": fields,
        "codelists": {k: v for k, v in [(cl["name"], cl) for cl in codelists.values()] + \
                      [(cl["name"], cl) for cl in INLINE_CODELISTS.values()] if k in used_lists},
        "terms": dict(sorted(terms.items(), key=lambda kv: [int(x) for x in kv[0][3:].split("-")])),
        "aux": AUX,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    mapped = [f for f in fields if f["bts"]]
    doc_bt = [f for f in fields if f["bts_doc"]]
    print(f"{OUT.name}: {len(fields)} fields, {len(containers)} containers, {len(terms)} BTs, "
          f"{len(mapped)} fields mapped, {len(doc_bt)} fields with BT in documentation, version {version}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
