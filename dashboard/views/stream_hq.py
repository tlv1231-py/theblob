"""Stream HQ — operator console for the 24/7 YouTube stream.

Three jobs:

  1. HEALTH. Report the streaming stack honestly, including the parts this app
     cannot see. A green light that isn't measuring anything is worse than no
     light: it reads as "fine" while the encoder pushes a frozen screenshot to
     YouTube for six hours. Anything not actually observed says so.

  2. EVENT BUS. Everything the Blob reacts to that didn't come from the trading
     engine lands in `stream_events` first, visible here before it goes out.
     Hold, count down, release, or cancel.

  3. SIMULATION. Fire any event the Blob can react to — a $50 donation, a raid,
     a losing exit — without waiting for one to happen. This is the only way to
     rehearse the stream.

Why a table and not postMessage: HQ and the Stream page never share a browser.
The stream renders in a headless Chromium on the streaming host; HQ runs
wherever the operator is. Supabase is the only thing both can reach.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import text

from dashboard.db import get_session

# How stale a heartbeat may be before the component is considered dead.
# Generous relative to each writer's cadence so a single missed beat is not an
# outage — but tight enough that a frozen render is caught in ~1 minute.
_STALE = {
    "stream_page": 60,    # page beats every ~15s
    "encoder":     90,    # agent would beat every ~30s
    "host":        90,
    "engine":     120,    # pipeline UPDATE lands every ~10s
}


# ── Health ────────────────────────────────────────────────────────────────────

def _check_db() -> dict:
    try:
        with get_session() as s:
            s.execute(text("SELECT 1"))
        return {"status": "ok", "detail": "Supabase reachable"}
    except Exception as e:
        return {"status": "down", "detail": str(e)[:80]}


def _check_engine() -> dict:
    """Is the autotrader actually running? The stream is pointless without it."""
    try:
        with get_session() as s:
            r = s.execute(text("""
                SELECT recorded_at, EXTRACT(EPOCH FROM (NOW() - recorded_at)) AS age
                FROM pipeline_events ORDER BY recorded_at DESC LIMIT 1
            """)).fetchone()
        if not r:
            return {"status": "down", "detail": "no pipeline events ever"}
        age = int(r.age)
        if age > _STALE["engine"]:
            return {"status": "down", "detail": f"last event {age}s ago — engine stopped"}
        return {"status": "ok", "detail": f"last event {age}s ago"}
    except Exception as e:
        return {"status": "unknown", "detail": str(e)[:80]}


def _check_heartbeat(component: str) -> dict:
    """Read a component's own heartbeat. No row = it has never reported."""
    try:
        with get_session() as s:
            r = s.execute(text("""
                SELECT status, detail, recorded_at,
                       EXTRACT(EPOCH FROM (NOW() - recorded_at)) AS age
                FROM stream_health WHERE component = :c
                ORDER BY recorded_at DESC LIMIT 1
            """), {"c": component}).fetchone()
        if not r:
            return {"status": "absent", "detail": "no agent has ever reported"}
        age = int(r.age)
        if age > _STALE.get(component, 90):
            return {"status": "down", "detail": f"last beat {age}s ago"}
        d = r.detail if isinstance(r.detail, dict) else {}
        extra = "  ·  ".join(f"{k}={v}" for k, v in list(d.items())[:3])
        return {"status": r.status, "detail": f"{age}s ago" + (f"  ·  {extra}" if extra else "")}
    except Exception as e:
        return {"status": "unknown", "detail": str(e)[:80]}


_DOT = {"ok": "🟢", "degraded": "🟡", "down": "🔴", "absent": "⚫", "unknown": "⚪"}


