"""Checks that depend on the document type (BT-3): corrective invoices, self-billing, prepayments, partial invoices.

Sources: EN 16931 (UNCL1001 subsets), Peppol BIS Billing 3.0 (PEPPOL-EN16931-P0100/P0101 – allowed type codes),
Peppol BIS Self-Billing 3.0 (BT-23 / BT-24 of self-billed invoices)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

TYPE_NAMES = {
    "71": "žádost o platbu (dílčí plnění)", "80": "vrubopis – zboží a služby", "81": "dobropis – zboží a služby",
    "82": "faktura za měřené služby", "83": "dobropis – finanční úpravy", "84": "vrubopis – finanční úpravy",
    "102": "daňové oznámení", "218": "konečná žádost o platbu (dokončené dílo)", "219": "žádost o platbu (dokončené části)",
    "326": "dílčí faktura", "331": "obchodní faktura s balicím listem", "380": "obchodní faktura", "381": "dobropis",
    "382": "provizní list", "383": "vrubopis", "384": "opravná faktura", "386": "zálohová faktura",
    "388": "daňová faktura", "389": "faktura vystavená odběratelem (self-billing)", "393": "faktoringová faktura",
    "395": "konsignační faktura", "396": "faktoringový dobropis", "532": "dobropis speditéra",
    "553": "protokol o rozdílech (speditér)", "575": "faktura pojistitele", "623": "faktura speditéra",
    "780": "faktura za přepravu", "817": "oznámení nároku", "870": "konzulární faktura",
    "875": "dílčí faktura za stavební práce", "876": "dílčí konečná faktura za stavební práce",
    "877": "konečná faktura za stavební práce",
}
CORRECTIVE = {"384", "381", "81", "83", "396", "532", "383", "80", "84"}
SELF_BILLING = {"389", "261", "527"}
PARTIAL = {"326", "875", "876", "877", "71", "218", "219"}
PEPPOL_BILLING_PROCESS = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
PEPPOL_SELFBILLING_PROCESS = "urn:fdc:peppol.eu:2017:poacc:selfbilling:01:1.0"


def _first(sem, bt):
    v = sem.document.values.get(bt)
    return v[0] if v else None


def _num(v) -> Decimal | None:
    try:
        return Decimal(v.value.replace(",", ".")) if v else None
    except InvalidOperation:
        return None


def check(sem, finding) -> list:
    """finding = Finding constructor (avoids an import cycle)."""
    out = []
    t = _first(sem, "BT-3")
    if t is None:
        return out
    code = t.value.strip()
    loc = dict(bt="BT-3", contexts=["doklad"], line=t.line, segment=t.segment)
    name = TYPE_NAMES.get(code)
    if name and code not in ("380", "381"):
        out.append(finding("info", "DOC-TYPE", f"Typ dokladu {code} = {name}.", **loc))
    bt23 = _first(sem, "BT-23")
    bt25 = sem.document.values.get("BT-25")

    if code in CORRECTIVE and not bt25:
        sev = "warning" if code == "384" else "info"
        out.append(finding(sev, "DOC-NO-PRECEDING",
                           f"{name or code}: chybí odkaz na původní fakturu (BT-25).",
                           hint="Opravný doklad by měl odkazovat na fakturu, kterou opravuje – řada odběratelů a CIUS "
                                "(např. Billa, SK CIUS u dobropisu) to vyžaduje.", **loc))

    if code in SELF_BILLING:
        if bt23 and bt23.value.strip() == PEPPOL_BILLING_PROCESS:
            out.append(finding("warning", "DOC-SELFBILLING",
                               f"Typ {code} (self-billing) není v Peppol BIS Billing 3.0 povolen (PEPPOL-EN16931-P0100).",
                               hint=f"Self-billing se v Peppolu posílá jako Peppol BIS Self-Billing 3.0: BT-23 = "
                                    f"{PEPPOL_SELFBILLING_PROCESS}, BT-24 = urn:cen.eu:en16931:2017#compliant#"
                                    f"urn:fdc:peppol.eu:2017:poacc:selfbilling:3.0. Fakturu vystavuje odběratel, ale "
                                    f"prodávající (BG-4) zůstává dodavatel.", **loc))
        else:
            out.append(finding("info", "DOC-SELFBILLING",
                               "Self-billing: fakturu vystavuje odběratel jménem dodavatele – prodávající (BG-4) je pořád "
                               "dodavatel, kupující (BG-7) je vystavitel.", **loc))
    elif bt23 and bt23.value.strip() == PEPPOL_SELFBILLING_PROCESS:
        out.append(finding("warning", "DOC-SELFBILLING",
                           f"BT-23 je proces self-billing, ale typ dokladu {code} není self-billing (389, dobropis 261).",
                           bt="BT-23", contexts=["doklad"], line=bt23.line, segment=bt23.segment))

    if code in ("326", "384", "389"):
        c40, c55 = _first(sem, "BT-40"), _first(sem, "BT-55")
        c40, c55 = (c40.value if c40 else None), (c55.value if c55 else None)
        if not ((c40 == c55 == "DE") or (code == "384" and c40 == c55 == "SK")):
            out.append(finding("warning", "DOC-PEPPOL-TYPE",
                               f"Typ {code} ({name}) Peppol BIS Billing povoluje jen mezi dvěma německými firmami"
                               f"{' (384 i mezi slovenskými)' if code == '384' else ''} – PEPPOL-EN16931-P0112.",
                               hint="Pro ostatní země použijte 380 (s odkazem BT-25) nebo dobropis 381.", **loc))

    if code == "386":
        out.append(finding("info", "DOC-PREPAYMENT",
                           "Zálohová faktura: zaplacená částka se v konečné faktuře odečítá jako zaplaceno předem (BT-113) "
                           "a konečná faktura by na zálohovou měla odkazovat (BT-25).", **loc))
    paid = _num(_first(sem, "BT-113"))
    if code not in ("386",) and paid and paid > 0 and not bt25:
        v = _first(sem, "BT-113")
        out.append(finding("info", "DOC-PREPAID-REF",
                           f"Odečtena záloha {v.value} (BT-113), ale doklad neodkazuje na zálohovou fakturu (BT-25).",
                           bt="BT-113", contexts=["doklad"], line=v.line, segment=v.segment))

    if code in PARTIAL and not (sem.document.values.get("BT-12") or bt25):
        out.append(finding("info", "DOC-PARTIAL",
                           f"{name or code}: u dílčích a konečných faktur se doporučuje odkaz na smlouvu (BT-12) "
                           f"nebo na předchozí dílčí faktury (BT-25).", **loc))

    total = _num(_first(sem, "BT-112"))
    if code == "380" and total is not None and total < 0 and sem.doc_kind == "Invoice":
        v = _first(sem, "BT-112")
        out.append(finding("info", "DOC-NEGATIVE",
                           f"Faktura 380 má zápornou celkovou částku {v.value} – nemá jít spíš o dobropis (381)?",
                           hint="EN 16931 záporné faktury dovoluje, ale řada odběratelů je odmítá.",
                           bt="BT-112", contexts=["doklad"], line=v.line, segment=v.segment))
    return out
