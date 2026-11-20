"""Semantic model (EN 16931 BTs) -> Peppol BIS 3 UBL 2.1 Invoice / CreditNote ("virtual UBL").

Used to run the official Schematron rules (CEN + Peppol) on non-XML input such as EDIFACT.
Element order follows the UBL 2.1 XSD. Every written element remembers the business term and the
source value it came from, so rule findings can point back to the original EDIFACT segment.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from ..semantic.model import Context, Semantic, Value

CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
ROOT_NS = {"Invoice": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
           "CreditNote": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"}


@dataclass
class VirtualDoc:
    xml: bytes
    kind: str
    provenance: dict[str, tuple[str, Value]] = field(default_factory=dict)  # element path -> (BT, value)
    notes: list[str] = field(default_factory=list)  # converter assumptions applied while writing


class _W:
    def __init__(self, sem: Semantic):
        self.sem = sem
        self.kind = sem.doc_kind
        self.cur = self._v(sem.document, "BT-5")
        self.cur = self.cur.value if self.cur else None
        self.prov: dict[etree._Element, tuple[str, Value]] = {}
        self.notes: list[str] = []

    @staticmethod
    def _v(ctx: Context, bt: str) -> Value | None:
        vals = ctx.values.get(bt)
        return vals[0] if vals else None

    def el(self, parent, tag: str):
        ns, local = tag.split(":")
        return etree.SubElement(parent, f"{{{CBC if ns == 'cbc' else CAC}}}{local}")

    def put(self, parent, tag: str, ctx: Context, bt: str, attrs: dict | None = None, amount=False):
        v = self._v(ctx, bt)
        if v is None:
            return None
        e = self.el(parent, tag)
        e.text = v.value
        if amount and self.cur:
            e.set("currencyID", self.cur)
        if v.scheme and tag.endswith(("ID", "EndpointID")):
            e.set("schemeID", v.scheme)
        for k, val in (attrs or {}).items():
            if val:
                e.set(k, val)
        self.prov[e] = (bt, v)
        return e

    @staticmethod
    def _num(v: Value | None):
        from decimal import Decimal, InvalidOperation
        if v is None:
            return None
        try:
            return Decimal(v.value)
        except InvalidOperation:
            return None

    def has(self, ctx: Context, *bts: str) -> bool:
        return any(ctx.has(b) for b in bts)

    def const(self, parent, tag: str, text: str):
        e = self.el(parent, tag)
        e.text = text
        return e

    # ------------------------------------------------------------------ parts
    def address(self, parent, tag, ctx, street, add, city, zip_, sub, country):
        if not self.has(ctx, street, add, city, zip_, sub, country):
            return
        a = self.el(parent, tag)
        self.put(a, "cbc:StreetName", ctx, street)
        self.put(a, "cbc:AdditionalStreetName", ctx, add)
        self.put(a, "cbc:CityName", ctx, city)
        self.put(a, "cbc:PostalZone", ctx, zip_)
        self.put(a, "cbc:CountrySubentity", ctx, sub)
        c = self.el(a, "cac:Country")
        if self.put(c, "cbc:IdentificationCode", ctx, country) is None:
            a.remove(c)

    def party(self, parent, d: Context, endpoint, ident, name, address, vat, taxreg, regname, legal, contact):
        p = self.el(parent, "cac:Party")
        self.put(p, "cbc:EndpointID", d, endpoint)
        if self.has(d, ident):
            self.put(self.el(p, "cac:PartyIdentification"), "cbc:ID", d, ident)
        if self.has(d, name[1]):
            self.put(self.el(p, "cac:PartyName"), "cbc:Name", d, name[1])
        self.address(p, "cac:PostalAddress", d, *address)
        for bt, scheme in ((vat, "VAT"), (taxreg, "TAX")):
            if bt and self.has(d, bt):
                ts = self.el(p, "cac:PartyTaxScheme")
                self.put(ts, "cbc:CompanyID", d, bt)
                self.const(self.el(ts, "cac:TaxScheme"), "cbc:ID", scheme)
        le = self.el(p, "cac:PartyLegalEntity")
        self.put(le, "cbc:RegistrationName", d, name[0])
        self.put(le, "cbc:CompanyID", d, legal)
        if regname:
            self.put(le, "cbc:CompanyLegalForm", d, regname)
        if self.has(d, *contact):
            c = self.el(p, "cac:Contact")
            self.put(c, "cbc:Name", d, contact[0])
            self.put(c, "cbc:Telephone", d, contact[1])
            self.put(c, "cbc:ElectronicMail", d, contact[2])

    def allowance(self, parent, ctx: Context, charge: bool, amount, base, pct, cat, rate, reason, code):
        a = self.el(parent, "cac:AllowanceCharge")
        self.const(a, "cbc:ChargeIndicator", "true" if charge else "false")
        self.put(a, "cbc:AllowanceChargeReasonCode", ctx, code)
        self.put(a, "cbc:AllowanceChargeReason", ctx, reason)
        self.put(a, "cbc:MultiplierFactorNumeric", ctx, pct)
        self.put(a, "cbc:Amount", ctx, amount, amount=True)
        self.put(a, "cbc:BaseAmount", ctx, base, amount=True)
        if cat:
            tc = self.el(a, "cac:TaxCategory")
            self.put(tc, "cbc:ID", ctx, cat)
            self.put(tc, "cbc:Percent", ctx, rate)
            self.const(self.el(tc, "cac:TaxScheme"), "cbc:ID", "VAT")

    def line(self, parent, ln: Context):
        inv = self.kind == "Invoice"
        line = self.el(parent, "cac:InvoiceLine" if inv else "cac:CreditNoteLine")
        self.put(line, "cbc:ID", ln, "BT-126")
        self.put(line, "cbc:Note", ln, "BT-127")
        unit = self._v(ln, "BT-130")
        q = self.put(line, "cbc:InvoicedQuantity" if inv else "cbc:CreditedQuantity", ln, "BT-129",
                     {"unitCode": unit.value if unit else None})
        self.put(line, "cbc:LineExtensionAmount", ln, "BT-131", amount=True)
        if self.has(ln, "BT-134", "BT-135"):
            per = self.el(line, "cac:InvoicePeriod")
            self.put(per, "cbc:StartDate", ln, "BT-134")
            self.put(per, "cbc:EndDate", ln, "BT-135")
        if self.has(ln, "BT-132"):
            self.put(self.el(line, "cac:OrderLineReference"), "cbc:LineID", ln, "BT-132")
        for bg, charge, bts in (("BG-27", False, ("BT-136", "BT-137", "BT-138", "BT-139", "BT-140")),
                                ("BG-28", True, ("BT-141", "BT-142", "BT-143", "BT-144", "BT-145"))):
            for ac in self.sem.groups.get(bg, []):
                if ac.parent is ln:
                    a = self.el(line, "cac:AllowanceCharge")
                    self.const(a, "cbc:ChargeIndicator", "true" if charge else "false")
                    self.put(a, "cbc:AllowanceChargeReasonCode", ac, bts[4])
                    self.put(a, "cbc:AllowanceChargeReason", ac, bts[3])
                    self.put(a, "cbc:MultiplierFactorNumeric", ac, bts[2])
                    self.put(a, "cbc:Amount", ac, bts[0], amount=True)
                    self.put(a, "cbc:BaseAmount", ac, bts[1], amount=True)
        item = self.el(line, "cac:Item")
        self.put(item, "cbc:Description", ln, "BT-154")
        self.put(item, "cbc:Name", ln, "BT-153")
        if self.has(ln, "BT-156"):
            self.put(self.el(item, "cac:BuyersItemIdentification"), "cbc:ID", ln, "BT-156")
        if self.has(ln, "BT-155"):
            self.put(self.el(item, "cac:SellersItemIdentification"), "cbc:ID", ln, "BT-155")
        if self.has(ln, "BT-157"):
            self.put(self.el(item, "cac:StandardItemIdentification"), "cbc:ID", ln, "BT-157")
        if self.has(ln, "BT-159"):
            self.put(self.el(item, "cac:OriginCountry"), "cbc:IdentificationCode", ln, "BT-159")
        tc = self.el(item, "cac:ClassifiedTaxCategory")
        self.put(tc, "cbc:ID", ln, "BT-151")
        self.put(tc, "cbc:Percent", ln, "BT-152")
        self.const(self.el(tc, "cac:TaxScheme"), "cbc:ID", "VAT")
        price = self.el(line, "cac:Price")
        self.put(price, "cbc:PriceAmount", ln, "BT-146", amount=True)
        bq_unit = self._v(ln, "BT-150")
        self.put(price, "cbc:BaseQuantity", ln, "BT-149", {"unitCode": bq_unit.value if bq_unit else None})
        if self.has(ln, "BT-147", "BT-148"):
            ac = self.el(price, "cac:AllowanceCharge")
            self.const(ac, "cbc:ChargeIndicator", "false")
            if self.put(ac, "cbc:Amount", ln, "BT-147", amount=True) is None:
                # gross price without discount: UBL requires Amount – the converter writes 0
                gross, net = self._num(self._v(ln, "BT-148")), self._num(self._v(ln, "BT-146"))
                disc = gross - net if gross is not None and net is not None and gross >= net else 0
                amt = self.el(ac, "cbc:Amount")
                amt.text = f"{disc:.2f}" if disc else "0.00"
                if self.cur:
                    amt.set("currencyID", self.cur)
                self.notes.append(f"{ln.label}: hrubá cena (BT-148) bez slevy z ceny (BT-147) – "
                                  f"konverze doplní slevu {amt.text} (hrubá − čistá cena).")
            self.put(ac, "cbc:BaseAmount", ln, "BT-148", amount=True)

    # ------------------------------------------------------------------ document
    def build(self) -> etree._Element:
        d = self.sem.document
        inv = self.kind == "Invoice"
        root = etree.Element(f"{{{ROOT_NS[self.kind]}}}{self.kind}", nsmap={None: ROOT_NS[self.kind], "cac": CAC, "cbc": CBC})
        self.put(root, "cbc:CustomizationID", d, "BT-24")
        self.put(root, "cbc:ProfileID", d, "BT-23")
        self.put(root, "cbc:ID", d, "BT-1")
        self.put(root, "cbc:IssueDate", d, "BT-2")
        if inv:
            self.put(root, "cbc:DueDate", d, "BT-9")
            self.put(root, "cbc:InvoiceTypeCode", d, "BT-3")
        else:
            self.put(root, "cbc:TaxPointDate", d, "BT-7")
            self.put(root, "cbc:CreditNoteTypeCode", d, "BT-3")
        notes = d.values.get("BT-22", [])
        if notes:
            e = self.el(root, "cbc:Note")
            e.text = " | ".join(v.value for v in notes)
            self.prov[e] = ("BT-22", notes[0])
            if len(notes) > 1:
                self.notes.append(f"BT-22: {len(notes)} poznámek (FTX) spojeno do jedné – Peppol povoluje jen jednu (PEPPOL-EN16931-R002).")
        if inv:
            self.put(root, "cbc:TaxPointDate", d, "BT-7")
        self.put(root, "cbc:DocumentCurrencyCode", d, "BT-5")
        self.put(root, "cbc:TaxCurrencyCode", d, "BT-6")
        self.put(root, "cbc:AccountingCost", d, "BT-19")
        self.put(root, "cbc:BuyerReference", d, "BT-10")
        if self.has(d, "BT-73", "BT-74"):
            per = self.el(root, "cac:InvoicePeriod")
            self.put(per, "cbc:StartDate", d, "BT-73")
            self.put(per, "cbc:EndDate", d, "BT-74")
        if self.has(d, "BT-13", "BT-14"):
            o = self.el(root, "cac:OrderReference")
            if self.put(o, "cbc:ID", d, "BT-13") is None:
                self.const(o, "cbc:ID", "NA")
            self.put(o, "cbc:SalesOrderID", d, "BT-14")
        if self.has(d, "BT-25"):
            br = self.el(self.el(root, "cac:BillingReference"), "cac:InvoiceDocumentReference")
            self.put(br, "cbc:ID", d, "BT-25")
            self.put(br, "cbc:IssueDate", d, "BT-26")
        if self.has(d, "BT-16"):
            self.put(self.el(root, "cac:DespatchDocumentReference"), "cbc:ID", d, "BT-16")
        if self.has(d, "BT-15"):
            self.put(self.el(root, "cac:ReceiptDocumentReference"), "cbc:ID", d, "BT-15")
        if self.has(d, "BT-12"):
            self.put(self.el(root, "cac:ContractDocumentReference"), "cbc:ID", d, "BT-12")

        self.party(self.el(root, "cac:AccountingSupplierParty"), d, "BT-34", "BT-29", ("BT-27", "BT-28"),
                   ("BT-35", "BT-36", "BT-37", "BT-38", "BT-39", "BT-40"), "BT-31", "BT-32", "BT-33", "BT-30",
                   ("BT-41", "BT-42", "BT-43"))
        self.party(self.el(root, "cac:AccountingCustomerParty"), d, "BT-49", "BT-46", ("BT-44", "BT-45"),
                   ("BT-50", "BT-51", "BT-52", "BT-53", "BT-54", "BT-55"), "BT-48", None, None, "BT-47",
                   ("BT-56", "BT-57", "BT-58"))
        if self.has(d, "BT-59"):
            pp = self.el(root, "cac:PayeeParty")
            if self.has(d, "BT-60"):
                self.put(self.el(pp, "cac:PartyIdentification"), "cbc:ID", d, "BT-60")
            self.put(self.el(pp, "cac:PartyName"), "cbc:Name", d, "BT-59")

        if self.has(d, "BT-70", "BT-71", "BT-72", "BT-75", "BT-77", "BT-78", "BT-80"):
            dl = self.el(root, "cac:Delivery")
            self.put(dl, "cbc:ActualDeliveryDate", d, "BT-72")
            if self.has(d, "BT-71", "BT-75", "BT-77", "BT-78", "BT-80"):
                loc = self.el(dl, "cac:DeliveryLocation")
                self.put(loc, "cbc:ID", d, "BT-71")
                self.address(loc, "cac:Address", d, "BT-75", "BT-76", "BT-77", "BT-78", "BT-79", "BT-80")
            if self.has(d, "BT-70"):
                self.put(self.el(self.el(dl, "cac:DeliveryParty"), "cac:PartyName"), "cbc:Name", d, "BT-70")

        if self.has(d, "BT-81", "BT-83", "BT-84"):
            pm = self.el(root, "cac:PaymentMeans")
            self.put(pm, "cbc:PaymentMeansCode", d, "BT-81")
            if not inv:
                self.put(pm, "cbc:PaymentDueDate", d, "BT-9")
            self.put(pm, "cbc:PaymentID", d, "BT-83")
            if self.has(d, "BT-84"):
                fa = self.el(pm, "cac:PayeeFinancialAccount")
                self.put(fa, "cbc:ID", d, "BT-84")
                self.put(fa, "cbc:Name", d, "BT-85")
                if self.has(d, "BT-86"):
                    self.put(self.el(fa, "cac:FinancialInstitutionBranch"), "cbc:ID", d, "BT-86")
        if self.has(d, "BT-20"):
            self.put(self.el(root, "cac:PaymentTerms"), "cbc:Note", d, "BT-20")

        for ctx in self.sem.groups.get("BG-20", []):
            self.allowance(root, ctx, False, "BT-92", "BT-93", "BT-94", "BT-95", "BT-96", "BT-97", "BT-98")
        for ctx in self.sem.groups.get("BG-21", []):
            self.allowance(root, ctx, True, "BT-99", "BT-100", "BT-101", "BT-102", "BT-103", "BT-104", "BT-105")

        tt = self.el(root, "cac:TaxTotal")
        if self.put(tt, "cbc:TaxAmount", d, "BT-110", amount=True) is None:
            pass
        line_rates = {self._num(self._v(ln, "BT-152")) for ln in self.sem.groups.get("BG-25", [])}
        for ctx in self.sem.groups.get("BG-23", []):
            base, tax, rate = (self._num(self._v(ctx, b)) for b in ("BT-116", "BT-117", "BT-119"))
            if not base and not tax and rate not in line_rates:
                self.notes.append(f"BG-23 {ctx.label}: prázdný rozpis DPH (základ i daň 0, žádný řádek s touto sazbou) vynechán.")
                continue
            st = self.el(tt, "cac:TaxSubtotal")
            self.put(st, "cbc:TaxableAmount", ctx, "BT-116", amount=True)
            self.put(st, "cbc:TaxAmount", ctx, "BT-117", amount=True)
            tc = self.el(st, "cac:TaxCategory")
            self.put(tc, "cbc:ID", ctx, "BT-118")
            self.put(tc, "cbc:Percent", ctx, "BT-119")
            self.put(tc, "cbc:TaxExemptionReasonCode", ctx, "BT-121")
            self.put(tc, "cbc:TaxExemptionReason", ctx, "BT-120")
            self.const(self.el(tc, "cac:TaxScheme"), "cbc:ID", "VAT")

        lmt = self.el(root, "cac:LegalMonetaryTotal")
        for tag, bt in (("LineExtensionAmount", "BT-106"), ("TaxExclusiveAmount", "BT-109"),
                        ("TaxInclusiveAmount", "BT-112"), ("AllowanceTotalAmount", "BT-107"),
                        ("ChargeTotalAmount", "BT-108"), ("PrepaidAmount", "BT-113"),
                        ("PayableRoundingAmount", "BT-114"), ("PayableAmount", "BT-115")):
            self.put(lmt, f"cbc:{tag}", d, bt, amount=True)

        for ln in self.sem.groups.get("BG-25", []):
            self.line(root, ln)
        return root


def write(sem: Semantic) -> VirtualDoc:
    w = _W(sem)
    root = w.build()
    tree = etree.ElementTree(root)
    prov = {tree.getpath(e): p for e, p in w.prov.items()}
    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    return VirtualDoc(xml, w.kind, prov, w.notes)


def provenance_for(vdoc: VirtualDoc, line: int | None):
    """(BT, Value) for the element on a given line of the virtual document (or its nearest ancestor)."""
    if line is None:
        return None
    tree = etree.ElementTree(etree.fromstring(vdoc.xml))
    for e in tree.iter():
        if e.sourceline == line:
            p = vdoc.provenance.get(tree.getpath(e))
            if p:
                return p
            # container element (e.g. LegalMonetaryTotal): first descendant with a source
            for d in e.iterdescendants():
                p = vdoc.provenance.get(tree.getpath(d))
                if p and p[1].line:
                    return p
            node = e.getparent()
            while node is not None:
                p = vdoc.provenance.get(tree.getpath(node))
                if p:
                    return p
                node = node.getparent()
            return None
    return None
