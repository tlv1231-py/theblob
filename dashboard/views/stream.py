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
import re

import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import text

from config import risk_limits
from dashboard.db import get_session
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


_NAV_RE = re.compile(r"NAV \$([\d,]+\.?\d*)")


def _load_live_nav() -> list[dict]:
    """NAV series parsed from the engine's own UPDATE events.

    NOT nav_snapshots. That table is written CLIENT-SIDE by home_nav.js using
    whichever Alpaca wallet happens to be active in an open browser, and it has
    no account column — so two books interleave into one series. Measured
    2026-07-16: rows at ~$22.1k and ~$25.3k landing seconds apart, which renders
    as a sawtooth between two portfolios.

    The engine writes `▸ scan complete · NAV $22,162.23 · 9 open` every ~10s,
    server-side, from one book. Measured over 5h: 2281/2281 rows parsed, zero
    discontinuities >$500. That is the honest live number, and it agrees with
    Alpaca's reported portfolio value.

    Ordering note: this MUST order DESC then reverse. `ORDER BY ... ASC LIMIT n`
    truncates from the WRONG END — with 4,325 rows in a 2-day window and a
    limit of 3,000 the caller receives the OLDEST 3,000 and believes the newest
    of those is "now". That is exactly why the page froze at a stale figure for
    hours. The same asc+limit bug exists in home.py's seed and home_nav.js.
    """
    with get_session() as s:
        rows = s.execute(text("""
            SELECT message, recorded_at
            FROM pipeline_events
            WHERE event_type = 'UPDATE'
              AND recorded_at >= NOW() - INTERVAL '8 hours'
            ORDER BY recorded_at DESC
            LIMIT 3000
        """)).fetchall()

    pts = []
    for r in reversed(rows):          # DESC fetch, ASC series
        m = _NAV_RE.search(r.message or "")
        if m:
            pts.append({"t": r.recorded_at.isoformat() + "Z",
                        "v": float(m.group(1).replace(",", ""))})
    return pts


def _yt_overlay_default() -> bool:
    """Whether the temp YouTube filter starts visible.

    Read from strategy_params so Stream HQ's toggle is the source of truth and
    survives a reload. `?yt=0` / `?yt=1` still overrides for a single page load.
    """
    try:
        with get_session() as s:
            v = s.execute(text("""
                SELECT value FROM strategy_params
                WHERE strategy = 'stream' AND param = 'yt_overlay'
            """)).scalar()
        return v != "0"      # default ON while the layout is being designed
    except Exception:
        return True


def _latest_stream_event_id() -> int:
    """Newest stream_event id at render time — the page's starting high-water mark."""
    try:
        with get_session() as s:
            return int(s.execute(text(
                "SELECT COALESCE(MAX(id), 0) FROM stream_events")).scalar() or 0)
    except Exception:
        return 0


def _load_ticker_colors() -> dict:
    """Per-ticker colours, assigned and edited on the Command Center.

    Stored stripped ('CRV', not 'CRV/USD'), so callers must normalise. Only a
    few are assigned; anything unset falls back on the Stream page rather than
    being invented here — the Command Center owns this and the stream reads it.
    """
    try:
        with get_session() as s:
            rows = s.execute(text("SELECT ticker, color FROM ticker_colors")).fetchall()
        return {r.ticker: r.color for r in rows if r.color}
    except Exception:
        return {}


def _load_crypto_positions() -> list[dict]:
    """Live crypto holdings — server-written, unlike the equity book."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT symbol, qty, entry_price, stop_price, target_price,
                   entered_at, strategy
            FROM crypto_positions ORDER BY entered_at DESC
        """)).fetchall()
    return [{
        "sym": r.symbol,
        "qty": float(r.qty or 0),
        "entry_price": float(r.entry_price or 0),
        "stop_price": float(r.stop_price or 0),
        "target_price": float(r.target_price or 0),
        "entered_at": r.entered_at.isoformat() + "Z" if r.entered_at else None,
        "strategy": r.strategy or "crypto",
        "is_crypto": True,
    } for r in rows]


