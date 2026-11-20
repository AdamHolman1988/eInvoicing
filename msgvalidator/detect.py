"""Guess what kind of message a file contains."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree


@dataclass
class Detection:
    family: str  # EDIFACT | EDITEL-INHOUSE | ORION-FLAT | XML-UBL | XML-CII | XML-ORION | XML-ORION-CCV | SBDH | SAP-IDOC | XML | UNKNOWN
    label: str
    message: str | None = None  # INVOIC / Invoice / ...
    version: str | None = None
    details: dict = field(default_factory=dict)
    supported: bool = False
    note: str | None = None


UNH_RE = re.compile(r"UNH\+[^+']*\+([A-Z]{6}):([A-Z]):(\w+):(\w+)(?::(\w+))?")
UBL_NS = {
    "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2": "Invoice",
    "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2": "CreditNote",
}
CII_NS = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
EDIFACT_SUPPORTED = {("INVOIC", "D96A"), ("INVOIC", "D01B")}
FLAT_LAYOUTS = {("INVOIC", "D01B"): "editel_inhouse_invoic_d01b"}
HDR_LAYOUTS = {"orion_ccv_invoic": ("ORION-FLAT", "ORION TXT INVOIC (CCV)"),
               "editel_inhouse_invoic_d01b": ("EDITEL-INHOUSE", "EDITEL INHOUSE INVOIC D01B")}


def detect(data: bytes) -> Detection:
    head = data[:4096].lstrip(b"\xef\xbb\xbf \r\n\t")
    if head.startswith(b"%PDF"):
        return Detection("PDF", "PDF (hybridní faktura?)", supported=True,
                         note="Hledá se vložená strukturovaná faktura (ZUGFeRD / Factur-X / XRechnung).")
    if head.startswith((b"UNA", b"UNB", b"UNH")):
        text = data[:20000].decode("latin-1")
        m = UNH_RE.search(text)
        if not m:
            return Detection("EDIFACT", "UN/EDIFACT (bez UNH)", note="Nenalezen segment UNH.")
        msg, _, rel, agency, assoc = m.groups()
        version = f"D{rel}"
        sup = (msg, version) in EDIFACT_SUPPORTED
        return Detection("EDIFACT", f"UN/EDIFACT {msg} {version}" + (f" ({assoc})" if assoc else ""),
                         message=msg, version=version, details={"agency": agency, "assoc": assoc},
                         supported=sup,
                         note=None if sup else f"{msg} {version} zatím není podporován (MVP: INVOIC D96A, D01B).")
    if head.startswith(b"SYS"):
        line = head.split(b"\n", 1)[0].decode("latin-1")
        m = re.search(r"(\d{2}[A-Z])([A-Z]{6})", line)
        ver, msg = (m.group(1), m.group(2)) if m else (None, None)
        layout = FLAT_LAYOUTS.get((msg, f"D{ver}"))
        return Detection("EDITEL-INHOUSE", f"EDITEL INHOUSE {msg or ''} {('D' + ver) if ver else ''}".strip(),
                         message=msg, version=f"D{ver}" if ver else None, details={"layout": layout},
                         supported=layout is not None,
                         note=None if layout else f"EDITEL INHOUSE {msg} D{ver} zatím nemá layout (podporováno: INVOIC D01B).")
    if head.startswith(b"HDR"):
        # record-oriented fixed width without SYS: EDITEL INHOUSE D01B or ORION TXT (CCV) – pick the layout that fits
        from .flat import best_layout, load_layout
        lid, score = best_layout(data, list(HDR_LAYOUTS))
        family, label = HDR_LAYOUTS[lid]
        lay = load_layout(lid)
        note = None if score == 0 else f"Soubor neodpovídá layoutu přesně ({score} chyb typu/záznamu v úvodu) – zkontrolujte, zda jde o správný formát."
        return Detection(family, f"{label} (pevná délka)", message="INVOIC", version=lay.raw.get("version"),
                         details={"layout": lid, "fit_errors": score}, supported=True, note=note)
    from .idoc import is_idoc_text
    if is_idoc_text(data):
        text = data[:4000].decode("utf-8", errors="replace")
        typ = re.search(r"IDOCTYP\s+(\S+)", text)
        mes = re.search(r"MESTYP\s+(\S+)", text)
        typ, mes = (typ.group(1) if typ else "IDoc"), (mes.group(1) if mes else "INVOIC")
        sup = mes == "INVOIC"
        snd = re.search(r"SNDPRN\s+(\S+)", text)
        return Detection("SAP-IDOC", f"SAP IDoc {typ} (textový výpis)", message=mes, version=typ,
                         details={"sender": snd.group(1) if snd else None}, supported=sup,
                         note=None if sup else f"IDoc typu {mes} zatím není podporován (podporováno: INVOIC).")
    if head.startswith(b"<") or head.startswith(b"<?xml"):
        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
            root = etree.fromstring(data, parser)
        except etree.XMLSyntaxError as e:
            return Detection("XML", "XML (nevalidní)", note=f"XML nelze načíst: {e}")
        qn = etree.QName(root)
        if qn.localname == "StandardBusinessDocument":
            return Detection("SBDH", "Peppol obálka (SBDH)", supported=True,
                             note="Kontroluje se obálka a doklad uvnitř.")
        if qn.namespace in UBL_NS:
            cid = root.findtext("{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}CustomizationID")
            label = f"UBL 2.1 {UBL_NS[qn.namespace]}"
            if cid and "peppol" in cid:
                label += " – Peppol BIS 3"
            return Detection("XML-UBL", label, message=UBL_NS[qn.namespace], details={"customization_id": cid},
                             note="Validace UBL přes oficiální Schematron (EN 16931 + Peppol) je ve fázi 2 roadmapy.")
        if qn.namespace == CII_NS:
            gid = root.findtext(f"{{{CII_NS}}}ExchangedDocumentContext/"
                                "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}GuidelineSpecifiedDocumentContextParameter/"
                                "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}ID")
            return Detection("XML-CII", "UN/CEFACT CII", message="CrossIndustryInvoice", supported=True,
                             details={"customization_id": gid})
        if qn.localname == "orion_message":
            mt = root.findtext("header/message_type")
            ver = root.findtext("header/version")
            sup = mt == "INVOIC"
            note = None
            if sup and not (ver or "3.").startswith("3."):
                note = (f"Hlavička uvádí verzi '{ver}', obsah se kontroluje podle ORION XML INVOIC 3.x "
                        f"(exporty z ERP často verzi v hlavičce neaktualizují).")
            return Detection("XML-ORION", f"ORION XML {mt or ''} {ver or ''}".strip(), message=mt, version=ver,
                             supported=sup,
                             note=note if sup else f"ORION XML {mt or '?'} {ver or ''} zatím není podporován "
                                                   f"(podporováno: INVOIC).")
        if qn.localname == "INVOIC" and qn.namespace is None and root.find("HDR") is not None:
            return Detection("XML-ORION-CCV", "ORION CCV XML INVOIC (eBUS)", message="INVOIC", supported=True,
                             note="Převedeno produkčním převodníkem „INVOIC exp ORION 3 XML“ na ORION XML 3 "
                                  "a zkontrolováno jako ORION XML.")
        from .idoc import is_idoc
        if is_idoc(root):
            typ = root.findtext(".//EDI_DC40/IDOCTYP") or qn.localname
            mes = root.findtext(".//EDI_DC40/MESTYP") or "INVOIC"
            sup = mes == "INVOIC"
            return Detection("SAP-IDOC", f"SAP IDoc {typ} (XML)", message=mes, version=typ,
                             details={"sender": root.findtext(".//EDI_DC40/SNDPRN")}, supported=sup,
                             note=None if sup else f"IDoc typu {mes} zatím není podporován (podporováno: INVOIC).")
        return Detection("XML", f"XML <{qn.localname}> (neznámý formát)", details={"namespace": qn.namespace, "mappable": True},
                         note="Formát validátor nezná – lze ho namapovat v editoru Mapování klienta.")
    return Detection("UNKNOWN", "Neznámý formát")
