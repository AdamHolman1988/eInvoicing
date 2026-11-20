"""ODHAD mapování neznámého formátu: z názvů polí, rolí nadřazených prvků a tvaru hodnot navrhne klientské mapování.

The result is an ordinary draft client mapping (same format as the mapping editor saves, base ``xml_generic``),
so extraction, checks, the editor and saving reuse the existing pipeline unchanged. Every proposed business term
carries a confidence (0–1) and human-readable reasons; nothing here is "learned" until a user confirms it.

Signals per source field (segment path + field name):
  * name       – normalised field name vs. the CZ/SK/EN/DE lexicon (data/guess/lexicon.yaml)
  * role       – seller / buyer / delivery from the field name or the nearest ancestor element
  * level      – document, invoice line (BG-25) or VAT breakdown (BG-23), from the detected repeating groups
  * shape      – what the values look like (date, amount, rate, IBAN, VAT id, GLN with check digit …)
  * arithmetic  – quantity x price = line amount, sums, net + VAT = total, base x rate = tax (guess/arith.py):
                  confirms / refutes the name-based candidates and computes what the format lacks (mapping `computed:`)
Assignment is greedy by confidence: one business term per level, one field per term.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from ..resources import data_path
from ..semantic.catalog import catalog
from . import arith
from .shapes import date_format, kinds

MIN_CONFIDENCE = 0.45
LEVEL_OF_GROUP = {"BG-25": "line", "BG-23": "vat"}
NORM_RE = re.compile(r"[^a-z0-9]+")
# shape expectations: kinds that must (strict) or should (soft) appear in the values
STRICT = {"BT-5": {"currency"}, "BT-40": {"country"}, "BT-55": {"country"}, "BT-80": {"country"}, "BT-159": {"country"},
          "BT-31": {"vatid"}, "BT-48": {"vatid"}, "BT-84": {"iban", "account"}, "BT-86": {"bic"},
          "BT-43": {"email"}, "BT-58": {"email"}, "BT-157": {"gtin", "int"}, "BT-29": {"gln", "int", "text"},
          "BT-46": {"gln", "int", "text"}, "BT-71": {"gln", "int", "text"}, "BT-38": {"zip"}, "BT-53": {"zip"},
          "BT-78": {"zip"}, "BT-42": {"phone", "int"}, "BT-57": {"phone", "int"}, "BT-30": {"int", "text"},
          "BT-47": {"int", "text"}, "BT-126": {"int", "text"}, "BT-119": {"percent"}, "BT-152": {"percent"}}
SOFT = {"BT-130": {"unit"}, "BT-3": {"typecode"}, "BT-151": {"vatcat"}, "BT-118": {"vatcat"}, "BT-29": {"gln"},
        "BT-46": {"gln"}, "BT-71": {"gln"}, "BT-30": {"ico"}, "BT-47": {"ico"}, "BT-119": {"rate"}, "BT-152": {"rate"},
        "BT-126": {"int"}, "BT-157": {"gtin"}}
TEXTUAL = {"BT-27", "BT-44", "BT-70", "BT-59", "BT-35", "BT-50", "BT-75", "BT-36", "BT-51", "BT-76", "BT-37", "BT-52",
           "BT-77", "BT-41", "BT-56", "BT-153", "BT-22", "BT-20"}
NOT_AMOUNT = {"BT-1", "BT-12", "BT-13", "BT-14", "BT-15", "BT-16", "BT-25", "BT-83"}
# shape alone (no name match) is enough for these, with the given confidence
SHAPE_ONLY = {"iban": ("BT-84", 0.75), "bic": ("BT-86", 0.6), "currency": ("BT-5", 0.6)}
ROLE_SHAPE_ONLY = {"vatid": ("vat", 0.7), "email": ("email", 0.55), "gln": ("gln", 0.55)}
ROLE_LABEL = {"seller": "dodavatel", "buyer": "odběratel", "delivery": "místo dodání", "payee": "příjemce platby"}
# common non-Rec20 units -> UN/ECE Rec 20
UNIT_MAP = {"KS": "H87", "PCS": "H87", "PCE": "H87", "ST": "H87", "STK": "H87", "PC": "H87", "KUS": "H87",
            "KG": "KGM", "G": "GRM", "T": "TNE", "L": "LTR", "ML": "MLT", "M": "MTR", "KM": "KMT", "M2": "MTK",
            "M3": "MTQ", "HOD": "HUR", "H": "HUR", "DEN": "DAY", "BAL": "XPK", "KAR": "XCT", "CAR": "XCT",
            "PAL": "XPX", "SET": "SET", "PAR": "PR", "BX": "XBX", "PK": "XPK"}
PERSON_WORDS = ("contact", "kontakt", "person", "osoba", "ansprechpartner", "referent")
GENERIC_NAMES = {"value", "id", "text", "code", "number", "nr", "content", "amount", "date", "name", "type", "valore",
                 "wert", "hodnota"}
LEVEL_LABEL = {"doc": "doklad", "line": "řádek faktury", "vat": "rekapitulace DPH"}


def norm(s: str) -> str:
    plain = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return NORM_RE.sub("", plain)


@lru_cache(maxsize=1)
def lexicon() -> dict:
    raw = yaml.safe_load(data_path("guess", "lexicon.yaml").read_text(encoding="utf-8"))
    lx = {"roles": {r: sorted({norm(w) for w in ws}, key=len, reverse=True) for r, ws in raw["roles"].items()},
          "groups": {g: {norm(w) for w in ws} for g, ws in raw["groups"].items()},
          "party": {k: {"bt": v["bt"], "words": {norm(w) for w in v["words"]}} for k, v in raw["party"].items()},
          "terms": {}}
    for level in ("document", "line", "vat"):
        lv = {"document": "doc"}.get(level, level)
        for bt, ws in raw[level].items():
            lx["terms"][(lv, bt)] = {norm(w) for w in ws}
    return lx


def name_score(name: str, words) -> tuple[float, str | None]:
    """1.0 whole name, 0.8 word at the start / end, 0.65 word inside (only words of 4+ characters)."""
    best, hit = 0.0, None
    for w in words:
        if not w:
            continue
        if name == w:
            return 1.0, w
        if len(w) >= 3 and (name.startswith(w) or name.endswith(w)) and best < 0.8:
            best, hit = 0.8, w
        elif len(w) >= 4 and w in name and best < 0.65:
            best, hit = 0.65, w
    return best, hit


@dataclass
class SourceField:
    path: tuple[str, ...]  # segment tags from the root
    name: str
    values: list[str] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)
    chains: list[tuple[int, ...]] = field(default_factory=list)  # ordinal of every ancestor element per value

    @property
    def key(self) -> str:
        """Normalised name used for matching; generic names ('Value', 'ID') take the parent element's name."""
        n = norm(self.name)
        return norm(self.path[-1]) + n if n in GENERIC_NAMES and self.path else n

    @property
    def label(self) -> str:
        return f"{' > '.join(self.path)} / {self.name}"

    def shape(self) -> dict[str, float]:
        vals = [v for v in self.values if v.strip()]
        if not vals:
            return {}
        counts: dict[str, int] = {}
        for v in vals:
            for k in kinds(v):
                counts[k] = counts.get(k, 0) + 1
        return {k: c / len(vals) for k, c in counts.items()}


