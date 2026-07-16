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


# ── Release policy ────────────────────────────────────────────────────────────
# Stored in strategy_params under strategy='stream' rather than a new table —
# it is already the project's key/value config store with a (strategy, param)
# unique constraint.
#
# The policy lives in the DB, not in this page, because the thing that will
# eventually create real events (a Streamlabs listener) is not this page. It has
# to read the same rule, and it will be running when HQ is closed.

_POLICY_DEFAULTS = {"auto_release": "1", "default_hold_s": "5"}


def _get_policy() -> dict:
    out = dict(_POLICY_DEFAULTS)
    try:
        with get_session() as s:
            for r in s.execute(text(
                "SELECT param, value FROM strategy_params WHERE strategy = 'stream'"
            )).fetchall():
                if r.value is not None:
                    out[r.param] = r.value
    except Exception:
        pass
    return out


def _set_policy(param: str, value: str, label: str) -> None:
    with get_session() as s:
        s.execute(text("""
            INSERT INTO strategy_params (strategy, param, value, unit, label, updated_at)
            VALUES ('stream', :p, :v, '', :l, :now)
            ON CONFLICT (strategy, param)
            DO UPDATE SET value = :v, updated_at = :now
        """), {"p": param, "v": value, "l": label, "now": datetime.utcnow()})
        s.commit()


def _render_policy() -> None:
    st.markdown("### Release policy")
    st.caption(
        "The default rule applied to events as they arrive. Lives in the database, "
        "so a future Streamlabs listener obeys it too — not just this page."
    )
    pol = _get_policy()
    auto = pol.get("auto_release", "1") == "1"
    hold = int(pol.get("default_hold_s", "5") or 5)

    c1, c2 = st.columns([1, 2])
    with c1:
        new_auto = st.toggle("Auto-release", value=auto,
                             help="Off holds every incoming event indefinitely — nothing "
                                  "reaches the stream until you release it by hand.")
    with c2:
        new_hold = st.slider("Default hold before air (seconds)", 0, 60, hold,
                             disabled=not new_auto,
                             help="0 airs on the stream's next poll (~2s). Anything higher "
                                  "gives you a window to cancel.")

    if new_auto != auto or new_hold != hold:
        _set_policy("auto_release", "1" if new_auto else "0", "Auto-release incoming events")
        _set_policy("default_hold_s", str(new_hold), "Default hold before air (s)")
        st.rerun()

    if not new_auto:
        st.warning("**Auto-release is OFF.** Every incoming event — real donations included — "
                   "holds until released by hand. Nothing airs while nobody is watching HQ.")
    elif new_hold == 0:
        st.info("**Instant.** Events air on the stream's next poll with no window to cancel.")
    else:
        st.success(f"Events air **{new_hold}s** after arriving, cancellable until then.")


# The house format: {USER} just {ACTIONED} {AMOUNT} !!!
# NOTE: this mirrors headline()/VERB in dashboard/stream.js. It is duplicated on
# purpose — HQ must show what will air without importing the renderer — but the
# two must be changed together or the preview starts lying.
_VERB = {
    "donation": "DONATED", "superchat": "SUPERCHATTED", "supersticker": "STICKERED",
    "bits": "CHEERED", "membership_gift": "GIFTED", "subscription": "SUBSCRIBED",
    "follow": "FOLLOWED", "raid": "RAIDED", "chat": "SAID",
}


def _headline_preview(event_type: str, p: dict) -> str:
    if event_type == "risk_breach":
        return f"RISK BREACH — {p.get('limit', '')} !!!"
    who = str(p.get("from", "SOMEONE")).upper()
    verb = _VERB.get(event_type, "DID SOMETHING")

    amt = ""
    if event_type in ("donation", "superchat", "supersticker"):
        v = float(p.get("amount") or 0)
        amt = f"${v:.0f}" if v % 1 == 0 else f"${v:.2f}"
    elif event_type == "bits":
        amt = f"{p.get('amount', 0)} BITS"
    elif event_type == "membership_gift":
        amt = f"{p.get('count', 1)}x"
    elif event_type == "raid":
        amt = f"+{p.get('viewers', 0)}"

    return f"{who} just {verb}{(' ' + amt) if amt else ''} !!!"


