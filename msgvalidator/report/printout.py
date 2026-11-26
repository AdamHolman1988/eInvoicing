"""Print layout ("tisková sestava") of an e-invoice: a conventional-looking A4 invoice rendered from the
semantic (EN 16931) model, so it works for every input format (UBL, CII, EDIFACT, ORION, IDoc ...).

It is a human-readable visualisation for accountants, not the legal original. PDF is produced by printing the
HTML with a locally installed Chromium browser (Edge is on every Windows), so the exe needs no PDF engine.
"""
from __future__ import annotations

import html
import os
import pathlib
import shutil
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation

from ..semantic.model import Context, Semantic

L = {
    "cs": {
        "380": "Faktura", "381": "Dobropis", "383": "Vrubopis", "384": "Opravná faktura", "386": "Zálohová faktura",
        "388": "Daňový doklad", "389": "Faktura (samofakturace)", "751": "Faktura – informace pro účetnictví",
        "invoice": "Faktura", "no": "č.", "supplier": "Dodavatel", "buyer": "Odběratel", "delivery": "Místo dodání",
        "payee": "Příjemce platby", "reg": "IČO", "vat": "IČ DPH", "tax": "DIČ", "contact": "Kontakt",
        "issue": "Datum vystavení", "due": "Datum splatnosti", "taxpoint": "Datum zdaň. plnění",
        "deldate": "Datum dodání", "period": "Fakturační období", "currency": "Měna",
        "order": "Objednávka", "salesorder": "Zakázka dodavatele", "buyerref": "Reference odběratele",
        "contract": "Smlouva", "despatch": "Dodací list", "receiving": "Příjemka", "project": "Projekt",
        "preceding": "K dokladu", "accounting": "Účetní reference",
        "payment": "Platba", "means": "Způsob úhrady", "iban": "Účet (IBAN)", "bic": "BIC", "vs": "Var. symbol / ref.",
        "terms": "Platební podmínky",
        "lines": "Položky", "pos": "Poz.", "code": "Kód", "item": "Položka", "qty": "Množství", "unit": "MJ",
        "price": "Cena/MJ", "disc": "Sleva / přirážka", "netunit": "Cena/MJ po slevě", "net": "Bez DPH",
        "vatpct": "DPH %", "doclevel": "Slevy a přirážky za doklad", "allowance": "Sleva", "charge": "Přirážka",
        "vatbreak": "Rekapitulace DPH", "cat": "Kategorie", "base": "Základ", "vatamt": "DPH", "reason": "Důvod",
        "sumlines": "Součet položek", "sumallow": "Slevy za doklad", "sumcharge": "Přirážky za doklad",
        "taxexcl": "Celkem bez DPH", "vattotal": "DPH celkem", "taxincl": "Celkem s DPH", "prepaid": "Zaplaceno zálohou",
        "rounding": "Zaokrouhlení", "payable": "K úhradě", "notes": "Poznámky",
        "disclaimer": "Vizualizace elektronické faktury – nejde o originál dokladu. Právně závazná je elektronická zpráva.",
        "source": "Zdroj", "gtin": "GTIN", "vatcur": "DPH v měně účtování",
    },
    "en": {
        "380": "Invoice", "381": "Credit note", "383": "Debit note", "384": "Corrected invoice", "386": "Prepayment invoice",
        "388": "Tax invoice", "389": "Self-billed invoice", "751": "Invoice – information for accounting",
        "invoice": "Invoice", "no": "No.", "supplier": "Seller", "buyer": "Buyer", "delivery": "Deliver to",
        "payee": "Payee", "reg": "Company ID", "vat": "VAT ID", "tax": "Tax ID", "contact": "Contact",
        "issue": "Issue date", "due": "Due date", "taxpoint": "Tax point date",
        "deldate": "Delivery date", "period": "Invoicing period", "currency": "Currency",
        "order": "Purchase order", "salesorder": "Sales order", "buyerref": "Buyer reference",
        "contract": "Contract", "despatch": "Despatch advice", "receiving": "Receiving advice", "project": "Project",
        "preceding": "Preceding invoice", "accounting": "Buyer accounting ref.",
        "payment": "Payment", "means": "Payment means", "iban": "Account (IBAN)", "bic": "BIC", "vs": "Payment reference",
        "terms": "Payment terms",
        "lines": "Lines", "pos": "#", "code": "Code", "item": "Item", "qty": "Quantity", "unit": "Unit",
        "price": "Unit price", "disc": "Allowance / charge", "netunit": "Net unit price", "net": "Net amount",
        "vatpct": "VAT %", "doclevel": "Document level allowances and charges", "allowance": "Allowance", "charge": "Charge",
        "vatbreak": "VAT breakdown", "cat": "Category", "base": "Taxable amount", "vatamt": "VAT", "reason": "Reason",
        "sumlines": "Sum of lines", "sumallow": "Allowances", "sumcharge": "Charges",
        "taxexcl": "Total without VAT", "vattotal": "Total VAT", "taxincl": "Total with VAT", "prepaid": "Paid amount",
        "rounding": "Rounding", "payable": "Amount due", "notes": "Notes",
        "disclaimer": "Visualisation of an electronic invoice – not the original document. The electronic message is legally binding.",
        "source": "Source", "gtin": "GTIN", "vatcur": "VAT in accounting currency",
    },
}
UNITS = {"C62": "ks", "H87": "ks", "EA": "ks", "PCE": "ks", "PR": "pár", "SET": "sada", "KGM": "kg", "GRM": "g",
         "TNE": "t", "MTR": "m", "MTK": "m²", "MTQ": "m³", "LTR": "l", "MLT": "ml", "HUR": "hod", "DAY": "den",
         "MON": "měs", "KMT": "km", "KWH": "kWh", "XPK": "bal", "XBX": "krab", "XPX": "pal", "ZZ": "", "LS": "pauš."}