@dataclass
class Proposal:
    bt: str
    name: str
    level: str  # doc | line | vat
    field: SourceField | None
    confidence: float
    reasons: list[str]
    rule: dict

    def as_dict(self) -> dict:
        src = self.field.label if self.field else ("(dopočteno)" if "computed" in self.rule or "derive" in self.rule
                                                   else None)
        return {"bt": self.bt, "name": self.name, "level": self.level, "source": src,
                "sample": (self.field.values[0] if self.field and self.field.values else None),
                "confidence": round(self.confidence, 2), "grade": grade(self.confidence), "reasons": self.reasons}


@dataclass
class Guess:
    root: str
    client: dict  # draft client mapping (base xml_generic)
    proposals: list[Proposal]
    groups: dict[str, dict]  # BG -> {path, count, reasons}
    unused: list[SourceField]
    checks: list[dict] = field(default_factory=list)  # arithmetic checks of the chosen fields (guess/arith.py)
    computed: dict = field(default_factory=dict)  # terms / groups computed from others (mapping section `computed`)
    facts: list[str] = field(default_factory=list)  # arithmetic relations found in the data

    @property
    def confidence(self) -> float:
        ps = [p.confidence for p in self.proposals]
        return sum(ps) / len(ps) if ps else 0.0


def grade(c: float) -> str:
    return "vysoká" if c >= 0.8 else "střední" if c >= 0.6 else "nízká"


