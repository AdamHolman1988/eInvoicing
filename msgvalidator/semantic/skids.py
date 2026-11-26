"""Slovak identifiers: shape and check digits of IČO, DIČ and IČ DPH (SK + DIČ).

- IČO (BT-30 / BT-47 / BT-61): 8 digits, mod-11 check digit (weights 8..2) – holds for 99.99 % of SK companies (733k checked).
- DIČ (BT-32, Peppol endpoint scheme 0245): 10 digits, divisible by 11 – holds for every SK DIČ.
- IČ DPH (BT-31 / BT-48 / BT-63 with prefix SK): "SK" + DIČ, third digit 2/3/4/7/8/9.
The typical mistake – DIČ sent in the IČO field – is formally valid for KoSIT, so it is caught here.
"""
from __future__ import annotations

import re

from .model import Context, Semantic, Value

PARTIES = {  # IČO, DIČ, IČ DPH, country, endpoint, who
    "seller": ("BT-30", "BT-32", "BT-31", "BT-40", "BT-34", "predávajúceho / dodavatele"),
    "buyer": ("BT-47", None, "BT-48", "BT-55", "BT-49", "kupujúceho / odběratele"),
    "payee": ("BT-61", None, None, None, None, "príjemcu platby"),
}


def ico_ok(s: str) -> bool:
    w = sum(int(s[i]) * (8 - i) for i in range(7))
    return (11 - w % 11) % 10 == int(s[7])


def dic_ok(s: str) -> bool:
    return len(s) == 10 and s[0] != "0" and int(s) % 11 == 0


def _digits(s: str) -> str:
    return re.sub(r"[\s.\-/]", "", s or "")


def _first(ctx: Context, bt: str | None) -> Value | None:
    vs = ctx.values.get(bt) if bt else None
    return vs[0] if vs else None


def check(sem: Semantic, Finding) -> list:
    d = sem.document
    out = []

    def add(sev, code, v: Value, bt, msg, hint=None):
        out.append(Finding(sev, code, msg, bt=bt, contexts=[d.label], line=v.line, segment=v.segment, hint=hint))

    for ico_bt, dic_bt, vat_bt, country_bt, ep_bt, who in PARTIES.values():
        vat = _first(d, vat_bt)
        vat_s = _digits(vat.value).upper() if vat else ""
        country = (_first(d, country_bt).value.strip().upper() if _first(d, country_bt) else "")
        is_sk = country == "SK" or vat_s.startswith("SK")
        if not is_sk:
            continue
        dic_from_vat = vat_s[2:] if vat_s.startswith("SK") else None

        if vat and vat_s.startswith("SK"):
            num = vat_s[2:]
            if not (num.isdigit() and len(num) == 10):
                add("error", "VAL-SK-ICDPH", vat, vat_bt,
                    f"{vat_bt} IČ DPH {who}: '{vat.value}' nemá tvar SK + 10 číslic.")
            elif not dic_ok(num) or num[2] not in "234789":
                add("warning", "VAL-SK-ICDPH-CHECK", vat, vat_bt,
                    f"{vat_bt} IČ DPH {who}: '{vat.value}' nemá platnou kontrolu (SK IČ DPH je dělitelné 11, 3. číslice 2/3/4/7/8/9).",
                    hint="Ověřte číslo v registru FS SR nebo VIES – pravděpodobně překlep.")

        ico = _first(d, ico_bt)
        if ico and ico.how != "const":
            s = _digits(ico.value)
            if s.upper().startswith("SK") and s[2:] == dic_from_vat:
                add("warning", "VAL-SK-ICO-IS-ICDPH", ico, ico_bt,
                    f"{ico_bt} IČO {who}: '{ico.value}' je IČ DPH, ne IČO.",
                    hint="IČO je 8místné číslo z obchodného registra (ORSR/RPO).")
            elif s.isdigit() and len(s) == 10:
                same = dic_from_vat and s == dic_from_vat
                add("warning", "VAL-SK-ICO-IS-DIC", ico, ico_bt,
                    f"{ico_bt} IČO {who}: '{ico.value}' má 10 číslic"
                    + (" a shoduje se s DIČ v IČ DPH" if same else "") + " – zřejmě je tam DIČ místo IČO.",
                    hint="SK IČO má 8 číslic (ORSR / RPO). Formálně faktura projde, věcně je údaj špatně.")
            elif not s.isdigit() or len(s) not in (6, 8):
                add("warning", "VAL-SK-ICO-FORMAT", ico, ico_bt,
                    f"{ico_bt} IČO {who}: '{ico.value}' nemá tvar SK IČO (8 číslic).")
            elif not ico_ok(s.zfill(8)):
                add("warning", "VAL-SK-ICO-CHECK", ico, ico_bt,
                    f"{ico_bt} IČO {who}: '{ico.value}' nemá platnou kontrolní číslici.",
                    hint="Ověřte v ORSR/RPO – u několika starých subjektů může kontrola výjimečně nesedět.")

        dic = _first(d, dic_bt)
        if dic and dic.how != "const":
            s = _digits(dic.value)
            if s.upper().startswith("SK"):
                s = s[2:]
            if not (s.isdigit() and len(s) == 10):
                add("warning", "VAL-SK-DIC-FORMAT", dic, dic_bt,
                    f"{dic_bt} DIČ {who}: '{dic.value}' nemá tvar SK DIČ (10 číslic).")
            elif not dic_ok(s):
                add("warning", "VAL-SK-DIC-CHECK", dic, dic_bt,
                    f"{dic_bt} DIČ {who}: '{dic.value}' není dělitelné 11 (neplatné SK DIČ).")
            elif dic_from_vat and s != dic_from_vat:
                add("warning", "VAL-SK-DIC-MISMATCH", dic, dic_bt,
                    f"{dic_bt} DIČ {who}: '{dic.value}' se liší od DIČ v IČ DPH '{vat.value}'.")

        ep = _first(d, ep_bt)
        if ep and (ep.scheme or "") == "0245":
            s = _digits(ep.value)
            if not dic_ok(s):
                add("error", "VAL-SK-ENDPOINT", ep, ep_bt,
                    f"{ep_bt} Peppol adresa {who} (schéma 0245 = SK DIČ): '{ep.value}' není platné DIČ (10 číslic dělitelných 11).",
                    hint="Na takovou adresu se faktura v síti Peppol nedoručí.")
    return out
