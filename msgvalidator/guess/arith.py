"""ODHAD – aritmetika jako důkaz: vztahy mezi čísly potvrdí, vyvrátí nebo doplní přiřazení částek.

Názvy polí jsou jen indicie; čísla se dají ověřit. Hledáme vztahy, které na názvech nezávisí:
  * řádek:   množství × cena (/ cenová jednotka 10/100/1000) = částka řádku
  * řádky:   Σ částek řádků = BT-106,  daň řádku / částka řádku = sazba,  Σ částka × sazba = BT-110
  * doklad:  netto + DPH = celkem  (BT-109 + BT-110 = BT-112)
  * DPH:     základ × sazba = daň v každé skupině BG-23,  Σ daní = BT-110,  Σ základů = BT-109
  * jednorázová rekapitulace DPH na úrovni dokladu (prvek se základem a sazbou, jejichž součin = BT-110)

find()     – důkazy nad všemi číselnými poli (před přiřazením): support / refute pro (úroveň, BT, pole)
apply()    – promítne důkazy do kandidátů podle názvů (posílí, oslabí, přidá nové)
verify()   – po přiřazení přepočítá vztahy s vybranými poli a výsledek (✓ / ✗ s čísly) zapíše do reasons
complete() – co ve formátu chybí a dá se spočítat: BT-110, BT-106, BT-109, BT-112, BT-115, rekapitulace DPH
             (BG-23) z řádků, sazba řádku z daně řádku → sekce `computed:` klientského mapování
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .shapes import TYPICAL_RATES, number

STRONG, WEAK = 0.3, 0.6  # remaining doubt after support: c' = 1 - (1 - c) * factor
NEW_CONF = {True: 0.72, False: 0.5}  # arithmetic only, no name match
BASES = {Decimal(10), Decimal(100), Decimal(1000)}  # price base quantities
HUNDRED = Decimal(100)
TAX_WORDS = ("tax", "vat", "dph", "dan", "mwst", "steuer", "iva", "imposta")
CENT = Decimal("0.01")


def dec(v: str | None) -> Decimal | None:
    if v is None:
        return None
    n = number(v)
    if n is None:
        return None
    s = v.strip().replace(" ", "").replace(" ", "")
    if n[1] == ",":
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def r2(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(d: Decimal) -> str:
    return format(r2(d), "f")


def close(a: Decimal, b: Decimal, n: int = 1) -> bool:
    """Equal up to rounding: 1 cent per summed item + 1 cent (absolute – sums must add up to the cent)."""
    return abs(a - b) <= CENT * n + CENT


def snap_rate(r: Decimal) -> Decimal | None:
    best = min(TYPICAL_RATES, key=lambda t: abs(r - t))
    return Decimal(best) if abs(r - best) <= Decimal("0.5") else None


def per_instance(f, depth: int) -> dict[int, Decimal]:
    """First numeric value of the field in every instance of the group at the given depth."""
    out: dict[int, Decimal] = {}
    for v, ch in zip(f.values, f.chains):
        if len(ch) >= depth and ch[depth - 1] not in out:
            d = dec(v)
            if d is not None:
                out[ch[depth - 1]] = d
    return out


def _amount_like(f) -> bool:
    sh = f.shape()
    if sh.get("num", 0) < 0.99 or sh.get("date", 0) or sh.get("gtin", 0) >= 0.5:
        return False
    if any(len(v) > 1 and v[0] == "0" and v[1].isdigit() for v in f.values):
        return False  # codes such as '002'
    return not all(v.isdigit() and len(v) >= 8 for v in f.values)  # ids, GLN, order numbers


def written_int(f) -> bool:
    """Values written without decimals ('1', '5') – counters, line numbers, codes; only weak evidence as amounts."""
    return all(v.lstrip("+-").isdigit() for v in f.values)


def _product_ok(q: Decimal, p: Decimal, a: Decimal, base: Decimal | None = None) -> bool:
    """quantity x price (/ price base 10/100/1000) = amount, allowing for a unit price rounded to 2 decimals."""
    if abs(q * p - a) <= CENT + abs(q) * Decimal("0.005"):
        return True
    return base in BASES and abs(q * p / base - a) <= CENT + abs(q) * Decimal("0.005") / base


# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Evidence:
    support: dict = field(default_factory=dict)  # (level, bt) -> {field key: (strong, text)}
    refute: dict = field(default_factory=dict)  # (level, bt) -> {field key: text}
    facts: list[str] = field(default_factory=list)
    vat_group: tuple | None = None  # document-level element that is a (single) VAT breakdown
    vat_reasons: list[str] = field(default_factory=list)
    line_tax: tuple | None = None  # key of the line field carrying the line VAT amount
    line_tax_text: str = ""

    def add(self, level, bt, key, strong: bool, text: str) -> None:
        slot = self.support.setdefault((level, bt), {})
        if key not in slot or (strong and not slot[key][0]):
            slot[key] = (strong, text)

    def no(self, level, bt, key, text: str) -> None:
        if key not in self.support.get((level, bt), {}):
            self.refute.setdefault((level, bt), {})[key] = text


def _best(cands, level, bt):
    """Key of the strongest name candidate for (level, bt)."""
    best = None
    for c in cands:
        if c[2] == bt and c[3] == level and (best is None or c[0] > best[0]):
            best = c
    return best[4] if best else None


def _label(fields, key) -> str:
    f = fields[key]
    return f"{f.path[-1]}/{f.name}"


def find(fields, groups, counts, cands) -> Evidence:
    ev = Evidence()
    line = groups.get("BG-25")
    vat = groups.get("BG-23")
    in_group = lambda p, g: g is not None and p[:len(g["path"])] == g["path"]

    # ------------------------------------------------------------------ document totals
    doc: dict[tuple, Decimal] = {}
    for key, f in fields.items():
        if in_group(f.path, line) or in_group(f.path, vat) or not _amount_like(f) or len(set(f.values)) != 1:
            continue
        d = dec(f.values[0])
        if d is not None and d != 0:
            doc[key] = d
    wint = {k for k in doc if written_int(fields[k])}
    triples = []  # (N, T, G, typical-rate ratio?)
    keys = list(doc)
    for kn in keys:
        for kt in keys:
            n, t = doc[kn], doc[kt]
            if kn == kt or (n > 0) != (t > 0) or abs(t) >= abs(n) or abs(t) / abs(n) > Decimal("0.35"):
                continue
            for kg in keys:
                if kg in (kn, kt) or not close(n + t, doc[kg]):
                    continue
                typical = snap_rate(t / n * HUNDRED) is not None and abs(t / n * HUNDRED - snap_rate(t / n * HUNDRED)) <= Decimal("0.05")
                triples.append((kn, kt, kg, typical))
    corrob_n: set = set()
    corrob_t: set = set()

    # ------------------------------------------------------------------ invoice lines
    amount_key = None
    n_lines = 0
    if line:
        depth = len(line["path"])
        n_lines = counts.get(line["path"], 0)
        need = max(1, int(0.8 * n_lines))
        vecs = {k: per_instance(f, depth) for k, f in fields.items()
                if f.path[:depth] == line["path"] and _amount_like(f)}
        vecs = {k: v for k, v in vecs.items() if len(v) >= need}
        bases = [k for k, v in vecs.items() if set(v.values()) <= BASES]
        products = []
        ks = list(vecs)
        for i, kq in enumerate(ks):
            for kp in ks[i + 1:]:
                for ka in ks:
                    if ka in (kq, kp):
                        continue
                    common = set(vecs[kq]) & set(vecs[kp]) & set(vecs[ka])
                    if len(common) < need:
                        continue
                    a_all = [vecs[ka][x] for x in common]
                    if all(a == 0 for a in a_all):
                        continue
                    base_used = None
                    ok = all(_product_ok(vecs[kq][x], vecs[kp][x], vecs[ka][x]) for x in common)
                    if not ok:
                        for kb in bases:
                            if kb not in (kq, kp, ka) and all(
                                    _product_ok(vecs[kq][x], vecs[kp][x], vecs[ka][x], vecs[kb].get(x)) for x in common):
                                ok, base_used = True, kb
                                break
                    if not ok:
                        continue
                    nontrivial = sum(1 for x in common if vecs[ka][x] != 0
                                     and vecs[kq][x] not in (0, 1) and vecs[kp][x] not in (0, 1))
                    if not nontrivial:
                        continue
                    integral = all(v == v.to_integral_value() for k in (kp, ka) for v in vecs[k].values())
                    strong = (nontrivial >= 2 or n_lines == 1) and not integral
                    products.append((strong, kq, kp, ka, base_used, min(common)))
        cand_q, cand_p = _best(cands, "line", "BT-129"), _best(cands, "line", "BT-146")
        for strong, kq, kp, ka, kb, x in products:
            # which factor is the quantity: name first, then whole numbers
            if kq == cand_p or kp == cand_q or (
                    kq != cand_q and kp != cand_p and all(v == int(v) for v in vecs[kp].values())
                    and not all(v == int(v) for v in vecs[kq].values())):
                kq, kp = kp, kq
            q, p, a = vecs[kq][x], vecs[kp][x], vecs[ka][x]
            txt = (f"aritmetika řádku: {_label(fields, kq)} × {_label(fields, kp)}"
                   + (f" / {_label(fields, kb)}" if kb else "") + f" = {_label(fields, ka)} "
                   f"({q.normalize():f} × {p.normalize():f}{' / ' + format(vecs[kb][x].normalize(), 'f') if kb else ''}"
                   f" = {fmt(a)}{', u všech řádků' if strong and n_lines > 1 else ''})")
            ev.add("line", "BT-131", ka, strong, txt)
            ev.add("line", "BT-129", kq, strong, txt)
            ev.add("line", "BT-146", kp, strong, txt)
            if kb:
                ev.add("line", "BT-149", kb, strong, txt)
            ev.facts.append(txt)
        strong_prod = [pr for pr in products if pr[0]]
        if strong_prod:  # a name candidate that contradicts the proven product
            for bt, idx in (("BT-131", 3), ("BT-146", 2)):
                proven = {pr[idx] for pr in strong_prod} | ({pr[1] for pr in strong_prod} if bt == "BT-146" else set())
                for c in {x[4] for x in cands if x[2] == bt and x[3] == "line"}:
                    if c in vecs and c not in proven and all(vecs[c] != vecs[k] for k in proven if k in vecs):
                        ev.no("line", bt, c, f"aritmetika řádku to vyvrací (sedí jiné pole: "
                                             f"{', '.join(_label(fields, k) for k in sorted(proven)[:2])})")
        # the line amount used for sums: proven product amount (best named), else the best name candidate
        proven_a = [pr[3] for pr in strong_prod] or [pr[3] for pr in products]
        named = _best(cands, "line", "BT-131")
        amount_key = named if named in proven_a else (proven_a[0] if proven_a else (named if named in vecs else None))
        if amount_key:
            av = vecs[amount_key]
            total = sum(av.values(), Decimal(0))
            for kd, d in doc.items():
                if close(total, d, len(av)):
                    strong = len(av) >= 2 and kd not in wint
                    txt = f"Σ částek řádků ({len(av)}× {_label(fields, amount_key)}) = {fmt(total)}"
                    ev.add("doc", "BT-106", kd, strong, txt)
                    ev.add("doc", "BT-109", kd, False, txt + " (bez slev a poplatků dokladu)")
                    if strong:
                        corrob_n.add(kd)
            # line VAT amount: tax / amount is a typical rate on every line
            for kx, xv in vecs.items():
                if kx == amount_key or len(set(xv) & set(av)) < need or written_int(fields[kx]):
                    continue
                rates, ok = [], True
                for i in set(xv) & set(av):
                    a, t = av[i], xv[i]
                    if a == 0:
                        continue
                    r = snap_rate(t / a * HUNDRED)
                    if r is None or not close(r2(a * r / HUNDRED), t) or t == a:
                        ok = False
                        break
                    rates.append(r)
                if ok and rates and any(r > 0 for r in rates) and any(xv[i] != 0 for i in xv):
                    tsum = sum(xv.values(), Decimal(0))
                    totals = [kd for kd, d in doc.items() if close(tsum, d, len(xv)) and kd not in wint]
                    named = any(w in fields[kx].name.lower() for w in TAX_WORDS)
                    if not totals and not (named and not doc):
                        continue  # e.g. price / amount = 20 % by coincidence
                    ev.line_tax = kx
                    ev.line_tax_text = (f"sazba = daň řádku / částka řádku ({_label(fields, kx)} / "
                                        f"{_label(fields, amount_key)} → {', '.join(sorted({f'{r:f}' for r in rates}))} %"
                                        + (f"; Σ daní řádků {fmt(tsum)} = DPH celkem" if totals else "") + ")")
                    for kd in totals:
                        ev.add("doc", "BT-110", kd, True, f"Σ daní řádků ({_label(fields, kx)}) = {fmt(tsum)}")
                        corrob_t.add(kd)
                    break

    # ------------------------------------------------------------------ triples (now with corroboration)
    def integral(*ks):
        return all(doc[k] == doc[k].to_integral_value() for k in ks) or any(k in wint for k in ks)

    def tstrong(kn, kt, kg, typical):
        return kn in corrob_n or kt in corrob_t or (typical and not integral(kn, kt, kg))

    triples.sort(key=lambda t: (t[0] in corrob_n or t[1] in corrob_t, t[3], not integral(*t[:3]),
                                abs(doc[t[2]])), reverse=True)
    for kn, kt, kg, typical in triples:
        strong = tstrong(kn, kt, kg, typical)
        txt = (f"netto + DPH = celkem: {_label(fields, kn)} {fmt(doc[kn])} + {_label(fields, kt)} {fmt(doc[kt])} "
               f"= {_label(fields, kg)} {fmt(doc[kg])}" + (f" (DPH {fmt(doc[kt] / doc[kn] * HUNDRED)} %)" if typical else ""))
        ev.add("doc", "BT-109", kn, strong, txt)
        ev.add("doc", "BT-110", kt, strong, txt)
        ev.add("doc", "BT-112", kg, strong, txt)
        for kd, d in doc.items():
            if kd != kg and d == doc[kg]:
                ev.add("doc", "BT-115", kd, False, f"stejná částka jako celkem s DPH ({fmt(d)})")
        if strong:
            ev.facts.append(txt)
    strong_t = {kt: doc[kt] for kt in corrob_t}  # best first
    strong_t |= {kt: doc[kt] for kn, kt, kg, typ in triples if tstrong(kn, kt, kg, typ) and kt not in strong_t}

    # ------------------------------------------------------------------ line rates against the total VAT
    if line and amount_key and strong_t:
        depth = len(line["path"])
        av = per_instance(fields[amount_key], depth)
        tval = next(iter(strong_t.values()))
        for k, f in fields.items():
            if f.path[:depth] != line["path"] or f.shape().get("percent", 0) < 0.99:
                continue
            rv = per_instance(f, depth)
            if len(set(rv) & set(av)) < max(1, int(0.8 * len(av))):
                continue
            est = sum((av[i] * rv[i] / HUNDRED for i in set(rv) & set(av)), Decimal(0))
            if close(est, tval, len(av) + 1) or abs(est - tval) <= Decimal("0.005") * len(av) + CENT:
                ev.add("line", "BT-152", k, True, f"Σ částka řádku × sazba = {fmt(est)} = DPH celkem {fmt(tval)}")
            elif tval and abs(est - tval) / abs(tval) > Decimal("0.02"):
                ev.no("line", "BT-152", k, f"nejsou to sazby DPH: Σ částka řádku × {f.name} = {fmt(est)}, "
                                           f"DPH celkem je {fmt(tval)}")

    # ------------------------------------------------------------------ VAT breakdown (BG-23)
    if vat:
        depth = len(vat["path"])
        vecs = {k: per_instance(f, depth) for k, f in fields.items() if f.path[:depth] == vat["path"] and _amount_like(f)}
        rates = [k for k, f in fields.items() if k in vecs and f.shape().get("percent", 0) >= 0.99]
        found = None
        for kr in rates:
            for kb in vecs:
                for kt in vecs:
                    if len({kr, kb, kt}) < 3:
                        continue
                    common = set(vecs[kr]) & set(vecs[kb]) & set(vecs[kt])
                    if not common or not any(vecs[kr][i] > 0 and vecs[kb][i] != 0 for i in common):
                        continue
                    if all(close(r2(vecs[kb][i] * vecs[kr][i] / HUNDRED), vecs[kt][i], 2) for i in common):
                        txt = (f"základ × sazba = daň v každé skupině DPH ({_label(fields, kb)} × {_label(fields, kr)} "
                               f"= {_label(fields, kt)})")
                        ev.add("vat", "BT-116", kb, True, txt)
                        ev.add("vat", "BT-119", kr, True, txt)
                        ev.add("vat", "BT-117", kt, True, txt)
                        ev.facts.append(txt)
                        found = found or (kb, kt)
        if found:
            kb, kt = found
            for key, bt, dst in ((kt, "BT-110", corrob_t), (kb, "BT-109", corrob_n)):
                s = sum(vecs[key].values(), Decimal(0))
                for kd, d in doc.items():
                    if close(s, d, len(vecs[key])):
                        ev.add("doc", bt, kd, kd not in wint, f"Σ {'daní' if bt == 'BT-110' else 'základů'} rekapitulace DPH = {fmt(s)}")
    elif strong_t:
        # a single VAT breakdown at document level: element with a base and a rate whose product is the total VAT
        tval = next(iter(strong_t.values()))
        for kb, b in doc.items():
            fb = fields[kb]
            if len(fb.path) < 2 or kb in strong_t or counts.get(fb.path, 0) != 1:
                continue
            for kr, fr in fields.items():
                if fr.path[:len(fb.path)] != fb.path or len(fr.path) > len(fb.path) + 1 or kr == kb:
                    continue
                r = dec(fr.values[0]) if len(set(fr.values)) == 1 else None
                if r is None or r <= 0 or snap_rate(r) != r or not close(r2(b * r / HUNDRED), tval, 2):
                    continue
                if any(f.path == fb.path and k in strong_t for k, f in fields.items()):
                    continue  # the totals element itself (net + tax + gross), not a breakdown
                ev.vat_group = fb.path
                ev.vat_reasons = [f"jediná rekapitulace DPH na úrovni dokladu: {_label(fields, kb)} {fmt(b)} × "
                                  f"{fr.name} {r.normalize():f} % = DPH celkem {fmt(tval)}"]
                ev.add("vat", "BT-116", kb, True, ev.vat_reasons[0])
                ev.add("vat", "BT-119", kr, True, ev.vat_reasons[0])
                for kt, ft in fields.items():
                    if ft.path[:len(fb.path)] != fb.path or kt in (kb, kr) or not _amount_like(ft):
                        continue
                    if dec(ft.values[0]) is not None and close(dec(ft.values[0]), tval):
                        ev.add("vat", "BT-117", kt, True, ev.vat_reasons[0])
                    else:
                        ev.no("vat", "BT-117", kt, f"není to daň skupiny: základ × sazba = {fmt(tval)}, "
                                                  f"pole má {ft.values[0]}")
                break
            if ev.vat_group:
                break
    return ev


def apply(ev: Evidence, cands: list, fields, level_of) -> list:
    """Name candidates adjusted by the arithmetic; supported fields without a name match become candidates too."""
    out, seen = [], set()
    for conf, depth, bt, level, key, gpath, reasons in cands:
        sup = ev.support.get((level, bt), {}).get(key)
        ref = ev.refute.get((level, bt), {}).get(key)
        if sup:
            conf = 1 - (1 - conf) * (STRONG if sup[0] else WEAK)
            reasons = reasons + [("✓ " if sup[0] else "≈ ") + sup[1]]
        elif ref:
            conf *= 0.3
            reasons = reasons + ["✗ " + ref]
        elif any(strong for strong, _ in ev.support.get((level, bt), {}).values()):
            conf *= 0.6
            reasons = reasons + ["✗ aritmetika ukazuje na jiné pole"]
        out.append((conf, depth, bt, level, key, gpath, reasons))
        seen.add((level, bt, key))
    for (level, bt), slot in ev.support.items():
        for key, (strong, txt) in slot.items():
            if (level, bt, key) in seen or key not in fields or not strong:
                continue
            lv, gpath = level_of(fields[key].path)
            if lv != level:
                continue
            out.append((NEW_CONF[strong], -len(fields[key].path), bt, level, key, gpath,
                        [("✓ " if strong else "≈ ") + txt + " (název pole nenapovídá)"]))
    out.sort(key=lambda c: (-c[0], -c[1], c[2]))
    return out


# ---------------------------------------------------------------------------------------------------------------
class _Vals:
    """Numbers of the assigned proposals: document values and per-instance vectors of the groups."""

    def __init__(self, props, groups):
        self.p = {(p.level, p.bt): p for p in props}
        self.groups = groups

    def doc(self, bt) -> Decimal | None:
        p = self.p.get(("doc", bt))
        if p is None or p.field is None or "path" not in p.rule:
            return None
        return dec(p.field.values[0])

    def vec(self, level, bt) -> dict[int, Decimal]:
        p = self.p.get((level, bt))
        g = self.groups.get({"line": "BG-25", "vat": "BG-23"}[level])
        if p is None or p.field is None or g is None or "path" not in p.rule:
            return {}
        return per_instance(p.field, len(g["path"]))


def verify(props, groups, annotate: bool = True) -> list[dict]:
    """Recompute the relations with the chosen fields; the result goes into the proposals' reasons and confidence."""
    v = _Vals(props, groups)
    checks = []

    def check(rule, ok, detail, bts):
        checks.append({"rule": rule, "ok": ok, "detail": detail, "bts": bts})

    q, pr, a = v.vec("line", "BT-129"), v.vec("line", "BT-146"), v.vec("line", "BT-131")
    base = v.vec("line", "BT-149")
    common = set(q) & set(pr) & set(a)
    if common:
        bad = [i for i in sorted(common) if not _product_ok(q[i], pr[i], a[i], base.get(i))]
        check("množství × cena = částka řádku", not bad,
              f"sedí {len(common) - len(bad)} z {len(common)} řádků" + (
                  f" (např. {q[bad[0]].normalize():f} × {pr[bad[0]].normalize():f} ≠ {fmt(a[bad[0]])}; "
                  "rozdíl může být sleva řádku)" if bad else ""),
              [("line", "BT-129"), ("line", "BT-146"), ("line", "BT-131")])
    b106, b109, b110, b112, b113, b115 = (v.doc(b) for b in ("BT-106", "BT-109", "BT-110", "BT-112", "BT-113", "BT-115"))
    if a and b106 is not None:
        s = sum(a.values(), Decimal(0))
        check("Σ částek řádků = BT-106", close(s, b106, len(a)), f"{fmt(s)} vs {fmt(b106)}",
              [("line", "BT-131"), ("doc", "BT-106")])
    if None not in (b109, b110, b112):
        check("BT-109 + BT-110 = BT-112", close(b109 + b110, b112), f"{fmt(b109)} + {fmt(b110)} = {fmt(b109 + b110)} vs {fmt(b112)}",
              [("doc", "BT-109"), ("doc", "BT-110"), ("doc", "BT-112")])
    if b112 is not None and b115 is not None and b113 is not None:
        check("BT-112 − BT-113 = BT-115", close(b112 - b113, b115), f"{fmt(b112)} − {fmt(b113)} vs {fmt(b115)}",
              [("doc", "BT-112"), ("doc", "BT-113"), ("doc", "BT-115")])
    vb, vr, vt = v.vec("vat", "BT-116"), v.vec("vat", "BT-119"), v.vec("vat", "BT-117")
    common = set(vb) & set(vr) & set(vt)
    if common:
        bad = [i for i in common if not close(r2(vb[i] * vr[i] / HUNDRED), vt[i], 2)]
        check("základ × sazba = daň (BG-23)", not bad, f"sedí {len(common) - len(bad)} z {len(common)} skupin",
              [("vat", "BT-116"), ("vat", "BT-119"), ("vat", "BT-117")])
    if vt and b110 is not None:
        s = sum(vt.values(), Decimal(0))
        check("Σ DPH skupin = BT-110", close(s, b110, len(vt)), f"{fmt(s)} vs {fmt(b110)}", [("vat", "BT-117"), ("doc", "BT-110")])
    if vb and b109 is not None:
        s = sum(vb.values(), Decimal(0))
        check("Σ základů skupin = BT-109", close(s, b109, len(vb)), f"{fmt(s)} vs {fmt(b109)}", [("vat", "BT-116"), ("doc", "BT-109")])
    lr = v.vec("line", "BT-152")
    if a and lr and b110 is not None and not vt:
        s = sum((a[i] * lr[i] / HUNDRED for i in set(a) & set(lr)), Decimal(0))
        check("Σ částka řádku × sazba = BT-110", abs(s - b110) <= Decimal("0.005") * len(a) + 2 * CENT,
              f"{fmt(s)} vs {fmt(b110)}", [("line", "BT-131"), ("line", "BT-152"), ("doc", "BT-110")])

    for c in checks if annotate else []:
        for key in c["bts"]:
            p = v.p.get(key)
            if p is None:
                continue
            p.reasons.append(("✓ ověřeno: " if c["ok"] else "✗ nesedí: ") + f"{c['rule']} ({c['detail']})")
            p.confidence = 1 - (1 - p.confidence) * 0.5 if c["ok"] else p.confidence * 0.7
    return checks