# ---------------------------------------------------------------------------------------------------------------
def collect(msg) -> tuple[dict[tuple, int], dict[tuple, SourceField]]:
    """Segment paths with instance counts and every leaf field with all its values (generic XML message)."""
    counts: dict[tuple, int] = {}
    fields: dict[tuple, SourceField] = {}

    def walk(node, parents: tuple, chain: tuple):
        seg = node.trigger if hasattr(node, "trigger") else node
        if seg is None or seg.tag == "UNS":
            return
        path = parents + (seg.tag,)
        counts[path] = counts.get(path, 0) + 1
        chain = chain + (counts[path],)
        for i, name in enumerate(msg.fields.get(seg.tag, [])):
            v = seg.get(i + 1)
            f = fields.setdefault((path, name), SourceField(path, name))
            if v and v.strip():
                f.values.append(v.strip())
                f.lines.append(seg.line)
                f.chains.append(chain)
        if hasattr(node, "trigger"):
            for ch in node.children[1:]:
                walk(ch, path, chain)

    for ch in msg.root.children:
        walk(ch, (), ())
    return counts, {k: f for k, f in fields.items() if f.values}


def _numeric_fields(path, fields) -> int:
    return sum(1 for (p, _), f in fields.items() if p[:len(path)] == path and f.shape().get("num", 0) >= 0.8)


def detect_groups(counts, fields) -> dict[str, dict]:
    lx = lexicon()
    out: dict[str, dict] = {}
    scored = []
    for path, n in counts.items():
        if len(path) < 2:
            continue
        tag = norm(path[-1])
        reasons, s = [], 0.0
        sc, w = name_score(tag, lx["groups"]["BG-25"])
        if sc:
            s += 0.6 * sc
            reasons.append(f"název prvku '{path[-1]}' ≈ '{w}'")
        if n >= 2:
            s += 0.25
            reasons.append(f"opakuje se {n}×")
        nums = _numeric_fields(path, fields)
        if nums >= 2:
            s += 0.2
            reasons.append(f"{nums} číselná pole")
        if name_score(tag, lx["groups"]["BG-23"])[0] >= 0.8:
            s -= 0.5
        scored.append((s, n, -len(path), path, reasons))
    scored.sort(reverse=True)  # equal score and count: the containing (shallower) element wins
    if scored and scored[0][0] >= 0.6:
        s, n, _, path, reasons = scored[0]
        out["BG-25"] = {"path": path, "count": n, "reasons": reasons, "score": s}
    line = out.get("BG-25", {}).get("path")
    vat = []
    for path, n in counts.items():
        if len(path) < 2 or (line and (path[:len(line)] == line or line[:len(path)] == path)):
            continue
        tag = norm(path[-1])
        sc, w = name_score(tag, lx["groups"]["BG-23"])
        own = [f for (p, _), f in fields.items() if p == path]
        has_rate = any(f.shape().get("percent", 0) >= 0.99 for f in own)
        has_amount = sum(1 for f in own if f.shape().get("num", 0) >= 0.99) >= 2
        if sc and has_rate and has_amount:
            vat.append((sc + (0.2 if n >= 2 else 0), n, path, [f"název prvku '{path[-1]}' ≈ '{w}'",
                                                               f"{n}× sazba + částky"]))
    if vat:
        vat.sort(reverse=True)
        s, n, path, reasons = vat[0]
        out["BG-23"] = {"path": path, "count": n, "reasons": reasons, "score": s}
    return out


def _level(path, groups) -> tuple[str, tuple | None]:
    for bg, lvl in (("BG-25", "line"), ("BG-23", "vat")):
        g = groups.get(bg)
        if g and path[:len(g["path"])] == g["path"]:
            return lvl, g["path"]
    return "doc", None