def _build_stream_html(data: dict, yt_overlay: bool = False,
                       live: bool = False) -> str:
    """Assemble the portrait stage: CSS, DOM skeleton, payload, renderers."""
    # Live NAV from the engine's UPDATE stream — see _load_live_nav for why
    # nav_snapshots is not trusted here. Falls back to the old series only if
    # the engine has emitted nothing at all.
    nav_pts = _load_live_nav() or data.get("nav_snap_pts") or []
    port = data.get("portfolio") or {}
    port_values = port.get("values") or []

    latest_nav = nav_pts[-1]["v"] if nav_pts else (
        port_values[-1] if port_values else _STARTING_CAPITAL
    )

    # Day P&L rebased off the session's own opening point in the same series,
    # so the number and its denominator always come from one book.
    day_pnl = float(data.get("day_pnl") or 0.0)
    if nav_pts:
        open_v = nav_pts[0]["v"]
        day_pnl = latest_nav - open_v
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
        "crypto":         _load_crypto_positions(),
        "ticker_colors":  _load_ticker_colors(),
        # High-water mark: the page shows only events created after it loaded.
        # Without this a fresh render would replay the entire backlog on boot.
        "last_event_id":  _latest_stream_event_id(),
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
    bg_js     = (_DASHBOARD / "stream_bg.js").read_text("utf-8")
    stream_js = (_DASHBOARD / "stream.js").read_text("utf-8")
    css       = (_DASHBOARD / "stream.css").read_text("utf-8")

    # TEMP design aid. Loads last so it sits above the stage. Always injected
    # but starts hidden unless enabled — it is toggled at runtime from Stream
    # HQ, which cannot reach this page any other way (different browsers).
    # Delete dashboard/yt_overlay.js and this block to remove it entirely.
    yt_js = (_DASHBOARD / "yt_overlay.js").read_text("utf-8")

    # Not an f-string: the CSS/JS brace density makes escaping a liability.
    # Data crosses into JS through one payload object instead.
    return (
        _FONTS
        + "<style>" + css + "</style>"
        + _STAGE_HTML
        + "<script>window._TND_STREAM = "
        + json.dumps(payload, default=str)
        + ";window._TND_YT_INITIAL = " + ("true" if yt_overlay else "false")
        + ";window._TND_LIVE = " + ("true" if live else "false")
        + ";</script>"
        + "<script>" + blob_js + "</script>"
        + "<script>" + bg_js + "</script>"
        + "<script>" + stream_js + "</script>"
        + "<script>" + yt_js + "</script>"
    )


# Laid out against YouTube's vertical-live safe zone. The top 380 and bottom
# 380 are reserved by YouTube chrome, and the right ~120 by the action rail —
# so EVERY informational element lives in #safe (870x1160 at 90,380) and
# nothing outside it carries meaning. The bands get ambient glow only: it costs
# nothing to lose, because YouTube is going to paint over it regardless.
_STAGE_HTML = """
<div id="stage-wrap">
  <div id="stage">
    <!-- Atmosphere. Fills the whole stage including the bands YouTube covers —
         everything here is decoration, so losing it to chrome costs nothing. -->
    <div id="ambient"></div>
    <canvas id="bgCanvas"></canvas>
    <div id="scanlines"></div>
    <div id="vignette"></div>

    <!-- ── SAFE BOX — 870 x 1160 @ (90, 380) ──────────────────────────── -->
    <!-- THREE THINGS: the board, him, the score. The status strip, the
         holdings header, the day P&L and the strategy P&L are all gone — none
         of them was what anyone tuned in for, and every one was taxing the
         three that are. Those figures live on the Command Center, where
         someone is reading rather than watching. -->
    <!-- blob <x> — the nameplate and the status line, reading as one sentence:
         "blob sold BTC for -$0.39". Above the board, which puts it at y12-112,
         i.e. inside the reserved band. -->
    <div id="s-title">
      <span class="ttl-name">blob</span>
      <span class="ttl-x idle" id="blob-status">is trading</span>
    </div>

    <!-- The board is OUTSIDE the safe box: it runs y120-600, above the safe
         box's own ceiling at y380. It floats over the stage; #safe pads its
         content down to clear it. -->
    <div id="s-pos">
      <div id="pos-list"></div>
    </div>

    <div id="safe">

      <div id="s-blob">
        <div class="blob-bloom" id="blob-bloom"></div>
        <canvas id="blobCanvas"></canvas>
        <div class="blob-mood" id="blob-mood">IDLE</div>
      </div>

      <!-- THE SCORE. -->
      <div id="s-nav">
        <div class="nav-label">PORTFOLIO VALUE</div>
        <div class="nav-big" id="hero-nav">$&mdash;</div>
      </div>

      <!-- Bottom of the stage, growing UPWARD — which is where a Gameboy text
           box actually lives. Idle it is a thin strip; a viewer event expands
           it. The name is its own element because the name is the point. -->
      <div id="s-events">
        <div class="ev-lcd" id="ev-lcd">
          <div class="ev-corners"></div>
          <div class="ev-idle" id="ev-idle">
            <span class="ev-icon" id="ev-icon">&#x25C8;</span>
            <span class="ev-head" id="ev-head"></span>
          </div>
          <div class="ev-body" id="ev-body">
            <div class="ev-nameline">
              <span class="ev-bigicon" id="ev-bigicon">&#x2665;</span>
              <span class="ev-name" id="ev-name"></span>
            </div>
            <div class="ev-act" id="ev-act"></div>
            <div class="ev-msg" id="ev-msg"></div>
          </div>
          <span class="ev-more" id="ev-more">&#x25BC;</span>
          <span class="ev-badge" id="ev-badge"></span>
        </div>
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

    # TEMP: YouTube safe-zone overlay. Stream HQ's toggle is the source of
    # truth; ?yt=0 / ?yt=1 overrides it for a single page load. Must be off for
    # a real capture — HQ shows the state so it can't be forgotten silently.
    _qp = st.query_params.get("yt")
    _yt = (_qp != "0") if _qp is not None else _yt_overlay_default()

    # ?live=1 marks THE BROADCAST — the render the encoder is capturing.
    # It is the one page that must never be muted, so it ignores HQ's mute
    # toggle entirely. Every other render (an operator's window, a spare tab)
    # respects it. Without this split, muting to stop the noise on your own
    # desk would silence the actual YouTube stream and nothing would say so.
    _live = st.query_params.get("live") == "1"

    components.html(_build_stream_html(data, yt_overlay=_yt, live=_live),
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
