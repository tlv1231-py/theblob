"""Command Center — full-screen DAW-style scrubbing timeline.

Three live tracks: portfolio value / SPY / QQQ.
Playhead at current date. Scroll to zoom, drag to pan.
Floating metric strip + terminal feed overlaid.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import text

from dashboard.db import get_session

_ROOT    = Path(__file__).resolve().parent.parent.parent
_ET      = ZoneInfo("America/New_York")
_REG_YAML = _ROOT / "registry" / "strategy_registry.yaml"
_MOM_YAML = _ROOT / "config" / "strategy_params" / "momentum.yaml"
_STARTING_CAPITAL = 100_000.0
_MONITOR_TARGET   = 20


# ── Data loaders ───────────────────────────────────────────────────────────────

def _load_chart_data() -> dict:
    with get_session() as s:
        # Portfolio track — from portfolio_snapshots
        port_rows = s.execute(text("""
            SELECT snapshot_date::text as d, total_value
            FROM portfolio_snapshots
            ORDER BY snapshot_date
        """)).fetchall()

        # Fallback: reconstruct from pnl table
        if not port_rows:
            port_rows = s.execute(text("""
                SELECT date::text as d,
                       COALESCE(cumulative_pnl, 0) + :start as total_value
                FROM pnl WHERE strategy = 'momentum'
                ORDER BY date
            """), {"start": _STARTING_CAPITAL}).fetchall()

        port_dates  = [r.d for r in port_rows]
        port_values = [float(r.total_value) for r in port_rows]

        # Benchmark tracks — SPY / QQQ
        start_cutoff = port_dates[0] if port_dates else "2026-01-01"
        bench_rows = s.execute(text("""
            SELECT symbol, date::text as d, close
            FROM price_bars
            WHERE symbol IN ('SPY','QQQ')
              AND date >= :cut
            ORDER BY symbol, date
        """), {"cut": start_cutoff}).fetchall()

        spy_dates  = [r.d    for r in bench_rows if r.symbol == "SPY"]
        spy_prices = [float(r.close) for r in bench_rows if r.symbol == "SPY"]
        qqq_dates  = [r.d    for r in bench_rows if r.symbol == "QQQ"]
        qqq_prices = [float(r.close) for r in bench_rows if r.symbol == "QQQ"]

        # Status scalars
        mon_days = s.execute(text(
            "SELECT COUNT(DISTINCT date) FROM pnl WHERE strategy='momentum'"
        )).scalar() or 0
        last_run = s.execute(text("SELECT MAX(date) FROM price_bars")).scalar()

        best = s.execute(text("""
            SELECT sharpe, cagr, max_drawdown
            FROM experiments
            WHERE strategy='momentum' AND sharpe IS NOT NULL
            ORDER BY sharpe DESC LIMIT 1
        """)).fetchone()

        latest_pnl = s.execute(text("""
            SELECT daily_pnl, cumulative_pnl
            FROM pnl WHERE strategy='momentum'
            ORDER BY date DESC LIMIT 1
        """)).fetchone()

    return {
        "portfolio":   {"dates": port_dates,  "values": port_values},
        "spy":         {"dates": spy_dates,   "prices": spy_prices},
        "qqq":         {"dates": qqq_dates,   "prices": qqq_prices},
        "monitoring_days": int(mon_days),
        "last_run":    str(last_run) if last_run else "—",
        "sharpe":      float(best.sharpe)       if best and best.sharpe       else None,
        "cagr":        float(best.cagr)         if best and best.cagr         else None,
        "max_drawdown":float(best.max_drawdown) if best and best.max_drawdown else None,
        "day_pnl":        float(latest_pnl.daily_pnl)      if latest_pnl else 0.0,
        "cumulative_pnl": float(latest_pnl.cumulative_pnl) if latest_pnl else 0.0,
        "rolling_sharpe": None,
    }


def _read_strategy_status() -> str:
    try:
        reg = yaml.safe_load(_REG_YAML.read_text())
        for s in reg.get("strategies", []):
            if s.get("name") == "momentum":
                return s.get("status", "unknown").upper()
    except Exception:
        pass
    return "PAPER"


# ── HTML builder ───────────────────────────────────────────────────────────────

def _build_daw_html(data: dict) -> str:
    port  = data["portfolio"]
    spy   = data["spy"]
    qqq   = data["qqq"]
    mon   = data["monitoring_days"]
    sharpe = f'{data["rolling_sharpe"]:.2f}' if data.get("rolling_sharpe") else "—"
    last_nav  = port["values"][-1]     if port["values"] else _STARTING_CAPITAL
    return_pct = (last_nav - _STARTING_CAPITAL) / _STARTING_CAPITAL
    ret_str    = f'{return_pct*100:+.2f}%'
    ret_color  = "#00ff9d" if return_pct >= 0 else "#ff3366"
    nav_str    = f'${last_nav:,.0f}'
    spy_latest = f'${spy["prices"][-1]:.2f}'  if spy["prices"]  else "—"
    qqq_latest = f'${qqq["prices"][-1]:.2f}'  if qqq["prices"]  else "—"
    status     = _read_strategy_status()
    last_run   = data["last_run"][:10] if data["last_run"] else "—"
    day_pnl    = data["day_pnl"]
    dpnl_str   = f'{day_pnl:+,.0f}'

    # Normalize SPY and QQQ to $100K at portfolio start date
    # so all 3 lines are directly comparable on one axis
    spy_norm: list[float] = []
    if spy["prices"] and port["values"]:
        spy_base = spy["prices"][0]
        spy_norm = [p / spy_base * _STARTING_CAPITAL for p in spy["prices"]]

    qqq_norm: list[float] = []
    if qqq["prices"] and port["values"]:
        qqq_base = qqq["prices"][0]
        qqq_norm = [p / qqq_base * _STARTING_CAPITAL for p in qqq["prices"]]

    # Latest normalized values for display
    spy_norm_latest = f'${spy_norm[-1]:,.0f}' if spy_norm else "—"
    qqq_norm_latest = f'${qqq_norm[-1]:,.0f}' if qqq_norm else "—"
    spy_ret = f'{(spy_norm[-1]/_STARTING_CAPITAL - 1)*100:+.1f}%' if spy_norm else "—"
    qqq_ret = f'{(qqq_norm[-1]/_STARTING_CAPITAL - 1)*100:+.1f}%' if qqq_norm else "—"

    # Serialize chart data as JSON (safe for embedding)
    port_dates_j  = json.dumps(port["dates"])
    port_values_j = json.dumps(port["values"])
    spy_dates_j   = json.dumps(spy["dates"])
    spy_norm_j    = json.dumps(spy_norm)
    qqq_dates_j   = json.dumps(qqq["dates"])
    qqq_norm_j    = json.dumps(qqq_norm)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  background:#060008; overflow:hidden;
  font-family:Consolas,'Courier New',monospace;
  color:#f0e0ff; height:100vh; width:100vw;
}}
body::after {{
  content:''; position:fixed; inset:0;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,0,0,0.07) 3px,rgba(0,0,0,0.07) 4px);
  pointer-events:none; z-index:200;
}}
@keyframes chroma-shift {{
  0%,90%,100% {{ text-shadow:0 0 12px rgba(255,0,204,.9),0 0 30px rgba(255,0,204,.4),0 0 60px rgba(255,0,204,.15); }}
  95% {{ text-shadow:-2px 0 rgba(0,229,255,.5),2px 0 rgba(255,0,204,.5),0 0 20px rgba(255,0,204,.6); }}
}}
@keyframes pdot {{
  0%,100% {{ opacity:1; box-shadow:0 0 10px rgba(255,0,204,.9); }}
  50% {{ opacity:.25; box-shadow:0 0 3px rgba(255,0,204,.2); }}
}}
@keyframes shimmer {{
  0%,100% {{ opacity:1; text-shadow:0 0 16px rgba(255,0,204,.5); }}
  50% {{ opacity:.85; text-shadow:0 0 24px rgba(255,0,204,.8); }}
}}

#chart {{ position:absolute; inset:0; }}
#pulse-canvas {{ position:absolute; inset:0; pointer-events:none; z-index:8; }}

/* ── Top bar ── */
.topbar {{
  position:absolute; top:0; left:0; right:0; height:44px;
  background:rgba(6,0,8,.9); border-bottom:1px solid #2a003d;
  backdrop-filter:blur(12px);
  display:flex; align-items:center; padding:0 20px; gap:14px; z-index:10;
}}
.wordmark {{ font-size:15px; font-weight:700; letter-spacing:-.02em; color:#ff00cc; animation:chroma-shift 6s ease-in-out infinite; white-space:nowrap; }}
.pulse-dot {{ width:6px; height:6px; border-radius:50%; background:#ff00cc; box-shadow:0 0 8px rgba(255,0,204,.9); animation:pdot 1.3s ease-in-out infinite; flex-shrink:0; }}
.pill {{ font-size:8px; letter-spacing:.18em; padding:3px 9px; border:1px solid currentColor; white-space:nowrap; display:inline-flex; align-items:center; gap:5px; }}
.pill-m {{ color:#ff00cc; border-color:rgba(255,0,204,.35); text-shadow:0 0 8px rgba(255,0,204,.5); }}
.pill-c {{ color:#00e5ff; border-color:rgba(0,229,255,.3); }}
.pill-d {{ color:#8060a0; border-color:rgba(128,96,160,.25); }}

/* ── NAV card (top-left, under topbar) ── */
.nav-card {{
  position:absolute; top:54px; left:110px;
  background:rgba(6,0,8,.82); border:1px solid #2a003d; border-top:2px solid #ff00cc;
  backdrop-filter:blur(10px); padding:10px 16px; z-index:10; min-width:160px;
}}
.nv-label {{ font-size:7px; letter-spacing:.22em; color:#3a1a4a; text-transform:uppercase; display:block; }}
.nv-val {{ font-size:24px; font-weight:700; letter-spacing:-.03em; color:#ff00cc; display:block; line-height:1.1; animation:shimmer 3s ease-in-out infinite; }}
.nv-ret {{ font-size:11px; font-weight:700; display:block; margin-top:2px; }}
.nv-dpnl {{ font-size:9px; color:#8060a0; display:block; margin-top:4px; letter-spacing:.04em; }}

/* ── Legend chips (top-right) ── */
.legend-strip {{
  position:absolute; top:54px; right:16px;
  display:flex; flex-direction:column; gap:6px; z-index:10;
}}
.leg-item {{
  display:flex; align-items:center; gap:8px;
  background:rgba(6,0,8,.82); border:1px solid #2a003d;
  backdrop-filter:blur(8px); padding:6px 12px;
  min-width:140px;
}}
.leg-dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
.leg-name {{ font-size:8px; letter-spacing:.16em; color:#8060a0; flex:1; }}
.leg-val {{ font-size:11px; font-weight:700; letter-spacing:-.01em; }}
.leg-ret {{ font-size:9px; margin-left:4px; }}

/* ── Bottom bar ── */
.bottombar {{
  position:absolute; bottom:0; left:0; right:0; height:44px;
  background:rgba(6,0,8,.93); border-top:1px solid #2a003d;
  backdrop-filter:blur(12px);
  display:flex; align-items:center; padding:0 20px; gap:0; z-index:10;
}}
.bm {{
  display:flex; flex-direction:column; gap:0;
  padding:0 20px; border-right:1px solid #2a003d;
}}
.bm:first-child {{ padding-left:0; }}
.bm:last-child {{ border-right:none; }}
.bm-label {{ font-size:7px; letter-spacing:.2em; color:#3a1a4a; text-transform:uppercase; line-height:1; }}
.bm-val {{ font-size:13px; font-weight:700; letter-spacing:-.02em; line-height:1.3; }}
.spacer {{ flex:1; }}
.hint {{ font-size:8px; letter-spacing:.1em; color:#2a003d; white-space:nowrap; }}
</style>
</head>
<body>

<div id="chart"></div>
<canvas id="pulse-canvas"></canvas>

<div class="topbar">
  <span class="wordmark">THE BLOB</span>
  <div class="pulse-dot"></div>
  <span class="pill pill-m">MOMENTUM · {status}</span>
  <span class="pill pill-c">▸ DAY {mon}/{_MONITOR_TARGET}</span>
  <span class="pill pill-d">LAST RUN {last_run}</span>
</div>

<div class="nav-card">
  <span class="nv-val">{nav_str}</span>
  <span class="nv-ret" style="color:{ret_color}">{ret_str} vs $100K start</span>
  <span class="nv-dpnl">today  {dpnl_str}</span>
</div>

<div class="legend-strip">
  <div class="leg-item">
    <div class="leg-dot" style="background:#ff00cc;box-shadow:0 0 6px rgba(255,0,204,.7);"></div>
    <span class="leg-name">PORTFOLIO</span>
    <span class="leg-val" style="color:#ff00cc">{nav_str}</span>
    <span class="leg-ret" style="color:{ret_color}">{ret_str}</span>
  </div>
  <div class="leg-item">
    <div class="leg-dot" style="background:#00e5ff;box-shadow:0 0 6px rgba(0,229,255,.7);"></div>
    <span class="leg-name">SPY</span>
    <span class="leg-val" style="color:#00e5ff">{spy_norm_latest}</span>
    <span class="leg-ret" style="color:#00e5ff">{spy_ret}</span>
  </div>
  <div class="leg-item">
    <div class="leg-dot" style="background:#9400ff;box-shadow:0 0 6px rgba(148,0,255,.7);"></div>
    <span class="leg-name">QQQ</span>
    <span class="leg-val" style="color:#9400ff">{qqq_norm_latest}</span>
    <span class="leg-ret" style="color:#9400ff">{qqq_ret}</span>
  </div>
</div>

<div class="bottombar">
  <div class="bm">
    <span class="bm-label">Rolling Sharpe</span>
    <span class="bm-val" style="color:#00e5ff">{sharpe}</span>
  </div>
  <div class="bm">
    <span class="bm-label">Day P&amp;L</span>
    <span class="bm-val" style="color:{'#00ff9d' if day_pnl >= 0 else '#ff3366'}">${abs(day_pnl):,.0f}</span>
  </div>
  <div class="bm">
    <span class="bm-label">SPY price</span>
    <span class="bm-val" style="color:#8060a0">{spy_latest}</span>
  </div>
  <div class="bm">
    <span class="bm-label">QQQ price</span>
    <span class="bm-val" style="color:#8060a0">{qqq_latest}</span>
  </div>
  <div class="spacer"></div>
  <span class="hint">scroll · zoom &nbsp;|&nbsp; drag · pan</span>
</div>

<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script>
var portDates  = {port_dates_j};
var portValues = {port_values_j};
var spyDates   = {spy_dates_j};
var spyNorm    = {spy_norm_j};
var qqqDates   = {qqq_dates_j};
var qqqNorm    = {qqq_norm_j};

var latestDate = portDates.length ? portDates[portDates.length-1] : null;

// Right edge: latest data + 3-day buffer so the pulsing dot isn't pinned to the wall
var xEndDate = latestDate
  ? new Date(new Date(latestDate).getTime() + 3*24*3600*1000).toISOString().split('T')[0]
  : null;

// Default left edge: 60 days back, but never before first data point
var firstDate = portDates.length ? portDates[0] : null;
var xStartDefault = latestDate
  ? new Date(new Date(latestDate).getTime() - 60*24*3600*1000).toISOString().split('T')[0]
  : null;
if (firstDate && xStartDefault && xStartDefault < firstDate) xStartDefault = firstDate;

var xEnd   = xEndDate;
var xStart = xStartDefault;

// Tight Y range for the visible window
function yRange(x0, x1) {{
  var minV = Infinity, maxV = -Infinity;
  var series = [
    [portDates, portValues],
    [spyDates,  spyNorm],
    [qqqDates,  qqqNorm],
  ];
  series.forEach(function(s) {{
    var dates = s[0], vals = s[1];
    for (var i=0; i<dates.length; i++) {{
      if ((!x0 || dates[i] >= x0) && (!x1 || dates[i] <= x1)) {{
        if (vals[i] < minV) minV = vals[i];
        if (vals[i] > maxV) maxV = vals[i];
      }}
    }}
  }});
  if (minV === Infinity) return [null, null];
  var pad = (maxV - minV) * 0.18 || 2000;
  return [minV - pad, maxV + pad];
}}

var yr = yRange(xStart, xEnd);

var traces = [
  // $100K baseline reference
  {{
    x: [portDates[0]||xStart, latestDate],
    y: [100000, 100000],
    type:'scatter', mode:'lines',
    line:{{ color:'rgba(58,26,74,0.6)', width:1, dash:'dot' }},
    name:'$100K baseline',
    hoverinfo:'skip',
  }},
  {{
    x: spyDates, y: spyNorm,
    type:'scatter', mode:'lines',
    line:{{ color:'#00e5ff', width:1.5, dash:'dot' }},
    name:'SPY (norm)',
    hovertemplate:'<b style="color:#00e5ff">SPY $%{{y:,.0f}}</b><extra></extra>',
  }},
  {{
    x: qqqDates, y: qqqNorm,
    type:'scatter', mode:'lines',
    line:{{ color:'#9400ff', width:1.5, dash:'dot' }},
    name:'QQQ (norm)',
    hovertemplate:'<b style="color:#9400ff">QQQ $%{{y:,.0f}}</b><extra></extra>',
  }},
  // Portfolio on top — solid, brightest
  {{
    x: portDates, y: portValues,
    type:'scatter', mode:'lines',
    line:{{ color:'#ff00cc', width:2.5 }},
    name:'PORTFOLIO',
    hovertemplate:'<b style="color:#ff00cc">PORTFOLIO $%{{y:,.0f}}</b><extra></extra>',
  }},
];

var shapes = latestDate ? [{{
  type:'line', xref:'x', yref:'paper',
  x0:latestDate, x1:latestDate, y0:0, y1:1,
  line:{{ color:'rgba(255,255,255,0.15)', width:1, dash:'dot' }},
}}] : [];

var annotations = latestDate ? [{{
  xref:'x', yref:'paper',
  x:latestDate, y:1.01,
  text:'▶ NOW',
  showarrow:false,
  font:{{ family:'Consolas', size:8, color:'rgba(255,255,255,0.3)' }},
  xanchor:'left',
}}] : [];

var layout = {{
  paper_bgcolor:'#060008',
  plot_bgcolor:'#060008',
  margin:{{ t:44, b:46, l:72, r:16 }},
  width: window.innerWidth,
  height: window.innerHeight,

  xaxis:{{
    range: xStart ? [xStart, xEnd] : undefined,
    showgrid:true, gridcolor:'rgba(42,0,61,0.5)', gridwidth:1,
    tickfont:{{ family:'Consolas', size:8, color:'#3a1a4a' }},
    tickformat:'%b %d', zeroline:false, showline:false, type:'date', fixedrange:false,
  }},
  yaxis:{{
    range: yr[0] !== null ? yr : undefined,
    showgrid:true, gridcolor:'rgba(42,0,61,0.35)',
    tickfont:{{ family:'Consolas', size:8, color:'#3a1a4a' }},
    tickformat:'$,.0f',
    zeroline:false, showline:false, fixedrange:true,
    tickprefix:'',
  }},

  shapes, annotations,
  showlegend:false,
  dragmode:'pan',
  hoverlabel:{{ bgcolor:'#0d0010', bordercolor:'#2a003d', font:{{ family:'Consolas', size:9, color:'#f0e0ff' }} }},
  hovermode:'x unified',
}};

var config = {{ scrollZoom:true, displayModeBar:false, responsive:true }};
var gd = document.getElementById('chart');

// ── Pulsing canvas dots ────────────────────────────────
var canvas = document.getElementById('pulse-canvas');
function resizeCanvas() {{ canvas.width=window.innerWidth; canvas.height=window.innerHeight; }}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

var pulseTargets = [];
function buildTargets() {{
  pulseTargets = [];
  // trace order: 0=baseline(skip), 1=SPY, 2=QQQ, 3=PORTFOLIO
  [[1,[0,229,255]], [2,[148,0,255]], [3,[255,0,204]]].forEach(function(ic) {{
    var tr = gd.data[ic[0]];
    if (tr && tr.x && tr.x.length) {{
      var pt = {{ x: tr.x[tr.x.length-1], y: tr.y[tr.y.length-1], rgb: ic[1] }};
      pulseTargets.push(pt);
      console.log('pulse target', pt.x, pt.y);
    }}
  }});
  console.log('canvas size', canvas.width, canvas.height, 'targets', pulseTargets.length);
}}

var phase = 0;
var rafId = null;
function drawPulse() {{
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  phase += 0.03;

  pulseTargets.forEach(function(t) {{
    try {{
      var fl = gd._fullLayout;
      if (!fl || !fl.xaxis || !fl.yaxis) return;
      // d2l converts data value → linearized internal value; l2p converts that → pixels
      var cx = fl.xaxis.l2p(fl.xaxis.d2l(t.x)) + fl.margin.l;
      var cy = fl.yaxis.l2p(fl.yaxis.d2l(t.y)) + fl.margin.t;
      if (!isFinite(cx) || !isFinite(cy)) return;
      var r=t.rgb[0], g=t.rgb[1], b=t.rgb[2];

      // 3 staggered expanding rings
      for (var k = 0; k < 3; k++) {{
        var p = (Math.sin(phase - k * 1.1) + 1) / 2;
        ctx.beginPath();
        ctx.arc(cx, cy, 5 + p * 26, 0, Math.PI*2);
        ctx.strokeStyle = 'rgba('+r+','+g+','+b+','+(0.7*(1-p))+')';
        ctx.lineWidth = 2 - k*0.4;
        ctx.stroke();
      }}

      // Bright core with glow
      ctx.shadowColor = 'rgba('+r+','+g+','+b+',1)';
      ctx.shadowBlur = 22;
      ctx.beginPath();
      ctx.arc(cx, cy, 6, 0, Math.PI*2);
      ctx.fillStyle = 'rgba('+r+','+g+','+b+',1)';
      ctx.fill();

      // White hot center
      ctx.shadowBlur = 0;
      ctx.beginPath();
      ctx.arc(cx, cy, 2.5, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.fill();
    }} catch(e) {{ console.error('pulse err', e, t); }}
  }});
  rafId = requestAnimationFrame(drawPulse);
}}

// Start everything once Plotly has rendered
Plotly.newPlot(gd, traces, layout, config).then(function() {{
  buildTargets();
  if (rafId) cancelAnimationFrame(rafId);
  drawPulse();
}});

gd.on('plotly_afterplot', buildTargets);

// Dynamically tighten Y as user pans/zooms
gd.on('plotly_relayout', function(update) {{
  if (update['xaxis.range[0]'] !== undefined) {{
    var x0 = (update['xaxis.range[0]']||'').split('T')[0];
    var x1 = (update['xaxis.range[1]']||'').split('T')[0];
    var r = yRange(x0||null, x1||null);
    if (r[0] !== null) Plotly.relayout(gd, {{'yaxis.range': r}});
  }}
  buildTargets();
}});

window.addEventListener('load', function() {{
  Plotly.relayout(gd, {{ width:window.innerWidth, height:window.innerHeight }});
}});
window.addEventListener('resize', function() {{
  Plotly.relayout(gd, {{ width:window.innerWidth, height:window.innerHeight }});
  resizeCanvas();
}});
</script>
</body>
</html>"""


# ── Entry point ────────────────────────────────────────────────────────────────

def render() -> None:
    st.markdown("""
    <style>
    section[data-testid="stMain"] > div,
    [data-testid="stMainBlockContainer"],
    [data-testid="block-container"],
    div[class*="block-container"],
    .main .block-container {
        padding: 0 !important;
        max-width: 100% !important;
    }
    iframe { display: block !important; }
    </style>
    """, unsafe_allow_html=True)

    try:
        data = _load_chart_data()
    except Exception as e:
        st.error(f"DB connection failed: {e}")
        return

    html = _build_daw_html(data)
    components.html(html, height=860, scrolling=False)
