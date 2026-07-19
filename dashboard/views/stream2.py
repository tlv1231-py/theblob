"""Stream 2 — SCAFFOLD for a second vertical stream app (1080x1920).

This is not a feature, it is a starting point. The Blob stream (`stream.py`)
arrived at a specific stage geometry, a specific safe zone and one hard runtime
constraint the expensive way; this page encodes all of it so a new stream app
does not have to rediscover any of them.

WHAT IT ALREADY GETS RIGHT — do not "simplify" these away:
  * 1080x1920 letterboxed stage. The stage is always exactly that in its own
    coordinate space and only --s scales it, so a true 1080x1920 capture
    resolves to scale 1 and nothing is resampled.
  * The YouTube vertical safe zone: 870x1160 at (90, 380). The top and bottom
    380 are covered by YouTube's own chrome on a LIVE stream (the chat input
    lives down there permanently). Anything outside #safe will be hidden.
  * setInterval for everything that moves. rAF and CSS animations are INERT in
    the component iframe — they fail silently, which is the worst way to fail.
  * A visible heartbeat, because ffmpeg encodes a FROZEN page at a perfect
    24fps and every health metric reads green while the picture is dead.

HOW IT GOES LIVE
The stream host captures a URL; the page is chosen by STREAM_URL on the VM:
    STREAM_URL=https://<app>.streamlit.app/?page=Stream2&yt=0&live=1
Nothing in the host is Blob-specific. See CLAUDE.md "Stream Infrastructure Is
Multi-App" for the two rules that keep two apps from corrupting each other:
CONFIG IS NAMESPACED PER APP, EVENTS ARE SHARED.

NOTE ON NAMING: "Stream 2" is a placeholder. Rename the page, this file and the
`stream:app2` config namespace together when the app knows what it is.
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

# Config namespace for THIS app. strategy_params' PK is (strategy, param), so
# giving each stream app its own `strategy` value is a free, migration-less
# namespace — and it is the thing that stops two apps fighting over settings
# like bg_enabled / potions / ticker_colors. Decide it before the app ships.
_CONFIG_NS = "stream:app2"

# Same public Supabase pair the Blob stream uses: the page polls the DB straight
# from the iframe, because Streamlit reruns the whole script per interaction and
# a rerun-per-frame would mean a DB round trip per frame.
_SUPA_URL = os.environ.get("SUPA_URL", "https://seeevuklabvhkawawtxn.supabase.co")
_SUPA_KEY = os.environ.get("SUPA_KEY", "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY")


# The reserved-band guides are build-time aids. They are inside the broadcast
# frame, so they must be off for a real capture — ?guides=1 turns them on.
_STAGE_HTML = """
<div id="stage-wrap">
  <div id="stage">

    <!-- Build-time guides for YouTube's reserved bands. Off by default. -->
    <div id="guide-top"></div>
    <div id="guide-bot"></div>

    <!-- EVERYTHING THAT MUST BE SEEN LIVES IN HERE (870x1160 at 90,380). -->
    <div id="safe">
      <div id="s2-title">STREAM 2</div>
      <div id="s2-sub">scaffold — replace me</div>
      <div id="s2-event"></div>

      <div id="s2-body">
        <div id="s2-beat">00</div>
      </div>

      <div id="s2-foot">—</div>
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
    css = (_DASHBOARD / "stream2.css").read_text("utf-8")
    js = (_DASHBOARD / "stream2.js").read_text("utf-8")

    # Read fresh every render (no cache decorator) so editing the .css/.js and
    # reloading the page is the whole dev loop — same as the Blob stream.
    guide_css = "" if show_guides else "#guide-top,#guide-bot{display:none!important;}"

    # Not an f-string: the CSS/JS brace density makes escaping a liability.
    # Data crosses into JS through one payload object instead.
    return (
        "<style>" + css + guide_css + "</style>"
        + _STAGE_HTML
        + "<script>window._TND_STREAM2 = " + json.dumps(payload, default=str) + ";</script>"
        + "<script>" + js + "</script>"
    )


def render() -> None:
    # This page is a CAPTURE TARGET: strip the rail and every Streamlit
    # affordance so the encoder sees only the stage. Identical treatment to
    # stream.py — including the overflow guard, which is not cosmetic: against
    # 1920px of content stMain grows a scrollbar, the scrollbar steals ~10px
    # from every child, and the stage lands on a fractional scale.
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

    # ?guides=1 draws YouTube's reserved bands while you build. MUST be off for
    # a real capture — they are inside the broadcast frame.
    show_guides = st.query_params.get("guides") == "1"

    components.html(_build_html(show_guides), height=_STAGE_H, scrolling=False)

    # Size the stage iframe to the REAL viewport. Streamlit guesses a height,
    # and letterboxing against a guess puts the stage on a fractional scale.
    # A 0-height sibling iframe reaches into the parent (same-origin) and fixes
    # it — same trick stream.py and home use.
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
      setInterval(size, 1000);          // setInterval — rAF is inert here
      window.addEventListener('resize', size);
    })();
    </script>
    """, height=0, scrolling=False)
