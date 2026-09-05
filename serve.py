#!/usr/bin/env python3
"""
serve.py - a thin view over contour.session.

All editing state lives in Session, in Python. This file does two things:
route actions to it, and render its view() payload. The browser holds nothing
but what is being typed at that moment.

That is the whole point of the split: a Qt window would replace this file and
nothing else. Everything underneath stays testable without a display, which is
how it is verified today.

    python3 serve.py            # http://localhost:8321/
"""

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from contour.session import Session, ExtSeg, PARTS
from contour.comp import COMP_LEFT, COMP_RIGHT, COMP_CENTER, compensate
from contour.dxf_import import import_dxf
from contour.viz import render

PORT = 8321
SESSION = Session()

def _f(q, k, d=None):
    v = q.get(k, [None])[0]
    return v if v not in (None, "") else d


def apply_action(q):
    """Route one action onto the session."""
    s = SESSION
    a = _f(q, "action", "")

    # plain field updates, sent with every request
    if _f(q, "part") and _f(q, "part") != s.profile_name:
        s.load(_f(q, "part"))
    s.stock_source = _f(q, "stocksrc", s.stock_source)
    s.comp_side = _f(q, "cside", s.comp_side)
    for key, attr, cast in (("od", "stock_od", float),
                            ("zf", "stock_zf", float),
                            ("zb", "stock_zb", float)):
        v = _f(q, key)
        if v is not None:
            try:
                setattr(s, attr, cast(v))
            except ValueError:
                pass
    for pfx, segs in (("s", s.start_segs), ("e", s.end_segs)):
        for n in (0, 1):
            d = _f(q, f"{pfx}{n+1}d", "")
            L = _f(q, f"{pfx}{n+1}l", "")
            A = _f(q, f"{pfx}{n+1}a", "")
            segs[n] = ExtSeg(d or "", L or "", A or "")

    if a == "click_element":
        s.click_element(int(q["i"][0]))
    elif a == "focus":
        s.focus = _f(q, "key")
    elif a == "toggle":
        s.toggle(int(q["i"][0]))
    elif a == "reverse":
        s.reverse()
    elif a == "del_start":
        s.delete_end("start")
    elif a == "del_end":
        s.delete_end("end")
    elif a == "select_all":
        s.select_all()
    elif a == "reset":
        s.reset()
    elif a == "blend":
        key = _f(q, "key")
        try:
            r = float(_f(q, "r", "0"))
        except ValueError:
            r = 0.0
        if key:
            s.set_blend(key, r)
    elif a == "click_stock":
        try:
            z, r = [float(x) for x in _f(q, "pt", "0,0").split(",")]
            s.click_stock((z, r))
        except ValueError:
            pass
    elif a == "clear_walk":
        s.clear_walk()
    elif a == "toggle_stock":
        s.show_stock = not s.show_stock


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
            self.send_response(302)
            self.send_header("Location", "/profile")
            self.end_headers()
            return
        if u.path == "/profile":
            return self._send(PROFILE_PAGE)
        if u.path == "/view.json":
            try:
                apply_action(q)
                v = SESSION.view()
                v["parts"] = list(PARTS)
                v["state"] = {
                    "part": SESSION.profile_name,
                    "stocksrc": SESSION.stock_source,
                    "cside": SESSION.comp_side,
                    "od": SESSION.stock_od, "zf": SESSION.stock_zf,
                    "zb": SESSION.stock_zb,
                    "focus": SESSION.focus,
                    "blends": {str(k): v2 for k, v2 in SESSION.blends.items()},
                }
                return self._send(json.dumps(v), "application/json")
            except Exception as e:
                import traceback
                return self._send(json.dumps(
                    {"error": f"{e}", "trace": traceback.format_exc()[-600:]}),
                    "application/json")
        if u.path == "/parts":
            body = []
            for name, (path, side, tip, nose) in PARTS.items():
                try:
                    c, _ = import_dxf(path, side=side, name=name)
                    cs = COMP_LEFT if name == "bore" else COMP_RIGHT
                    cm, probs = compensate(c, nose, tip, comp_side=cs)
                    svg = render([("profile", c, "part profile"),
                                  ("tool", cm, f"comp tip#{tip} {cs}")],
                                 width=860, title=name)
                    body.append(f"<h2>{name}</h2><div class='card'>{svg}</div>"
                                f"<pre>{chr(10).join(probs)}</pre>")
                except Exception as e:
                    body.append(f"<h2>{name}</h2><pre>ERROR {e}</pre>")
            return self._send(PARTS_PAGE.replace("__BODY__", "".join(body)))
        self.send_error(404)

    def log_message(self, *a):
        pass


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
<nav><a href="/profile">profile</a><a href="/parts">reference parts</a></nav>
__BODY__
</body></html>"""


PROFILE_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>lathe - profile</title>
<style>
 body{font-family:monospace;margin:0;padding:10px;background:#f4f4f4;color:#222}
 nav a{font-size:12px;margin-right:10px}
 .grid{display:grid;grid-template-columns:210px 1fr 260px;gap:10px;align-items:start}
 .panel{background:#fff;border:1px solid #ddd;border-radius:3px;padding:8px}
 .panel h2{font-size:11px;margin:0 0 6px;color:#555;font-weight:normal;
   text-transform:uppercase;letter-spacing:.5px}
 .row{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin-bottom:6px}
 label{display:flex;flex-direction:column;font-size:11px}
 select,input{font-family:monospace;font-size:13px;padding:4px;
   border:1px solid #bbb;border-radius:3px}
 input{width:78px}
 input.badfit{background:#ffe9a3;border-color:#d9a300;color:#6b4e00;font-weight:bold}
 fieldset{border:1px solid #ccc;border-radius:3px;margin:0 0 8px;padding:7px}
 legend{font-size:11px;color:#555}
 button{font-family:monospace;font-size:11px;padding:4px 8px;cursor:pointer;
   border:1px solid #bbb;border-radius:3px;background:#fff}
 .el{font-size:11px;padding:4px 6px;border-radius:3px;cursor:pointer;
   border:1px solid transparent;display:flex;justify-content:space-between;gap:6px}
 .el:hover{background:#f0f4fa}
 .el.real{background:#fff;border-color:#eee}
 .el.off{opacity:.45;text-decoration:line-through}
 .el.ext{background:#eef7ee;border-color:#cfe6cf;color:#2a6b2a}
 .el.bridge{background:#fff6e6;border-color:#f0dcb8;color:#8a6412}
 .el.blend{background:#eef2fb;border-color:#c8d4ee;color:#33509c}
 .el.stock{background:#f6f6f6;border-color:#e6e6e6;color:#555}
 .el.focus{outline:2px solid #1060c0}
 .el .pad{display:inline-block;width:15px}
 .ends{font-size:10px;color:#888;margin:3px 0}
 #info{font-size:11px;white-space:pre;color:#444;margin-top:6px}
 table.props{width:100%;border-collapse:collapse;font-size:11px}
 table.props td{padding:2px 3px;border-bottom:1px solid #f0f0f0}
 table.props td.k{color:#777;white-space:nowrap}
 table.props td.v{text-align:right}
 .sec{margin-top:8px;font-size:10px;color:#888;text-transform:uppercase}
</style></head><body>
<nav><a href="/profile">profile</a><a href="/parts">reference parts</a></nav>

<div class="row">
 <label>profile<select id="part"></select></label>
 <label>stock<select id="stocksrc">
  <option value="param">parametric</option>
  <option value="stock_closed">stock_closed.dxf</option>
  <option value="none">none</option></select></label>
 <label>comp side<select id="cside">
  <option value="right">right (turning)</option>
  <option value="left">left (boring)</option>
  <option value="center">center (no comp)</option></select></label>
 <label>stock OD<input id="od"></label>
 <label>z face<input id="zf"></label>
 <label>z back<input id="zb"></label>
 <label>&nbsp;<button id="tstock">stock on/off</button></label>
</div>

<fieldset><legend>extensions &mdash; segment 2 is a length/angle nudge; clearance lives in the toolpath</legend>
<div class="row">
 <label>start 1 dir<select id="s1d" class="dir"></select></label>
 <label>len<input id="s1l" placeholder="to stock"></label>
 <label>angle<input id="s1a" placeholder="deg"></label>
 <label>start 2 len<input id="s2l" placeholder="len"></label>
 <label>angle<input id="s2a" placeholder="deg"></label>
</div>
<div class="row">
 <label>end 1 dir<select id="e1d" class="dir"></select></label>
 <label>len<input id="e1l" placeholder="to stock"></label>
 <label>angle<input id="e1a" placeholder="deg"></label>
 <label>end 2 len<input id="e2l" placeholder="len"></label>
 <label>angle<input id="e2a" placeholder="deg"></label>
</div>
</fieldset>

<div class="grid">
 <div class="panel">
  <h2>elements</h2>
  <div class="row" style="gap:4px;margin-bottom:4px">
   <button id="brev">reverse</button><button id="bdels">del start</button>
   <button id="bdele">del end</button><button id="ball">all</button>
   <button id="breset">reset</button>
  </div>
  <div class="ends" id="hint"></div>
  <div id="list"></div>
  <h2 style="margin-top:12px">stock boundary</h2>
  <div class="ends">click the stock beside an extension, on the side you want it to run</div>
  <div class="row" style="gap:4px;margin:4px 0"><button id="bwclr">clear walk</button></div>
  <div id="stocklist"></div>
 </div>
 <div class="panel"><div id="out">loading...</div><div id="info"></div></div>
 <div class="panel">
  <h2>element detail</h2>
  <div id="props">click an element</div>
  <div id="blendbox" style="display:none">
   <div class="sec">blend to next element</div>
   <div class="row" style="gap:6px">
    <label>radius<input id="blendr"></label>
    <label>&nbsp;<button id="bset">apply</button></label>
    <label>&nbsp;<button id="bclr">clear</button></label>
   </div>
   <div class="ends" id="blendnote"></div>
  </div>
 </div>
</div>

<script>
// No state here. Every click posts an action; the server owns the session and
// returns the whole view. This script only forwards events and paints.
let ROWS=[], BERR={}, STATE={}, PARTNAMES=[];
const DIRS=['','+Z','-Z','+X','-X'];
for(const s of document.querySelectorAll('select.dir'))
 s.innerHTML=DIRS.map(d=>`<option value="${d}">${d||'(none)'}</option>`).join('');

function fields(){
 const q=new URLSearchParams();
 for(const id of ['part','stocksrc','cside','od','zf','zb',
                  's1d','s1l','s1a','s2l','s2a','e1d','e1l','e1a','e2l','e2a']){
  const el=document.getElementById(id);
  if(el) q.set(id, el.value);
 }
 return q;
}
async function act(extra){
 const q=fields();
 for(const k in (extra||{})) q.set(k, extra[k]);
 const r=await fetch('/view.json?'+q);
 const j=await r.json();
 if(j.error){ info.textContent=j.error; return; }
 paint(j);
}
function paint(j){
 STATE=j.state||{}; ROWS=j.rows||[]; BERR=j.blend_errors||{};
 out.innerHTML=j.svg||''; info.textContent=j.info||'';
 hint.textContent=j.hint||'';
 if(!part.options.length){
  PARTNAMES=j.parts||[];
 }
 renderList(ROWS); renderStock(j.walk_rows||[]); renderProps(j.props);
 attach();
}
function renderList(rows){
 if(!rows.length){ list.innerHTML='<div class="ends">nothing selected</div>'; return; }
 let h='';
 for(const r of rows){
  const isReal=(r.check!==null&&r.check!==undefined);
  const cls=['el',r.cls,(isReal&&!r.check)?'off':'',
             String(STATE.focus)===String(r.key)?'focus':''].filter(Boolean).join(' ');
  const box=isReal
   ? `<input type="checkbox" class="cb" data-cb="${r.key}" ${r.check?'checked':''}>`
   : '<span class="pad"></span>';
  h+=`<div class="${cls}" data-el="${r.key}"><span>${box}${isReal?r.key:''}</span>`
   +`<span class="tag">${r.label}</span></div>`;
 }
 list.innerHTML=h;
 for(const el of document.querySelectorAll('[data-el]'))
  el.addEventListener('click',ev=>{
   if(ev.target.classList.contains('cb')) return;
   act({action:'focus', key:el.dataset.el});
  });
 for(const cb of document.querySelectorAll('.cb'))
  cb.addEventListener('change',()=>act({action:'toggle', i:cb.dataset.cb}));
}
function renderStock(rows){
 if(!rows.length){ stocklist.innerHTML='<div class="ends">nothing chained yet</div>'; return; }
 let h='';
 rows.forEach((r,k)=>{
  const cls=['el','stock',String(STATE.focus)===('s'+k)?'focus':''].filter(Boolean).join(' ');
  h+=`<div class="${cls}" data-sw="${k}"><span>${k}</span><span class="tag">${r.label}</span></div>`;
 });
 stocklist.innerHTML=h;
 for(const el of document.querySelectorAll('[data-sw]'))
  el.addEventListener('click',()=>act({action:'focus', key:'s'+el.dataset.sw}));
}
function jkeyOf(key){
 const r=ROWS.find(x=>String(x.key)===String(key));
 return r? (r.jkey||null) : null;
}
function renderProps(p){
 const key=jkeyOf(STATE.focus);
 if(key){
  blendbox.style.display='';
  blendr.value=(STATE.blends&&STATE.blends[key])||'';
  const e=BERR[key];
  if(e){ blendr.classList.add('badfit');
   blendnote.textContent='R'+e.asked+' does not fit \u00b7 max R'+e.max; }
  else { blendr.classList.remove('badfit');
   blendnote.textContent=key+' \u00b7 stays put if the chain is reversed'; }
 } else blendbox.style.display='none';
 if(!p){ props.textContent='click an element'; return; }
 const f=(v,n=4)=>(typeof v==='number')?v.toFixed(n):v;
 let h='<table class="props">';
 const row=(k,v)=>{h+=`<tr><td class="k">${k}</td><td class="v">${v}</td></tr>`;};
 row('element',p.index); row('kind',p.kind);
 row('origin',p.origin||'DXF element');
 row('DXF entity',(p.source_id===null||p.source_id===undefined)?'&mdash;':p.source_id);
 h+='</table><div class="sec">start</div><table class="props">';
 row('Z',f(p.start_z)); row('X dia',f(p.start_x)); row('radius',f(p.start_r));
 h+='</table><div class="sec">end</div><table class="props">';
 row('Z',f(p.end_z)); row('X dia',f(p.end_x)); row('radius',f(p.end_r));
 h+='</table><div class="sec">geometry</div><table class="props">';
 row('length',f(p.length));
 if(p.kind==='line'){ row('angle from axis',f(p.angle_from_axis,3)+'&deg;');
  row('included angle',f(p.included_angle,3)+'&deg;');
  row('dZ',f(p.dz)); row('dR',f(p.dr)); }
 else { row('radius',f(p.radius)); row('centre Z',f(p.center_z));
  row('centre X dia',f(p.center_x)); row('direction',p.direction);
  row('sweep',f(p.sweep,3)+'&deg;'); }
 h+='</table>';
 props.innerHTML=h;
}
function modelPoint(ev){
 const svg=document.getElementById('pickfig');
 const g=document.getElementById('modelspace');
 if(!svg||!g) return null;
 const pt=svg.createSVGPoint(); pt.x=ev.clientX; pt.y=ev.clientY;
 const m=g.getScreenCTM(); if(!m) return null;
 const q=pt.matrixTransform(m.inverse());
 return [q.x,q.y];
}
function attach(){
 for(const h of document.querySelectorAll('.hit'))
  h.addEventListener('click',()=>act({action:'click_element', i:h.dataset.idx}));
 for(const h of document.querySelectorAll('.shit'))
  h.addEventListener('click',ev=>{
   const p=modelPoint(ev); if(!p) return;
   act({action:'click_stock', pt:p[0].toFixed(6)+','+p[1].toFixed(6)});
  });
}
function applyBlend(){
 const key=jkeyOf(STATE.focus); if(!key) return;
 act({action:'blend', key:key, r:blendr.value||'0'});
}
document.getElementById('bset').addEventListener('click',applyBlend);
blendr.addEventListener('keydown',ev=>{ if(ev.key==='Enter'){ev.preventDefault();applyBlend();} });
document.getElementById('bclr').addEventListener('click',()=>{
 const key=jkeyOf(STATE.focus); if(!key) return;
 blendr.value=''; act({action:'blend', key:key, r:'0'});});
document.getElementById('brev').addEventListener('click',()=>act({action:'reverse'}));
document.getElementById('bdels').addEventListener('click',()=>act({action:'del_start'}));
document.getElementById('bdele').addEventListener('click',()=>act({action:'del_end'}));
document.getElementById('ball').addEventListener('click',()=>act({action:'select_all'}));
document.getElementById('breset').addEventListener('click',()=>act({action:'reset'}));
document.getElementById('bwclr').addEventListener('click',()=>act({action:'clear_walk'}));
document.getElementById('tstock').addEventListener('click',()=>act({action:'toggle_stock'}));
for(const id of ['part','stocksrc','cside','od','zf','zb',
                 's1d','s1l','s1a','s2l','s2a','e1d','e1l','e1a','e2l','e2a'])
 document.getElementById(id).addEventListener('change',()=>act({}));

fetch('/view.json?action=init').then(r=>r.json()).then(j=>{
 part.innerHTML=(j.parts||[]).map(n=>`<option value="${n}">${n}</option>`).join('');
 const st=j.state||{};
 part.value=st.part; stocksrc.value=st.stocksrc; cside.value=st.cside;
 od.value=st.od; zf.value=st.zf; zb.value=st.zb;
 e1d.value='+X';
 paint(j);
});
</script></body></html>"""


if __name__ == "__main__":
    print(f"serving on http://0.0.0.0:{PORT}/   (ctrl-c to stop)")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