def _queue_event(event_type: str, payload: dict, delay_s: int | None, source: str = "simulated") -> None:
    """Queue an event. `release_at` is the gate — the stream fires it on its own
    when the countdown expires. Nothing has to be clicked; a delay of 0 means
    release_at is now, so it airs on the stream's next poll (~2s).

    delay_s=None means "hold indefinitely": release_at stays NULL, and the
    stream's `release_at=lte.now` filter can never match a NULL, so the event
    waits for a manual release. That is how Auto-release OFF is enforced —
    in the data, not in a UI flag the stream would have to trust.
    """
    now = datetime.utcnow()
    rel = None if delay_s is None else now + timedelta(seconds=max(0, delay_s))
    with get_session() as s:
        s.execute(text("""
            INSERT INTO stream_events
                (event_type, source, payload, status, release_at, created_at)
            VALUES
                (:t, :src, CAST(:p AS JSON), 'queued', :rel, :now)
        """), {
            "t": event_type, "src": source, "p": json.dumps(payload),
            "rel": rel, "now": now,
        })
        s.commit()


def _release_now(event_id: int) -> None:
    """Skip the countdown — pull release_at to now so the next poll airs it."""
    with get_session() as s:
        s.execute(text("UPDATE stream_events SET release_at = :n WHERE id = :i"),
                  {"n": datetime.utcnow(), "i": event_id})
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
        "Everything bound for the Blob lands here first. `release_at` is the gate — "
        "an event airs on its own once its countdown expires, whether or not this page is open."
    )

    df = _load_events()
    if df.empty:
        st.info("No events yet. Fire one from the simulator below.")
        return

    # Delivery is proven by consumed_at, NOT by status — status stays 'queued'
    # after air, because flipping it would pull the row out of other renderers'
    # broadcast query. Filtering these lists on status would flag every
    # successfully aired event as stuck.
    aired = df["consumed_at"].notna()
    live = (df["status"] == "queued") & ~aired

    # Held indefinitely: no release_at at all. Not "late" — it has no T.
    held = df[live & df["release_at"].isna()]
    if not held.empty:
        st.markdown("**Held — no countdown, waiting on you**")
        for _, r in held.iterrows():
            c1, c2, c3 = st.columns([3, 5, 2])
            c1.markdown(f"**{r['event_type']}**  \n`{r['source']}`")
            c2.code(json.dumps(r["payload"] or {}), language="json")
            if c3.button("Release", key=f"hrel{r['id']}", type="primary"):
                _release_now(int(r["id"])); st.rerun()
            if c3.button("Cancel", key=f"hcan{r['id']}"):
                _set_status(int(r["id"]), "cancelled"); st.rerun()
        st.divider()

    # Still counting down — the only window in which cancelling is possible.
    pending = df[live & df["release_at"].notna() & (df["countdown"].fillna(0) > 0)]
    if not pending.empty:
        st.markdown("**Counting down — fires automatically at T-0**")
        st.caption("Cancel now or it airs on its own. Release skips the countdown.")
        for _, r in pending.iterrows():
            cd = int(r["countdown"] or 0)
            c1, c2, c3, c4 = st.columns([3, 4, 2, 2])
            c1.markdown(f"**{r['event_type']}**  \n`{r['source']}`")
            c2.code(json.dumps(r["payload"] or {}), language="json")
            c3.metric("T-minus", f"{max(0, cd)}s")
            if c4.button("Release", key=f"rel{r['id']}", type="primary"):
                _release_now(int(r["id"])); st.rerun()
            if c4.button("Cancel", key=f"can{r['id']}"):
                _set_status(int(r["id"]), "cancelled"); st.rerun()
        st.info("Countdowns tick in the database, not in this page — "
                "the event fires whether or not HQ is open. Hit Refresh to update the clock.")
        st.divider()

    # Past T-0, eligible, and still unaired. Give it a few seconds of slack for
    # the stream's ~2s poll before calling it stuck — otherwise this cries wolf
    # on every healthy event during its normal flight time.
    due = df[live & df["release_at"].notna() & (df["countdown"].fillna(0) <= -8)]
    if not due.empty:
        st.error(
            f"**{len(due)} event(s) past T-0 by 8s+ and still not aired.** They are eligible now. "
            "No Stream page is picking them up — check the Stream page heartbeat above."
        )

    st.markdown("**Recent**")
    view = df[["id", "event_type", "source", "created_at", "consumed_at"]].copy()
    # "On air" is the only status an operator cares about, and it is the one the
    # status column cannot tell them — consumed_at is the truth.
    view.insert(1, "on_air", df["consumed_at"].notna().map({True: "AIRED", False: "—"}))
    view.loc[df["status"] == "cancelled", "on_air"] = "CANCELLED"
    view["created_at"] = pd.to_datetime(view["created_at"]).dt.strftime("%H:%M:%S")
    view["consumed_at"] = pd.to_datetime(view["consumed_at"]).dt.strftime("%H:%M:%S")
    st.dataframe(view, use_container_width=True, hide_index=True, height=260)

    st.caption(
        "`consumed_at` is stamped by the first renderer to air an event — it is proof of "
        "delivery, not a lock. Events broadcast: every open Stream page shows every event. "
        "Note this means any Stream page you leave open elsewhere also airs them."
    )


