"""Vertical Stream — 1080x1920 portrait stage for autonomous livestreaming.

Reorients Command Center assets into 9:16. Designed to be pointed at by a
browser-source encoder (OBS et al) and left running unattended: no hover
states, no click targets, no scrollbars. Every pixel of motion comes from
live data, not from a user.

Reuse boundaries — deliberate:
  * home._load_chart_data()  reused verbatim. One query pass, same numbers as
    the Command Center. This page must never disagree with Home.
  * blob.js                  reused verbatim. It is self-contained by contract.
  * home_nav.js              NOT reused. It binds ~173 getElementById calls to
    Command Center nodes that do not exist here, and its margins/axis are tuned
    for a wide stage. Portrait gets its own lean renderer in stream.js.

Streamlit serves the shell once and is then out of the loop — same reasoning as
BLOB.md: a rerun per frame would mean a DB round trip per frame.
"""
from __future__ import annotations

import json
import pathlib as _pl

import streamlit as st
import streamlit.components.v1 as components

from config import risk_limits
from dashboard.views.home import _load_chart_data, _read_strategy_status

_DASHBOARD = _pl.Path(__file__).resolve().parent.parent

# Mirrors the publishable Supabase credentials already inlined in home_nav.js.
# Publishable/anon key — client-side by design. Kept here so the stream page
# polls the same nav_snapshots source without importing that file's DOM baggage.
_SUPA_URL = "https://seeevuklabvhkawawtxn.supabase.co"
_SUPA_KEY = "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY"

_STARTING_CAPITAL = 100_000.0

# The stage is fixed. The encoder captures exactly this; the browser only ever
# scales it to fit for preview.
_STAGE_W = 1080
_STAGE_H = 1920


def _build_stream_html(data: dict) -> str:
    """Assemble the portrait stage: CSS, DOM skeleton, payload, renderers."""
    nav_pts = data.get("nav_snap_pts") or []
    port = data.get("portfolio") or {}
    port_values = port.get("values") or []

    latest_nav = nav_pts[-1]["v"] if nav_pts else (
        port_values[-1] if port_values else _STARTING_CAPITAL
    )
    day_pnl = float(data.get("day_pnl") or 0.0)
    prev_nav = latest_nav - day_pnl
    day_pnl_pct = (day_pnl / prev_nav * 100.0) if prev_nav else 0.0

    payload = {
        "nav_pts":        nav_pts,
        "nav":            latest_nav,
        "day_pnl":        day_pnl,
        "day_pnl_pct":    day_pnl_pct,
        "cumulative_pnl": float(data.get("cumulative_pnl") or 0.0),
        "starting_capital": _STARTING_CAPITAL,
        "positions":      data.get("positions_data") or [],
        "events":         (data.get("term_events") or [])[:40],
        "queued":         data.get("queued_actions") or [],
        "sharpe":         data.get("sharpe"),
        "cagr":           data.get("cagr"),
        "max_drawdown":   data.get("max_drawdown"),
        "monitoring_days": data.get("monitoring_days") or 0,
        "last_run":       data.get("last_run") or "—",
        "status":         _read_strategy_status(),
        "alpaca":         data.get("alpaca") or {},
        "limits": {
            "daily_dd":  risk_limits.MAX_DAILY_DRAWDOWN,
            "total_dd":  risk_limits.MAX_TOTAL_DRAWDOWN,
            "max_pos":   risk_limits.MAX_POSITION_SIZE,
            "max_gross": risk_limits.MAX_GROSS_EXPOSURE,
        },
        "supa": {"url": _SUPA_URL, "key": _SUPA_KEY},
        "stage": {"w": _STAGE_W, "h": _STAGE_H},
    }

    blob_js   = (_DASHBOARD / "blob.js").read_text("utf-8")
    stream_js = (_DASHBOARD / "stream.js").read_text("utf-8")
    css       = (_DASHBOARD / "stream.css").read_text("utf-8")

    # Not an f-string: the CSS/JS brace density makes escaping a liability.
    # Data crosses into JS through one payload object instead.
    return (
        "<style>" + css + "</style>"
        + _STAGE_HTML
        + "<script>window._TND_STREAM = "
        + json.dumps(payload, default=str)
        + ";</script>"
        + "<script>" + blob_js + "</script>"
        + "<script>" + stream_js + "</script>"
    )


