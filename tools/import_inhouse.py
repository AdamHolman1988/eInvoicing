"""Import an EDITEL INHOUSE fixed-width specification (xlsx) into a layout JSON.

    python tools/import_inhouse.py "<...>/Specifikace_Inhouse_INVOIC_D01B_2012.xlsx" editel_inhouse_invoic_d01b

Only field positions/types/names are taken over (the spreadsheet itself stays in Dokumentace).
Known errors of the spreadsheet are corrected in FIXES (wrong variable names, 'Date' types of text fields).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import openpyxl

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "msgvalidator" / "data" / "flat"

VAR_RE = re.compile(r"^[A-Z][A-Z0-9_\-]*$")

# (record, field no.) -> overrides
FIXES = {
    ("HDR", 51): {"name": "IBAN"},  # spreadsheet says NAZEV_BANKY (copy/paste error)
    ("HDR", 62): {"name": "PRENES_DPH"},
    ("HDR", 63): {"name": "INT_KOD_DODAV"},
    ("NAD", 12): {"name": "ADR_UL_4"},
    ("LIN", 54): {"type": "Char"},
    ("LIN", 57): {"type": "Char"},
    ("LIN", 60): {"name": "L_PRENES_DPH"},
    ("LIN", 61): {"name": "L_RECYKL_CELK"},
    ("LIN", 62): {"name": "L_AUTOR_CELK"},
    ("LIN", 63): {"name": "L_RECYKL_JEDN"},
    ("LIN", 64): {"name": "L_AUTOR_JEDN"},
    ("LIN", 65): {"name": "L_RECYKL_MJ"},
    ("LIN", 66): {"name": "L_AUTOR_MJ"},
    ("LIN", 67): {"name": "L_RECYKL_TYP"},
    ("LIN", 68): {"name": "L_AUTOR_TYP"},
}

# order of records in a message, occurrences, nesting (from the section headers of the spreadsheet)
STRUCTURE = [
    {"tag": "SYS", "min": 0, "max": 1},
    {"tag": "HDR", "min": 1, "max": 1},
    {"tag": "NAD", "min": 2, "max": 9},
    {"tag": "ALC", "min": 0, "max": 20},
    {"tag": "LIN", "min": 1, "max": 25000, "children": [{"tag": "LAC", "min": 0, "max": 20}]},
    {"tag": "AAI", "min": 1, "max": 1},
    {"tag": "SUR", "min": 0, "max": 1},
    {"tag": "ZZZ", "min": 0, "max": 1},
    {"tag": "AAW", "min": 0, "max": 1},
    {"tag": "SUM", "min": 1, "max": 1, "summary": True},
]

SYS = {"label": "Systémový záznam", "fields": [
    {"n": 1, "name": "TAG", "label": "uvození SYS", "type": "Char", "start": 1, "end": 3, "req": True},
    {"n": 2, "name": "PARTNER_EAN", "label": "Identifikace partnera (EAN)", "type": "Char", "start": 4, "end": 17, "req": True},
    {"n": 3, "name": "STANDARD", "label": "Standard (E)", "type": "Char", "start": 18, "end": 18, "req": True},
    {"n": 4, "name": "VERZE", "label": "Verze (D  01B)", "type": "Char", "start": 19, "end": 24, "req": True},
    {"n": 5, "name": "ZPRAVA", "label": "Zpráva (INVOIC)", "type": "Char", "start": 25, "end": 30, "req": True},
    {"n": 6, "name": "TEST", "label": "Test identifikátor (T/P)", "type": "Char", "start": 31, "end": 31, "req": True},
]}


def _len(v) -> tuple[int, int | None]:
    s = str(v).replace(".", ",")
    a, _, b = s.partition(",")
    return int(float(a)), (int(b) if b else None)


def build(xlsx: pathlib.Path, layout_id: str) -> dict:
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = next(w for w in wb.worksheets if w.title.startswith("Specifikace"))
    records: dict[str, dict] = {"SYS": SYS}
    cur = None
    for r in ws.iter_rows(values_only=True):
        r = list(r) + [None] * 12
        if isinstance(r[0], str) and re.fullmatch(r"[A-Z]{3}", r[0].strip()) and str(r[2]).strip() == "Typ":
            cur = r[0].strip()
            records[cur] = {"label": str(r[1]).strip(), "fields": []}
            continue
        if cur is None or not isinstance(r[0], int) or not isinstance(r[4], int):
            continue
        n = r[0]
        length, dec = _len(r[3])
        var = str(r[9]).strip() if r[9] else ""
        note = str(r[11]).strip() if r[11] else ""
        if var and not VAR_RE.match(var):
            note, var = (var + (" " + note if note else "")).strip(), ""
        f = {"n": n, "name": "TAG" if n == 1 else (var or f"F{n}"), "label": str(r[1]).strip(),
             "type": str(r[2]).strip(), "start": r[4], "end": r[6] if isinstance(r[6], int) else r[4] + length - 1,
             "req": str(r[8]).strip().startswith("P"), "cond": str(r[8]).strip() == "P*"}
        if dec is not None:
            f["dec"] = dec
        if r[10]:
            f["mig"] = str(r[10]).strip()
        if note:
            f["note"] = note
        f.update(FIXES.get((cur, n), {}))
        records[cur]["fields"].append(f)
    # duplicate names -> suffix with field number
    for tag, rec in records.items():
        seen = {}
        for f in rec["fields"]:
            if f["name"] in seen:
                f["name"] = f"{f['name']}_{f['n']}"
            seen[f["name"]] = 1
    return {
        "id": layout_id,
        "label": "EDITEL INHOUSE INVOIC D01B (2012)",
        "family": "EDITEL-INHOUSE",
        "message": "INVOIC",
        "version": "D01B",
        "source": xlsx.name,
        "encoding": "cp1250",
        "tag": {"start": 1, "end": 3},
        "message_start": ["SYS", "HDR"],
        "ref_field": ["HDR", "CIS_DOKL"],
        "structure": STRUCTURE,
        "records": records,
        # VAT breakdown is not repeated – SUM has fixed columns per tax group; split into virtual VAT records
        "unpivot": {
            "VAT": {"from": "SUM", "label": "rekapitulace DPH (ze SUM)", "fields": ["SKUPINA", "ZAKLAD", "SAZBA", "DAN"],
                    "rows": [
                        {"SKUPINA": "=0", "ZAKLAD": "ZAKL_DPH_0", "SAZBA": "=0", "DAN": "=0"},
                        {"SKUPINA": "=1", "ZAKLAD": "ZAKL_DPH_1", "SAZBA": "SAZB_DPH_1", "DAN": "DAN_DPH_1"},
                        {"SKUPINA": "=2", "ZAKLAD": "ZAKL_DPH_2", "SAZBA": "SAZB_DPH_2", "DAN": "DAN_DPH_2"},
                    ],
                    "skip_if_zero": ["ZAKLAD", "DAN"]},
            # line fees (recycling / author's fee) are columns of LIN -> virtual line charge records
            "LFE": {"from": "LIN", "parent": "LIN", "label": "poplatek na řádku (z LIN)",
                    "fields": ["KOD", "CASTKA", "NA_JEDNOTKU", "MJ", "TYP"],
                    "rows": [
                        {"KOD": "=AEO", "CASTKA": "L_RECYKL_CELK", "NA_JEDNOTKU": "L_RECYKL_JEDN", "MJ": "L_RECYKL_MJ", "TYP": "L_RECYKL_TYP"},
                        {"KOD": "=AEP", "CASTKA": "L_AUTOR_CELK", "NA_JEDNOTKU": "L_AUTOR_JEDN", "MJ": "L_AUTOR_MJ", "TYP": "L_AUTOR_TYP"},
                    ],
                    "skip_if_zero": ["CASTKA"]},
        },
    }


if __name__ == "__main__":
    src, lid = pathlib.Path(sys.argv[1]), sys.argv[2]
    OUT.mkdir(parents=True, exist_ok=True)
    data = build(src, lid)
    (OUT / f"{lid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(lid, {k: len(v["fields"]) for k, v in data["records"].items()})
