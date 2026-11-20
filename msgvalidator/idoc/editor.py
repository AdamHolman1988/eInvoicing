"""Data for the visual mapping editor (UI tab "Mapování"): source tree, business terms, live preview."""
from __future__ import annotations

from ..i18n import localize, tr
from ..profiles import loader
from ..semantic.catalog import catalog
from . import IdocMessage, dictionary, parse, segment_info
from . import mapping as idoc_mapping

QUALIFIER_FIELDS = ("PARVW", "QUALF", "SUMID", "IDDAT", "ALCKZ", "TDID")
STATUS = {"explicit": "ok", "mapped": "ok", "derived": "derived", "ambiguous": "derived", "const": "const"}

# Derivations offered in the editor for a picked field (args: path + value of that field)
TRANSFORMS = {
    "": "beze změny",
    "date": "datum RRRRMMDD → ISO",
    "gln_endpoint_at": "GLN → elektronická adresa (0088)",
    "sk_endpoint_from_vat_at": "IČ DPH / DIČ → elektronická adresa SK (0245)",
    "sk_tax_id_from_vat_at": "IČ DPH → SK DIČ",
    "vat_id_if_prefixed_at": "IČ DPH jen s kódem země",
    "country_code_at": "kód země (2 písmena)",
    "country_from_vat_at": "země z IČ DPH",
    "vat_category_from_rate_at": "sazba DPH → kategorie (S / Z)",
    "payment_means_from_account_at": "účet / IBAN → kód platby 30",
    "ref_if_differs_at": "jen pokud se liší od čísla dokladu",
}


def _qualifier(el_tag: str, fields: dict[str, str]) -> tuple[str, str] | None:
    q = segment_info(el_tag).get("qualifier")
    if q and fields.get(q):
        return q, fields[q]
    for q in QUALIFIER_FIELDS:
        if fields.get(q):
            return q, fields[q]
    return None


def source_tree(msg: IdocMessage) -> list[dict]:
    """Distinct segment kinds (tag + qualifier) in document order, with field labels and sample values."""
    nodes: dict[str, dict] = {}

    def walk(children, parents: list[str]):
        for ch in children:
            seg = ch.trigger if hasattr(ch, "trigger") else ch
            if seg is None or seg.tag == "UNS":
                continue
            names = msg.fields.get(seg.tag, [])
            vals = {n: (seg.get(i + 1) or "") for i, n in enumerate(names)}
            q = _qualifier(seg.tag, vals)
            step = f"{seg.tag}[{q[0]}={q[1]}]" if q else seg.tag
            path = " > ".join(parents + [step])
            info = segment_info(seg.tag)
            node = nodes.get(path)
            if node is None:
                node = nodes[path] = {
                    "path": path, "tag": seg.tag, "step": step, "parent": " > ".join(parents) or None,
                    "depth": len(parents), "label": info.get("label") or ("" if msg.generic else "(segment mimo slovník)"),
                    "qualifier": {"field": q[0], "code": q[1], "label": info.get("codes", {}).get(q[1])} if q else None,
                    "count": 0, "summary": seg.tag == "E1EDS01", "fields": {}}
            node["count"] += 1
            for n, v in vals.items():
                f = node["fields"].setdefault(n, {"name": n, "label": info.get("fields", {}).get(n), "samples": []})
                if v and v not in f["samples"] and len(f["samples"]) < 3:
                    f["samples"].append(v)
            if hasattr(ch, "trigger"):
                walk(ch.children[1:], parents + [step])

    walk(msg.root.children, [])
    out = []
    for n in nodes.values():
        n["fields"] = [f for f in n["fields"].values() if f["samples"] or f["label"]]
        out.append(n)
    return out


def terms(profile_ids: list[str]) -> list[dict]:
    cat = catalog()
    profs = [loader.load(p) for p in profile_ids]
    names_sk = {}
    try:
        names_sk = {k: r.name_sk for k, r in loader.load("sk-cius").requirements.items() if r.name_sk}
    except Exception:  # pragma: no cover - profile missing
        pass
    out = []
    for tid in cat.order:
        t = cat.get(tid)
        lv = [p.requirements[tid].level for p in profs if tid in p.requirements]
        level = "required" if "required" in lv else "conditional" if "conditional" in lv else "optional"
        if t.kind == "BG" and t.min >= 1:
            level = "required"
        out.append({"id": tid, "kind": t.kind, "name": t.name, "name_sk": names_sk.get(tid), "parent": t.parent,
                    "depth": len(cat.ancestors(tid)), "level": level, "max": t.max, "datatype": t.datatype, "codelist": t.codelist})
    return out


