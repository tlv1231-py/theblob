"""The Blob — algorithmic trading research and paper trading platform.

Entry point: streamlit run dashboard/app.py
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

st.set_page_config(
    page_title="The Blob",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={},
)

from dashboard.views import home, benchmarks, portfolio, signals, backtest_lab, risk_monitor, daytrader

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Futurepunk palette ───────────────────────────────────────────────── */
:root {
    --bg:          #060008;
    --bg2:         #0d0010;
    --bg3:         #160018;
    --border:      #2a003d;
    --border2:     #3d0055;
    --accent:      #ff00cc;
    --accent2:     #00e5ff;
    --accent3:     #9400ff;
    --accent-glow: rgba(255,0,204,0.15);
    --text-hi:     #f0e0ff;
    --text-mid:    #8060a0;
    --text-dim:    #3a1a4a;
    --danger:      #ff3366;
    --warn:        #ff9900;
    --ok:          #00ff9d;
}

/* ── Global ────────────────────────────────────────────────────────────── */
html, body, .stApp, [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="stMainBlockContainer"] {
    background-color: var(--bg) !important;
    color: var(--text-hi) !important;
}

/* Scanline overlay on whole app */
body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 3px,
        rgba(0,0,0,0.06) 3px,
        rgba(0,0,0,0.06) 4px
    );
    pointer-events: none;
    z-index: 9999;
}

html, body, [class*="css"], .stMarkdown, p, li, label, span {
    font-family: Consolas, 'Courier New', monospace !important;
}

/* ── Headings ──────────────────────────────────────────────────────────── */
h1, h2, h3, h4 {
    font-family: Consolas, 'Courier New', monospace !important;
    font-weight: 700 !important;
    color: var(--text-hi) !important;
}
h1 { font-size: 1.3rem !important; letter-spacing: -0.02em !important; }
h2 { font-size: 0.95rem !important; letter-spacing: -0.01em !important; }
h3 {
    font-size: 0.62rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.16em !important;
    color: var(--text-dim) !important;
    font-weight: 600 !important;
}

/* ── Metrics ───────────────────────────────────────────────────────────── */
[data-testid="stMetricValue"] {
    font-size: 1.2rem !important;
    font-weight: 700 !important;
    color: var(--text-hi) !important;
    letter-spacing: -0.03em !important;
    font-family: Consolas, monospace !important;
}
[data-testid="stMetricLabel"] > div {
    font-family: Consolas, monospace !important;
    font-size: 0.56rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.16em !important;
    color: var(--text-dim) !important;
}
[data-testid="stMetric"] {
    background-color: var(--bg2) !important;
    border: 1px solid var(--border) !important;
    border-top: 1px solid var(--accent3) !important;
    border-radius: 0px !important;
    padding: 14px 16px 12px !important;
}

/* ── Sidebar ───────────────────────────────────────────────────────────── */
[data-testid="stSidebar"],
section[data-testid="stSidebar"] {
    background-color: var(--bg) !important;
    border-right: 1px solid var(--border) !important;
    min-width: 220px !important;
    max-width: 220px !important;
}
[data-testid="stSidebar"] * {
    font-family: Consolas, 'Courier New', monospace !important;
}
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"] { display: none !important; }

/* ── Sidebar wordmark ──────────────────────────────────────────────────── */
.blob-wordmark {
    font-family: Consolas, 'Courier New', monospace !important;
    font-size: 1.25rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    color: var(--accent) !important;
    text-shadow:
        0 0 12px rgba(255,0,204,0.8),
        0 0 30px rgba(255,0,204,0.3),
        0 0 60px rgba(255,0,204,0.1) !important;
    display: block !important;
    padding: 4px 0 1px !important;
}
.blob-sub {
    font-size: 0.54rem !important;
    letter-spacing: 0.2em !important;
    color: var(--text-dim) !important;
    text-transform: uppercase !important;
    display: block !important;
    margin-top: -1px !important;
}

/* ── Sidebar nav ───────────────────────────────────────────────────────── */
[data-testid="stSidebar"] .stRadio label {
    font-size: 0.74rem !important;
    font-weight: 400 !important;
    color: var(--text-mid) !important;
    letter-spacing: 0.02em !important;
    padding: 3px 0 !important;
    transition: color 0.1s !important;
}
[data-testid="stSidebar"] .stRadio label:hover { color: var(--accent) !important; }

/* ── Terminal feed ─────────────────────────────────────────────────────── */
.term-feed-wrap {
    margin-top: 8px;
    border: 1px solid var(--border);
    border-left: 2px solid var(--accent);
    background: rgba(6,0,8,0.95);
    padding: 0;
    overflow: hidden;
}
.term-feed-header {
    font-size: 8px;
    letter-spacing: 0.22em;
    color: var(--accent);
    text-shadow: 0 0 8px rgba(255,0,204,0.5);
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
    display: block;
}
.term-feed-body {
    padding: 4px 0;
    max-height: 320px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border2) transparent;
}
.term-entry {
    padding: 5px 10px 4px;
    border-bottom: 1px solid rgba(42,0,61,0.4);
}
.term-entry:last-child { border-bottom: none; }
.term-main {
    display: flex;
    align-items: baseline;
    gap: 6px;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.3;
}
.term-tag {
    font-size: 8px;
    letter-spacing: .18em;
    opacity: .7;
    flex-shrink: 0;
}
.term-sym {
    font-size: 13px;
    font-weight: 700;
    flex-shrink: 0;
}
.term-val {
    font-size: 11px;
    font-weight: 400;
    opacity: .85;
}
.term-sub {
    font-size: 9px;
    color: #3a1a4a;
    margin-top: 2px;
    letter-spacing: .04em;
}
.ev-fill     { color: #ff00cc; }
.ev-signal   { color: #00e5ff; }
.ev-snapshot { color: #9400ff; }
.ev-pipeline { color: var(--text-mid); }

.tw-cursor {
    color: var(--accent);
    font-weight: 400;
}
.tw-cursor.blink {
    animation: blink-cur 1s step-start infinite;
}
@keyframes blink-cur {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0; }
}
@keyframes term-in {
    from { opacity: 0; }
    to   { opacity: 1; }
}

/* ── Dividers ──────────────────────────────────────────────────────────── */
hr {
    border: none !important;
    border-top: 1px solid var(--border) !important;
    margin: 0.8rem 0 !important;
}

/* ── Buttons ───────────────────────────────────────────────────────────── */
.stButton > button {
    font-family: Consolas, monospace !important;
    font-size: 0.68rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    border-radius: 0px !important;
    border: 1px solid var(--border2) !important;
    background: var(--bg2) !important;
    color: var(--text-mid) !important;
    transition: all 0.12s !important;
    padding: 7px 14px !important;
}
.stButton > button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
    box-shadow: 0 0 14px rgba(255,0,204,0.12) !important;
}
.stButton > button[kind="primary"] {
    background: transparent !important;
    border: 1px solid var(--accent) !important;
    color: var(--accent) !important;
    box-shadow: 0 0 16px rgba(255,0,204,0.1) !important;
}
.stButton > button[kind="primary"]:hover {
    background: rgba(255,0,204,0.06) !important;
    box-shadow: 0 0 28px rgba(255,0,204,0.2) !important;
}

/* ── Tabs ──────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid var(--border) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    font-family: Consolas, monospace !important;
    font-size: 0.62rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
    padding: 8px 18px !important;
    color: var(--text-dim) !important;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    color: var(--accent) !important;
    border-bottom: 1px solid var(--accent) !important;
    background: transparent !important;
    text-shadow: 0 0 8px rgba(255,0,204,0.4) !important;
}

/* ── Inputs ────────────────────────────────────────────────────────────── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    font-family: Consolas, monospace !important;
    font-size: 0.78rem !important;
    background-color: var(--bg2) !important;
    border: 1px solid var(--border2) !important;
    border-radius: 0px !important;
    color: var(--text-hi) !important;
}

/* ── Dataframes ────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border) !important;
    border-radius: 0px !important;
}

/* ── Alerts ────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 0px !important;
    font-family: Consolas, monospace !important;
    font-size: 0.70rem !important;
    border-left-width: 2px !important;
    background: var(--bg2) !important;
}

/* ── Captions ──────────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"] p {
    font-family: Consolas, monospace !important;
    font-size: 0.60rem !important;
    color: var(--text-dim) !important;
    letter-spacing: 0.06em !important;
}

/* ── Scrollbars ────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 3px; height: 3px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 0; }
::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

/* ── Zero padding on Command Center ───────────────────────────────────── */
[data-testid="stMainBlockContainer"] {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
}
[data-testid="stMain"] > div:first-child { padding-top: 0 !important; }

/* ── Hide ALL Streamlit chrome ─────────────────────────────────────────── */
#MainMenu, header, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stHeader"],
[data-testid="stAppViewBlockContainer"] > div:first-child,
footer { display: none !important; visibility: hidden !important; height: 0 !important; }

/* Kill the top padding that Streamlit adds for the header */
.stApp > header { display: none !important; }
[data-testid="stMain"] { padding-top: 0 !important; margin-top: 0 !important; }
[data-testid="stAppViewContainer"] { padding-top: 0 !important; }

/* ── Live dot ──────────────────────────────────────────────────────────── */
.live-dot {
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 8px var(--accent);
    animation: dot-pulse 1.2s ease-in-out infinite;
    margin-right: 5px;
    vertical-align: middle;
}
@keyframes dot-pulse {
    0%, 100% { opacity: 1; box-shadow: 0 0 10px rgba(255,0,204,0.8); }
    50%       { opacity: 0.3; box-shadow: 0 0 4px rgba(255,0,204,0.2); }
}
</style>
""", unsafe_allow_html=True)

