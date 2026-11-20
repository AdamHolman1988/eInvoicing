"""HTML report (self-contained) + JSON export."""
from __future__ import annotations

import html as _h
import re
import threading
from dataclasses import asdict

from ..i18n import tr
from ..ui.theme import FAMILY, THEME_INIT, TOKENS
from ..validate import Report, coverage_rows

SEV_LABEL = {"error": "Chyba", "warning": "Varování", "info": "Info"}
STATUS_LABEL = {"explicit": "ve zprávě", "derived": "odvozeno", "const": "doplní konverze",
                "missing": "chybí", "not-in-format": "formát nenese"}
STRUCTURE_LABEL = {"XML-ORION": "ORION XML – XSD + dokumentace", "SAP-IDOC": "SAP IDoc – segmenty a formát polí",
                   "XML": "XML – obecné čtení", "EDITEL-INHOUSE": "pevná délka – layout",
                   "ORION-FLAT": "pevná délka – layout", "PDF": "vložené XML",
                   "XML-ORION-CCV": "ORION XML (převedeno z CCV XML) – XSD + dokumentace",
                   "SBDH": "Peppol obálka (SBDH)"}
LEVEL_MARK = {"required": "●", "conditional": "◐", "optional": ""}

CSS = TOKENS + """
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 """ + FAMILY + """;background:var(--bg);color:var(--fg)}
.rep{max-width:1280px;margin:0 auto;padding:24px}
h1{font-size:22px;font-weight:700;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:16px;font-weight:700;margin:32px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:12px;font-weight:600;margin:22px 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.meta{color:var(--muted);font-size:13px}.meta b{color:var(--fg);font-weight:600}
.counts{display:flex;gap:6px;margin:14px 0;flex-wrap:wrap}
.pill{padding:3px 10px;font-weight:600;font-size:12px;letter-spacing:.02em}
.p-error{background:var(--errbg);color:var(--err)}.p-warning{background:var(--warnbg);color:var(--warn)}
.p-info{background:var(--infobg);color:var(--info)}.p-ok{background:var(--okbg);color:var(--ok)}
table{border-collapse:collapse;width:100%;font-size:13px;background:var(--surface)}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--surface);color:var(--muted);font-weight:600;font-size:12px;position:sticky;top:0;border-bottom:1px solid var(--fg)}
.code{font-family:Consolas,"Cascadia Mono",monospace;font-size:12px;color:var(--muted)}
.seg{font-family:Consolas,"Cascadia Mono",monospace;font-size:12px;background:var(--soft);padding:1px 4px;word-break:break-all}
.hint{color:var(--muted);font-size:12px;margin-top:3px}
.ctx{font-size:12px;color:var(--muted)}
.prof{display:inline-block;font-size:11px;border:1px solid var(--line);padding:0 5px;margin:1px 2px 0 0;color:var(--muted)}
.st{font-size:12px;padding:1px 6px;white-space:nowrap}
.st-explicit{background:var(--okbg);color:var(--ok)}.st-derived,.st-const{background:var(--warnbg);color:var(--warn)}
.st-missing,.st-not-in-format{background:var(--errbg);color:var(--err)}
.guess{border:2px dashed var(--warn);border-radius:8px;padding:8px 12px;margin:8px 0;background:var(--warnbg)}
.guess b.tag{background:var(--warn);color:#fff;border-radius:4px;padding:1px 6px;margin-right:6px}
.lvl{text-align:center;color:var(--accent)}
.filters{display:flex;gap:16px;margin:8px 0;font-size:13px;flex-wrap:wrap;color:var(--muted)}
.filters input{accent-color:var(--accent)}
.empty{color:var(--muted);font-style:italic;padding:6px 0}
details summary{cursor:pointer;color:var(--accent);margin:10px 0;font-weight:500}
.legend{font-size:12px;color:var(--muted);margin:4px 0 8px}
.wrap{overflow-x:auto;border:1px solid var(--line)}
.wrap table{border:0}
.run{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--accent);padding:8px 12px;margin:6px 0}
"""

JS = """
document.querySelectorAll('.filters input').forEach(cb=>cb.addEventListener('change',()=>{
 const root=cb.closest('.rep');const on=[...root.querySelectorAll('.filters input:checked')].map(x=>x.value);
 root.querySelectorAll('tr[data-sev]').forEach(tr=>tr.style.display=on.includes(tr.dataset.sev)?'':'none');}));
document.querySelectorAll('.filters input[value=info]').forEach(cb=>cb.dispatchEvent(new Event('change')));
"""


_STATE = threading.local()
DATA_OPEN, DATA_CLOSE = "", ""  # protects document data from the phrase translation


def e(s) -> str:
    x = _h.escape("" if s is None else str(s))
    return f"{DATA_OPEN}{x}{DATA_CLOSE}" if getattr(_STATE, "protect", False) else x


def _translate_static(html: str, lang: str) -> str:
    parts = re.split(f"({DATA_OPEN}.*?{DATA_CLOSE})", html, flags=re.S)
    out = [p[1:-1] if p.startswith(DATA_OPEN) else tr(p, lang) for p in parts]
    return "".join(out)


