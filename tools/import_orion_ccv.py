"""Import the ORION fixed-width (CCV) INVOIC specification (.xls) into a layout JSON.

    python tools/import_orion_ccv.py "<...>/CCV_ORION_FORMAT_INVOIC_257.xls" orion_ccv_invoic

Field names follow the convention used by the specification itself: <record><number> (HDR3, LIN14, SUM30 …).
Only positions/types/labels are taken over; the spreadsheet stays outside the repository.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import xlrd

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "msgvalidator" / "data" / "flat"

STRUCTURE = [
    {"tag": "HDR", "min": 1, "max": 1},
    {"tag": "LIN", "min": 0, "max": 999999, "children": [{"tag": "LAC", "min": 0, "max": 20}]},
    {"tag": "TXT", "min": 0, "max": 999999},
    {"tag": "REG", "min": 0, "max": 1},
    {"tag": "AAW", "min": 0, "max": 1},
    {"tag": "SUM", "min": 1, "max": 1, "summary": True},
]


def _vat_rows():
    rows = []
    for grp, base, rate, tax in (("0", "SUM2", "=0", "=0"), ("1", "SUM3", "SUM6", "SUM8"),
                                 ("1.2", "SUM45", "SUM46", "SUM47"), ("2", "SUM4", "SUM7", "SUM9")):
        rows.append({"SKUPINA": f"={grp}", "ZAKLAD": base, "SAZBA": rate, "DAN": tax, "KATEGORIE": "="})
    for grp, base, rate in (("1", "SUM52", "SUM6"), ("1.2", "SUM53", "SUM46"), ("2", "SUM54", "SUM7")):
        rows.append({"SKUPINA": f"={grp} PDP", "ZAKLAD": base, "SAZBA": "=0", "DAN": "=0", "KATEGORIE": "=AE"})
    return rows


def _doc_ac_rows(kind: str):
    # (group, percent field, absolute field, rate field) for allowances (A) / charges (C)
    spec = {"A": (("0", "SUM14", "SUM15", "=0"), ("1", "SUM16", "SUM17", "SUM6"), ("2", "SUM18", "SUM19", "SUM7"),
                  ("1.2", "SUM48", "SUM49", "SUM46")),
            "C": (("0", "SUM22", "SUM23", "=0"), ("1", "SUM24", "SUM25", "SUM6"), ("2", "SUM26", "SUM27", "SUM7"),
                  ("1.2", "SUM50", "SUM51", "SUM46"))}[kind]
    return [{"KOD": f"={kind}", "SKUPINA": f"={g}", "PROCENTO": p, "CASTKA": a, "SAZBA": r} for g, p, a, r in spec]


def build(xls: pathlib.Path, layout_id: str) -> dict:
    sh = xlrd.open_workbook(str(xls)).sheet_by_name("INVOIC")
    title = str(sh.cell_value(0, 0))
    m = re.search(r"ver\.\s*([\d.]+)", title)
    records: dict[str, dict] = {}
    cur = None
    for i in range(sh.nrows):
        r = [c.value for c in sh.row(i)] + [""] * 12
        if isinstance(r[0], str) and re.fullmatch(r"[A-Z]{3}", r[0].strip()) and r[1]:
            cur = r[0].strip()
            records[cur] = {"label": str(r[1]).strip(), "fields": []}
            continue
        if isinstance(r[0], str) and r[0].strip() in ("End", "Poznámky:"):
            cur = None
            continue
        if cur is None or not isinstance(r[0], float) or not isinstance(r[4], float):
            continue
        n = int(r[0])
        start = int(r[4])
        end_raw = r[5]
        end = int(end_raw)
        dec = None
        if isinstance(end_raw, float) and end_raw != int(end_raw):
            dec = int(round((end_raw - int(end_raw)) * 10))
        req = str(r[7]).strip()
        f = {"n": n, "name": "TAG" if n == 1 else f"{cur}{n}", "label": str(r[1]).strip(),
             "type": str(r[2]).strip(), "start": start, "end": end,
             "req": req == "Ano", "cond": req != "Ano" and req != "Ne"}
        if dec is not None:
            f["dec"] = dec
        note = str(r[8]).strip()
        if note and note != f'"{cur}"':
            f["note"] = note
        if str(r[9]).strip():
            f["format"] = str(r[9]).strip()
        records[cur]["fields"].append(f)
    records = {t: r for t, r in records.items() if r["fields"]}
    # field numbers in the sheet skip 91 in HDR – n is the documented number, positions are authoritative
    for tag, rec in records.items():
        rec["fields"].sort(key=lambda f: f["start"])
    digits = re.search(r"(\d)(\d)(\d)$", xls.stem)  # CCV_ORION_FORMAT_INVOIC_257 -> 2.5.7 (sheet title lags behind)
    version = ".".join(digits.groups()) if digits else (m.group(1) if m else "?")
    return {
        "id": layout_id,
        "label": f"ORION INVOIC – pevná délka (CCV, spec. {xls.stem.rsplit('_', 1)[-1]})",
        "family": "ORION-FLAT",
        "message": "INVOIC",
        "version": version,
        "source": xls.name,
        "encoding": "cp1250",
        "tag": {"start": 1, "end": 3},
        "message_start": ["HDR"],
        "ref_field": ["HDR", "HDR3"],
        "structure": STRUCTURE,
        "records": records,
        "unpivot": {
            "VAT": {"from": "SUM", "label": "rekapitulace DPH (ze SUM)",
                    "fields": ["SKUPINA", "ZAKLAD", "SAZBA", "DAN", "KATEGORIE"], "rows": _vat_rows(),
                    "skip_if_zero": ["ZAKLAD", "DAN"]},
            "DAC": {"from": "SUM", "label": "sleva/přirážka dokladu (ze SUM)",
                    "fields": ["KOD", "SKUPINA", "PROCENTO", "CASTKA", "SAZBA"],
                    "rows": _doc_ac_rows("A") + _doc_ac_rows("C"), "skip_if_zero": ["CASTKA", "PROCENTO"]},
        },
    }


if __name__ == "__main__":
    src, lid = pathlib.Path(sys.argv[1]), sys.argv[2]
    OUT.mkdir(parents=True, exist_ok=True)
    data = build(src, lid)
    (OUT / f"{lid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(lid, data["version"], {k: len(v["fields"]) for k, v in data["records"].items()})
