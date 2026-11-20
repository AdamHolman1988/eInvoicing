"""Gap analysis: semantic model (what the message carries) vs. a requirement profile."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from ..semantic.catalog import catalog, codelists
from ..semantic.model import Context, Semantic, Value
from .loader import Profile


@dataclass
class Finding:
    severity: str  # error | warning | info
    code: str
    message: str
    bt: str | None = None
    contexts: list[str] = field(default_factory=list)
    line: int | None = None
    segment: str | None = None
    hint: str | None = None
    profiles: list[str] = field(default_factory=list)
    name_sk: str | None = None

    def key(self):
        return (self.severity, self.code, self.bt, self.message, self.hint)


SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VAT_PREFIX_RE = re.compile(r"^[A-Z]{2}[A-Z0-9+*.]{2,}$")
VAT_IDS = {"BT-31", "BT-48", "BT-63"}
UNIT_PRICES = {"BT-146", "BT-147", "BT-148"}
PLACEHOLDER_RE = re.compile(r"^(X{3,}|Country|City|PostalCode)$", re.I)
# Retail profiles (Billa …) demand a GTIN for goods; a service line has none -> warning only.
SERVICE_SOFT = {"BT-157"}
# Typical CZ/SK service wording; no English "service" – it is too common in company names ("XY Service s.r.o.").
SERVICE_TEXT_RE = re.compile(r"služb|sluzb|doprav|přeprav|preprav|doručen|dorucen|nájem|nájom|najem|najom|"
                             r"provize|provízi|provizi|poplat", re.I)


def service_reason(ctx: Context) -> str | None:
    """Why an invoice line counts as a service, or None. The format's item type wins over the item name."""
    if ctx.bg != "BG-25":
        return None
    t = ctx.aux.get("item_type") or item_properties(ctx).get("item_type")
    if t is not None:
        return f"typ položky {t.value}" if t.value.strip().upper() == "S" else None
    name = ctx.values.get("BT-153")
    if name and SERVICE_TEXT_RE.search(name[0].value):
        return "podle názvu položky"
    return None


def item_properties(ctx: Context) -> dict[str, Value]:
    """BT-160 name -> BT-161 value of one invoice line (pairs read in document order)."""
    names, vals = ctx.values.get("BT-160", []), ctx.values.get("BT-161", [])
    return {n.value.strip(): v for n, v in zip(names, vals)}


NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def check_item_properties(sem: Semantic, profile: Profile) -> list[Finding]:
    """Profile vocabulary of Additional Item Property names (GS1 SK FMCG): unknown names, wrong value types."""
    vocab = profile.item_properties
    out: list[Finding] = []
    if not vocab:
        return out
    for ctx in sem.groups.get("BG-25", []):
        for name, v in item_properties(ctx).items():
            loc = dict(bt="BT-160", contexts=[ctx.label], line=v.line, segment=v.segment, profiles=[profile.name])
            spec = vocab.get(name)
            if spec is None:
                close = [k for k in vocab if k.lower() == name.lower().replace(" ", "_").replace("-", "_")]
                out.append(Finding("warning", "PROP-UNKNOWN",
                                   f"Additional Item Property '{name}' není ve slovníku názvů (GS1 SK FMCG).",
                                   hint=(f"Správný název je '{close[0]}'." if close else
                                         "Odběratel ji nemusí umět zpracovat – použijte název ze slovníku nebo ji dohodněte."),
                                   **loc))
                continue
            typ, val = spec.get("type"), v.value.strip()
            bad = (typ == "num" and not NUM_RE.match(val)) or (typ == "date" and not DATE_RE.match(val))
            if bad:
                want = "číslo (desetinná tečka)" if typ == "num" else "datum YYYY-MM-DD"
                out.append(Finding("warning", "PROP-TYPE",
                                   f"Additional Item Property '{name}' = '{val}': očekáváno {want}.", **loc))
            if name == "item_type" and val.upper() not in ("Z", "O", "S"):
                out.append(Finding("warning", "PROP-VALUE",
                                   f"Additional Item Property item_type = '{val}': povolené Z (zboží), O (obaly), S (služba).",
                                   **loc))
    return out


def gs1_check_digit_ok(code: str) -> bool:
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits[:-1])))
    return (10 - total % 10) % 10 == digits[-1]


def _term_name(bt: str) -> str:
    t = catalog().get(bt)
    return t.name if t else bt