def _ctx(f) -> str:
    if not f.contexts or f.contexts == ["doklad"]:
        return ""
    if len(f.contexts) > 6:
        return f"{e(f.contexts[0])} … {e(f.contexts[-1])} ({len(f.contexts)}×)"
    return ", ".join(e(c) for c in f.contexts)


def _findings_table(findings, show_profiles: bool, profiles_head: str = "Profily") -> str:
    if not findings:
        return '<div class="empty">Bez nálezů.</div>'
    rows = []
    for f in findings:
        where = []
        if f.line:
            where.append(f"ř.&nbsp;{f.line}")
        if f.segment:
            where.append(f'<span class="seg">{e(f.segment[:120])}</span>')
        desc = e(f.message)
        if getattr(f, "name_sk", None):
            desc += f' <span class="ctx">({e(f.name_sk)})</span>'
        if f.hint:
            desc += f'<div class="hint">→ {e(f.hint)}</div>'
        ctx = _ctx(f)
        if ctx:
            desc += f'<div class="ctx">{ctx}</div>'
        prof = "".join(f'<span class="prof">{e(p)}</span>' for p in f.profiles) if show_profiles else ""
        rows.append(f'<tr data-sev="{f.severity}"><td><span class="pill p-{f.severity}">{SEV_LABEL[f.severity]}</span></td>'
                    f'<td class="code">{e(f.code)}</td><td>{desc}</td><td>{"<br>".join(where)}</td>'
                    + (f"<td>{prof}</td>" if show_profiles else "") + "</tr>")
    head = "<tr><th>Závažnost</th><th>Kód</th><th>Popis</th><th>Kde</th>" + (f"<th>{profiles_head}</th>" if show_profiles else "") + "</tr>"
    return f'<div class="wrap"><table>{head}{"".join(rows)}</table></div>'


def _coverage(res, profiles) -> str:
    rows = coverage_rows(res, profiles)
    if not rows:
        return ""
    head = "<tr><th>BT</th><th>Název</th><th>Stav</th><th>Hodnota (1. výskyt)</th><th>Výskyt</th>" + "".join(
        f'<th class="lvl" title="{e(p.name)}">{e(p.id)}</th>' for p in profiles) + "</tr>"
    body = []
    for r in rows:
        lv = "".join(f'<td class="lvl" title="{r["levels"][p.id]}">{LEVEL_MARK[r["levels"][p.id]]}</td>' for p in profiles)
        body.append(f'<tr><td class="code">{e(r["bt"])}</td><td>{e(r["name"])}</td>'
                    f'<td><span class="st st-{r["status"]}">{STATUS_LABEL[r["status"]]}</span></td>'
                    f'<td>{e((r["value"] or "")[:60])}{" <span class=ctx>ř. " + str(r["line"]) + "</span>" if r["line"] else ""}</td>'
                    f'<td class="ctx">{e(r["count"] or "")}</td>{lv}</tr>')
    return (f'<details><summary>Pokrytí business termů ({len(rows)} BT – povinné v profilech + nalezené)</summary>'
            f'<div class="legend">● povinné &nbsp; ◐ podmíněně povinné &nbsp;|&nbsp; Výskyt = v kolika instancích '
            f'opakující se skupiny (řádky, DPH…) je údaj vyplněn</div>'
            f'<div class="wrap"><table>{head}{"".join(body)}</table></div></details>')


GRADE_CLASS = {"vysoká": "explicit", "střední": "derived", "nízká": "missing"}


def _guess(m) -> str:
    g = m.guess
    if not g:
        return ""
    lvl = {"doc": "doklad", "line": "řádek", "vat": "DPH"}
    rows = "".join(
        f'<tr><td class="code">{e(p["bt"])}</td><td>{e(p["name"])}</td><td class="ctx">{lvl[p["level"]]}</td>'
        f'<td class="code">{e(p["source"] or "")}</td><td>{e((p["sample"] or "")[:40])}</td>'
        f'<td><span class="st st-{GRADE_CLASS[p["grade"]]}">{p["confidence"]:.0%} {p["grade"]}</span></td>'
        f'<td class="ctx">{e("; ".join(p["reasons"]))}</td></tr>' for p in g["proposals"])
    groups = "; ".join(f'{bg} = {e(v["path"])} ({v["count"]}×)' for bg, v in g["groups"].items()) or "žádné"
    unused = ", ".join(f'{e(u["source"])} = {e(u["sample"][:30])}' for u in g["unused"][:30])
    checks = "".join(f'<li>{"✓" if c["ok"] else "✗"} {e(c["rule"])} – {e(c["detail"])}</li>' for c in g.get("checks", []))
    computed = "".join(f'<li>{e(k)}: {e(v)}</li>' for k, v in g.get("computed", {}).items())
    return ('<div class="guess"><b class="tag">ODHAD</b>Formát není naučený – přiřazení níže je odhad podle názvů polí, '
            f'nadřazených prvků, tvaru hodnot a aritmetiky částek (průměrná jistota {g["confidence"]:.0%}). Opakující se skupiny: {groups}.'
            '<br>Odhad zkontrolujte a uložte v editoru „Mapování klienta“; pak se z něj stane naučený formát.</div>'
            f'<details open><summary>Odhad mapování ({len(g["proposals"])} BT)</summary><div class="wrap"><table>'
            '<tr><th>BT</th><th>Název</th><th>Úroveň</th><th>Pole ve zdroji</th><th>Ukázka</th><th>Jistota</th>'
            f'<th>Proč</th></tr>{rows}</table></div>'
            + (f'<div class="legend">Aritmetická kontrola přiřazení:<ul>{checks}</ul></div>' if checks else "")
            + (f'<div class="legend">Dopočteno (formát údaj nenese):<ul>{computed}</ul></div>' if computed else "")
            + (f'<div class="legend">Nepřiřazená pole: {unused}</div>' if unused else "") + '</details>')


