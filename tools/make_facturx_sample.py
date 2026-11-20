"""Synthetic Factur-X / ZUGFeRD test PDFs (fictitious data) for tests/samples/pdf.

    python tools/make_facturx_sample.py
"""
import pathlib

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "samples" / "pdf"

CII = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
 xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
 xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
 xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100">
 <rsm:ExchangedDocumentContext>
  <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>{guideline}</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
 </rsm:ExchangedDocumentContext>
 <rsm:ExchangedDocument>
  <ram:ID>FX-2026-001</ram:ID><ram:TypeCode>380</ram:TypeCode>
  <ram:IssueDateTime><udt:DateTimeString format="102">20261101</udt:DateTimeString></ram:IssueDateTime>
 </rsm:ExchangedDocument>
 <rsm:SupplyChainTradeTransaction>
  <ram:IncludedSupplyChainTradeLineItem>
   <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID></ram:AssociatedDocumentLineDocument>
   <ram:SpecifiedTradeProduct><ram:Name>Testovací zboží</ram:Name></ram:SpecifiedTradeProduct>
   <ram:SpecifiedLineTradeAgreement>
    <ram:NetPriceProductTradePrice><ram:ChargeAmount>10.00</ram:ChargeAmount></ram:NetPriceProductTradePrice>
   </ram:SpecifiedLineTradeAgreement>
   <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="H87">2</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
   <ram:SpecifiedLineTradeSettlement>
    <ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax>
    <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>20.00</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
   </ram:SpecifiedLineTradeSettlement>
  </ram:IncludedSupplyChainTradeLineItem>
  <ram:ApplicableHeaderTradeAgreement>
   <ram:BuyerReference>REF-1</ram:BuyerReference>
   <ram:SellerTradeParty><ram:Name>Verkäufer Test GmbH</ram:Name>
    <ram:PostalTradeAddress><ram:PostcodeCode>10115</ram:PostcodeCode><ram:LineOne>Teststraße 1</ram:LineOne><ram:CityName>Berlin</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
    <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">DE123456789</ram:ID></ram:SpecifiedTaxRegistration>
   </ram:SellerTradeParty>
   <ram:BuyerTradeParty><ram:Name>Käufer Test AG</ram:Name>
    <ram:PostalTradeAddress><ram:PostcodeCode>80331</ram:PostcodeCode><ram:LineOne>Musterweg 2</ram:LineOne><ram:CityName>München</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
   </ram:BuyerTradeParty>
  </ram:ApplicableHeaderTradeAgreement>
  <ram:ApplicableHeaderTradeDelivery/>
  <ram:ApplicableHeaderTradeSettlement>
   <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
   <ram:ApplicableTradeTax><ram:CalculatedAmount>3.80</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount>20.00</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>19</ram:RateApplicablePercent></ram:ApplicableTradeTax>
   <ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">20261201</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
   <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    <ram:LineTotalAmount>20.00</ram:LineTotalAmount><ram:TaxBasisTotalAmount>20.00</ram:TaxBasisTotalAmount>
    <ram:TaxTotalAmount currencyID="EUR">3.80</ram:TaxTotalAmount><ram:GrandTotalAmount>23.80</ram:GrandTotalAmount>
    <ram:DuePayableAmount>23.80</ram:DuePayableAmount>
   </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
  </ram:ApplicableHeaderTradeSettlement>
 </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""

XMP = """<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
 <rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"><pdfaid:part>3</pdfaid:part><pdfaid:conformance>B</pdfaid:conformance></rdf:Description>
 <rdf:Description rdf:about="" xmlns:fx="urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#">
  <fx:DocumentType>INVOICE</fx:DocumentType><fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>
  <fx:Version>1.0</fx:Version><fx:ConformanceLevel>{level}</fx:ConformanceLevel>
 </rdf:Description>
</rdf:RDF></x:xmpmeta>
<?xpacket end="w"?>"""


def make(name: str, guideline: str | None, level: str | None, xml_name: str = "factur-x.xml") -> None:
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    if guideline:
        w.add_attachment(xml_name, CII.format(guideline=guideline).encode("utf-8"))
    if level:
        meta = DecodedStreamObject()
        meta.set_data(XMP.format(level=level).encode("utf-8"))
        meta.update({NameObject("/Type"): NameObject("/Metadata"), NameObject("/Subtype"): NameObject("/XML")})
        w._root_object[NameObject("/Metadata")] = w._add_object(meta)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, "wb") as fh:
        w.write(fh)


if __name__ == "__main__":
    make("facturx_en16931.pdf", "urn:cen.eu:en16931:2017", "EN 16931")
    make("facturx_mismatch.pdf", "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic", "EN 16931", "invoice.xml")
    make("plain.pdf", None, None)
    print("ok", OUT)
