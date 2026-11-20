"""Single-page UI (served by ui/server.py). Placeholders __X__ are filled in by the server."""

PAGE = r"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MsgValidator</title>
__THEME_INIT__
<style>
__FONT__
__CSS__
__HEADER_CSS__
.top{max-width:1280px;margin:0 auto;padding:24px 24px 8px;display:grid;grid-template-columns:1fr 360px;gap:20px}
@media (max-width:860px){.top{grid-template-columns:1fr;padding:16px}}
#drop{border:1px dashed var(--muted);padding:40px 20px;text-align:center;cursor:pointer;background:var(--surface);transition:border-color .15s,background .15s;min-height:190px;display:flex;flex-direction:column;justify-content:center}
#drop:hover,#drop:focus{border-color:var(--accent);outline:none}
#drop.over{border:1px solid var(--accent);background:var(--soft)}
#drop .big{font-size:20px;font-weight:600;letter-spacing:-.01em}
#drop .small{color:var(--muted);font-size:13px;margin-top:10px;line-height:1.6}
#drop .fmt{display:inline-block;background:var(--soft);padding:1px 7px;margin:2px;font-size:12px;color:var(--fg)}
.box{background:var(--surface);border:1px solid var(--line);padding:16px 18px}
.box h4{margin:0 0 10px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.grp{font-size:11px;color:var(--muted);margin:12px 0 2px;text-transform:uppercase;letter-spacing:.06em}
.grp:first-child{margin-top:0}
.box label.pr{display:flex;gap:8px;align-items:flex-start;padding:5px 0;font-size:14px;cursor:pointer}
.box label.pr input{margin-top:3px;accent-color:var(--accent)}
.box label.pr small{display:block;color:var(--muted);font-size:12px;line-height:1.35;margin-top:1px}
select{font:inherit;width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:0;background:var(--surface);color:var(--fg)}
select:focus{outline:2px solid var(--accent);outline-offset:-1px}
.note{font-size:12px;color:var(--muted);margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
.actions{display:flex;gap:6px;margin-top:14px;flex-wrap:wrap}
button{font:500 13px __FAMILY__;border:1px solid var(--accent);background:var(--accent);color:var(--accent-fg);border-radius:0;padding:8px 14px;cursor:pointer}
button.sec{background:transparent;color:var(--accent);border-color:var(--line)}
button.sec:hover:not(:disabled){border-color:var(--accent)}
button:disabled{opacity:.35;cursor:default}
#status{margin-top:10px;font-size:13px;color:var(--muted);min-height:18px;display:flex;align-items:center;gap:8px}
.spin{width:14px;height:14px;border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:sp .8s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
#result.busy{opacity:.45;pointer-events:none;transition:opacity .2s}
#cta{max-width:1280px;margin:0 auto;padding:8px 24px 0}
#cta .box{display:flex;gap:16px;align-items:center;border-left:3px solid var(--accent)}
</style></head><body>
__HEADER__
<div class="top">
  <div>
    <div id="drop" tabindex="0">
      <div class="big">Přetáhněte sem soubor</div>
      <div class="small">nebo klikněte a vyberte<br>
        <span class="fmt">EDIFACT INVOIC</span><span class="fmt">ORION XML / TXT</span><span class="fmt">EDITEL INHOUSE</span>
        <span class="fmt">SAP IDoc</span><span class="fmt">UBL / CII</span><span class="fmt">Peppol obálka (SBDH)</span><span class="fmt">PDF – ZUGFeRD / Factur-X</span><span class="fmt">jiné XML</span></div>
      <input type="file" id="file" hidden>
    </div>
    <div id="status"></div>
  </div>
  <div class="box">
    <h4>Porovnat s profily</h4>
    <div id="profiles"></div>
    <div class="note">Oficiální pravidla (KoSIT) se spustí pro každý zaškrtnutý standard – Peppol / SK CIUS, XRechnung.</div>
    <div class="actions">
      <button id="rerun" class="sec" disabled>Znovu zkontrolovat</button>
      <button id="dl" class="sec" disabled>HTML report</button>
      <button id="dlj" class="sec" disabled>JSON</button>
      <button id="dlx" class="sec" disabled title="XML faktury vytažené z PDF (ZUGFeRD / Factur-X) nebo z Peppol obálky, nebo ORION XML převedené z CCV XML">Vložené / převedené XML</button>
      <button id="dlu" class="sec" disabled title="Zdrojový formát převedený do Peppol UBL – nad ním běží oficiální pravidla">Virtuální UBL</button>
    </div>
  </div>
</div>
<div id="cta" hidden></div>
<div id="result"></div>
<script>
__THEME_JS__
const PROFILES=__PROFILES__, DEFAULTS=__DEFAULTS__, RULES=__RULES__;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const box=document.getElementById('profiles');
let lastGrp=null;
PROFILES.forEach(p=>{
  if(p.group!==lastGrp){const g=document.createElement('div');g.className='grp';g.textContent=p.group;box.appendChild(g);lastGrp=p.group;}
  const l=document.createElement('label');l.className='pr';l.title=p.description;
  l.innerHTML=`<input type="checkbox" value="${esc(p.id)}" ${DEFAULTS.includes(p.id)?'checked':''}><span>${esc(p.name)}<small>${esc(p.description.length>90?p.description.slice(0,88)+'…':p.description)}</small></span>`;
  box.appendChild(l);});
let current=null;
const drop=document.getElementById('drop'), inp=document.getElementById('file'), st=document.getElementById('status');
const sel=()=>[...box.querySelectorAll('input:checked')].map(x=>x.value).join(',');
drop.onclick=()=>inp.click();drop.onkeydown=e=>{if(e.key==='Enter')inp.click()};
inp.onchange=()=>inp.files[0]&&load(inp.files[0]);
['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',e=>e.dataTransfer.files[0]&&load(e.dataTransfer.files[0]));
async function load(f){current={name:f.name,data:await f.arrayBuffer()};run();}
async function post(path){return fetch(path,{method:'POST',body:current.data,
  headers:{'X-Filename':encodeURIComponent(current.name),'X-Profiles':sel()}});}
async function run(){
  if(!current)return; st.innerHTML='<span class="spin"></span>Kontroluji '+esc(current.name)+' – struktura, profily, oficiální pravidla …';
  document.getElementById('result').classList.add('busy');
  const r=await post('/api/validate'); const t=await r.text();
  document.getElementById('result').classList.remove('busy');
  if(!r.ok){st.textContent='';document.getElementById('result').innerHTML='<pre class="rep">'+esc(t)+'</pre>';return;}
  document.getElementById('result').innerHTML=t; st.textContent='';
  showCta(r.headers.get('X-Mappable')==='1', r.headers.get('X-Family'), decodeURIComponent(r.headers.get('X-Client')||''));
  ['rerun','dl','dlj','dlu'].forEach(id=>document.getElementById(id).disabled=false);
  document.getElementById('dlx').disabled=!['PDF','XML-ORION-CCV','SBDH'].includes(r.headers.get('X-Family'));
  bindFilters();
}
function showCta(ok,fam,client){
  const el=document.getElementById('cta'); el.hidden=!ok; if(!ok)return;
  const unknown=fam==='XML'&&!client;
  el.innerHTML=`<div class="box"><div style="flex:1">${unknown?'<b>Tento formát validátor nezná.</b> Namapujte ho – kliknutím přiřadíte údaje faktury polím souboru a mapování se uloží pro tohoto klienta.'
      :client?`Použito mapování klienta <b>${esc(client)}</b>. Pokud něco nesedí, upravte ho v editoru.`
      :'Použito <b>standardní mapování SAP IDoc</b>. Pokud klient používá pole jinak, vytvořte mu vlastní mapování.'}</div>
    <button id="toMapper">${unknown?'Namapovat tento formát':client?'Upravit mapování klienta':'Vytvořit mapování klienta'}</button></div>`;
  document.getElementById('toMapper').onclick=async()=>{
    const r=await fetch('/api/mapper/stash',{method:'POST',body:current.data}); const j=await r.json();
    location.href='/mapper#'+j.token+':'+encodeURIComponent(current.name);};
}
function bindFilters(){const root=document.querySelector('#result .rep');if(!root)return;
  const apply=()=>{const on=[...root.querySelectorAll('.filters input:checked')].map(x=>x.value);
    root.querySelectorAll('tr[data-sev]').forEach(tr=>tr.style.display=on.includes(tr.dataset.sev)?'':'none');};
  root.querySelectorAll('.filters input').forEach(cb=>cb.onchange=apply);apply();}
async function download(path,ext,type){const r=await post(path);const b=new Blob([await r.arrayBuffer()],{type});
  const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='report_'+current.name+ext;a.click();}
document.getElementById('rerun').onclick=run;
box.addEventListener('change',()=>current&&run());
document.getElementById('dl').onclick=()=>download('/api/report','.html','text/html');
document.getElementById('dlj').onclick=()=>download('/api/json','.json','application/json');
document.getElementById('dlx').onclick=()=>download('/api/embedded','.xml','application/xml');
document.getElementById('dlu').onclick=()=>download('/api/ubl','.ubl.xml','application/xml');
</script></body></html>"""