# ── Page registry ──────────────────────────────────────────────────────────────
PAGES = {
    "Command Center": home.render,
    "Portfolio":      portfolio.render,
    "Benchmarks":     benchmarks.render,
    "Signals":        signals.render,
    "Backtest Lab":   backtest_lab.render,
    "Risk Monitor":   risk_monitor.render,
    "Daytrader":      daytrader.render,
}

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.markdown(
    '<span class="blob-wordmark">The Blob</span>'
    '<span class="blob-sub">Algorithmic Trading</span>',
    unsafe_allow_html=True,
)
st.sidebar.divider()

selection = st.sidebar.radio("nav", list(PAGES.keys()), label_visibility="collapsed")
st.sidebar.divider()

# ── Bottom terminal feed (full-width fixed panel) ─────────────────────────────
def _render_bottom_terminal() -> None:
    try:
        from sqlalchemy import text as _text
        from dashboard.db import get_session

        events: list[dict] = []

        with get_session() as s:
            fills = s.execute(_text("""
                SELECT symbol, UPPER(side) as side, quantity,
                       ROUND(fill_price::numeric,2) as price,
                       filled_at as ts
                FROM fills ORDER BY filled_at DESC LIMIT 10
            """)).fetchall()
            for r in fills:
                action = "bought" if r.side == "BUY" else "sold"
                events.append({"type": "fill", "sym": r.symbol,
                                "line1": f"{action} {r.quantity} shares",
                                "line2": f"filled at ${r.price}", "ts": r.ts})

            sigs = s.execute(_text("""
                SELECT symbol, UPPER(direction) as direction,
                       ROUND(score::numeric,3) as score,
                       as_of_date::timestamp as ts
                FROM signals ORDER BY as_of_date DESC LIMIT 10
            """)).fetchall()
            for r in sigs:
                events.append({"type": "signal", "sym": r.symbol,
                                "line1": "flagged for entry",
                                "line2": f"momentum score {r.score}", "ts": r.ts})

            snaps = s.execute(_text("""
                SELECT ROUND(total_value::numeric,0) as nav,
                       snapshot_date::timestamp as ts
                FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 3
            """)).fetchall()
            for r in snaps:
                events.append({"type": "snapshot", "sym": "PORTFOLIO",
                                "line1": f"valued at ${int(r.nav):,}",
                                "line2": "end of day snapshot", "ts": r.ts})

        # newest first in HTML — column-reverse makes newest appear at bottom
        events.sort(key=lambda e: e["ts"] if e["ts"] else "", reverse=True)
        events = events[:20]

        css_class = {"fill": "ev-fill", "signal": "ev-signal", "snapshot": "ev-snapshot"}
        type_tag  = {"fill": "TRADE", "signal": "SIGNAL", "snapshot": "UPDATE"}

        CHAR_MS  = 14
        LINE_GAP = 80
        lines_html = ""
        # animate newest-last (visually bottom) with shortest delay so it types first
        for idx, ev in enumerate(reversed(events)):
            ts_raw = str(ev["ts"]) if ev["ts"] else ""
            ts_str = ts_raw[5:16] if len(ts_raw) >= 16 else ts_raw
            cls    = css_class.get(ev["type"], "ev-pipeline")
            tag    = type_tag.get(ev["type"], "EVT")
            text   = f"{tag}  {ev['sym']}  —  {ev.get('line1','')}"
            sub    = f"{ts_str}  ·  {ev.get('line2','')}"
            n      = max(len(text), 1)
            dur    = n * CHAR_MS
            delay  = idx * (LINE_GAP / 1000)

            lines_html += f"""
<div class="te">
  <div class="tm {cls}" style="animation:tw {dur}ms steps({n},end) {delay:.2f}s forwards">{text}</div>
  <div class="ts" style="animation:fi 0.2s ease {delay + dur/1000:.2f}s forwards">{sub}</div>
</div>"""

        blink_delay = len(events) * LINE_GAP / 1000

        st.markdown(f"""
<style>
#blob-term{{
  position:fixed; bottom:0; left:0; right:0; height:220px; z-index:9000;
  background:rgba(4,0,6,.97); border-top:2px solid #ff00cc;
  font-family:Consolas,'Courier New',monospace;
  display:flex; flex-direction:column;
}}
#blob-term-hdr{{
  flex-shrink:0; padding:5px 16px; border-bottom:1px solid #2a003d;
  font-size:8px; letter-spacing:.22em; color:#ff00cc;
  text-shadow:0 0 8px rgba(255,0,204,.5);
  display:flex; align-items:center; gap:10px;
}}
#blob-term-hdr span.live{{
  width:6px;height:6px;border-radius:50%;background:#ff00cc;
  box-shadow:0 0 6px #ff00cc;
  animation:blink-c 2s ease-in-out infinite;
  flex-shrink:0;
}}
#blob-term-body{{
  flex:1; overflow:hidden;
  display:flex; flex-direction:column-reverse;
  padding:6px 0 4px;
}}
.te{{padding:3px 18px 2px;border-top:1px solid rgba(42,0,61,.3);flex-shrink:0}}
.tm{{font-size:13px;font-weight:600;line-height:1.4;
     overflow:hidden;white-space:nowrap;width:0;max-width:100%}}
.ts{{font-size:9px;color:#3a1a4a;margin-top:1px;letter-spacing:.04em;opacity:0}}
.ev-fill{{color:#ff00cc}}.ev-signal{{color:#00e5ff}}.ev-snapshot{{color:#9400ff}}
#blob-cursor{{padding:4px 18px;flex-shrink:0;
  opacity:0;animation:fi 0s {blink_delay:.2f}s forwards}}
#blob-cursor span{{color:#ff00cc;animation:blink-c 1s step-start {blink_delay:.2f}s infinite}}
@keyframes tw    {{from{{width:0}}to{{width:100%}}}}
@keyframes fi    {{from{{opacity:0}}to{{opacity:1}}}}
@keyframes blink-c{{0%,100%{{opacity:1}}50%{{opacity:0}}}}
/* push page content up so it's not hidden behind terminal */
section[data-testid="stMain"] .block-container{{padding-bottom:240px!important}}
</style>
<div id="blob-term">
  <div id="blob-term-hdr"><span class="live"></span>SYSTEM FEED</div>
  <div id="blob-term-body">
    <div id="blob-cursor"><span>█</span></div>
    {lines_html}
  </div>
</div>
""", unsafe_allow_html=True)

    except Exception:
        pass  # terminal offline — fail silently

