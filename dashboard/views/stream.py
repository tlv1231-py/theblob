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


def _build_stream_html(data: dict, yt_overlay: bool = False) -> str:
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
            # Drives the tile meter's left wall and the stop-breach alarm.
            "stop_loss": risk_limits.DEFAULT_STOP_LOSS_PCT,
        },
        "supa": {"url": _SUPA_URL, "key": _SUPA_KEY},
        "stage": {"w": _STAGE_W, "h": _STAGE_H},
    }

    blob_js   = (_DASHBOARD / "blob.js").read_text("utf-8")
    stream_js = (_DASHBOARD / "stream.js").read_text("utf-8")
    css       = (_DASHBOARD / "stream.css").read_text("utf-8")

    # TEMP design aid. Loads last so it sits above the stage. Delete
    # dashboard/yt_overlay.js and this block to remove it entirely.
    yt_js = (_DASHBOARD / "yt_overlay.js").read_text("utf-8") if yt_overlay else ""

    # Not an f-string: the CSS/JS brace density makes escaping a liability.
    # Data crosses into JS through one payload object instead.
    return (
        _FONTS
        + "<style>" + css + "</style>"
        + _STAGE_HTML
        + "<script>window._TND_STREAM = "
        + json.dumps(payload, default=str)
        + ";</script>"
        + "<script>" + blob_js + "</script>"
        + "<script>" + stream_js + "</script>"
        + ("<script>" + yt_js + "</script>" if yt_js else "")
    )


# Laid out against YouTube's vertical-live safe zone. The top 380 and bottom
# 380 are reserved by YouTube chrome, and the right ~120 by the action rail —
# so EVERY informational element lives in #safe (870x1160 at 90,380) and
# nothing outside it carries meaning. The bands get ambient glow only: it costs
# nothing to lose, because YouTube is going to paint over it regardless.
_STAGE_HTML = """
<div id="stage-wrap">
  <div id="stage">
    <div id="ambient"></div>
    <div id="scanlines"></div>
    <div id="vignette"></div>

    <!-- ── SAFE BOX — 870 x 1160 @ (90, 380) ──────────────────────────── -->
    <div id="safe">

      <div id="s-status">
        <span class="st-live"><i class="dot"></i>LIVE</span>
        <span class="st-chip" id="chip-status">PAPER</span>
        <span class="st-chip st-dim" id="chip-day">DAY &mdash;/20</span>
        <span class="st-spacer"></span>
        <span class="st-sess" id="hd-sess">&mdash;</span>
        <span class="st-clock" id="hd-clock">--:--:--</span>
      </div>

      <div id="s-blob">
        <div class="blob-bloom" id="blob-bloom"></div>
        <canvas id="blobCanvas"></canvas>
        <div class="blob-mood" id="blob-mood">IDLE</div>
      </div>

      <div id="s-nav">
        <div class="nav-label">PORTFOLIO VALUE</div>
        <div class="nav-big" id="hero-nav">$&mdash;</div>
        <div class="nav-day" id="hero-day">&mdash;</div>
        <div class="nav-sub" id="chip-total">&mdash;</div>
      </div>

      <div id="s-chart">
        <canvas id="navCanvas"></canvas>
        <div class="chart-meta" id="chart-meta">&mdash;</div>
      </div>

      <div id="s-pos">
        <div class="pos-hdr">
          <span class="pos-name">HOLDINGS</span>
          <span class="pos-meta" id="pos-meta">&mdash;</span>
        </div>
        <div id="pos-list"></div>
      </div>

    </div>
  </div>
</div>
"""

# Arcade faces, same source the Command Center tiles use. Loaded inside the
# component iframe because it has its own document. If these silently fall back
# to monospace the tiles stop reading as 8-bit at all — that is the whole look.
_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P'
    '&family=VT323&display=swap" rel="stylesheet">'
)


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

    # TEMP: YouTube safe-zone overlay, on by default while the page is being
    # laid out. ?yt=0 to see the stage clean. Must be off for a real capture.
    _yt = st.query_params.get("yt", "1") != "0"

    components.html(_build_stream_html(data, yt_overlay=_yt),
                    height=_STAGE_H, scrolling=False)

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
