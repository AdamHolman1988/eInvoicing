"""Hybrid PDF invoices: ZUGFeRD 1.0 / 2.x, Factur-X, XRechnung or UBL embedded in a PDF (PDF/A-3).

Reads the embedded XML and the XMP metadata (fx:ConformanceLevel, fx:DocumentFileName, pdfaid:part)
and checks the container. The embedded XML itself is then validated like any other XML file.
Full PDF/A-3 conformance (fonts, colour profiles …) needs veraPDF – here only the declarations are checked.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from lxml import etree

KNOWN_NAMES = {
    "factur-x.xml": "Factur-X / ZUGFeRD 2.1+",
    "zugferd-invoice.xml": "ZUGFeRD 2.0",
    "ZUGFeRD-invoice.xml": "ZUGFeRD 1.0",
    "xrechnung.xml": "XRechnung (ZUGFeRD 2.1+)",
}
# CII guideline (BT-24) -> profile name; ZUGFeRD 2.0 uses urn:zugferd.de:2p0:<profile>, Factur-X urn:factur-x.eu:1p0:<profile>
SUFFIXES = [("basicwl", "BASIC WL"), ("minimum", "MINIMUM"), ("basic", "BASIC"), ("extended", "EXTENDED")]


def profile_of(guideline: str | None) -> str | None:
    g = (guideline or "").strip().lower()
    if not g:
        return None
    if "xrechnung" in g:
        return "XRECHNUNG"
    last = g.rsplit("#", 1)[-1].rsplit(":", 1)[-1]
    for suffix, name in SUFFIXES:
        if last == suffix:
            return name
    return "EN 16931" if g.startswith("urn:cen.eu:en16931:2017") else None


NOT_EN16931 = {"MINIMUM", "BASIC WL"}
CII_NS = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
ZF1_NS = "urn:ferd:CrossIndustryDocument:invoice:1p0"


@dataclass
class PdfInvoice:
    attachments: list[str] = field(default_factory=list)
    xml_name: str | None = None
    xml: bytes | None = None
    syntax: str | None = None  # CII | UBL | ZUGFeRD 1.0 | XML
    guideline: str | None = None  # BT-24 from the XML
    profile: str | None = None  # from the guideline
    xmp: dict = field(default_factory=dict)  # ConformanceLevel, DocumentFileName, DocumentType, Version, pdfa_part …
    af_relationship: str | None = None
    issues: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        if not self.xml:
            return "PDF bez strukturované faktury"
        kind = KNOWN_NAMES.get(self.xml_name or "", "vložené XML")
        return f"PDF – {kind}" + (f", profil {self.profile}" if self.profile else "") + f" ({self.xml_name}, {self.syntax})"


def _issue(sev, code, msg, hint=None):
    return {"severity": sev, "code": code, "message": msg, "hint": hint}


def _xmp(reader) -> dict:
    out = {}
    try:
        meta = reader.xmp_metadata
        raw = meta.stream.get_data() if meta is not None else None
    except Exception:  # pragma: no cover - broken metadata stream
        raw = None
    if not raw:
        return out
    try:
        root = etree.fromstring(raw.strip(), etree.XMLParser(resolve_entities=False, no_network=True, recover=True))
    except etree.XMLSyntaxError:
        return out
    if root is None:
        return out
    want = {"ConformanceLevel", "DocumentFileName", "DocumentType", "Version", "part", "conformance"}
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for k, v in el.attrib.items():  # rdf:Description fx:ConformanceLevel="EN 16931"
            name = etree.QName(k).localname
            if name in want and v.strip():
                out.setdefault(name, v.strip())
        name = etree.QName(el).localname
        if name in want and (el.text or "").strip():
            out.setdefault(name, el.text.strip())
    if "part" in out:
        out["pdfa"] = out.pop("part") + out.pop("conformance", "")
    return out


def _af_relationship(reader, name: str) -> str | None:
    try:
        names = reader.trailer["/Root"]["/Names"]["/EmbeddedFiles"]["/Names"]
        for i in range(0, len(names), 2):
            if str(names[i]) == name:
                spec = names[i + 1].get_object()
                rel = spec.get("/AFRelationship")
                return str(rel).lstrip("/") if rel is not None else None
    except Exception:
        return None
    return None


def _pick(atts: dict[str, list[bytes]]) -> str | None:
    for n in ("factur-x.xml", "zugferd-invoice.xml", "ZUGFeRD-invoice.xml", "xrechnung.xml"):
        for a in atts:
            if a.lower() == n.lower():
                return a
    xmls = [a for a in atts if a.lower().endswith(".xml")]
    return xmls[0] if xmls else None


def read(data: bytes) -> PdfInvoice:
    import pypdf
    out = PdfInvoice()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        atts = reader.attachments
    except Exception as ex:
        out.issues.append(_issue("error", "PDF-READ", f"PDF nelze načíst: {ex}"))
        return out
    out.attachments = list(atts)
    out.xmp = _xmp(reader)
    name = _pick(atts)
    if name is None:
        out.issues.append(_issue(
            "error", "PDF-NO-XML",
            "PDF neobsahuje vloženou strukturovanou fakturu (XML) – jde jen o obrazovou fakturu, ne o ZUGFeRD / Factur-X.",
            "Hybridní faktura musí mít jako přílohu factur-x.xml (ZUGFeRD 2.1+ / Factur-X) nebo zugferd-invoice.xml."))
        return out
    out.xml_name, out.xml = name, atts[name][0]
    out.af_relationship = _af_relationship(reader, name)
    _inspect(out)
    return out


def _inspect(out: PdfInvoice) -> None:
    try:
        root = etree.fromstring(out.xml, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as ex:
        out.syntax = "XML"
        out.issues.append(_issue("error", "PDF-XML-INVALID", f"Vložené {out.xml_name} není platné XML: {ex}"))
        return
    ns = etree.QName(root).namespace
    if ns == CII_NS:
        out.syntax = "CII"
        out.guideline = root.findtext(f"{{{CII_NS}}}ExchangedDocumentContext/"
                                      "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}"
                                      "GuidelineSpecifiedDocumentContextParameter/"
                                      "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}ID")
    elif ns == ZF1_NS:
        out.syntax = "ZUGFeRD 1.0"
    elif ns and "ubl:schema:xsd" in ns:
        out.syntax = "UBL"
        out.guideline = root.findtext("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}CustomizationID")
    else:
        out.syntax = "XML"
    out.profile = profile_of(out.guideline)

    x = out.xmp
    if out.syntax == "ZUGFeRD 1.0":
        out.issues.append(_issue("warning", "PDF-ZUGFERD1",
                                 "ZUGFeRD 1.0 – starý formát (do 2020), není podle EN 16931; oficiální pravidla pro něj neexistují.",
                                 "Odesílatel by měl přejít na ZUGFeRD 2.x / Factur-X (profil EN 16931) nebo XRechnung."))
    if not x.get("ConformanceLevel"):
        out.issues.append(_issue("warning", "PDF-XMP", "V metadatech PDF (XMP) chybí popis ZUGFeRD / Factur-X (fx:ConformanceLevel).",
                                 "Factur-X vyžaduje v XMP DocumentType, DocumentFileName, Version a ConformanceLevel."))
    else:
        lvl = x["ConformanceLevel"].upper().replace("EN16931", "EN 16931").replace("COMFORT", "EN 16931")
        if out.profile and lvl != out.profile and not (lvl == "XRECHNUNG" and out.profile == "XRECHNUNG"):
            out.issues.append(_issue("warning", "PDF-PROFILE-MISMATCH",
                                     f"Profil v metadatech PDF ({x['ConformanceLevel']}) se liší od profilu ve vloženém XML ({out.profile})."))
        if x.get("DocumentFileName") and x["DocumentFileName"] != out.xml_name:
            out.issues.append(_issue("warning", "PDF-FILENAME",
                                     f"Metadata PDF uvádějí soubor {x['DocumentFileName']}, vložen je {out.xml_name}."))
    if out.xml_name not in KNOWN_NAMES:
        out.issues.append(_issue("warning", "PDF-FILENAME",
                                 f"Vložené XML se jmenuje {out.xml_name} – standard očekává factur-x.xml (resp. zugferd-invoice.xml / xrechnung.xml)."))
    if x.get("pdfa") and not x["pdfa"].startswith("3"):
        out.issues.append(_issue("warning", "PDF-PDFA",
                                 f"PDF se hlásí jako PDF/A-{x['pdfa']}; ZUGFeRD / Factur-X vyžaduje PDF/A-3 (přílohy)."))
    elif not x.get("pdfa"):
        out.issues.append(_issue("info", "PDF-PDFA", "PDF neuvádí shodu s PDF/A-3 (pdfaid). Úplnou kontrolu PDF/A dělá např. veraPDF."))
    if out.af_relationship is None:
        out.issues.append(_issue("info", "PDF-AFREL", f"Příloha {out.xml_name} nemá AFRelationship (PDF/A-3 ho vyžaduje; obvykle Alternative / Data)."))
    if out.profile in NOT_EN16931:
        out.issues.append(_issue("warning", "PDF-PROFILE-LIGHT",
                                 f"Profil {out.profile} není plnohodnotná faktura podle EN 16931 (chybí položky / daňový rozpis); "
                                 f"v Německu ji od 2025 nelze použít jako e-fakturu.",
                                 "Chyby oficiálních pravidel EN 16931 níže jsou u tohoto profilu očekávané."))
    out.issues.append(_issue("info", "PDF-CONTAINER",
                             f"Vložené XML: {out.xml_name} ({out.syntax}"
                             + (f", {out.guideline}" if out.guideline else "") + ")"
                             + (f"; další přílohy: {', '.join(a for a in out.attachments if a != out.xml_name)}"
                                if len(out.attachments) > 1 else "")
                             + (f"; XMP: {x.get('ConformanceLevel')} / {x.get('DocumentFileName')} / verze {x.get('Version')}"
                                if x.get("ConformanceLevel") else "")))