def _render_health() -> None:
    st.markdown("### Pipeline health")

    checks = [
        ("Database",      _check_db(),                    "Supabase — the channel everything rides on"),
        ("Trading engine", _check_engine(),               "pipeline_events still flowing"),
        ("Stream page",   _check_heartbeat("stream_page"), "the render itself — catches a frozen page"),
        ("Encoder",       _check_heartbeat("encoder"),     "ffmpeg speed / fps — needs host agent"),
        ("Host",          _check_heartbeat("host"),        "Oracle VM CPU / memory — needs host agent"),
    ]

    for name, res, why in checks:
        c1, c2, c3 = st.columns([2, 3, 5])
        c1.markdown(f"{_DOT.get(res['status'], '⚪')} **{name}**")
        c2.markdown(f"`{res['status'].upper()}`")
        c3.caption(f"{res['detail']}  —  {why}")

    absent = [n for n, r, _ in checks if r["status"] == "absent"]
    if absent:
        st.warning(
            f"**{', '.join(absent)} report ⚫ ABSENT — nothing is measuring them.** "
            "These live on the streaming host and cannot be observed from this app. "
            "They stay absent until an agent on the VM writes to `stream_health`. "
            "Treat them as unknown, not healthy."
        )


# ── Build plan ────────────────────────────────────────────────────────────────

_PLAN = [
    ("1. Oracle Cloud Always Free ARM VM",
     "4 vCPU / 24GB, no 6h cap, 24/7 permitted.",
     "Capacity for Always Free ARM is frequently exhausted in popular regions — "
     "this is the single most likely step to simply not be available. Verify you can "
     "actually launch before building on it."),
    ("2. ffmpeg → YouTube RTMP, test pattern",
     "Prove the RTMP path before any browser exists.",
     "Do this second, exactly as planned. If RTMP fails you want to know before "
     "Xvfb and Chromium are in the picture confusing the diagnosis."),
    ("3. Xvfb virtual display :99 @ 1080x1920",
     "Framebuffer in RAM. No monitor.",
     "Must be exactly 1080x1920 or the stage letterboxes and the Blob's pixel art "
     "resamples — the scale has to resolve to 1."),
    ("4. Chromium kiosk → Stream page",
     "Renders into the framebuffer.",
     "Needs --autoplay-policy=no-user-gesture-required or the arcade sounds never "
     "fire: AudioContext stays suspended with no one to click."),
    ("5. Music bed",
     "Looping licensed playlist mixed as the audio track.",
     "Copyright is a strike risk, not a mute risk. Licensed/royalty-free only."),
    ("6. systemd + retry loop",
     "Restart on disconnect and on reboot.",
     "Restarting ffmpeg is not enough — a frozen Chromium survives an ffmpeg "
     "restart and keeps feeding a dead frame."),
    ("7. Watchdog",
     "Periodic Chromium reload; heartbeat to stream_health.",
     "This is the one that actually matters. See below."),
]


def _render_plan() -> None:
    st.markdown("### Build order")
    st.caption("Sequential — each step assumes the previous one is proven.")
    for title, what, risk in _PLAN:
        with st.expander(title, expanded=False):
            st.markdown(what)
            st.info(f"**Watch out:** {risk}")


# ── Event bus ─────────────────────────────────────────────────────────────────

# Every event the Blob can react to. Payload fields drive his reaction, so the
# simulator has to produce the same shape the real source will.
_EVENT_TYPES = {
    "donation":        {"amount": 5.00, "currency": "USD", "from": "quantfan_88", "message": "get him"},
    "superchat":       {"amount": 10.00, "currency": "USD", "from": "degenmike", "message": "buy the dip"},
    "supersticker":    {"amount": 2.00, "currency": "USD", "from": "ada_l"},
    "follow":          {"from": "new_viewer"},
    "subscription":    {"from": "member_x", "months": 1, "tier": "1"},
    "membership_gift": {"from": "whale", "count": 5},
    "bits":            {"from": "twitchuser", "amount": 500},
    "raid":            {"from": "bigstreamer", "viewers": 120},
    "chat":            {"from": "someone", "message": "is the blob ok"},
    "trade_enter":     {"symbol": "BTC/USD", "price": 64200.0},
    "trade_exit":      {"symbol": "BTC/USD", "price": 64250.0, "pnl": 12.40},
    "risk_breach":     {"limit": "daily_drawdown", "value": -9.2},
}


def _queue_event(event_type: str, payload: dict, delay_s: int, source: str = "simulated") -> None:
    with get_session() as s:
        s.execute(text("""
            INSERT INTO stream_events
                (event_type, source, payload, status, release_at, created_at)
            VALUES
                (:t, :src, CAST(:p AS JSON), :st, :rel, :now)
        """), {
            "t": event_type, "src": source, "p": json.dumps(payload),
            # A zero-delay event is released immediately; anything else holds
            # until release_at so the operator can still cancel it.
            "st": "released" if delay_s <= 0 else "queued",
            "rel": datetime.utcnow() + timedelta(seconds=max(0, delay_s)),
            "now": datetime.utcnow(),
        })
        s.commit()


