"""UBL 2.1 Invoice / CreditNote -> semantic model (EN 16931 BTs), driven by the Peppol syntax binding XPaths.

Lets the gap analysis (SK CIUS, retailer profiles) run on XML input exactly like on EDIFACT.
"""
from __future__ import annotations

from lxml import etree

from ..semantic.catalog import catalog
from ..semantic.model import Context, Semantic, Value
from ..xmlval.paths import readable

NS = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}

# Repeating groups: (base xpath, label prefix). Allowances vs charges share the UBL element.
GROUPS = {
    "BG-20": "/ubl:Invoice/cac:AllowanceCharge[cbc:ChargeIndicator='false']",
    "BG-21": "/ubl:Invoice/cac:AllowanceCharge[cbc:ChargeIndicator='true']",
    "BG-23": "/ubl:Invoice/cac:TaxTotal/cac:TaxSubtotal",
    "BG-25": "/ubl:Invoice/cac:InvoiceLine",
}
CATALOG_BASE = {"BG-20": "/ubl:Invoice/cac:AllowanceCharge", "BG-21": "/ubl:Invoice/cac:AllowanceCharge",
                "BG-23": "/ubl:Invoice/cac:TaxTotal/cac:TaxSubtotal", "BG-25": "/ubl:Invoice/cac:InvoiceLine"}

# Terms that share one UBL element and need a discriminator (full xpath override).
OVERRIDES = {
    "BT-31": "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']/cbc:CompanyID",
    "BT-32": "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme[not(cac:TaxScheme/cbc:ID='VAT')]/cbc:CompanyID",
    "BT-48": "/ubl:Invoice/cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']/cbc:CompanyID",
    "BT-63": "/ubl:Invoice/cac:TaxRepresentativeParty/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']/cbc:CompanyID",
    "BT-110": "/ubl:Invoice/cac:TaxTotal[cac:TaxSubtotal]/cbc:TaxAmount",
    "BT-111": "/ubl:Invoice/cac:TaxTotal[not(cac:TaxSubtotal)]/cbc:TaxAmount",
    "BT-29": "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID[not(@schemeID='SEPA')]",
    "BT-90": "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID[@schemeID='SEPA']",
    "BT-18": "/ubl:Invoice/cac:AdditionalDocumentReference[cbc:DocumentTypeCode='130']/cbc:ID",
    "BT-122": "/ubl:Invoice/cac:AdditionalDocumentReference[not(cbc:DocumentTypeCode='130')]/cbc:ID",
}
# Line allowances (BG-27) vs charges (BG-28): discriminate inside the line context
LINE_AC = {"BG-27": "cac:AllowanceCharge[cbc:ChargeIndicator='false']", "BG-28": "cac:AllowanceCharge[cbc:ChargeIndicator='true']"}
CN_RENAMES = [("ubl:Invoice", "cn:CreditNote"), ("cac:InvoiceLine", "cac:CreditNoteLine"),
              ("cbc:InvoicedQuantity", "cbc:CreditedQuantity"), ("cbc:InvoiceTypeCode", "cbc:CreditNoteTypeCode")]


def _cn(xp: str) -> str:
    for a, b in CN_RENAMES:
        xp = xp.replace(a, b)
    return xp.replace("/cn:CreditNote/cbc:DueDate", "/cn:CreditNote/cac:PaymentMeans/cbc:PaymentDueDate")


def _label(bg, el, n):
    if bg == "BG-25":
        return f"řádek {el.findtext('cbc:ID', namespaces=NS) or n}"
    if bg == "BG-23":
        cat = el.findtext("cac:TaxCategory/cbc:ID", namespaces=NS) or ""
        return f"DPH {el.findtext('cac:TaxCategory/cbc:Percent', namespaces=NS) or '?'} % {cat}".strip()
    return {"BG-20": "sleva dokladu", "BG-21": "přirážka dokladu"}[bg] + f" #{n}"


def _value(bt, node, tree) -> Value | None:
    if isinstance(node, etree._Element):
        text = (node.text or "").strip()
        line = node.sourceline
        scheme = node.get("schemeID")
        path = tree.getpath(node)
    else:  # attribute / text result
        text = str(node).strip()
        parent = node.getparent()
        line = parent.sourceline if parent is not None else None
        scheme = None
        path = tree.getpath(parent) + "/@" + node.attrname if parent is not None else None
    if not text:
        return None
    nice = None
    if path:
        nice = "/" + etree.QName(tree.getroot()).localname + path[2:] if path.startswith("/*") else path
        nice = nice.replace("cac:", "").replace("cbc:", "")
    return Value(bt, text, line=line, segment=nice, scheme=scheme, rule=path)


def read(data: bytes) -> Semantic:
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    tree = root.getroottree()
    kind = "CreditNote" if etree.QName(root).localname == "CreditNote" else "Invoice"
    fix = _cn if kind == "CreditNote" else (lambda x: x)
    cat = catalog()

    repeating: dict[str, str] = {}
    for tid in cat.order:
        for anc in cat.ancestors(tid):
            if anc in GROUPS:
                repeating[tid] = anc
                break

    document = Context(None, "doklad", root.sourceline)
    groups: dict[str, list[Context]] = {}
    group_nodes: dict[str, list] = {}
    for bg, base in GROUPS.items():
        nodes = root.xpath(fix(base), namespaces=NS)
        group_nodes[bg] = nodes
        groups[bg] = [Context(bg, _label(bg, el, n), el.sourceline) for n, el in enumerate(nodes, 1)]

    rules = {}
    for tid in cat.order:
        t = cat.get(tid)
        if t.kind != "BT" or not t.xpath:
            continue
        xp = OVERRIDES.get(tid, t.xpath)
        rules[tid] = [{"path": readable(fix(xp).replace("ubl:", "").replace("cn:", "")), "value": "text"}]
        bg = repeating.get(tid)
        if bg is None:
            for node in root.xpath(fix(xp), namespaces=NS):
                v = _value(tid, node, tree)
                if v:
                    document.add(v)
            continue
        rel = xp[len(CATALOG_BASE[bg]):].lstrip("/")
        if bg == "BG-25":
            for sub, disc in LINE_AC.items():
                if sub in cat.ancestors(tid):
                    rel = rel.replace("cac:AllowanceCharge", disc, 1)
        rel = fix(rel) if rel else "."
        for el, ctx in zip(group_nodes[bg], groups[bg]):
            for node in el.xpath(rel, namespaces=NS):
                v = _value(tid, node, tree)
                if v:
                    ctx.add(v)

    return Semantic(
        source_format=f"UBL 2.1 {kind}",
        mapping_id="ubl-peppol-syntax-binding",
        document=document,
        groups=groups,
        mapped_terms=set(rules),
        rules=rules,
        repeating=repeating,
        doc_kind=kind,
    )
