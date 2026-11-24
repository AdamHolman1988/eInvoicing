"""Checks that depend on the document type (BT-3): corrective invoices, self-billing, prepayments, partial invoices.

Sources: EN 16931 (UNCL1001 subsets), Peppol BIS Billing 3.0 (PEPPOL-EN16931-P0100/P0101 – allowed type codes,
section 5.6 negative invoices and credit notes), Peppol BIS Self-Billing 3.0 (BT-23 / BT-24 of self-billed invoices),
Slovak Financial Administration FAQ on eFaktúra 9/DPH/2025/IM (version 2026-09-11): part I no. 34 (a proforma is not an
e-invoice), I-50 (credit note + new invoice, BT-25), II-22 (tax document on a received payment = 388), II-38 (deducting
taxed / untaxed advances in the final invoice)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

TYPE_NAMES = {
    "71": "žádost o platbu (dílčí plnění)", "80": "vrubopis – zboží a služby", "81": "dobropis – zboží a služby",
    "82": "faktura za měřené služby", "83": "dobropis – finanční úpravy", "84": "vrubopis – finanční úpravy",
    "102": "daňové oznámení", "218": "konečná žádost o platbu (dokončené dílo)", "219": "žádost o platbu (dokončené části)",
    "326": "dílčí faktura", "331": "obchodní faktura s balicím listem", "380": "obchodní faktura", "381": "dobropis",
    "382": "provizní list", "383": "vrubopis", "384": "opravná faktura", "386": "zálohová faktura",
    "388": "daňový doklad (např. k přijaté platbě před dodáním)",
    "389": "faktura vystavená odběratelem (self-billing)", "393": "faktoringová faktura",
    "395": "konsignační faktura", "396": "faktoringový dobropis", "532": "dobropis speditéra",
    "553": "protokol o rozdílech (speditér)", "575": "faktura pojistitele", "623": "faktura speditéra",
    "780": "faktura za přepravu", "817": "oznámení nároku", "870": "konzulární faktura",
    "875": "dílčí faktura za stavební práce", "876": "dílčí konečná faktura za stavební práce",
    "877": "konečná faktura za stavební práce",
}
CORRECTIVE = {"384", "381", "81", "83", "396", "532", "383", "80", "84"}
SELF_BILLING = {"389", "261", "527"}
PARTIAL = {"326", "875", "876", "877", "71", "218", "219"}
ADVANCE = {"386", "388"}
PEPPOL_BILLING_PROCESS = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
PEPPOL_SELFBILLING_PROCESS = "urn:fdc:peppol.eu:2017:poacc:selfbilling:01:1.0"
FAQ_SK = "FAQ Finančnej správy SR k eFaktúre 9/DPH/2025/IM"


def _first(ctx, bt):
    v = ctx.values.get(bt)
    return v[0] if v else None


def _num(v) -> Decimal | None:
    try:
        return Decimal(v.value.replace(",", ".")) if v else None
    except InvalidOperation:
        return None


def check(sem, finding) -> list:
    """finding = Finding constructor (avoids an import cycle)."""
    out = []
    doc = sem.document
    t = _first(doc, "BT-3")
    if t is None:
        return out
    code = t.value.strip()
    loc = dict(bt="BT-3", contexts=["doklad"], line=t.line, segment=t.segment)
    name = TYPE_NAMES.get(code)
    if name and code not in ("380", "381"):
        out.append(finding("info", "DOC-TYPE", f"Typ dokladu {code} = {name}.", **loc))
    bt23 = _first(doc, "BT-23")
    bt25 = doc.values.get("BT-25")
    c40, c55 = _first(doc, "BT-40"), _first(doc, "BT-55")
    c40, c55 = (c40.value.strip() if c40 else None), (c55.value.strip() if c55 else None)
    sk_sk = c40 == c55 == "SK"

    if code in CORRECTIVE and not bt25:
        sev = "warning" if code == "384" or (sk_sk and code in ("381", "383")) else "info"
        out.append(finding(sev, "DOC-NO-PRECEDING",
                           f"{name or code}: chybí odkaz na původní fakturu (BT-25).",
                           hint="Opravný doklad by měl odkazovat na fakturu, kterou opravuje – řada odběratelů a CIUS "
                                "(např. Billa, SK CIUS u dobropisu) to vyžaduje."
                                + (f" Na Slovensku musí opravný doklad nést jednoznačnou referenci na původní fakturu "
                                   f"v BT-25 ({FAQ_SK}, časť I, príklad 50)." if sk_sk else ""), **loc))

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
        if not ((c40 == c55 == "DE") or (code == "384" and sk_sk)):
            out.append(finding("warning", "DOC-PEPPOL-TYPE",
                               f"Typ {code} ({name}) Peppol BIS Billing povoluje jen mezi dvěma německými firmami"
                               f"{' (384 i mezi slovenskými)' if code == '384' else ''} – PEPPOL-EN16931-P0112.",
                               hint="Pro ostatní země použijte 380 (s odkazem BT-25) nebo dobropis 381.", **loc))

    # --- advances: 386 = payment request (proforma), 388 = tax document on a received payment
    if code == "386":
        if sk_sk:
            out.append(finding("warning", "DOC-SK-PROFORMA",
                               "Zálohová faktura 386 mezi slovenskými firmami: proforma / výzva k platbě není faktura "
                               f"podle zákona o DPH a přes eFaktúru se neposílá ({FAQ_SK}, časť I, príklad 34).",
                               hint="Po přijetí platby se vystavuje daňový doklad k přijaté platbě s typem 388 "
                                    "(časť II, príklad 22) – ten už eFaktúrou je.", **loc))
        else:
            out.append(finding("info", "DOC-PREPAYMENT",
                               "Zálohová faktura: zaplacená částka se v konečné faktuře odečítá jako zaplaceno předem "
                               "(BT-113) a konečná faktura by na zálohovou měla odkazovat (BT-25).", **loc))
    if code == "388":
        out.append(finding("info", "DOC-TAX-ADVANCE",
                           "Daňový doklad k přijaté platbě (388): v konečné faktuře se zdaněná záloha odečítá záporným "
                           "řádkem (množství −1, stejná sazba DPH, odkaz BT-25 na tento doklad); vrácení zálohy se "
                           "posílá jako dobropis 381 s kladnými částkami a odkazem BT-25 na tento doklad.",
                           hint=f"{FAQ_SK}, časť II, príklad 22 a 38; Peppol BIS Billing 3.0, kap. 5.6.", **loc))

    paid = _num(_first(doc, "BT-113"))
    if code not in ADVANCE and paid and paid > 0:
        v = _first(doc, "BT-113")
        vloc = dict(bt="BT-113", contexts=["doklad"], line=v.line, segment=v.segment)
        if not bt25:
            out.append(finding("info", "DOC-PREPAID-REF",
                               f"Odečtena záloha {v.value} (BT-113), ale doklad neodkazuje na zálohový doklad (BT-25).",
                               **vloc))
        if sk_sk:
            out.append(finding("info", "DOC-SK-ADVANCE",
                               f"Záloha {v.value} odečtena jako zaplaceno předem (BT-113) – na Slovensku jen pro "
                               "nezdaněnou zálohu (bez daňového dokladu k přijaté platbě).",
                               hint="Byl-li k záloze vystaven daňový doklad 388, odečítá se záporným řádkem (množství −1, "
                                    "základ i DPH se stejnou sazbou) s odkazem BT-25 na ten doklad, ne přes BT-113 ani "
                                    f"slevu dokladu ({FAQ_SK}, časť II, príklad 38).", **vloc))

    lines = sem.groups.get("BG-25", [])
    if sk_sk and sem.doc_kind == "Invoice" and code not in ADVANCE and not bt25:
        for ln in lines:
            amt = _num(_first(ln, "BT-131"))
            if amt is not None and amt < 0:
                v = _first(ln, "BT-131")
                out.append(finding("info", "DOC-SK-ADVANCE-LINE",
                                   f"Záporný řádek {v.value} bez odkazu na předchozí doklad (BT-25).",
                                   hint="Jde-li o odpočet zdaněné zálohy, musí doklad odkazovat na daňový doklad "
                                        f"k přijaté platbě (388) v BT-25 ({FAQ_SK}, časť II, príklad 38).",
                                   bt="BT-131", contexts=[ln.label], line=v.line, segment=v.segment))
                break

    for ln in lines:
        for bt in ("BT-146", "BT-148"):
            p = _num(_first(ln, bt))
            if p is not None and p < 0:
                v = _first(ln, bt)
                out.append(finding("warning", "DOC-NEGATIVE-PRICE",
                                   f"Záporná cena {v.value} – Peppol / EN 16931 vyžaduje cenu vždy kladnou "
                                   "(BR-27, BR-28).",
                                   hint="Znaménko patří na množství (BT-129) a částku řádku (BT-131), cena zůstává "
                                        "kladná (Peppol BIS Billing 3.0, kap. 5.6.2). Pro vrácení nebo storno je "
                                        "bezpečnější dobropis 381 s kladnými částkami a odkazem BT-25.",
                                   bt=bt, contexts=[ln.label], line=v.line, segment=v.segment))
                break

    if code in PARTIAL and not (doc.values.get("BT-12") or bt25):
        out.append(finding("info", "DOC-PARTIAL",
                           f"{name or code}: u dílčích a konečných faktur se doporučuje odkaz na smlouvu (BT-12) "
                           f"nebo na předchozí dílčí faktury (BT-25).", **loc))

    total = _num(_first(doc, "BT-112"))
    if total is not None and total < 0 and sem.doc_kind == "Invoice":
        v = _first(doc, "BT-112")
        vloc = dict(bt="BT-112", contexts=["doklad"], line=v.line, segment=v.segment)
        if code == "380":
            out.append(finding("info", "DOC-NEGATIVE",
                               f"Faktura 380 má zápornou celkovou částku {v.value} – nemá jít spíš o dobropis (381)?",
                               hint="Peppol BIS záporné faktury dovoluje (kap. 5.6: příjemce musí umět obě varianty), "
                                    "ale řada odběratelů je odmítá – explicitní dobropis je bezpečnější.", **vloc))
        elif code in ADVANCE:
            out.append(finding("warning", "DOC-NEGATIVE",
                               f"Doklad k záloze ({code}) má zápornou celkovou částku {v.value} – nejsou obrácená "
                               "znaménka?",
                               hint="Zálohový doklad i daňový doklad k přijaté platbě mají být kladné. Vrácení nebo storno "
                                    "zálohy se posílá jako dobropis 381 s kladnými částkami a odkazem BT-25 na původní "
                                    f"doklad ({FAQ_SK}, časť I, príklad 50; Peppol BIS Billing 3.0, kap. 5.6.1).",
                               **vloc))
    return out
