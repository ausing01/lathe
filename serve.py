#!/usr/bin/env python3
"""
serve.py - a small interactive viewer for the lathe backend.

Runs a stdlib HTTP server (no dependencies). Open it in a browser on the
machine, or from your phone over Tailscale:  http://<tailscale-ip>:8321/

    python3 serve.py            # listens on 0.0.0.0:8321

Pages:
  /        parametric stock builder - change values, see the profile redraw
  /parts   the four reference parts, profile overlaid with comp output
  /profile element picker + extensions, click elements to select

All geometry is computed by the real backend modules; nothing is reimplemented
in the browser, so what you see is what the post would emit.
"""

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from contour.stock import parametric
from contour.extend import (Extension, extend_profile,
                            blend_extensions, extension_junctions)
from contour.select import (auto_chain, manual, check_selection,
                            assemble, is_bridge, is_blend, blend_key)
from contour.viz import render, render_pickable
from contour.dxf_import import import_dxf
from contour.comp import compensate
from contour.model import Side

PORT = 8321

PARTS = {
    "part1":    ("tests/test_part_1.dxf", Side.OD, 3, 0.03125),
    "part2":    ("tests/test_part_2.dxf", Side.OD, 3, 0.03125),
    "bore":     ("tests/bore.dxf",        Side.ID, 6, 0.0886),
    "backface": ("tests/backface.dxf",    Side.OD, 8, 0.0886),
}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lathe - stock</title>
<style>
 body{font-family:monospace;margin:0;padding:12px;background:#f4f4f4;color:#222}
 h1{font-size:15px;margin:0 0 10px}
 .row{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:10px}
 label{display:flex;flex-direction:column;font-size:11px}
 input{font-family:monospace;font-size:15px;padding:6px;width:110px;
   border:1px solid #bbb;border-radius:3px}
 .checks{display:flex;gap:14px;font-size:12px;align-items:center;margin-bottom:10px}
 #out{background:#fff;border:1px solid #ddd;border-radius:3px;overflow:auto}
 #info{font-size:12px;white-space:pre;margin-top:8px;color:#444}
 nav a{font-size:12px;margin-right:10px}
</style></head><body>
<nav><a href="/">stock</a><a href="/profile">profile</a><a href="/parts">reference parts</a></nav>
<h1>parametric stock</h1>
<div class="row">
 <label>OD (dia)<input id="od" value="3.0"></label>
 <label>bore (dia)<input id="bore" value="0"></label>
 <label>z face<input id="zf" value="0.1"></label>
 <label>z back<input id="zb" value="-3.0"></label>
</div>
<div class="checks">
 <label style="flex-direction:row;gap:4px"><input type="checkbox" id="of" checked>face open</label>
 <label style="flex-direction:row;gap:4px"><input type="checkbox" id="oo" checked>OD open</label>
 <label style="flex-direction:row;gap:4px"><input type="checkbox" id="ob">back open</label>
</div>
<div id="out">loading...</div>
<div id="info"></div>
<script>
async function go(){
 const q=new URLSearchParams({od:od.value,bore:bore.value,zf:zf.value,zb:zb.value,
   of:of.checked?1:0,oo:oo.checked?1:0,ob:ob.checked?1:0});
 const r=await fetch('/stock.json?'+q); const j=await r.json();
 out.innerHTML=j.svg||''; info.textContent=j.info||j.error||'';
}
for(const el of document.querySelectorAll('input')) el.addEventListener('input',go);
go();
</script></body></html>"""

PARTS_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lathe - parts</title>
<style>
 body{font-family:monospace;margin:0;padding:12px;background:#f4f4f4;color:#222}
 h2{font-size:13px;margin:14px 0 6px}
 .card{background:#fff;border:1px solid #ddd;border-radius:3px;margin-bottom:14px;overflow:auto}
 nav a{font-size:12px;margin-right:10px}
 pre{font-size:11px;color:#555;margin:6px 0 0}
</style></head><body>
<nav><a href="/">stock</a><a href="/profile">profile</a><a href="/parts">reference parts</a></nav>
__BODY__
</body></html>"""


def stock_svg(q):
    od = float(q.get("od", ["3.0"])[0])
    bore = float(q.get("bore", ["0"])[0])
    zf = float(q.get("zf", ["0.1"])[0])
    zb = float(q.get("zb", ["-3.0"])[0])
    s = parametric(od=od, z_face=zf, z_back=zb, id_bore=bore,
                   open_face=q.get("of", ["1"])[0] == "1",
                   open_od=q.get("oo", ["1"])[0] == "1",
                   open_back=q.get("ob", ["0"])[0] == "1")
    svg = render([], stock=s, width=860,
                 title=f"bar od{od} bore{bore} z {zf}..{zb}")
    return {"svg": svg, "info": s.describe()}


def _ext_from(q, pfx):
    d = q.get(pfx + "d", [""])[0]
    ang = q.get(pfx + "a", [""])[0]
    if not d and not ang:
        return None
    ln = q.get(pfx + "l", [""])[0]
    return Extension(direction=d or "+Z",
                     length=float(ln) if ln.strip() else None,
                     angle=float(ang) if ang.strip() else None,
                     clearance=float(q.get(pfx + "c", ["0"])[0] or 0))


def extend_svg(q):
    od = float(q.get("od", ["5.5"])[0])
    zf = float(q.get("zf", ["0.15"])[0])
    zb = float(q.get("zb", ["-4.2"])[0])
    st = parametric(od=od, z_face=zf, z_back=zb)
    c, _ = import_dxf("tests/test_part_1.dxf", side=Side.OD, name="part1")
    ex = extend_profile(c, st, start=_ext_from(q, "s"), end=_ext_from(q, "e"))
    svg = render([("profile", c, "original profile"),
                  ("tool", ex, "extended profile")],
                 stock=st, width=860, title="part 1 with extensions")
    s0, s1 = ex.elements[0].start, ex.elements[-1].end
    info = (f"extended start  z={s0.z:+.4f} r={s0.r:.4f}  X={2*s0.r:.4f}\n"
            f"extended end    z={s1.z:+.4f} r={s1.r:.4f}  X={2*s1.r:.4f}\n"
            f"elements {len(c.elements)} -> {len(ex.elements)}")
    return {"svg": svg, "info": info}


def _load_pick(name):
    path, side, _tip, _nose = PICK_PARTS[name]
    return import_dxf(path, side=side, name=name)[0]


def pick_meta(q):
    c = _load_pick(q.get("part", ["part1"])[0])
    desc = []
    for e in c.elements:
        desc.append(f"{e.kind} src{e.source_id}")
    return {"n": len(c.elements), "closed": c.closed, "elements": desc}


def pick_svg(q):
    name = q.get("part", ["part1"])[0]
    c = _load_pick(name)
    rev = q.get("rev", ["0"])[0] == "1"
    if q.get("mode", ["auto"])[0] == "manual":
        raw = q.get("idx", [""])[0]
        idx = [int(x) for x in raw.split(",") if x != ""]
        sel = manual(c, idx, forward=not rev)
        how = f"manual {idx}"
    else:
        si = int(q.get("si", ["0"])[0])
        ei = int(q.get("ei", [str(len(c.elements) - 1)])[0])
        sel = auto_chain(c, si, ei, forward=not rev)
        how = f"auto chain {si} -> {ei} {'backward' if rev else 'forward'}"
    probs = check_selection(sel)
    svg = render([("stock", c, "full DXF"), ("tool", sel, "selected profile")],
                 width=860, title=f"{name} - {how}")
    info = (f"{how}\nclosed source: {c.closed}\n"
            f"selected {len(sel.elements)} of {len(c.elements)} elements\n"
            f"source ids: {[e.source_id for e in sel.elements]}\n"
            f"continuity: {probs if probs else 'clean chain'}")
    return {"svg": svg, "info": info}



PROFILE_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lathe - profile</title>
<style>
 body{font-family:monospace;margin:0;padding:10px;background:#f4f4f4;color:#222}
 nav a{font-size:12px;margin-right:10px}
 h1{font-size:14px;margin:6px 0 8px}
 .grid{display:grid;grid-template-columns:190px 1fr 260px;gap:10px;
   align-items:start}
 .panel{background:#fff;border:1px solid #ddd;border-radius:3px;padding:8px}
 .panel h2{font-size:11px;margin:0 0 6px;color:#555;font-weight:normal;
   text-transform:uppercase;letter-spacing:.5px}
 #list{max-height:60vh;overflow:auto}
 .el{font-size:11px;padding:4px 6px;border-radius:3px;cursor:pointer;
   border:1px solid transparent;display:flex;justify-content:space-between;gap:6px}
 .el:hover{background:#f0f4fa}
 .el.on{background:#fdecec;border-color:#f0b8b8}
 .el.focus{outline:2px solid #1060c0}
 .el .tag{color:#888}
 .el.off{opacity:.45;text-decoration:line-through}
 .el.ext{background:#eef7ee;border-color:#cfe6cf;color:#2a6b2a}
 .el.bridge{background:#fff6e6;border-color:#f0dcb8;color:#8a6412}
 .el.blend{background:#eef2fb;border-color:#c8d4ee;color:#33509c}
 .el.nopick{cursor:pointer}
 .el .pad{display:inline-block;width:15px}
 .el input{margin:0 4px 0 0}
 .ends{font-size:10px;color:#888;margin:3px 0}
 .row{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin-bottom:6px}
 label{display:flex;flex-direction:column;font-size:11px}
 select,input{font-family:monospace;font-size:13px;padding:4px;
   border:1px solid #bbb;border-radius:3px}
 input{width:78px}
 input.badfit{background:#ffe9a3;border-color:#d9a300;color:#6b4e00;
   font-weight:bold}
 fieldset{border:1px solid #ccc;border-radius:3px;margin:0 0 8px;padding:7px}
 legend{font-size:11px;color:#555}
 .checks{display:flex;gap:14px;font-size:12px;align-items:center;flex-wrap:wrap}
 .checks label{flex-direction:row;gap:5px;align-items:center}
 button{font-family:monospace;font-size:11px;padding:4px 8px;cursor:pointer;
   border:1px solid #bbb;border-radius:3px;background:#fff}
 .hint{font-size:11px;color:#666;margin:4px 0 6px}
 #info{font-size:11px;white-space:pre;color:#444;margin-top:6px}
 table.props{width:100%;border-collapse:collapse;font-size:11px}
 table.props td{padding:2px 3px;border-bottom:1px solid #f0f0f0}
 table.props td.k{color:#777;white-space:nowrap}
 table.props td.v{text-align:right}
 .sec{margin-top:8px;font-size:10px;color:#888;text-transform:uppercase}
</style></head><body>
<nav><a href="/">stock</a><a href="/profile">profile</a><a href="/parts">reference parts</a></nav>

<div class="row">
 <label>part<select id="part">
  <option value="part1">part1 (open, 9)</option>
  <option value="part2">part2 (open, 7)</option>
  <option value="bore">bore (open, 4)</option>
  <option value="backface">backface (open, 3)</option>
  <option value="stock_closed">stock_closed (CLOSED, 4)</option>
 </select></label>
 <label>stock OD<input id="od" value="5.5"></label>
 <label>z face<input id="zf" value="0.15"></label>
 <label>z back<input id="zb" value="-4.2"></label>
 <label>&nbsp;<button id="showstock">stock on/off</button></label>
</div>

<fieldset><legend>extensions &mdash; each segment has its own angle; clearance lives in the toolpath</legend>
<div class="row">
 <label>start 1 dir<select id="sd" class="dir"></select></label>
 <label>len<input id="sl" placeholder="to stock"></label>
 <label>angle<input id="sa" placeholder="deg"></label>
 <label>start 2 len<input id="sl2" placeholder="len"></label>
 <label>angle<input id="sa2" placeholder="deg"></label>
</div>
<div class="row">
 <label>end 1 dir<select id="ed" class="dir"></select></label>
 <label>len<input id="el" placeholder="to stock"></label>
 <label>angle<input id="ea" placeholder="deg"></label>
 <label>end 2 len<input id="el2" placeholder="len"></label>
 <label>angle<input id="ea2" placeholder="deg"></label>
</div>
</fieldset>

<div class="grid">
 <div class="panel">
  <h2>elements</h2>
  <div class="row" style="gap:4px;margin-bottom:4px">
   <button id="revlist">reverse</button>
   <button id="delstart">del start</button>
   <button id="delend">del end</button>
   <button id="reset">reset</button>
  </div>
  <div class="ends" id="hint">top = start &nbsp;&middot;&nbsp; bottom = end</div>
  <div id="list"></div>
 </div>
 <div class="panel">
  <div id="out">loading...</div>
  <div id="info"></div>
 </div>
 <div class="panel">
  <h2>element detail</h2>
  <div id="props">click an element</div>
  <div id="blendbox" style="display:none">
   <div class="sec">blend to next element</div>
   <div class="row" style="gap:6px">
    <label>radius<input id="blendr" placeholder="0"></label>
    <label>&nbsp;<button id="blendset">apply</button></label>
    <label>&nbsp;<button id="blendclr">clear</button></label>
   </div>
   <div class="ends" id="blendnote"></div>
  </div>
 </div>
</div>

<script>
let N=0, SEL=[], A=null, B=null, STOCK=true, FOCUS=null;
let ORDER=null, OFF=new Set(), FLIP=false, BLENDS={};
const DIRS=['','+Z','-Z','+X','-X'];
for(const s of document.querySelectorAll('select.dir'))
 s.innerHTML=DIRS.map(d=>`<option value="${d}">${d||'(none)'}</option>`).join('');
document.getElementById('ed').value='+X';

function autoMode(){return true;}
function setHint(){
 let t;
 if(ORDER&&ORDER.length) t="top = start \u00b7 bottom = end \u00b7 click outside to extend";
 else if(A===null) t="click the START element";
 else if(B===null) t="start = "+A+" \u00b7 click the END element";
 else t="chain "+A+" to "+B;
 hint.innerHTML=t;
}
async function loadPart(){
 const r=await fetch('/pick_meta.json?part='+part.value); const j=await r.json();
 N=j.n; SEL=[...Array(N).keys()]; A=null; B=null; FOCUS=null;
 ORDER=null; OFF=new Set(); FLIP=false; BLENDS={}; go();
}
function ext(pfx){
 const d=document.getElementById(pfx+'d').value;
 const a=document.getElementById(pfx+'a').value;
 const l=document.getElementById(pfx+'l').value;
 return (d||a.trim())? `${d}|${l}|${a}` : '';
}
async function go(){
 setHint();
 const q=new URLSearchParams({part:part.value,od:od.value,zf:zf.value,zb:zb.value,
  mode:'auto', rev:0, stock:STOCK?1:0});
 q.set('s1', ext('s'));
 q.set('s2', segOf(null,'sl2','sa2'));
 q.set('e1', ext('e'));
 q.set('e2', segOf(null,'el2','ea2'));
 if(FOCUS!==null) q.set('focus',FOCUS);
 if(ORDER!==null){
  q.set('order', ORDER.join(','));
  q.set('off', [...OFF].join(','));
  q.set('flip', FLIP?1:0);
  q.set('blends', Object.entries(BLENDS).map(([k,v])=>k+':'+v).join(','));
 } else if(autoMode()){
  if(A!==null)q.set('si',A); if(B!==null)q.set('ei',B);
 } else q.set('idx',SEL.join(','));
 const r=await fetch('/profile.json?'+q); const j=await r.json();
 out.innerHTML=j.svg||''; info.textContent=j.info||j.error||'';
 if(ORDER===null && j.order && j.order.length) ORDER=j.order.slice();
 ROWS=j.rows||[]; BERR=j.blend_errors||{};
 renderList(ROWS);
 pruneBlends();
 renderProps(j.props);
 attach();
}
function segOf(di,li,ai){
 // segment 2 has no direction control - it is a manual length/angle nudge
 const l=document.getElementById(li).value, a=document.getElementById(ai).value;
 return (l.trim()||a.trim())? `|${l}|${a}` : '';
}
function shown(){ return FLIP ? [...(ORDER||[])].reverse() : (ORDER||[]); }
function renderList(rows){
 if(!rows || rows.length===0){
  list.innerHTML='<div class="ends">nothing selected</div>'; return; }
 let h='';
 for(const r of rows){
  const isReal = (r.check !== null && r.check !== undefined);
  const off = isReal && OFF.has(parseInt(r.key));
  const cls = [ 'el', isReal?'on':'nopick', r.cls,
                off?'off':'', String(FOCUS)===String(r.key)?'focus':'' ]
              .filter(Boolean).join(' ');
  const box = isReal
   ? `<input type="checkbox" class="cb" data-cb="${r.key}" ${off?'':'checked'}>`
   : `<span class="pad"></span>`;
  const num = isReal ? r.key : '';
  h += `<div class="${cls}" data-el="${r.key}">`
     + `<span>${box}${num}</span>`
     + `<span class="tag">${r.label}</span></div>`;
 }
 list.innerHTML=h;
 for(const el of document.querySelectorAll('.el'))
  el.addEventListener('click',ev=>{
   if(ev.target.classList.contains('cb')) return;
   FOCUS=el.dataset.el; go();
  });
 for(const cb of document.querySelectorAll('.cb'))
  cb.addEventListener('change',()=>{
   const i=parseInt(cb.dataset.cb);
   if(cb.checked) OFF.delete(i); else OFF.add(i);
   go();
  });
}
let ROWS=[], BERR={};
function jkeyOf(rowKey){
 const r=ROWS.find(x=>String(x.key)===String(rowKey));
 return r? (r.jkey||null) : null;
}
function pruneBlends(){
 // Drop blends whose junction no longer exists. Re-checking an element closes
 // a gap and removes the bridge, so a blend that sat on either end of that
 // bridge goes with it. The server tells us which junctions are live.
 const valid=new Set(ROWS.map(r=>r.jkey).filter(Boolean));
 let dropped=0;
 for(const key of Object.keys(BLENDS))
  if(!valid.has(key)){ delete BLENDS[key]; dropped++; }
 return dropped;
}
function junctionLabel(key){
 if(!key) return '';
 if(key.indexOf('|')>=0){
  const p=key.split('|');
  return 'element '+p[0]+' \u2194 bridge';
 }
 const p=key.split('-');
 return 'element '+p[0]+' \u2194 element '+p[1];
}
function updateBlendBox(){
 const key = FOCUS===null? null : jkeyOf(FOCUS);
 if(!key){ blendbox.style.display='none'; return; }
 blendbox.style.display='';
 blendr.value = BLENDS[key]||'';
 const err = BERR[key];
 if(err){
  blendr.classList.add('badfit');
  blendnote.textContent = junctionLabel(key) +
    ' \u00b7 R'+err.asked+' does not fit \u00b7 max R'+err.max;
 } else {
  blendr.classList.remove('badfit');
  blendnote.textContent = junctionLabel(key) +
    ' \u00b7 stays put if the chain is reversed';
 }
}
function renderProps(p){
 updateBlendBox();
 if(!p){props.textContent='click an element';return;}
 const f=(v,n=4)=>(typeof v==='number')? v.toFixed(n): v;
 let h='<table class="props">';
 const row=(k,v)=>{h+=`<tr><td class="k">${k}</td><td class="v">${v}</td></tr>`;};
 row('element', p.index);
 const org = p.origin ? p.origin : 'DXF element';
 row('kind', p.kind);
 row('origin', org);
 row('DXF entity', (p.source_id===null||p.source_id===undefined)? '&mdash;' : p.source_id);
 h+='</table><div class="sec">start</div><table class="props">';
 row('Z', f(p.start_z)); row('X dia', f(p.start_x)); row('radius', f(p.start_r));
 h+='</table><div class="sec">end</div><table class="props">';
 row('Z', f(p.end_z)); row('X dia', f(p.end_x)); row('radius', f(p.end_r));
 h+='</table><div class="sec">geometry</div><table class="props">';
 row('length', f(p.length));
 if(p.kind==='line'){
  row('angle from axis', f(p.angle_from_axis,2)+'&deg;');
  row('included angle', f(p.included_angle,2)+'&deg;');
  row('dZ', f(p.dz)); row('dR', f(p.dr));
 } else {
  row('radius', f(p.radius));
  row('centre Z', f(p.center_z));
  row('centre X dia', f(p.center_x));
  row('direction', p.direction);
  row('sweep', f(p.sweep,2)+'&deg;');
 }
 h+='</table>';
 props.innerHTML=h;
}
function attach(){
 for(const h of document.querySelectorAll('.hit')){
  h.addEventListener('click',()=>{
   const i=parseInt(h.dataset.idx);
   if(ORDER && ORDER.length){
    if(ORDER.indexOf(i)<0){
     // clicked beyond the chain: grow it to reach that element
     const lo=Math.min(...ORDER), hi=Math.max(...ORDER);
     const desc = ORDER.length>1 && ORDER[0]>ORDER[ORDER.length-1];
     let a,b;
     if(i>hi){a=lo;b=i;} else if(i<lo){a=i;b=hi;} else {a=lo;b=hi;}
     let rng=[]; for(let k=a;k<=b;k++) rng.push(k);
     ORDER = desc? rng.reverse() : rng;
     pruneBlends();
    }
   } else if(autoMode()){
    if(A===null||B!==null){A=i;B=null;} else {B=i;}
   } else {
    const k=SEL.indexOf(i);
    if(k<0) SEL.push(i); else SEL.splice(k,1);
    SEL.sort((x,y)=>x-y);
   }
   FOCUS=String(i);
   go();
  });
 }
}
document.getElementById('reset').addEventListener('click',()=>{
 A=null;B=null;SEL=[...Array(N).keys()];FOCUS=null;ORDER=null;OFF=new Set();FLIP=false;BLENDS={};go();});
document.getElementById('revlist').addEventListener('click',()=>{
 if(ORDER){FLIP=!FLIP;go();}});
function dropIdx(v){
 const k=ORDER.indexOf(v); if(k>=0) ORDER.splice(k,1);
 OFF.delete(v); if(String(FOCUS)===String(v)) FOCUS=null;
 pruneBlends();
}
document.getElementById('delstart').addEventListener('click',()=>{
 const d=shown(); if(ORDER&&d.length>1){dropIdx(d[0]);go();}});
document.getElementById('delend').addEventListener('click',()=>{
 const d=shown(); if(ORDER&&d.length>1){dropIdx(d[d.length-1]);go();}});
showstock.addEventListener('click',()=>{STOCK=!STOCK;go();});
function applyBlend(){
 // evaluated only on apply or Enter - never while typing, since a partial
 // entry like "0." parses as 0 and would wipe the field mid-keystroke
 const key=jkeyOf(FOCUS); if(!key) return;
 const v=parseFloat(blendr.value);
 if(v>0) BLENDS[key]=v; else delete BLENDS[key];
 go();
}
document.getElementById('blendset').addEventListener('click',applyBlend);
blendr.addEventListener('keydown',ev=>{
 if(ev.key==='Enter'){ ev.preventDefault(); applyBlend(); }
});
document.getElementById('blendclr').addEventListener('click',()=>{
 const key=jkeyOf(FOCUS); if(!key) return;
 delete BLENDS[key]; blendr.value=''; go();});
part.addEventListener('change',loadPart);
for(const e of ['od','zf','zb','sd','sl','sa','sl2','sa2',
                'ed','el','ea','el2','ea2'])
 document.getElementById(e).addEventListener('input',go);
loadPart();
</script></body></html>"""


PICK_PARTS = dict(PARTS)
PICK_PARTS["stock_closed"] = ("tests/stock_closed.dxf", Side.OD, 3, 0.03125)


def _load_pick(name):
    path, side, _t, _n = PICK_PARTS[name]
    return import_dxf(path, side=side, name=name)[0]


def pick_meta(q):
    c = _load_pick(q.get("part", ["part1"])[0])
    return {"n": len(c.elements), "closed": c.closed,
            "elements": [f"{e.kind} src{e.source_id}" for e in c.elements]}


def _seg(spec):
    """Parse one 'dir|len|angle' segment string into an Extension, or None."""
    if not spec:
        return None
    parts = (spec.split("|") + ["", "", ""])[:3]
    d, ln, ang = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if not d and not ang:
        return None
    return Extension(direction=d or "+Z",
                     length=float(ln) if ln else None,
                     angle=float(ang) if ang else None)


def _ext_list(q, k1, k2):
    """Extension chain for one end: up to two segments, applied outward."""
    out = []
    for k in (k1, k2):
        e = _seg(q.get(k, [""])[0])
        if e is not None:
            out.append(e)
    return out or None


def _props(e, i):
    from contour.model import element_properties
    return element_properties(e, i)


def _labels(c):
    out = {}
    for i, e in enumerate(c.elements):
        pr = _props(e, i)
        out[i] = (f"line {_fmt_ang(pr['angle_from_axis'])}\u00b0"
                  if e.kind == "line"
                  else f"arc R{pr['radius']:.4f} {pr['direction']}")
    return out


def _rows_full(c, final, order, off, flip=False, sel=None):
    """
    Rows for the whole chain in true cut order, built from the assembled
    sequence rather than reconstructed, so blends, bridges and extensions land
    exactly where they are in the geometry.

    Unchecked elements are listed immediately AFTER the bridge that replaces
    them, so the bridge reads first and the skipped elements sit with it,
    keeping their checkbox so they can be put back.
    """
    def shape_of(e, pos=0):
        pr = _props(e, pos)
        return (f"line {_fmt_ang(pr['angle_from_axis'])}\u00b0"
                if e.kind == "line"
                else f"arc R{pr['radius']:.4f} {pr['direction']}")

    rows = []
    meta = getattr(sel, "meta", None)

    # Leading synthetic run: everything before the first real element. That is
    # the start extensions AND any blends between them, in order.
    reals = [n for n, e in enumerate(final.elements)
             if getattr(e, "origin", None) is None]
    first_real = reals[0] if reals else len(final.elements)
    last_real = reals[-1] if reals else -1
    for n in range(first_real):
        e = final.elements[n]
        o = getattr(e, "origin", None)
        if o == "blend":
            rows.append({"key": f"x{n}",
                         "label": f"blend \u00b7 {shape_of(e, n)}",
                         "check": None, "cls": "blend"})
        else:
            rows.append({"key": f"x{n}",
                         "label": f"start ext \u00b7 {shape_of(e, n)}",
                         "check": None, "cls": "ext"})

    if meta is None:
        # no assembly metadata (shouldn't happen) - fall back to plain order
        for i in order:
            rows.append({"key": str(i), "label": _label_for(c, i),
                         "check": i not in off, "cls": "real"})
        _annotate_junctions(rows)
        return rows

    # map assembled elements back to positions in `final` (extensions shift it)
    shift = sum(1 for e in final.elements
                if getattr(e, "origin", None) == "extension"
                and final.elements.index(e) < 1)
    base = 0
    for n, e in enumerate(final.elements):
        if getattr(e, "origin", None) != "extension":
            base = n
            break

    off_order = [i for i in order if i in off]
    used_off = set()

    for k, (kind, val) in enumerate(meta):
        pos = base + k
        e = final.elements[pos] if pos < len(final.elements) else None
        if kind == "real":
            rows.append({"key": str(val), "label": _label_for(c, val),
                         "check": True, "cls": "real"})
        elif kind == "blend":
            rows.append({"key": f"x{pos}",
                         "label": f"blend \u00b7 {shape_of(e, pos)}",
                         "check": None, "cls": "blend"})
        elif kind == "bridge":
            rows.append({"key": f"x{pos}",
                         "label": f"bridge \u00b7 {shape_of(e, pos)}",
                         "check": None, "cls": "bridge"})
            # the elements this bridge replaced, listed with it
            a_i, b_i = val
            span = []
            try:
                ia, ib = order.index(a_i), order.index(b_i)
                lo, hi = min(ia, ib), max(ia, ib)
                span = [order[t] for t in range(lo + 1, hi)]
            except ValueError:
                span = []
            for j in span:
                if j in off and j not in used_off:
                    used_off.add(j)
                    rows.append({"key": str(j), "label": _label_for(c, j),
                                 "check": False, "cls": "real"})

    # any unchecked elements not covered by a bridge (they sat at a chain end)
    for j in off_order:
        if j not in used_off:
            rows.append({"key": str(j), "label": _label_for(c, j),
                         "check": False, "cls": "real"})

    # Trailing synthetic run: everything after the last real element.
    for n in range(last_real + 1, len(final.elements)):
        e = final.elements[n]
        o = getattr(e, "origin", None)
        if o == "blend":
            rows.append({"key": f"x{n}",
                         "label": f"blend \u00b7 {shape_of(e, n)}",
                         "check": None, "cls": "blend"})
        else:
            rows.append({"key": f"x{n}",
                         "label": f"end ext \u00b7 {shape_of(e, n)}",
                         "check": None, "cls": "ext"})

    _annotate_junctions(rows)
    _annotate_extension_junctions(rows)
    return rows



def _annotate_extension_junctions(rows):
    """
    Junction keys for extension rows: s1/s2 counting inward from the start,
    e1/e2 counting outward from the end. s1 is where the innermost start
    extension meets the profile; e1 is where the profile meets the innermost
    end extension.
    """
    firsts = [n for n, r in enumerate(rows)
              if r["cls"] == "ext" and r["label"].startswith("start")]
    lasts = [n for n, r in enumerate(rows)
             if r["cls"] == "ext" and r["label"].startswith("end")]
    # start extensions are listed outermost first, so the innermost carries s1
    for k, n in enumerate(reversed(firsts)):
        rows[n]["jkey"] = f"s{k + 1}"
    # the junction before the innermost end extension belongs to the row above
    for k, n in enumerate(lasts):
        prev = n - 1
        if prev >= 0 and k == 0:
            rows[prev]["jkey"] = "e1"
        rows[n]["jkey"] = f"e{k + 2}" if k + 1 < len(lasts) else None
    return rows


def _annotate_junctions(rows):
    """
    Tag each row with `jkey`: the junction that follows it, or None.

    Junctions run between geometric neighbours - real kept elements and bridges.
    Unchecked rows and blend rows are skipped, so a row whose junction already
    carries a blend still reports the same key and the radius stays editable.

      real i / real j        ->  "i-j"
      real i / bridge        ->  "i|far"     far = real element past the bridge
      bridge / real j        ->  "j|far"     far = real element before it
    """
    geo = [r for r in rows
           if (r["cls"] == "bridge") or (r["cls"] == "real" and r["check"])]
    for r in rows:
        r["jkey"] = None
    for k in range(len(geo) - 1):
        a, b = geo[k], geo[k + 1]
        if a["cls"] == "real" and b["cls"] == "real":
            ia, ib = int(a["key"]), int(b["key"])
            key = f"{min(ia, ib)}-{max(ia, ib)}"
        elif a["cls"] == "real" and b["cls"] == "bridge":
            nxt = geo[k + 2] if k + 2 < len(geo) else None
            if nxt is None or nxt["cls"] != "real":
                continue
            key = f"{int(a['key'])}|{int(nxt['key'])}"
        elif a["cls"] == "bridge" and b["cls"] == "real":
            prv = geo[k - 1] if k >= 1 else None
            if prv is None or prv["cls"] != "real":
                continue
            key = f"{int(b['key'])}|{int(prv['key'])}"
        else:
            continue
        a["jkey"] = key
    return rows


def _fmt_ang(v):
    """Angle to three decimals, trailing zeros dropped."""
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _label_for(c, i):
    e = c.elements[i]
    pr = _props(e, i)
    return (f"line {_fmt_ang(pr['angle_from_axis'])}\u00b0" if e.kind == "line"
            else f"arc R{pr['radius']:.4f} {pr['direction']}")


def _rows(final, idx):
    """
    Describe the full cut sequence, in order, one row per element.

    Real DXF elements carry their contour index as the key and get a checkbox.
    Synthetic elements (extensions, bridges) have no contour index, so they get
    a positional key and no checkbox - they are consequences of the chain, not
    things to pick.
    """
    out = []
    ptr = 0
    seen_real = False
    n_real = len(idx)
    for pos, e in enumerate(final.elements):
        origin = getattr(e, "origin", None)
        pr = _props(e, pos)
        shape = (f"line {_fmt_ang(pr['angle_from_axis'])}\u00b0"
                 if e.kind == "line"
                 else f"arc R{pr['radius']:.4f} {pr['direction']}")
        if origin is None:
            key = str(idx[ptr]) if ptr < n_real else f"x{pos}"
            if ptr < n_real:
                ptr += 1
                seen_real = True
            out.append({"key": key, "label": shape, "check": True,
                        "cls": "real"})
        elif origin == "extension":
            where = "end ext" if seen_real else "start ext"
            out.append({"key": f"x{pos}", "label": f"{where} \u00b7 {shape}",
                        "check": False, "cls": "ext"})
        else:
            out.append({"key": f"x{pos}", "label": f"bridge \u00b7 {shape}",
                        "check": False, "cls": "bridge"})
    return out


def _focus_props_row(q, c, final, idx):
    """Properties for the focused row: a contour index, or x<pos> in the
    assembled cut sequence."""
    f = q.get("focus", [None])[0]
    if f is None:
        return None
    if f.startswith("x"):
        pos = int(f[1:])
        if 0 <= pos < len(final.elements):
            return _props(final.elements[pos], pos)
        return None
    i = int(f)
    return _props(c.elements[i], i) if 0 <= i < len(c.elements) else None


def _focus_props(q, c):
    f = q.get("focus", [None])[0]
    if f is None:
        return None
    i = int(f)
    return _props(c.elements[i], i) if 0 <= i < len(c.elements) else None


def profile_svg(q):
    name = q.get("part", ["part1"])[0]
    c = _load_pick(name)
    n = len(c.elements)
    rev = q.get("rev", ["0"])[0] == "1"
    want_stock = q.get("stock", ["1"])[0] == "1"

    st = None
    if want_stock:
        st = parametric(od=float(q.get("od", ["5.5"])[0]),
                        z_face=float(q.get("zf", ["0.15"])[0]),
                        z_back=float(q.get("zb", ["-4.2"])[0]))

    notes = []

    # An explicit order (sent once the client owns the list) wins: it carries
    # the cut direction, and `off` lists elements to bridge over.
    raw_order = q.get("order", [""])[0]
    if raw_order.strip():
        order = [int(x) for x in raw_order.split(",") if x != ""]
        off = {int(x) for x in q.get("off", [""])[0].split(",") if x != ""}
        flip = q.get("flip", ["0"])[0] == "1"
        blends = _blends(q)
        sel, anotes = assemble(c, order, off, flip=flip, blends=blends)
        notes += anotes
        how = (f"chain of {len(order)} element(s)"
               + (f", {len(off)} skipped" if off else "")
               + (" (reversed)" if flip else ""))
        idx = [i for i in order if i not in off]
        if not sel.elements:
            return {"svg": render_pickable(c, selected=(), stock=st,
                                           title=f"{name} - nothing kept"),
                    "info": "every element is unchecked",
                    "order": order, "labels": _labels(c),
                    "props": _focus_props(q, c)}
        return _finish(q, c, name, st, sel, idx, order, how,
                       probs_extra=notes, off=off)

    if q.get("mode", ["auto"])[0] == "manual":
        raw = q.get("idx", [""])[0]
        idx = [int(x) for x in raw.split(",") if x != ""]
        how = f"manual {idx}"
        sel = manual(c, idx, forward=not rev) if idx else None
    else:
        si = q.get("si", [None])[0]
        ei = q.get("ei", [None])[0]
        if si is None:
            return {"svg": render_pickable(c, selected=(), stock=st,
                                           title=f"{name} - click a start element"),
                    "info": "auto chain: click the START element",
                    "order": [], "labels": _labels(c),
                    "props": _focus_props(q, c)}
        si = int(si)
        if ei is None:
            e0 = c.elements[si]
            # walking backward reverses the element, so its entry point is the
            # original end
            gdot = ((e0.end.z, e0.end.r) if rev else (e0.start.z, e0.start.r))
            rdot = ((e0.start.z, e0.start.r) if rev else (e0.end.z, e0.end.r))
            return {"svg": render_pickable(
                        c, selected={si}, stock=st,
                        title=f"{name} - start {si}, click the end",
                        start_dot=gdot, end_dot=rdot),
                    "info": f"auto chain: start = {si}, now click the END "
                            f"element\ngreen dot is the chain entry point; "
                            f"red is where this element finishes\n"
                            f"press reset to unpick it"}
        ei = int(ei)
        how = f"auto chain {si} -> {ei} {'backward' if rev else 'forward'}"
        try:
            sel = auto_chain(c, si, ei, forward=not rev)
            idx = indices_for_chain(c, si, ei, not rev)
        except ValueError as e:
            return {"svg": render_pickable(c, selected={si, ei}, stock=st,
                                           title=f"{name} - {how}"),
                    "info": f"{how}\nERROR: {e}\n"
                            f"try ticking 'reverse direction'"}
    if sel is None:
        return {"svg": render_pickable(c, selected=(), stock=st,
                                       title=f"{name} - nothing selected"),
                "info": "no elements selected",
                "order": [], "labels": _labels(c),
                "props": _focus_props(q, c)}

    if q.get("mode", ["auto"])[0] == "manual":
        idx = [int(x) for x in q.get("idx", [""])[0].split(",") if x != ""]

    return _finish(q, c, name, st, sel, idx, list(idx), how, probs_extra=notes)


def _blends(q):
    """Parse 'i-j:R,i-j:R' into {(i,j): radius} on the unordered pair."""
    raw = q.get("blends", [""])[0]
    out = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        pair, r = part.split(":", 1)
        try:
            rv = float(r)
        except ValueError:
            continue
        if rv <= 0:
            continue
        if "|" in pair:
            # a bridge-end junction: keyed as "touching|far", kept as a string
            out[pair] = rv
        elif pair and pair[0] in "se" and pair[1:].isdigit():
            # an extension junction: s1/s2 inward from the start, e1/e2 outward
            out[pair] = rv
        elif "-" in pair:
            a, b = pair.split("-", 1)
            try:
                out[blend_key(int(a), int(b))] = rv
            except ValueError:
                continue
    return out


def _finish(q, c, name, st, sel, idx, order, how, probs_extra=(), off=()):
    notes = list(probs_extra)
    probs = check_selection(sel)
    ext = None
    ext_errors = {}
    e0 = _ext_list(q, "s1", "s2")
    e1 = _ext_list(q, "e1", "e2")
    if e0 or e1:
        try:
            ext = extend_profile(sel, st, start=e0, end=e1)
            ext, xnotes = blend_extensions(ext, _blends(q))
            notes += xnotes
            ext_errors = getattr(ext, "blend_errors", {}) or {}
            added = sum(1 for e in ext.elements
                        if getattr(e, "origin", None) == "extension")
            asked = len(e0 or []) + len(e1 or [])
            notes.append(f"extensions: {added} of {asked} segment(s) added"
                         + ("  (zero-length dropped)" if added < asked else ""))
        except ValueError as err:
            notes.append(f"extension ERROR: {err}")
            ext = None

    sd = (sel.elements[0].start.z, sel.elements[0].start.r)
    ed = (sel.elements[-1].end.z, sel.elements[-1].end.r)
    fkey = q.get("focus", [None])[0]
    f_idx, f_el = None, None
    if fkey is not None:
        if fkey.startswith("x"):
            fp = int(fkey[1:])
            src = ext if ext is not None else sel
            if 0 <= fp < len(src.elements):
                f_el = src.elements[fp]
        else:
            fi = int(fkey)
            if 0 <= fi < len(c.elements):
                f_idx = fi
    # Triangles mark the extreme ends of the CUT: only the outermost extension
    # at each end, not every segment.
    stri = etri = None
    if ext is not None and ext.elements:
        f0, f1 = ext.elements[0], ext.elements[-1]
        if getattr(f0, "origin", None) == "extension":
            stri = (f0.start.z, f0.start.r,
                    f0.end.z - f0.start.z, f0.end.r - f0.start.r)
        if getattr(f1, "origin", None) == "extension":
            etri = (f1.end.z, f1.end.r,
                    f1.end.z - f1.start.z, f1.end.r - f1.start.r)

    svg = render_pickable(c, selected=idx, extended=ext, stock=st,
                          title=f"{name} - {how}",
                          start_dot=sd, end_dot=ed,
                          focus=f_idx, focus_element=f_el,
                          start_tri=stri, end_tri=etri)

    final = ext or sel
    rows = _rows_full(c, final, order, set(off),
                      flip=q.get("flip", ["0"])[0] == "1", sel=sel)
    labels = _labels(c)
    props = _focus_props_row(q, c, final, idx)
    nbridge = sum(1 for e in sel.elements if is_bridge(e))
    p0, p1 = (ext or sel).elements[0].start, (ext or sel).elements[-1].end
    info = "\n".join([
        how,
        f"source closed: {c.closed}   kept {len(sel.elements)} element(s)"
        + (f", {nbridge} bridge line(s)" if nbridge else ""),
        f"source ids: {[e.source_id for e in sel.elements]}",
        f"continuity: {probs if probs else 'clean chain'}",
        f"profile start  z={p0.z:+.4f}  X={2*p0.r:.4f}",
        f"profile end    z={p1.z:+.4f}  X={2*p1.r:.4f}",
    ] + notes)
    # blend failures, keyed in the same wire format the page uses, with the
    # largest radius that would fit at that junction
    errs = {}
    for src in (getattr(sel, "blend_errors", {}) or {}, ext_errors):
        for k, v in src.items():
            wire = f"{k[0]}-{k[1]}" if isinstance(k, tuple) else str(k)
            errs[wire] = {"asked": v["asked"], "max": round(v["max"], 4),
                          "where": v.get("where", wire)}

    return {"svg": svg, "info": info, "order": order,
            "labels": labels, "props": props, "rows": rows,
            "blend_errors": errs}


def indices_for_chain(c, si, ei, forward):
    from contour.select import chain_indices
    return chain_indices(c, si, ei, forward)


class H(BaseHTTPRequestHandler):
    def _send(self, body, ctype="text/html; charset=utf-8"):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self._send(PAGE)
        if u.path == "/stock.json":
            try:
                return self._send(json.dumps(stock_svg(q)), "application/json")
            except Exception as e:
                return self._send(json.dumps({"error": str(e)}),
                                  "application/json")
        if u.path == "/profile":
            return self._send(PROFILE_PAGE)
        if u.path in ("/pick_meta.json", "/profile.json"):
            try:
                fn = pick_meta if u.path == "/pick_meta.json" else profile_svg
                return self._send(json.dumps(fn(q)), "application/json")
            except Exception as e:
                return self._send(json.dumps({"error": str(e)}),
                                  "application/json")
        if u.path == "/parts":
            body = []
            for name, (path, side, tip, nose) in PARTS.items():
                try:
                    c, _ = import_dxf(path, side=side, name=name)
                    cm, probs = compensate(c, nose, tip)
                    svg = render([("profile", c, "part profile"),
                                  ("tool", cm, f"comp tip#{tip} nose{nose}")],
                                 width=860, title=name)
                    note = ("\n".join(probs)) if probs else ""
                    body.append(f"<h2>{name}</h2><div class='card'>{svg}</div>"
                                f"<pre>{note}</pre>")
                except Exception as e:
                    body.append(f"<h2>{name}</h2><pre>ERROR {e}</pre>")
            return self._send(PARTS_PAGE.replace("__BODY__", "".join(body)))
        self.send_error(404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"serving on http://0.0.0.0:{PORT}/   (ctrl-c to stop)")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