def _set_status(event_id: int, status: str) -> None:
    with get_session() as s:
        s.execute(text("UPDATE stream_events SET status = :s WHERE id = :i"),
                  {"s": status, "i": event_id})
        s.commit()


def _load_events(limit: int = 40) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, event_type, source, payload, status, release_at,
                   created_at, consumed_at,
                   EXTRACT(EPOCH FROM (release_at - NOW())) AS countdown
            FROM stream_events ORDER BY created_at DESC LIMIT :l
        """), {"l": limit}).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r._mapping) for r in rows])


def _render_bus() -> None:
    st.markdown("### Event bus")
    st.caption(
        "Everything bound for the Blob lands here first. Queued events are invisible "
        "to the stream until released — the stream only ever picks up `released`."
    )

    df = _load_events()
    if df.empty:
        st.info("No events yet. Fire one from the simulator below.")
        return

    pending = df[df["status"] == "queued"]
    if not pending.empty:
        st.markdown("**Holding — release or cancel before these go out**")
        for _, r in pending.iterrows():
            cd = int(r["countdown"] or 0)
            c1, c2, c3, c4 = st.columns([3, 4, 2, 2])
            c1.markdown(f"**{r['event_type']}**  \n`{r['source']}`")
            c2.code(json.dumps(r["payload"] or {}), language="json")
            c3.metric("T-minus", f"{max(0, cd)}s" if cd > 0 else "DUE")
            if c4.button("Release", key=f"rel{r['id']}", type="primary"):
                _set_status(int(r["id"]), "released"); st.rerun()
            if c4.button("Cancel", key=f"can{r['id']}"):
                _set_status(int(r["id"]), "cancelled"); st.rerun()
        st.divider()

    st.markdown("**Recent**")
    view = df[["id", "event_type", "source", "status", "created_at", "consumed_at"]].copy()
    view["created_at"] = pd.to_datetime(view["created_at"]).dt.strftime("%H:%M:%S")
    view["consumed_at"] = pd.to_datetime(view["consumed_at"]).dt.strftime("%H:%M:%S")
    st.dataframe(view, use_container_width=True, hide_index=True, height=260)

    consumed = int((df["status"] == "consumed").sum())
    released = int((df["status"] == "released").sum())
    if released and not consumed:
        st.warning(
            f"**{released} event(s) released but none consumed.** The Stream page has not "
            "picked them up — it is either not open, not deployed with the consumer, or frozen. "
            "`consumed_at` is stamped by the page itself, so an empty column proves nothing landed."
        )


# ── Simulator ─────────────────────────────────────────────────────────────────

def _render_sim() -> None:
    st.markdown("### Simulator")
    st.caption(
        "Fire any event the Blob can react to, without waiting for a real one. "
        "Payloads match the shape the real source sends, so a rehearsal exercises "
        "the same code path as production."
    )

    c1, c2 = st.columns([1, 1])
    with c1:
        etype = st.selectbox("Event", list(_EVENT_TYPES.keys()))
        delay = st.slider("Hold before release (seconds)", 0, 60, 5,
                          help="0 fires immediately. Anything else holds it in the bus "
                               "so you can cancel before it reaches the stream.")
    with c2:
        default = json.dumps(_EVENT_TYPES[etype], indent=2)
        raw = st.text_area("Payload", value=default, height=180, key=f"pl_{etype}")

    if st.button("Queue event", type="primary"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            st.error(f"Payload is not valid JSON: {e}")
            return
        _queue_event(etype, payload, delay)
        st.success(f"`{etype}` queued — releases in {delay}s" if delay else f"`{etype}` released now")
        st.rerun()


# ── Entry point ───────────────────────────────────────────────────────────────

def render() -> None:
    st.markdown("## Stream HQ")
    st.caption("Operator console — health, event bus, and simulation for the 24/7 stream.")

    if st.button("Refresh"):
        st.rerun()

    _render_health()
    st.divider()
    _render_bus()
    st.divider()
    _render_sim()
    st.divider()
    _render_plan()
