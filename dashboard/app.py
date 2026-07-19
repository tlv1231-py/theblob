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
    initial_sidebar_state="collapsed",
    menu_items={},
)

from dashboard.views import (home, benchmarks, portfolio, signals, backtest_lab,
                             risk_monitor, daytrader, stream, stream2, stream_hq)

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

/* ── Hide sidebar entirely ─────────────────────────────────────────────── */
[data-testid="stSidebar"],
section[data-testid="stSidebar"],
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"] { display: none !important; }

/* ── Icon rail ─────────────────────────────────────────────────────────── */
#icon-rail {
    position: fixed;
    left: 0; top: 0; bottom: 0;
    width: 52px;
    background: var(--bg);
    border-right: 1px solid var(--border2);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0;
    z-index: 1000;
    gap: 0;
}
#icon-rail .ir-logo {
    font-size: 1.2rem;
    color: var(--accent);
    text-shadow: 0 0 16px rgba(255,0,204,0.7);
    padding: 14px 0 12px;
    letter-spacing: -0.02em;
    line-height: 1;
    cursor: default;
    font-family: Consolas, monospace;
}
#icon-rail .ir-divider {
    width: 28px;
    height: 1px;
    background: var(--border);
    margin: 2px 0 6px;
    flex-shrink: 0;
}
#icon-rail .ir-spacer { flex: 1; }
#icon-rail a.ir-item {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 44px;
    padding: 0;
    margin: 0;
    text-decoration: none;
    color: var(--text-dim);
    font-size: 1.1rem;
    line-height: 1;
    font-family: Consolas, monospace;
    text-align: center;
    transition: color 0.12s, background 0.12s;
    position: relative;
    flex-shrink: 0;
    box-sizing: border-box;
}
#icon-rail a.ir-item:hover {
    color: var(--accent2);
    background: rgba(0,229,255,0.06);
}
#icon-rail a.ir-item.ir-active {
    color: var(--accent);
}
#icon-rail a.ir-item.ir-active::before {
    content: '';
    position: absolute;
    left: 0; top: 6px; bottom: 6px;
    width: 2px;
    background: var(--accent);
    box-shadow: 0 0 8px rgba(255,0,204,0.6);
}

/* ── Shift main content right of icon rail ─────────────────────────────── */
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    margin-left: 52px !important;
}

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
    "Stream":         stream.render,
    "Stream 2":       stream2.render,
    "Stream HQ":      stream_hq.render,
}

# ── Page selection via query params ───────────────────────────────────────────
_qp_page = st.query_params.get("page", "Command Center")
if _qp_page not in PAGES:
    _qp_page = "Command Center"

# ── Icon rail ──────────────────────────────────────────────────────────────────
_PAGE_ICONS = {
    "Command Center": ("◈", "Command Center"),
    "Portfolio":      ("▣", "Portfolio"),
    "Benchmarks":     ("≋", "Benchmarks"),
    "Signals":        ("⚡", "Signals"),
    "Backtest Lab":   ("⟳", "Backtest Lab"),
    "Risk Monitor":   ("◬", "Risk Monitor"),
    "Daytrader":      ("⊕", "Daytrader"),
    "Stream":         ("▶", "Stream (vertical)"),
    "Stream 2":       ("▷", "Stream 2 (vertical) — scaffold"),
    "Stream HQ":      ("◉", "Stream HQ"),
}

_rail_items = ""
for _pg, (_icon, _label) in _PAGE_ICONS.items():
    _active_cls = " ir-active" if _pg == _qp_page else ""
    _href = f"?page={_pg.replace(' ', '+')}"
    _rail_items += f'<a href="{_href}" class="ir-item{_active_cls}" title="{_label}">{_icon}</a>\n'

st.markdown(f"""
<div id="icon-rail">
  <div class="ir-logo">◈</div>
  <div class="ir-divider"></div>
  {_rail_items}
  <div class="ir-spacer"></div>
</div>
""", unsafe_allow_html=True)

# ── Render page ────────────────────────────────────────────────────────────────
PAGES[_qp_page]()
