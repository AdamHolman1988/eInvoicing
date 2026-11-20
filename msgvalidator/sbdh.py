"""Peppol envelope: Standard Business Document Header (SBDH) around a UBL / CII invoice.

The payload is validated like a standalone file; here only the envelope and its consistency with the payload
(Peppol Envelope Specification 2.0: document type, process, sender / receiver, COUNTRY_C1)."""
from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

SH = "http://www.unece.org/cefact/namespaces/StandardBusinessDocumentHeader"
NS = {"sh": SH}


@dataclass
class Envelope:
    sender: str | None = None
    receiver: str | None = None
    standard: str | None = None
    type: str | None = None
    type_version: str | None = None
    instance: str | None = None
    scopes: dict[str, str] = field(default_factory=dict)
    payload: bytes | None = None
    payload_root: str | None = None  # {namespace}localname
    issues: list[dict] = field(default_factory=list)


def _issue(sev, code, msg, hint=None) -> dict:
    return {"severity": sev, "code": code, "message": msg, "hint": hint}


def read(data: bytes) -> Envelope:
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    env = Envelope()
    h = root.find("sh:StandardBusinessDocumentHeader", NS)
    if h is None:
        env.issues.append(_issue("error", "SBDH-HEADER", "Obálka nemá StandardBusinessDocumentHeader."))
    else:
        env.sender = h.findtext("sh:Sender/sh:Identifier", namespaces=NS)
        env.receiver = h.findtext("sh:Receiver/sh:Identifier", namespaces=NS)
        env.standard = h.findtext("sh:DocumentIdentification/sh:Standard", namespaces=NS)
        env.type = h.findtext("sh:DocumentIdentification/sh:Type", namespaces=NS)
        env.type_version = h.findtext("sh:DocumentIdentification/sh:TypeVersion", namespaces=NS)
        env.instance = h.findtext("sh:DocumentIdentification/sh:InstanceIdentifier", namespaces=NS)
        for s in h.findall("sh:BusinessScope/sh:Scope", NS):
            env.scopes[(s.findtext("sh:Type", namespaces=NS) or "").strip()] = (s.findtext("sh:InstanceIdentifier", namespaces=NS) or "").strip()
        for who, el in (("Sender", h.find("sh:Sender/sh:Identifier", NS)), ("Receiver", h.find("sh:Receiver/sh:Identifier", NS))):
            if el is None or not (el.text or "").strip():
                env.issues.append(_issue("error", "SBDH-PARTY", f"V obálce chybí {who}/Identifier."))
            elif el.get("Authority") != "iso6523-actorid-upis" or ":" not in el.text:
                env.issues.append(_issue("error", "SBDH-PARTY",
                                         f"{who}/Identifier '{el.text}' musí mít tvar schéma:hodnota a Authority=\"iso6523-actorid-upis\"."))
        for t in ("DOCUMENTID", "PROCESSID"):
            if not env.scopes.get(t):
                env.issues.append(_issue("error", "SBDH-SCOPE", f"V obálce chybí BusinessScope {t}."))
        if not env.scopes.get("COUNTRY_C1"):
            env.issues.append(_issue("warning", "SBDH-COUNTRY", "V obálce chybí COUNTRY_C1 (země odesílatele) – v Peppolu povinné od 2024."))
    payload = [c for c in root if isinstance(c.tag, str) and c is not h]
    if not payload:
        env.issues.append(_issue("error", "SBDH-PAYLOAD", "Obálka neobsahuje žádný doklad."))
        return env
    p = payload[0]
    env.payload_root = p.tag
    env.payload = etree.tostring(p, encoding="utf-8", xml_declaration=True)
    q = etree.QName(p)
    if env.standard and env.standard != q.namespace:
        env.issues.append(_issue("error", "SBDH-DOCTYPE", f"Obálka uvádí Standard '{env.standard}', doklad má namespace '{q.namespace}'."))
    if env.type and env.type != q.localname:
        env.issues.append(_issue("error", "SBDH-DOCTYPE", f"Obálka uvádí Type '{env.type}', doklad je <{q.localname}>."))
    return env


def check_against(env: Envelope, sem) -> list[dict]:
    """Envelope vs. the payload's business terms (BT-23, BT-24, BT-34, BT-49, BT-40)."""
    if sem is None:
        return []

    def first(bt):
        v = sem.document.values.get(bt)
        return v[0] if v else None
    out = []
    q = etree.QName(env.payload_root) if env.payload_root else None
    bt24, bt23 = first("BT-24"), first("BT-23")
    docid = env.scopes.get("DOCUMENTID")
    if docid and q is not None and bt24:
        version = "D16B" if "CrossIndustryInvoice" in q.localname else "2.1"
        expected = f"{q.namespace}::{q.localname}##{bt24.value}::{version}"
        if docid != expected:
            out.append(_issue("error", "SBDH-DOCUMENTID", f"DOCUMENTID v obálce neodpovídá dokladu.",
                              hint=f"obálka: {docid}\nočekáváno: {expected}"))
    if env.scopes.get("PROCESSID") and bt23 and env.scopes["PROCESSID"] != bt23.value:
        out.append(_issue("error", "SBDH-PROCESSID", f"PROCESSID v obálce '{env.scopes['PROCESSID']}' ≠ BT-23 '{bt23.value}'."))
    for who, ident, bt in (("Sender", env.sender, "BT-34"), ("Receiver", env.receiver, "BT-49")):
        v = first(bt)
        if ident and v:
            mine = f"{v.scheme}:{v.value}" if v.scheme else v.value
            if ident.strip().lower() != mine.strip().lower():
                out.append(_issue("warning", "SBDH-ENDPOINT",
                                  f"{who} v obálce '{ident}' ≠ {bt} v dokladu '{mine}'.",
                                  hint="Peppol směruje podle obálky; elektronická adresa v dokladu by měla být stejná."))
    c1, bt40 = env.scopes.get("COUNTRY_C1"), first("BT-40")
    if c1 and bt40 and c1 != bt40.value:
        out.append(_issue("info", "SBDH-COUNTRY", f"COUNTRY_C1 '{c1}' ≠ země prodávajícího BT-40 '{bt40.value}' "
                                                  f"(v pořádku, pokud odesílá třeba účetní firma z jiné země)."))
    return out
