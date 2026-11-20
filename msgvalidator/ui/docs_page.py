"""Tab "Dokumentace" – short user guide, written in both languages (not machine-translated)."""

DOCS = {
"cs": """
<h1>Jak to funguje</h1>
<p class="lead">MsgValidator zkontroluje fakturu ve formátu klienta a řekne, co chybí pro zvolený standard
(Peppol, SK CIUS, XRechnung) nebo odběratele (Billa, COOP, Lidl …). Vše běží lokálně, soubor nikam neodchází.</p>

<h2>1. Kontrola souboru</h2>
<ol>
 <li>Vpravo zaškrtněte <b>standardy</b> a případně <b>odběratele</b>, vůči kterým chcete kontrolovat.</li>
 <li>Přetáhněte soubor do pole vlevo. Formát se pozná sám.</li>
 <li>Nahoře uvidíte počet <b>chyb</b> (musí se opravit), <b>varování</b> (ověřit) a <b>info</b>.</li>
</ol>

<h2>2. Co je ve výsledku</h2>
<table>
 <tr><th>Oddíl</th><th>Co říká</th></tr>
 <tr><td>Obálka / formát</td><td>Problémy celého souboru (kódování, PDF, neznámý formát …).</td></tr>
 <tr><td>Oficiální pravidla</td><td>Výsledek oficiálních pravidel (KoSIT) – pro každý zaškrtnutý standard zvlášť: <b>přijato / odmítnuto</b>.
   Soubor se nejdřív převede na fakturu daného standardu (virtuální UBL).</td></tr>
 <tr><td>Gap analýza</td><td>Které údaje faktury (BT) standard nebo odběratel vyžaduje a ve zprávě chybí, nebo je konverze musí dopočítat.</td></tr>
 <tr><td>Kontrola hodnot</td><td>Formát hodnot: data, čísla, číselníky, IČ DPH, GLN/GTIN.</td></tr>
 <tr><td>Struktura</td><td>Kontrola podle specifikace formátu (segmenty, pole, délky).</td></tr>
 <tr><td>Pokrytí BT</td><td>Tabulka všech údajů faktury: co zpráva nese, co se odvodí, co chybí.</td></tr>
</table>
<p><b>Odvozeno</b> = údaj ve zprávě není, převodník ho dopočítá (např. kód země z IČ DPH). <b>Formát nenese</b> = formát klienta takový údaj vůbec nemá.</p>

<h2>3. Standardy a odběratelé</h2>
<ul>
 <li><b>Peppol BIS 3.0</b> – evropská e-faktura (jádro EN 16931).</li>
 <li><b>SK CIUS</b> – slovenská pravidla nad Peppolem. Spustí se, když je na faktuře slovenská strana.</li>
 <li><b>XRechnung 3.0</b> – německá pravidla (povinný kontakt na prodávajícího, referenční označení kupujícího …).</li>
 <li><b>Slovenská transpozice – rozšířené formáty</b>: GS1 SK FMCG (příručka GS1 Slovakia / Czech Republic včetně
 slovníku Additional Item Property – kontroluje názvy a typy hodnot) a odběratelé nad ní: Billa, COOP Jednota; Lidl SK
 (od 1. 1. 2027, navíc kontrola očekávaných hodnot – IČ DPH Lidlu, GLN skladů).</li>
</ul>

<h2>4. Podporované formáty</h2>
<p>EDIFACT INVOIC D.96A / D.01B (GS1 CZ) · ORION XML, ORION TXT a CCV XML (eBUS, převede se na ORION XML) · EDITEL INHOUSE · SAP IDoc (XML i textový výpis) ·
UBL 2.1 · CII · Peppol obálka (SBDH) · PDF se ZUGFeRD / Factur-X · jiné XML přes mapování klienta.</p>
<p>U každého dokladu se kontroluje i typ (BT-3): opravná faktura a dobropis bez odkazu na původní fakturu, self-billing, záloha a konečná faktura, dílčí faktury a typy, které Peppol povoluje jen mezi německými (slovenskými) firmami.</p>
<h2>Neznámý formát – ODHAD</h2>
<p>XML, které validátor nezná a pro které ještě není mapování klienta, se zkontroluje podle <b>odhadu</b>: údaje faktury se přiřadí podle názvů polí (CZ / SK / EN / DE / IT), nadřazených prvků (dodavatel, odběratel, místo dodání, řádky, rekapitulace DPH) a tvaru hodnot (datum, IBAN, IČ DPH, GLN / EAN s kontrolní číslicí, měna, sazba). Report je označený <b>ODHAD</b> a u každého údaje ukazuje jistotu a důvod. Chybějící povinné údaje se hlásí jen jako varování (odhad nepozná, jestli údaj ve formátu není, nebo má nečekaný název). Soubor, který nevypadá jako faktura, se neodhaduje.</p>
<p>Editor <i>Mapování klienta</i> se otevře předvyplněný odhadem – stačí opravit, pojmenovat a uložit; tím se z odhadu stane naučený formát. Z příkazové řádky: <code>MsgValidator.exe guess soubor.xml -o navrh.yaml</code>.</p>
<h2>Vzory dokladů</h2>
<p>Záložka <b>Vzory</b> stáhne vzorový doklad zvoleného typu (faktura, dobropis, opravná, zálohová, self-billing, PDP, dodání do EU, slevy a přirážky, dílčí) jako UBL, CII, UBL v Peppol obálce nebo Factur-X PDF. Data jsou fiktivní, každý vzor projde oficiálními pravidly.</p>

<h2>5. Mapování klienta</h2>
<p>Když klient posílá údaje v jiných polích, než je standard, nebo formát validátor nezná:</p>
<ol>
 <li>Po kontrole klikněte na <b>Vytvořit / Upravit mapování klienta</b> (nebo záložka <i>Mapování klienta</i>).</li>
 <li>Vlevo vyberte údaj faktury (např. <i>BT-27 Název prodávajícího</i>).</li>
 <li>Vpravo klikněte na pole vzorku, odkud se má brát. Hodnota se hned ukáže.</li>
 <li>U opakovaných částí (řádky faktury, DPH) nejdřív vyberte skupinu (<i>BG-25</i>) a klikněte na záhlaví segmentu.</li>
 <li>Vyplňte název klienta a <b>Uložit mapování</b>.</li>
</ol>
<p>Při další kontrole se mapování použije samo (klient se pozná podle odesílatele / IČ DPH – tlačítko <i>Rozpoznání klienta</i>).
Mapování se ukládají do <code>%APPDATA%\\MsgValidator\\mapovani</code>.</p>
<p>Barvy teček: <span class="d ok"></span> ze zprávy · <span class="d der"></span> odvozeno · <span class="d miss"></span> chybí, povinné · <span class="d cst"></span> doplní konverze.</p>

<h2>6. Tlačítka</h2>
<ul>
 <li><b>HTML report</b> – výsledek do souboru (pro klienta nebo kolegu).</li>
 <li><b>JSON</b> – strojový výstup.</li>
 <li><b>Virtuální UBL</b> – zdroj převedený do Peppol UBL (nad ním běží oficiální pravidla).</li>
 <li><b>Vložené XML</b> – XML faktury vytažené z PDF.</li>
</ul>

<h2>7. Co zatím neumí</h2>
<ul>
 <li>Úplnou kontrolu PDF/A (písma, barvy) – na to je veraPDF.</li>
 <li>CSV a Excel jako vstup.</li>
</ul>
<p class="muted">Texty oficiálních pravidel (KoSIT, CEN, Peppol, SK CIUS, BR-DE) jsou v jazyce jejich vydavatele.</p>
""",
"en": """
<h1>How it works</h1>
<p class="lead">MsgValidator checks an invoice in the client’s format and tells you what is missing for the chosen standard
(Peppol, SK CIUS, XRechnung) or buyer (Billa, COOP, Lidl …). Everything runs locally; the file never leaves your computer.</p>

<h2>1. Check a file</h2>
<ol>
 <li>On the right, tick the <b>standards</b> and, if needed, the <b>buyers</b> to check against.</li>
 <li>Drop the file into the box on the left. The format is detected automatically.</li>
 <li>At the top you see the number of <b>errors</b> (must be fixed), <b>warnings</b> (to verify) and <b>info</b>.</li>
</ol>

<h2>2. What the result contains</h2>
<table>
 <tr><th>Section</th><th>Meaning</th></tr>
 <tr><td>Envelope / format</td><td>Problems of the whole file (encoding, PDF, unknown format …).</td></tr>
 <tr><td>Official rules</td><td>Result of the official rules (KoSIT) – separately for every ticked standard: <b>accepted / rejected</b>.
   The file is first converted into an invoice of that standard (virtual UBL).</td></tr>
 <tr><td>Gap analysis</td><td>Which invoice terms (BT) the standard or buyer requires and the message lacks, or the conversion has to derive.</td></tr>
 <tr><td>Value checks</td><td>Format of values: dates, numbers, code lists, VAT IDs, GLN/GTIN.</td></tr>
 <tr><td>Structure</td><td>Check against the format specification (segments, fields, lengths).</td></tr>
 <tr><td>BT coverage</td><td>Table of all invoice terms: what the message carries, what is derived, what is missing.</td></tr>
</table>
<p><b>Derived</b> = not in the message, the converter computes it (e.g. country code from the VAT ID). <b>Not in format</b> = the client’s format has no such field at all.</p>

<h2>3. Standards and buyers</h2>
<ul>
 <li><b>Peppol BIS 3.0</b> – European e-invoice (EN 16931 core).</li>
 <li><b>SK CIUS</b> – Slovak rules on top of Peppol. Applied when a Slovak party is on the invoice.</li>
 <li><b>XRechnung 3.0</b> – German rules (mandatory seller contact, buyer reference …).</li>
 <li><b>Slovak transposition – extended formats</b>: GS1 SK FMCG (GS1 Slovakia / Czech Republic guideline including the
 Additional Item Property vocabulary – names and value types are checked) and the buyers built on it: Billa, COOP Jednota; Lidl SK
 (from 1 Jan 2027, also checks expected values – Lidl VAT id, warehouse GLNs).</li>
</ul>

<h2>4. Supported formats</h2>
<p>EDIFACT INVOIC D.96A / D.01B (GS1 CZ) · ORION XML, ORION TXT and CCV XML (eBUS, converted to ORION XML) · EDITEL INHOUSE · SAP IDoc (XML and text dump) ·
UBL 2.1 · CII · Peppol envelope (SBDH) · PDF with ZUGFeRD / Factur-X · any other XML via a client mapping.</p>
<p>The document type (BT-3) is checked as well: corrected invoices and credit notes without a reference to the original invoice, self-billing, prepayment and final invoices, partial invoices and types Peppol allows only between German (Slovak) companies.</p>
<h2>Unknown format – GUESS</h2>
<p>XML the validator does not know and that has no client mapping yet is checked with a <b>guess</b>: invoice terms are assigned from field names (CZ / SK / EN / DE / IT), parent elements (seller, buyer, delivery place, lines, VAT breakdown) and value shapes (date, IBAN, VAT id, GLN / EAN with check digit, currency, rate). The report is marked <b>GUESS</b> and shows a confidence and a reason for every term. Missing mandatory terms are only warnings (a guess cannot tell whether the format lacks the term or names it unexpectedly). A file that does not look like an invoice is not guessed.</p>
<p>The <i>Client mapping</i> editor opens pre-filled with the guess – fix, name and save it; the guess then becomes a learned format. Command line: <code>MsgValidator.exe guess file.xml -o draft.yaml</code>.</p>
<h2>Sample documents</h2>
<p>The <b>Samples</b> tab downloads a sample document of the chosen type (invoice, credit note, corrected, prepayment, self-billing, reverse charge, intra-EU supply, allowances and charges, partial) as UBL, CII, UBL in a Peppol envelope or Factur-X PDF. The data are fictitious and every sample passes the official rules.</p>

<h2>5. Client mapping</h2>
<p>When a client sends data in other fields than the standard, or the format is unknown:</p>
<ol>
 <li>After the check, click <b>Create / Edit client mapping</b> (or the <i>Client mapping</i> tab).</li>
 <li>On the left, pick an invoice term (e.g. <i>BT-27 Seller name</i>).</li>
 <li>On the right, click the sample field it comes from. The value appears immediately.</li>
 <li>For repeating parts (invoice lines, VAT) first pick the group (<i>BG-25</i>) and click the segment header.</li>
 <li>Enter the client name and <b>Save mapping</b>.</li>
</ol>
<p>Next time the mapping is applied automatically (the client is recognised by sender / VAT ID – button <i>Client recognition</i>).
Mappings are stored in <code>%APPDATA%\\MsgValidator\\mapovani</code>.</p>
<p>Dot colours: <span class="d ok"></span> from the message · <span class="d der"></span> derived · <span class="d miss"></span> missing, mandatory · <span class="d cst"></span> added by the conversion.</p>

<h2>6. Buttons</h2>
<ul>
 <li><b>HTML report</b> – the result as a file (for the client or a colleague).</li>
 <li><b>JSON</b> – machine-readable output.</li>
 <li><b>Virtual UBL</b> – the source converted to Peppol UBL (the official rules run on it).</li>
 <li><b>Embedded XML</b> – invoice XML extracted from a PDF.</li>
</ul>

<h2>7. Not supported yet</h2>
<ul>
 <li>Full PDF/A validation (fonts, colours) – use veraPDF.</li>
 <li>CSV and Excel input.</li>
</ul>
<p class="muted">Texts of the official rules (KoSIT, CEN, Peppol, SK CIUS, BR-DE) are in the language of their publisher.</p>
""",
}

