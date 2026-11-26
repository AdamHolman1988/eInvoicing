"""Native Python implementation of the KoSIT validator scenario engine.

Reads KoSIT configuration repositories (``scenarios.xml`` + resources, framework 1.0.0) and
runs them the same way the KoSIT Java validator does:

    well-formedness -> first scenario whose <match> is true -> XML Schema -> each Schematron XSLT (SVRL)
    -> in:createReportInput -> the scenario's report XSL (param input-document) -> <acceptMatch>

so official configurations (e.g. XRechnung) and our own Peppol/SK configuration work unchanged,
and the same configuration can be cross-checked in the Java validator.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import pathlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

from lxml import etree

from .. import __version__
from ..resources import data_path
from . import saxon

S = "http://www.xoev.de/de/validator/framework/1/scenarios"
IN = "http://www.xoev.de/de/validator/framework/1/createreportinput"
REP = "http://www.xoev.de/de/validator/varl/1"
SVRL = "http://purl.oclc.org/dsdl/svrl"
NS = {"s": S, "in": IN, "rep": REP, "svrl": SVRL}

BUILTIN = {
    "peppol": "Peppol BIS 3.0 + EN 16931 (CEN 1.3.17, Peppol 3.0.21) + SK CIUS 1.13",
    "xrechnung": "KoSIT XRechnung 3.0.2 (oficiální konfigurace KoSIT)",
}


@dataclass
class Scenario:
    name: str
    element: etree._Element
    namespaces: dict[str, str]
    match: str
    xsd: list[tuple[str, pathlib.Path]]
    schematron: list[tuple[str, pathlib.Path, etree._Element]]
    report: pathlib.Path
    accept_match: str | None


@dataclass
class Repository:
    id: str
    name: str
    root: pathlib.Path
    scenarios: list[Scenario]
    no_scenario_report: pathlib.Path | None


@dataclass
class Message:
    code: str
    level: str  # error | warning | information
    text: str
    step: str  # name of the validation step (resource)
    xpath: str | None = None
    line: int | None = None


@dataclass
class Result:
    repository: str
    scenario: str | None
    accepted: bool
    valid: bool
    messages: list[Message] = field(default_factory=list)
    steps: list[tuple[str, bool]] = field(default_factory=list)  # (step name, valid)
    report_xml: str = ""
    warn_steps: list[str] = field(default_factory=list)  # steps that passed but raised warnings


def _res(el, root: pathlib.Path) -> tuple[str, pathlib.Path, etree._Element]:
    return (el.findtext("s:name", namespaces=NS), (root / el.findtext("s:location", namespaces=NS)).resolve(), el)


@lru_cache(maxsize=None)
def load(repo: str) -> Repository:
    """Load a repository: built-in id ('peppol', 'xrechnung') or a path to a KoSIT config directory."""
    root = data_path("rules", repo) if repo in BUILTIN else pathlib.Path(repo)
    doc = etree.parse(str(root / "scenarios.xml")).getroot()
    scenarios = []
    for sc in doc.findall("s:scenario", NS):
        scenarios.append(Scenario(
            name=sc.findtext("s:name", namespaces=NS),
            element=sc,
            namespaces={n.get("prefix"): n.text.strip() for n in sc.findall("s:namespace", NS)},
            match=sc.findtext("s:match", namespaces=NS).strip(),
            xsd=[_res(r, root)[:2] for r in sc.findall("s:validateWithXmlSchema/s:resource", NS)],
            schematron=[_res(r, root) for r in sc.findall("s:validateWithSchematron/s:resource", NS)],
            report=_res(sc.find("s:createReport/s:resource", NS), root)[1],
            accept_match=(sc.findtext("s:acceptMatch", namespaces=NS) or "").strip() or None,
        ))
    nsr = doc.find("s:noScenarioReport/s:resource", NS)
    return Repository(repo, BUILTIN.get(repo) or doc.findtext("s:name", namespaces=NS) or repo, root,
                      scenarios, _res(nsr, root)[1] if nsr is not None else None)


@lru_cache(maxsize=None)
def _schema(path: pathlib.Path) -> etree.XMLSchema:
    return etree.XMLSchema(etree.parse(str(path)))


# --- SVRL locations -> lxml XPath (for line numbers) ------------------------------------------
_Q = re.compile(r"Q\{[^}]*\}([\w.-]+)")
_ISO = re.compile(r"\*:([\w.-]+)\[namespace-uri\(\)='[^']*'\]")


def _line_of(tree: etree._ElementTree, location: str | None) -> int | None:
    if not location:
        return None
    expr = _ISO.sub(r"*[local-name()='\1']", location)
    expr = re.sub(r"@\*\[local-name\(\)='([\w.-]+)'\]", r"@\1", _Q.sub(r"*[local-name()='\1']", expr))
    expr = expr.replace("@*[local-name()=", "@*[local-name()=")
    try:
        hit = tree.xpath(expr)
    except (etree.XPathError, TypeError):
        return None
    if not hit:
        return None
    node = hit[0]
    if isinstance(node, etree._Element):
        return node.sourceline
    parent = getattr(node, "getparent", lambda: None)()
    return parent.sourceline if parent is not None else None


def _el(parent, tag, text=None, **attrs):
    e = etree.SubElement(parent, tag, **attrs)
    if text is not None:
        e.text = str(text)
    return e


def _copy_resource(parent, res_el):
    parent.append(etree.fromstring(etree.tostring(res_el)))


def validate(data: bytes, repo_id: str = "peppol", name: str = "document.xml") -> Result:
    repo = load(repo_id)
    with saxon.LOCK:
        return _validate(repo, data, name)


def _validate(repo: Repository, data: bytes, name: str) -> Result:
    cri = etree.Element(f"{{{IN}}}createReportInput", nsmap={"in": IN, "s": S, "svrl": SVRL},
                        frameworkVersion="1.0.0")
    eng = _el(cri, f"{{{IN}}}engine")
    _el(eng, f"{{{IN}}}name", f"MsgValidator {__version__} (KoSIT-compatible, Python + Saxon HE)")
    _el(cri, f"{{{IN}}}timestamp", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    ident = _el(cri, f"{{{IN}}}documentIdentification")
    h = _el(ident, f"{{{IN}}}documentHash")
    _el(h, f"{{{IN}}}hashAlgorithm", "SHA-256")
    _el(h, f"{{{IN}}}hashValue", base64.b64encode(hashlib.sha256(data).digest()).decode())
    _el(ident, f"{{{IN}}}documentReference", name)

    # 1) well-formedness
    try:
        tree = etree.ElementTree(etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True)))
    except etree.XMLSyntaxError as e:
        wf = _el(cri, f"{{{IN}}}validationResultsWellformedness")
        err = _el(wf, f"{{{IN}}}xmlSyntaxError")
        _el(err, f"{{{IN}}}message", str(e))
        _el(err, f"{{{IN}}}severityCode", "SEVERITY_FATAL_ERROR")
        _el(err, f"{{{IN}}}rowNumber", e.lineno or -1)
        _el(err, f"{{{IN}}}columnNumber", e.offset or -1)
        return Result(repo.id, None, False, False,
                      [Message("XML-WELLFORMED", "error", str(e), "XML", None, e.lineno)])

    text = etree.tostring(tree, encoding="unicode")
    doc = saxon.parse(text)

    # 2) scenario
    sc = next((s for s in repo.scenarios if saxon.xpath_true(doc, s.match, s.namespaces)), None)
    if sc is None:
        return Result(repo.id, None, False, False,
                      [Message("NO-SCENARIO", "error", f"Dokument neodpovídá žádnému scénáři konfigurace '{repo.name}'.", "scénář")])
    cri.append(etree.fromstring(etree.tostring(sc.element)))

    steps: list[tuple[str, bool]] = []
    # 3) XML Schema
    xsd_ok = True
    if sc.xsd:
        res = _el(cri, f"{{{IN}}}validationResultsXmlSchema")
        for xname, xpath_ in sc.xsd:
            _copy_resource(res, sc.element.find("s:validateWithXmlSchema/s:resource", NS))
            schema = _schema(xpath_)
            if not schema.validate(tree):
                xsd_ok = False
                for err in schema.error_log:
                    e = _el(res, f"{{{IN}}}xmlSyntaxError")
                    _el(e, f"{{{IN}}}message", f"cvc-xsd: {err.message}")
                    _el(e, f"{{{IN}}}severityCode", "SEVERITY_ERROR")
                    _el(e, f"{{{IN}}}rowNumber", err.line)
                    _el(e, f"{{{IN}}}columnNumber", err.column)
            steps.append((xname, xsd_ok))

    # 4) Schematron – like KoSIT, only on schema-valid documents
    if xsd_ok:
        for sname, spath, sres in sc.schematron:
            svrl = saxon.stylesheet(str(spath)).transform_to_string(xdm_node=doc)
            r = _el(cri, f"{{{IN}}}validationResultsSchematron")
            _copy_resource(r, sres)
            results = _el(r, f"{{{IN}}}results")
            results.append(etree.fromstring(svrl.encode("utf-8")))

    # 5) report + acceptance
    report_exe = saxon.stylesheet(str(sc.report))
    report_exe.set_parameter("input-document", doc)
    cri_node = saxon.parse(etree.tostring(cri, encoding="unicode"))
    report_xml = report_exe.transform_to_string(xdm_node=cri_node)
    report_exe.clear_parameters()
    rep_node = saxon.parse(report_xml)
    ns = dict(sc.namespaces, rep=REP)
    accepted = saxon.xpath_true(rep_node, sc.accept_match, ns) if sc.accept_match else \
        saxon.xpath_true(rep_node, "/rep:report/rep:assessment/rep:accept", ns)

    rep = etree.fromstring(report_xml.encode("utf-8"))
    msgs, warn_steps = [], []
    for vsr in rep.iter(f"{{{REP}}}validationStepResult"):
        step = vsr.findtext("s:resource/s:name", namespaces=NS) or vsr.get("id")
        if not vsr.get("id", "").startswith("val-xsd"):
            # KoSIT's report marks a step valid="false" even when it holds only warnings; a step fails only on errors
            levels = {m.get("level") or "error" for m in vsr.findall("rep:message", NS)}
            steps.append((step, vsr.get("valid") == "true" or "error" not in levels))
            if "warning" in levels and "error" not in levels:
                warn_steps.append(step)
        for m in vsr.findall("rep:message", NS):
            line = int(m.get("lineNumber")) if m.get("lineNumber") else _line_of(tree, m.get("xpathLocation"))
            msgs.append(Message(m.get("code") or "UNSPECIFIC", m.get("level") or "error",
                                " ".join("".join(m.itertext()).split()), step, m.get("xpathLocation"), line))
    return Result(repo.id, sc.name, accepted, rep.get("valid") == "true", msgs, steps, report_xml, warn_steps)