def body(rep: Report, lang: str = "cs") -> str:
    """Report body; for English the static texts are translated, document data (escaped via e()) is kept."""
    _STATE.protect = lang == "en"
    try:
        html = _body(rep)
    finally:
        _STATE.protect = False
    return _translate_static(html, lang) if lang == "en" else html


def _body(rep: Report) -> str:
    c = rep.counts()
    out = ['<div class="rep">',
           f'<h1>{e(rep.filename) or "Report"}</h1>',
           f'<div class="meta">Formát: <b>{e(rep.detection.label)}</b> &nbsp;·&nbsp; Profily: <b>{e(", ".join(p.name for p in rep.profiles))}</b>'
           f' &nbsp;·&nbsp; {e(rep.created)} &nbsp;·&nbsp; MsgValidator {e(rep.tool_version)}</div>',
           '<div class="counts">' + ('<span class="pill p-ok">Bez chyb</span>' if not c["error"]
                                     else f'<span class="pill p-error">{c["error"]} chyb</span>')
           + f'<span class="pill p-warning">{c["warning"]} varování</span>'
           f'<span class="pill p-info">{c["info"]} info</span></div>',
           '<div class="filters">Zobrazit: '
           '<label><input type="checkbox" value="error" checked> chyby</label>'
           '<label><input type="checkbox" value="warning" checked> varování</label>'
           '<label><input type="checkbox" value="info"> info</label></div>']
    if rep.envelope:
        out.append("<h2>Obálka / formát</h2>" + _findings_table(rep.envelope, False))
    for m in rep.messages:
        out.append(f"<h2>{e(m.label)}</h2>")
        out.append(_guess(m))
        if m.rules_info:
            runs = m.rules_info.get("runs") or [{**m.rules_info, "label": m.rules_info.get("repository"), "note": None}]
            out.append("<h3>Oficiální pravidla podle cílového standardu (KoSIT)</h3>")
            for r in runs:
                verdict = ('<span class="pill p-ok">PŘIJATO</span>' if r["accepted"]
                           else '<span class="pill p-error">ODMÍTNUTO</span>')
                steps = " ".join(f'<span class="st st-{"explicit" if ok else "missing"}">{"✓" if ok else "✖"} {e(n)}</span>'
                                 for n, ok in r["steps"])
                out.append(f'<div class="run"><div class="meta"><b>{e(r["label"])}</b> &nbsp;{verdict}&nbsp; '
                           f'scénář: {e(r["scenario"] or "žádný")}</div>'
                           + (f'<div class="hint">{e(r["note"])}</div>' if r.get("note") else "")
                           + f'<div class="counts" style="margin:6px 0 0">{steps}</div></div>')
            out.append(_findings_table(m.rules, len(runs) > 1, "Standard"))
            if not m.semantic:
                continue
        if m.semantic:
            out.append("<h3>Gap analýza vůči profilům</h3>" + _findings_table(m.gaps, len(rep.profiles) > 1))
        out.append("<h3>Kontrola hodnot</h3>" + _findings_table(m.values, False))
        st = STRUCTURE_LABEL.get(rep.detection.family, "UN/EDIFACT + GS1 CZ subset")
        out.append(f"<h3>Struktura ({st})</h3>" + _findings_table(m.structure, False))
        out.append(_coverage(m, rep.profiles))
    out.append("</div>")
    return "\n".join(out)


def render(rep: Report, lang: str = "cs") -> str:
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>MsgValidator – {_h.escape(rep.filename)}</title>'
            f'{THEME_INIT}<style>{CSS}</style></head><body>{body(rep, lang)}<script>{JS}</script></body></html>')


def to_dict(rep: Report) -> dict:
    def fl(fs):
        return [asdict(f) for f in fs]
    return {
        "file": rep.filename, "created": rep.created, "tool_version": rep.tool_version,
        "detection": asdict(rep.detection), "profiles": [p.id for p in rep.profiles],
        "counts": rep.counts(), "envelope": fl(rep.envelope),
        "messages": [{"ref": m.ref, "label": m.label, "structure": fl(m.structure), "values": fl(m.values),
                      "gaps": fl(m.gaps), "rules": fl(m.rules), "rules_info": m.rules_info, "guess": m.guess,
                      "coverage": coverage_rows(m, rep.profiles)} for m in rep.messages],
    }
