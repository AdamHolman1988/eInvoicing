"""Semantic model (EN 16931 BTs) -> UN/CEFACT CII D16B CrossIndustryInvoice.

Covers the terms used by the sample generator (msgvalidator/samples.py) and the common core of EN 16931:
document, parties with addresses / identifiers / tax registrations / endpoints, delivery, payment, VAT breakdown,
document and line allowances / charges, preceding invoice, totals. Element order follows the CII D16B XSD.
"""
from __future__ import annotations

from lxml import etree

from ..semantic.model import Context, Semantic

RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
QDT = "urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
NSMAP = {"rsm": RSM, "ram": RAM, "udt": UDT, "qdt": QDT}
URI = {"rsm": RSM, "ram": RAM, "udt": UDT, "qdt": QDT}


def _v(ctx: Context, bt: str):
    vals = ctx.values.get(bt)
    return vals[0] if vals else None


class _W:
    def __init__(self, sem: Semantic):
        self.sem = sem
        cur = _v(sem.document, "BT-5")
        self.cur = cur.value if cur else None

    @staticmethod
    def el(parent, tag: str, text=None, **attrs):
        ns, local = tag.split(":")
        e = etree.SubElement(parent, f"{{{URI[ns]}}}{local}")
        if text is not None:
            e.text = str(text)
        for k, v in attrs.items():
            if v:
                e.set(k, v)
        return e

    def put(self, parent, tag, ctx, bt, scheme_attr=None, **attrs):
        v = _v(ctx, bt)
        if v is None:
            return None
        if scheme_attr and v.scheme:
            attrs[scheme_attr] = v.scheme
        return self.el(parent, tag, v.value, **attrs)

    def date(self, parent, tag, ctx, bt, inner="udt:DateTimeString"):
        v = _v(ctx, bt)
        if v is None:
            return None
        w = self.el(parent, tag)
        self.el(w, inner, v.value.replace("-", "")[:8], format="102")
        return w

    def has(self, ctx, *bts):
        return any(_v(ctx, b) for b in bts)

    # ------------------------------------------------------------------ parts
    def party(self, parent, tag, d, bts):
        """bts: name, id, legal id, vat id, endpoint, street, city, zip, country, (tax id FC)"""
        name, ident, legal, vat, endpoint, street, city, zipc, country, tax = bts
        p = self.el(parent, tag)
        idv = _v(d, ident) if ident else None
        if idv is not None:
            if idv.scheme:
                self.el(p, "ram:GlobalID", idv.value, schemeID=idv.scheme)
            else:
                self.el(p, "ram:ID", idv.value)
        self.put(p, "ram:Name", d, name)
        if legal and _v(d, legal):
            lo = self.el(p, "ram:SpecifiedLegalOrganization")
            self.put(lo, "ram:ID", d, legal, "schemeID")
        if tag == "ram:SellerTradeParty" and self.has(d, "BT-41", "BT-42", "BT-43"):
            c = self.el(p, "ram:DefinedTradeContact")
            self.put(c, "ram:PersonName", d, "BT-41")
            if _v(d, "BT-42"):
                self.put(self.el(c, "ram:TelephoneUniversalCommunication"), "ram:CompleteNumber", d, "BT-42")
            if _v(d, "BT-43"):
                self.put(self.el(c, "ram:EmailURIUniversalCommunication"), "ram:URIID", d, "BT-43")
        if self.has(d, street, city, zipc, country):
            a = self.el(p, "ram:PostalTradeAddress")
            self.put(a, "ram:PostcodeCode", d, zipc)
            self.put(a, "ram:LineOne", d, street)
            self.put(a, "ram:CityName", d, city)
            self.put(a, "ram:CountryID", d, country)
        if endpoint and _v(d, endpoint):
            u = self.el(p, "ram:URIUniversalCommunication")
            self.put(u, "ram:URIID", d, endpoint, "schemeID")
        if vat and _v(d, vat):
            self.el(self.el(p, "ram:SpecifiedTaxRegistration"), "ram:ID", _v(d, vat).value, schemeID="VA")
        if tax and _v(d, tax):
            self.el(self.el(p, "ram:SpecifiedTaxRegistration"), "ram:ID", _v(d, tax).value, schemeID="FC")

    def allowance(self, parent, ctx, charge: bool, bts):
        amount, base, pct, cat, rate, reason, code = bts
        ac = self.el(parent, "ram:SpecifiedTradeAllowanceCharge")
        self.el(self.el(ac, "ram:ChargeIndicator"), "udt:Indicator", "true" if charge else "false")
        self.put(ac, "ram:CalculationPercent", ctx, pct) if pct else None
        self.put(ac, "ram:BasisAmount", ctx, base) if base else None
        self.put(ac, "ram:ActualAmount", ctx, amount)
        self.put(ac, "ram:ReasonCode", ctx, code)
        self.put(ac, "ram:Reason", ctx, reason)
        if cat and _v(ctx, cat):
            t = self.el(ac, "ram:CategoryTradeTax")
            self.el(t, "ram:TypeCode", "VAT")
            self.put(t, "ram:CategoryCode", ctx, cat)
            self.put(t, "ram:RateApplicablePercent", ctx, rate)

    def line(self, parent, ln: Context):
        li = self.el(parent, "ram:IncludedSupplyChainTradeLineItem")
        doc = self.el(li, "ram:AssociatedDocumentLineDocument")
        self.put(doc, "ram:LineID", ln, "BT-126")
        if _v(ln, "BT-127"):
            self.el(self.el(doc, "ram:IncludedNote"), "ram:Content", _v(ln, "BT-127").value)
        pr = self.el(li, "ram:SpecifiedTradeProduct")
        self.put(pr, "ram:GlobalID", ln, "BT-157", "schemeID")
        self.put(pr, "ram:SellerAssignedID", ln, "BT-155")
        self.put(pr, "ram:BuyerAssignedID", ln, "BT-156")
        self.put(pr, "ram:Name", ln, "BT-153")
        self.put(pr, "ram:Description", ln, "BT-154")
        ag = self.el(li, "ram:SpecifiedLineTradeAgreement")
        if _v(ln, "BT-148"):
            g = self.el(ag, "ram:GrossPriceProductTradePrice")
            self.put(g, "ram:ChargeAmount", ln, "BT-148")
        np = self.el(ag, "ram:NetPriceProductTradePrice")
        self.put(np, "ram:ChargeAmount", ln, "BT-146")
        if _v(ln, "BT-149"):
            self.put(np, "ram:BasisQuantity", ln, "BT-149", unitCode=(_v(ln, "BT-150") or _v(ln, "BT-130")).value)
        dl = self.el(li, "ram:SpecifiedLineTradeDelivery")
        u = _v(ln, "BT-130")
        self.put(dl, "ram:BilledQuantity", ln, "BT-129", unitCode=u.value if u else None)
        st = self.el(li, "ram:SpecifiedLineTradeSettlement")
        t = self.el(st, "ram:ApplicableTradeTax")
        self.el(t, "ram:TypeCode", "VAT")
        self.put(t, "ram:CategoryCode", ln, "BT-151")
        self.put(t, "ram:RateApplicablePercent", ln, "BT-152")
        if self.has(ln, "BT-134", "BT-135"):
            per = self.el(st, "ram:BillingSpecifiedPeriod")
            self.date(per, "ram:StartDateTime", ln, "BT-134")
            self.date(per, "ram:EndDateTime", ln, "BT-135")
        sm = self.el(st, "ram:SpecifiedTradeSettlementLineMonetarySummation")
        self.put(sm, "ram:LineTotalAmount", ln, "BT-131")

    # ------------------------------------------------------------------ document
    def write(self) -> bytes:
        d = self.sem.document
        root = etree.Element(f"{{{RSM}}}CrossIndustryInvoice", nsmap=NSMAP)
        ctx = self.el(root, "rsm:ExchangedDocumentContext")
        if _v(d, "BT-23"):
            self.put(self.el(ctx, "ram:BusinessProcessSpecifiedDocumentContextParameter"), "ram:ID", d, "BT-23")
        self.put(self.el(ctx, "ram:GuidelineSpecifiedDocumentContextParameter"), "ram:ID", d, "BT-24")

        ed = self.el(root, "rsm:ExchangedDocument")
        self.put(ed, "ram:ID", d, "BT-1")
        self.put(ed, "ram:TypeCode", d, "BT-3")
        self.date(ed, "ram:IssueDateTime", d, "BT-2")
        for n in d.values.get("BT-22", []):
            self.el(self.el(ed, "ram:IncludedNote"), "ram:Content", n.value)

        tx = self.el(root, "rsm:SupplyChainTradeTransaction")
        for ln in self.sem.groups.get("BG-25", []):
            self.line(tx, ln)

        ag = self.el(tx, "ram:ApplicableHeaderTradeAgreement")
        self.put(ag, "ram:BuyerReference", d, "BT-10")
        self.party(ag, "ram:SellerTradeParty", d,
                   ("BT-27", "BT-29", "BT-30", "BT-31", "BT-34", "BT-35", "BT-37", "BT-38", "BT-40", "BT-32"))
        self.party(ag, "ram:BuyerTradeParty", d,
                   ("BT-44", "BT-46", "BT-47", "BT-48", "BT-49", "BT-50", "BT-52", "BT-53", "BT-55", None))
        if _v(d, "BT-14"):
            self.put(self.el(ag, "ram:SellerOrderReferencedDocument"), "ram:IssuerAssignedID", d, "BT-14")
        if _v(d, "BT-13"):
            self.put(self.el(ag, "ram:BuyerOrderReferencedDocument"), "ram:IssuerAssignedID", d, "BT-13")
        if _v(d, "BT-12"):
            self.put(self.el(ag, "ram:ContractReferencedDocument"), "ram:IssuerAssignedID", d, "BT-12")

        dl = self.el(tx, "ram:ApplicableHeaderTradeDelivery")
        if _v(d, "BT-80"):
            st = self.el(dl, "ram:ShipToTradeParty")
            self.put(self.el(st, "ram:PostalTradeAddress"), "ram:CountryID", d, "BT-80")
        if _v(d, "BT-72"):
            self.date(self.el(dl, "ram:ActualDeliverySupplyChainEvent"), "ram:OccurrenceDateTime", d, "BT-72")

        s = self.el(tx, "ram:ApplicableHeaderTradeSettlement")
        self.put(s, "ram:PaymentReference", d, "BT-83")
        self.put(s, "ram:TaxCurrencyCode", d, "BT-6")
        self.put(s, "ram:InvoiceCurrencyCode", d, "BT-5")
        if _v(d, "BT-81"):
            pm = self.el(s, "ram:SpecifiedTradeSettlementPaymentMeans")
            self.put(pm, "ram:TypeCode", d, "BT-81")
            if _v(d, "BT-84"):
                self.put(self.el(pm, "ram:PayeePartyCreditorFinancialAccount"), "ram:IBANID", d, "BT-84")
        for t in self.sem.groups.get("BG-23", []):
            tt = self.el(s, "ram:ApplicableTradeTax")
            self.put(tt, "ram:CalculatedAmount", t, "BT-117")
            self.el(tt, "ram:TypeCode", "VAT")
            self.put(tt, "ram:ExemptionReason", t, "BT-120")
            self.put(tt, "ram:BasisAmount", t, "BT-116")
            self.put(tt, "ram:CategoryCode", t, "BT-118")
            self.put(tt, "ram:ExemptionReasonCode", t, "BT-121")
            if _v(d, "BT-7"):
                self.date(tt, "ram:TaxPointDate", d, "BT-7", inner="udt:DateString")
            self.put(tt, "ram:RateApplicablePercent", t, "BT-119")
        if self.has(d, "BT-73", "BT-74"):
            per = self.el(s, "ram:BillingSpecifiedPeriod")
            self.date(per, "ram:StartDateTime", d, "BT-73")
            self.date(per, "ram:EndDateTime", d, "BT-74")
        for a in self.sem.groups.get("BG-20", []):
            self.allowance(s, a, False, ("BT-92", "BT-93", "BT-94", "BT-95", "BT-96", "BT-97", "BT-98"))
        for c in self.sem.groups.get("BG-21", []):
            self.allowance(s, c, True, ("BT-99", "BT-100", "BT-101", "BT-102", "BT-103", "BT-104", "BT-105"))
        if self.has(d, "BT-9", "BT-20"):
            pt = self.el(s, "ram:SpecifiedTradePaymentTerms")
            self.put(pt, "ram:Description", d, "BT-20")
            self.date(pt, "ram:DueDateDateTime", d, "BT-9")
        sm = self.el(s, "ram:SpecifiedTradeSettlementHeaderMonetarySummation")
        self.put(sm, "ram:LineTotalAmount", d, "BT-106")
        self.put(sm, "ram:ChargeTotalAmount", d, "BT-108")
        self.put(sm, "ram:AllowanceTotalAmount", d, "BT-107")
        self.put(sm, "ram:TaxBasisTotalAmount", d, "BT-109")
        self.put(sm, "ram:TaxTotalAmount", d, "BT-110", currencyID=self.cur)
        self.put(sm, "ram:GrandTotalAmount", d, "BT-112")
        self.put(sm, "ram:TotalPrepaidAmount", d, "BT-113")
        self.put(sm, "ram:DuePayableAmount", d, "BT-115")
        if _v(d, "BT-25"):
            r = self.el(s, "ram:InvoiceReferencedDocument")
            self.put(r, "ram:IssuerAssignedID", d, "BT-25")
            self.date(r, "ram:FormattedIssueDateTime", d, "BT-26", inner="qdt:DateTimeString")
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def write(sem: Semantic) -> bytes:
    return _W(sem).write()
