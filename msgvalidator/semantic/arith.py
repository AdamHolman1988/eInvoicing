"""Strict arithmetic checks that the official rules tolerate.

BR-CO-17 (EN 16931 Schematron 1.3.x) accepts a VAT category tax amount within ±1 currency unit of
taxable amount × rate, so a VAT amount off by a cent (wrong rounding) passes Peppol validation unnoticed –
yet the tax on the document is wrong. Here the amount must equal the rounded product exactly."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def _num(ctx, bt) -> tuple[Decimal | None, object]:
    vals = ctx.values.get(bt)
    if not vals:
        return None, None
    try:
        return Decimal(vals[0].value.replace(",", ".")), vals[0]
    except InvalidOperation:
        return None, vals[0]


def check(sem, finding) -> list:
    """finding = Finding constructor (avoids an import cycle)."""
    out = []
    diff_sum = Decimal(0)
    for ctx in sem.groups.get("BG-23", []):
        base, _ = _num(ctx, "BT-116")
        tax, tv = _num(ctx, "BT-117")
        rate, _ = _num(ctx, "BT-119")
        if base is None or tax is None or rate is None or tv.how != "explicit":
            continue  # derived tax is computed exactly; nothing to compare
        exact = base * rate / 100
        expected = exact.quantize(CENT, rounding=ROUND_HALF_UP)
        diff = tax - expected
        if diff == 0:
            continue
        diff_sum += diff
        out.append(finding(
            "warning", "ARITH-VAT",
            f"BT-117 DPH za sazbu {rate.normalize():f} %: {tax} ≠ základ {base} × {rate.normalize():f} % = {exact:f} "
            f"→ správně {expected} (rozdíl {diff:+}).",
            bt="BT-117", contexts=[ctx.label], line=tv.line, segment=tv.segment,
            hint="Oficiální pravidlo BR-CO-17 toleruje odchylku ±1 jednotky měny, takže Peppol validace projde – "
                 "částka DPH na dokladu je ale chybně zaokrouhlená. Ověřte výpočet DPH u vystavitele."))
    if diff_sum and out:
        tt, tv = _num(sem.document, "BT-110")
        tot, gv = _num(sem.document, "BT-112")
        parts = []
        if tt is not None:
            parts.append(f"DPH celkem (BT-110) {tt} → {tt - diff_sum}")
        if tot is not None:
            parts.append(f"celkem s DPH (BT-112) {tot} → {tot - diff_sum}")
        if parts:
            v = tv or gv
            out.append(finding("warning", "ARITH-VAT-TOTAL",
                               "Chybné zaokrouhlení DPH se promítá do součtů: " + ", ".join(parts) + ".",
                               bt="BT-110" if tv else "BT-112", contexts=["doklad"],
                               line=v.line, segment=v.segment))
    return out