# ── Simulator ─────────────────────────────────────────────────────────────────

def _render_sim() -> None:
    st.markdown("### Simulator")
    st.caption(
        "Fire any event the Blob can react to, without waiting for a real one. "
        "Payloads match the shape the real source sends, so a rehearsal exercises "
        "the same code path as production."
    )

    pol = _get_policy()
    pol_auto = pol.get("auto_release", "1") == "1"
    pol_hold = int(pol.get("default_hold_s", "5") or 5)

    c1, c2 = st.columns([1, 1])
    with c1:
        etype = st.selectbox("Event", list(_EVENT_TYPES.keys()))
        mode = st.radio(
            "Release",
            ["Use policy", "Fire now", "Hold for me"],
            horizontal=True,
            help="Use policy applies the rule above — the same path a real event takes. "
                 "Fire now skips the countdown. Hold for me waits for a manual release.",
        )
        if mode == "Use policy":
            delay = pol_hold if pol_auto else None
            st.caption(f"→ {'airs in ' + str(pol_hold) + 's' if pol_auto else 'held until released'}")
        elif mode == "Fire now":
            delay = 0
            st.caption("→ airs on the next poll (~2s)")
        else:
            delay = None
            st.caption("→ held until you release it")
    with c2:
        default = json.dumps(_EVENT_TYPES[etype], indent=2)
        raw = st.text_area("Payload", value=default, height=190, key=f"pl_{etype}")

    # Show exactly what the stream will announce, before it goes out.
    try:
        _preview = json.loads(raw)
        st.markdown(f"**On air:**  `{_headline_preview(etype, _preview)}`")
    except json.JSONDecodeError:
        st.caption("Payload is not valid JSON — fix it to see the on-air preview.")

    if st.button("Queue event", type="primary"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            st.error(f"Payload is not valid JSON: {e}")
            return
        _queue_event(etype, payload, delay)
        if delay is None:
            st.success(f"`{etype}` held — release it from the bus above.")
        elif delay == 0:
            st.success(f"`{etype}` on air within ~2s.")
        else:
            st.success(f"`{etype}` airs in {delay}s — cancellable until then.")
        st.rerun()


# ── Entry point ───────────────────────────────────────────────────────────────

def render() -> None:
    st.markdown("## Stream HQ")
    st.caption("Operator console — health, event bus, and simulation for the 24/7 stream.")

    if st.button("Refresh"):
        st.rerun()

    _render_health()
    st.divider()
    _render_policy()
    st.divider()
    _render_bus()
    st.divider()
    _render_sim()
    st.divider()
    _render_plan()