def _role(f: SourceField) -> tuple[str | None, str, str | None]:
    """(role, field name without the role word, where the role came from)."""
    lx = lexicon()
    name = norm(f.name)  # the field's own name (not the parent-prefixed key)
    hits = [(len(w), role, w) for role, words in lx["roles"].items() for w in words
            if len(w) >= 4 and w in name and name != w]
    if hits:  # the longest word wins: 'prijemceplatby' (payee) over 'prijemce' (buyer)
        _, role, w = max(hits)
        return role, name.replace(w, "", 1), f"název pole '{f.name}'"
    for tag in reversed(f.path):
        t = norm(tag)
        hits = [(len(w), role) for role, words in lx["roles"].items() for w in words
                if t == w or (len(w) >= 5 and w in t)]
        if hits:
            return max(hits)[1], f.key, f"prvek '{tag}'"
    return None, f.key, None


def _shape_fit(bt: str, term, shape: dict[str, float]) -> tuple[float, str | None]:
    """(score 0..1, reason); 0 = the values contradict the term."""
    if not shape:
        return 0.0, None
    dtp = term.datatype if term else None
    if dtp == "Date":
        f = shape.get("date", 0)
        return (f, f"hodnoty mají tvar data ({f:.0%})") if f >= 0.8 else (0.0, None)
    if dtp in ("Amount", "Quantity", "Percentage") or bt in ("BT-119", "BT-152"):
        need = "percent" if (dtp == "Percentage" or bt in ("BT-119", "BT-152")) else "num"
        f = shape.get(need, 0)
        if f < 0.99:
            return 0.0, None
        bonus = 0.15 if need == "percent" and shape.get("rate", 0) >= 0.99 else 0.0
        return min(1.0, 0.85 + bonus), "hodnoty jsou " + ("sazby DPH" if bonus else "čísla")
    if bt in STRICT:
        f = max(shape.get(k, 0) for k in STRICT[bt])
        if f < 0.8:
            return 0.0, None
        soft = SOFT.get(bt)
        best = max((shape.get(k, 0) for k in soft), default=0) if soft else f
        return 0.75 + 0.25 * best, f"tvar hodnot odpovídá ({', '.join(sorted(k for k in STRICT[bt] if shape.get(k)))})"
    if bt in SOFT:
        f = max(shape.get(k, 0) for k in SOFT[bt])
        return 0.6 + 0.4 * f, (f"tvar hodnot odpovídá ({', '.join(SOFT[bt])})" if f else None)
    if bt in TEXTUAL:
        if shape.get("text", 0) >= 0.8:
            return 0.9, "textové hodnoty"
        if shape.get("date", 0) or shape.get("num", 0) >= 0.8:
            return 0.0, None
        return 0.6, None
    if bt in NOT_AMOUNT:
        # 20260815 is a valid YYYYMMDD but also a typical variable symbol / document number
        if (shape.get("date", 0) >= 0.8 and shape.get("int", 0) < 0.8) or (shape.get("num", 0) >= 0.8 and shape.get("int", 0) < 0.8):
            return 0.0, None
        return 0.8, None
    return 0.7, None


