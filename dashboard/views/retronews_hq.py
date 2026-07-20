"""RetroNews HQ — the control room for the RetroNews channel.

Sibling of Stream HQ, but it writes to a DIFFERENT config namespace:

    strategy = 'stream:retronews'      (this page)
    strategy = 'stream'                (the Blob stream)

That split is the whole reason two apps can share one database without
corrupting each other. strategy_params' primary key is (strategy, param), so a
namespace is FREE — no migration, no new column. See CLAUDE.md "Stream
Infrastructure Is Multi-App": CONFIG IS NAMESPACED PER APP, EVENTS ARE SHARED.

Nothing here talks to the stream directly. Every control writes one row, and the
page polls it (~3s). Same mechanism as the ON AIR button, the BG fader and the
potion table — proven five times over, and it is why HQ can run in one browser
while the broadcast runs on a VM in another country.
"""
from __future__ import annotations

import json
from datetime import datetime

import streamlit as st
from sqlalchemy import text

from dashboard.db import get_session

_NS = "stream:retronews"

# Tile ids must match data-tile in retronews.py's markup.
_TILES = {
    "wx":         "National Conditions (LIVE — Open-Meteo)",
    "donors":     "Top Contributors (placeholder)",
    "market":     "Market Watch (placeholder)",
    "nowplaying": "Now Playing (placeholder)",
}

_DEFAULTS = {
    "rotation": json.dumps(["wx", "donors", "market", "nowplaying"]),
    "dwell_s":  "15",
    "host_name": "YOUR HOST",
    "host_say": "",
    "alert": "",
}


def _get() -> dict:
    out = dict(_DEFAULTS)
    try:
        with get_session() as s:
            rows = s.execute(text(
                "SELECT param, value FROM strategy_params WHERE strategy = :ns"
            ), {"ns": _NS}).fetchall()
        for r in rows:
            if r.value is not None:
                out[r.param] = r.value
    except Exception:
        pass
    return out


def _set(param: str, value: str, label: str = "RetroNews") -> None:
    with get_session() as s:
        s.execute(text("""
            INSERT INTO strategy_params (strategy, param, value, unit, label, updated_at)
            VALUES (:ns, :p, :v, '', :l, :now)
            ON CONFLICT (strategy, param)
            DO UPDATE SET value = :v, updated_at = :now
        """), {"ns": _NS, "p": param, "v": value, "l": label, "now": datetime.utcnow()})
        s.commit()


