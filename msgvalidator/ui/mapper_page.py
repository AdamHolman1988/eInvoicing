"""Visual mapping editor for SAP IDoc clients (served at /mapper). Placeholders __X__ are filled by the server.

Left: EN 16931 business terms with the value the current mapping produces from the sample.
Right: the selected term's rules + the sample's segments/fields; clicking a field assigns it.
Every change re-runs the extraction + gap analysis on the sample (preview), saving writes a client YAML.
"""

MAPPER_PAGE = r"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mapování klienta</title>
__THEME_INIT__
<style>
__FONT__
__CSS__
__HEADER_CSS__
.mwrap{max-width:1600px;margin:0 auto;padding:20px 24px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
#drop{border:1px dashed var(--muted);padding:12px 18px;cursor:pointer;background:var(--surface);min-width:280px}
#drop:hover{border-color:var(--accent)}#drop.over{border:1px solid var(--accent);background:var(--soft)}
#drop b{font-size:14px;font-weight:600}#drop div{color:var(--muted);font-size:12px}
input[type=text],select{font:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--line);border-radius:0;background:var(--surface);color:var(--fg)}
input[type=text]:focus,select:focus{outline:2px solid var(--accent);outline-offset:-1px}
input[type=checkbox],input[type=radio]{accent-color:var(--accent)}
button{font:500 13px __FAMILY__;border:1px solid var(--accent);background:var(--accent);color:var(--accent-fg);border-radius:0;padding:7px 14px;cursor:pointer}
button.sec{background:transparent;color:var(--accent);border-color:var(--line)}button.sec:hover:not(:disabled){border-color:var(--accent)}
button.mini{padding:2px 8px;font-size:12px}button:disabled{opacity:.35;cursor:default}
button.danger{border-color:var(--line);color:var(--err);background:transparent}button.danger:hover{border-color:var(--err)}
.muted{color:var(--muted);font-size:12px}
a{color:var(--accent)}
.grid{display:grid;grid-template-columns:minmax(380px,44%) 1fr;gap:16px;margin-top:14px}
@media (max-width:980px){.grid{grid-template-columns:1fr}}
.panel{background:var(--surface);border:1px solid var(--line);overflow:hidden;display:flex;flex-direction:column;min-height:0}
.panel>h4{margin:0;padding:10px 12px;border-bottom:1px solid var(--line);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.panel>h4 label,.panel>h4 span{text-transform:none;letter-spacing:0;font-weight:400;font-size:12px}
.scroll{overflow:auto;max-height:calc(100vh - 260px)}
#terms .row{display:grid;grid-template-columns:14px 74px 1fr minmax(90px,34%);gap:8px;padding:6px 12px;border-bottom:1px solid var(--line);cursor:pointer;align-items:baseline;font-size:13px}
#terms .row:hover{background:var(--soft)}#terms .row.sel{background:var(--soft);box-shadow:inset 3px 0 var(--accent)}
#terms .bg{font-weight:600;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;background:var(--line)}
.d-ok{background:var(--ok)}.d-derived{background:var(--warn)}.d-const{background:var(--muted)}.d-missing{background:var(--err)}.d-none{background:transparent;border:1px solid var(--line)}
.lvl{font-size:10px;padding:0 4px;margin-left:6px;vertical-align:1px}
.l-required{background:var(--errbg);color:var(--err)}.l-conditional{background:var(--warnbg);color:var(--warn)}
.val{font-family:Consolas,"Cascadia Mono",monospace;font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cl{font-size:10px;background:var(--accent);color:var(--accent-fg);padding:0 4px;margin-left:6px}
#detail{padding:14px 16px;border-bottom:1px solid var(--line)}
#detail h3{margin:0 0 2px;color:var(--fg);text-transform:none;letter-spacing:0;font-size:16px}
.rule{display:flex;gap:8px;align-items:center;border:1px solid var(--line);padding:6px 10px;margin:5px 0;font-size:13px;flex-wrap:wrap}
.rule .n{color:var(--muted);font-size:11px;width:16px}
.rule .txt{flex:1;min-width:200px}
.maptab{margin:4px 0 4px 22px;font-size:12px}.maptab input{width:90px;padding:2px 5px}
.tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px;font-size:13px}
.tip{background:var(--infobg);color:var(--info);padding:8px 10px;font-size:12px;margin-top:8px}
.warnbox{background:var(--warnbg);color:var(--warn);padding:8px 10px;font-size:12px;margin-top:6px}
#src .seg{display:block;background:none;padding:0}
.node{border-bottom:1px solid var(--line)}
.node>.nh{padding:7px 12px;background:var(--soft);font-size:13px;cursor:pointer;display:flex;gap:8px;align-items:baseline}
.node>.nh .t{font-family:Consolas,"Cascadia Mono",monospace;font-weight:600}.node.d1>.nh{padding-left:28px}.node.d2>.nh{padding-left:44px}
.node.grp>.nh{box-shadow:inset 3px 0 var(--accent)}
.f{display:grid;grid-template-columns:110px 1fr 1.2fr auto;gap:8px;padding:4px 12px 4px 24px;font-size:12px;cursor:pointer;align-items:baseline}
.node.d1 .f{padding-left:40px}.node.d2 .f{padding-left:56px}
.f:hover{background:var(--soft)}
.f .fn{font-family:Consolas,"Cascadia Mono",monospace}.f .fs{font-family:Consolas,"Cascadia Mono",monospace;color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip{font-size:10px;padding:0 4px;background:var(--okbg);color:var(--ok);margin-left:3px;white-space:nowrap}
.chip.cur{background:var(--accent);color:var(--accent-fg)}
#findings{margin-top:16px}
#findings .fi{display:flex;gap:10px;padding:6px 12px;border-bottom:1px solid var(--line);font-size:13px;cursor:pointer}
#findings .fi:hover{background:var(--soft)}
.sev{font-size:11px;font-weight:600;padding:0 6px;height:fit-content}
.s-error{background:var(--errbg);color:var(--err)}.s-warning{background:var(--warnbg);color:var(--warn)}.s-info{background:var(--infobg);color:var(--info)}
#msg{font-size:13px;min-height:18px;margin-top:10px}
dialog{border:1px solid var(--line);border-radius:0;background:var(--surface);color:var(--fg);max-width:620px;width:92vw;padding:20px}
dialog::backdrop{background:rgba(13,16,28,.5)}
dialog label{display:block;margin:8px 0 2px;font-size:13px}
dialog input[type=text]{width:100%}
</style></head><body>
__HEADER__
<div class="mwrap">
 <div class="bar">
  <div id="drop" tabindex="0"><b>Přetáhněte vzorový soubor klienta</b><div>nebo klikněte · SAP IDoc (XML i textový výpis) · jakékoli XML</div><input type="file" id="file" hidden></div>
  <div>
   <div class="bar"><label class="muted">Mapování:</label><select id="clientSel"></select>
    <input type="text" id="cname" placeholder="název klienta (např. Company, s.r.o.)" size="26">
    <button id="save" disabled>Uložit mapování</button><button id="match" class="sec" disabled title="Podle čeho se klient pozná při kontrole">Rozpoznání klienta…</button></div>
   <div class="muted" style="margin-top:4px">Složka mapování: <span id="mdir"></span> <button class="sec mini" id="chdir">změnit</button></div>
  </div>
  <div style="margin-left:auto;text-align:right">
   <div id="counts" class="counts" style="margin:0;justify-content:flex-end"></div>
   <div class="bar" style="justify-content:flex-end;margin-top:4px"><span id="profs" class="muted"></span>
    <button class="sec mini" id="full" disabled title="Spustí i oficiální pravidla Peppol/SK nad virtuálním UBL (pomalejší)">Plná kontrola</button></div>
  </div>
 </div>
 <div id="msg" class="muted"></div>
 <div class="grid" id="grid" hidden>
  <div class="panel"><h4>Faktura EN 16931 <input type="text" id="q" placeholder="hledat BT / název" size="16">
     <label><input type="checkbox" id="onlyReq" checked> jen povinné</label><label><input type="checkbox" id="onlyBad"> jen problémy</label></h4>
   <div class="scroll" id="terms"></div></div>
  <div class="panel"><div id="detail"></div>
   <h4>Vzorek klienta – segmenty a pole <input type="text" id="qs" placeholder="hledat pole / hodnotu" size="18"><label style="text-transform:none;letter-spacing:0"><input type="checkbox" id="empty"> i prázdná pole</label><span id="srcinfo" style="text-transform:none;letter-spacing:0"></span></h4>
   <div class="scroll" id="src" style="max-height:calc(100vh - 420px)"></div></div>
 </div>
 <div class="panel" id="findings" hidden><h4>Výsledek kontroly vzorku s tímto mapováním <span id="flabel" style="text-transform:none;letter-spacing:0"></span></h4><div id="flist" class="scroll" style="max-height:300px"></div></div>
</div>
<dialog id="dlgMatch"><h3>Rozpoznání klienta</h3>
 <p class="muted">Při kontrole se mapování použije automaticky, když soubor splní všechny zaškrtnuté podmínky.</p>
 <div id="matchRows"></div>
 <div class="tools"><button id="matchOk">Hotovo</button></div></dialog>
<script>
__THEME_JS__
const PROFILES=__PROFILES__, DEFAULTS=__DEFAULTS__;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let S=null, client=null, sel=null, prev=null, profiles=[...DEFAULTS], timer=null, sample=null;
const SCHEMES={'BT-157':'0160','BT-71':'0088'};
const DATE_FIELDS=['DATUM','CREDAT','TXDAT'];
$('profs').innerHTML=PROFILES.map(p=>`<label title="${esc(p.description)}"><input type="checkbox" value="${p.id}" ${DEFAULTS.includes(p.id)?'checked':''}> ${esc(p.name)}</label>`).join(' ');
$('profs').onchange=()=>{profiles=[...$('profs').querySelectorAll('input:checked')].map(x=>x.value); if(sample) open(sample);};

// ---------------------------------------------------------------- file
const drop=$('drop'), inp=$('file');
drop.onclick=()=>inp.click(); inp.onchange=()=>inp.files[0]&&load(inp.files[0]);
['dragenter','dragover'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',ev=>ev.dataTransfer.files[0]&&load(ev.dataTransfer.files[0]));
async function load(f){sample={name:f.name,data:await f.arrayBuffer()};open(sample);}
async function api(action,body){const r=await fetch('/api/mapper/'+action,{method:'POST',body:JSON.stringify(body),headers:{'Content-Type':'application/json'}});
  const j=await r.json(); if(!r.ok){$('msg').innerHTML='<span style="color:var(--err)">'+esc(j.error||r.status)+'</span>';throw j;} return j;}
async function open(smp){
  $('msg').textContent='Načítám '+smp.name+' …';
  const r=await fetch('/api/mapper/open',{method:'POST',body:smp.data||'',headers:{'X-Filename':encodeURIComponent(smp.name),'X-Profiles':profiles.join(','),'X-Token':smp.token||''}});
  const j=await r.json(); if(!r.ok){$('msg').innerHTML='<span style="color:var(--err)">'+esc(j.error)+'</span>';return;}
  const keepClient=S&&client&&client.name?client:null;
  S=j; client=keepClient||norm(j.client); sel=sel||'BT-1';
  $('grid').hidden=false;$('findings').hidden=false;['save','match','full'].forEach(id=>$(id).disabled=false);
  $('mdir').textContent=S.mapping_dir; fillClients(S.clients, S.picked||client.id||'');
  $('cname').value=client.name||'';
  const c=S.idoc.control; if(smp.token&&!smp.data){sample={name:smp.name,token:S.token};}
  $('msg').innerHTML=(S.idoc.generic&&S.guess&&S.guess.proposals.length&&!S.picked?`<b>${esc(j.file)}</b> · ${esc(S.idoc.type)} – neznámý formát, <b style="color:var(--warn)">mapování je předvyplněné ODHADEM</b> (${S.guess.proposals.length} BT, průměrná jistota ${Math.round(S.guess.confidence*100)} %). Projděte údaje vlevo, opravte co nesedí, pojmenujte klienta a uložte – pak se z odhadu stane naučený formát.`
    :S.idoc.generic?`<b>${esc(j.file)}</b> · ${esc(S.idoc.type)} – neznámý formát, mapování začíná od nuly. <b>Nejdřív</b> vlevo klikněte na <b>BG-25</b> (řádky faktury) a pak na záhlaví segmentu položky ve vzorku.`
    :`<b>${esc(j.file)}</b> · ${esc(S.idoc.type)} · doklad ${esc(S.idoc.ref)} · odesílatel <span class="seg">${esc(c.SNDPRN||'?')}</span> port <span class="seg">${esc(c.SNDPOR||'?')}</span>`)+
    (S.idoc.count>1?` · ${S.idoc.count} IDocy v souboru (editor ukazuje první)`:'')+
    (S.picked?` · <b>rozpoznán klient „${esc(client.name)}“</b>`:S.idoc.generic?'':` · klient nerozpoznán – začínáte ze standardního mapování`);
  renderSource(); preview();
}
function norm(c){c=JSON.parse(JSON.stringify(c||{}));c.terms=c.terms||{};c.groups=c.groups||{};c.aux=c.aux||{};c.match=c.match||{};return c;}
function fillClients(list,cur){
  $('clientSel').innerHTML='<option value="">— nové mapování (ze standardu) —</option>'+
    list.map(c=>`<option value="${esc(c.id)}" ${c.id===cur?'selected':''} ${c.error?'disabled':''}>${esc(c.name||c.id)}${c.error?' (chyba v souboru)':''}</option>`).join('');
}
$('clientSel').onchange=async()=>{
  const id=$('clientSel').value;
  client=id?norm(await api('client',{id})):norm({match:S.suggest_match});
  client.base=client.base||S.idoc.base;
  $('cname').value=client.name||''; renderAll(); preview();
};
$('cname').oninput=()=>{client.name=$('cname').value;};
if(location.hash.length>2){const [tok,nm]=location.hash.slice(1).split(':');history.replaceState(null,'','/mapper');open({name:decodeURIComponent(nm||'soubor'),token:tok});}

// ---------------------------------------------------------------- mapping helpers
const T=()=>S.terms, term=id=>S.terms.find(t=>t.id===id);
function groupsEff(){const g=JSON.parse(JSON.stringify(S.standard.groups));
  for(const [k,v] of Object.entries(client.groups||{})){ if(!v||!Object.keys(v).length) delete g[k]; else g[k]={...(g[k]||{}),...v}; } return g;}
function rulesOf(bt){return bt in client.terms?client.terms[bt]:(S.standard.terms[bt]||[]);}
function overridden(bt){return bt in client.terms;}
function groupOf(bt){const g=groupsEff();let t=term(bt);while(t&&t.parent){if(g[t.parent])return t.parent;t=term(t.parent);}return null;}
const REPEATING=['BG-20','BG-21','BG-23','BG-25','BG-27','BG-28'];
function missingGroup(bt){let t=term(bt);const g=groupsEff();while(t&&t.parent){if(g[t.parent])return null;if(REPEATING.includes(t.parent))return t.parent;t=term(t.parent);}return null;}
function absEach(bg){const g=groupsEff()[bg];if(!g)return null;return g.parent?absEach(g.parent)+' > '+g.each:g.each;}
const tagOf=step=>step.replace(/\[.*$/,'').trim();
function nodeByPath(p){return S.source.find(n=>n.path===p);}
function absPath(bt,path){ // rule path -> absolute source path
  if(!path) return null; if(!path.startsWith('@')) return path;
  const bg=groupOf(bt); const base=bg?absEach(bg):''; const rest=path.replace(/^@(\[[^\]]*\])?\s*>?\s*/,'');
  return rest?base+' > '+rest:base;}
function relPath(bt,node){ // source node -> rule path for this BT, or {error}
  const bg=groupOf(bt);
  if(!bg) return {path:node.path, note: node.depth>0?'Pole je v položce – použije se hodnota z první položky.':null};
  const gs=absEach(bg).split(' > '), ns=node.path.split(' > ');
  if(ns.length<gs.length || gs.some((s,i)=>tagOf(s)!==tagOf(ns[i])))
    return {error:`${bt} patří do skupiny ${bg} (${esc(term(bg)?.name_sk||term(bg)?.name)}), která se opakuje pro segment ${esc(absEach(bg))}. Vyberte pole uvnitř tohoto segmentu.`};
  const exact=gs.every((s,i)=>s===ns[i]);
  const rest=ns.slice(gs.length); const p=rest.length?'@ > '+rest.join(' > '):'@';
  return {path:p, note: exact?null:`Kvalifikátor segmentu se liší od definice skupiny (${esc(absEach(bg))}).`};
}
function fieldLabel(path,name){const n=nodeByPath(path);const f=n&&n.fields.find(f=>f.name===name);return f&&f.label?f.label:'';}
function segText(abs){
  if(!abs) return '';
  const n=nodeByPath(abs); const last=abs.split(' > ').pop();
  const q=n&&n.qualifier&&n.qualifier.label?` (${n.qualifier.label})`:'';
  return `<span class="seg" style="display:inline">${esc(last)}</span>${esc(q)}`;}
function describe(bt,r){
  if('const' in r) return `konstanta <b>${esc(r.const)}</b>`+(r.note?` <span class="muted">${esc(r.note)}</span>`:'');
  if(r.derive){
    const a=r.args||{};
    if(a.path&&a.value){const abs=absPath(bt,a.path);return `${esc(S.transforms[r.derive]||r.derive)}: ${segText(abs)} › <b>${esc(a.value)}</b> <span class="muted">${esc(fieldLabel(abs,a.value))}</span>`;}
    return `výpočet <b>${esc(r.derive)}</b>`+(r.note?` <span class="muted">${esc(r.note)}</span>`:' <span class="muted">(dopočet z jiných údajů)</span>');
  }
  const abs=absPath(bt,r.path);
  let s=`${segText(abs)} › <b>${esc(r.value||(r.join||[]).join('+'))}</b> <span class="muted">${esc(fieldLabel(abs,r.value))}</span>`;
  if(r.date) s+=' <span class="chip">datum</span>';
  if(r.scheme) s+=` <span class="chip">schéma ${esc(r.scheme)}</span>`;
  if(r.map) s+=' <span class="chip">převod '+Object.entries(r.map).map(([a,b])=>esc(a)+'→'+esc(b)).join(', ')+'</span>';
  return s;}
function ruleField(bt,r){ // [absPath, field] a rule reads
  if(r.derive&&r.args&&r.args.path) return [absPath(bt,r.args.path),r.args.value];
  if(r.path) return [absPath(bt,r.path),r.value];
  return null;}
function setRules(bt,rules){client.terms[bt]=rules;changed();}
function changed(){renderAll();clearTimeout(timer);timer=setTimeout(preview,250);}

// ---------------------------------------------------------------- preview
async function preview(full){
  if(!S) return;
  $('flabel').textContent=full?'· plná kontrola běží …':'· počítám …';
  try{prev=await api('preview',{token:S.token,client,profiles,rules:!!full});}catch(e){return;}
  const c=prev.counts;
  $('counts').innerHTML=`<span class="pill p-error">${c.error} chyb</span><span class="pill p-warning">${c.warning} varování</span><span class="pill p-info">${c.info} info</span>`+
    (prev.accepted===true?'<span class="pill p-ok">pravidla OK</span>':prev.accepted===false?'<span class="pill p-error">pravidla neprošla</span>':'');
  $('flabel').textContent='· '+(full?'včetně oficiálních pravidel':'bez oficiálních pravidel (tlačítko Plná kontrola)');
  renderAll(); renderFindings();
}
$('full').onclick=()=>preview(true);
function status(bt){
  const v=prev&&prev.values[bt]; if(v) return v.status;
  const t=term(bt); if(t.kind==='BG') return 'none';
  return t.level==='optional'?'none':'missing';}
function problems(){const s=new Set();(prev?.findings||[]).forEach(f=>{if(f.bt&&f.severity!=='info')s.add(f.bt)});return s;}

// ---------------------------------------------------------------- left: terms
['q','onlyReq','onlyBad'].forEach(id=>$(id).oninput=renderTerms);
function renderAll(){renderTerms();renderDetail();renderSource();}
function renderTerms(){
  if(!S) return;
  const q=$('q').value.toLowerCase(), req=$('onlyReq').checked, bad=$('onlyBad').checked, pr=problems();
  const show=t=>{ if(q&&!(t.id.toLowerCase().includes(q)||(t.name||'').toLowerCase().includes(q)||(t.name_sk||'').toLowerCase().includes(q)))return false;
    if(t.kind==='BG') return true;
    if(req&&t.level==='optional'&&!(prev&&prev.values[t.id])&&!overridden(t.id)) return false;
    if(bad&&!pr.has(t.id)&&status(t.id)!=='missing') return false; return true;};
  const vis=T().filter(show);
  const hasChild=new Set(vis.filter(t=>t.kind==='BT').flatMap(t=>{const a=[];let p=t.parent;while(p){a.push(p);p=term(p)?.parent;}return a;}));
  const qm=t=>q&&(t.id.toLowerCase().includes(q)||(t.name||'').toLowerCase().includes(q)||(t.name_sk||'').toLowerCase().includes(q));
  $('terms').innerHTML=vis.filter(t=>t.kind==='BT'||hasChild.has(t.id)||qm(t)||(!req&&!bad&&!q)).map(t=>{
    const v=prev&&prev.values[t.id]; const st=status(t.id);
    const pad=`padding-left:${10+t.depth*12}px`;
    if(t.kind==='BG'){const g=groupsEff()[t.id];const n=prev&&prev.groups[t.id];
      return `<div class="row bg ${sel===t.id?'sel':''}" data-id="${t.id}" style="${pad}"><span></span><span>${t.id}</span><span>${esc(t.name_sk||t.name)}${client.groups[t.id]?'<span class="cl">klient</span>':''}</span><span class="val">${g?'opakuje se: '+esc(absEach(t.id))+(n!=null?' ('+n+'×)':''):''}</span></div>`;}
    return `<div class="row ${sel===t.id?'sel':''}" data-id="${t.id}" style="${pad}" title="${esc(t.name)}"><span class="dot d-${st}"></span><span>${t.id}</span>
      <span>${esc(t.name_sk||t.name)}${t.level!=='optional'?`<span class="lvl l-${t.level}">${t.level==='required'?'povinné':'podmíněné'}</span>`:''}${overridden(t.id)?'<span class="cl">klient</span>':''}${pr.has(t.id)?' ⚠':''}</span>
      <span class="val">${v?esc(v.value)+(v.n>1?' ('+v.n+'×)':''):(rulesOf(t.id).length?'<i>prázdné ve vzorku</i>':'—')}</span></div>`;}).join('');
  $('terms').querySelectorAll('.row').forEach(r=>r.onclick=()=>{sel=r.dataset.id;renderAll();});
}

// ---------------------------------------------------------------- right top: detail of the selected term
function renderDetail(){
  if(!S||!sel){$('detail').innerHTML='';return;}
  const t=term(sel);
  if(t.kind==='BG') return renderGroup(t);
  const rules=rulesOf(sel), v=prev&&prev.values[sel], bg=groupOf(sel);
  const fs=(prev?.findings||[]).filter(f=>f.bt===sel&&f.severity!=='info');
  let h=`<h3>${t.id} ${esc(t.name_sk||t.name)} ${t.level!=='optional'?`<span class="lvl l-${t.level}">${t.level==='required'?'povinné':'podmíněné'}</span>`:''}</h3>
   <div class="muted">${esc(t.name)}${t.datatype?' · '+esc(t.datatype):''}${t.codelist?' · číselník '+esc(t.codelist):''}${bg?` · opakuje se ve skupině ${bg} (${esc(absEach(bg))})`:' · údaj dokladu'}</div>
   <div style="margin:6px 0">Hodnota ze vzorku: ${v?`<b class="seg" style="display:inline">${esc(v.value)}</b>${v.raw?` <span class="muted">(ze zdroje ${esc(v.raw)})</span>`:''} <span class="muted">${v.how==='explicit'?'':esc(v.how)} ${esc(v.context)}${v.n>1?' · '+v.n+'×':''}</span>${v.note?`<div class="hint">${esc(v.note)}</div>`:''}`:'<b style="color:var(--err)">žádná</b>'}</div>`;
  fs.forEach(f=>h+=`<div class="warnbox"><b>${esc(f.code)}</b> ${esc(f.message)}${f.hint?'<br>'+esc(f.hint):''}</div>`);
  h+=`<div style="margin-top:8px"><b>Odkud se bere</b> <span class="muted">(první pravidlo, které ve vzorku najde hodnotu, vyhrává)</span> ${overridden(sel)?'<span class="cl">klientská úprava</span>':'<span class="muted">· standard</span>'}</div>`;
  if(!rules.length) h+=`<div class="muted" style="margin:4px 0">${overridden(sel)?'Klient tento údaj neposílá (označeno ručně).':'Standardní mapování tento údaj neplní.'}</div>`;
  rules.forEach((r,i)=>{
    h+=`<div class="rule"><span class="n">${i+1}.</span><span class="txt">${describe(sel,r)}</span>
      ${r.path&&!r.derive?`<button class="sec mini" data-a="map" data-i="${i}" title="Převod kódů klienta na kódy EN 16931">převod kódů</button>`:''}
      ${i>0?`<button class="sec mini" data-a="up" data-i="${i}" title="Zkusit dřív">↑</button>`:''}
      <button class="danger mini" data-a="del" data-i="${i}" title="Odebrat">✕</button></div>`;
    if(mapEdit&&mapEdit.bt===sel&&mapEdit.i===i) h+=mapEditor(r,i);
  });
  h+=`<div class="tools">Klik na pole vzorku níže:
     <label><input type="radio" name="mode" value="replace" ${mode==='replace'?'checked':''}> nahradí pravidla</label>
     <label><input type="radio" name="mode" value="add" ${mode==='add'?'checked':''}> přidá další možnost</label>
     · úprava hodnoty <select id="tf">${Object.entries(S.transforms).map(([k,l])=>`<option value="${k}" ${k===tf?'selected':''}>${esc(l)}</option>`).join('')}</select></div>
   <div class="tools"><button class="sec mini" id="bConst">pevná hodnota…</button>
     <button class="sec mini" id="bNone">klient neposílá</button>
     ${overridden(sel)?'<button class="sec mini" id="bStd">vrátit standard</button>':''}</div>`;
  $('detail').innerHTML=h;
  $('detail').querySelectorAll('button[data-a]').forEach(b=>b.onclick=()=>ruleAction(b.dataset.a,+b.dataset.i));
  $('detail').querySelectorAll('input[name=mode]').forEach(x=>x.onchange=()=>mode=x.value);
  $('tf').onchange=()=>tf=$('tf').value;
  $('bConst').onclick=()=>{const v=prompt('Pevná hodnota pro '+sel+':');if(v!=null&&v!=='')setRules(sel,[{const:v,note:'Pevná hodnota z klientského mapování.'}]);};
  $('bNone').onclick=()=>setRules(sel,[]);
  if($('bStd')) $('bStd').onclick=()=>{delete client.terms[sel];changed();};
  bindMapEditor();
}
let mode='replace', tf='', mapEdit=null;
function copyRules(){return JSON.parse(JSON.stringify(rulesOf(sel)));}
function ruleAction(a,i){
  const rs=copyRules(); mapEdit=null;
  if(a==='del'){rs.splice(i,1);return setRules(sel,rs);}
  if(a==='up'){[rs[i-1],rs[i]]=[rs[i],rs[i-1]];return setRules(sel,rs);}
  if(a==='map'){mapEdit={bt:sel,i};renderDetail();}
}
function mapEditor(r,i){
  const [abs,fld]=ruleField(sel,r)||[]; const n=nodeByPath(abs); const f=n&&n.fields.find(x=>x.name===fld);
  const m=r.map||{}; const keys=[...new Set([...Object.keys(m),...((f&&f.samples)||[])])];
  return `<div class="maptab" data-i="${i}">Převod hodnot (zdroj → EN 16931):`+keys.map(k=>`<div><input class="mk" value="${esc(k)}"> → <input class="mv" value="${esc(m[k]||'')}" placeholder="beze změny"></div>`).join('')+
    `<div><input class="mk" placeholder="kód klienta"> → <input class="mv" placeholder="kód EN 16931"></div><button class="mini" id="mapOk">Použít převod</button></div>`;}
function bindMapEditor(){const ok=$('mapOk');if(!ok)return;
  ok.onclick=()=>{const box=ok.closest('.maptab'),i=+box.dataset.i;const m={};
    box.querySelectorAll('div').forEach(d=>{const k=d.querySelector('.mk'),v=d.querySelector('.mv');if(k&&v&&k.value.trim()&&v.value.trim())m[k.value.trim()]=v.value.trim();});
    const rs=copyRules(); if(Object.keys(m).length) rs[i].map=m; else delete rs[i].map; mapEdit=null; setRules(sel,rs);};}
function renderGroup(t){
  const g=groupsEff()[t.id];
  let h=`<h3>${t.id} ${esc(t.name_sk||t.name)}</h3><div class="muted">${esc(t.name)}${t.max!=='1'?' · skupina se může opakovat':''}</div>`;
  h+=g?`<div style="margin:6px 0">Opakuje se pro každý segment <span class="seg" style="display:inline">${esc(absEach(t.id))}</span>${prev&&prev.groups[t.id]!=null?` – ve vzorku ${prev.groups[t.id]}×`:''}</div>`
      :`<div style="margin:6px 0" class="muted">Skupina se z IDocu neplní${S.standard.groups[t.id]?'':' (ve standardu není)'}.</div>`;
  if(client.groups[t.id]&&g){
    const kids=T().filter(x=>x.kind==='BT'&&groupOf(x.id)===t.id&&rulesOf(x.id).length);
    const stale=kids.filter(x=>rulesOf(x.id).some(r=>{const rf=ruleField(x.id,r);return rf&&rf[0]&&!nodeByPath(rf[0]);}));
    if(stale.length||(prev&&prev.groups[t.id]===0))
      h+=`<div class="warnbox">Skupina se teď bere z jiného segmentu. Přemapujte její údaje na pole tohoto segmentu: `+
        (stale.length?stale:kids).map(x=>`<a href="#" data-go="${x.id}">${x.id}</a>`).join(', ')+
        `. Výskyty bez částky / sazby se vynechávají${prev&&prev.groups[t.id]===0?' – proto teď 0×':''}.</div>`;
  }
  h+=`<div class="tip">Klikněte na <b>záhlaví segmentu</b> ve vzorku níže – skupina se pak bude opakovat pro každý jeho výskyt (např. rekapitulace DPH pro každý E1EDK04, slevy dokladu pro E1EDK05[ALCKZ=-]).</div>
   <div class="tools">${client.groups[t.id]?'<button class="sec mini" id="gStd">vrátit standard</button>':''}${g?'<button class="sec mini" id="gNone">skupinu neplnit</button>':''}</div>`;
  $('detail').innerHTML=h;
  $('detail').querySelectorAll('a[data-go]').forEach(a=>a.onclick=e=>{e.preventDefault();sel=a.dataset.go;renderAll();});
  if($('gStd')) $('gStd').onclick=()=>{delete client.groups[t.id];changed();};
  if($('gNone')) $('gNone').onclick=()=>{client.groups[t.id]={};changed();};
}
function pickGroupNode(node){
  const t=term(sel); let parentBg=null;
  // nested under an invoice line (BG-27/28 under BG-25)
  const lines=absEach('BG-25');
  if(['BG-27','BG-28'].includes(t.id)&&lines&&node.path.startsWith(lines+' > ')) parentBg='BG-25';
  const each=parentBg?node.path.slice(lines.length+3):node.path;
  const cfg={each, scope: node.summary?'summary':(t.id==='BG-25'?'line':'header')};
  if(parentBg){cfg.parent=parentBg;cfg.scope='line';}
  client.groups[t.id]=cfg; changed();
}

// ---------------------------------------------------------------- right bottom: source sample
$('qs').oninput=renderSource;$('empty').onchange=renderSource;
function usage(){ // "absPath|FIELD" -> [BT…]
  const u={}; const all=new Set([...Object.keys(S.standard.terms),...Object.keys(client.terms)]);
  all.forEach(bt=>rulesOf(bt).forEach(r=>{const rf=ruleField(bt,r);if(rf&&rf[0]){(u[rf[0]+'|'+rf[1]]=u[rf[0]+'|'+rf[1]]||[]).push(bt);}}));
  return u;}
function renderSource(){
  if(!S) return;
  const q=$('qs').value.toLowerCase(), u=usage(), isGrp=sel&&term(sel)?.kind==='BG';
  const groupPaths=new Set(Object.keys(groupsEff()).map(absEach));
  $('srcinfo').textContent=isGrp?' · klik na záhlaví segmentu nastaví opakování skupiny':(sel?' · klik na pole přiřadí '+sel:'');
  $('src').innerHTML=S.source.map((n,ni)=>{
    const fields=n.fields.filter(f=>($('empty').checked||f.samples.length||(u[n.path+'|'+f.name]||[]).length)).filter(f=>!q||n.path.toLowerCase().includes(q)||f.name.toLowerCase().includes(q)||(f.label||'').toLowerCase().includes(q)||f.samples.some(s=>s.toLowerCase().includes(q)));
    if(q&&!fields.length) return '';
    const ql=n.qualifier?` <span class="muted">${esc(n.qualifier.field)}=${esc(n.qualifier.code)}${n.qualifier.label?' – '+esc(n.qualifier.label):''}</span>`:'';
    return `<div class="node d${Math.min(n.depth,2)} ${groupPaths.has(n.path)?'grp':''}"><div class="nh" data-n="${ni}"><span class="t">${esc(n.step)}</span><span>${esc(n.label)}</span>${ql}<span class="muted" style="margin-left:auto">${n.count}×</span></div>`+
      fields.map(f=>{const bts=u[n.path+'|'+f.name]||[];
        return `<div class="f" data-n="${ni}" data-f="${esc(f.name)}"><span class="fn">${esc(f.name)}</span><span class="muted">${esc(f.label||'')}</span><span class="fs" title="${esc(f.samples.join(' | '))}">${esc(f.samples.join(' | '))||'<i class="muted">prázdné</i>'}</span>
          <span>${bts.map(b=>`<span class="chip ${b===sel?'cur':''}">${b}</span>`).join('')}</span></div>`;}).join('')+'</div>';}).join('');
  $('src').querySelectorAll('.f').forEach(el=>el.onclick=()=>pickField(S.source[+el.dataset.n],el.dataset.f));
  $('src').querySelectorAll('.nh').forEach(el=>el.onclick=()=>{if(sel&&term(sel).kind==='BG')pickGroupNode(S.source[+el.dataset.n]);});
}
function pickField(node,field){
  if(!sel){alert('Nejdřív vlevo vyberte údaj faktury (BT).');return;}
  const t=term(sel);
  if(t.kind==='BG'){pickGroupNode(node);return;}
  const mg=missingGroup(sel);
  if(mg){$('msg').innerHTML=`<span style="color:var(--warn)">${sel} patří do opakované skupiny ${mg} (${esc(term(mg).name_sk||term(mg).name)}). Nejdřív vlevo vyberte <a href="#" id="goG">${mg}</a> a klikněte na záhlaví segmentu, který se pro ni opakuje.</span>`;
    $('goG').onclick=e=>{e.preventDefault();sel=mg;$('onlyReq').checked=false;renderAll();};return;}
  const rp=relPath(sel,node);
  if(rp.error){$('msg').innerHTML='<span style="color:var(--warn)">'+rp.error+'</span>';return;}
  let rule; const how=tf||(DATE_FIELDS.includes(field)?'date':'');
  if(how==='') rule={path:rp.path,value:field};
  else if(how==='date') rule={path:rp.path,value:field,date:'102'};
  else {rule={derive:how,args:{path:rp.path,value:field}}; if(how==='ref_if_differs_at') rule.args.other='BT-1';}
  if(SCHEMES[sel]&&!rule.derive) rule.scheme=SCHEMES[sel];
  if(node.summary&&!groupOf(sel)) rule.scope='summary';  // totals after the line items (E1EDS01)
  const rs=mode==='add'?[...copyRules(),rule]:[rule];
  $('msg').innerHTML=rp.note?'<span style="color:var(--warn)">'+rp.note+'</span>':`${sel} ← ${esc(node.step)} › ${esc(field)}`;
  setRules(sel,rs);
}

// ---------------------------------------------------------------- findings
function renderFindings(){
  const fs=(prev?.findings||[]).slice().sort((a,b)=>({error:0,warning:1,info:2}[a.severity]-{error:0,warning:1,info:2}[b.severity]));
  $('flist').innerHTML=fs.map((f,i)=>`<div class="fi" data-bt="${esc(f.bt||'')}"><span class="sev s-${f.severity}">${f.severity==='error'?'chyba':f.severity==='warning'?'varování':'info'}</span>
    <span class="code">${esc(f.code)}</span><span>${esc(f.message)}${f.hint?`<div class="hint">${esc(f.hint)}</div>`:''}</span><span class="ctx" style="margin-left:auto">${esc((f.contexts||[]).join(', '))}</span></div>`).join('')||'<div class="muted" style="padding:8px">Bez nálezů.</div>';
  $('flist').querySelectorAll('.fi').forEach(el=>el.onclick=()=>{if(el.dataset.bt&&term(el.dataset.bt)){sel=el.dataset.bt;$('onlyReq').checked=false;renderAll();
    document.querySelector('#terms .row.sel')?.scrollIntoView({block:'center'});}});
}

// ---------------------------------------------------------------- save / match / settings
$('match').onclick=()=>{
  const cand={...S.suggest_match,...client.match};
  $('matchRows').innerHTML=Object.entries(cand).map(([k,v])=>`<label><input type="checkbox" data-k="${esc(k)}" ${k in client.match?'checked':''}> ${esc(k)} = <input type="text" value="${esc(v)}" data-v="${esc(k)}" style="width:auto"></label>`).join('')+
    '<div class="muted">EDI_DC40.SNDPRN = systém SAP odesílatele, E1EDK01.EIGENUINR = IČ DPH dodavatele.</div>';
  $('dlgMatch').showModal();};
$('matchOk').onclick=()=>{const m={};$('matchRows').querySelectorAll('input[type=checkbox]:checked').forEach(c=>{m[c.dataset.k]=$('matchRows').querySelector(`input[data-v="${c.dataset.k}"]`).value.trim();});
  client.match=m;$('dlgMatch').close();};
$('save').onclick=async()=>{
  client.name=$('cname').value.trim();
  if(!client.name){alert('Vyplňte název klienta.');$('cname').focus();return;}
  if(!Object.keys(client.match||{}).length&&!confirm('Mapování nemá podmínky rozpoznání – při kontrole se nepoužije automaticky. Uložit i tak?'))return;
  const j=await api('save',{client}); client.id=j.id; fillClients(j.clients,j.id);
  $('msg').innerHTML=`Uloženo: <span class="seg">${esc(j.path)}</span> – kontrola souborů tohoto klienta ho teď použije automaticky.`;};
$('chdir').onclick=async()=>{const d=prompt('Složka s klientskými mapováními (např. sdílená složka týmu na OneDrive):',$('mdir').textContent);
  if(!d)return; const j=await api('settings',{mapping_dir:d}); $('mdir').textContent=j.mapping_dir; fillClients(j.clients,client.id||'');};
</script></body></html>"""