def _candidates(f: SourceField, level: str) -> list[tuple[float, str, list[str]]]:
    lx, cat = lexicon(), catalog()
    shape = f.shape()
    role, rest, role_src = _role(f)
    out = []
    name = f.key

    def add(bt, ns, hit, extra=None):
        term = cat.get(bt)
        if term is None:
            return
        sf, why = _shape_fit(bt, term, shape)
        if sf == 0.0:
            return
        conf = 0.65 * ns + 0.35 * sf
        shown = f.name if norm(f.name) == f.key else f"{f.path[-1]}/{f.name}"
        reasons = [f"název pole '{shown}' ≈ '{hit}'"] + ([extra] if extra else []) + ([why] if why else [])
        out.append((conf, bt, reasons))

    if level == "doc":
        person = any(w in norm(t) for t in f.path for w in PERSON_WORDS)
        for kind, spec in lx["party"].items():
            if role and role in spec["bt"]:
                if person and kind == "name":
                    kind, spec = "contact", lx["party"]["contact"]  # 'ContactPerson / Name' is not the company name
                    if role not in spec["bt"]:
                        continue
                ns, hit = name_score(rest or name, spec["words"] | (lx["party"]["name"]["words"] if person else set()))
                if ns:
                    add(spec["bt"][role], ns, hit, f"strana: {ROLE_LABEL[role]} ({role_src})"
                        + (", kontaktní osoba" if person and kind == "contact" else ""))
    for (lv, bt), words in lx["terms"].items():
        if lv != level:
            continue
        ns, hit = name_score(name, words)
        if ns:
            if role and level == "doc" and bt in ("BT-1", "BT-2", "BT-22", "BT-112", "BT-109"):
                ns *= 0.5  # 'Dodavatel / Cislo' is not the invoice number
            add(bt, ns, hit)
    # distinctive values without a name match
    for k, (bt, conf) in SHAPE_ONLY.items():
        if level == "doc" and shape.get(k, 0) >= 0.99 and not any(b == bt for _, b, _ in out):
            out.append((conf, bt, [f"hodnota má tvar {k.upper()} ({f.values[0]})"]))
    if level == "doc" and role:
        for k, (kind, conf) in ROLE_SHAPE_ONLY.items():
            bt = lx["party"][kind]["bt"].get(role)
            if bt and shape.get(k, 0) >= 0.99 and not any(b == bt for _, b, _ in out):
                out.append((conf, bt, [f"hodnota má tvar {k} ({f.values[0]})", f"strana: {ROLE_LABEL[role]} ({role_src})"]))
    if level == "line" and shape.get("gtin", 0) >= 0.99 and len(f.values[0]) in (8, 13, 14):
        out.append((0.6, "BT-157", [f"hodnoty jsou platné GTIN/EAN ({f.values[0]})"]))
    return out


def _rule(f: SourceField, bt: str, group_path: tuple | None) -> dict:
    if group_path is None:
        path = " > ".join(f.path)
    elif f.path == group_path:
        path = "@"
    else:
        path = "@ > " + " > ".join(f.path[len(group_path):])
    rule = {"path": path, "value": f.name}
    term = catalog().get(bt)
    if term and term.datatype == "Date":
        fmts = {date_format(v) for v in f.values}
        fmt = next(iter(fmts - {None, "iso"}), None)
        if fmt:
            rule["date"] = fmt
    elif f.shape().get("comma", 0) > 0:
        rule["decimal"] = ","
    if bt == "BT-130":
        known = {u.upper() for u in f.values} & set(UNIT_MAP)
        if known:
            rule["map"] = {v: UNIT_MAP[v.upper()] for v in sorted(set(f.values)) if v.upper() in UNIT_MAP}
            rule["note"] = "Jednotka převedena na UN/ECE Rec 20 (odhad)."
    if bt in ("BT-29", "BT-46", "BT-71") and f.shape().get("gln", 0) >= 0.99:
        rule["scheme"] = "0088"
    if bt == "BT-157":
        rule["scheme"] = "0160"
    return rule


CORE = {"BT-1", "BT-2"}
AMOUNTS = {"BT-109", "BT-110", "BT-112", "BT-115", "BT-131", "BT-116"}


def looks_like_invoice(g: "Guess") -> tuple[bool, str]:
    """Is it worth presenting the guess at all? (config files, code lists, orders are not invoices)."""
    bts = {p.bt for p in g.proposals if p.field is not None}
    if not bts & CORE:
        return False, "nenalezeno číslo ani datum dokladu"
    if not bts & AMOUNTS:
        return False, "nenalezena žádná částka faktury"
    if len(bts) < 6:
        return False, f"rozpoznáno jen {len(bts)} údajů faktury"
    return True, ""


def _all_candidates(fields, groups) -> list:
    cands = []
    for key, f in fields.items():
        level, gpath = _level(f.path, groups)
        for conf, bt, reasons in _candidates(f, level):
            if conf >= MIN_CONFIDENCE * 0.5:  # weak name matches may still be confirmed by arithmetic
                cands.append((conf, -len(f.path), bt, level, key, gpath, reasons))
    return cands