def open_file(data: bytes, profile_ids: list[str], lang: str = "cs") -> dict:
    f = parse(data)
    if not f.messages:
        raise ValueError("Soubor neobsahuje IDoc.")
    msg = f.messages[0]
    picked = idoc_mapping.pick(msg)
    base = idoc_mapping.base_for(msg)
    std = idoc_mapping.standard(base)
    client = ({k: picked.get(k) for k in ("id", "name", "note", "base", "match", "terms", "groups", "aux", "computed")
               if picked.get(k)}
              if picked else {"id": "", "name": "", "match": idoc_mapping.suggest_match(msg), "terms": {}, "groups": {}})
    client["base"] = base
    guessed = None
    if picked is None and msg.generic:
        from ..guess import guess
        g = guess(msg)
        if g.proposals:
            client["terms"], client["groups"] = g.client["terms"], g.client["groups"]
            if g.computed:  # totals / VAT breakdown the format lacks (arithmetic, guess/arith.py)
                client["computed"] = g.computed
            guessed = {"confidence": round(g.confidence, 2), "proposals": [p.as_dict() for p in g.proposals],
                       "checks": [{k: c[k] for k in ("rule", "ok", "detail")} for c in g.checks]}
    source = source_tree(msg)
    term_list = terms(profile_ids)
    transforms = dict(TRANSFORMS)
    codes = {tag: s.get("codes", {}) for tag, s in dictionary()["segments"].items() if s.get("codes")}
    if lang == "en":
        for n in source:
            n["label"] = tr(n["label"], lang)
            if n["qualifier"]:
                n["qualifier"]["label"] = tr(n["qualifier"]["label"], lang)
            for fld in n["fields"]:
                fld["label"] = tr(fld["label"], lang)
        for t in term_list:
            t["name_sk"] = None  # English term names from the EN 16931 catalogue
        transforms = {k: tr(v, lang) for k, v in transforms.items()}
        codes = {tag: {c: tr(v, lang) for c, v in cs.items()} for tag, cs in codes.items()}
    return {
        "idoc": {"type": msg.idoctyp, "ref": msg.ref, "count": len(f.messages), "control": msg.control,
                 "generic": msg.generic, "base": base},
        "source": source,
        "terms": term_list,
        "standard": {"terms": std["terms"], "groups": std["groups"], "aux": std.get("aux", {})},
        "client": client,
        "guess": guessed,
        "picked": picked["id"] if picked else None,
        "clients": [{"id": c["id"], "name": c.get("name"), "match": c.get("match"), "file": c.get("file"),
                     "error": c.get("error")} for c in idoc_mapping.clients()],
        "suggest_match": idoc_mapping.suggest_match(msg),
        "mapping_dir": str(idoc_mapping.settings.mapping_dir()),
        "transforms": transforms,
        "codes": codes,
    }


def preview(data: bytes, client: dict, profile_ids: list[str], rules: bool = False, lang: str = "cs") -> dict:
    from ..validate import validate
    rep = validate(data, "náhled.xml", profile_ids, virtual_rules=rules, client=client)
    localize(rep, lang)
    m = rep.messages[0]
    sem = m.semantic
    values = {}
    for ctx in sem.contexts():
        for bt, vs in ctx.values.items():
            e = values.setdefault(bt, {"value": vs[0].value, "how": vs[0].how, "status": STATUS.get(vs[0].how, "ok"),
                                       "raw": vs[0].raw, "note": tr(vs[0].note, lang), "context": tr(ctx.label, lang), "n": 0})
            e["n"] += 1
    counts = {bg: len(insts) for bg, insts in sem.groups.items()}
    findings = [{"severity": f.severity, "code": f.code, "bt": f.bt, "message": f.message, "hint": f.hint,
                 "contexts": f.contexts[:3]} for f in m.structure + m.values + m.gaps + m.rules]
    return {"values": values, "groups": counts, "mapped": sorted(sem.mapped_terms), "findings": findings,
            "counts": rep.counts(), "label": m.label,
            "accepted": (m.rules_info or {}).get("accepted") if rules else None}
