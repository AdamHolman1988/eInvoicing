"""Plain-text report for the CLI."""
from __future__ import annotations

from ..validate import Report

ICON = {"error": "✖", "warning": "▲", "info": "·"}


def _ctx(f):
    if not f.contexts or f.contexts == ["doklad"]:
        return ""
    if len(f.contexts) > 4:
        return f" [{f.contexts[0]} … {f.contexts[-1]}, {len(f.contexts)}×]"
    return " [" + ", ".join(f.contexts) + "]"


def _line(f, verbose):
    s = f"  {ICON[f.severity]} {f.code:<18} {f.message}{_ctx(f)}"
    if f.line:
        s += f"  (ř. {f.line})"
    if verbose and f.hint:
        s += f"\n      → {f.hint}"
    return s


def render(rep: Report, verbose: bool = True, show_info: bool = False) -> str:
    out = [f"Soubor:   {rep.filename}", f"Formát:   {rep.detection.label}",
           f"Profily:  {', '.join(p.name for p in rep.profiles)}"]
    c = rep.counts()
    out.append(f"Výsledek: {c['error']} chyb, {c['warning']} varování, {c['info']} informací")
    keep = (lambda f: True) if show_info else (lambda f: f.severity != "info")
    if rep.envelope:
        out.append("\n== Obálka / formát")
        out += [_line(f, verbose) for f in rep.envelope if keep(f)]
    for m in rep.messages:
        out.append(f"\n== {m.label}")
        st = [f for f in m.structure if keep(f)]
        out.append(f"-- Struktura ({len(st)})")
        out += [_line(f, verbose) for f in st]
        vals = [f for f in m.values if keep(f)]
        out.append(f"-- Hodnoty ({len(vals)})")
        out += [_line(f, verbose) for f in vals]
        if m.rules_info:
            for r in m.rules_info.get("runs") or [{**m.rules_info, "label": m.rules_info["repository"]}]:
                verdict = "PŘIJATO (accept)" if r["accepted"] else "ODMÍTNUTO (reject)"
                out.append(f"-- Oficiální pravidla – {r['label']}: {r['scenario'] or 'žádný scénář'} → {verdict}")
                for name, ok in r["steps"]:
                    out.append(f"     {'✓' if ok else '✖'} {name}")
            out += [_line(f, verbose) + (f"  [{f.segment}]" if f.segment else "") for f in m.rules if keep(f)]
        fs = [f for f in m.gaps if keep(f)]
        out.append(f"-- Gap analýza ({len(fs)})")
        for f in fs:
            prof = "" if len(rep.profiles) == 1 else "\n      ⟶ profily: " + ", ".join(f.profiles)
            out.append(_line(f, verbose) + prof)
    return "\n".join(out)
