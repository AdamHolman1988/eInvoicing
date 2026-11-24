"""Sample documents for different document types – synthetic data, arithmetically consistent, Peppol BIS 3 valid.

A scenario builds the EN 16931 model (BT/BG); writers turn it into UBL (ubl/writer.py), CII (cii/writer.py),
UBL in a Peppol envelope (SBDH) or a Factur-X PDF (CII embedded in a PDF).

    python -m msgvalidator sample --type credit-note --format cii -o vzor.xml
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal

from .semantic.catalog import catalog
from .semantic.model import Context, Semantic, Value

FORMATS = {"ubl": ("UBL 2.1 (Peppol BIS 3)", ".xml"), "cii": ("UN/CEFACT CII", ".xml"),
           "sbdh": ("UBL v Peppol obálce (SBDH)", ".xml"), "pdf": ("Factur-X / ZUGFeRD PDF (CII)", ".pdf")}

BILLING = ("urn:fdc:peppol.eu:2017:poacc:billing:01:1.0",
           "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0")
SELFBILLING = ("urn:fdc:peppol.eu:2017:poacc:selfbilling:01:1.0",
               "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:selfbilling:3.0")

# id: (Czech label, English label, BT-3, short description)
SCENARIOS = {
    "invoice": ("Faktura", "Invoice", "380", "Běžná faktura, 2 řádky, DPH 21 %."),
    "credit-note": ("Dobropis", "Credit note", "381", "Vrácení zboží s odkazem na původní fakturu (BT-25)."),
    "corrected": ("Opravná faktura", "Corrected invoice", "384",
                  "Oprava ceny s odkazem na původní fakturu; SK → SK (Peppol povoluje 384 jen DE–DE a SK–SK)."),
    "prepayment": ("Zálohová faktura", "Prepayment invoice", "386",
                   "Záloha 10 000 + DPH (výzva k platbě; na Slovensku se přes eFaktúru neposílá)."),
    "final": ("Konečná faktura po záloze", "Final invoice after prepayment", "380",
              "Odečtená nezdaněná záloha jako zaplaceno předem (BT-113) a odkaz na zálohovou fakturu."),
    "tax-advance": ("Daňový doklad k přijaté platbě", "Tax document for a received payment", "388",
                    "SK → SK, přijatá záloha 1 000 + DPH 23 % před dodáním (FAQ FS SR, časť II, príklad 22)."),
    "advance-credit": ("Dobropis k dokladu k přijaté platbě", "Credit note for a received-payment document", "381",
                       "Vrácení zálohy: kladné částky a odkaz BT-25 na doklad 388; SK → SK."),
    "final-sk": ("Konečná faktura po zdaněné záloze", "Final invoice after a taxed advance", "380",
                 "SK → SK, záloha odečtená záporným řádkem (množství −1, DPH 23 %) s odkazem BT-25 na doklad 388 "
                 "(FAQ FS SR, časť II, príklad 38)."),
    "self-billing": ("Self-billing", "Self-billing", "389",
                     "Fakturu vystavuje odběratel (Peppol BIS Self-Billing 3.0; kontroluje se jádro EN 16931)."),
    "reverse-charge": ("Přenesená daňová povinnost", "Domestic reverse charge", "380",
                       "Tuzemské PDP, kategorie AE, sazba 0 %."),
    "intra-eu": ("Dodání do jiného státu EU", "Intra-community supply", "380",
                 "CZ → DE, kategorie K, osvobozeno (VATEX-EU-IC), datum a země dodání."),
    "allowance-charge": ("Sleva a přirážka na dokladu", "Document allowance and charge", "380",
                         "Sleva 5 % a dopravné na úrovni dokladu."),
    "partial": ("Dílčí faktura", "Partial invoice", "326",
                "Dílčí plnění podle smlouvy (BT-12); DE → DE (Peppol povoluje 326 jen DE–DE)."),
}

# Slovak domestic scenarios (SK seller and buyer, EUR, 23 %)
SK_SCENARIOS = {"corrected", "tax-advance", "advance-credit", "final-sk"}

D2 = Decimal("0.01")


def _q(x) -> Decimal:
    return Decimal(x).quantize(D2, rounding=ROUND_HALF_UP)


def gln(base12: str) -> str:
    s = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(base12)))
    return base12 + str((10 - s % 10) % 10)


SELLER = {"name": "Vzorový dodavatel s.r.o.", "gln": gln("859000000001"), "ico": "12345679", "vat": "CZ12345679",
          "street": "Vzorová 1", "city": "Praha", "zip": "11000", "country": "CZ",
          "iban": "CZ6508000000192000145399"}
BUYER = {"name": "Vzorový odběratel a.s.", "gln": gln("859000000002"), "ico": "87654321", "vat": "CZ87654321",
         "street": "Testovací 2", "city": "Brno", "zip": "60200", "country": "CZ"}
SELLER_SK = {"name": "Vzorový dodávateľ s.r.o.", "gln": gln("858000000001"), "ico": "12345678", "vat": "SK2020123456",
             "street": "Vzorová 1", "city": "Bratislava", "zip": "81101", "country": "SK",
             "iban": "SK3112000000198742637541"}
BUYER_SK = {"name": "Vzorový odberateľ a.s.", "gln": gln("858000000002"), "ico": "87654322", "vat": "SK2020654321",
            "street": "Testovacia 2", "city": "Košice", "zip": "04001", "country": "SK"}
SELLER_DE = {"name": "Musterlieferant GmbH", "gln": gln("400000000004"), "ico": None, "vat": "DE987654321",
             "street": "Lieferweg 4", "city": "Hamburg", "zip": "20095", "country": "DE",
             "iban": "DE89370400440532013000"}
BUYER_DE = {"name": "Musterkunde GmbH", "gln": gln("400000000003"), "ico": None, "vat": "DE123456789",
            "street": "Musterstraße 3", "city": "Berlin", "zip": "10115", "country": "DE"}

ITEMS = [("Vzorové zboží A", gln("859000000010"), "A-001", Decimal("10"), "H87", Decimal("125.00")),
         ("Vzorové zboží B", gln("859000000011"), "B-002", Decimal("3"), "H87", Decimal("99.90"))]


class _B:
    def __init__(self):
        self.doc = Context(None, "doklad", None)
        self.groups: dict[str, list[Context]] = {"BG-20": [], "BG-21": [], "BG-23": [], "BG-25": []}

    def put(self, ctx: Context, bt: str, value, scheme: str | None = None):
        if value is not None and value != "":
            ctx.add(Value(bt, str(value), how="explicit", scheme=scheme, segment="vzor"))


def _party(b: _B, p: dict, role: str):
    """role 'seller' (BG-4) or 'buyer' (BG-7)."""
    bts = {"seller": ("BT-27", "BT-29", "BT-30", "BT-31", "BT-34", "BT-35", "BT-37", "BT-38", "BT-40"),
           "buyer": ("BT-44", "BT-46", "BT-47", "BT-48", "BT-49", "BT-50", "BT-52", "BT-53", "BT-55")}[role]
    name, ident, legal, vat, endpoint, street, city, zipc, country = bts
    b.put(b.doc, name, p["name"])
    b.put(b.doc, ident, p["gln"], "0088")
    b.put(b.doc, legal, p["ico"])
    b.put(b.doc, vat, p["vat"])
    b.put(b.doc, endpoint, p["gln"], "0088")
    b.put(b.doc, street, p["street"])
    b.put(b.doc, city, p["city"])
    b.put(b.doc, zipc, p["zip"])
    b.put(b.doc, country, p["country"])


def build(scenario: str, issue: dt.date | None = None) -> Semantic:
    if scenario not in SCENARIOS:
        raise ValueError(f"Neznámý typ vzoru '{scenario}'. Možnosti: {', '.join(SCENARIOS)}")
    label, _, code, _ = SCENARIOS[scenario]
    issue = issue or dt.date.today()
    b = _B()
    prefix = {"381": "DB", "384": "OF", "386": "ZF", "388": "ZDP", "389": "SB"}.get(code, "FV")
    sk = scenario in SK_SCENARIOS
    process = SELFBILLING if scenario == "self-billing" else BILLING
    b.put(b.doc, "BT-1", f"{prefix}-{issue.year}-0001")
    b.put(b.doc, "BT-2", issue.isoformat())
    b.put(b.doc, "BT-3", code)
    b.put(b.doc, "BT-5", "EUR" if sk or scenario in ("intra-eu", "partial") else "CZK")
    b.put(b.doc, "BT-9", (issue + dt.timedelta(days=14)).isoformat())
    b.put(b.doc, "BT-10", "OBJ-4711")
    b.put(b.doc, "BT-23", process[0])
    b.put(b.doc, "BT-24", process[1])
    b.put(b.doc, "BT-22", f"Vzorový doklad ({label}) – fiktivní data.")
    seller, buyer = {"intra-eu": (SELLER, BUYER_DE), "partial": (SELLER_DE, BUYER_DE)}.get(
        scenario, (SELLER_SK, BUYER_SK) if sk else (SELLER, BUYER))
    _party(b, seller, "seller")
    b.put(b.doc, "BT-41", "Jana Vzorová")
    b.put(b.doc, "BT-42", "+420 123 456 789")
    b.put(b.doc, "BT-43", "fakturace@example.com")
    _party(b, buyer, "buyer")
    b.put(b.doc, "BT-81", "30")
    b.put(b.doc, "BT-84", seller["iban"])
    b.put(b.doc, "BT-83", f"{issue.year}0001")

    if scenario in ("credit-note", "corrected"):
        b.put(b.doc, "BT-25", f"FV-{issue.year}-0000")
        b.put(b.doc, "BT-26", (issue - dt.timedelta(days=10)).isoformat())
    if scenario == "final":
        b.put(b.doc, "BT-25", f"ZF-{issue.year}-0001")
    if sk:  # SK CIUS: tax point date (date of delivery / of the received payment, § 74 ods. 1 písm. d)
        b.put(b.doc, "BT-7", (issue - dt.timedelta(days=2 if scenario == "tax-advance" else 0)).isoformat())
    if scenario in ("advance-credit", "final-sk"):
        b.put(b.doc, "BT-25", f"ZDP-{issue.year}-0001")
        b.put(b.doc, "BT-26", (issue - dt.timedelta(days=10)).isoformat())
    if scenario == "partial":
        b.put(b.doc, "BT-12", "SML-2026-15")

    # lines
    cat, rate, exemption = "S", Decimal("23" if sk else {"partial": "19"}.get(scenario, "21")), (None, None)
    if scenario == "reverse-charge":
        cat, rate, exemption = "AE", Decimal("0"), ("Daň odvede zákazník (přenesená daňová povinnost).", "VATEX-EU-AE")
    if scenario == "intra-eu":
        cat, rate, exemption = "K", Decimal("0"), ("Dodání zboží do jiného členského státu – osvobozeno.", "VATEX-EU-IC")
        b.put(b.doc, "BT-72", issue.isoformat())
        b.put(b.doc, "BT-80", "DE")
    items = ITEMS
    if scenario == "prepayment":
        items = [("Záloha na objednávku OBJ-4711", None, "ZAL", Decimal("1"), "C62", Decimal("10000.00"))]
    elif scenario in ("tax-advance", "advance-credit"):
        what = "Prijatá platba – záloha" if scenario == "tax-advance" else "Vrátenie zálohy"
        items = [(f"{what} na objednávku OBJ-4711", None, "ZAL", Decimal("1"), "C62", Decimal("1000.00"))]
    elif scenario == "final-sk":
        items = ITEMS + [(f"Odpočet zálohy – daňový doklad ZDP-{issue.year}-0001", None, "ZAL", Decimal("-1"), "C62",
                          Decimal("1000.00"))]
    elif scenario == "credit-note":
        items = [("Vzorové zboží A – vráceno", ITEMS[0][1], "A-001", Decimal("2"), "H87", Decimal("125.00"))]
    elif scenario == "corrected":
        items = [("Vzorové zboží A – oprava ceny", ITEMS[0][1], "A-001", Decimal("10"), "H87", Decimal("120.00"))]
    elif scenario == "partial":
        items = [("Dílčí plnění – etapa 1 ze 3", None, "ETAPA-1", Decimal("1"), "C62", Decimal("50000.00"))]

    line_total = Decimal("0")
    for n, (name, gtin, sku, qty, unit, price) in enumerate(items, 1):
        ln = Context("BG-25", f"řádek {n}", None)
        amount = _q(qty * price)
        line_total += amount
        b.put(ln, "BT-126", n)
        b.put(ln, "BT-129", qty)
        b.put(ln, "BT-130", unit)
        b.put(ln, "BT-131", amount)
        b.put(ln, "BT-146", price)
        b.put(ln, "BT-151", cat)
        b.put(ln, "BT-152", rate)
        b.put(ln, "BT-153", name)
        b.put(ln, "BT-155", sku)
        if gtin:
            b.put(ln, "BT-157", gtin, "0160")
        b.groups["BG-25"].append(ln)

    allowances = charges = Decimal("0")
    if scenario == "allowance-charge":
        a = Context("BG-20", "sleva dokladu #1", None)
        allowances = _q(line_total * Decimal("0.05"))
        for bt, v in (("BT-92", allowances), ("BT-93", line_total), ("BT-94", "5"), ("BT-95", cat), ("BT-96", rate),
                      ("BT-97", "Množstevní sleva"), ("BT-98", "95")):
            b.put(a, bt, v)
        b.groups["BG-20"].append(a)
        c = Context("BG-21", "přirážka dokladu #1", None)
        charges = Decimal("150.00")
        for bt, v in (("BT-99", charges), ("BT-102", cat), ("BT-103", rate), ("BT-104", "Dopravné"), ("BT-105", "FC")):
            b.put(c, bt, v)
        b.groups["BG-21"].append(c)

    basis = line_total - allowances + charges
    vat = _q(basis * rate / 100)
    t = Context("BG-23", f"DPH {rate} % {cat}", None)
    for bt, v in (("BT-116", basis), ("BT-117", vat), ("BT-118", cat), ("BT-119", rate),
                  ("BT-120", exemption[0]), ("BT-121", exemption[1])):
        b.put(t, bt, v)
    b.groups["BG-23"].append(t)

    total = basis + vat
    prepaid = Decimal("0")
    if scenario == "final":
        prepaid = Decimal("12100.00")  # 10 000 + 21 % from the prepayment sample
        if prepaid > total:
            prepaid = _q(total / 2)
    for bt, v in (("BT-106", line_total), ("BT-107", allowances if allowances else None),
                  ("BT-108", charges if charges else None), ("BT-109", basis), ("BT-110", vat), ("BT-112", total),
                  ("BT-113", prepaid if prepaid else None), ("BT-115", total - prepaid)):
        b.put(b.doc, bt, v)

    cat_ = catalog()
    repeating = {}
    for tid in cat_.order:
        for anc in cat_.ancestors(tid):
            if anc in b.groups:
                repeating[tid] = anc
                break
    return Semantic(source_format=f"vzor: {label}", mapping_id="sample", document=b.doc, groups=b.groups,
                    mapped_terms=set(), rules={}, repeating=repeating,
                    doc_kind="CreditNote" if code == "381" else "Invoice")


def ubl(sem: Semantic) -> bytes:
    from .ubl.writer import write
    return write(sem).xml


def cii(sem: Semantic) -> bytes:
    from .cii.writer import write
    return write(sem)


def sbdh(sem: Semantic) -> bytes:
    from lxml import etree
    payload = etree.fromstring(ubl(sem))
    kind = etree.QName(payload).localname
    ns = etree.QName(payload).namespace
    d = sem.document.values

    def v(bt):
        x = d.get(bt)
        return x[0] if x else None
    sender, receiver = v("BT-34"), v("BT-49")
    SH = "http://www.unece.org/cefact/namespaces/StandardBusinessDocumentHeader"
    root = etree.Element(f"{{{SH}}}StandardBusinessDocument", nsmap={"sh": SH})
    h = etree.SubElement(root, f"{{{SH}}}StandardBusinessDocumentHeader")

    def sub(parent, tag, text=None, **attrs):
        e = etree.SubElement(parent, f"{{{SH}}}{tag}", **attrs)
        if text is not None:
            e.text = text
        return e
    sub(h, "HeaderVersion", "1.0")
    sub(sub(h, "Sender"), "Identifier", f"{sender.scheme}:{sender.value}", Authority="iso6523-actorid-upis")
    sub(sub(h, "Receiver"), "Identifier", f"{receiver.scheme}:{receiver.value}", Authority="iso6523-actorid-upis")
    di = sub(h, "DocumentIdentification")
    sub(di, "Standard", ns)
    sub(di, "TypeVersion", "2.1")
    sub(di, "InstanceIdentifier", str(uuid.uuid4()))
    sub(di, "Type", kind)
    sub(di, "CreationDateAndTime", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    bs = sub(h, "BusinessScope")
    for typ, inst, ident in (("DOCUMENTID", f"{ns}::{kind}##{v('BT-24').value}::2.1", "busdox-docid-qns"),
                             ("PROCESSID", v("BT-23").value, "cenbii-procid-ubl"),
                             ("COUNTRY_C1", v("BT-40").value, None)):
        s = sub(bs, "Scope")
        sub(s, "Type", typ)
        sub(s, "InstanceIdentifier", inst)
        if ident:
            sub(s, "Identifier", ident)
    root.append(payload)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


XMP = """<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
 <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"><pdfaid:part>3</pdfaid:part><pdfaid:conformance>B</pdfaid:conformance></rdf:Description>
 <rdf:Description rdf:about="" xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
  <fx:DocumentType>INVOICE</fx:DocumentType><fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>
  <fx:Version>1.0</fx:Version><fx:ConformanceLevel>EN 16931</fx:ConformanceLevel>
 </rdf:Description>
</rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>"""


def pdf(sem: Semantic) -> bytes:
    """Factur-X 1.0 (EN 16931 profile): blank page + CII attachment + XMP. Not a full PDF/A-3 – a test sample."""
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    w.add_attachment("factur-x.xml", cii(_facturx(sem)))
    meta = DecodedStreamObject()
    meta.set_data(XMP.encode("utf-8"))
    meta.update({NameObject("/Type"): NameObject("/Metadata"), NameObject("/Subtype"): NameObject("/XML")})
    w._root_object[NameObject("/Metadata")] = w._add_object(meta)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _facturx(sem: Semantic) -> Semantic:
    """Factur-X EN 16931 profile: guideline 'urn:cen.eu:en16931:2017' instead of the Peppol customization."""
    sem.document.values["BT-24"] = [Value("BT-24", "urn:cen.eu:en16931:2017", segment="vzor")]
    return sem


def render(scenario: str, fmt: str) -> tuple[bytes, str]:
    """-> (file content, suggested file name)."""
    if fmt not in FORMATS:
        raise ValueError(f"Neznámý formát '{fmt}'. Možnosti: {', '.join(FORMATS)}")
    sem = build(scenario)
    data = {"ubl": ubl, "cii": cii, "sbdh": sbdh, "pdf": pdf}[fmt](sem)
    return data, f"vzor_{scenario}_{fmt}{FORMATS[fmt][1]}"