def guess(msg) -> Guess:
    counts, fields = collect(msg)
    groups = detect_groups(counts, fields)
    cat = catalog()
    cands = _all_candidates(fields, groups)
    ev = arith.find(fields, groups, counts, cands)
    if ev.vat_group and "BG-23" not in groups:  # a single VAT breakdown found by arithmetic: re-level the fields
        groups["BG-23"] = {"path": ev.vat_group, "count": counts.get(ev.vat_group, 1), "reasons": ev.vat_reasons, "score": 0.8}
        cands = _all_candidates(fields, groups)
        first, ev = ev, arith.find(fields, groups, counts, cands)
        for key, slot in first.support.items():  # the breakdown evidence of the first pass stays valid
            if key[0] == "vat":
                ev.support.setdefault(key, {}).update(slot)
        for key, slot in first.refute.items():
            if key[0] == "vat":
                ev.refute.setdefault(key, {}).update(slot)
    cands = arith.apply(ev, cands, fields, lambda path: _level(path, groups))
    taken_bt: set[tuple[str, str]] = set()
    taken_field: set[tuple] = set()
    proposals: list[Proposal] = []
    for conf, _, bt, level, key, gpath, reasons in cands:
        if conf < MIN_CONFIDENCE or (level, bt) in taken_bt or key in taken_field:
            continue
        taken_bt.add((level, bt))
        taken_field.add(key)
        f = fields[key]
        proposals.append(Proposal(bt, cat.get(bt).name, level, f, conf, reasons, _rule(f, bt, gpath)))
    if not any(p.bt == "BT-5" for p in proposals):
        cur = sorted((f for k, f in fields.items() if f.shape().get("currency", 0) >= 0.99),
                     key=lambda f: (0 if any(w in norm(f.name) for w in ("curr", "mena", "waehr", "divisa")) else 1, len(f.path)))
        if cur:
            f = cur[0]
            proposals.append(Proposal("BT-5", cat.get("BT-5").name, "doc", f, 0.6,
                                      [f"kód měny ({f.values[0]}) – jediný výskyt měny je v '{' > '.join(f.path)}'"],
                                      _rule(f, "BT-5", None)))
    proposals += _implied(proposals, groups)
    checks = arith.verify(proposals, groups, annotate=False)
    # an implied copy (e.g. BT-106 = BT-109) that the arithmetic contradicts is dropped and computed instead
    failed = {k for c in checks if not c["ok"] for k in c["bts"]}
    dropped = [p for p in proposals if (p.level, p.bt) in failed and p.field is not None
               and (p.reasons[0].startswith("stejná hodnota jako") or p.confidence < 0.6)]
    proposals = [p for p in proposals if p not in dropped]
    for p in dropped:  # keep the field visible as unassigned (unless another proposal still uses it)
        if not any(q.field is p.field for q in proposals):
            taken_field.discard(next((k for k, f in fields.items() if f is p.field), None))
    replaced = []
    for p in dropped:
        alt = [(k, txt) for k, (strong, txt) in ev.support.get((p.level, p.bt), {}).items()
               if strong and k not in taken_field and _level(fields[k].path, groups)[0] == p.level]
        if alt:
            k, txt = alt[0]
            taken_field.add(k)
            f = fields[k]
            replaced.append(Proposal(p.bt, p.name, p.level, f, arith.NEW_CONF[True], ["✓ " + txt],
                                     _rule(f, p.bt, _level(f.path, groups)[1])))
    if replaced:  # a replacement must pass the checks too
        bad = {k for c in arith.verify(proposals + replaced, groups, annotate=False) if not c["ok"] for k in c["bts"]}
        proposals += [p for p in replaced if (p.level, p.bt) not in bad]
    checks = arith.verify(proposals, groups)

    def make(bt, level, f, conf, reasons, rule):
        return Proposal(bt, cat.get(bt).name, level, f, conf, reasons, rule)

    extra, computed, more = arith.complete(proposals, groups, ev, fields, make)
    proposals += extra
    checks += more

    root = msg.root_tag
    client = {"name": f"Odhad – {root}", "base": "xml_generic", "match": {"ROOT": root},
              "note": "Návrh vytvořený odhadem (nenaučený formát) – zkontrolujte a uložte.", "terms": {}, "groups": {}}
    for bg, g in groups.items():
        client["groups"][bg] = {"each": " > ".join(g["path"]), "scope": "line" if bg == "BG-25" else "header"}
    for p in proposals:
        if "computed" not in p.rule:
            client["terms"].setdefault(p.bt, []).append(p.rule)
    if computed:
        client["computed"] = computed
    unused = [f for k, f in fields.items() if k not in taken_field]
    order = {t: i for i, t in enumerate(cat.order)}
    proposals.sort(key=lambda p: ({"doc": 0, "vat": 1, "line": 2}[p.level], order.get(p.bt, 9999)))
    return Guess(root, client, proposals, groups, unused, checks, computed, ev.facts)


