"""Structural validation of ORION XML INVOIC.

1. XSD (msgvalidator/data/orion/INVOIC_XML3_*.xsd, chosen by header/version). The official XSDs lag behind the
   documentation (no <skonto>, <party_description> order, …) and reject empty elements that ORION tolerates, so
   such XSD messages are reported as info only; everything else as a warning (ORION-XSD).
2. Checks driven by the documentation spreadsheet (data/mappings/orion_invoic.json):
   ORION-MISSING  mandatory 'Yes' field / mandatory container missing or empty     (error)
   ORION-LENGTH   value longer than the documented length                          (warning)
   ORION-FORMAT   Date (YYYY-MM-DD) / Time (HH:MM[:SS]) / Num (decimal point) format (error)
   ORION-CODE     value not in the code list (closed list = error, open list = info)
   ORION-UNKNOWN  element not in the documentation                                 (warning)
   ORION-VERSION  element newer than the version declared in header/version        (info)
"""
from __future__ import annotations

import datetime as dt
import re

from lxml import etree

from ..profiles.checker import Finding, merge
from ..resources import data_path
from . import mapping, parse, rel_path, text, version_key, where

XSDS = [("3.1", "INVOIC_XML3_3.1.1.xsd"), ("3.0", "INVOIC_XML3_3.0.xsd")]  # newest first
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$")
NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
EMPTY_RE = re.compile(r"Element '([\w.-]+)': '' is not a valid value")
ATOMIC_RE = re.compile(r"Element '([\w.-]+)': '.*' is not a valid value of the atomic type")
UNEXPECTED_RE = re.compile(r"Element '([\w.-]+)': This element is not expected")

_xsd_cache: dict[str, etree.XMLSchema] = {}


def xsd_for(version: str | None) -> str:
    for prefix, name in XSDS:
        if (version or "").startswith(prefix):
            return name
    return XSDS[0][1]


def _schema(name: str) -> etree.XMLSchema:
    if name not in _xsd_cache:
        _xsd_cache[name] = etree.XMLSchema(etree.parse(str(data_path("orion", name))))
    return _xsd_cache[name]


def _context(el) -> list[str]:
    """Label of the nearest repeating ancestor (for merging identical findings)."""
    node = el
    while node is not None:
        tag = etree.QName(node).localname if isinstance(node.tag, str) else ""
        if tag == "item":
            return [f"položka {text(node.find('item_number')) or '?'}"]
        if tag == "party":
            return [f"partner {text(node.find('party_qualifier')) or '?'}"]
        if tag == "vat":
            return [f"DPH skupina {text(node.find('vat_group')) or '?'}"]
        if tag in ("allowance", "charge", "skonto", "article_id_add", "advance_payment"):
            return [f"{tag} #{len(list(node.itersiblings(tag, preceding=True))) + 1}"]
        node = node.getparent()
    return ["doklad"]


def _field_label(f: dict) -> str:
    return f"{f['id'] + ' ' if f.get('id') else ''}{f.get('name_cs') or f['tag']}"


def xsd_findings(root, version: str | None) -> list[Finding]:
    name = xsd_for(version)
    schema = _schema(name)
    tree = etree.ElementTree(root)
    schema.validate(tree)
    known = mapping()["by_path"].keys() | mapping()["containers_by_path"].keys()
    by_line: dict[tuple[int, str], etree._Element] = {}
    for el in root.iter(tag=etree.Element):
        by_line.setdefault((el.sourceline, etree.QName(el).localname), el)
    out, empties = [], []
    for e in schema.error_log:
        m = EMPTY_RE.search(e.message)
        if m:
            empties.append(m.group(1))
            continue
        m = UNEXPECTED_RE.search(e.message)
        el = by_line.get((e.line, m.group(1))) if m else None
        if el is not None and rel_path(el) in known:
            out.append(Finding("info", "ORION-XSD",
                               f"<{m.group(1)}> je v dokumentaci ORION, ale XSD {name} jej na tomto místě nečeká "
                               f"(jiné pořadí prvků nebo prvek novější než XSD).",
                               line=e.line, segment=where(el), contexts=_context(el)))
            continue
        msg = re.sub(r"\s+", " ", e.message)
        m = ATOMIC_RE.search(e.message)
        el = el if el is not None else (by_line.get((e.line, m.group(1))) if m else None)
        f = mapping()["by_path"].get(rel_path(el)) if el is not None else None
        if m and f and (f.get("type") or "").lower() == "char":
            out.append(Finding("info", "ORION-XSD",
                               f"XSD {name} vyžaduje pro <{m.group(1)}> jiný datový typ, než uvádí dokumentace "
                               f"(Char) – chyba XSD: {msg}", line=e.line, segment=where(el), contexts=_context(el)))
            continue
        out.append(Finding("warning", "ORION-XSD", f"XSD {name}: {msg}", line=e.line,
                           segment=where(el) if el is not None else None))
    if empties:
        uniq = list(dict.fromkeys(empties))
        out.append(Finding("info", "ORION-XSD",
                           f"{len(empties)} prázdných prvků ({', '.join('<' + t + '/>' for t in uniq[:5])}"
                           f"{' …' if len(uniq) > 5 else ''}) – XSD je u typů datum/číslo nepřipouští, ORION je toleruje; "
                           f"validátor je považuje za nevyplněné.", hint=f"XSD {name}"))
    return out