_render_bottom_terminal()

# ── Sidebar pipeline runner ────────────────────────────────────────────────────
st.sidebar.divider()

if "pipeline_proc" not in st.session_state:
    st.session_state.pipeline_proc    = None
    st.session_state.pipeline_output  = []
    st.session_state.pipeline_running = False

import subprocess as _sp, sys as _sys

_label = "◼ STOP" if st.session_state.pipeline_running else "▶ RUN PIPELINE"
if st.sidebar.button(_label, type="primary", key="sidebar_pipeline_btn"):
    if st.session_state.pipeline_running and st.session_state.pipeline_proc:
        st.session_state.pipeline_proc.terminate()
        st.session_state.pipeline_running = False
        st.session_state.pipeline_proc    = None
    else:
        _proc = _sp.Popen(
            [_sys.executable, str(_ROOT / "run_pipeline.py")],
            stdout=_sp.PIPE, stderr=_sp.STDOUT,
            text=True, bufsize=1, cwd=str(_ROOT),
            encoding="utf-8", errors="replace",
        )
        st.session_state.pipeline_proc    = _proc
        st.session_state.pipeline_running = True
        st.session_state.pipeline_output  = []

if st.session_state.pipeline_running and st.session_state.pipeline_proc:
    _proc = st.session_state.pipeline_proc
    try:
        for _line in iter(_proc.stdout.readline, ""):
            if not _line: break
            st.session_state.pipeline_output.append(_line.rstrip())
    except Exception:
        pass
    if _proc.poll() is not None:
        st.session_state.pipeline_running = False

if st.session_state.pipeline_output:
    for _ln in st.session_state.pipeline_output[-3:]:
        st.sidebar.caption(_ln)

# ── Render page ────────────────────────────────────────────────────────────────
PAGES[selection]()