MEANS = {"1": "neurčeno", "10": "hotově", "20": "šek", "30": "převodem", "31": "převodem", "42": "převodem na účet",
         "48": "kartou", "49": "inkasem", "57": "trvalým příkazem", "58": "SEPA převodem", "59": "SEPA inkasem",
         "97": "zápočtem", "ZZZ": "jiný"}
MEANS_EN = {"1": "not defined", "10": "cash", "20": "cheque", "30": "credit transfer", "31": "credit transfer",
            "42": "payment to bank account", "48": "card", "49": "direct debit", "57": "standing order",
            "58": "SEPA credit transfer", "59": "SEPA direct debit", "97": "clearing", "ZZZ": "other"}
VATCAT = {"S": "základní/snížená", "Z": "nulová sazba", "E": "osvobozeno", "AE": "přenesená daň. povinnost",
          "K": "dodání v rámci EU", "G": "vývoz", "O": "mimo předmět DPH", "L": "Kanárské ostrovy", "M": "Ceuta/Melilla"}
VATCAT_EN = {"S": "standard", "Z": "zero rated", "E": "exempt", "AE": "reverse charge", "K": "intra-community",
             "G": "export", "O": "outside scope", "L": "Canary Islands", "M": "Ceuta/Melilla"}


def _e(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _v(ctx: Context | None, bt: str) -> str | None:
    vs = ctx.values.get(bt) if ctx else None
    return vs[0].value if vs else None


def _all(ctx: Context | None, bt: str) -> list[str]:
    return [v.value for v in (ctx.values.get(bt) or [])] if ctx else []


def _dec(s) -> Decimal | None:
    try:
        return Decimal(str(s).replace(" ", "").replace(",", ".")) if s not in (None, "") else None
    except InvalidOperation:
        return None


def _num(s, places: int | None = 2) -> str:
    """1234.5 -> '1 234,50' (CZ/SK style); quantities keep their own precision without trailing zeros."""
    d = _dec(s)
    if d is None:
        return _e(s or "")
    if places is None:
        d = d.normalize()
        txt = f"{d:f}"
    else:
        txt = f"{d.quantize(Decimal(1).scaleb(-places)):f}"
    neg = txt.startswith("-")
    whole, _, frac = txt.lstrip("-").partition(".")
    whole = f"{int(whole):,}".replace(",", " ")
    return ("-" if neg else "") + whole + ("," + frac if frac else "")


def _date(s) -> str:
    s = (s or "").strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"{int(s[8:10])}. {int(s[5:7])}. {s[:4]}"
    if len(s) == 8 and s.isdigit():
        return f"{int(s[6:8])}. {int(s[4:6])}. {s[:4]}"
    return _e(s)


def _party(t: dict, title: str, ctx: Context, name, trade, street, street2, city, zip_, country, reg, vat,
           tax=None, legal=None, cname=None, cphone=None, cmail=None) -> str:
    nm = _v(ctx, name) or _v(ctx, trade)
    if not nm and not _v(ctx, street) and not _v(ctx, city):
        return ""
    rows = [f'<div class="pname">{_e(nm)}</div>']
    if _v(ctx, trade) and _v(ctx, trade) != nm:
        rows.append(f"<div>{_e(_v(ctx, trade))}</div>")
    for bt in (street, street2):
        if bt and _v(ctx, bt):
            rows.append(f"<div>{_e(_v(ctx, bt))}</div>")
    place = " ".join(x for x in (_v(ctx, zip_), _v(ctx, city)) if x)
    if place or _v(ctx, country):
        rows.append(f"<div>{_e(place)}{', ' if place and _v(ctx, country) else ''}{_e(_v(ctx, country) or '')}</div>")
    ids = []
    for key, bt in (("reg", reg), ("tax", tax), ("vat", vat)):
        if bt and _v(ctx, bt):
            ids.append(f"<tr><td>{t[key]}:</td><td>{_e(_v(ctx, bt))}</td></tr>")
    if ids:
        rows.append(f'<table class="ids">{"".join(ids)}</table>')
    if legal and _v(ctx, legal):
        rows.append(f'<div class="small">{_e(_v(ctx, legal))}</div>')
    contact = ", ".join(_e(_v(ctx, b)) for b in (cname, cphone, cmail) if b and _v(ctx, b))
    if contact:
        rows.append(f'<div class="small">{t["contact"]}: {contact}</div>')
    return f'<div class="party"><div class="lbl">{title}</div>{"".join(rows)}</div>'


def _kv(t: dict, pairs) -> str:
    rows = [f"<tr><td>{t[k]}</td><td>{v}</td></tr>" for k, v in pairs if v]
    return f'<table class="kv">{"".join(rows)}</table>' if rows else ""


def _line_extras(sem: Semantic, line: Context) -> list[tuple[bool, str, str | None, str | None]]:
    """(is_charge, amount, reason, percent) of the line-level allowances/charges, flat or as BG-27/BG-28 children."""
    out = []
    for amt, reason, code, pct, is_charge in (("BT-136", "BT-139", "BT-140", "BT-138", False),
                                              ("BT-141", "BT-144", "BT-145", "BT-143", True)):
        amts, rs, cs, ps = _all(line, amt), _all(line, reason), _all(line, code), _all(line, pct)
        for i, a in enumerate(amts):
            out.append((is_charge, a, (rs[i] if i < len(rs) else None) or (cs[i] if i < len(cs) else None),
                        ps[i] if i < len(ps) else None))
    for bg, is_charge, amt, reason, code, pct in (("BG-27", False, "BT-136", "BT-139", "BT-140", "BT-138"),
                                                   ("BG-28", True, "BT-141", "BT-144", "BT-145", "BT-143")):
        for c in sem.groups.get(bg, []):
            if c.parent is line and _v(c, amt):
                out.append((is_charge, _v(c, amt), _v(c, reason) or _v(c, code), _v(c, pct)))
    return out


def render(sem: Semantic, lang: str = "cs", source: str = "", footer: str = "") -> str:
    t = L.get(lang, L["cs"])
    units = UNITS if lang == "cs" else {k: ("pcs" if v == "ks" else v) for k, v in UNITS.items()}
    means = MEANS if lang == "cs" else MEANS_EN
    vatcat = VATCAT if lang == "cs" else VATCAT_EN
    d = sem.document
    cur = _v(d, "BT-5") or ""
    kind = _v(d, "BT-3") or ("381" if sem.doc_kind == "CreditNote" else "380")
    title = t.get(kind, t["invoice"])

    # header blocks
    seller = _party(t, t["supplier"], d, "BT-27", "BT-28", "BT-35", "BT-36", "BT-37", "BT-38", "BT-40",
                    "BT-30", "BT-31", "BT-32", "BT-33", "BT-41", "BT-42", "BT-43")
    buyer = _party(t, t["buyer"], d, "BT-44", "BT-45", "BT-50", "BT-51", "BT-52", "BT-53", "BT-55",
                   "BT-47", "BT-48", None, None, "BT-56", "BT-57", "BT-58")
    delivery = _party(t, t["delivery"], d, "BT-70", None, "BT-75", "BT-76", "BT-77", "BT-78", "BT-80", None, None)
    payee = _party(t, t["payee"], d, "BT-59", None, None, None, None, None, None, "BT-61", None)
    period = " – ".join(_date(x) for x in (_v(d, "BT-73"), _v(d, "BT-74")) if x)
    dates = _kv(t, [("issue", _date(_v(d, "BT-2"))), ("taxpoint", _date(_v(d, "BT-7"))),
                    ("deldate", _date(_v(d, "BT-72"))), ("period", period), ("due", _date(_v(d, "BT-9"))),
                    ("currency", _e(cur))])
    preceding = ", ".join(_e(x) for x in _all(d, "BT-25") + [_v(c, "BT-25") for c in sem.groups.get("BG-3", [])] if x)
    refs = _kv(t, [("order", _e(_v(d, "BT-13"))), ("salesorder", _e(_v(d, "BT-14"))),
                   ("buyerref", _e(_v(d, "BT-10") if _v(d, "BT-10") != _v(d, "BT-13") else None)),
                   ("contract", _e(_v(d, "BT-12"))), ("despatch", _e(_v(d, "BT-16"))),
                   ("receiving", _e(_v(d, "BT-15"))), ("project", _e(_v(d, "BT-11"))),
                   ("accounting", _e(_v(d, "BT-19"))), ("preceding", preceding)])
    code81 = _v(d, "BT-81")
    pm_name = _v(d, "BT-82") or (means.get(code81, code81) if code81 else None)
    ibans = _all(d, "BT-84") + [_v(c, "BT-84") for c in sem.groups.get("BG-17", []) if _v(c, "BT-84")]
    pay = _kv(t, [("means", _e(pm_name)), ("iban", "<br>".join(_e(x) for x in dict.fromkeys(ibans))),
                  ("bic", _e(_v(d, "BT-86"))), ("vs", _e(_v(d, "BT-83"))), ("terms", _e(_v(d, "BT-20")))])

    # lines
    lines = sem.groups.get("BG-25", [])
    any_extra = any(_line_extras(sem, ln) for ln in lines)
    any_code = any(_v(ln, "BT-155") or _v(ln, "BT-157") or _v(ln, "BT-156") for ln in lines)
    body = []
    for i, ln in enumerate(lines, 1):
        qty, amount = _dec(_v(ln, "BT-129")), _dec(_v(ln, "BT-131"))
        price, base_q = _dec(_v(ln, "BT-146")), _dec(_v(ln, "BT-149")) or Decimal(1)
        unit = _v(ln, "BT-130") or ""
        netunit = (amount / qty) if qty and amount is not None and qty != 0 else None
        unit_price = (price / base_q) if price is not None and base_q else None
        show_net = netunit is not None and (unit_price is None or abs(netunit - unit_price) >= Decimal("0.005"))
        extras = _line_extras(sem, ln)
        ex_html = "<br>".join(
            f'{"+" if ch else "−"}{_num(a)}' + (f" ({_num(p, None)} %)" if p else "")
            + (f'<div class="small">{_e(r)}</div>' if r else "") for ch, a, r, p in extras)
        name = _e(_v(ln, "BT-153") or "")
        desc = _v(ln, "BT-154")
        sub = []
        if desc and desc != _v(ln, "BT-153"):
            sub.append(_e(desc))
        if _v(ln, "BT-157") and _v(ln, "BT-155"):
            sub.append(f'{t["gtin"]} {_e(_v(ln, "BT-157"))}')
        for b in ("BT-127",):
            sub += [_e(x) for x in _all(ln, b)]
        if _v(ln, "BT-134") or _v(ln, "BT-135"):
            sub.append(" – ".join(_date(x) for x in (_v(ln, "BT-134"), _v(ln, "BT-135")) if x))
        gross = _v(ln, "BT-148")
        price_html = _num(_v(ln, "BT-146"), 4 if price is not None and price != price.quantize(Decimal("0.01")) else 2)
        if base_q != 1:
            price_html += f'<div class="small">/ {_num(base_q, None)} {_e(units.get(unit, unit))}</div>'
        if gross and _dec(gross) != price:
            price_html += f'<div class="small">({_num(gross)} − {_num(_v(ln, "BT-147"))})</div>'
        code = _e(_v(ln, "BT-155") or _v(ln, "BT-157") or _v(ln, "BT-156") or "")
        cells = [f'<td class="c">{_e(_v(ln, "BT-126") or i)}</td>']
        if any_code:
            cells.append(f"<td>{code}</td>")
        cells += [f'<td>{name}' + "".join(f'<div class="small">{s}</div>' for s in sub) + "</td>",
                  f'<td class="r">{_num(_v(ln, "BT-129"), None)}</td>', f"<td>{_e(units.get(unit, unit))}</td>",
                  f'<td class="r">{price_html}</td>']
        if any_extra:
            cells.append(f'<td class="r">{ex_html}</td>')
        cells += [f'<td class="r">{_num(netunit, 4) if show_net else ""}</td>',
                  f'<td class="r">{_num(_v(ln, "BT-152"), None) if _v(ln, "BT-152") else _e(_v(ln, "BT-151") or "")}</td>',
                  f'<td class="r b">{_num(_v(ln, "BT-131"))}</td>']
        body.append("<tr>" + "".join(cells) + "</tr>")
    head = [f'<th class="c">{t["pos"]}</th>'] + ([f'<th>{t["code"]}</th>'] if any_code else []) + [
        f'<th>{t["item"]}</th>', f'<th class="r">{t["qty"]}</th>', f'<th>{t["unit"]}</th>', f'<th class="r">{t["price"]}</th>'] + (
        [f'<th class="r">{t["disc"]}</th>'] if any_extra else []) + [
        f'<th class="r">{t["netunit"]}</th>', f'<th class="r">{t["vatpct"]}</th>', f'<th class="r">{t["net"]} ({_e(cur)})</th>']
    lines_html = f'<table class="lines"><thead><tr>{"".join(head)}</tr></thead><tbody>{"".join(body)}</tbody></table>'

    # document level allowances / charges
    ac = []
    for bg, key, amt, reason, code, pct, cat, rate in (
            ("BG-20", "allowance", "BT-92", "BT-97", "BT-98", "BT-94", "BT-95", "BT-96"),
            ("BG-21", "charge", "BT-99", "BT-104", "BT-105", "BT-101", "BT-102", "BT-103")):
        for c in sem.groups.get(bg, []):
            sign = "−" if key == "allowance" else "+"
            ac.append(f'<tr><td>{t[key]}</td><td>{_e(_v(c, reason) or _v(c, code) or "")}'
                      + (f' ({_num(_v(c, pct), None)} %)' if _v(c, pct) else "") + "</td>"
                      f'<td class="r">{_e(_v(c, cat) or "")} {_num(_v(c, rate), None) + " %" if _v(c, rate) else ""}</td>'
                      f'<td class="r b">{sign}{_num(_v(c, amt))}</td></tr>')
    ac_html = (f'<h3>{t["doclevel"]}</h3><table class="lines"><tbody>{"".join(ac)}</tbody></table>') if ac else ""

    # VAT breakdown
    vb = []
    for c in sem.groups.get("BG-23", []):
        cat = _v(c, "BT-118") or ""
        reason = _v(c, "BT-120") or _v(c, "BT-121") or ""
        vb.append(f'<tr><td>{_e(cat)} – {_e(vatcat.get(cat, ""))}' + (f'<div class="small">{_e(reason)}</div>' if reason else "")
                  + f'</td><td class="r">{_num(_v(c, "BT-119"), None) if _v(c, "BT-119") else ""} %</td>'
                  f'<td class="r">{_num(_v(c, "BT-116"))}</td><td class="r">{_num(_v(c, "BT-117"))}</td></tr>')
    vat_html = (f'<table class="lines vat"><thead><tr><th>{t["cat"]}</th><th class="r">{t["vatpct"]}</th>'
                f'<th class="r">{t["base"]}</th><th class="r">{t["vatamt"]}</th></tr></thead><tbody>{"".join(vb)}</tbody></table>') if vb else ""

    tot = [("sumlines", "BT-106"), ("sumallow", "BT-107"), ("sumcharge", "BT-108"), ("taxexcl", "BT-109"),
           ("vattotal", "BT-110"), ("taxincl", "BT-112"), ("prepaid", "BT-113"), ("rounding", "BT-114")]
    trows = [f'<tr><td>{t[k]}</td><td class="r">{_num(_v(d, bt))}</td></tr>' for k, bt in tot
             if _v(d, bt) and not (bt in ("BT-107", "BT-108", "BT-113", "BT-114") and _dec(_v(d, bt)) == 0)]
    if _v(d, "BT-111"):
        trows.append(f'<tr><td>{t["vatcur"]} ({_e(_v(d, "BT-6") or "")})</td><td class="r">{_num(_v(d, "BT-111"))}</td></tr>')
    totals = (f'<table class="totals">{"".join(trows)}<tr class="pay"><td>{t["payable"]}</td>'
              f'<td class="r">{_num(_v(d, "BT-115"))} {_e(cur)}</td></tr></table>')

    notes = _all(d, "BT-22")
    notes_html = (f'<h3>{t["notes"]}</h3>' + "".join(f'<p class="note">{_e(n)}</p>' for n in notes)) if notes else ""
    src = f'{t["source"]}: {_e(source)} · ' if source else ""

    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<title>{_e(title)} {_e(_v(d, "BT-1") or "")}</title><style>{CSS}</style></head><body>
<div class="head"><div><h1>{_e(title)}</h1><div class="docno">{t["no"]} {_e(_v(d, "BT-1") or "")}</div></div>
<div class="meta">{dates}</div></div>
<div class="parties">{seller}{buyer}</div>
<div class="parties">{delivery}{payee}<div class="party">{refs}</div><div class="party">{pay}</div></div>
<h3>{t["lines"]}</h3>{lines_html}
{ac_html}
<div class="sums"><div>{f'<h3>{t["vatbreak"]}</h3>' + vat_html if vat_html else ""}</div><div>{totals}</div></div>
{notes_html}
<div class="foot">{t["disclaimer"]}<br>{src}{_e(footer)}</div>
</body></html>"""


CSS = """
@page{size:A4;margin:14mm 12mm 16mm}
*{box-sizing:border-box}
body{font-family:"Segoe UI",Arial,Helvetica,sans-serif;font-size:9.5pt;color:#111;margin:0;background:#fff}
@media screen{body{max-width:210mm;margin:12px auto;padding:14mm 12mm;box-shadow:0 0 6px #0003}}
h1{font-size:20pt;margin:0;letter-spacing:.5px;text-transform:uppercase}
h3{font-size:10pt;margin:14px 0 4px;border-bottom:1px solid #999;padding-bottom:2px}
.docno{font-size:13pt;font-weight:600;margin-top:2px}
.head{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #111;padding-bottom:8px}
.parties{display:flex;gap:10px;margin-top:10px}
.party{flex:1;border:1px solid #bbb;border-radius:3px;padding:6px 8px;min-width:0}
.party:empty{display:none}
.lbl{font-size:8pt;text-transform:uppercase;color:#555;margin-bottom:2px}
.pname{font-weight:700;font-size:10.5pt}
.small{font-size:8pt;color:#444}
table{border-collapse:collapse}
.ids td,.kv td{padding:0 6px 0 0;vertical-align:top}
.kv td:first-child{color:#555;white-space:nowrap}.kv td+td{overflow-wrap:anywhere}
.lines{width:100%}
.lines th{background:#eee;font-size:8pt;text-align:left;padding:4px;border-bottom:1px solid #888}
.lines td{padding:4px;border-bottom:1px solid #ddd;vertical-align:top}
.lines tr{page-break-inside:avoid}
.r{text-align:right;white-space:nowrap}.c{text-align:center}.b{font-weight:600}
.sums{display:flex;gap:16px;justify-content:space-between;align-items:flex-start;margin-top:6px;page-break-inside:avoid}
.sums>div:first-child{flex:1}
.vat{width:100%}
.totals{margin-top:14px;min-width:75mm}
.totals td{padding:2px 6px}
.totals .pay td{font-size:12pt;font-weight:700;border-top:2px solid #111;padding-top:5px}
.note{margin:2px 0;font-size:8.5pt}
.foot{margin-top:18px;border-top:1px solid #bbb;padding-top:4px;font-size:7.5pt;color:#666}
"""


def browser() -> str | None:
    """A Chromium-based browser able to print to PDF headlessly (Edge first, it ships with Windows)."""
    cands = [os.environ.get("MSGVALIDATOR_BROWSER")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands += [os.path.join(base, r"Microsoft\Edge\Application\msedge.exe"),
                      os.path.join(base, r"Google\Chrome\Application\chrome.exe")]
    cands += [shutil.which(n) for n in ("msedge", "chrome", "chromium", "google-chrome")]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def to_pdf(html_text: str, timeout: int = 60) -> bytes:
    exe = browser()
    if not exe:
        raise RuntimeError("Pro PDF je potřeba Microsoft Edge nebo Google Chrome (nenalezen).")
    with tempfile.TemporaryDirectory(prefix="msgv_pdf_") as tmp:
        src, out = pathlib.Path(tmp, "invoice.html"), pathlib.Path(tmp, "invoice.pdf")
        src.write_text(html_text, encoding="utf-8")
        # own profile dir: a running Edge with the user's profile must not swallow the headless call
        cmd = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--disable-extensions",
               f"--user-data-dir={tmp}\\profile", "--no-pdf-header-footer", f"--print-to-pdf={out}", src.as_uri()]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(cmd, timeout=timeout, capture_output=True, creationflags=flags)
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("Prohlížeč nevytvořil PDF.")
        return out.read_bytes()


def for_report(rep, lang: str = "cs") -> str | None:
    """Print HTML of the first message of a validation report that has a semantic model."""
    from .. import __version__
    m = next((m for m in rep.messages if m.semantic), None)
    if m is None:
        return None
    return render(m.semantic, lang, source=f"{rep.filename} ({m.semantic.source_format})" if getattr(rep, "filename", None)
                  else m.semantic.source_format, footer=f"MsgValidator {__version__}")