def _present(ctx: Context, gid: str) -> bool:
    """A group (or parent BT) is present when any term below it carries a non-constant value."""
    if gid.startswith("BT") and any(v.how != "const" for v in ctx.values.get(gid, [])):
        return True
    for d in catalog().descendants(gid):
        if any(v.how != "const" for v in ctx.values.get(d, [])):
            return True
    return False


def _applicable(bt: str, ctx: Context, sem: Semantic, required: set[str] = frozenset()) -> bool:
    """Required only if every optional ancestor group (below the repeating group) is present.
    A group the profile itself makes mandatory (e.g. XRechnung BG-6 Seller contact) counts as present."""
    cat = catalog()
    stop = sem.repeating.get(bt)
    for anc in cat.ancestors(bt):
        if anc == stop:
            break
        t = cat.get(anc)
        if anc in required:
            continue
        if t and (t.min == 0 or anc.startswith("BT")) and not _present(ctx, anc):
            return False
    return True


def _where(sem: Semantic, bt: str) -> str | None:
    rules = [r for r in sem.rules.get(bt, []) if "path" in r]
    if not rules:
        return None
    parts = []
    for r in rules[:2]:
        pos = r.get("value") or "+".join(r.get("join", [])[:1])
        pos_txt = "" if pos == "text" else f" (prvek {pos})"
        parts.append(f"{r['path']}{pos_txt}{' – ' + r['var'] if r.get('var') else ''}")
    return "Očekáváno v: " + " nebo ".join(parts)


def _generic_note(note: str | None) -> str | None:
    """Drop concrete numbers from a per-line note so identical findings merge."""
    return re.sub(r"\d+ řádků", "řádků", note) if note else note


def check_values(sem: Semantic) -> list[Finding]:
    cat, cls = catalog(), codelists()
    out: list[Finding] = []
    for ctx in sem.contexts():
        for bt, vals in ctx.values.items():
            term = cat.get(bt)
            for v in vals:
                out.extend(_check_value(bt, term, v, ctx, cls))
    from ..semantic.doctype import check as doctype_check
    out.extend(doctype_check(sem, Finding))
    from ..semantic.arith import check as arith_check
    out.extend(arith_check(sem, Finding))
    return out


def _check_value(bt, term, v: Value, ctx: Context, cls) -> list[Finding]:
    res = []
    if v.how == "const" or term is None:
        return res
    name = term.name
    loc = dict(bt=bt, contexts=[ctx.label], line=v.line, segment=v.segment)
    if PLACEHOLDER_RE.match(v.value):
        res.append(Finding("info", "VAL-PLACEHOLDER",
                           f"{bt} {name}: '{v.value}' vypadá jako anonymizovaná/testovací hodnota – nekontrolováno.", **loc))
        return res
    if bt == "BT-3" and v.value in cls.get("UNCL1001-cn", {}).get("codes", {}):
        res.append(Finding("info", "DOC-CREDITNOTE",
                           f"BT-3 '{v.value}' = dobropis → v Peppol se posílá jako UBL CreditNote (číselník UNCL1001-cn).", **loc))
        return res
    if term.codelist and term.codelist in cls:
        cl = cls[term.codelist]["codes"]
        if v.value not in cl:
            hint = None
            if bt in ("BT-118", "BT-151", "BT-95", "BT-102") and v.value == "AA":
                hint = "AA (snížená sazba) není v EN 16931 povolená – pro sníženou sazbu použijte S."
            res.append(Finding("error", "VAL-CODELIST",
                               f"{bt} {name}: hodnota '{v.value}' není v číselníku {term.codelist}.", hint=hint, **loc))
    if term.datatype == "Date" and not DATE_RE.match(v.value):
        res.append(Finding("error", "VAL-DATE", f"{bt} {name}: '{v.value}' není platné datum.", **loc))
    if term.datatype in ("Amount", "Quantity", "Percentage") or (term.datatype is None and bt in ("BT-146", "BT-148")):
        try:
            d = Decimal(v.value)
            # BR-DEC rules limit amounts to 2 decimals; unit prices (BT-146/147/148) may have more
            if term.datatype == "Amount" and bt not in UNIT_PRICES and d.as_tuple().exponent < -2:
                res.append(Finding("warning", "VAL-DECIMALS",
                                   f"{bt} {name}: '{v.value}' má více než 2 desetinná místa (Peppol dovoluje max. 2).", **loc))
        except InvalidOperation:
            res.append(Finding("error", "VAL-NUMBER", f"{bt} {name}: '{v.value}' není číslo.", **loc))
    if bt in VAT_IDS and not VAT_PREFIX_RE.match(v.value.replace(" ", "")):
        res.append(Finding("error", "VAL-VATID",
                           f"{bt} {name}: '{v.value}' nezačíná kódem země (BR-CO-09, např. CZ12345678 / SK2020123456).", **loc))
    if v.scheme in ("0088", "0160") and v.how == "explicit" and not gs1_check_digit_ok(v.value):
        what = "GLN" if v.scheme == "0088" else "GTIN"
        res.append(Finding("warning", "VAL-CHECKDIGIT", f"{bt} {name}: '{v.value}' není platný {what} (kontrolní číslice).", **loc))
    if v.how == "mapped":
        res.append(Finding("info", "MAP-CONVERTED", f"{bt} {name}: '{v.raw}' → '{v.value}'. {v.note or ''}".strip(), **loc))
    elif v.note and v.how == "explicit":
        res.append(Finding("info", "MAP-NOTE", f"{bt} {name}: {v.note}", **loc))
    return res


