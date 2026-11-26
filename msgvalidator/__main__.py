"""CLI entry point.

  msgvalidator                       -> spustí lokální UI v prohlížeči
  msgvalidator check FILE [-p ID...] -> textový report
  msgvalidator check FILE --html OUT -> HTML report
  msgvalidator profiles              -> seznam profilů
  msgvalidator sample -t TYP -f FMT  -> vzorový doklad (synteticky, Peppol-validní)
  msgvalidator guess FILE [-o X.yaml]-> ODHAD mapování neznámého XML (návrh klientského mapování)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="msgvalidator", description="Validátor a gap analýza e-fakturačních zpráv")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="zkontrolovat soubor")
    c.add_argument("file")
    c.add_argument("-p", "--profile", action="append", help="ID profilu (lze opakovat), výchozí peppol-bis3 + sk-cius")
    c.add_argument("--html", help="uložit HTML report do souboru")
    c.add_argument("--json", help="uložit JSON report do souboru")
    c.add_argument("--info", action="store_true", help="zobrazit i informativní nálezy")
    c.add_argument("--pdf", help="uložit tiskovou sestavu faktury (PDF; .html = jen tisková HTML)")
    c.add_argument("--ubl", help="uložit virtuální UBL (EDIFACT / ORION → Peppol UBL) do souboru")
    c.add_argument("--no-rules", action="store_true", help="u EDIFACT / ORION nespouštět oficiální pravidla nad virtuálním UBL")
    c.add_argument("--lang", default="cs", choices=["cs", "en"], help="jazyk výstupu (cs / en)")
    c.add_argument("--rules", default=None,
                   help="vynutit jednu KoSIT konfiguraci (peppol, xrechnung nebo cesta se scenarios.xml); "
                        "výchozí: pravidla všech cílových standardů ze zvolených profilů")
    sub.add_parser("profiles", help="vypsat dostupné profily")
    sm = sub.add_parser("sample", help="vygenerovat vzorový doklad (fiktivní data)")
    sm.add_argument("-t", "--type", default="invoice", help="typ vzoru (výpis: sample --list)")
    sm.add_argument("-f", "--format", default="ubl", help="ubl | cii | sbdh | pdf")
    sm.add_argument("-o", "--out", help="výstupní soubor (výchozí: vzor_<typ>_<formát> v aktuální složce)")
    sm.add_argument("--list", action="store_true", help="vypsat typy a formáty")
    gs = sub.add_parser("guess", help="odhadnout mapování neznámého XML formátu")
    gs.add_argument("-v", "--verbose", action="store_true", help="vypsat důvody u každého BT")
    gs.add_argument("file")
    gs.add_argument("-o", "--out", help="uložit návrh klientského mapování (YAML) – lze pak nahrát do složky mapování")
    u = sub.add_parser("ui", help="spustit lokální UI (výchozí)")
    u.add_argument("--port", type=int, default=0)
    u.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd in ("profiles", "check", "sample", "guess"):
        from . import splash
        splash.close()
    if args.cmd == "sample":
        from . import samples
        if args.list:
            for k, (cs, _, code, desc) in samples.SCENARIOS.items():
                print(f"{k:<17} {code:>4}  {cs} – {desc}")
            print("formáty: " + ", ".join(f"{k} ({v[0]})" for k, v in samples.FORMATS.items()))
            return 0
        data, name = samples.render(args.type, args.format)
        out = pathlib.Path(args.out or name)
        out.write_bytes(data)
        print(out.resolve())
        return 0
    if args.cmd == "guess":
        import yaml
        from . import idoc
        from .detect import detect
        from .guess import guess, looks_like_invoice
        path = pathlib.Path(args.file)
        data = path.read_bytes()
        det = detect(data)
        if not det.details.get("mappable"):
            print(f"{det.label}: formát validátor zná – odhad není potřeba (použijte check).")
            return 1
        g = guess(idoc.parse(data).messages[0])
        print(f"ODHAD mapování – {det.label}: {len(g.proposals)} BT, průměrná jistota {g.confidence:.0%}")
        ok, why = looks_like_invoice(g)
        if not ok:
            print(f"  POZOR: soubor nevypadá jako faktura ({why}) – při kontrole se odhad nepoužije.")
        for bg, v in g.groups.items():
            print(f"  skupina {bg}: {' > '.join(v['path'])} ({v['count']}×) – {'; '.join(v['reasons'])}")
        for p in g.proposals:
            d = p.as_dict()
            print(f"  {p.bt:<7} {d['confidence']:>4.0%} {d['grade']:<7} {(d['source'] or '(předpoklad)'):<48} {p.name}")
            if args.verbose:
                for r in p.reasons:
                    print(f"            · {r}")
        for c in g.checks:
            print(f"  {'✓' if c['ok'] else '✗'} aritmetika: {c['rule']} – {c['detail']}")
        for k, spec in g.computed.items():
            print(f"  dopočteno {k}: {spec.get('note', '')}")
        if g.unused:
            print("  nepřiřazeno: " + ", ".join(f.label for f in g.unused))
        if args.out:
            pathlib.Path(args.out).write_text(
                "# Návrh klientského mapování vytvořený ODHADEM (msgvalidator guess) – zkontrolujte před použitím.\n"
                + yaml.safe_dump(g.client, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
            print(pathlib.Path(args.out).resolve())
        return 0
    if args.cmd == "profiles":
        from .profiles.loader import available
        for p in available():
            print(f"{p['id']:<14} {p['name']}  –  {p['description']}")
        return 0
    if args.cmd == "check":
        from .report import html, text
        from .validate import validate
        path = pathlib.Path(args.file)
        rep = validate(path.read_bytes(), path.name, args.profile, rules_repo=args.rules,
                       virtual_rules=not args.no_rules)
        from .i18n import localize, tr
        localize(rep, args.lang)
        if args.ubl and rep.messages and rep.messages[0].virtual_xml:
            pathlib.Path(args.ubl).write_bytes(rep.messages[0].virtual_xml)
        print(tr(text.render(rep, show_info=args.info), args.lang))
        if args.html:
            pathlib.Path(args.html).write_text(html.render(rep, args.lang), encoding="utf-8")
            print(f"\nHTML report: {args.html}")
        if args.pdf:
            from .report import printout
            page = printout.for_report(rep, args.lang)
            if page is None:
                print("\nTiskovou sestavu nelze vytvořit (chybí sémantický model).")
            elif args.pdf.lower().endswith((".html", ".htm")):
                pathlib.Path(args.pdf).write_text(page, encoding="utf-8")
            else:
                pathlib.Path(args.pdf).write_bytes(printout.to_pdf(page))
                print(f"\nPDF faktura: {args.pdf}")
        if args.json:
            pathlib.Path(args.json).write_text(json.dumps(html.to_dict(rep), ensure_ascii=False, indent=1), encoding="utf-8")
        return 1 if rep.counts()["error"] else 0
    from . import splash
    from .ui.server import serve
    splash.text("Připravuji validační pravidla (EN 16931, Peppol, KoSIT)…")
    splash.prewarm()
    splash.text("Spouštím rozhraní…")
    serve(port=getattr(args, "port", 0), open_browser=not getattr(args, "no_browser", False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
