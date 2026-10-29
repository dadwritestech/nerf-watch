"""Static dashboard: one self-contained HTML file, data embedded, no JS dependencies."""
import datetime as dt
import json
import os

from . import suite

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>nerf-watch: did they nerf it today?</title>
<style>
.viz-root{color-scheme:light;--surface-0:#f3f2ef;--surface-1:#fcfcfb;--border:#dedcd6;--grid:#ebe9e4;
 --text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#7a7974;
 --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;
 --good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
 --surface-0:#111110;--surface-1:#1a1a19;--border:#34332f;--grid:#2a2927;--text-primary:#f0efec;--text-secondary:#c3c2b7;--text-muted:#8f8e86;
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767}}
*{box-sizing:border-box}
body{margin:0}
.viz-root{background:var(--surface-0);color:var(--text-primary);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh;padding:28px 32px 48px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:16px;margin:32px 0 10px}
.sub{color:var(--text-secondary);margin:0 0 20px;max-width:900px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile .name{display:flex;align-items:center;gap:8px;font-weight:600}
.sw{width:10px;height:10px;border-radius:3px;flex:none}
.tile .big{font-size:30px;font-weight:650;margin:6px 0 2px;font-variant-numeric:tabular-nums}
.tile .meta{color:var(--text-secondary);font-size:12.5px}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid var(--border);color:var(--text-primary)}
.badge i{font-style:normal;width:8px;height:8px;border-radius:50%;display:inline-block}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:12px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:14px 16px;position:relative}
.card h3{margin:0 0 2px;font-size:14px}
.card .note{color:var(--text-muted);font-size:12px;margin:0 0 6px}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--text-secondary);margin:0 0 12px}
.legend span{display:inline-flex;align-items:center;gap:6px}
svg text{fill:var(--text-muted);font-size:11px}
.tip{position:absolute;pointer-events:none;background:var(--surface-1);border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;z-index:2;min-width:180px}
.tip b{color:var(--text-primary)} .tip div{color:var(--text-secondary)}
table{border-collapse:collapse;width:100%;background:var(--surface-1);border:1px solid var(--border);border-radius:10px;overflow:hidden;font-size:12.5px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums}
th{color:var(--text-secondary);font-weight:600}
details{margin-top:12px} summary{cursor:pointer;color:var(--text-secondary)}
code{font-size:12px}
.foot{color:var(--text-muted);font-size:12px;margin-top:28px;max-width:900px}
</style></head>
<body><div class="viz-root">
<h1>nerf-watch</h1>
<p class="sub">Did they nerf it today? A fixed, rule-scored canary suite (__N_ITEMS__ items: hidden-test coding, exact instruction checks, refusal and over-refusal probes) run repeatedly against each model. A run is flagged only if an exact stratified permutation test against the model's own baseline gives p&nbsp;&lt;&nbsp;__ALPHA__ <em>and</em> the pass rate moves by at least __MIN_EFFECT__ pts. Suite __SUITE__ · built __BUILT__.</p>
<div class="tiles" id="tiles"></div>
<h2>Pass rate over time</h2>
<div class="legend" id="legend"></div>
<div class="charts">
 <div class="card"><h3>Overall pass rate</h3><p class="note">Hollow = baseline run · filled = checked against baseline · ▼▲ = flagged change</p><svg id="c-score"></svg><div class="tip"></div></div>
 <div class="card"><h3>Coding (hidden tests)</h3><p class="note">Share of coding items whose hidden asserts all pass</p><svg id="c-code"></svg><div class="tip"></div></div>
 <div class="card"><h3>Instruction following</h3><p class="note">Share of items passing every exact rule</p><svg id="c-instruct"></svg><div class="tip"></div></div>
 <div class="card"><h3>Verbosity</h3><p class="note">Median completion tokens per answer</p><svg id="c-tokens"></svg><div class="tip"></div></div>