def _value_findings(el, f: dict, value: str, codelists: dict, declared: str | None) -> list[Finding]:
    out = []
    loc = dict(line=el.sourceline, segment=where(el), contexts=_context(el))
    label = _field_label(f)
    typ = (f.get("type") or "").lower()
    if typ == "date":
        ok = bool(DATE_RE.match(value))
        if ok:
            try:
                dt.date.fromisoformat(value)
            except ValueError:
                ok = False
        if not ok:
            out.append(Finding("error", "ORION-FORMAT", f"{label}: '{value}' není datum ve formátu YYYY-MM-DD.", **loc))
    elif typ == "time":
        if not TIME_RE.match(value):
            out.append(Finding("error", "ORION-FORMAT", f"{label}: '{value}' není čas ve formátu HH:MM.", **loc))
    elif typ == "num":
        if not NUM_RE.match(value):
            hint = "Desetinný oddělovač musí být tečka." if "," in value else None
            out.append(Finding("error", "ORION-FORMAT", f"{label}: '{value}' není číslo.", hint=hint, **loc))
        elif f.get("length"):
            digits = len(re.sub(r"[^0-9]", "", value))
            if digits > f["length"]:
                out.append(Finding("warning", "ORION-LENGTH",
                                   f"{label}: '{value}' má {digits} číslic, dokumentace povoluje max. {f['length']}.", **loc))
    if typ not in ("date", "time", "num") and f.get("length") and len(value) > f["length"]:
        out.append(Finding("warning", "ORION-LENGTH",
                           f"{label}: hodnota má {len(value)} znaků, dokumentace povoluje max. {f['length']}.",
                           hint=value[:80], **loc))
    cl = codelists.get(f.get("codelist") or "")
    if cl and value not in cl["codes"]:
        allowed = ", ".join(list(cl["codes"])[:12])
        if cl.get("open"):
            out.append(Finding("info", "ORION-CODE",
                               f"{label}: '{value}' není mezi kódy uvedenými v dokumentaci ({cl['name']}: {allowed}); "
                               f"seznam je otevřený, kód musí odpovídat číselníku EDIFACT/ISO.", **loc))
        else:
            out.append(Finding("error", "ORION-CODE",
                               f"{label}: '{value}' není povolený kód ({cl['name']}: {allowed}).", **loc))
    since = f.get("since")
    if since and declared and version_key(declared) and version_key(since) > version_key(declared):
        out.append(Finding("info", "ORION-VERSION",
                           f"<{f['tag']}> je ve specifikaci až od verze {since}, zpráva deklaruje verzi {declared}.", **loc))
    return out


def check(data: bytes) -> list[Finding]:
    try:
        root = parse(data)
    except etree.XMLSyntaxError as e:
        return [Finding("error", "ORION-XML", f"XML nelze načíst: {e}", line=e.lineno)]
    mp = mapping()
    by_path, containers, codelists = mp["by_path"], mp["containers_by_path"], mp["codelists"]
    declared = text(root.find("header/version"))
    out: list[Finding] = []
    if etree.QName(root).localname != "orion_message":
        return [Finding("error", "ORION-XML", "Kořenový prvek není <orion_message>.", line=root.sourceline)]
    mt = text(root.find("header/message_type"))
    if mt and mt != "INVOIC":
        out.append(Finding("error", "ORION-CODE", f"SYS1 Typ zprávy: '{mt}' – validátor podporuje jen INVOIC.",
                           line=root.find("header/message_type").sourceline))
    if declared and declared not in mp["versions"]:
        out.append(Finding("info", "ORION-VERSION",
                           f"Verze '{declared}' není v changelogu dokumentace ({', '.join(mp['versions'])}); "
                           f"kontroluje se podle {mp['version']}.", line=root.find("header/version").sourceline))
    out += xsd_findings(root, declared)

    # element by element: unknown elements, value formats, lengths, codes, versions
    for el in root.iter(tag=etree.Element):
        if el is root:
            continue
        path = rel_path(el)
        f = by_path.get(path)
        if f is None and path not in containers:
            parent = el.getparent()
            if parent is root or rel_path(parent) in by_path or rel_path(parent) in containers:
                out.append(Finding("warning", "ORION-UNKNOWN",
                                   f"Prvek <{etree.QName(el).localname}> ({path}) není v dokumentaci ORION INVOIC {mp['version']}.",
                                   line=el.sourceline, segment=where(el), contexts=_context(el)))
            continue
        if f is None:
            c = containers[path]
            if c.get("since") and declared and version_key(c["since"]) > version_key(declared):
                out.append(Finding("info", "ORION-VERSION",
                                   f"<{etree.QName(el).localname}> je ve specifikaci až od verze {c['since']}, "
                                   f"zpráva deklaruje verzi {declared}.", line=el.sourceline, segment=where(el),
                                   contexts=_context(el)))
            continue
        value = text(el)
        if value:
            out += _value_findings(el, f, value, codelists, declared)

    # mandatory fields / containers within every present parent instance
    required = [(f["path"], f) for f in mp["fields"] if f["mandatory"] == "yes"] + \
               [(c["path"], None) for c in mp["containers"] if (c.get("occurrence") or "1").startswith("1")]
    for path, f in required:
        parent_path, _, tag = path.rpartition("/")
        parents = root.findall(parent_path) if parent_path else [root]
        for parent in parents:
            child = parent.find(tag)
            ok = child is not None and (f is None or text(child))
            if ok:
                continue
            what = _field_label(f) if f else f"sekce <{tag}>"
            where_txt = parent_path or "orion_message"
            out.append(Finding("error", "ORION-MISSING",
                               f"Chybí povinný prvek <{tag}> ({what}) v {where_txt}."
                               + (" Prvek je prázdný." if child is not None else ""),
                               line=(child if child is not None else parent).sourceline,
                               segment=where(parent) if parent is not root else "orion_message",
                               contexts=_context(parent)))
    return merge(out)
