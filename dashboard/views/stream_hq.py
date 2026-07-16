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


@st.fragment(run_every="3s")
def _render_health() -> None:
    """Compact by design — this page lives in a narrow column beside the stream
    itself, so health is a strip you glance at, not a section you read.

    A FRAGMENT because this console runs beside a 24/7 stream: a health strip
    you have to refresh by hand is a health strip that is always stale, and the
    whole reason it exists is to tell you the moment something dies. Fragments
    rerun only this function, so the rest of the page — including whatever you
    are typing into the simulator — is untouched."""
    checks = [
        ("DB",      _check_db(),                     "Supabase — the channel everything rides on"),
        ("ENGINE",  _check_engine(),                 "pipeline_events still flowing"),
        ("PAGE",    _check_heartbeat("stream_page"), "the render itself — catches a frozen page"),
        ("ENCODER", _check_heartbeat("encoder"),     "ffmpeg speed / fps — needs a host agent"),
        ("HOST",    _check_heartbeat("host"),        "Oracle VM CPU / mem — needs a host agent"),
    ]

    # One line, five dots. Detail moves into the tooltip so the strip stays
    # readable at ~600px instead of wrapping into five paragraphs.
    strip = "  ".join(
        f"{_DOT.get(r['status'], '⚪')} `{n}`" for n, r, _ in checks
    )
    st.markdown(strip)

    with st.expander("health detail", expanded=False):
        for name, res, why in checks:
            st.markdown(
                f"{_DOT.get(res['status'], '⚪')} **{name}** — `{res['status'].upper()}`  \n"
                f"<span style='color:#8060a0;font-size:0.8em'>{res['detail']} · {why}</span>",
                unsafe_allow_html=True,
            )
        absent = [n for n, r, _ in checks if r["status"] == "absent"]
        if absent:
            st.warning(
                f"**{', '.join(absent)} are ⚫ ABSENT — nothing is measuring them.** "
                "They live on the streaming host and cannot be seen from this app. "
                "Absent until an agent on the VM writes to `stream_health`. "
                "Unknown, not healthy."
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
    pol = _get_policy()
    auto = pol.get("auto_release", "1") == "1"
    hold = int(pol.get("default_hold_s", "5") or 5)

    c1, c2 = st.columns([1, 2])
    with c1:
        new_auto = st.toggle("Auto-release", value=auto,
                             help="Off holds every incoming event indefinitely — nothing "
                                  "reaches the stream until you release it by hand.")
    with c2:
        new_hold = st.slider("Hold (s)", 0, 60, hold, disabled=not new_auto,
                             help="0 airs on the stream's next poll (~2s). Higher gives "
                                  "you a window to cancel.")

    if new_auto != auto or new_hold != hold:
        _set_policy("auto_release", "1" if new_auto else "0", "Auto-release incoming events")
        _set_policy("default_hold_s", str(new_hold), "Default hold before air (s)")
        st.rerun()

    if not new_auto:
        st.warning("**OFF** — every event, real donations included, holds until released by hand.")
    elif new_hold == 0:
        st.caption("Instant — airs on the next poll, no window to cancel.")
    else:
        st.caption(f"Airs **{new_hold}s** after arriving · cancellable until then · "
                   "rule lives in the DB, so a future Streamlabs listener obeys it too.")


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


@st.fragment(run_every="1s")
def _render_bus() -> None:
    """1s because this is where countdowns live. A T-minus clock that only moves
    when you press a button is not a countdown, it is a screenshot of one —
    and the cancel window is the entire point of the hold."""
    df = _load_events()
    if df.empty:
        st.info("No events yet — fire one from Simulate.")
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
        st.markdown("**Held** — no countdown, waiting on you")
        for _, r in held.iterrows():
            c1, c2 = st.columns([5, 3])
            c1.markdown(f"`{r['event_type']}` {_headline_preview(r['event_type'], r['payload'] or {})}")
            b1, b2 = c2.columns(2)
            if b1.button("Air", key=f"hrel{r['id']}", type="primary", use_container_width=True):
                _release_now(int(r["id"])); st.rerun()
            if b2.button("Kill", key=f"hcan{r['id']}", use_container_width=True):
                _set_status(int(r["id"]), "cancelled"); st.rerun()
        st.divider()

    # Still counting down — the only window in which cancelling is possible.
    pending = df[live & df["release_at"].notna() & (df["countdown"].fillna(0) > 0)]
    if not pending.empty:
        st.markdown("**Counting down** — fires on its own at T-0")
        for _, r in pending.iterrows():
            cd = int(r["countdown"] or 0)
            c1, c2 = st.columns([5, 3])
            c1.markdown(f"**T-{max(0, cd)}s** · `{r['event_type']}`  \n"
                        f"{_headline_preview(r['event_type'], r['payload'] or {})}")
            b1, b2 = c2.columns(2)
            if b1.button("Air", key=f"rel{r['id']}", type="primary", use_container_width=True):
                _release_now(int(r["id"])); st.rerun()
            if b2.button("Kill", key=f"can{r['id']}", use_container_width=True):
                _set_status(int(r["id"]), "cancelled"); st.rerun()
        st.caption("Countdowns tick in the DB — these fire whether or not HQ is open.")
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

    # Narrow column: only the columns an operator actually scans. "On air" is
    # the one thing they care about and the one thing `status` cannot tell them
    # — consumed_at is the truth.
    view = pd.DataFrame({
        "id": df["id"],
        "on_air": df["consumed_at"].notna().map({True: "AIRED", False: "—"}),
        "event": df["event_type"],
        "at": pd.to_datetime(df["created_at"]).dt.strftime("%H:%M:%S"),
    })
    view.loc[df["status"] == "cancelled", "on_air"] = "KILLED"
    st.dataframe(view, use_container_width=True, hide_index=True, height=200)

    st.caption(
        "`consumed_at` is stamped by the first renderer to air an event — proof of delivery, "
        "not a lock. Events **broadcast**: every open Stream page airs every event, so a tab "
        "you left open elsewhere is also showing them."
    )


# ── Simulator ─────────────────────────────────────────────────────────────────

def _render_sim() -> None:
    pol = _get_policy()
    pol_auto = pol.get("auto_release", "1") == "1"
    pol_hold = int(pol.get("default_hold_s", "5") or 5)

    c1, c2 = st.columns([2, 3])
    etype = c1.selectbox("Event", list(_EVENT_TYPES.keys()), label_visibility="collapsed")
    mode = c2.radio("Release", ["Policy", "Now", "Hold"], horizontal=True,
                    label_visibility="collapsed",
                    help="Policy applies the rule above — the same path a real event takes. "
                         "Now skips the countdown. Hold waits for a manual release.")
    delay = (pol_hold if pol_auto else None) if mode == "Policy" else (0 if mode == "Now" else None)

    raw = st.text_area("Payload", value=json.dumps(_EVENT_TYPES[etype]),
                       height=80, key=f"pl_{etype}", label_visibility="collapsed")

    # Show exactly what the stream will announce, before it goes out.
    try:
        st.markdown(f"**On air →** `{_headline_preview(etype, json.loads(raw))}`")
    except json.JSONDecodeError:
        st.caption("Payload is not valid JSON — fix it to see the on-air line.")

    if st.button("QUEUE EVENT", type="primary", use_container_width=True):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            st.error(f"Payload is not valid JSON: {e}")
            return
        _queue_event(etype, payload, delay)
        if delay is None:
            st.success(f"`{etype}` held — air it from Bus.")
        elif delay == 0:
            st.success(f"`{etype}` on air within ~2s.")
        else:
            st.success(f"`{etype}` airs in {delay}s.")
        st.rerun()


# ── Entry point ───────────────────────────────────────────────────────────────

def render() -> None:
    # Laid out for a narrow column beside the stream itself, not full width.
    # Health is a one-line strip and everything else is tabbed, so the console
    # never pushes the thing you are actually watching off screen.
    st.markdown("""
    <style>
    [data-testid="stMainBlockContainer"] { padding-top: 2.4rem !important; }
    /* Tight vertical rhythm — this page is scanned, not read. */
    [data-testid="stVerticalBlock"] { gap: 0.55rem !important; }
    .stTabs [data-baseweb="tab"] { padding: 6px 12px !important; }
    [data-testid="stMetricValue"] { font-size: 1rem !important; }
    </style>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([5, 3, 1])
    c1.markdown("#### ◉ Stream HQ")

    # TEMP: the YouTube filter switch. Lives in the header, not behind a tab —
    # it must be visible at a glance, because leaving it on during a real
    # capture puts fake YouTube chrome on the actual broadcast.
    pol = _get_policy()
    yt_on = pol.get("yt_overlay", "1") != "0"
    if c2.button("YT FILTER: " + ("ON" if yt_on else "OFF"),
                 use_container_width=True,
                 type="primary" if yt_on else "secondary",
                 help="Overlays YouTube's vertical-live chrome and safe zones on the "
                      "Stream page. Applies live (~3s), no reload. MUST be off for a "
                      "real capture."):
        _set_policy("yt_overlay", "0" if yt_on else "1", "Temp YouTube safe-zone filter")
        st.rerun()

    # Health and the bus refresh themselves (fragments, 3s / 1s). This is only
    # for the parts that don't — the plan text and the policy row.
    if c3.button("↻", use_container_width=True, help="Force a full reload"):
        st.rerun()

    if yt_on:
        st.caption("⚠︎ **YT filter is ON** — the Stream page is showing the design overlay, "
                   "not a clean capture.")

    _render_health()

    tab_sim, tab_bus, tab_pol, tab_plan = st.tabs(["Simulate", "Bus", "Policy", "Plan"])
    with tab_sim:
        _render_sim()
    with tab_bus:
        _render_bus()
    with tab_pol:
        _render_policy()
    with tab_plan:
        _render_plan()