def check_profile(sem: Semantic, profile: Profile) -> list[Finding]:
    cat = catalog()
    out: list[Finding] = []
    required_groups = {k for k, r in profile.requirements.items() if r.level == "required" and k.startswith("BG")}
    for bt, req in profile.requirements.items():
        if req.level == "optional":
            continue
        term = cat.get(bt)
        if term is None:
            continue  # e.g. SK-specific sub-ids (BT-34-1) not in the UBL binding – reported by schematron later
        if term.kind == "BG":
            insts = sem.groups.get(bt)
            if req.level != "required" or not _applicable(bt, sem.document, sem, required_groups - {bt}):
                continue
            if insts is not None and not insts:
                out.append(Finding("error", "GAP-MISSING", f"Chybí skupina {bt} {term.name} (žádný výskyt).",
                                   bt=bt, contexts=["doklad"], profiles=req.sources, hint=" | ".join(req.notes) or None))
            elif insts is None and term.min == 0 and not _present(sem.document, bt):
                # optional in EN 16931, mandatory in this profile (XRechnung BG-6, BG-16)
                out.append(Finding("error", "GAP-MISSING", f"Chybí skupina {bt} {term.name}.",
                                   bt=bt, contexts=["doklad"], profiles=req.sources, hint=" | ".join(req.notes) or None))
            continue
        bg = sem.repeating.get(bt)
        ctxs = sem.groups.get(bg, []) if bg else [sem.document]
        for ctx in ctxs:
            forced = sem.doc_kind in req.when
            if not forced and not _applicable(bt, ctx, sem, required_groups):
                continue
            vals = ctx.values.get(bt, [])
            name = term.name
            if not vals and req.unless and any(sem.document.has(u) or ctx.has(u) for u in req.unless):
                continue  # alternative term present (e.g. BT-13 instead of BT-10)
            if sem.doc_kind in req.when:
                if not vals:
                    kind = "dobropis" if sem.doc_kind == "CreditNote" else sem.doc_kind
                    hint = " | ".join([*req.notes, _where(sem, bt) or ""]).strip(" |")
                    out.append(Finding("error", "GAP-MISSING", f"{bt} {name}: povinné pro {kind}, ve zprávě chybí.",
                                       bt=bt, contexts=[ctx.label], profiles=req.sources, hint=hint))
                continue
            if req.level == "conditional":
                if not vals:
                    out.append(Finding("info", "GAP-CONDITIONAL", f"{bt} {name}: podmíněně povinné, ve zprávě není.",
                                       bt=bt, contexts=[ctx.label], profiles=req.sources,
                                       hint=" | ".join(req.notes) or _where(sem, bt)))
                continue
            if not vals:
                if bt not in sem.mapped_terms:
                    out.append(Finding("error", "GAP-NOT-IN-FORMAT",
                                       f"{bt} {name}: povinné, ale zdrojový formát (mapování {sem.mapping_id}) tento údaj nepřenáší.",
                                       bt=bt, contexts=[ctx.label], profiles=req.sources,
                                       hint=" | ".join(req.notes) or None))
                elif bt in SERVICE_SOFT and (why := service_reason(ctx)):
                    out.append(Finding("warning", "GAP-SERVICE",
                                       f"{bt} {name}: chybí u řádku se službou ({why}) – profil vyžaduje "
                                       f"u zboží, u služby jen varování.",
                                       bt=bt, contexts=[ctx.label], profiles=req.sources,
                                       hint="Je-li to zboží, údaj doplňte; u služby ověřte s odběratelem, "
                                            "že řádek bez něj přijme."))
                else:
                    out.append(Finding("error", "GAP-MISSING", f"{bt} {name}: povinné, ve zprávě chybí.",
                                       bt=bt, contexts=[ctx.label], profiles=req.sources, hint=_where(sem, bt)))
                continue
            v = vals[0]
            if v.how == "derived":
                # per-line values differ – keep the message value-free so that all lines merge into one finding
                what = f"konverze odvodí '{v.value}'" if ctx.bg is None else "konverze hodnotu odvodí"
                out.append(Finding("warning", "GAP-DERIVED",
                                   f"{bt} {name}: není ve zprávě explicitně, {what}.",
                                   bt=bt, contexts=[ctx.label], line=v.line, segment=v.segment,
                                   profiles=req.sources, hint=_generic_note(v.note) if ctx.bg else v.note))
            elif v.how == "ambiguous":
                out.append(Finding("warning", "GAP-AMBIGUOUS",
                                   f"{bt} {name}: nelze jednoznačně odvodit (předpoklad '{v.value}').",
                                   bt=bt, contexts=[ctx.label], line=v.line, segment=v.segment,
                                   profiles=req.sources, hint=v.note))
            elif v.how == "const":
                out.append(Finding("info", "GAP-CONST", f"{bt} {name}: doplní konverze ('{v.value}').",
                                   bt=bt, contexts=[ctx.label], profiles=req.sources))
    for f in out:
        r = profile.requirements.get(f.bt)
        f.name_sk = r.name_sk if r else None
        f.profiles = [profile.name]
    return out + check_allowed_values(sem, profile) + check_item_properties(sem, profile)


