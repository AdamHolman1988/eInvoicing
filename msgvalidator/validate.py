"""Top-level orchestration: bytes in -> Report out."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import __version__
from .detect import Detection, detect
from .edifact import parser as edi_parser
from .edifact import structure
from .profiles import loader
from .profiles.checker import PLACEHOLDER_RE, Finding, check_profile, check_values, combine, merge
from .semantic.catalog import catalog
from .semantic.extract import extract
from .semantic.model import Semantic

DEFAULT_PROFILES = ["peppol-bis3", "sk-cius"]
EDIFACT_MAPPINGS = {("INVOIC", "D96A"): "edifact_invoic_eancom", ("INVOIC", "D01B"): "edifact_invoic_eancom"}


@dataclass
class MessageResult:
    ref: str
    label: str
    structure: list[Finding]
    semantic: Semantic | None
    values: list[Finding]
    profiles: dict[str, list[Finding]]  # profile id -> findings (gap analysis)
    gaps: list[Finding] = field(default_factory=list)  # combined over all profiles
    rules: list[Finding] = field(default_factory=list)  # KoSIT / Schematron findings
    rules_info: dict | None = None  # repository, scenario, accepted, steps
    virtual_xml: bytes | None = None  # EDIFACT → virtual UBL used for the rules
    guess: dict | None = None  # unknown format read by a GUESSED mapping (msgvalidator/guess): proposals, groups


@dataclass
class Report:
    filename: str
    created: str
    tool_version: str
    detection: Detection
    profiles: list[loader.Profile]
    envelope: list[Finding] = field(default_factory=list)
    messages: list[MessageResult] = field(default_factory=list)
    embedded_xml: bytes | None = None  # XML extracted from a hybrid PDF / ORION XML converted from CCV XML

    def counts(self) -> dict[str, int]:
        c = {"error": 0, "warning": 0, "info": 0}
        for f in self.all_findings():
            c[f.severity] += 1
        return c

    def all_findings(self):
        yield from self.envelope
        for m in self.messages:
            yield from m.structure
            yield from m.values
            yield from m.gaps
            yield from m.rules


def _issue_to_finding(i: dict) -> Finding:
    return Finding(i["severity"], i["code"], i["message"], line=i.get("line"), segment=i.get("segment"))


LEVEL = {"error": "error", "warning": "warning", "information": "info"}


def rules_findings(result) -> tuple[list[Finding], dict]:
    """Convert a KoSIT result into findings + summary."""
    from .xmlval.paths import readable
    out = [Finding(LEVEL.get(m.level, "error"), m.code, m.text, line=m.line,
                   segment=readable(m.xpath), profiles=[m.step]) for m in result.messages]
    info = {"repository": result.repository, "scenario": result.scenario, "accepted": result.accepted,
            "steps": result.steps}
    return out, info


TARGETS = {"peppol": "Peppol BIS 3.0 / EN 16931", "xrechnung": "XRechnung 3.0 (DE)"}
XRECHNUNG_ID = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
UBL_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CII_RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
CII_RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"


def rule_targets(profiles, forced: str | None = None) -> list[str]:
    """Which official rule sets to run: one per target standard of the selected profiles (Peppol, XRechnung …)."""
    if forced:
        return [forced]
    out = []
    for p in profiles:
        if p.rules not in out:
            out.append(p.rules)
    return out or ["peppol"]


def _combine_runs(runs: list[dict]) -> tuple[list[Finding], dict]:
    findings = merge([f for r in runs for f in r["findings"]])
    info = {"runs": [{k: v for k, v in r.items() if k != "findings"} for r in runs],
            "accepted": all(r["accepted"] for r in runs),
            "repository": runs[0]["repository"], "scenario": runs[0]["scenario"], "steps": runs[0]["steps"]}
    return findings, info


def _own_target(data: bytes) -> str:
    """The standard a UBL / CII document declares itself to be (BT-24)."""
    from lxml import etree
    try:
        root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return "peppol"
    ids = root.findtext(f"{{{UBL_CBC}}}CustomizationID") or root.findtext(
        f"{{{CII_RSM}}}ExchangedDocumentContext/{{{CII_RAM}}}GuidelineSpecifiedDocumentContextParameter/{{{CII_RAM}}}ID") or ""
    return "xrechnung" if "xrechnung_3" in ids else "peppol"


def _as_target(data: bytes, target: str) -> bytes:
    """'What if' copy of a UBL / CII document declaring itself as the target standard (only BT-24 changes)."""
    from lxml import etree
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    el = root.find(f"{{{UBL_CBC}}}CustomizationID")
    if el is None:
        el = root.find(f"{{{CII_RSM}}}ExchangedDocumentContext/{{{CII_RAM}}}GuidelineSpecifiedDocumentContextParameter/{{{CII_RAM}}}ID")
    if el is not None and target == "xrechnung":
        el.text = XRECHNUNG_ID
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def native_rules(data: bytes, filename: str, targets: list[str]) -> tuple[list[Finding], dict]:
    """UBL / CII as delivered: the rules of the standard it declares, plus 'what if' runs for other targets."""
    from .xmlval import kosit
    own = _own_target(data)
    runs = []
    for t in [own] + [x for x in targets if x != own]:
        doc, note = data, None
        if t != own and t == "xrechnung":
            doc = _as_target(data, t)
            note = ("Dokument se k XRechnung nehlásí – kontrola „co kdyby“: identifikátor specifikace (BT-24) "
                    "dočasně nastaven na XRechnung 3.0, ostatní obsah beze změny.")
        findings, info = rules_findings(kosit.validate(doc, t, filename or "document.xml"))
        for f in findings:
            f.profiles = [TARGETS.get(t, t)]
        runs.append({"target": t, "label": TARGETS.get(t, t), "note": note, **info, "findings": findings})
    return _combine_runs(runs)


def virtual_rules_findings(sem, rules_repo: str = "peppol"):
    """Source format → virtual UBL declared as the target standard → official rules; findings point back to the source."""
    from .ubl.writer import provenance_for, write
    from .xmlval import kosit
    from .xmlval.paths import readable
    if rules_repo == "xrechnung":
        import dataclasses
        from .semantic.model import Value
        doc = dataclasses.replace(sem.document, values={
            **sem.document.values, "BT-24": [Value("BT-24", XRECHNUNG_ID, how="const", note="Doplní konverze (XRechnung).")]})
        sem = dataclasses.replace(sem, document=doc)
    vdoc = write(sem)
    result = kosit.validate(vdoc.xml, rules_repo, "virtual-ubl.xml")
    out = []
    for m in result.messages:
        prov = provenance_for(vdoc, m.line)
        bt, val = prov if prov else (None, None)
        where = readable(m.xpath)
        hint = f"virtuální UBL: {where}" + (f" · {bt}" if bt else "")
        if val is not None and val.how in ("derived", "ambiguous", "const"):
            hint += f" · hodnota '{val.value}' je odvozená konverzí"
        sev = LEVEL.get(m.level, "error")
        if val is not None and PLACEHOLDER_RE.match(val.value):
            sev, hint = "info", hint + " · anonymizovaná/testovací hodnota – nález ignorován"
        out.append(Finding(sev, m.code, m.text, bt=bt,
                           line=val.line if val is not None else None,
                           segment=val.segment if val is not None else None, hint=hint,
                           profiles=[TARGETS.get(rules_repo, rules_repo)]))
    out += [Finding("info", "UBL-CONVERSION", n, profiles=[TARGETS.get(rules_repo, rules_repo)]) for n in vdoc.notes]
    info = {"repository": result.repository, "scenario": f"virtuální UBL {vdoc.kind} → {result.scenario}",
            # ignoring findings caused only by anonymised test values
            "accepted": result.accepted or not any(f.severity == "error" for f in out),
            "steps": result.steps}
    return merge(out), info, vdoc.xml


def virtual_rules_all(sem, targets: list[str]):
    runs, xml = [], None
    for t in targets:
        findings, info, vxml = virtual_rules_findings(sem, t)
        xml = xml or vxml
        runs.append({"target": t, "label": TARGETS.get(t, t), "note": None, **info, "findings": findings})
    findings, info = _combine_runs(runs)
    return findings, info, xml


def validate(data: bytes, filename: str = "", profile_ids: list[str] | None = None,
             rules_repo: str | None = None, virtual_rules: bool = True, client=None, guess: bool = True) -> Report:
    """rules_repo: None = official rules of every target standard among the selected profiles (Peppol, XRechnung),
    or one forced KoSIT configuration.
    client (SAP IDoc only): None = pick a client mapping automatically, "standard" = standard mapping,
    a client id, or a client mapping dict (unsaved draft from the mapping editor)."""
    profile_ids = profile_ids or DEFAULT_PROFILES
    det = detect(data)
    rep = Report(filename=filename, created=dt.datetime.now().isoformat(timespec="seconds"),
                 tool_version=__version__, detection=det, profiles=[loader.load(p) for p in profile_ids])
    targets = rule_targets(rep.profiles, rules_repo)
    if det.family == "PDF":
        _pdf(data, rep, profile_ids, rules_repo, virtual_rules, client)
        return rep
    if det.family == "SBDH":
        _sbdh(data, rep, profile_ids, rules_repo, virtual_rules, client)
        return rep
    if det.family in ("XML-UBL", "XML-CII"):
        res = MessageResult("1", det.label, [], None, [], {})
        res.rules, res.rules_info = native_rules(data, filename, targets)
        try:
            if det.family == "XML-UBL":
                from .ubl.reader import read
            else:
                from .cii.reader import read
            sem = read(data)
        except Exception as ex:  # malformed XML is already reported by the rules engine
            res.structure.append(Finding("warning", "UBL-READ" if det.family == "XML-UBL" else "CII-READ",
                                         f"{'UBL' if det.family == 'XML-UBL' else 'CII'} nelze převést na BT model: {ex}"))
        else:
            res.semantic = sem
            res.values = merge(check_values(sem))
            for p in rep.profiles:
                res.profiles[p.id] = merge(check_profile(sem, p))
            res.gaps = combine(list(res.profiles.values()))
        rep.messages.append(res)
        return rep
    if det.family == "XML-ORION" and det.supported:
        rep.messages.append(_orion(data, det, rep, targets, virtual_rules))
        return rep
    if det.family == "XML-ORION-CCV":
        from .orion import ccv
        try:
            xml = ccv.to_orion3(data)
        except Exception as ex:
            rep.envelope.append(Finding("error", "CCV-CONVERT", f"CCV XML se nepodařilo převést na ORION XML 3: {ex}"))
            return rep
        rep.embedded_xml = xml
        res = _orion(xml, det, rep, targets, virtual_rules)
        res.label = "ORION CCV XML → ORION XML 3 (převodník INVOIC exp ORION 3 XML)"
        rep.messages.append(res)
        return rep
    if (det.family == "SAP-IDOC" and det.supported) or det.details.get("mappable"):
        _idoc(data, det, rep, targets, virtual_rules, client, guess)
        return rep
    if det.family in ("EDITEL-INHOUSE", "ORION-FLAT") and det.supported:
        _flat(data, det, rep, targets, virtual_rules)
        return rep
    if det.family != "EDIFACT":
        rep.envelope.append(Finding("warning", "FMT-UNSUPPORTED",
                                    f"Rozpoznáno: {det.label}. {det.note or 'Tento formát zatím není podporován.'}"))
        return rep

    ic = edi_parser.parse(data)
    rep.envelope = [_issue_to_finding(i) for i in ic.issues]
    if not ic.messages:
        rep.envelope.append(Finding("error", "ENV-NO-MESSAGE", "Soubor neobsahuje žádnou zprávu (UNH)."))
    for msg in ic.messages:
        label = f"{msg.type} {msg.version} {msg.assoc} – zpráva {msg.ref}"
        tree, issues = structure.match(msg)
        res = MessageResult(msg.ref, label, [_issue_to_finding(i) for i in issues], None, [], {})
        mapping = EDIFACT_MAPPINGS.get((msg.type, msg.version))
        if tree is None or mapping is None:
            res.structure.append(Finding("warning", "MAP-UNSUPPORTED",
                                         f"Pro {msg.type} {msg.version} zatím není mapování na EN 16931 – gap analýza přeskočena."))
            rep.messages.append(res)
            continue
        _semantic_checks(res, extract(msg, tree, mapping), rep, targets, virtual_rules)
        rep.messages.append(res)
    return rep


def _semantic_checks(res: MessageResult, sem: Semantic, rep: Report, targets: list[str], virtual_rules: bool) -> None:
    """BT model -> value checks, gap analysis per profile, official rules over the virtual UBL."""
    res.semantic = sem
    res.values = merge(check_values(sem) + [Finding("info", n.get("code", "MAP-EMPTY-GROUP"), n["message"],
                                                    line=n["line"]) for n in sem.notes])
    for p in rep.profiles:
        res.profiles[p.id] = merge(check_profile(sem, p))
    res.gaps = combine(list(res.profiles.values()))
    if virtual_rules:
        res.rules, res.rules_info, res.virtual_xml = virtual_rules_all(sem, targets)


def _orion(data: bytes, det: Detection, rep: Report, targets: list[str], virtual_rules: bool) -> MessageResult:
    """ORION XML INVOIC: structure (XSD + documentation) -> BT model -> gaps -> virtual UBL rules."""
    from .orion import reader as orion_reader
    from .orion import structure as orion_structure
    res = MessageResult("1", det.label, orion_structure.check(data), None, [], {})
    try:
        sem = orion_reader.read(data)
    except Exception as ex:  # malformed XML is already reported by the structure check
        res.structure.append(Finding("warning", "ORION-READ", f"ORION XML nelze převést na BT model: {ex}"))
        return res
    _semantic_checks(res, sem, rep, targets, virtual_rules)
    return res


FLAT_MAPPINGS = {"editel_inhouse_invoic_d01b": "flat_editel_inhouse_invoic_d01b",
                 "orion_ccv_invoic": "flat_orion_ccv_invoic"}


def _flat(data: bytes, det: Detection, rep: Report, targets: list[str], virtual_rules: bool) -> None:
    """Fixed-width INHOUSE: layout checks -> records as segments -> mapping by field names -> BT model."""
    from . import flat
    from .flat import mapping as flat_mapping
    layout_id = det.details["layout"]
    ff = flat.parse(data, layout_id)
    rep.envelope = [_issue_to_finding(i) for i in ff.issues]
    mp = flat_mapping.load(FLAT_MAPPINGS[layout_id])
    for msg in ff.messages:
        label = f"{ff.layout.label} – doklad {msg.ref}"
        res = MessageResult(msg.ref, label, [_issue_to_finding(i) for i in msg.issues], None, [], {})
        tree = flat.build_tree(msg, ff.layout)
        sem = extract(msg, tree, mp["id"], mapping=mp, source_format=f"{ff.layout.label} ({ff.encoding})")
        _semantic_checks(res, sem, rep, targets, virtual_rules)
        rep.messages.append(res)


def _pdf(data: bytes, rep: Report, profile_ids, rules_repo: str | None, virtual_rules: bool, client) -> None:
    """Hybrid PDF (ZUGFeRD / Factur-X): container checks, then the embedded XML like a standalone file."""
    from . import pdfinv
    inv = pdfinv.read(data)
    rep.detection.label = inv.label
    rep.detection.details = {"attachments": inv.attachments, "xml": inv.xml_name, "profile": inv.profile,
                             "xmp": inv.xmp}
    rep.envelope = [Finding(i["severity"], i["code"], i["message"], hint=i.get("hint")) for i in inv.issues]
    if not inv.xml or inv.syntax in ("ZUGFeRD 1.0",):
        return
    if inv.profile == "XRECHNUNG" and "xrechnung_3" not in (inv.guideline or "").lower():
        rep.envelope.append(Finding("warning", "PDF-XRECHNUNG-OLD",
                                    f"Starší verze XRechnung ({inv.guideline}) – oficiální konfigurace KoSIT je jen pro XRechnung 3.0; "
                                    f"zkontrolováno podle EN 16931."))
    sub = validate(inv.xml, inv.xml_name, profile_ids, rules_repo, virtual_rules, client)
    rep.envelope += sub.envelope
    for m in sub.messages:
        m.label = f"{inv.xml_name} (vloženo v PDF) – {m.label}"
        rep.messages.append(m)
    rep.embedded_xml = inv.xml


def _sbdh(data: bytes, rep: Report, profile_ids, rules_repo: str | None, virtual_rules: bool, client) -> None:
    """Peppol envelope: envelope checks, the payload validated like a standalone file, envelope vs. payload."""
    from . import sbdh
    env = sbdh.read(data)
    rep.detection.details = {"sender": env.sender, "receiver": env.receiver, "scopes": env.scopes}
    rep.envelope = [Finding(i["severity"], i["code"], i["message"], hint=i.get("hint")) for i in env.issues]
    if not env.payload:
        return
    sub = validate(env.payload, "payload.xml", profile_ids, rules_repo, virtual_rules, client)
    rep.detection.label = f"Peppol obálka (SBDH) → {sub.detection.label}"
    rep.envelope += sub.envelope
    sem = next((m.semantic for m in sub.messages if m.semantic), None)
    rep.envelope += [Finding(i["severity"], i["code"], i["message"], hint=i.get("hint")) for i in sbdh.check_against(env, sem)]
    for m in sub.messages:
        m.label = f"doklad v obálce – {m.label}"
        rep.messages.append(m)
    rep.embedded_xml = env.payload


def idoc_mapping_for(msg, client=None) -> dict:
    """Effective (unresolved) mapping for one IDoc message – see validate(client=...)."""
    from .idoc import mapping as idoc_mapping
    base = idoc_mapping.base_for(msg)
    if isinstance(client, dict):
        return idoc_mapping.effective(client, base)
    if client == "standard":
        return idoc_mapping.effective(None, base)
    if client:
        c = idoc_mapping.get_client(client)
        if c is None:
            raise ValueError(f"Klientské mapování '{client}' nenalezeno ve složce {idoc_mapping.settings.mapping_dir()}.")
        return idoc_mapping.effective(c, base)
    return idoc_mapping.effective(idoc_mapping.pick(msg), base)


def _idoc(data: bytes, det: Detection, rep: Report, targets: list[str], virtual_rules: bool, client=None,
          guess_unknown: bool = True) -> None:
    """SAP IDoc XML: structure -> segments by field name -> (client) mapping -> BT model."""
    from . import idoc
    from .idoc import mapping as idoc_mapping
    f = idoc.parse(data)
    rep.envelope = [_issue_to_finding(i) for i in f.issues]
    for msg in f.messages:
        guessed = None
        if msg.generic and client is None and idoc_mapping.pick(msg) is None:
            from .guess import guess, looks_like_invoice
            guessed = guess(msg) if guess_unknown else None
            ok, why = looks_like_invoice(guessed) if guessed else (False, "")
            if not ok:
                rep.envelope.append(Finding(
                    "warning", "FMT-UNMAPPED",
                    f"Formát {msg.idoctyp} validátor nezná a pro tohoto klienta zatím není mapování."
                    + (f" Odhad nepoužit – soubor nevypadá jako faktura ({why})." if why else ""),
                    hint="Otevřete soubor v editoru „Mapování klienta“ (tlačítko u výsledku) a přiřaďte údaje faktury."))
                continue
            rep.envelope.append(Finding(
                "warning", "FMT-GUESSED",
                f"Formát {msg.idoctyp} validátor nezná – údaje faktury jsou ODHADNUTÉ podle názvů polí a tvaru hodnot "
                f"({len(guessed.proposals)} BT, průměrná jistota {guessed.confidence:.0%}). Nejde o naučený formát, "
                f"výsledek berte orientačně.",
                hint="Odhad zkontrolujte v editoru „Mapování klienta“ (otevře se předvyplněný) a uložte – "
                     "pak se z něj stane naučený formát."))
        mp = idoc_mapping_for(msg, guessed.client if guessed else client)
        who = mp.get("client", {}).get("name")
        kind = msg.idoctyp if msg.generic else f"SAP IDoc {msg.idoctyp}"
        label = f"{kind} – doklad {msg.ref}" + (f" · mapování klienta {who}" if who else " · standardní mapování")
        res = MessageResult(msg.ref, label, [_issue_to_finding(i) for i in msg.issues], None, [], {})
        resolved = idoc_mapping.resolve_for(msg, mp)
        sem = extract(msg, msg.root, mp["id"], mapping=resolved,
                      source_format=kind + (f" (klient {who})" if who else ""))
        bt1 = sem.document.values.get("BT-1")
        if msg.generic and bt1:
            res.ref = bt1[0].value
            res.label = res.label.replace(f"doklad {msg.ref}", f"doklad {bt1[0].value}")
        _semantic_checks(res, sem, rep, targets, virtual_rules)
        if guessed:
            _mark_guessed(res, guessed)
        rep.messages.append(res)


def _mark_guessed(res: MessageResult, g) -> None:
    """A guessed mapping cannot tell 'the format does not carry it' from 'not recognised' – say so."""
    res.label = res.label.replace(f" · mapování klienta {g.client['name']}", "") + " · ODHAD (nenaučený formát)"
    res.semantic.source_format += " – ODHAD mapování"
    res.guess = {"confidence": round(g.confidence, 2), "proposals": [p.as_dict() for p in g.proposals],
                 "groups": {bg: {"path": " > ".join(v["path"]), "count": v["count"], "reasons": v["reasons"]}
                            for bg, v in g.groups.items()},
                 "unused": [{"source": f.label, "sample": f.values[0]} for f in g.unused],
                 "checks": [{k: c[k] for k in ("rule", "ok", "detail")} for c in g.checks],
                 "computed": {k: v.get("note", "") for k, v in g.computed.items()}}
    for f in res.gaps + [f for fs in res.profiles.values() for f in fs]:
        if f.code == "GAP-NOT-IN-FORMAT":
            f.code, f.severity = "GAP-NOT-GUESSED", "warning"
            f.message = f.message.split(":")[0] + ": povinné – odhad ho v souboru nenašel (může chybět, nebo má nečekaný název)."
            f.hint = "Pokud v souboru je, přiřaďte ho v editoru „Mapování klienta“."
    res.gaps = merge(res.gaps)


def coverage_rows(res: MessageResult, profiles: list[loader.Profile]) -> list[dict]:
    """BT x profile table for the report (document level + first instance of each repeating group)."""
    sem = res.semantic
    if sem is None:
        return []
    cat = catalog()
    rows = []
    for tid in cat.order:
        t = cat.get(tid)
        if t.kind != "BT":
            continue
        bg = sem.repeating.get(tid)
        ctxs = sem.groups.get(bg, []) if bg else [sem.document]
        vals = [v for c in ctxs for v in c.values.get(tid, [])]
        levels = {p.id: (p.requirements[tid].level if tid in p.requirements else "optional") for p in profiles}
        if not vals and all(l == "optional" for l in levels.values()):
            continue
        hows = {v.how for v in vals}
        status = ("explicit" if hows <= {"explicit", "mapped"} else
                  "const" if hows == {"const"} else "derived") if vals else (
            "missing" if tid in sem.mapped_terms else "not-in-format")
        present_in = len({id(c) for c in ctxs if c.values.get(tid)})
        rows.append({"bt": tid, "name": t.name, "group": bg, "levels": levels, "status": status,
                     "value": vals[0].value if vals else None,
                     "count": f"{present_in}/{len(ctxs)}" if bg else None,
                     "line": vals[0].line if vals else None})
    return rows
