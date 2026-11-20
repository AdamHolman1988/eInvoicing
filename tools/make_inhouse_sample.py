"""Generate synthetic (fictional) EDITEL INHOUSE INVOIC D01B test files from the layout.

    python tools/make_inhouse_sample.py   -> tests/samples/flat/inhouse_d01b_*.txt
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAYOUT = json.loads((ROOT / "msgvalidator/data/flat/editel_inhouse_invoic_d01b.json").read_text(encoding="utf-8"))
OUT = ROOT / "tests" / "samples" / "flat"


def gs1(body: str) -> str:
    """Append the GS1 check digit (fictional GLN/GTIN)."""
    tot = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body)))
    return body + str((10 - tot % 10) % 10)


def rec(tag: str, **values) -> str:
    fields = LAYOUT["records"][tag]["fields"]
    width = max(f["end"] for f in fields)
    buf = [" "] * width
    buf[0:3] = tag
    for f in fields[1:]:
        if f["name"] not in values:
            continue
        v = str(values[f["name"]])
        n = f["end"] - f["start"] + 1
        v = v.rjust(n) if f["type"] == "Num" else v.ljust(n)
        assert len(v) == n, (tag, f["name"], v)
        buf[f["start"] - 1:f["end"]] = v
    return "".join(buf).rstrip()


def party(q, gln, name, street, city, zip_, country, vat, ico, sk_dic=""):
    return rec("NAD", PARTNER_KVALIF=q, GLN_CIS=gln, OBCH_JM_1=name, ADR_UL_1=street, ADR_MISTO=city,
               ADR_PSC=zip_, ADR_ZEME=country, VAT_IC=vat, ICO=ico, SK_DIC=sk_dic)


def invoice(credit: bool = False) -> str:
    lines = [
        rec("SYS", PARTNER_EAN=gs1("859000000001"), STANDARD="E", VERZE="D  01B", ZPRAVA="INVOIC", TEST="T"),
        rec("HDR", DRUH_DOKL="381" if credit else "380", CIS_DOKL="DOB2026001" if credit else "FA2026001",
            FN_ZPR="9", DAT_VYST="20261102", KVALIF_DAT_VYST="102", DAT_UZP="20261102", DAT_SPLAT="20261202",
            ZPUS_UHR="42", CIS_OBJ_ZAK="OBJ-778", KOD_MENY="EUR", IBAN="SK3112000000198742637541",
            VAR_SYMB_PLAT="2026001",
            **({"VYZN_REF_CIS_FKT": "IV", "REF_CIS_FKT": "FA2025999", "DAT_REF_CIS_FKT": "20261001",
                "KVALIF_DAT_REF_CIS_FKT": "102"} if credit else {})),
        party("SU", gs1("859000000001"), "Testovací dodavatel s.r.o.", "Hlavná 1", "Bratislava", "81101", "SK",
              "SK2020000000", "12345678", "2020000000"),
        party("BY", gs1("858000000001"), "Testovací odběratel a.s.", "Obchodná 2", "Košice", "04001", "SK",
              "SK2021111111", "87654321", "2021111111"),
        party("DP", gs1("858000000002"), "Prodejna Košice", "Obchodná 2", "Košice", "04001", "SK", "", ""),
        rec("LIN", L_CIS_R="1", L_GTIN_ZBO=gs1("859000000010"), L_CIS_ZBO="A-100", L_TYP_CIS_ZBO="SA", L_TYP_POL="Z",
            L_MNOZSTV_FKT="10.000", L_MER_JEDN_FKT="PCE", L_CELK_CEN_ZA_POL="100.0000",
            L_CEN_JEDN_PRED_SL="10.0000", L_CEN_JEDN_PO_SL="10.0000", L_SAZB_DPH="23.00",
            L_DOD_SPEC="Testovací zboží A", L_DAN_DPH="23.0000"),
        rec("LIN", L_CIS_R="2", L_GTIN_ZBO=gs1("859000000011"), L_CIS_ZBO="B-200", L_TYP_CIS_ZBO="SA", L_TYP_POL="Z",
            L_MNOZSTV_FKT="4.000", L_MER_JEDN_FKT="PCE", L_CELK_CEN_ZA_POL="20.0000",
            L_CEN_JEDN_PRED_SL="6.0000", L_SLV_JEDN_ABS="1.0000", L_CEN_JEDN_PO_SL="5.0000", L_SAZB_DPH="19.00",
            L_DOD_SPEC="Testovací zboží B", L_DAN_DPH="3.8000"),
        rec("AAI", DOD_ZAPIS_OR_A_DALSI_ZE_ZAKONA="Zapísaná v OR OS Bratislava I, oddiel Sro, vložka 1/B"),
    ]
    if credit:
        lines.append(rec("AAW", DUVOD_OPR_DOKL="Vrácení zboží"))
    lines.append(rec("SUM", ZAKL_DPH_0="0.00", ZAKL_DPH_1="20.00", ZAKL_DPH_2="100.00", CENA_BEZ_DPH_CELK="120.00",
                     SAZB_DPH_1="19.00", SAZB_DPH_2="23.00", DAN_DPH_1="3.80", DAN_DPH_2="23.00",
                     DAN_DPH_CELK="26.80", SPOTR_DAN_CELK="0.00", CEN_RADK_POL_CELK="120.00",
                     FAKT_CELK="146.80", K_UHRADE="146.80", POC_RADK="2"))
    return "\r\n".join(lines) + "\r\n"


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "inhouse_d01b_invoice.txt").write_bytes(invoice().encode("cp1250"))
    (OUT / "inhouse_d01b_creditnote.txt").write_bytes(invoice(credit=True).encode("cp1250"))
    print("written", sorted(p.name for p in OUT.iterdir()))


# ------------------------------------------------------------------ ORION TXT (CCV) INVOIC
CCV = json.loads((ROOT / "msgvalidator/data/flat/orion_ccv_invoic.json").read_text(encoding="utf-8"))


def ccv(tag: str, **values) -> str:
    fields = CCV["records"][tag]["fields"]
    buf = [" "] * max(f["end"] for f in fields)
    buf[0:3] = tag
    by_name = {f["name"]: f for f in fields}
    for name, v in values.items():
        f = by_name[name]
        n = f["end"] - f["start"] + 1
        v = str(v).rjust(n) if f["type"] == "Num" else str(v).ljust(n)
        assert len(v) == n, (tag, name, v)
        buf[f["start"] - 1:f["end"]] = v
    return "".join(buf).rstrip()


def ccv_invoice() -> str:
    return "\r\n".join([
        ccv("HDR", HDR2=gs1("858000000001"), HDR3="FV2026100", HDR5="380", HDR6="9", HDR7="20261102", HDR8="20261102",
            HDR13="20261202", HDR14="42", HDR16="OBJ-991", HDR25="EAN", HDR26=gs1("858000000001"), HDR27="87654321",
            HDR28="2021111111", HDR29="Testovací odběratel a.s.", HDR30="Obchodná 2", HDR31="Košice", HDR32="04001",
            HDR33="SK", HDR57="EAN", HDR58=gs1("859000000001"), HDR59="12345678", HDR60="2020000000",
            HDR61="Testovací dodavatel s.r.o.", HDR62="Hlavná 1", HDR63="Bratislava", HDR64="81101", HDR65="SK",
            HDR76="2026100", HDR78="EUR", HDR83="SK3112000000198742637541", HDR84="TATRSKBX",
            HDR92="SK2021111111", HDR93="SK2020000000"),
        ccv("LIN", LIN2="1", LIN3="EAN", LIN4=gs1("859000000010"), LIN7="Testovací zboží A", LIN8="Z",
            LIN9="10.000", LIN10="10.00", LIN13="10.00", LIN14="100.00", LIN15="23.00", LIN16="PCE"),
        ccv("LIN", LIN2="2", LIN3="EAN", LIN4=gs1("859000000011"), LIN7="Testovací zboží B", LIN8="Z",
            LIN9="4.000", LIN10="6.00", LIN12="1.00", LIN13="5.00", LIN14="20.00", LIN15="19.00", LIN16="PCE"),
        ccv("TXT", TXT2="1", TXT3="Zapísaná v OR OS Bratislava I, oddiel Sro, vložka 1/B"),
        ccv("SUM", SUM2="0.00", SUM3="20.00", SUM4="100.00", SUM5="120.00", SUM6="19.00", SUM7="23.00",
            SUM8="3.80", SUM9="23.00", SUM10="26.80", SUM13="120.00", SUM30="146.80", SUM34="146.80",
            SUM36="2", SUM37="1"),
    ]) + "\r\n"


if __name__ == "__main__":
    (OUT / "orion_ccv_invoice.txt").write_bytes(ccv_invoice().encode("cp1250"))
    print("written orion_ccv_invoice.txt")
