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

    brand bar     864 x  96
    gap                  16
    content       864 x 752     <- TWO slots of 368, gap 16
    gap                  16
    host strip    864 x 272     <- portrait 288x272 + nameplate/dialogue
                       -----
                        1152  ✓

WHY TWO SLOTS. One panel at a time meant 3 of 4 were invisible at any moment,
while the host strip held 32% of the safe area for a dialogue box that is idle
unless a viewer just tipped. Two slots double the visible content for 96 stage px
taken off the host. Each cycles the same list independently and pickNext() keeps
them off the same panel; only one dissolves at a time, because two firing
together reads as the screen glitching rather than as pages turning.

HOST PORTRAIT SPEC — 288x360 is a 72x90 art cell at 4x, and the 4x is load
bearing. The strip is now 272 tall, so the portrait is CLIPPED at the collar
(measured: neck at art y62-64, collar begins y66) rather than scaled: only whole
multiples keep one art pixel on one logical pixel, and 3x lands at 67.5 logical —
off the grid the page is built on. The sprite element stays 72x90 so the
background-position maths in retronews.js is untouched; #rn-portrait clips it. Stage x 0.75 = broadcast device pixels, so 72*4*0.75 = 216 = 72*3: an
exact integer scale, no resampling. Any scale that is not a multiple of 4 filters
the sprite and the era read collapses. 4x also survives every resolution we might
use (1080x1920 -> 4x, 810x1440 -> 3x, 540x960 -> 2x). Sheet: 3 lid columns x 6
expression rows of 72x90 = 216x540 PNG, <=32 colours, no anti-aliasing.
Text is vector and EXEMPT from this rule — only sprite art must land on the grid.

Config namespace: strategy='stream:retronews'. Events stay on the shared bus.
"""
from __future__ import annotations

import base64
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
  <div id="stage" class="__GUIDES__">

    <div id="guide-top"></div>
    <div id="guide-bot"></div>

    <!-- Invisible double-tap target, top-left. Enters fullscreen so the stage
         frames at a true 9:16 — what a YouTube vertical live stream gives you —
         and switches the reserved-band guides on. Never paints anything: this
         corner is inside the broadcast frame. -->
    <div id="fs-hit"></div>

    <div id="safe">

      <!-- 1. BRAND BAR — 870 x 88 -->
      <div id="rn-brand">
        <div id="rn-logo">RETRONEWS</div>
        <div id="rn-slug">CHANNEL 4</div>
        <div id="rn-clock">--:--</div>
      </div>

      <!-- 2. CONTENT — 216 x 188 logical. TWO slots, each cycling the same
           panel set independently and never showing the same panel twice. Each
           slot owns its own dissolve overlay so one changing does not blank the
           other. Tile internals are CLASS-keyed, not id-keyed: the set appears
           twice, and duplicate ids would silently bind every lookup to the
           first slot. -->
      <div id="rn-content">

        <div id="rn-alert"></div>

        <div class="rn-slot" data-slot="a">
          <div class="rn-wipe"></div>
        <!-- LIVE: national conditions, Open-Meteo, no API key. -->
        <div class="rn-tile" data-tile="wx">
          <div class="rn-tile-head">
            <div class="rn-tile-title">NATIONAL CONDITIONS</div>
            <div class="rn-tile-sub rn-wx-sub">UPDATING</div>
          </div>
          <div class="rn-wx-grid"></div>
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

        <div class="rn-slot" data-slot="b">
          <div class="rn-wipe"></div>
        <!-- LIVE: national conditions, Open-Meteo, no API key. -->
        <div class="rn-tile" data-tile="wx">
          <div class="rn-tile-head">
            <div class="rn-tile-title">NATIONAL CONDITIONS</div>
            <div class="rn-tile-sub rn-wx-sub">UPDATING</div>
          </div>
          <div class="rn-wx-grid"></div>
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

      </div>

      <!-- 3. HOST STRIP — 870 x 384 -->
      <div id="rn-host">
        <div id="rn-portrait">
          <div id="rn-host-sprite"></div>
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


def _build_html(show_guides: bool, live: bool) -> str:
    payload = {
        "stage": {"w": _STAGE_W, "h": _STAGE_H},
        "ns": _CONFIG_NS,
        "supa": {"url": _SUPA_URL, "key": _SUPA_KEY},
        # ?live=1 marks THE render the encoder is capturing. The watchdog filters
        # its freeze check on detail->>live, because every open copy of this page
        # beats — a phone, a preview tab — and the newest beat of ANY of them
        # would keep the watchdog happy straight through a frozen broadcast.
        "live": live,
    }
    css = (_DASHBOARD / "retronews.css").read_text("utf-8")

    # The host sheet is INLINED as a data URI rather than served as a file. The
    # stage is delivered as one HTML blob inside a component iframe, which has no
    # route to a static asset — the same reason blob.js carries its sprite sheets
    # as base64. 9KB, so the cost is nothing.
    _bg = _DASHBOARD / "retronews_bg.png"
    bg_css = ""
    if _bg.exists():
        b64bg = base64.b64encode(_bg.read_bytes()).decode("ascii")
        bg_css = ("#stage{background-image:url(data:image/png;base64," + b64bg + ");"
                  "background-size:1080px 1920px;background-repeat:no-repeat;"
                  "image-rendering:pixelated;}")

    _host = _DASHBOARD / "retronews_host.png"
    host_css = ""
    if _host.exists():
        b64 = base64.b64encode(_host.read_bytes()).decode("ascii")
        host_css = ("#rn-host-sprite{background-image:url(data:image/png;base64,"
                    + b64 + ");}")
    js = (_DASHBOARD / "retronews.js").read_text("utf-8")
    # Guides are hidden by CSS default and revealed by a class, so the runtime
    # fullscreen preview can switch them on without re-rendering the page.
    stage_cls = "guides-on" if show_guides else ""

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
        + "<style>" + css + bg_css + host_css + "</style>"
        + _STAGE_HTML.replace("__GUIDES__", stage_cls)
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

    # ?live=1 is set by STREAM_URL on the broadcast host and by nothing else.
    live = st.query_params.get("live") == "1"

    components.html(_build_html(show_guides, live), height=_STAGE_H, scrolling=False)

    # Size the stage iframe to the REAL viewport.
    #
    # WITHOUT THIS THE PAGE IS BLACK ON A PHONE. components.html is given
    # height=1920, and #stage-wrap is position:fixed inset:0 INSIDE that iframe —
    # so the wrap is 1920 tall and centres the stage in it. On a 812px-tall phone
    # the stage's top lands ~626px down and everything above it is the wrap's
    # black background. Measured at a 375x812 viewport: iframe 375x1920, stage
    # rendered 375x667, sitting mostly below the fold.
    #
    # This is the Blob stream's sizer VERBATIM, because it is the one proven on a
    # real phone. Three details are load-bearing and an earlier hand-rolled
    # version got the first one wrong:
    #   * find the BIGGEST iframe, not one matched by title — the component
    #     iframe's title attribute is not something to rely on.
    #   * set the height ATTRIBUTE as well as style.height. Streamlit drives the
    #     attribute, so styling alone gets overridden.
    #   * listen to the PARENT's resize; the iframe's own event does not fire
    #     when it is resized from outside.
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
