"""Apply a mapping (data/mappings/*.yaml) to an EDIFACT group tree -> Semantic model."""
from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache

import yaml

from ..edifact.parser import Message
from ..edifact.structure import GroupInstance
from ..resources import data_path
from .catalog import catalog, codelists
from .derive import DERIVERS
from .model import Context, Semantic, Value
from .selector import node_segment, select


@lru_cache(maxsize=None)
def load_mapping(name: str) -> dict:
    return yaml.safe_load(data_path("mappings", f"{name}.yaml").read_text(encoding="utf-8"))


def _date(value: str, fmt: str | None) -> tuple[str, str | None]:
    fmt = fmt or "102"
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":  # already ISO (generic XML)
        try:
            return dt.date.fromisoformat(value[:10]).isoformat(), None
        except ValueError:
            pass
    try:
        if fmt == "102":
            return dt.datetime.strptime(value[:8], "%Y%m%d").date().isoformat(), None
        if fmt in ("203", "204"):
            return dt.datetime.strptime(value[:8], "%Y%m%d").date().isoformat(), None
        if fmt == "101":
            return dt.datetime.strptime(value[:6], "%y%m%d").date().isoformat(), None
        if fmt == "dmy":  # 1.11.2026 / 01. 11. 2026 (Czech / Slovak / German)
            return dt.datetime.strptime(value.replace(" ", ""), "%d.%m.%Y").date().isoformat(), None
    except ValueError:
        return value, f"Neplatné datum '{value}' (formát {fmt})."
    return value, f"Formát data {fmt} není podporován pro převod."


def _split_scopes(root: GroupInstance):
    header, summary, lines = GroupInstance("SCOPE"), GroupInstance("SCOPE"), []
    after_uns = False
    for ch in root.children:
        seg = node_segment(ch)
        if seg is not None and seg.tag == "UNS":
            after_uns = True
            continue
        if seg is not None and seg.tag in ("UNH", "UNT"):
            continue
        if after_uns:
            summary.children.append(ch)
        elif isinstance(ch, GroupInstance) and seg is not None and seg.tag == "LIN":
            lines.append(ch)
            header.children.append(ch)  # still addressable for 'each: LIN'
        else:
            header.children.append(ch)
    return header, summary, lines


def _fill(tpl: str, seg) -> str:
    """Group label template with resolved positions: 'DPH {3.1} %' -> 'DPH 23 %'."""
    def val(m):
        e, _, c = m.group(1).partition(".")
        return (seg.get(int(e), int(c or 1)) or "?").strip()
    return re.sub(r"\{(\d+(?:\.\d+)?)\}", val, tpl)


def _label(bg: str, seg, n: int, tpl: str | None = None) -> str:
    if tpl:
        return _fill(tpl, seg).replace("{n}", str(n))
    if bg == "BG-25":
        return f"řádek {seg.get(1) or n}"
    if bg == "BG-23" and seg.tag == "VAT":
        return f"DPH skupina {seg.get(1)} – {seg.get(3) or 0} %"
    if bg == "BG-23":
        rate = seg.get(5, 4) or ("0" if seg.get(5, 1) == "0" else "?")
        return f"DPH {rate} %" + (f" {seg.get(6, 1)}" if seg.get(6, 1) else "")
    if bg == "BG-20":
        return f"sleva dokladu #{n}"
    if bg == "BG-21":
        return f"přirážka dokladu #{n}"
    return f"{bg} #{n}"


