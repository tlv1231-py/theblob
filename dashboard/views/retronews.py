"""RetroNews — a fake 90s cable channel, vertical (1080x1920).

The second stream app. Reference: WeatherSTAR 4000 (https://weather.com/retro/)
crossed with late-night infomercial chrome. It runs on the SAME host as the Blob
stream — the encoder captures a URL and does not care what is on it — so going
live is a STREAM_URL change, not new infrastructure.

WHY THIS ERA (it is not just taste — see CLAUDE.md "RetroNews — the era rule"):
90s cable graphics are the aesthetic whose constraints match ours exactly.
Cartridge consoles were the INVERSE of this rig: 60Hz refresh with starved
colour. We have lavish colour and a slow, stepped ~24fps refresh — which is
precisely early-90s broadcast CG. Its defining habits are also our optimal
strategy:
  * pages CUT on a timer (no tweening — we cannot tween smoothly anyway)
  * ambient life is palette-based (blink, colour cycle) — costs zero frames
  * hard offset shadows, flat saturated colour — no blur to composite

LAYOUT — arithmetic, not vibes. Everything lives in the 870x1160 safe box at
(90,380); the top and bottom 380 are covered by YouTube's own chrome on a live
vertical stream. The Blob stream's known cost (8 of its 14 tiles sitting behind
that chrome) is deliberately not repeated here.

    brand bar     870 x  88
    gap                  12
    content       870 x 664     <- the rotating tiles
    gap                  12
    host strip    870 x 384     <- portrait 288x360 + nameplate/dialogue
                       -----
                        1160  ✓

HOST PORTRAIT SPEC — 288x360 is a 72x90 art cell at 4x, and the 4x is load
bearing. Stage x 0.75 = broadcast device pixels, so 72*4*0.75 = 216 = 72*3: an
exact integer scale, no resampling. Any scale that is not a multiple of 4 filters
the sprite and the era read collapses. 4x also survives every resolution we might
use (1080x1920 -> 4x, 810x1440 -> 3x, 540x960 -> 2x). Sheet: 3 lid columns x 6
expression rows of 72x90 = 216x540 PNG, <=32 colours, no anti-aliasing.
Text is vector and EXEMPT from this rule — only sprite art must land on the grid.

Config namespace: strategy='stream:retronews'. Events stay on the shared bus.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_DASHBOARD = Path(__file__).resolve().parent.parent

_STAGE_W = 1080
_STAGE_H = 1920
_CONFIG_NS = "stream:retronews"

_SUPA_URL = os.environ.get("SUPA_URL", "https://seeevuklabvhkawawtxn.supabase.co")
_SUPA_KEY = os.environ.get("SUPA_KEY", "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY")


# Tiles are all present in the DOM and swapped by CUT (display none/block).
# Building them as siblings rather than re-rendering means a cut is free and
# cannot strand a half-finished animation — the same reason the Blob stream's
# lane arbiter never tears down a beat mid-flight.
_STAGE_HTML = """
<div id="stage-wrap">
  <div id="stage">

    <div id="guide-top"></div>
    <div id="guide-bot"></div>

    <div id="safe">

      <!-- 1. BRAND BAR — 870 x 88 -->
      <div id="rn-brand">
        <div id="rn-logo">RETRONEWS</div>
        <div id="rn-slug">CHANNEL 4</div>
        <div id="rn-clock">--:--</div>
      </div>

      <!-- 2. CONTENT — 870 x 664. One tile visible at a time. -->
      <div id="rn-content">

        <div id="rn-alert"></div>

        <!-- LIVE: national conditions, Open-Meteo, no API key. -->
        <div class="rn-tile on" data-tile="wx">
          <div class="rn-tile-head">
            <div class="rn-tile-title">NATIONAL CONDITIONS</div>
            <div class="rn-tile-sub" id="rn-wx-sub">UPDATING</div>
          </div>
          <div id="rn-wx-grid"></div>
        </div>

        <!-- PLACEHOLDER: top donors, infomercial chrome. -->
        <div class="rn-tile" data-tile="donors">
          <div class="rn-tile-head">
            <div class="rn-tile-title">TOP CONTRIBUTORS</div>
            <div class="rn-tile-sub">THIS BROADCAST</div>
          </div>
          <div class="rn-placeholder">
            <div class="rn-ph-label">PANEL RESERVED</div>
            <div class="rn-ph-note">Top donors, styled as a late-night
              infomercial order screen. Data already exists on the shared
              stream_events bus.</div>
          </div>
        </div>

        <!-- PLACEHOLDER: market crawl. -->
        <div class="rn-tile" data-tile="market">
          <div class="rn-tile-head">
            <div class="rn-tile-title">MARKET WATCH</div>
            <div class="rn-tile-sub">DELAYED</div>
          </div>
          <div class="rn-placeholder">
            <div class="rn-ph-label">PANEL RESERVED</div>
            <div class="rn-ph-note">CNBC-style ticker. Live market data already
              lives in this database — no new source required.</div>
          </div>
        </div>

        <!-- PLACEHOLDER: now playing (the host's music bed). -->
        <div class="rn-tile" data-tile="nowplaying">
          <div class="rn-tile-head">
            <div class="rn-tile-title">NOW PLAYING</div>
            <div class="rn-tile-sub">SMOOTH JAZZ</div>
          </div>
          <div class="rn-placeholder">
            <div class="rn-ph-label">PANEL RESERVED</div>
            <div class="rn-ph-note">The music bed the stream host already mixes
              into the broadcast (normalised to -16 LUFS on the VM).</div>
          </div>
        </div>

      </div>

      <!-- 3. HOST STRIP — 870 x 384 -->
      <div id="rn-host">
        <div id="rn-portrait">
          <div class="ph">
            <b>HOST</b>
            288 &times; 360<br>
            72&times;90 art @ 4&times;<br>
            3 lids &times; 6 moods
          </div>
        </div>
        <div id="rn-host-right">
          <div id="rn-nameplate">YOUR HOST</div>
          <div id="rn-say"></div>
        </div>
      </div>

    </div>
  </div>
</div>
"""


def _build_html(show_guides: bool) -> str:
    payload = {
        "stage": {"w": _STAGE_W, "h": _STAGE_H},
        "ns": _CONFIG_NS,
        "supa": {"url": _SUPA_URL, "key": _SUPA_KEY},
    }
    css = (_DASHBOARD / "retronews.css").read_text("utf-8")
    js = (_DASHBOARD / "retronews.js").read_text("utf-8")
    guide_css = "" if show_guides else "#guide-top,#guide-bot{display:none!important;}"

    # Press Start 2P — an 8x8 bitmap face. Correct HERE, and only here: the
    # conceit is a Game Boy rendering a cable channel, so the machine's own font
    # is the joke. For a straight 90s-broadcast homage this would be the wrong
    # era and a bold sans would be right.
    fonts = (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P'
        '&display=swap" rel="stylesheet">'
    )

    # Not an f-string: CSS/JS brace density makes escaping a liability.
    return (
        fonts
        + "<style>" + css + guide_css + "</style>"
        + _STAGE_HTML
        + "<script>window._TND_RETRONEWS = " + json.dumps(payload, default=str) + ";</script>"
        + "<script>" + js + "</script>"
    )


def render() -> None:
    # A capture target: strip every Streamlit affordance so the encoder sees
    # only the stage. The overflow guard is not cosmetic — against 1920px of
    # content stMain grows a scrollbar, the scrollbar steals ~10px from every
    # child, and the stage lands on a fractional scale.
    st.markdown("""
    <style>
    #icon-rail { display: none !important; }
    [data-testid="stAppViewContainer"], [data-testid="stMain"] { margin-left: 0 !important; }
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stSidebar"], [data-testid="collapsedControl"],
    #MainMenu, footer { display: none !important; }
    section[data-testid="stMain"], section[data-testid="stMain"] > div,
    [data-testid="stMainBlockContainer"], div[class*="block-container"] {
        padding: 0 !important; margin: 0 !important; max-width: 100% !important;
    }
    body::after { display: none !important; }
    iframe { display: block !important; border: none !important; }
    html, body, .stApp { background: #000 !important; overflow: hidden !important; }
    section[data-testid="stMain"] { overflow: hidden !important; }
    </style>
    """, unsafe_allow_html=True)

    # ?guides=1 draws YouTube's reserved bands. MUST be off for a real capture.
    show_guides = st.query_params.get("guides") == "1"

    components.html(_build_html(show_guides), height=_STAGE_H, scrolling=False)

    # Size the stage iframe to the REAL viewport — Streamlit guesses a height,
    # and letterboxing against a guess puts the stage on a fractional scale.
    components.html("""
    <script>
    (function () {
      function size() {
        try {
          var d = window.parent.document;
          var frames = d.querySelectorAll('iframe[title="streamlit_component_v1"]');
          for (var i = 0; i < frames.length; i++) {
            var f = frames[i];
            if (f.height === '0' || f.clientHeight === 0) continue;
            f.style.height = window.parent.innerHeight + 'px';
            f.style.width = '100%';
          }
        } catch (e) {}
      }
      size();
      setInterval(size, 1000);
      window.addEventListener('resize', size);
    })();
    </script>
    """, height=0, scrolling=False)
