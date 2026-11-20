"""Value shapes for the format guesser: what kind of data a field carries (date, IBAN, VAT id, GLN …)."""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache

from ..semantic.catalog import codelists

ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$")
DMY_DATE = re.compile(r"^(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})$")
YMD_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
NUM_DOT = re.compile(r"^[+-]?\d{1,3}(?:[  ]?\d{3})*(?:\.\d+)?$|^[+-]?\d+(?:\.\d+)?$")
NUM_COMMA = re.compile(r"^[+-]?\d{1,3}(?:[  .]?\d{3})*,\d+$|^[+-]?\d+,\d+$")
INT_RE = re.compile(r"^\d+$")
VATID_RE = re.compile(r"^([A-Z]{2})[0-9A-Z]{8,12}$")
IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")
BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[\d ()/-]{9,20}$")
ZIP_RE = re.compile(r"^(?:\d{3} ?\d{2}|\d{4,5}|[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})$")
ACCOUNT_RE = re.compile(r"^(?:\d{1,6}-)?\d{2,10}/\d{4}$")  # Czech / Slovak domestic account 123-4567890/0800
VAT_CATEGORIES = {"S", "Z", "E", "AE", "K", "G", "O", "L", "M"}
TYPICAL_RATES = {0, 5, 7, 9, 10, 12, 13, 15, 19, 20, 21, 23}
COMMON_UNITS = {"KS", "KG", "PCS", "PCE", "ST", "M", "L", "BAL", "KAR", "PAL", "HOD", "H", "KM", "T", "M2", "M3", "SET", "BX", "PK"}


@lru_cache(maxsize=1)
def _lists():
    cl = codelists()
    return ({c.upper() for c in cl.get("ISO4217", {}).get("codes", {})},
            {c.upper() for c in cl.get("ISO3166", {}).get("codes", {})},
            {c.upper() for c in cl.get("UNECERec20", {}).get("codes", {})},
            set(cl.get("UNCL1001-inv", {}).get("codes", {})) | set(cl.get("UNCL1001-cn", {}).get("codes", {})))


def gs1_ok(code: str) -> bool:
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    d = [int(c) for c in code]
    total = sum(x * (3 if i % 2 == 0 else 1) for i, x in enumerate(reversed(d[:-1])))
    return (10 - total % 10) % 10 == d[-1]


def iban_ok(v: str) -> bool:
    s = v[4:] + v[:4]
    try:
        return int("".join(str(int(c, 36)) for c in s)) % 97 == 1
    except ValueError:
        return False


def date_format(v: str) -> str | None:
    """'iso' | 'dmy' | '102' (YYYYMMDD) for a plausible date, else None."""
    v = v.strip()
    for rx, fmt, order in ((ISO_DATE, "iso", "ymd"), (DMY_DATE, "dmy", "dmy"), (YMD_DATE, "102", "ymd")):
        m = rx.match(v)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups()[:3])
        y, mo, d = (a, b, c) if order == "ymd" else (c, b, a)
        if not 1990 <= y <= 2100:
            return None
        try:
            dt.date(y, mo, d)
        except ValueError:
            return None
        return fmt
    return None


def number(v: str) -> tuple[float, str] | None:
    """(value, decimal separator) for '1 234,50' / '1234.50' / '12', else None."""
    s = v.strip()
    if NUM_DOT.match(s):
        try:
            return float(s.replace(" ", "").replace(" ", "")), "."
        except ValueError:
            return None
    if NUM_COMMA.match(s):
        try:
            return float(s.replace(" ", "").replace(" ", "").replace(".", "").replace(",", ".")), ","
        except ValueError:
            return None
    return None


def kinds(v: str) -> set[str]:
    """All shapes a single value fits."""
    s = v.strip()
    if not s:
        return set()
    cur, ctry, units, types = _lists()
    out = set()
    up = s.upper()
    if date_format(s):
        out.add("date")
    n = number(s)
    if n is not None and "date" not in out:
        out.add("num")
        if n[1] == ",":
            out.add("comma")
        if 0 <= n[0] <= 100:
            out.add("percent")
            if n[0] in TYPICAL_RATES:
                out.add("rate")
    if INT_RE.match(s):
        out.add("int")
        if gs1_ok(s):
            out.add("gtin")
            if len(s) == 13:
                out.add("gln")
        if len(s) in (6, 8):
            out.add("ico")
        if len(s) == 10:
            out.add("dic10")
        if s in types:
            out.add("typecode")
    if len(s) == 3 and up in cur and s.isalpha():
        out.add("currency")
    if len(s) == 2 and up in ctry and s.isalpha():
        out.add("country")
    m = VATID_RE.match(up.replace(" ", ""))
    if m and (m.group(1) in ctry or m.group(1) in ("EL", "XI")) and sum(c.isdigit() for c in up) >= 7:
        out.add("vatid")
    if IBAN_RE.match(up.replace(" ", "")) and iban_ok(up.replace(" ", "")):
        out.add("iban")
    if ACCOUNT_RE.match(s):
        out.add("account")
    if BIC_RE.match(s) and not s.isdigit() and up[4:6] in ctry:
        out.add("bic")
    if EMAIL_RE.match(s):
        out.add("email")
    if PHONE_RE.match(s) and sum(c.isdigit() for c in s) >= 9 and "date" not in out and not INT_RE.match(s):
        out.add("phone")
    if ZIP_RE.match(up):
        out.add("zip")
    if up in units or up in COMMON_UNITS:
        out.add("unit")
    if up in VAT_CATEGORIES:
        out.add("vatcat")
    if any(c.isalpha() for c in s) and not out & {"date", "currency", "country", "vatid", "iban", "bic", "email", "unit", "vatcat"}:
        out.add("text")
    return out
