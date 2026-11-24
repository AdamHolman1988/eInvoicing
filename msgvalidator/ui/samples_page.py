"""'Vzory' tab: download synthetic sample documents per document type and format (msgvalidator/samples.py)."""
from __future__ import annotations

import html

from ..samples import FORMATS, SCENARIOS

EN_DESC = {
    "invoice": "Ordinary invoice, 2 lines, 21 % VAT.",
    "credit-note": "Returned goods with a reference to the original invoice (BT-25).",
    "corrected": "Price correction with a reference to the original invoice; SK → SK (Peppol allows 384 only DE–DE or SK–SK).",
    "prepayment": "Prepayment 10 000 + VAT (a payment request; not sent via eFaktúra in Slovakia).",
    "final": "Untaxed prepayment deducted as paid amount (BT-113) and a reference to the prepayment invoice.",
    "tax-advance": "SK → SK, advance payment 1 000 + 23 % VAT received before delivery (SK FA FAQ, part II, no. 22).",
    "advance-credit": "Advance refund: positive amounts and a BT-25 reference to the 388 document; SK → SK.",
    "final-sk": "SK → SK, advance deducted by a negative line (quantity −1, 23 % VAT) with a BT-25 reference to the "
                "388 document (SK FA FAQ, part II, no. 38).",
    "self-billing": "Issued by the buyer (Peppol BIS Self-Billing 3.0).",
    "reverse-charge": "Domestic reverse charge, category AE, 0 %.",
    "intra-eu": "CZ → DE, category K, exempt (VATEX-EU-IC), delivery date and country.",
    "allowance-charge": "5 % discount and freight on document level.",
    "partial": "Partial invoice under a contract (BT-12); DE → DE (Peppol allows 326 only DE–DE).",
}
FMT_EN = {"ubl": "UBL 2.1 (Peppol BIS 3)", "cii": "UN/CEFACT CII", "sbdh": "UBL in Peppol envelope (SBDH)",
          "pdf": "Factur-X / ZUGFeRD PDF (CII)"}

TEXT = {
    "cs": {"title": "Vzory dokladů",
           "lead": "Syntetické vzorové doklady (fiktivní firmy a částky) pro různé typy dokladů. Každý vzor je aritmeticky "
                   "správný a projde oficiálními pravidly Peppol BIS 3 / EN 16931 – hodí se jako ukázka pro klienta, "
                   "k testům převodníků nebo k porovnání s tím, co posílá klient.",
           "type": "Typ dokladu", "code": "Kód", "desc": "Co obsahuje", "dl": "Stáhnout",
           "note": "Self-billing kontroluje validátor jen podle EN 16931 (pravidla Peppol Self-Billing nejsou v aplikaci). "
                   "Factur-X PDF je testovací vzor (prázdná stránka + XML), ne plné PDF/A-3."},
    "en": {"title": "Sample documents",
           "lead": "Synthetic sample documents (fictitious companies and amounts) for different document types. Every sample "
                   "is arithmetically correct and passes the official Peppol BIS 3 / EN 16931 rules – useful as an example "
                   "for a client, for testing converters or for comparing with what a client sends.",
           "type": "Document type", "code": "Code", "desc": "Contents", "dl": "Download",
           "note": "Self-billing is checked against EN 16931 only (Peppol Self-Billing rules are not included). "
                   "The Factur-X PDF is a test sample (blank page + XML), not a full PDF/A-3."},
}


def body(lang: str) -> str:
    t = TEXT["en" if lang == "en" else "cs"]
    rows = []
    for key, (cs, en, code, desc) in SCENARIOS.items():
        btns = " ".join(
            f'<a class="btn" href="/api/sample?type={key}&amp;fmt={f}" download '
            f'title="{html.escape(FMT_EN[f] if lang == "en" else v[0])}">{f.upper()}</a>'
            for f, v in FORMATS.items())
        rows.append(f"<tr><td>{html.escape(en if lang == 'en' else cs)}</td><td><code>{code}</code></td>"
                    f"<td>{html.escape(EN_DESC[key] if lang == 'en' else desc)}</td><td class='dl'>{btns}</td></tr>")
    return (f"<h1>{t['title']}</h1><p class='lead'>{t['lead']}</p>"
            f"<table><thead><tr><th>{t['type']}</th><th>{t['code']}</th><th>{t['desc']}</th><th>{t['dl']}</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table><p class='muted'>{t['note']}</p>")