DOCS_PAGE = r"""<!doctype html>
<html lang="__LANG__"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MsgValidator – __TITLE__</title>
__THEME_INIT__
<style>
__FONT__
__CSS__
__HEADER_CSS__
.doc{max-width:860px;margin:0 auto;padding:32px 24px 64px;line-height:1.6;font-size:15px}
.doc h1{font-size:28px;margin:0 0 12px}
.doc h2{font-size:17px;margin:36px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}
.doc .lead{font-size:16px;color:var(--muted);margin:0 0 8px}
.doc li{margin:4px 0}.doc ol,.doc ul{padding-left:22px}
.doc table{background:var(--surface);border:1px solid var(--line);font-size:14px}
.doc td:first-child{white-space:nowrap;font-weight:600}
.doc td.dl{white-space:nowrap}.doc .btn{display:inline-block;padding:3px 8px;margin:1px;border:1px solid var(--line);text-decoration:none;color:var(--fg);font-size:12px;font-weight:600}.doc .btn:hover{border-color:var(--accent,#0f40f7);color:var(--accent,#0f40f7)}
.doc code{font-family:Consolas,monospace;font-size:13px;background:var(--soft);padding:1px 5px}
.doc .muted{color:var(--muted);font-size:13px;margin-top:28px}
.d{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 2px 0 6px}
.d.ok{background:var(--ok)}.d.der{background:var(--warn)}.d.miss{background:var(--err)}.d.cst{background:var(--muted)}
</style></head><body>
__HEADER__
<div class="doc">__DOCS__</div>
<script>__THEME_JS__</script>
</body></html>"""