def _apply_rules(bt, rules, ctx_nodes, header_nodes, ctx: Context, version: str):
    for rule in rules:
        if rule.get("versions") and version not in rule["versions"]:
            continue
        if "const" in rule:
            ctx.add(Value(bt, rule["const"], how="const", note=rule.get("note"), rule="const"))
            return
        if rule.get("derive") == "position":  # line number = position of the line in the message
            if ctx.index is not None:
                ctx.add(Value(bt, str(ctx.index), how="derived", note=rule.get("note") or "pořadí řádku ve zprávě",
                              rule="position"))
                return
            continue
        if "derive" in rule:
            fn = DERIVERS[rule["derive"]]
            res = fn(ctx_nodes, rule.get("args", {}), header_nodes, ctx.values)
            if res and res.get("value"):
                seg = res.get("seg")
                note = "; ".join(x for x in (rule.get("note"), res.get("note")) if x)
                ctx.add(Value(bt, res["value"], how=res.get("how", "derived"), line=seg.line if seg else None,
                              segment=seg.raw if seg else None, scheme=res.get("scheme"), note=note or None,
                              rule=rule["derive"]))
                return
            continue
        nodes = select(ctx_nodes, rule["path"])
        found = False
        for node in nodes:
            seg = node_segment(node)
            if "join" in rule:
                parts = []
                for pos in rule["join"]:
                    e, _, c = pos.partition(".")
                    v = seg.get(int(e), int(c or 1))
                    if v:
                        parts.append(v.strip())
                value = " ".join(parts) or None
            else:
                e, _, c = rule["value"].partition(".")
                value = seg.get(int(e), int(c or 1))
                value = value.strip() if value else None
            if not value:
                continue
            how, raw, note = "explicit", None, rule.get("note") if not rule.get("map") else None
            if "format_at" in rule or "date" in rule:
                if "format_at" in rule:
                    e, _, c = rule["format_at"].partition(".")
                    fmt = seg.get(int(e), int(c or 1)) or rule.get("date")
                else:
                    fmt = rule["date"]
                value, err = _date(value, fmt)
                if err:
                    note = err
            if rule.get("decimal") == ",":  # 1 234,50 -> 1234.50
                value = value.replace(" ", "").replace("\u00a0", "").replace(".", "").replace(",", ".")
            if rule.get("map") and value in rule["map"]:
                raw, value, how = value, rule["map"][value], "mapped"
                note = rule.get("note")
            ctx.add(Value(bt, value, how=how, line=seg.line, segment=seg.raw, raw=raw,
                          scheme=rule.get("scheme"), note=note, rule=rule["path"]))
            found = True
        if found:
            return


def _first(ctx: Context, bt: str) -> str | None:
    vs = ctx.values.get(bt)
    return vs[0].value if vs else None


def _dec(v: str | None) -> Decimal | None:
    try:
        return Decimal(v) if v else None
    except InvalidOperation:
        return None