def check_allowed_values(sem: Semantic, profile: Profile) -> list[Finding]:
    """Profile-fixed values (Lidl SK: buyer VAT id, delivery-location GLNs …)."""
    out = []
    for bt, req in profile.requirements.items():
        if not req.values:
            continue
        bg = sem.repeating.get(bt)
        for ctx in (sem.groups.get(bg, []) if bg else [sem.document]):
            for v in ctx.values.get(bt, []):
                if v.how == "const" or v.value.replace(" ", "") in {x.replace(" ", "") for x in req.values}:
                    continue
                out.append(Finding("warning", "PROF-VALUE",
                                   f"{bt} {_term_name(bt)}: '{v.value}' není mezi hodnotami, které odběratel očekává "
                                   f"({', '.join(req.values)}).",
                                   bt=bt, contexts=[ctx.label], line=v.line, segment=v.segment,
                                   profiles=[profile.name], hint=req.values_note, name_sk=req.name_sk))
    return out


def combine(per_profile: list[list[Finding]]) -> list[Finding]:
    """One gap list across all selected profiles; each finding lists the profiles that raise it."""
    merged = merge([f for fs in per_profile for f in fs])
    hard = {f.bt for f in merged if f.severity == "error" and f.code.startswith("GAP-")}
    return [f for f in merged if not (f.code == "GAP-CONDITIONAL" and f.bt in hard)]


def _location(f: Finding) -> str:
    return " ".join(x for x in (f.segment or "", f"(ř. {f.line})" if f.line else "") if x)


def merge(findings: list[Finding]) -> list[Finding]:
    """Collapse identical findings that differ only by context (e.g. the same gap on every line)."""
    merged: dict[tuple, Finding] = {}
    for f in findings:
        k = f.key()
        if k in merged:
            m = merged[k]
            if not f.contexts and (f.line, f.segment) != (m.line, m.segment) and (f.line or f.segment):
                # same rule failing at another place (e.g. R040 on two lines) – keep every location
                if not m.contexts and (m.line or m.segment):
                    m.contexts.append(_location(m))
                if _location(f) not in m.contexts:
                    m.contexts.append(_location(f))
            for c in f.contexts:
                if c not in m.contexts:
                    m.contexts.append(c)
            for p in f.profiles:
                if p not in m.profiles:
                    m.profiles.append(p)
        else:
            merged[k] = Finding(**{**f.__dict__, "contexts": list(f.contexts), "profiles": list(f.profiles)})
    cat = catalog()
    return sorted(merged.values(), key=lambda f: (SEVERITY_ORDER[f.severity], cat.sort_key(f.bt or ""), f.code))