def render() -> None:
    st.markdown("## ◐ RETRONEWS HQ")
    st.caption(
        "Control room for the RetroNews channel. Everything here writes to "
        f"`strategy='{_NS}'` — a separate namespace from the Blob stream, so the "
        "two apps cannot overwrite each other's settings. The page polls every "
        "~3s, so edits are live in a few seconds with no restart."
    )

    cfg = _get()

    # ── YT FILTER ─────────────────────────────────────────────────────────
    # In the header, not behind a tab, for the same reason the Blob stream's is:
    # leaving it on during a real capture puts fake YouTube chrome on the actual
    # broadcast, so it must be visible at a glance rather than discoverable.
    yt_on = cfg.get("yt_overlay", "0") == "1"
    c1, c2 = st.columns([1, 3])
    if c1.button("YT FILTER: " + ("ON" if yt_on else "OFF"),
                 use_container_width=True,
                 type="primary" if yt_on else "secondary",
                 help="Overlays YouTube's vertical-LIVE chrome and every published "
                      "reading of the safe area on the RetroNews page. Applies live "
                      "(~3s), no reload. MUST be off for a real capture."):
        _set("yt_overlay", "0" if yt_on else "1", "YouTube measuring overlay")
        st.rerun()
    if yt_on:
        c2.warning("Measuring overlay is ON — it renders on the broadcast page. "
                   "Turn it off before going to air.", icon="⚠️")
    else:
        c2.caption("Draws the live chrome plus all three published safe-area "
                   "readings, which disagree by 260px on the top margin. The "
                   "solid red box is their union — outside it is safe under every "
                   "reading. Green means our box clears it; amber means it does not.")

    # ── HOST ON AIR ───────────────────────────────────────────────────────
    # Header, beside the YT filter: it changes what the broadcast looks like
    # right now, so it should not be two clicks deep in a tab.
    host_on = cfg.get("host_visible", "1") != "0"
    h1, h2 = st.columns([1, 3])
    if h1.button("HOST: " + ("ON" if host_on else "OFF"),
                 use_container_width=True,
                 type="primary" if host_on else "secondary",
                 help="Show or hide the host strip. Hidden, the content panel "
                      "takes the space (195 -> 291 logical) and REVEALS MORE ROWS "
                      "at the same size — 10 cities become 15. Nothing scales. "
                      "Applies live (~3s), no reload."):
        _set("host_visible", "0" if host_on else "1", "Host strip on screen")
        st.rerun()
    h2.caption("Hiding the host gives the content panel his 96 logical. NOTHING "
               "SCALES — the type and row height are identical either way, the "
               "board just reveals more of itself (10 weather rows become 15). "
               "Hard cut, never a fade: CSS transitions are inert inside the "
               "stream page's iframe."
               if host_on else
               "Host is OFF — the panel is full height, showing 15 rows.")

    tab_sched, tab_host, tab_alert, tab_live = st.tabs(
        ["Schedule", "Host", "Breaking", "Go Live"])

    # ── Schedule ──────────────────────────────────────────────────────────
    with tab_sched:
        st.markdown("#### Programming schedule")
        st.caption("The rotation IS the aesthetic — 'Local on the 8s'. Tiles "
                   "change by HARD CUT, never a fade: that is both authentic to "
                   "90s broadcast and the only motion a 24fps software "
                   "compositor does cleanly.")

        try:
            current = json.loads(cfg.get("rotation") or "[]")
        except ValueError:
            current = []
        if not current:
            current = list(_TILES.keys())

        picked = st.multiselect(
            "Tiles in rotation (order matters)",
            options=list(_TILES.keys()),
            default=[t for t in current if t in _TILES],
            format_func=lambda k: _TILES[k],
        )

        dwell = st.slider("Seconds per tile", 4, 120,
                          int(cfg.get("dwell_s") or 15), step=1)

        if st.button("SAVE SCHEDULE", type="primary", use_container_width=True):
            if not picked:
                st.error("At least one tile must be in rotation.")
            else:
                _set("rotation", json.dumps(picked))
                _set("dwell_s", str(dwell))
                st.success(f"Saved — {len(picked)} tiles, {dwell}s each "
                           f"({len(picked) * dwell}s per full cycle).")

    # ── Host ──────────────────────────────────────────────────────────────
    with tab_host:
        st.markdown("#### The host")
        st.caption("The portrait panel is reserved at 288×360 — a 72×90 art cell "
                   "at 4×. The 4× is load-bearing: stage × 0.75 = broadcast "
                   "pixels, so 72·4·0.75 = 216 = 72·3, an exact integer scale. "
                   "Any other multiple resamples the sprite.")

        name = st.text_input("Nameplate", value=cfg.get("host_name") or "YOUR HOST",
                             max_chars=28)
        # 63 IS THE BOX'S MEASURED CAPACITY, not a round number — binary search
        # on realistically-wrapping sentences at the real size (14 logical VT323
        # over a 124x64 logical content area). Enforcing it HERE, where the copy
        # is written, is the only place the limit is visible: past it the text
        # simply clips on air with nothing to say why.
        # Sentence case is fine and preferred — the dialogue face has true
        # lowercase, which the signage face effectively does not.
        say = st.text_area("What he's saying", value=cfg.get("host_say") or "",
                           max_chars=63, height=100,
                           help="Cleared automatically when a viewer event "
                                "takes over the dialogue box for ~12s.")
        if st.button("SAVE HOST", type="primary", use_container_width=True):
            _set("host_name", name.strip().upper())
            _set("host_say", say.strip())
            st.success("Saved — live within ~3s.")

    # ── Breaking / alert bar ──────────────────────────────────────────────
    with tab_alert:
        st.markdown("#### Breaking bar")
        st.caption("A red blinking bar across the top of the content area. "
                   "Blink is a class toggle on an interval — no CSS transition, "
                   "because animations are inert in the stream's iframe. "
                   "Leave empty to hide it.")
        alert = st.text_input("Breaking text (empty = off)",
                              value=cfg.get("alert") or "", max_chars=48)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("SET BAR", type="primary", use_container_width=True):
                _set("alert", alert.strip().upper())
                st.success("On air within ~3s." if alert.strip() else "Bar hidden.")
        with c2:
            if st.button("CLEAR BAR", use_container_width=True):
                _set("alert", "")
                st.success("Cleared.")

    # ── Go live ───────────────────────────────────────────────────────────
    with tab_live:
        st.markdown("#### Putting RetroNews on air")
        st.caption("The stream host captures a URL — nothing in it is "
                   "Blob-specific. Switching channels is one env var plus a "
                   "Chromium restart (~90s of black; it is 'changing the "
                   "channel', not a crossfade).")
        st.code(
            "# on the stream host\n"
            "sudo nano /opt/blob-stream/.env\n"
            "#   STREAM_URL=https://<app>.streamlit.app/?page=RetroNews&yt=0&live=1\n"
            "sudo systemctl restart blob-chromium",
            language="bash",
        )
        st.info(
            "**One stream at a time — a hardware fact, not a policy.** A single "
            "810×1440 render already pegs the VM's software compositor at ~98% "
            "of one core, and that cost is per-pixel, not per-animation. Two "
            "concurrent broadcasts need a second VM.",
            icon="⚠️",
        )
        st.markdown(
            "**Donations already work here.** `streamlabs.py` and `chat.py` write "
            "to the shared `stream_events` bus and have no idea which page is "
            "rendering, so tips fire on whichever app is live — same account, "
            "same token, no changes."
        )
