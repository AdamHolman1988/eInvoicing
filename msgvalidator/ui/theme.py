"""GRiT visual style for the UI and the HTML report (tokens from design-manual/tokens.css).

Light and dark mode: follows the system by default, the header toggle stores an explicit choice
(localStorage 'mv-theme' -> <html data-theme="light|dark">). Square corners, Figtree, blue only as accent.
"""

# Colour tokens. Names are shared by report + UI; dark values are tuned for contrast on #0d101c.
LIGHT = ("--bg:#f7f7f7;--surface:#ffffff;--fg:#0d101c;--muted:#6b6e78;--line:#eaeaea;--soft:#f1f2f4;"
         "--accent:#0f40f7;--accent-fg:#ffffff;--head:#0d101c;--head-fg:#ffffff;--head-muted:#a9adbb;"
         "--err:#c62828;--errbg:#fbeaea;--warn:#8a5a00;--warnbg:#fdf3e1;--info:#4b5160;--infobg:#eef0f3;"
         "--ok:#1a7f37;--okbg:#e7f5ec")
DARK = ("--bg:#0d101c;--surface:#141827;--fg:#eceef4;--muted:#9a9eae;--line:#262b3d;--soft:#1a1f31;"
        "--accent:#6d8dff;--accent-fg:#0d101c;--head:#080a12;--head-fg:#ffffff;--head-muted:#8d92a5;"
        "--err:#ff8a80;--errbg:#3a1d22;--warn:#f2c46b;--warnbg:#352a14;--info:#b8bfcc;--infobg:#1f2435;"
        "--ok:#7fd99a;--okbg:#17301f")

TOKENS = (f":root{{{LIGHT};color-scheme:light}}"
          f"@media (prefers-color-scheme: dark){{:root:not([data-theme=light]){{{DARK};color-scheme:dark}}}}"
          f":root[data-theme=dark]{{{DARK};color-scheme:dark}}")

FONT = ('@font-face{font-family:"Figtree";src:url("/assets/Figtree-VariableFont.ttf") format("truetype");'
        'font-weight:300 900;font-display:swap}')
FAMILY = '"Figtree","Segoe UI",system-ui,sans-serif'

HEADER_CSS = """
.mv-head{background:var(--head);color:var(--head-fg);display:flex;align-items:center;gap:18px;padding:0 24px;height:56px;position:sticky;top:0;z-index:20}
.mv-head img{height:22px;display:block}
.mv-head .app{font-weight:600;letter-spacing:.02em;padding-right:18px;border-right:1px solid #2a2f42;white-space:nowrap}
.mv-head .app small{display:block;font-weight:400;font-size:11px;color:var(--head-muted);letter-spacing:0}
.mv-head nav{display:flex;gap:2px;flex:1;height:100%}
.mv-head nav a{color:var(--head-muted);text-decoration:none;font-weight:500;font-size:14px;padding:0 12px;display:flex;align-items:center;border-bottom:3px solid transparent}
.mv-head nav a:hover{color:var(--head-fg)}
.mv-head nav a.on{color:var(--head-fg);border-bottom-color:#0f40f7}
.mv-langs{display:flex;border:1px solid #2a2f42}
.mv-lang{background:none;border:0;color:var(--head-muted);font-weight:600;font-size:12px;font-family:inherit;padding:0 9px;height:32px;cursor:pointer;letter-spacing:.04em}
.mv-lang.on{background:#0f40f7;color:#fff}.mv-lang:not(.on):hover{color:var(--head-fg)}
.mv-theme{background:none;border:1px solid #2a2f42;color:var(--head-fg);width:34px;height:34px;padding:0;font-size:16px;cursor:pointer;border-radius:0}
.mv-theme:hover{border-color:var(--head-muted)}
@media (max-width:720px){.mv-head{gap:10px;padding:0 12px}.mv-head .app small{display:none}.mv-head nav a{padding:0 6px;font-size:13px}}
"""

# Runs in <head> before paint: apply the stored choice (no flash of the wrong theme).
THEME_INIT = ("<script>try{var t=localStorage.getItem('mv-theme');if(t)document.documentElement.dataset.theme=t;}"
              "catch(e){}</script>")
THEME_JS = """
(function(){const b=document.getElementById('mvTheme');if(!b)return;
 const cur=()=>document.documentElement.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
 const show=()=>{const d=cur()==='dark';b.textContent=d?'☀':'☾';b.title=d?'Světlý režim':'Tmavý režim';};
 b.onclick=()=>{const n=cur()==='dark'?'light':'dark';document.documentElement.dataset.theme=n;
   try{localStorage.setItem('mv-theme',n);}catch(e){} show();};
 show();})();
document.querySelectorAll('.mv-lang').forEach(x=>x.onclick=()=>{
  document.cookie='mv-lang='+x.dataset.lang+';path=/;max-age=31536000;SameSite=Strict';location.reload();});
"""


def header(active: str, version: str, lang: str = "cs") -> str:
    """Dark top bar: GRiT logo, app name, navigation, language and theme toggles (texts translated by the page)."""
    def link(href, label, key):
        return f'<a href="{href}" class="{"on" if active == key else ""}">{label}</a>'
    langs = "".join(f'<button type="button" class="mv-lang{" on" if lang == code else ""}" data-lang="{code}">{"CZ" if code == "cs" else "EN"}</button>'
                    for code in ("cs", "en"))
    return (f'<header class="mv-head"><img src="/assets/grit-logo-white.svg" alt="GRiT">'
            f'<div class="app">MsgValidator<small>e-fakturace · v{version}</small></div>'
            f'<nav>{link("/", "Kontrola souboru", "check")}{link("/mapper", "Mapování klienta", "mapper")}'
            f'{link("/samples", "Vzory", "samples")}{link("/docs", "Dokumentace", "docs")}</nav>'
            f'<div class="mv-langs">{langs}</div>'
            f'<button class="mv-theme" id="mvTheme" type="button" aria-label="Přepnout světlý / tmavý režim"></button></header>')