def _implied(props: list[Proposal], groups) -> list[Proposal]:
    """Terms that follow from others when the format has no separate field (no prepayment, no document allowances)."""
    have = {(p.level, p.bt): p for p in props}
    cat = catalog()
    out = []

    def same(src_bt, bt, why, factor=0.85, level="doc"):
        s = have.get((level, src_bt))
        if s and (level, bt) not in have:
            out.append(Proposal(bt, cat.get(bt).name, level, s.field, s.confidence * factor,
                                [f"stejná hodnota jako {src_bt} – {why}"], dict(s.rule)))

    if ("doc", "BT-113") not in have:
        same("BT-112", "BT-115", "ve formátu není samostatná částka k úhradě ani záloha")
        same("BT-115", "BT-112", "ve formátu není samostatná celková částka ani záloha")
    if ("doc", "BT-107") not in have and ("doc", "BT-108") not in have:
        same("BT-109", "BT-106", "ve formátu nejsou slevy ani poplatky dokladu")
        same("BT-106", "BT-109", "ve formátu nejsou slevy ani poplatky dokladu")
    def derive(bt, src_bt, fn, why, factor=0.8, check=None):
        src = have.get(("doc", src_bt))
        if src and ("doc", bt) not in have and "path" in src.rule and (check is None or check(src.field)):
            have[("doc", bt)] = pr = Proposal(bt, cat.get(bt).name, "doc", src.field, src.confidence * factor, [why],
                                              {"derive": fn, "args": {"path": src.rule["path"], "value": src.rule["value"]}})
            out.append(pr)

    derive("BT-81", "BT-84", "payment_means_from_account_at", "odvozeno z čísla účtu / IBAN (převod na účet = 30)")
    for party, gln_bt, vat_bt in (("BT-34", "BT-29", "BT-31"), ("BT-49", "BT-46", "BT-48")):
        derive(party, gln_bt, "gln_endpoint_at", f"elektronická adresa z GLN ({gln_bt}, schéma 0088)",
               check=lambda f: f.shape().get("gln", 0) >= 0.99)
        derive(party, vat_bt, "sk_endpoint_from_vat_at", f"elektronická adresa SK z IČ DPH ({vat_bt}, schéma 0245)",
               check=lambda f: all(v.upper().startswith("SK") for v in f.values))
    if "BG-25" in groups and ("line", "BT-126") not in have:
        out.append(Proposal("BT-126", cat.get("BT-126").name, "line", None, 0.6,
                            ["ve formátu není číslo řádku – použije se pořadí řádku ve zprávě"],
                            {"derive": "position", "note": "ODHAD: číslo řádku = pořadí ve zprávě."}))
    if ("doc", "BT-3") not in have:
        out.append(Proposal("BT-3", cat.get("BT-3").name, "doc", None, 0.5,
                            ["předpoklad: běžná faktura – v souboru není pole s typem dokladu"],
                            {"const": "380", "note": "ODHAD: typ dokladu 380 (faktura) – ve formátu nenalezen."}))
    for level, rate_bt, cat_bt in (("vat", "BT-119", "BT-118"), ("line", "BT-152", "BT-151")):
        r = have.get((level, rate_bt))
        if r and (level, cat_bt) not in have:
            out.append(Proposal(cat_bt, cat.get(cat_bt).name, level, r.field, r.confidence * 0.8,
                                ["odvozeno ze sazby DPH (kladná sazba = S, 0 % nejednoznačné)"],
                                {"derive": "vat_category_from_rate_at",
                                 "args": {"path": r.rule["path"], "value": r.rule["value"]}}))
    return out
