# MsgValidator – eInvoicing

[CZ](#cz) · [EN](#en) · **[⬇ MsgValidator.exe](https://github.com/AdamHolman1988/eInvoicing/releases/latest/download/MsgValidator.exe)** (Windows, no install)

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/01-home-dark.png"><img src="docs/screenshots/01-home.png" alt="Kontrola souboru"></picture>

## CZ

**Co to je:** lokální validátor a gap analýza e-faktur. Přetáhnete soubor, nástroj rozpozná formát a ukáže, co oproti cílovému standardu chybí, co se musí odvodit a co nesedí.

**Formáty:** EDIFACT INVOIC (D.96A, D.01B), ORION XML / TXT, EDITEL INHOUSE, SAP IDoc, UBL / CII, Peppol SBDH, PDF ZUGFeRD / Factur-X, neznámé XML (odhad mapování).

**Cíle:** Peppol BIS 3.0, EN 16931, SK CIUS, XRechnung a retailer profily (GS1 SK FMCG, BILLA, COOP, Lidl).

**Proč:**
- konec dohadů „sedí tenhle vzorek na specifikaci?“ – odpověď za pár sekund, po jednotlivých BT
- oficiální pravidla (KoSIT, CEN, Peppol) i nad ne-XML formáty přes „virtuální UBL“
- mapování klienta (SAP IDoc, vlastní XML) naklikáte bez programování
- u každého nálezu vysvětlení běžnou řečí („Co to znamená?“), kontrola SK IČO / DIČ / IČ DPH
- PDF faktura: tisková sestava v obvyklé podobě pro účetní z jakéhokoli vstupního formátu
- vše běží lokálně, soubory nikam neodcházejí

## EN

**What:** a local e-invoice validator and gap analysis. Drop a file, it detects the format and shows what is missing against the target standard, what has to be derived and what is wrong.

**Formats:** EDIFACT INVOIC (D.96A, D.01B), ORION XML / TXT, EDITEL INHOUSE, SAP IDoc, UBL / CII, Peppol SBDH, PDF ZUGFeRD / Factur-X, unknown XML (mapping guess).

**Targets:** Peppol BIS 3.0, EN 16931, SK CIUS, XRechnung and retailer profiles (GS1 SK FMCG, BILLA, COOP, Lidl).

**Why:**
- no more guessing whether a sample matches the spec – answer in seconds, per business term
- official rules (KoSIT, CEN, Peppol) even for non-XML formats via a "virtual UBL"
- client mappings (SAP IDoc, custom XML) built by clicking, no coding
- every finding explained in plain language ("What does it mean?"), Slovak company / tax ID checks
- PDF invoice: a conventional print layout for accountants from any input format
- runs locally, files never leave your machine

## Screenshots

<table>
<tr><td><picture><source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/02-official-rules-dark.png"><img src="docs/screenshots/02-official-rules.png" alt="Official rules"></picture><br>Official rules (KoSIT)</td><td><picture><source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/03-gap-analysis-dark.png"><img src="docs/screenshots/03-gap-analysis.png" alt="Gap analysis"></picture><br>Gap analysis vs. profiles</td></tr>
<tr><td><picture><source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/04-mapper-dark.png"><img src="docs/screenshots/04-mapper.png" alt="Client mapping"></picture><br>Client mapping</td><td><picture><source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/05-samples-dark.png"><img src="docs/screenshots/05-samples.png" alt="Samples"></picture><br>Sample documents</td></tr>
</table>

Screenshots follow your GitHub theme (light / dark).

## Run

```powershell
pip install -e .
python -m msgvalidator                      # UI in browser
python -m msgvalidator check invoice.edi    # text report
.\build.ps1                                 # -> dist\MsgValidator.exe (pip install -e .[dev])
```

License: AGPL-3.0
