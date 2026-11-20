"""Derivation functions: values that are not explicit in the message but can be inferred.

Every derived value is reported as such, so the analyst sees that the converter has to
compute it (and on which assumption).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .selector import node_segment, select


def _num(s: str | None) -> Decimal | None:
    if s is None:
        return None
    try:
        return Decimal(s.replace(",", "."))
    except InvalidOperation:
        return None


def endpoint_from_party(ctx_nodes, args, header_nodes, ctx_values):
    nodes = select(header_nodes, f"NAD[1.1={args['party']};2.3=9]")
    if not nodes:
        return None
    seg = node_segment(nodes[0])
    return {"value": seg.get(2, 1), "scheme": "0088", "seg": seg, "how": "derived"}


def country_from_vat(ctx_nodes, args, header_nodes, ctx_values):
    nodes = select(header_nodes, f"NAD[1.1={args['party']}] > RFF[1.1=VA]")
    for n in nodes:
        seg = node_segment(n)
        vat = (seg.get(1, 2) or "").strip()
        if len(vat) >= 2 and vat[:2].isalpha():
            return {"value": vat[:2].upper(), "seg": seg, "how": "derived"}
    return None


def vat_category_from_rate(ctx_nodes, args, header_nodes, ctx_values):
    nodes = select(ctx_nodes, args.get("path", "@"))
    for n in nodes:
        seg = node_segment(n)
        if seg.get(6, 1):
            return None  # explicit category exists – nothing to derive
        rate = _num(seg.get(5, 4))
        if rate is None and seg.get(5, 1) == "0":
            rate = Decimal(0)  # GS1 CZ: tax group code 0 = zero rate
        if rate is None:
            continue
        if rate > 0:
            return {"value": "S", "seg": seg, "how": "derived"}
        return {"value": "Z", "seg": seg, "how": "ambiguous",
                "note": "Sazba 0 % – kategorie může být Z (nulová), E (osvobozeno), O (mimo předmět) nebo AE; "
                        "nelze jednoznačně odvodit."}
    return None


def price_discount(ctx_nodes, args, header_nodes, ctx_values):
    gross = ctx_values.get("BT-148")
    net = ctx_values.get("BT-146")
    if not gross or not net:
        return None
    g, n = _num(gross[0].value), _num(net[0].value)
    if g is None or n is None or g < n:
        return None
    return {"value": str(g - n), "seg": None, "how": "derived"}


def default_unit(ctx_nodes, args, header_nodes, ctx_values):
    nodes = select(ctx_nodes, args["path"])
    if nodes and node_segment(nodes[0]).get(1, 3) is None:
        return {"value": "H87", "seg": node_segment(nodes[0]), "how": "ambiguous"}
    return None


def zero_tax_amount(ctx_nodes, args, header_nodes, ctx_values):
    cat = (ctx_values.get("BT-118") or [None])[0]
    rate = (ctx_values.get("BT-119") or [None])[0]
    if (cat and cat.value in ("AE", "E", "Z", "O", "K", "G")) or (rate and _num(rate.value) == 0):
        seg = node_segment(ctx_nodes[0]) if ctx_nodes else None
        return {"value": "0", "seg": seg, "how": "derived"}
    return None


def rate_from_code(ctx_nodes, args, header_nodes, ctx_values):
    seg = node_segment(ctx_nodes[0]) if ctx_nodes else None
    if seg is not None and seg.get(5, 1) == "0" and seg.get(5, 4) is None:
        return {"value": "0", "seg": seg, "how": "derived"}
    return None


def sk_tax_id_from_vat(ctx_nodes, args, header_nodes, ctx_values):
    for n in select(header_nodes, f"NAD[1.1={args['party']}] > RFF[1.1=VA]"):
        seg = node_segment(n)
        vat = (seg.get(1, 2) or "").replace(" ", "")
        if vat.upper().startswith("SK") and vat[2:].isdigit():
            return {"value": vat[2:], "seg": seg, "how": "derived"}
    return None


# ---------------------------------------------------------------------------------------------------------------
# Generic derivations parameterised by path + value position (used by flat-file and user-built mappings).
# args: path  – selector ('@ ...' = relative to the current group, otherwise from the document header)
#       value – "element.component" in the segment found by the path
def _at(ctx_nodes, header_nodes, args):
    path = args["path"]
    nodes = select(ctx_nodes if path.startswith("@") else header_nodes, path)
    e, _, c = args["value"].partition(".")
    for n in nodes:
        seg = node_segment(n)
        v = seg.get(int(e), int(c or 1))
        if v and v.strip():
            yield seg, v.strip()


def country_from_vat_at(ctx_nodes, args, header_nodes, ctx_values):
    for seg, vat in _at(ctx_nodes, header_nodes, args):
        vat = vat.replace(" ", "")
        if len(vat) >= 2 and vat[:2].isalpha():
            return {"value": vat[:2].upper(), "seg": seg, "how": "derived"}
    return None


def sk_tax_id_from_vat_at(ctx_nodes, args, header_nodes, ctx_values):
    for seg, vat in _at(ctx_nodes, header_nodes, args):
        vat = vat.replace(" ", "")
        if vat.upper().startswith("SK") and vat[2:].isdigit():
            return {"value": vat[2:], "seg": seg, "how": "derived"}
    return None


def gln_endpoint_at(ctx_nodes, args, header_nodes, ctx_values):
    for seg, v in _at(ctx_nodes, header_nodes, args):
        if v.isdigit() and len(v) == 13:
            return {"value": v, "scheme": "0088", "seg": seg, "how": "derived"}
    return None


def vat_category_from_rate_at(ctx_nodes, args, header_nodes, ctx_values):
    """S for a positive rate, AE when a reverse-charge flag (args.flag_path/flag) says so, Z/E/O ambiguous for 0 %."""
    if args.get("flag_path"):
        fl = {"path": args["flag_path"], "value": args["flag"]}
        for seg, v in _at(ctx_nodes, header_nodes, fl):
            if v.upper() in ("AE", "1"):
                return {"value": "AE", "seg": seg, "how": "derived",
                        "note": f"Příznak přenesení daňové povinnosti = {v}."}
    for seg, v in _at(ctx_nodes, header_nodes, args):
        rate = _num(v)
        if rate is None:
            continue
        if rate > 0:
            return {"value": "S", "seg": seg, "how": "derived"}
        return {"value": "Z", "seg": seg, "how": "ambiguous",
                "note": "Sazba 0 % – kategorie může být Z (nulová), E (osvobozeno), O (mimo předmět) nebo AE; "
                        "nelze jednoznačně odvodit."}
    return None


def vat_id_if_prefixed_at(ctx_nodes, args, header_nodes, ctx_values):
    """Use a tax number as VAT ID only when it carries a country prefix (CZ…, SK…)."""
    for seg, v in _at(ctx_nodes, header_nodes, args):
        v = v.replace(" ", "")
        if len(v) > 2 and v[:2].isalpha():
            return {"value": v, "seg": seg, "how": "mapped"}
    return None


def sk_endpoint_from_vat_at(ctx_nodes, args, header_nodes, ctx_values):
    """SK Peppol endpoint 0245 = DIČ (10 digits), taken from a 'SK…' VAT ID or a bare 10-digit DIČ."""
    for seg, v in _at(ctx_nodes, header_nodes, args):
        v = v.replace(" ", "").upper()
        dic = v[2:] if v.startswith("SK") else v
        if dic.isdigit() and len(dic) == 10:
            return {"value": dic, "scheme": "0245", "seg": seg, "how": "derived"}
    return None


def zero_rate_for_category(ctx_nodes, args, header_nodes, ctx_values):
    cat = (ctx_values.get("BT-118") or ctx_values.get("BT-151") or [None])[0]
    if cat and cat.value in ("AE", "E", "Z", "O", "K", "G"):
        seg = node_segment(ctx_nodes[0]) if ctx_nodes else None
        return {"value": "0", "seg": seg, "how": "derived"}
    return None


def _amounts(nodes, spec) -> list[tuple]:
    """(segment, Decimal) for a nested {path, value} argument evaluated in the given context nodes."""
    if not spec:
        return []
    out = []
    for seg, v in _at(nodes, nodes, spec):
        n = _num(v)
        if n is not None:
            out.append((seg, n))
    return out


def _fmt(d: Decimal, places: int = 6) -> str:
    q = d.quantize(Decimal(1).scaleb(-places))
    s = format(q.normalize(), "f")
    if "." not in s:
        s += ".00"
    elif len(s.split(".")[1]) < 2:
        s += "0"
    return s


def unit_price_from_line(ctx_nodes, args, header_nodes, ctx_values):
    """Net price (BT-146) = (line net amount + line allowances − line charges) / quantity.

    Keeps PEPPOL-EN16931-R120 arithmetic consistent when the source has no usable unit price
    (SAP IDoc: E1EDP26 amounts differ by pricing procedure, the line net amount is reliable)."""
    amt, qty = ctx_values.get("BT-131"), ctx_values.get("BT-129")
    a, q = (_num(amt[0].value) if amt else None), (_num(qty[0].value) if qty else None)
    if a is None or not q:
        return None
    allow = sum((n for _, n in _amounts(ctx_nodes, args.get("allowances"))), Decimal(0))
    charge = sum((n for _, n in _amounts(ctx_nodes, args.get("charges"))), Decimal(0))
    price = (a + abs(allow) - abs(charge)) / q
    note = "Cena za jednotku dopočtena: (netto řádku" + (" + slevy" if allow else "") +            (" − přirážky" if charge else "") + ") / množství."
    if a < 0 < q:
        note += (" Záporná částka řádku při kladném množství (např. sleva jako řádek) – Peppol nedovoluje zápornou "
                 "cenu, konverze musí obrátit znaménko množství.")
    return {"value": _fmt(abs(price)), "seg": None, "how": "derived", "note": note}


def sum_lines_by_rate_at(ctx_nodes, args, header_nodes, ctx_values):
    """VAT breakdown taxable amount (BT-116) = sum of line net amounts with the same tax code (or rate).

    args: lines (path from the header), amount / line_rate / line_code / group_code ({path, value})."""
    g_code = next((v for _, v in _at(ctx_nodes, ctx_nodes, args["group_code"])), None) if args.get("group_code") else None
    g_rate = ctx_values.get("BT-119")
    g_rate = _num(g_rate[0].value) if g_rate else None
    total, used, first = Decimal(0), 0, None
    for line in select(header_nodes, args["lines"]):
        l_code = next((v for _, v in _at([line], [line], args["line_code"])), None) if args.get("line_code") else None
        l_rate = next((_num(v) for _, v in _at([line], [line], args["line_rate"])), None) if args.get("line_rate") else None
        same = (l_code == g_code) if (g_code and l_code) else (l_rate is not None and l_rate == g_rate)
        if not same:
            continue
        for seg, n in _amounts([line], args["amount"])[:1]:
            total += n
            used += 1
            first = first or seg
    if not used:
        return None
    key = f"kódem daně {g_code}" if g_code else f"sazbou {g_rate} %"
    return {"value": _fmt(total, 2), "seg": first, "how": "derived",
            "note": f"Základ daně = součet netto částek {used} řádků se {key} (zdroj ho v rekapitulaci DPH nenese)."}


def ref_if_differs_at(ctx_nodes, args, header_nodes, ctx_values):
    """A reference (e.g. preceding invoice) only when it differs from another term (e.g. the own number BT-1)."""
    other = ctx_values.get(args.get("other", "BT-1"))
    own = other[0].value.lstrip("0") if other else None
    for seg, v in _at(ctx_nodes, header_nodes, args):
        if v.lstrip("0") != own:
            return {"value": v, "seg": seg, "how": "explicit"}
    return None


def payment_means_from_account_at(ctx_nodes, args, header_nodes, ctx_values):
    code = args.get("code", "30")
    what = "SEPA převod" if code == "58" else "převod (58 = SEPA převod)"
    for seg, v in _at(ctx_nodes, header_nodes, args):
        return {"value": code, "seg": seg, "how": "derived",
                "note": f"Kód způsobu úhrady chybí; je uvedeno číslo účtu / IBAN → kód {code} – {what}. "
                        f"Ověřte s klientem."}
    return None


TYPICAL_RATES = (0, 5, 7, 9, 10, 12, 13, 15, 19, 20, 21, 23)


def rate_from_tax_at(ctx_nodes, args, header_nodes, ctx_values):
    """Line VAT rate (BT-152) = line VAT amount / line net amount, snapped to a usual rate (format has no rate)."""
    amt = ctx_values.get("BT-131")
    a = _num(amt[0].value) if amt else None
    for seg, v in _at(ctx_nodes, header_nodes, args):
        t = _num(v)
        if t is None or not a:
            continue
        r = t / a * 100
        best = min(TYPICAL_RATES, key=lambda x: abs(r - x))
        val = Decimal(best) if abs(r - best) <= Decimal("0.5") else r.quantize(Decimal("0.01"))
        return {"value": _fmt(val, 2), "seg": seg, "how": "derived",
                "note": f"Sazba dopočtena z daně řádku: {v} / {amt[0].value} = {r.quantize(Decimal('0.001'))} %."}
    return None


def vat_category_from_ctx(ctx_nodes, args, header_nodes, ctx_values):
    """VAT category from an already known (possibly derived) rate of the same context."""
    r = ctx_values.get("BT-152") or ctx_values.get("BT-119")
    rate = _num(r[0].value) if r else None
    if rate is None:
        return None
    if rate > 0:
        return {"value": "S", "seg": None, "how": "derived"}
    return {"value": "Z", "seg": None, "how": "ambiguous",
            "note": "Sazba 0 % – kategorie může být Z, E, O nebo AE; nelze jednoznačně odvodit."}


def tax_from_base_rate(ctx_nodes, args, header_nodes, ctx_values):
    """VAT category tax amount (BT-117) = taxable amount x rate, rounded half up to 2 places."""
    b, r = ctx_values.get("BT-116"), ctx_values.get("BT-119")
    b, r = (_num(b[0].value) if b else None), (_num(r[0].value) if r else None)
    if b is None or r is None:
        return None
    return {"value": _fmt((b * r / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), 2), "seg": None,
            "how": "derived", "note": "Daň dopočtena: základ × sazba."}


DERIVERS = {
    "rate_from_tax_at": rate_from_tax_at,
    "vat_category_from_ctx": vat_category_from_ctx,
    "tax_from_base_rate": tax_from_base_rate,
    "unit_price_from_line": unit_price_from_line,
    "sum_lines_by_rate_at": sum_lines_by_rate_at,
    "ref_if_differs_at": ref_if_differs_at,
    "payment_means_from_account_at": payment_means_from_account_at,
    "country_from_vat_at": country_from_vat_at,
    "sk_tax_id_from_vat_at": sk_tax_id_from_vat_at,
    "gln_endpoint_at": gln_endpoint_at,
    "vat_category_from_rate_at": vat_category_from_rate_at,
    "zero_rate_for_category": zero_rate_for_category,
    "vat_id_if_prefixed_at": vat_id_if_prefixed_at,
    "sk_endpoint_from_vat_at": sk_endpoint_from_vat_at,
    "country_code_at": lambda c, a, h, v: next(({"value": x.upper(), "seg": s, "how": "explicit"}
                                                for s, x in _at(c, h, a) if len(x) == 2 and x.isalpha()), None),
    "sk_tax_id_from_vat": sk_tax_id_from_vat,
    "zero_tax_amount": zero_tax_amount,
    "rate_from_code": rate_from_code,
    "default_unit": default_unit,
    "endpoint_from_party": endpoint_from_party,
    "country_from_vat": country_from_vat,
    "vat_category_from_rate": vat_category_from_rate,
    "price_discount": price_discount,
}