def complete(props, groups, ev: Evidence, fields, make) -> tuple[list, dict, list[dict]]:
    """Terms the format lacks but arithmetic can supply. Returns (new proposals, `computed` spec, checks).

    make(bt, level, field, conf, reasons, rule) builds a Proposal (keeps this module free of the dataclass)."""
    have = {(p.level, p.bt): p for p in props}
    v = _Vals(props, groups)
    new, computed, checks = [], {}, []
    a = v.vec("line", "BT-131")

    # line VAT rate from the line VAT amount
    if "BG-25" in groups and ("line", "BT-152") not in have and ev.line_tax and ("line", "BT-131") in have:
        f = fields[ev.line_tax]
        gp = groups["BG-25"]["path"]
        path = "@" if f.path == gp else "@ > " + " > ".join(f.path[len(gp):])
        conf = have[("line", "BT-131")].confidence * 0.9
        have[("line", "BT-152")] = p = make("BT-152", "line", f, conf, ["dopočteno: " + ev.line_tax_text],
                                            {"derive": "rate_from_tax_at", "args": {"path": path, "value": f.name}})
        new.append(p)
        if ("line", "BT-151") not in have:
            new.append(make("BT-151", "line", None, conf * 0.85,
                            ["odvozeno z dopočtené sazby (kladná sazba = S, 0 % nejednoznačné)"],
                            {"derive": "vat_category_from_ctx"}))
            have[("line", "BT-151")] = new[-1]

    # VAT breakdown without a tax amount field: tax = base x rate
    if "BG-23" in groups and ("vat", "BT-117") not in have and ("vat", "BT-116") in have and ("vat", "BT-119") in have:
        conf = min(have[("vat", "BT-116")].confidence, have[("vat", "BT-119")].confidence) * 0.9
        new.append(make("BT-117", "vat", None, conf, ["dopočteno: daň = základ × sazba (pole s daní skupiny nenalezeno)"],
                        {"derive": "tax_from_base_rate"}))
        have[("vat", "BT-117")] = new[-1]

    # VAT breakdown from the lines: one group per category + rate
    vat_computed = False
    if "BG-23" not in groups and ("line", "BT-131") in have and (
            ("line", "BT-152") in have or ("line", "BT-151") in have):
        conf = min(have[("line", "BT-131")].confidence, (have.get(("line", "BT-152")) or have[("line", "BT-151")]).confidence)
        why = "dopočteno z řádků: rekapitulace DPH ve formátu není – Σ částek řádků podle kategorie a sazby DPH"
        computed["BG-23"] = {"from": "BG-25",
                             "note": "ODHAD: rekapitulace DPH dopočtená z řádků (formát ji nenese)."}
        for bt, extra in (("BT-116", "základ = Σ BT-131"), ("BT-117", "daň = základ × sazba, zaokrouhleno na 2 místa"),
                          ("BT-118", "kategorie z řádků (BT-151)"), ("BT-119", "sazba z řádků (BT-152)")):
            new.append(make(bt, "vat", None, conf * 0.9, [why, extra], {"computed": None}))
        vat_computed = True
        rates = v.vec("line", "BT-152")
        if rates or ev.line_tax:
            tax = Decimal(0)
            tv = per_instance(fields[ev.line_tax], len(groups["BG-25"]["path"])) if ev.line_tax and not rates else {}
            by: dict[Decimal, Decimal] = {}
            for i, amt in a.items():
                r = rates.get(i)
                if r is None and i in tv and amt:
                    r = snap_rate(tv[i] / amt * HUNDRED)
                if r is not None:
                    by[r] = by.get(r, Decimal(0)) + amt
            tax = sum((r2(b * r / HUNDRED) for r, b in by.items()), Decimal(0))
            b110 = v.doc("BT-110")
            if by and b110 is not None:
                ok = close(tax, b110, len(by) + len(a))
                checks.append({"rule": "Σ DPH dopočtené z řádků = BT-110", "ok": ok,
                               "detail": f"{fmt(tax)} vs {fmt(b110)} ({len(by)} sazb{'a' if len(by) == 1 else 'y'})",
                               "bts": [("doc", "BT-110")]})
                for p in new[-4:]:
                    p.reasons.append(("✓ ověřeno: " if ok else "✗ nesedí: ") + f"Σ DPH z řádků {fmt(tax)} vs BT-110 {fmt(b110)}")
                    p.confidence = 1 - (1 - p.confidence) * 0.5 if ok else p.confidence * 0.7

    def comp(bt, spec, reasons, conf):
        computed[bt] = spec
        have[("doc", bt)] = p = make(bt, "doc", None, conf, reasons, {"computed": spec})
        new.append(p)

    def conf_of(*keys):
        cs = [have[k].confidence for k in keys if k in have]
        return min(cs) * 0.95 if cs else 0.6

    has_vat = "BG-23" in groups or vat_computed
    if ("doc", "BT-110") not in have and has_vat:
        vt = v.vec("vat", "BT-117")
        txt = (f" ({fmt(sum(vt.values(), Decimal(0)))})" if vt else "")
        comp("BT-110", {"sum": "BT-117", "over": "BG-23", "note": "ODHAD: DPH celkem = Σ daní rekapitulace DPH."},
             [f"dopočteno: Σ daní rekapitulace DPH (BT-117){txt} – formát celkovou DPH nenese"],
             conf_of(("vat", "BT-117"), ("vat", "BT-116")))
    if ("doc", "BT-106") not in have and ("line", "BT-131") in have:
        comp("BT-106", {"sum": "BT-131", "over": "BG-25", "note": "ODHAD: součet řádků = Σ BT-131."},
             [f"dopočteno: Σ částek řádků (BT-131){' = ' + fmt(sum(a.values(), Decimal(0))) if a else ''}"],
             conf_of(("line", "BT-131")))
    if ("doc", "BT-109") not in have:
        if ("doc", "BT-112") in have and ("doc", "BT-110") in have:
            comp("BT-109", {"sum": ["BT-112", "-BT-110"], "note": "ODHAD: celkem bez DPH = celkem s DPH − DPH."},
                 ["dopočteno: BT-112 − BT-110"], conf_of(("doc", "BT-112"), ("doc", "BT-110")))
        elif ("doc", "BT-106") in have:
            comp("BT-109", {"sum": ["BT-106"], "note": "ODHAD: bez slev a poplatků dokladu = součet řádků."},
                 ["dopočteno: = BT-106 (ve formátu nejsou slevy ani poplatky dokladu)"], conf_of(("doc", "BT-106")) * 0.9)
    if ("doc", "BT-112") not in have and ("doc", "BT-109") in have and ("doc", "BT-110") in have:
        comp("BT-112", {"sum": ["BT-109", "BT-110"], "note": "ODHAD: celkem s DPH = BT-109 + BT-110."},
             ["dopočteno: BT-109 + BT-110"], conf_of(("doc", "BT-109"), ("doc", "BT-110")))
    if ("doc", "BT-115") not in have and ("doc", "BT-112") in have:
        comp("BT-115", {"sum": ["BT-112"], "note": "ODHAD: k úhradě = celkem s DPH (bez zálohy)."},
             ["dopočteno: = BT-112 (ve formátu není záloha ani částka k úhradě)"], conf_of(("doc", "BT-112")) * 0.9)
    return new, computed, checks
