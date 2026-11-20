"""ORION XML INVOIC -> semantic model (EN 16931 BTs).

Driven by data/mappings/orion_invoic.json ('terms': BT -> ordered rules, generated from the ORION documentation
by tools/import_orion.py). Rule kinds:
  field  – value of one ORION field (path relative to the repeating group instance or to <orion_message>)
  fields – every non-empty value of the listed fields (e.g. all free texts -> BT-22)
  party  – the field is read from the header <party> with this qualifier (preference order, e.g. "SE|SU")
  map    – code conversion (value reported as 'mapped'), scheme – identifier scheme to add (0088 = GLN)
  derive – value is not in the message, a function below infers it (reported as derived / ambiguous)
  const  – the converter adds a constant (BT-23, BT-24)
The first rule that yields a value wins.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ..semantic.catalog import catalog, codelists
from ..semantic.model import Context, Semantic, Value
from . import mapping, parse, text, where

PARTY = "body/message_header/party"
HEADER = "body/message_header"


def _num(s: str | None) -> Decimal | None:
    try:
        return Decimal(s) if s is not None else None
    except InvalidOperation:
        return None


def _party(root, qualifiers: str):
    parties = root.findall(PARTY)
    for q in qualifiers.split("|"):
        for p in parties:
            if text(p.find("party_qualifier")) == q:
                return p
    return None


def _res(el, value, how="derived", note=None, scheme=None):
    return {"value": value, "el": el, "how": how, "note": note, "scheme": scheme}


# ------------------------------------------------------------------------------------------------ derivations
def endpoint_from_party(root, ctx_el, args):
    p = _party(root, args["party"])
    el = p.find("party_id") if p is not None else None
    gln = text(el)
    if gln and gln.isdigit() and len(gln) == 13:
        return _res(el, gln, scheme="0088")
    # no GLN: SK Peppol endpoint 0245 = DIČ (vat_id, 10 digits) or IČ DPH (tax_id) without the SK prefix
    for tag in ("vat_id", "tax_id"):
        el = p.find(tag) if p is not None else None
        v = (text(el) or "").replace(" ", "").upper()
        dic = v[2:] if v.startswith("SK") else v
        if dic.isdigit() and len(dic) == 10:
            return _res(el, dic, scheme="0245", note="GLN chybí – endpoint odvozen z DIČ (0245).")
    return None


def country_from_vat(root, ctx_el, args):
    p = _party(root, args["party"])
    el = p.find("tax_id") if p is not None else None
    vat = (text(el) or "").replace(" ", "")
    if len(vat) >= 2 and vat[:2].isalpha():
        return _res(el, vat[:2].upper())
    return None


def sk_tax_id_from_vat(root, ctx_el, args):
    p = _party(root, args["party"])
    el = p.find("tax_id") if p is not None else None
    vat = (text(el) or "").replace(" ", "")
    if vat.upper().startswith("SK") and vat[2:].isdigit():
        return _res(el, vat[2:])
    return None


def payment_terms_text(root, ctx_el, args):
    hdr = root.find(HEADER)
    if hdr is None:
        return None
    parts, first = [], None
    blocks = [hdr] + hdr.findall("skonto")
    for b in blocks:
        due, rate, amount = (text(b.find(t)) for t in ("discount_due_date", "discount_rate", "discount_amount"))
        if not (due or rate or amount):
            continue
        first = first if first is not None else next(b.find(t) for t in ("discount_due_date", "discount_rate",
                                                                          "discount_amount") if text(b.find(t)))
        s = "Skonto" + (f" {rate} %" if rate else "") + (f" ({amount})" if amount else "")
        parts.append(s + (f" při platbě do {due}" if due else ""))
    mtype, mval = text(hdr.find("skonto_maturity_date_type")), text(hdr.find("skonto_maturity_date_value"))
    if mval:
        parts.append(f"lhůta skonta {mval} {mtype or ''}".strip())
        first = first if first is not None else hdr.find("skonto_maturity_date_value")
    if not parts:
        return None
    return _res(first, "; ".join(parts), note="Text sestaven konverzí z polí skonta.")


def _vat_by_group(root, group: str):
    for v in root.findall("body/summary/tax_details/vat"):
        if text(v.find("vat_group")) == group:
            return v
    return None


def _category(rate: Decimal | None, reverse: bool, group: str | None = None):
    """(category, how, note) from an ORION VAT rate / group / reverse-charge flag."""
    if reverse:
        return "AE", "derived", "Přenesená daňová povinnost (reverse_charge=A) → kategorie AE."
    if rate is not None and rate > 0:
        return "S", "derived", None
    if rate is not None or group == "0":
        return "E", "ambiguous", ("Sazba 0 % / daňová skupina 0 (ORION: osvobozeno) → předpoklad E; může jít i o "
                                  "Z (nulová sazba), O (mimo předmět), K nebo G – nelze jednoznačně odvodit.")
    return None


def _flag(el, tag) -> bool | None:
    v = text(el.find(tag)) if el is not None else None
    return None if v is None else v.upper() == "A"


def vat_category(root, ctx_el, args):
    rc = _flag(ctx_el, "reverse_charge")
    if rc is None and not any(text(v.find("reverse_charge")) for v in root.findall("body/summary/tax_details/vat")):
        rc = _flag(root.find(HEADER), "reverse_charge")  # only the header says it (older senders)
    rate_el = ctx_el.find("vat_rate")
    cat = _category(_num(text(rate_el)), bool(rc), text(ctx_el.find("vat_group")))
    if cat is None:
        return None
    return _res(rate_el if text(rate_el) else ctx_el, cat[0], how=cat[1], note=cat[2])


def vat_exemption_code(root, ctx_el, args):
    res = vat_category(root, ctx_el, args)
    if res and res["value"] == "AE":
        return _res(res["el"], "VATEX-EU-AE")
    return None


def line_vat_category(root, ctx_el, args):
    rc = _flag(ctx_el, "reverse_charge")
    if rc is None:
        rc = _flag(root.find(HEADER), "reverse_charge")
    rate_el = ctx_el.find("vat_rate")
    cat = _category(_num(text(rate_el)), bool(rc))
    if cat is None:
        return None
    return _res(rate_el, cat[0], how=cat[1], note=cat[2])


def ac_category(root, ctx_el, args):
    group_el = ctx_el.find(mapping()["by_id"][args["field"]]["tag"])
    group = text(group_el)
    vat = _vat_by_group(root, group) if group else None
    if vat is None:
        return None
    res = vat_category(root, vat, {})
    if res:
        res["el"] = group_el
    return res


def ac_rate(root, ctx_el, args):
    group_el = ctx_el.find(mapping()["by_id"][args["field"]]["tag"])
    group = text(group_el)
    vat = _vat_by_group(root, group) if group else None
    rate = text(vat.find("vat_rate")) if vat is not None else None
    return _res(group_el, rate) if rate else None


def article_id_add(root, ctx_el, args):
    for add in ctx_el.findall("article_id_add"):
        if text(add.find("article_id_type")) == args["type"] and text(add.find("article_id_code")):
            return _res(add.find("article_id_code"), text(add.find("article_id_code")), how="explicit",
                        note=f"Převzato z doplňkového čísla zboží (article_id_type={args['type']}).")
    return None


DERIVERS = {f.__name__: f for f in (endpoint_from_party, country_from_vat, sk_tax_id_from_vat, payment_terms_text,
                                    vat_category, vat_exemption_code, line_vat_category, ac_category, ac_rate, article_id_add)}


# ------------------------------------------------------------------------------------------------ engine
def _label(bg, el, n, parent: Context | None = None):
    if bg == "BG-25":
        return f"řádek {text(el.find('item_number')) or n}"
    if bg == "BG-23":
        rc = " AE" if _flag(el, "reverse_charge") else ""
        return f"DPH {text(el.find('vat_rate')) or '?'} % (skupina {text(el.find('vat_group')) or '?'}{rc})"
    if bg in ("BG-27", "BG-28"):
        return f"{parent.label} – {'sleva' if bg == 'BG-27' else 'přirážka'} #{n}"
    return {"BG-20": "sleva dokladu", "BG-21": "přirážka dokladu"}[bg] + f" #{n}"


def _hint_path(field: dict, rule: dict, base: str | None) -> str:
    path = field["path"]
    if rule.get("party"):
        path = path.replace(PARTY + "/", f"{PARTY}[party_qualifier={rule['party']}]/", 1)
    if base and path.startswith(base + "/"):
        path = path[len(base) + 1:]
    return path


def _apply(bt, rules, ctx: Context, ctx_el, root, base: str | None, fields: dict) -> None:
    for rule in rules:
        if "const" in rule:
            ctx.add(Value(bt, rule["const"], how="const", note=rule.get("note"), rule="const"))
            return
        if "derive" in rule:
            res = DERIVERS[rule["derive"]](root, ctx_el, rule.get("args", {}))
            if res and res.get("value"):
                el = res["el"]
                note = "; ".join(x for x in (rule.get("note"), res.get("note")) if x) or None
                ctx.add(Value(bt, res["value"], how=res["how"], line=el.sourceline if el is not None else None,
                              segment=where(el) if el is not None else None, scheme=res.get("scheme"),
                              note=note, rule=rule["derive"]))
                return
            continue
        found = False
        for fid in rule.get("fields") or [rule["field"]]:
            f = fields[fid]
            path = f["path"]
            if rule.get("party"):
                holder = _party(root, rule["party"])
                path = path[len(PARTY) + 1:]
            else:
                holder = ctx_el
                if base:
                    if not path.startswith(base + "/"):
                        continue
                    path = path[len(base) + 1:]
            if holder is None:
                continue
            for el in holder.findall(path):
                value = text(el)
                if not value:
                    continue
                how, raw, note = "explicit", None, rule.get("note") if not rule.get("map") else None
                if rule.get("map") and value in rule["map"]:
                    raw, value, how, note = value, rule["map"][value], "mapped", rule.get("note")
                ctx.add(Value(bt, value, how=how, line=el.sourceline, segment=where(el), raw=raw,
                              scheme=rule.get("scheme"), note=note, rule=fid))
                found = True
                if "fields" not in rule:
                    break
        if found:
            return


def read(data: bytes) -> Semantic:
    root = parse(data)
    mp = mapping()
    cat = catalog()
    fields = mp["by_id"]
    groups_cfg = mp["groups"]

    repeating: dict[str, str] = {}
    for bt in mp["terms"]:
        for anc in cat.ancestors(bt):
            if anc in groups_cfg:
                repeating[bt] = anc
                break

    document = Context(None, "doklad", root.sourceline)
    groups: dict[str, list[Context]] = {}
    group_els: dict[str, list] = {}
    for bg, cfg in groups_cfg.items():
        groups[bg], group_els[bg] = [], []
        if cfg.get("parent"):
            pbase = groups_cfg[cfg["parent"]]["each"]
            sub = cfg["each"][len(pbase) + 1:]
            for pel, pctx in zip(group_els[cfg["parent"]], groups[cfg["parent"]]):
                for n, el in enumerate(pel.findall(sub), 1):
                    groups[bg].append(Context(bg, _label(bg, el, n, pctx), el.sourceline, parent=pctx))
                    group_els[bg].append(el)
            continue
        for n, el in enumerate(root.findall(cfg["each"]), 1):
            groups[bg].append(Context(bg, _label(bg, el, n), el.sourceline))
            group_els[bg].append(el)

    rules_hint: dict[str, list[dict]] = {}
    for bt, rules in mp["terms"].items():
        bg = repeating.get(bt)
        base = groups_cfg[bg]["each"] if bg else None
        rules_hint[bt] = []
        for r in rules:
            for fid in r.get("fields") or ([r["field"]] if "field" in r else []):
                rules_hint[bt].append({"path": _hint_path(fields[fid], r, base), "value": "text", "var": fid})
            if "derive" in r or "const" in r:
                rules_hint[bt].append({k: v for k, v in r.items() if k in ("derive", "const", "note")})
        if bg is None:
            _apply(bt, rules, document, root, root, None, fields)
        else:
            for el, ctx in zip(group_els[bg], groups[bg]):
                _apply(bt, rules, ctx, el, root, base, fields)

    # helper facts outside EN 16931 (e.g. item_type: Z goods / O packaging / S service)
    for key, cfg in mp.get("aux", {}).items():
        bg = cfg.get("group")
        base = groups_cfg[bg]["each"] if bg else None
        targets = zip(group_els[bg], groups[bg]) if bg else [(root, document)]
        for el, ctx in targets:
            tmp = Context(bg, ctx.label, ctx.line)
            _apply(key, cfg["rules"], tmp, el, root, base, fields)
            if tmp.values.get(key):
                ctx.aux[key] = tmp.values[key][0]

    notes = []
    # ORION sends one <vat> per VAT group, often with zero amounts; keep only those a line (or a non-zero amount) uses
    line_keys = {(_first(ln, "BT-151"), _norm(_first(ln, "BT-152"))) for ln in groups.get("BG-25", [])}
    kept = []
    for ctx in groups.get("BG-23", []):
        base_amt, tax = _num(_first(ctx, "BT-116")), _num(_first(ctx, "BT-117"))
        if not base_amt and not tax and (_first(ctx, "BT-118"), _norm(_first(ctx, "BT-119"))) not in line_keys:
            notes.append({"line": ctx.line, "code": "ORION-EMPTY-VAT",
                          "message": f"BG-23 {ctx.label}: prázdná daňová skupina (základ i daň 0, žádný řádek s touto "
                                     f"sazbou/kategorií) – konverze ji vynechá."})
            continue
        kept.append(ctx)
    groups["BG-23"] = kept

    bt3 = document.values.get("BT-3")
    cn_codes = codelists().get("UNCL1001-cn", {}).get("codes", {})
    doc_kind = "CreditNote" if bt3 and bt3[0].value in cn_codes else "Invoice"
    if doc_kind == "CreditNote":
        neg = [v for c in [document, *groups.get("BG-25", [])] for b in ("BT-112", "BT-115", "BT-131")
               for v in c.values.get(b, []) if (_num(v.value) or 0) < 0]
        if neg:
            notes.append({"line": neg[0].line, "code": "ORION-CN-SIGN",
                          "message": "Dobropis ORION nese záporné částky; Peppol CreditNote má částky kladné – "
                                     "konverze musí obrátit znaménka."})

    version = root.findtext("header/version")
    return Semantic(
        source_format=f"ORION XML INVOIC {version or ''}".strip(),
        mapping_id=mp["id"],
        document=document,
        groups=groups,
        mapped_terms=set(mp["terms"]),
        rules=rules_hint,
        repeating=repeating,
        notes=notes,
        doc_kind=doc_kind,
    )


def _first(ctx: Context, bt: str) -> str | None:
    vals = ctx.values.get(bt)
    return vals[0].value if vals else None


def _norm(rate: str | None):
    n = _num(rate)
    return n.normalize() if n is not None else None

