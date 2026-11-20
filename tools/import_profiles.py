"""Generate requirement profiles from the analyst spreadsheets.

  python tools/import_profiles.py sk   "<...>/2026.10.29_Peppol_Bis3_v1_13.xlsx"
  python tools/import_profiles.py gs1   "<...>/PEPPOL-BIS3.0_SK_FMCG.xlsx"   (GS1 SK/CZ guideline, generic FMCG)
  python tools/import_profiles.py billa "<...>/1. Billa poziadavky - PEPPOL-BIS3.0_SK_FMCG_version_v1.10_BILLA_SK.xlsx"

Output: msgvalidator/data/profiles/<id>.json
Levels: required | conditional | optional
"""
import json
import pathlib
import re
import sys

import openpyxl

OUT = pathlib.Path(__file__).resolve().parents[1] / "msgvalidator" / "data" / "profiles"
BT_RE = re.compile(r"\b(B[GT]-\d+(?:-\d+)?)\b")


def norm_id(t):
    """BG-04 -> BG-4 (catalogue uses unpadded ids)."""
    kind, _, rest = t.partition("-")
    return kind + "-" + "-".join(str(int(x)) for x in rest.split("-"))


def clean(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else None


def sk_level(v):
    v = (clean(v) or "").lower()
    if v.startswith("vyžaduje"):
        return "required"
    if v.startswith("podmien"):
        return "conditional"
    return "optional"


def import_sk(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Obchod. term.(legis.) validácia"]
    req = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        tid = clean(r[12])
        if not tid or not BT_RE.fullmatch(tid):
            continue
        tid = norm_id(tid)
        if tid in req:
            # the sheet repeats the BT id on the scheme-identifier row ("Identifikátor schémy") – it is BT-x-1,
            # it must not overwrite the level of the term itself (e.g. BT-157 optional, its scheme required)
            if tid.count("-") > 1 or f"{tid}-1" in req:
                continue
            tid = f"{tid}-1"
        level = sk_level(r[17])
        req[tid] = {"level": level, "name_sk": clean(r[18]),
                    "note": clean(r[23]) if level != "optional" else None,
                    "extension": clean(r[10]) not in (None, "Norma")}
    version = next((clean(c) for row in wb["Úvod"].iter_rows(max_row=12, values_only=True)
                    for c in row if c and "Verzia" in str(c)), "")
    return {"id": "sk-cius", "name": "SK CIUS – transpozícia Peppol BIS 3.0",
            "description": f"Slovenská transpozícia Peppol BIS Billing 3.0 ({version}), stĺpec 'Povinná náležitosť faktúry'.",
            "source": pathlib.Path(path).name, "extends": ["peppol-bis3"], "requirements": req}


EXT_GROUP = "Slovenská transpozice – rozšířené formáty"


def gs1_level(v):
    v = (clean(v) or "").lower()
    if v.startswith("vyžaduje") or v.startswith("vyžaduje"):
        return "required"
    if v.startswith("podmien"):
        return "conditional"
    return None


def import_gs1(path):
    """GS1 SK/CZ 'PEPPOL-BIS3.0_SK_FMCG' guideline: SK CIUS levels + the AdditionalItemProperty vocabulary."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["INVOIC_D01B_BIS3.0"]
    req = {}
    for r in ws.iter_rows(min_row=3, values_only=True):
        ids = BT_RE.findall(str(r[4] or ""))
        level = gs1_level(r[7])
        if not ids or not level or "/" in str(r[7] or ""):
            continue  # "vyžaduje sa/nevyžaduje sa" rows (BT-136 vs BT-147) depend on the variant – skip
        note = clean(r[15]) if clean(r[15]) not in (None, "-") else None
        for tid in map(norm_id, ids):
            if tid in ("BT-160", "BT-161"):
                continue
            prev = req.get(tid)
            if prev and (prev["level"] == "required" or level == "conditional"):
                continue
            req[tid] = {"level": level, "note": note if level == "conditional" else None,
                        "var": clean(r[0]), "name_sk": clean(r[1])}
    props = {}
    for r in wb["AdditionalItemProperty"].iter_rows(values_only=True):
        name, typ = clean(r[0]), clean(r[1]) if len(r) > 1 else None
        if name and typ in ("char", "num", "date") and re.fullmatch(r"[a-z0-9_]+", name):
            note = clean(r[3]) if len(r) > 3 else None
            props[name] = {"type": typ, "name_sk": clean(r[2]),
                           "note": note if note and not note.startswith("<") else None}
    version = ""
    for row in wb["Overview"].iter_rows(values_only=True):
        for c in row:
            if isinstance(c, str) and re.fullmatch(r"v\d+\.\d+", c.strip()):
                version = c.strip()
    return {"id": "gs1-sk-fmcg", "name": f"GS1 SK FMCG (Peppol BIS 3.0 SK FMCG {version})",
            "group": EXT_GROUP,
            "description": f"Implementační příručka GS1 Slovakia / GS1 Czech Republic pro FMCG ({version}): "
                           "úrovně SK CIUS a slovník Additional Item Property (BT-160/161).",
            "source": pathlib.Path(path).name, "extends": ["sk-cius"], "requirements": req,
            "item_properties": props}


def import_retailer(path, pid, name):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["INVOIC_D01B_BIS3.0"]
    req = {}
    for r in ws.iter_rows(min_row=3, values_only=True):
        ids = BT_RE.findall(str(r[4] or ""))
        flag = clean(r[8]) or ""
        if not ids:
            continue
        if flag.lower().startswith("áno"):
            level, note = "required", None
        elif flag.lower().startswith("podmiene"):
            level, note = "conditional", flag
        else:
            continue
        for tid in map(norm_id, ids):
            prev = req.get(tid)
            if prev and prev["level"] == "required":
                continue
            req[tid] = {"level": level, "note": note, "var": clean(r[0]), "name_sk": clean(r[1])}
            if note and "dobropis" in note.lower():
                req[tid]["when"] = ["CreditNote"]
    return {"id": pid, "name": name,
            "description": f"Požiadavky retailera nad rámec SK CIUS (stĺpec 'Požadované pre ...') – {pathlib.Path(path).name}",
            "source": pathlib.Path(path).name, "group": EXT_GROUP, "extends": ["gs1-sk-fmcg"],
            "requirements": req}


def main(kind, path):
    if kind == "sk":
        prof = import_sk(path)
    elif kind == "gs1":
        prof = import_gs1(path)
    elif kind == "billa":
        prof = import_retailer(path, "billa-sk", "BILLA SK (Peppol BIS 3.0 SK FMCG)")
    else:
        raise SystemExit(f"unknown kind {kind}")
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"{prof['id']}.json"
    dst.write_text(json.dumps(prof, ensure_ascii=False, indent=1), encoding="utf-8")
    lv = {}
    for v in prof["requirements"].values():
        lv[v["level"]] = lv.get(v["level"], 0) + 1
    print(prof["id"], lv, "->", dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