_STAGE_HTML = """
<div id="stage-wrap">
  <div id="stage">
    <div id="scanlines"></div>
    <div id="vignette"></div>

    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <header id="s-head">
      <div class="hd-brand"><span class="hd-mark">&#x25C8;</span> THE BLOB</div>
      <div class="hd-right">
        <span class="hd-live"><i class="dot"></i>LIVE</span>
        <span class="hd-clock" id="hd-clock">--:--:--</span>
        <span class="hd-sess" id="hd-sess">&mdash;</span>
      </div>
    </header>

    <!-- ── Hero: blob + NAV ───────────────────────────────────────────── -->
    <section id="s-hero">
      <div class="hero-blob">
        <div class="blob-bloom" id="blob-bloom"></div>
        <canvas id="blobCanvas"></canvas>
        <div class="blob-mood" id="blob-mood">IDLE</div>
      </div>
      <div class="hero-num">
        <div class="hero-label">PORTFOLIO VALUE</div>
        <div class="hero-nav" id="hero-nav">$&mdash;</div>
        <div class="hero-day" id="hero-day">&mdash;</div>
        <div class="hero-chips">
          <span class="chip" id="chip-status">PAPER</span>
          <span class="chip chip-dim" id="chip-day">DAY &mdash;/20</span>
          <span class="chip chip-dim" id="chip-total">TOTAL &mdash;</span>
        </div>
      </div>
    </section>

    <!-- ── NAV chart ──────────────────────────────────────────────────── -->
    <section id="s-chart">
      <div class="sect-hdr">
        <span class="sect-name">NAV</span>
        <span class="sect-meta" id="chart-meta">&mdash;</span>
      </div>
      <canvas id="navCanvas"></canvas>
    </section>

    <!-- ── Positions ──────────────────────────────────────────────────── -->
    <section id="s-pos">
      <div class="sect-hdr">
        <span class="sect-name">POSITIONS</span>
        <span class="sect-meta" id="pos-meta">&mdash;</span>
      </div>
      <div id="pos-list"></div>
    </section>

    <!-- ── Feed ───────────────────────────────────────────────────────── -->
    <section id="s-feed">
      <div class="sect-hdr">
        <span class="sect-name">FEED</span>
        <span class="sect-meta" id="feed-meta">&mdash;</span>
      </div>
      <div id="feed-list"></div>
    </section>

    <!-- ── Footer ticker ──────────────────────────────────────────────── -->
    <footer id="s-foot">
      <div id="foot-track"></div>
    </footer>
  </div>
</div>
"""


def render() -> None:
    # This page is a capture target: strip the rail and every Streamlit affordance
    # so the encoder sees only the stage.
    st.markdown("""
    <style>
    #icon-rail { display: none !important; }
    [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        margin-left: 0 !important;
    }
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stSidebar"], [data-testid="collapsedControl"],
    #MainMenu, footer { display: none !important; }
    section[data-testid="stMain"], section[data-testid="stMain"] > div,
    [data-testid="stMainBlockContainer"], div[class*="block-container"] {
        padding: 0 !important; margin: 0 !important; max-width: 100% !important;
    }
    body::after { display: none !important; }   /* app scanlines — stage draws its own */
    iframe { display: block !important; border: none !important; }
    html, body, .stApp { background: #000 !important; overflow: hidden !important; }

    /* stMain defaults to overflow-y:auto. Against 1920px of content it grows a
       scrollbar, and that scrollbar steals ~10px from every child — which
       lands the stage on a fractional scale and resamples the Blob's pixel
       art. Capture fidelity depends on this staying hidden. */
    section[data-testid="stMain"] { overflow: hidden !important; }
    </style>
    """, unsafe_allow_html=True)

    try:
        data = _load_chart_data()
    except Exception as e:
        st.error(f"DB connection failed: {e}")
        return

    components.html(_build_stream_html(data), height=_STAGE_H, scrolling=False)

    # Same trick as Home: a 0-height sibling iframe reaches into the parent
    # (same-origin) and sizes the stage iframe to the real viewport, so the
    # stage can letterbox itself against the true window rather than a
    # Streamlit-guessed height.
    components.html("""
    <script>
    (function() {
        function fit() {
            try {
                var p = window.parent, doc = p.document;
                var big = null, bh = 0;
                doc.querySelectorAll('iframe').forEach(function(f) {
                    if (f !== window.frameElement && f.offsetHeight > bh) { big = f; bh = f.offsetHeight; }
                });
                if (big) {
                    big.setAttribute('height', p.innerHeight);
                    big.style.height = p.innerHeight + 'px';
                    big.style.width  = '100%';
                }
            } catch(e) {}
        }
        fit();
        [100, 400, 900, 2000].forEach(function(ms) { setTimeout(fit, ms); });
        window.parent.addEventListener('resize', fit);
    })();
    </script>
    """, height=0, scrolling=False)