def _money(d: Decimal) -> str:
    return format(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _compute(key: str, spec: dict, document: Context, groups: dict, repeating: dict) -> set[str]:
    """Mapping section `computed:` – values the format does not carry, computed after extraction (never overriding):
      BG-23: {from: BG-25}             VAT breakdown from the lines (sum of BT-131 per category BT-151 + rate BT-152)
      BT-x:  {sum: BT-y, over: BG-n}   sum of a term over the instances of a group
      BT-x:  {sum: [BT-a, -BT-b]}      signed sum of document terms
    Returns the terms it supplies (they count as 'carried by the format')."""
    note = spec.get("note")
    if key == "BG-23":
        if groups.get("BG-23"):
            return set()
        buckets: dict[tuple, list] = {}
        for ctx in groups.get(spec.get("from", "BG-25"), []):
            amt, rate, cat = _dec(_first(ctx, "BT-131")), _dec(_first(ctx, "BT-152")), _first(ctx, "BT-151")
            if amt is None or (rate is None and cat is None):
                continue
            k = (cat or ("S" if rate and rate > 0 else None), rate)
            b = buckets.setdefault(k, [Decimal(0), 0])
            b[0] += amt
            b[1] += 1
        out = []
        for n, ((cat, rate), (base, cnt)) in enumerate(buckets.items(), 1):
            shown = _money(rate) if rate is not None else "?"
            ctx = Context("BG-23", f"DPH {cat or '?'} {shown} % (dopočteno z řádků)", None, index=n)
            why = f"{note + ' ' if note else ''}Součet {cnt} řádků."
            ctx.add(Value("BT-116", _money(base), how="derived", note=why, rule="computed"))
            if rate is not None:
                ctx.add(Value("BT-119", shown, how="derived", note=why, rule="computed"))
                ctx.add(Value("BT-117", _money(base * rate / 100), how="derived", note="Daň = základ × sazba.",
                              rule="computed"))
            if cat:
                ctx.add(Value("BT-118", cat, how="derived", note=why, rule="computed"))
            out.append(ctx)
        groups["BG-23"] = out
        for bt in ("BT-116", "BT-117", "BT-118", "BT-119"):
            repeating.setdefault(bt, "BG-23")
        return {"BT-116", "BT-117", "BT-118", "BT-119"}
    if document.has(key):
        return set()
    total, parts = Decimal(0), []
    if isinstance(spec.get("sum"), str):
        insts = groups.get(spec["over"], [])
        if not insts:
            return set()
        for ctx in insts:
            v = _dec(_first(ctx, spec["sum"]))
            if v is None:
                return set()  # an instance without the value – the sum would be wrong
            total += v
        how = f"součet {spec['sum']} ({len(insts)}× {spec['over']})"
    else:
        for item in spec.get("sum", []):
            sign, bt = (-1, item[1:]) if item.startswith("-") else (1, item)
            v = _dec(_first(document, bt))
            if v is None:
                return set()
            total += sign * v
            parts.append(("− " if sign < 0 else "+ ") + bt)
        how = " ".join(parts).removeprefix("+ ")
    document.add(Value(key, _money(total), how="derived", note=f"{note + ' ' if note else ''}Dopočteno: {how}.",
                       rule="computed"))
    return {key}


def extract(msg: Message, root: GroupInstance, mapping_name: str, mapping: dict | None = None,
            source_format: str | None = None) -> Semantic:
    mp = mapping if mapping is not None else load_mapping(mapping_name)
    cat = catalog()
    header, summary, lines = _split_scopes(root)
    scopes = {"header": header, "summary": summary}
    groups_cfg = mp.get("groups", {})

    # which repeating BG does each BT live in?
    repeating: dict[str, str] = {}
    for bt in mp["terms"]:
        for anc in cat.ancestors(bt):
            if anc in groups_cfg:
                repeating[bt] = anc
                break

    document = Context(None, "doklad", None)
    groups: dict[str, list[Context]] = {}
    group_nodes: dict[str, list] = {}
    for bg, cfg in groups_cfg.items():
        groups[bg], group_nodes[bg] = [], []
        if cfg.get("parent"):  # nested repeating group, e.g. line charges inside each invoice line
            for pnode, pctx in zip(group_nodes[cfg["parent"]], groups[cfg["parent"]]):
                for n, node in enumerate(select([pnode], "@ > " + cfg["each"]), 1):
                    seg = node_segment(node)
                    kind = {"BG-27": "sleva", "BG-28": "přirážka"}.get(bg, bg)
                    groups[bg].append(Context(bg, f"{pctx.label} – {kind} #{n}", seg.line, parent=pctx))
                    group_nodes[bg].append(node)
            continue
        base = [header] if cfg["scope"] in ("header", "line") else [scopes[cfg["scope"]]]
        insts = select(base, cfg["each"])
        for n, node in enumerate(insts, 1):
            seg = node_segment(node)
            groups[bg].append(Context(bg, _label(bg, seg, n, cfg.get("label")), seg.line, index=n))
        group_nodes[bg] = insts

    # explicit/const terms first, terms with derivation rules afterwards (they may use other values)
    late = {"BT-117", "BT-147"}  # derivations that read other (possibly derived) values

    def tier(bt, rules):  # category from an already derived rate (guess) comes before the tax amount
        return 2 if bt in late else 1 if any(r.get("derive") == "vat_category_from_ctx" for r in rules) else 0
    ordered = sorted(mp["terms"].items(), key=lambda kv: (tier(*kv), any("derive" in r for r in kv[1])))
    for bt, rules in ordered:
        bg = repeating.get(bt)
        if bg is None:
            scope_name = rules[0].get("scope", "header") if rules else "header"
            _apply_rules(bt, rules, [scopes[scope_name]], [header], document, msg.version)
        else:
            for node, ctx in zip(group_nodes[bg], groups[bg]):
                _apply_rules(bt, rules, [node], [header], ctx, msg.version)

    # helper facts outside EN 16931 (e.g. item_type: Z goods / O packaging / S service)
    for key, cfg in mp.get("aux", {}).items():
        bg = cfg.get("group")
        targets = zip(group_nodes[bg], groups[bg]) if bg else [(header, document)]
        for node, ctx in targets:
            tmp = Context(bg, ctx.label, ctx.line)
            _apply_rules(key, cfg["rules"], [node], [header], tmp, msg.version)
            if tmp.values.get(key):
                ctx.aux[key] = tmp.values[key][0]

    mapped = set(mp["terms"])
    for key, spec in (mp.get("computed") or {}).items():
        mapped |= _compute(key, spec, document, groups, repeating)

    notes = []
    for bg, cfg in groups_cfg.items():
        need = cfg.get("skip_if_missing")
        if not need:
            continue
        kept = []
        for ctx in groups[bg]:
            if any(ctx.has(bt) for bt in need):
                kept.append(ctx)
            else:
                notes.append({"line": ctx.line, "message": f"{bg} {ctx.label}: prázdná skupina (bez částky / sazby) – konverze ji vynechá."})
        groups[bg] = kept

    bt3 = document.values.get("BT-3")
    cn_codes = codelists().get("UNCL1001-cn", {}).get("codes", {})
    doc_kind = "CreditNote" if bt3 and bt3[0].value in cn_codes else "Invoice"

    return Semantic(
        source_format=source_format or f"EDIFACT {msg.type} {msg.version} ({msg.assoc})",
        mapping_id=mp["id"],
        document=document,
        groups=groups,
        mapped_terms=mapped,
        rules=mp["terms"],
        repeating=repeating,
        notes=notes,
        doc_kind=doc_kind,
    )