</div>
<h2>Run-to-run noise (measured, not assumed)</h2>
<table id="noise"></table>
<h2>Detector drills: deliberately degraded copies</h2>
<p class="sub">Same model, same suite, plus an injected system prompt. Compared against the clean model's baseline. If the detector cannot catch these, it cannot catch a vendor.</p>
<table id="drills"></table>
<details><summary>All runs (table view)</summary><table id="runs"></table></details>
<p class="foot">Scoring is regex/parse/assert only; no LLM judge. Responses to harmful prompts are never stored. Vendor APIs appear only when a key is configured; no vendor data is shown here unless it was measured. Latency depends on the host and never counts as a nerf.</p>
</div>
<script>
const R = __DATA__;
const COLORS = ["--s1","--s2","--s3","--s4","--s5","--s6","--s7","--s8"];
const css = v => getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(v).trim();
const series = R.targets.map((t,i)=>({...t, key:t.target+" · T="+t.temperature, color:COLORS[i%8]}));
const VERDICT = {same:["--good","No significant change"],worse:["--critical","Worse vs baseline"],better:["--good","Better vs baseline"],shifted:["--warning","Behaviour shifted"],"n/a":["--text-muted","Not enough runs"]};
const fmt = (x,d=1)=> x==null?"–":(x*100).toFixed(d)+"%";
const esc = s => String(s??"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

// tiles
document.getElementById('tiles').innerHTML = series.map(s=>{
  const p=s.points[s.points.length-1], c=p.cmp?p.cmp.score:null, v=VERDICT[p.verdict]||VERDICT["n/a"];
  return `<div class="tile"><div class="name"><span class="sw" style="background:var(${s.color})"></span>${esc(s.key)}</div>
  <div class="big">${fmt(p.summary.score)}</div>
  <span class="badge"><i style="background:var(${v[0]})"></i>${p.verdict==="worse"?"▼ ":p.verdict==="better"?"▲ ":""}${v[1]}</span>
  <div class="meta" style="margin-top:6px">latest run Δ ${c?(c.delta>=0?"+":"")+(c.delta*100).toFixed(1)+" pts":"–"} · p = ${c?Number(c.p).toPrecision(2):"–"} · ${s.points.length} runs · noise SD ${fmt(s.noise.score_sd)}</div></div>`;}).join("");
document.getElementById('legend').innerHTML = series.map(s=>`<span><span class="sw" style="background:var(${s.color})"></span>${esc(s.key)}</span>`).join("");

function chart(id, get, opts){
  const svg=document.getElementById(id), W=svg.parentNode.clientWidth-32, H=230, m={l:44,r:12,t:10,b:26};
  svg.setAttribute("viewBox",`0 0 ${W} ${H}`); svg.setAttribute("width",W); svg.setAttribute("height",H);
  const all=series.flatMap(s=>s.points.map(p=>({s,p,t:Date.parse(p.ts),y:get(p)}))).filter(d=>d.y!=null);
  if(!all.length){svg.innerHTML=`<text x="10" y="20">no data</text>`;return;}
  const t0=Math.min(...all.map(d=>d.t)), t1=Math.max(...all.map(d=>d.t))||t0+1;
  let y0=opts.min??Math.min(...all.map(d=>d.y)), y1=opts.max??Math.max(...all.map(d=>d.y));
  // pad to at least ±20% of the level, so wobble below the 15% flag threshold looks small
  if(opts.pad){const pd=Math.max((y1-y0)*.15,(y0+y1)/2*.2,1);y0=Math.max(0,y0-pd);y1=y1+pd;}
  const dec=opts.pct?0:((y1-y0)/4<2?1:0);
  const X=t=>m.l+(t1===t0?0.5:(t-t0)/(t1-t0))*(W-m.l-m.r), Y=y=>H-m.b-(y-y0)/(y1-y0||1)*(H-m.t-m.b);
  let g="";
  for(let k=0;k<=4;k++){const v=y0+(y1-y0)*k/4;g+=`<line x1="${m.l}" x2="${W-m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${m.l-6}" y="${Y(v)+4}" text-anchor="end">${opts.pct?Math.round(v*100)+"%":v.toFixed(dec)}</text>`;}
  const days=[...new Set(all.map(d=>new Date(d.t).toISOString().slice(0,10)))];
  const tl=[t0,(t0+t1)/2,t1];
  tl.forEach((t,i)=>{const d=new Date(t);const lab=days.length>1?d.toISOString().slice(5,10):d.toISOString().slice(11,16)+"Z";g+=`<text x="${X(t)}" y="${H-8}" text-anchor="${i==0?"start":i==2?"end":"middle"}">${lab}</text>`;});
  series.forEach(s=>{
    const pts=s.points.map(p=>({p,t:Date.parse(p.ts),y:get(p)})).filter(d=>d.y!=null);
    if(pts.length>1) g+=`<polyline fill="none" stroke="var(${s.color})" stroke-width="2" stroke-linejoin="round" points="${pts.map(d=>X(d.t)+","+Y(d.y)).join(" ")}"/>`;
    pts.forEach(d=>{const base=d.p.role==="baseline", flag=opts.flag&&(d.p.verdict==="worse"||d.p.verdict==="better");
      g+=`<circle cx="${X(d.t)}" cy="${Y(d.y)}" r="4" fill="${base?"var(--surface-1)":`var(${s.color})`}" stroke="var(${s.color})" stroke-width="2"/>`;
      if(flag) g+=`<text x="${X(d.t)}" y="${Y(d.y)-9}" text-anchor="middle" style="fill:var(--text-primary);font-size:12px">${d.p.verdict==="worse"?"▼":"▲"}</text>`;});
  });
  g+=`<line class="xh" x1="0" x2="0" y1="${m.t}" y2="${H-m.b}" stroke="var(--text-muted)" stroke-dasharray="3 3" style="display:none"/>`;
  svg.innerHTML=g;
  const tip=svg.parentNode.querySelector('.tip'), xh=svg.querySelector('.xh');
  svg.onmousemove=e=>{const r=svg.getBoundingClientRect(), mx=(e.clientX-r.left)*(W/r.width), my=(e.clientY-r.top)*(H/r.height);
    let best=null,bd=1e9; all.forEach(d=>{const dd=Math.hypot(X(d.t)-mx,(Y(d.y)-my)*.5); if(dd<bd){bd=dd;best=d;}});
    if(!best||bd>60){tip.style.display="none";xh.style.display="none";return;}
    xh.setAttribute("x1",X(best.t));xh.setAttribute("x2",X(best.t));xh.style.display="";
    const c=best.p.cmp, v=VERDICT[best.p.verdict]||VERDICT["n/a"];
    tip.innerHTML=`<b>${esc(best.s.key)}</b><div>${best.p.ts.replace("T"," ").replace("Z"," UTC")} · ${best.p.role}</div><div>${opts.label}: <b>${opts.pct?fmt(best.y):Math.round(best.y)}</b></div>${c?`<div>score Δ ${(c.score.delta*100).toFixed(1)} pts · p ${c.score.p}</div><div>tokens ×${c.tokens.ratio} · p ${c.tokens.p}</div>`:""}<div><span class="badge" style="margin-top:4px"><i style="background:var(${v[0]})"></i>${v[1]}</span></div>`;
    tip.style.display="block"; const left=X(best.t)/W*r.width+16; tip.style.left=Math.min(left,r.width-200)+"px"; tip.style.top=(Y(best.y)/H*r.height+40)+"px";};
  svg.onmouseleave=()=>{tip.style.display="none";xh.style.display="none";};
}
const draw=()=>{
chart("c-score",p=>p.summary.score,{pct:true,min:0,max:1,flag:true,label:"pass rate"});
chart("c-code",p=>p.summary.code,{pct:true,min:0,max:1,label:"coding"});
chart("c-instruct",p=>p.summary.instruct,{pct:true,min:0,max:1,label:"instruction"});
chart("c-tokens",p=>p.summary.median_tokens,{pad:true,label:"median tokens"});};
draw(); addEventListener("resize",draw);

document.getElementById('noise').innerHTML = `<tr><th>Model</th><th>Runs</th><th>Mean pass</th><th>Run-to-run SD</th><th>Min–max</th><th>Items that flap</th><th>Median tokens range</th><th>False flags among baseline runs</th><th>Catches a silent break of</th></tr>`+
 series.map(s=>{const n=s.noise, b=s.points.filter(p=>p.role==="baseline"), ff=b.filter(p=>p.verdict!=="same").length;
 return `<tr><td><span class="sw" style="display:inline-block;background:var(${s.color})"></span> ${esc(s.key)}</td><td>${n.runs}</td><td>${fmt(n.score_mean)}</td><td>${fmt(n.score_sd)}</td><td>${fmt(n.score_min)} – ${fmt(n.score_max)}</td><td>${n.flapping_items.length} <span style="color:var(--text-muted)">${esc(n.flapping_items.join(", "))}</span></td><td>${n.median_tokens_range?n.median_tokens_range.join(" – "):"–"}</td><td>${ff} / ${b.length}</td><td>${(()=>{const pw=n.power;if(!pw)return "–";const k=Object.keys(pw).map(Number).filter(k=>k>0&&pw[k]>=0.8).sort((a,b)=>a-b)[0];return k?`≥${k} items (${Math.round(pw[k]*100)}% of trials)`:"–";})()}</td></tr>`;}).join("");

document.getElementById('drills').innerHTML = R.drills.length? `<tr><th>Drill</th><th>vs</th><th>Injected system prompt</th><th>Pass rate</th><th>Δ vs baseline</th><th>p</th><th>Tokens ×</th><th>Verdict</th></tr>`+
 R.drills.flatMap(d=>d.runs.map(r=>{const v=VERDICT[r.verdict]||VERDICT["n/a"];return `<tr><td>${esc(d.target)}</td><td>${esc(d.parent)} · T=${d.temperature}</td><td style="max-width:320px">${esc(d.system_prompt)}</td><td>${fmt(r.summary.score)}</td><td>${(r.cmp.score.delta*100).toFixed(1)} pts</td><td>${r.cmp.score.p}</td><td>${r.cmp.tokens.ratio}</td><td><span class="badge"><i style="background:var(${v[0]})"></i>${v[1]}</span></td></tr>`;})).join("") : `<tr><td>No drills run yet.</td></tr>`;

document.getElementById('runs').innerHTML = `<tr><th>Run</th><th>Model</th><th>Role</th><th>Pass</th><th>Code</th><th>Instr.</th><th>Refuses harmful</th><th>Over-refusal</th><th>Med. tokens</th><th>Med. latency</th><th>Verdict</th></tr>`+
 series.flatMap(s=>s.points.map(p=>`<tr><td><code>${esc(p.run_id)}</code></td><td>${esc(s.key)}</td><td>${p.role}</td><td>${fmt(p.summary.score)}</td><td>${fmt(p.summary.code,0)}</td><td>${fmt(p.summary.instruct,0)}</td><td>${fmt(p.summary.refuse_rate,0)}</td><td>${fmt(p.summary.over_refusal,0)}</td><td>${p.summary.median_tokens}</td><td>${p.summary.median_latency_s}s</td><td>${p.verdict}</td></tr>`)).join("");
</script></body></html>
"""


def build(report, out):
    data = json.dumps(report, separators=(",", ":")).replace("</", "<\\/")
    html = (TEMPLATE.replace("__DATA__", data)
            .replace("__N_ITEMS__", str(len(suite.items())))
            .replace("__ALPHA__", str(report["alpha"]))
            .replace("__MIN_EFFECT__", str(round(report["min_effect"] * 100)))
            .replace("__SUITE__", suite.SUITE_VERSION)
            .replace("__BUILT__", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out
