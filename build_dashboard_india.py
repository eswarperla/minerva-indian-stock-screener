"""
Build the India SEPA-VCP watchlist dashboard (self-contained HTML).
====================================================================
Reads sepa_data_india_latest.json (produced by sepa_screener_india.py) and
writes sepa_vcp_india_watchlist.html - a single-file dashboard you can open in
any browser. The same HTML is what the Cowork artifact 'sepa-vcp-india-watchlist'
displays; a scheduled task can re-render it daily.

Mirrors the US dashboard: KPI/regime strip, screen-volume sparkline, pipeline
funnel, bucket tabs (A-E), Audit Log tab, and sector breakdown.
Formatting is INR (₹) and stock links point to TradingView NSE pages.

Usage:
  python3 build_dashboard_india.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "sepa_data_india_latest.json"
OUT = HERE / "sepa_vcp_india_watchlist.html"

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SEPA-VCP India Watchlist</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.0/dist/chart.umd.js" integrity="sha384-iU8HYtnGQ8Cy4zl7gbNMOhsDTTKX02BTXptVP/vqAWIaTfM7isw76iyZCsjL2eVi" crossorigin="anonymous"></script>
<style>
:root{color-scheme:light}*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:#f8fafc;color:#0f172a;padding:16px;font-size:14px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px}
.header h1{font-size:18px;font-weight:600}.header .meta{font-size:12px;color:#64748b}
.note{background:#fffbeb;border:1px solid #fde68a;color:#92400e;border-radius:8px;padding:8px 12px;font-size:12px;margin-bottom:14px}
.top-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.kpi-card{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px}
.kpi-label{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
.kpi-value{font-size:18px;font-weight:600}.kpi-sub{font-size:11px;color:#64748b;margin-top:2px}
.kpi-card.green .kpi-value{color:#10b981}.kpi-card.amber .kpi-value{color:#f59e0b}.kpi-card.red .kpi-value{color:#ef4444}.kpi-card.blue .kpi-value{color:#3b82f6}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}
.dot.green{background:#10b981}.dot.amber{background:#f59e0b}.dot.red{background:#ef4444}
/* screen volume sparkline */
.sparkline-row{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;margin-bottom:14px}
.sparkline-row-header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.sparkline-row-title{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;font-weight:500}
.sparkline-row-sub{font-size:11px;color:#94a3b8}
.sparkline-canvas-wrap{position:relative;width:100%;height:70px}
.sparkline-canvas{width:100%!important;height:70px!important;display:block}
/* funnel */
.funnel-section{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px 14px;margin-bottom:14px}
.funnel-section summary{font-size:12px;font-weight:600;color:#475569;cursor:pointer;user-select:none}
.funnel-section[open] summary{margin-bottom:10px}
.funnel-row{display:flex;align-items:center;gap:10px;font-size:12px;margin-bottom:4px}
.funnel-label{width:220px;color:#475569;font-weight:500;display:flex;align-items:center;gap:6px}
.funnel-label .step{display:inline-block;width:18px;height:18px;border-radius:50%;background:#f1f5f9;color:#64748b;font-size:10px;font-weight:700;text-align:center;line-height:18px}
.funnel-bar{flex:1;height:14px;background:#f1f5f9;border-radius:4px;overflow:hidden}
.funnel-bar-fill{height:100%;background:linear-gradient(90deg,#3b82f6,#6366f1)}
.funnel-count{width:90px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
.funnel-pct{width:55px;text-align:right;color:#94a3b8;font-size:11px;font-variant-numeric:tabular-nums}
.funnel-note{font-size:11px;color:#94a3b8;margin-top:8px;padding-top:8px;border-top:1px solid #f1f5f9}
.tabs{display:flex;gap:4px;border-bottom:2px solid #e2e8f0;margin-bottom:12px;flex-wrap:wrap}
.tab{background:none;border:none;padding:10px 14px;font-size:13px;font-weight:500;cursor:pointer;color:#64748b;border-bottom:2px solid transparent;margin-bottom:-2px}
.tab.active{color:#0f172a;border-bottom-color:#0f172a}
.tab .badge{background:#e2e8f0;border-radius:10px;padding:1px 7px;font-size:11px;margin-left:6px;font-weight:600}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;font-size:13px}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid #f1f5f9;white-space:nowrap}
th{background:#f8fafc;color:#475569;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em}
td.l,th.l{text-align:left}tr:hover td{background:#f8fafc}
.tk{font-weight:700;color:#0f172a;text-decoration:none}.tk:hover{color:#3b82f6;text-decoration:underline}
.sub{color:#94a3b8;font-size:11px}.pos{color:#10b981}.neg{color:#ef4444}
.score{display:inline-block;min-width:34px;text-align:center;border-radius:6px;padding:2px 6px;font-weight:700;color:#fff}
.tag{display:inline-block;background:#dbeafe;color:#1e40af;border-radius:6px;padding:1px 6px;font-size:10px;font-weight:600;margin-left:4px}
.tag.warn{background:#fee2e2;color:#991b1b}
.empty{padding:40px;text-align:center;color:#94a3b8;background:#fff;border:1px solid #e2e8f0;border-radius:8px}
.foot{margin-top:14px;font-size:11px;color:#94a3b8;line-height:1.6}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:#64748b;margin-bottom:12px}
.ext{color:#3b82f6;text-decoration:none;font-size:11px;margin-left:6px}.ext:hover{text-decoration:underline}
/* sector breakdown */
.sector-box{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px 14px;margin-top:14px}
.sector-box h3{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}
.sector-row{display:flex;align-items:center;gap:10px;margin-bottom:6px;font-size:12px}
.sector-name{width:160px;color:#475569}
.sector-track{flex:1;height:18px;background:#f1f5f9;border-radius:4px;overflow:hidden}
.sector-fill{height:100%;background:#3b82f6;border-radius:4px}.sector-fill.warn{background:#f59e0b}
.sector-val{width:90px;text-align:right;color:#0f172a;font-variant-numeric:tabular-nums}
.audit-note{font-size:11px;color:#64748b;margin-top:12px;padding:8px;background:#f8fafc;border-radius:4px}
</style></head><body>
<div id="app"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const CUR = D.currency || 'INR';
const inr = v => v==null ? '–' : '₹' + Number(v).toLocaleString('en-IN',{maximumFractionDigits:2});
const pct = v => v==null ? '–' : (v>=0?'+':'') + Number(v).toFixed(2) + '%';
const pctC = v => v==null ? '<span class="sub">–</span>' : `<span class="${v>=0?'pos':'neg'}">${pct(v)}</span>`;
const gpct = v => v==null ? '<span class="sub">–</span>' : `<span class="${v>=0?'pos':'neg'}">${(v*100).toFixed(0)}%</span>`;
const sym = t => t.replace(/\.(NS|BO)$/,'');
const tv = t => `https://www.tradingview.com/chart/?symbol=NSE:${sym(t)}`;
const scoreColor = s => s>=80?'#10b981':s>=65?'#3b82f6':s>=50?'#f59e0b':'#94a3b8';
const BUCKETS = {A:'At Pivot',B:'Just Broke Out',C:'Developing Base',D:'Failed Breakout',E:'Too Early'};
const stocks = D.stocks||[];
let active = ['A','B','C','E','D'].find(b => (D.buckets&&D.buckets[b]>0)) || 'A';

function kpis(){
  const m = D.marketRegime||{};
  const card=(label,val,sub,cls)=>`<div class="kpi-card ${cls||''}"><div class="kpi-label">${label}</div><div class="kpi-value">${val}</div><div class="kpi-sub">${sub||''}</div></div>`;
  return `<div class="top-strip">
   ${card('Market Regime', `<span class="dot ${m.regimeLight}"></span>${m.regimeLabel||'–'}`, m.regimeSub||'', m.regimeLight)}
   ${card('Distribution Days', m.distributionDays25d!=null?m.distributionDays25d:'–', m.distSub||'25-day', m.distLight)}
   ${card('Avg SEPA Score', m.avgSepaScore!=null?m.avgSepaScore:'–', 'across candidates','blue')}
   ${card('Universe Health', (m.universeHealthPct!=null?m.universeHealthPct+'%':'–'), 'passing trend template','blue')}
   ${card('Failed Breakouts 30d', m.failedBreakoutRate30d!=null?(m.failedBreakoutRate30d*100).toFixed(0)+'%':'–', m.failSub||'', m.failLight)}
   ${card('New Today', D.newToday!=null?D.newToday:'–', 'fresh entries','blue')}
  </div>`;
}

function funnel(){
  const f = D.funnel;
  if(!f || !Object.keys(f).length) return '';
  const universe = f.universe_size || 1;
  const fb = f.final_per_bucket || {};
  const totalFinal = (fb.A||0)+(fb.B||0)+(fb.C||0)+(fb.D||0)+(fb.E||0);
  const steps = [
    ['Universe', f.universe_size],
    ['Prices fetched', f.prices_fetched],
    ['Trend Template + RS pass', f.trend_passed],
    ['VCP base detected', f.vcp_detected],
    ['VCP fully passed (tight)', f.vcp_passed],
    ['Bucket classified', f.bucket_classified],
    ['Size + liquidity pass', f.size_liquidity_passed],
    ['Final candidates', totalFinal],
  ];
  const rows = steps.map(([label,c],i)=>{
    c = c||0; const p = c/universe*100;
    return `<div class="funnel-row"><div class="funnel-label"><span class="step">${i+1}</span>${label}</div>
      <div class="funnel-bar"><div class="funnel-bar-fill" style="width:${Math.max(0.5,p)}%"></div></div>
      <div class="funnel-count">${c.toLocaleString('en-IN')}</div><div class="funnel-pct">${p.toFixed(1)}%</div></div>`;
  }).join('');
  return `<details class="funnel-section" open><summary>Pipeline funnel — where candidates drop out</summary>${rows}
    <div class="funnel-note">Of ${(f.trend_passed||0).toLocaleString('en-IN')} trend-passing stocks, ${totalFinal} reached the buckets.
    Bucket A needs VCP fully passed + within 3% of pivot + fundamentals; B needs a volume-confirmed breakout in the last 3 days; C is a base still forming.</div></details>`;
}

function tabs(){
  const b=D.buckets||{};
  const bt = ['A','B','C','E','D'].map(k=>
    `<button class="tab ${k===active?'active':''}" data-b="${k}">${k} · ${BUCKETS[k]}<span class="badge">${b[k]||0}</span></button>`).join('');
  const auditN = (D.auditHistory||[]).length;
  return `<div class="tabs">${bt}<button class="tab ${active==='AUDIT'?'active':''}" data-b="AUDIT">Audit Log<span class="badge">${auditN}</span></button></div>`;
}

function row(s){
  const risk = s.riskPct;
  const riskTag = (risk!=null && risk>(D.maxLossPct||8)) ? `<span class="tag warn">risk ${risk}%</span>` : (risk!=null?`<span class="sub">${risk}%</span>`:'<span class="sub">–</span>');
  const er = s.earningsWithin5d?'<span class="tag warn">earnings ≤5d</span>':'';
  const nw = s.isNewToday?'<span class="tag">new</span>':'';
  return `<tr>
    <td class="l"><a class="tk" href="${tv(s.ticker)}" target="_blank">${sym(s.ticker)}</a>${nw}${er}<div class="sub">${s.name||''} · ${s.sector||''}</div></td>
    <td><span class="score" style="background:${scoreColor(s.sepaScore)}">${s.sepaScore}</span></td>
    <td>${s.rsRank??'–'}</td><td>${inr(s.pivotPrice)}</td><td>${inr(s.close)}</td><td>${pctC(s.distFromPivotPct)}</td>
    <td>${s.baseWeeks??'–'}</td><td>${s.numContractions??'–'}</td><td>${s.lastContractionPct!=null?s.lastContractionPct+'%':'–'}</td>
    <td>${gpct(s.epsGrowthAnnual)}</td><td>${s.roe!=null?(s.roe*100).toFixed(0)+'%':'–'}</td><td>${inr(s.stopPrice)}</td><td>${riskTag}</td>
  </tr>`;
}

function bucketTable(){
  const rows = stocks.filter(s=>s.bucket===active).sort((a,b)=>b.sepaScore-a.sepaScore);
  if(!rows.length) return `<div class="empty">No stocks in bucket ${active} (${BUCKETS[active]}) today.</div>`;
  return `<table><thead><tr>
    <th class="l">Ticker</th><th>SEPA</th><th>RS</th><th>Pivot</th><th>Close</th><th>Dist %</th>
    <th>Base wk</th><th>Contr.</th><th>Last C%</th><th>EPS YoY</th><th>ROE</th><th>Stop</th><th>Risk</th>
  </tr></thead><tbody>${rows.map(row).join('')}</tbody></table>`;
}

function auditTable(){
  const a = D.auditHistory||[];
  if(!a.length) return `<div class="empty">No failed breakouts in the audit log yet.<br><span class="sub">History builds up as the screener runs daily.</span></div>`;
  const m = D.marketRegime||{};
  const rows = a.map(x=>{
    const d1=new Date(x.breakoutDate), d2=new Date(x.failureDate);
    const dtf=Math.round((d2-d1)/86400000);
    return `<tr>
      <td class="l"><a class="tk" href="${tv(x.ticker)}" target="_blank">${sym(x.ticker)}</a></td>
      <td>${x.breakoutDate||'–'}</td><td>${inr(x.breakoutPrice)}</td><td>${x.failureDate||'–'}</td>
      <td class="neg">${x.failurePct!=null?x.failurePct+'%':'–'}</td><td>${isNaN(dtf)?'–':dtf}</td>
      <td>${inr(x.currentClose)}</td><td class="neg">${x.currentVsBreakoutPct!=null?x.currentVsBreakoutPct+'%':'–'}</td>
      <td class="l"><a class="ext" href="${tv(x.ticker)}" target="_blank">TradingView</a></td></tr>`;
  }).join('');
  const fr = m.failedBreakoutRate30d!=null?(m.failedBreakoutRate30d*100).toFixed(0)+'%':'–';
  return `<table><thead><tr>
    <th class="l">Ticker</th><th>Breakout</th><th>BO Price</th><th>Failure</th><th>Fail %</th><th>Days</th><th>Close</th><th>Total Drop</th><th class="l">Link</th>
  </tr></thead><tbody>${rows}</tbody></table>
  <div class="audit-note"><b>Why this matters:</b> failed-breakout rate is a regime signal — currently ${fr} over 30 days. Under 25% = normal, 25–40% = reduce size, over 40% = stop initiating new positions.</div>`;
}

function sectorBox(){
  const sb = D.sectorBreakdown||[];
  if(!sb.length) return '';
  const max = Math.max(...sb.map(s=>s.count));
  const rows = sb.map(s=>{
    const warn = s.pct>=40;
    return `<div class="sector-row"><div class="sector-name">${s.sector}</div>
      <div class="sector-track"><div class="sector-fill ${warn?'warn':''}" style="width:${s.count/max*100}%"></div></div>
      <div class="sector-val">${s.count} · ${s.pct}%</div></div>`;
  }).join('');
  return `<div class="sector-box"><h3>Sector concentration${sb.some(s=>s.pct>=40)?' ⚠ one sector ≥40%':''}</h3>${rows}</div>`;
}

function screenVolChart(){
  const series = (D.marketRegime||{}).screenVolume60d || [];
  if(!series.length) return;
  const ctx = document.getElementById('screenVolChart').getContext('2d');
  const labels = series.map((_,i)=>{const d=series.length-1-i; if(d===0)return 'Today'; if(d%10===0)return `-${d}d`; return '';});
  new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'Candidates',data:series,borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,0.12)',borderWidth:1.8,fill:true,pointRadius:0,pointHoverRadius:4,tension:0.25}]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{callbacks:{title:items=>{const d=series.length-1-items[0].dataIndex; return d===0?'Today':`${d} day${d>1?'s':''} ago`;},label:it=>`${it.parsed.y} candidates`}}},
      scales:{x:{grid:{display:false},ticks:{font:{size:10},color:'#94a3b8',maxRotation:0,autoSkip:false}},y:{beginAtZero:true,grid:{color:'#f1f5f9'},ticks:{font:{size:10},color:'#94a3b8',precision:0}}}}});
}

function render(){
  const hasVol = ((D.marketRegime||{}).screenVolume60d||[]).length>0;
  document.getElementById('app').innerHTML = `
   <div class="header"><div><h1>🇮🇳 SEPA-VCP India Watchlist</h1>
     <div class="meta">As of ${D.asOf||'–'} · NSE · benchmark ${D.benchmarkLabel||'NIFTY'} · fundamentals: ${D.fundamentalsProvider||'–'}</div></div>
     <div class="meta">Prices in ${CUR}. Not investment advice.</div></div>
   ${D._sample?'<div class="note">⚠️ Sample data shown. Run sepa_screener_india.py locally after the NSE close, then re-render with build_dashboard_india.py to populate real candidates. The funnel, screen-volume chart and audit log fill in as the screener runs daily.</div>':''}
   ${kpis()}
   ${hasVol?`<div class="sparkline-row"><div class="sparkline-row-header"><div class="sparkline-row-title">Screen Volume (60-day history)</div><div class="sparkline-row-sub">Daily count of qualifying candidates · builds up over time</div></div><div class="sparkline-canvas-wrap"><canvas id="screenVolChart" class="sparkline-canvas"></canvas></div></div>`:''}
   ${funnel()}
   <div class="legend"><b>Buckets:</b> A At Pivot · B Just Broke Out · C Developing Base · E Too Early · D Failed Breakout (avoid). Click a ticker to open its TradingView NSE chart.</div>
   ${tabs()}
   ${active==='AUDIT'?auditTable():bucketTable()}
   ${active!=='AUDIT'?sectorBox():''}
   <div class="foot">Mark Minervini SEPA + Volatility Contraction Pattern. RS = relative-strength percentile (1–99). Pivot = line of least resistance from the final contraction. Stop = final-contraction low; Risk = % from pivot to stop (flagged if &gt; ${D.maxLossPct||8}%). Verify every name on the chart before acting.</div>`;
  if(hasVol) screenVolChart();
  document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{active=t.dataset.b;render();});
}
render();
</script></body></html>"""


def main():
    if not DATA.exists():
        raise SystemExit(f"{DATA.name} not found - run sepa_screener_india.py first.")
    data = json.loads(DATA.read_text())
    html = TEMPLATE.replace("__DATA__", json.dumps(data))
    OUT.write_text(html)
    print(f"[OK] Wrote dashboard -> {OUT}  (open in a browser)")


if __name__ == "__main__":
    main()
