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
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from sqlalchemy import text

from dashboard.db import get_session

# How stale a heartbeat may be before the component is considered dead.
# Generous relative to each writer's cadence so a single missed beat is not an
# outage — but tight enough that a frozen render is caught in ~1 minute.
_STALE = {
    "stream_page": 60,    # page beats every ~15s
    "encoder":     90,    # agent beats every ~30s (measured)
    "host":        90,    # measured: 30s
    "switch":      90,    # measured: 30s — see _check_switch
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


def _switch_state() -> dict:
    """The ON AIR button's conscience.

    The button writes `broadcast_enabled` to a table. Nothing else. A daemon on
    the VM polls that every 5s and starts/stops ffmpeg — so if the daemon is
    dead, the click still writes the row, the button still flips, and NOTHING
    HAPPENS. That is a placebo, and the dangerous direction is not the one you
    would guess: pressing OFF AIR while the daemon is dead leaves ffmpeg running
    and you believe you are off the air while still broadcasting.

    So the button is only trustworthy if `switch` is beating. It reports both
    `desired` (what it read from the policy) and `encoder` (what systemd actually
    says the unit is doing), which lets HQ catch the disagreement rather than
    merely proving something is alive.

    Returns the raw facts; the caller decides how loud to be.
    """
    out = {"alive": False, "desired": None, "encoder": None, "unit": None, "age": None}
    try:
        with get_session() as s:
            r = s.execute(text("""
                SELECT status, detail, EXTRACT(EPOCH FROM (NOW() - recorded_at)) AS age
                FROM stream_health WHERE component = 'switch'
                ORDER BY recorded_at DESC LIMIT 1
            """)).fetchone()
        if not r:
            return out
        age = int(r.age)
        out["age"] = age
        out["alive"] = age <= _STALE["switch"]
        d = r.detail if isinstance(r.detail, dict) else {}
        out["desired"] = d.get("desired")
        out["encoder"] = d.get("encoder")
        out["unit"] = d.get("unit")
        return out
    except Exception:
        return out


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
        ("SWITCH",  _check_heartbeat("switch"),      "the daemon that obeys ON AIR — dead means the button lies"),
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
    # Blobby's own voice — the speaks lane. Same Gameboy window as a popup, but
    # it is him talking, so it outranks trades and yields to viewer events.
    # `mood` is optional and takes any name from BLOB.md's taxonomy.
    "blob_speak":      {"message": "that one hurt.", "mood": "SCARED"},
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


# ── AFK phrases ───────────────────────────────────────────────────────────────
# What x says when nothing is happening. The list is the Blob's whole idle
# personality, so it belongs where you can rewrite it while watching him say it
# — not in a JS array behind a deploy.
#
# 25 characters is a hard geometric fact, not a style rule: the nameplate leaves
# 640px of runway at 25.5px/glyph and #s-title is overflow:hidden, so a 26th
# character does not wrap or shrink, it silently disappears mid-word on air.
# The stream re-checks this too — this editor is a courtesy, not the guard.
_AFK_MAX = 25

_AFK_DEFAULT = [
    "is trading", "is watching the tape", "is doing numbers", "is up to something",
    "is holding the line", "is thinking about it", "is reading the charts", "is vibing",
    "is waiting for a sign", "is down bad", "is cooking", "is locked in",
    "is calculating", "is fully committed", "is trusting the plan", "needs a minute",
    "is running the numbers", "is feeling lucky", "has a good feeling",
    "is staying humble", "is doing his best", "is monitoring", "is unbothered",
    "is so back", "is never selling", "is in the trenches", "is chilling",
    "is zoomed in", "is touching grass", "is diamond handing", "is not selling",
    "is being patient",
]


def _get_afk() -> list[str]:
    raw = _get_policy().get("afk_phrases")
    if not raw:
        return list(_AFK_DEFAULT)
    try:
        v = json.loads(raw)
        return [str(x) for x in v] if isinstance(v, list) and v else list(_AFK_DEFAULT)
    except (json.JSONDecodeError, TypeError):
        return list(_AFK_DEFAULT)


def _render_afk() -> None:
    st.caption(
        f"What **blob** says when nothing is happening — the nameplate reads "
        f"“blob *is cooking*”. One per line, **max {_AFK_MAX} characters**, live on the "
        "stream within ~15s. Longer lines are dropped, not truncated."
    )
    cur = _get_afk()
    txt = st.text_area("AFK phrases", value="\n".join(cur), height=260,
                       label_visibility="collapsed", key="afk_txt")

    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    toolong = [l for l in lines if len(l) > _AFK_MAX]
    ok = [l for l in lines if len(l) <= _AFK_MAX]

    if toolong:
        st.warning(
            f"**{len(toolong)} line(s) over {_AFK_MAX} chars — these will NOT air:**\n\n"
            + "\n".join(f"- `{l}` ({len(l)})" for l in toolong[:6])
        )
    if not ok:
        st.error("At least one phrase under the limit is required — an empty list "
                 "would leave him with nothing to say.")

    c1, c2 = st.columns([1, 1])
    if c1.button("SAVE PHRASES", type="primary", use_container_width=True, disabled=not ok):
        _set_policy("afk_phrases", json.dumps(ok), "AFK phrases for x")
        st.success(f"Saved {len(ok)} phrases — live within ~15s.")
        st.rerun()
    if c2.button("RESET TO DEFAULTS", use_container_width=True):
        _set_policy("afk_phrases", json.dumps(_AFK_DEFAULT), "AFK phrases for x")
        st.rerun()


# ── Donation power-ups ────────────────────────────────────────────────────────
# Autofilled by the stream when a paid event airs; editable here because the
# autofill cannot know everything — a name may need cleaning up, a troll may
# need revoking, and you may want to comp someone an orbit.
#
# $1 : 1 minute is the promise. `until` is an absolute timestamp rather than a
# duration so it survives a page reload, a re-deploy, and the encoder restarting
# — a countdown living in a browser tab would not.

def _get_powerups() -> list[dict]:
    raw = _get_policy().get("dono_powerups")
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(v, list):
        return []
    out = []
    for d in v:
        if not isinstance(d, dict):
            continue
        try:
            until = datetime.fromisoformat(str(d.get("until", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append({"id": str(d.get("id", "")), "name": str(d.get("name", "")),
                    "amount": float(d.get("amount") or 0), "until": until})
    return out


def _put_powerups(rows: list[dict]) -> None:
    _set_policy("dono_powerups", json.dumps([
        {"id": r["id"], "name": r["name"], "amount": float(r["amount"]),
         "until": r["until"].astimezone(timezone.utc).isoformat()}
        for r in rows
    ]), "Active donation power-ups")


# The stream only orbits this many. Mirrors PU_MAX in stream.js — they are one
# decision, and if they disagree this table lies about what is on air.
_PU_ON_AIR = 5


def _pu_since(r: dict) -> datetime:
    """When it arrived. Derived, not stored: until = arrival + amount minutes,
    so this inverts it exactly and works on every row already in the store."""
    return r["until"] - timedelta(minutes=max(1.0, float(r["amount"] or 0)))


@st.fragment(run_every="5s")
def _render_powerups() -> None:
    st.caption(
        f"Names orbiting the Blob. **Autofilled** when a paid event airs; edit or revoke "
        f"here. Duration is **$1 = 1 minute** and size scales with the amount, so the ring "
        f"shows who paid and roughly how much without anyone reading a number. "
        f"The stream orbits the **{_PU_ON_AIR} most recent** — the rest wait."
    )

    now = datetime.now(timezone.utc)
    rows = _get_powerups()
    live = [r for r in rows if r["until"] > now]
    # Expired rows are hidden here AND filtered by the stream, but they are only
    # actually deleted on the next write — nothing on this page should be doing
    # housekeeping on a 5s fragment.
    lapsed = len(rows) - len(live)

    if not live:
        st.info("No power-ups in orbit." + (f"  ({lapsed} lapsed)" if lapsed else ""))
    else:
        # NEWEST FIRST, by arrival — the same key the stream sorts on, so this
        # table shows what is actually on air rather than a different opinion.
        # It used to sort by `until`, which is arrival + amount and therefore
        # ranks an hour-old $50 above a fresh $10; new donations sank to the
        # bottom and never reached the ring.
        src = sorted(live, key=_pu_since, reverse=True)
        # An explicit KILL column. Revoking used to mean zeroing the minutes or
        # blanking the name — a side effect of editing, which is not something
        # anyone should have to discover when a troll's handle is on the stream
        # and they want it gone NOW.
        # Say which rows are ACTUALLY on the stream. Without this the table shows
        # eighteen names and the ring shows five, and the only way to find out
        # why yours is missing is to ask someone.
        df = pd.DataFrame([{
            "on air": i < _PU_ON_AIR,
            "kill": False,
            "name": r["name"],
            "$": r["amount"],
            "min left": max(0, round((r["until"] - now).total_seconds() / 60, 1)),
        } for i, r in enumerate(src)])
        edited = st.data_editor(
            df, use_container_width=True, hide_index=True, key="pu_edit",
            num_rows="fixed",
            disabled=["on air"],
            column_config={
                "on air": st.column_config.CheckboxColumn(
                    "◉", help=f"On the stream right now. Only the {_PU_ON_AIR} newest orbit; "
                              "the rest are waiting for one to lapse or be removed.",
                    width="small"),
                "kill": st.column_config.CheckboxColumn(
                    "✕", help="Tick and APPLY to remove them from orbit.", width="small"),
                "name": st.column_config.TextColumn("Name", max_chars=16),
                "$": st.column_config.NumberColumn("$", min_value=0.0, step=1.0, format="$%.2f"),
                "min left": st.column_config.NumberColumn("Min left", min_value=0.0, step=1.0,
                                                          help="Editing this re-dates the expiry "
                                                               "from now."),
            },
        )
        if len(src) > _PU_ON_AIR:
            st.caption(
                f"⚠︎ **{len(src) - _PU_ON_AIR} waiting** — only the {_PU_ON_AIR} most recent "
                "are in orbit. Remove some to let the rest on."
            )

        marked = [src[i]["name"] for i in range(len(src)) if bool(edited.iloc[i]["kill"])]
        c1, c2 = st.columns([3, 2])
        if c1.button(
            ("REMOVE " + str(len(marked)) + " + APPLY EDITS") if marked else "APPLY EDITS",
            type="primary", use_container_width=True,
        ):
            out = []
            for i, r in enumerate(src):
                e = edited.iloc[i]
                if bool(e["kill"]):
                    continue                     # ✕ ticked — gone
                mins = float(e["min left"])
                if mins <= 0 or not str(e["name"]).strip():
                    continue                     # still honoured: 0 min or no name revokes
                out.append({"id": r["id"], "name": str(e["name"]).strip()[:16],
                            "amount": float(e["$"]),
                            "until": now + timedelta(minutes=mins)})
            _put_powerups(out)
            st.success(
                ("Removed " + ", ".join(marked) + " — " if marked else "Applied — ")
                + "the ring updates within ~10s.")
            st.rerun()

        # The panic button. A single tick-every-box-and-apply is too many actions
        # when something is on the broadcast that should not be.
        if c2.button("CLEAR ALL", use_container_width=True,
                     help="Removes every power-up from orbit immediately."):
            _put_powerups([])
            st.rerun()

    with st.expander("comp a power-up", expanded=False):
        c1, c2 = st.columns([2, 1])
        nm = c1.text_input("Name", key="pu_new_nm", placeholder="viewer name",
                           label_visibility="collapsed")
        amt = c2.number_input("$", min_value=1.0, value=5.0, step=1.0, key="pu_new_amt",
                              label_visibility="collapsed")
        st.caption(f"→ orbits for **{amt:.0f} min**")
        if st.button("ADD TO ORBIT", use_container_width=True, disabled=not nm.strip()):
            rows = [r for r in _get_powerups() if r["until"] > now]
            rows.append({"id": f"hq{int(now.timestamp())}", "name": nm.strip()[:16],
                         "amount": float(amt),
                         "until": now + timedelta(minutes=float(amt))})
            _put_powerups(rows)
            st.rerun()


# ── Potions ───────────────────────────────────────────────────────────────────
# The magic power-ups. Every donation brews a RANDOM one from this pool, shown as
# a violet popup behind the dono, then run on the stream's left-side arcade HUD
# with a live countdown. Three fields per potion: name, status effect, duration.
# Stored as a JSON list in strategy_params (potions), polled by the stream ~15s.
_POTION_DEFAULT = [
    {"name": "DOUBLE XP", "status": "gains count double", "duration": 30},
    {"name": "SHIELD",    "status": "losses shrugged off", "duration": 20},
    {"name": "FRENZY",    "status": "trading twice as fast", "duration": 25},
    {"name": "LUCKY",     "status": "the next exit is a winner", "duration": 15},
    {"name": "SLOW-MO",   "status": "the market holds its breath", "duration": 20},
]


def _render_potions() -> None:
    st.caption("Every donation brews a **random** potion from this pool. Edit + "
               "**SAVE** and the live stream picks it up within ~3s — no restart "
               "needed. Note: a potion only appears **on a donation**, and the pick "
               "is random, so an edit shows up the next time that potion is rolled.")
    pol = _get_policy()
    try:
        rows = json.loads(pol.get("potions", "")) or []
    except (TypeError, ValueError):
        rows = []
    if not rows:
        rows = list(_POTION_DEFAULT)

    df = pd.DataFrame(rows, columns=["name", "status", "duration"])
    edited = st.data_editor(
        df, use_container_width=True, hide_index=True, key="potion_edit",
        num_rows="dynamic",
        column_config={
            "name": st.column_config.TextColumn("Potion name", max_chars=18, required=True),
            "status": st.column_config.TextColumn("Status effect", max_chars=40),
            "duration": st.column_config.NumberColumn("Duration (s)", min_value=1,
                                                      max_value=999, step=1, format="%d s"),
        },
    )
    if st.button("SAVE POTIONS", type="primary", use_container_width=True):
        out = []
        for _, r in edited.iterrows():
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            try:
                dur = int(r.get("duration") or 20)
            except (TypeError, ValueError):
                dur = 20
            out.append({
                "name": name[:18],
                "status": str(r.get("status") or "").strip()[:40],
                "duration": max(1, min(999, dur)),
            })
        _set_policy("potions", json.dumps(out), "Potions for the potion event")
        st.rerun()


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
    # The speaks lane has no actor and no house format — it is him talking, so
    # the preview is just the line. Falling through to the {WHO} just {VERB}
    # template below would render it as "SOMEONE just DID SOMETHING !!!".
    if event_type == "blob_speak":
        return f"blob: “{p.get('message', '')}”"
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

    # blob_speak gets real fields instead of raw JSON. Editing JSON to make a
    # character talk invited exactly one mistake, and it was made immediately:
    # overwrite the KEY with the line you want said rather than the value, giving
    # {"I see what you're doing here.": "that one hurt."} — no `message` key, so
    # the stream dropped it silently. The line is the ONLY thing anyone wants to
    # change here, so it gets its own box and cannot be misplaced.
    if etype == "blob_speak":
        # Mood sits OUTSIDE the form so it survives clear_on_submit — you can send
        # ten HAPPY lines in a row without re-picking it every time.
        mood = st.selectbox("Mood", ["(none)", "HAPPY", "SCARED", "ALERT", "SMUG", "IDLE"],
                            index=2, key="speak_mood", label_visibility="collapsed",
                            help="Drives his face while he talks. From BLOB.md's taxonomy.")
        # A FORM purely so ENTER sends. The alternative — on_change on a bare
        # text_input — also fires on BLUR, so clicking away from a half-typed line
        # would air it. A form submits on Enter or the button, and on nothing else.
        # There is no live "On air →" line here because a form's value does not
        # propagate until submit: the preview could only ever echo the PREVIOUS
        # line, which is worse than no preview. Nothing is lost — that preview
        # exists to decode JSON into a headline, and this box needs no decoding.
        with st.form("speak_form", clear_on_submit=True, border=False):
            line = st.text_input("Line", key="speak_line", label_visibility="collapsed",
                                 placeholder="what should blob say?   ↵ sends")
            sent = st.form_submit_button("QUEUE EVENT  ↵", type="primary",
                                         use_container_width=True)
        if not sent:
            return
        if not str(line).strip():
            st.error("Give him a line to say.")
            return
        payload = {"message": line}
        if mood != "(none)":
            payload["mood"] = mood
        _queue_event("blob_speak", payload, delay)
        # No st.rerun(): submitting the form already reran us, and rerunning again
        # would wipe this confirmation before anyone could read it.
        st.success("`blob: “{}”` {}".format(line, (
            "held — air it from Bus." if delay is None
            else "on air within ~2s." if delay == 0
            else f"airs in {delay}s.")))
        return

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

def _render_audio() -> None:
    st.caption("Live audio faders. **faders.py** on the host polls these ~3s and "
               "retargets the encoder over ZMQ — no restart, no blip. Music is the "
               "bed; SFX are the Blob's 8-bit sounds, boosted because the browser "
               "emits them quiet against the -16 LUFS music.")
    pol = _get_policy()
    try:
        music = float(pol.get("music_vol", "0.6") or 0.6)
    except ValueError:
        music = 0.6
    try:
        sfx = float(pol.get("sfx_vol", "2.0") or 2.0)
    except ValueError:
        sfx = 2.0

    c1, c2 = st.columns(2)
    with c1:
        new_music = st.slider("♫ Music bed", 0.0, 1.5, music, 0.05,
                              help="Gain on the music. 0.60 is the default bed level.")
    with c2:
        new_sfx = st.slider("▸ Blob SFX", 0.0, 4.0, sfx, 0.1,
                            help="Gain on the 8-bit sounds. 2.0 default — the browser "
                                 "emits them quiet, so they need the boost to cut through.")

    if abs(new_music - music) > 1e-9:
        _set_policy("music_vol", f"{new_music:.2f}", "Music bed gain")
    if abs(new_sfx - sfx) > 1e-9:
        _set_policy("sfx_vol", f"{new_sfx:.2f}", "SFX gain")

    st.caption(f"Now: music **{new_music:.2f}** · sfx **{new_sfx:.2f}**. "
               "0 mutes that channel. A change is audible on the broadcast within a poll.")


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

    c1, c2, c3, c4 = st.columns([3, 3, 3, 1])
    c1.markdown("#### ◉ Stream HQ")

    pol = _get_policy()

    # ── ON AIR ────────────────────────────────────────────────────────────
    # The only control here that reaches the outside world. Everything else on
    # this page changes what YOU see; this one starts and stops a public
    # broadcast, so it is the one that must never lie about its own state.
    #
    # It writes `broadcast_enabled` and nothing more. switch.py on the VM polls
    # that every 5s and runs systemctl start|stop blob-ffmpeg (the host has no
    # inbound ports — it pulls). Resting state is '0': nothing airs until pressed.
    sw = _switch_state()
    on_air = pol.get("broadcast_enabled", "0") == "1"

    # A dead daemon makes this a placebo, so say so IN THE LABEL rather than
    # rendering a confident ON AIR that controls nothing.
    if sw["alive"]:
        label = "◉ ON AIR" if on_air else "○ OFF AIR"
        btn_help = ("Starts/stops the YouTube encoder on the stream host. Applies in ~5s. "
                    "The render keeps running either way.")
    else:
        label = "⚠ NO SWITCH"
        btn_help = ("The switch daemon on the host is not reporting, so this button would "
                    "write the flag and nothing would obey it. Fix the host before trusting it.")

    if c2.button(label, use_container_width=True,
                 type="primary" if (on_air and sw["alive"]) else "secondary",
                 disabled=not sw["alive"],
                 help=btn_help):
        _set_policy("broadcast_enabled", "0" if on_air else "1", "Broadcast to YouTube")
        st.rerun()

    # TEMP: the YouTube filter switch. Lives in the header, not behind a tab —
    # it must be visible at a glance, because leaving it on during a real
    # capture puts fake YouTube chrome on the actual broadcast.
    # c3, not c2 — ON AIR already owns c2, and the two had been stacking in one
    # column ever since ON AIR was added. The freed SOUND slot is where this
    # belongs.
    yt_on = pol.get("yt_overlay", "1") != "0"
    if c3.button("YT FILTER: " + ("ON" if yt_on else "OFF"),
                 use_container_width=True,
                 type="primary" if yt_on else "secondary",
                 help="Overlays YouTube's vertical-live chrome and safe zones on the "
                      "Stream page. Applies live (~3s), no reload. MUST be off for a "
                      "real capture."):
        _set_policy("yt_overlay", "0" if yt_on else "1", "Temp YouTube safe-zone filter")
        st.rerun()

    # ── Background ────────────────────────────────────────────────────────────
    # The animated cyberpunk background on the Stream page, controllable live so
    # you can dim it under the Blob or kill it entirely mid-broadcast without a
    # reload. Same store and shape as every other live setting; the stream polls
    # it ~2s and eases the opacity so the fader reads as a fade, not a jump.
    # OFF stops the draw loop on the host, so it is a real toggle, not just an
    # invisible canvas. 68 is the tuned default (full strength out-shouts the sun).
    bg_on = pol.get("bg_enabled", "1") != "0"
    try:
        bg_op = max(0, min(100, int(float(pol.get("bg_opacity", "68")))))
    except (TypeError, ValueError):
        bg_op = 68
    bgc1, bgc2 = st.columns([1, 3])
    if bgc1.button("BG: " + ("ON" if bg_on else "OFF"), use_container_width=True,
                   type="primary" if bg_on else "secondary",
                   help="The animated cyberpunk background on the Stream page. Fades out "
                        "when off and stops rendering. Applies live (~2s), no reload."):
        _set_policy("bg_enabled", "0" if bg_on else "1", "Stream animated background on/off")
        st.rerun()
    new_bg_op = bgc2.slider("BG opacity", 0, 100, bg_op, disabled=not bg_on,
                            help="Fades the background live on the Stream page. 68 is the "
                                 "tuned default; 100 is full strength, 0 is invisible.")
    if new_bg_op != bg_op:
        _set_policy("bg_opacity", str(new_bg_op), "Stream background opacity (%)")
        st.rerun()

    # The SOUND/MUTED button is GONE, and so is preview_muted.
    #
    # It worked exactly as designed, and that was the problem: it sat at 1 for
    # hours while a phone was reported as having no sound. A silent device reads
    # as a broken device, not as a toggle on another page doing its job. It cost
    # more debugging than it ever saved.
    #
    # Removed rather than left defaulting to 0: a toggle the Stream page no
    # longer reads is a placebo, and this console already refuses to ship one of
    # those (see ON AIR). To kill the noise: mute the browser tab.

    # Health and the bus refresh themselves (fragments, 3s / 1s). This is only
    # for the parts that don't — the plan text and the policy row.
    if c4.button("↻", use_container_width=True, help="Force a full reload"):
        st.rerun()

    # ── Does the encoder agree with the button? ───────────────────────────
    # The switch reports `desired` (what it read) alongside `encoder` (what
    # systemd actually says). Comparing them is the difference between "the
    # button works" and "the button wrote a row". A green light only proves the
    # daemon is alive; this proves it did the thing.
    if not sw["alive"]:
        st.error(
            f"**The switch daemon is not reporting"
            + (f" (last beat {sw['age']}s ago)" if sw["age"] is not None else " — it never has")
            + ".** ON AIR is disabled because it would be a placebo: the click writes a "
            "flag, and nothing on the host is listening. If the encoder was already "
            "running when the daemon died, **it is still broadcasting** — this app cannot "
            "stop it. Fix the host."
        )
    else:
        enc = (sw["encoder"] or "unknown").lower()
        seen = (sw["desired"] or "").lower()      # what the switch itself last READ
        want_on = on_air
        want_str = "on" if want_on else "off"
        age_txt = f"{sw['age']}s ago" if sw["age"] is not None else "unknown"
        # DO NOT compare the button against a report that predates the click.
        #
        # The button writes instantly; switch.py only POSTS its state every ~30s
        # (SWITCH_REPORT), though it polls and acts every ~5s. So for up to 30s
        # after any click the newest row still describes the PREVIOUS state — and
        # this block used to read that as a fault and shout "YOU ARE PROBABLY
        # STILL BROADCASTING" on a perfectly good stop, while telling you it
        # would clear in ~5s (the poll interval, not the report interval — it
        # could not clear that fast). It cried wolf on every single press.
        #
        # `desired` is what the switch last read from the flag, so it dates the
        # report: if it still disagrees with the button, the row is simply older
        # than the click. Wait for the next one rather than alarming.
        if seen and seen != want_str:
            st.info(
                f"Waiting for the host to confirm **{'ON AIR' if want_on else 'OFF AIR'}** — "
                f"the switch acts within ~5s but only reports every ~30s (last report {age_txt}). "
                "This clears on its own."
            )
        # From here the switch has confirmed it read the same flag you set, so a
        # mismatch is real.
        elif want_on and enc != "active":
            st.error(
                f"**ON AIR is set, but `{sw['unit'] or 'the encoder unit'}` is `{enc}`.** "
                "Nothing is reaching YouTube. The switch is alive and saw the flag, so this "
                "is the encoder itself failing — check its journal on the host."
            )
        elif not want_on and enc == "active":
            st.error(
                f"**OFF AIR is set and the switch has confirmed it read that, but "
                f"`{sw['unit'] or 'the encoder unit'}` is still `active` — YOU ARE PROBABLY "
                f"STILL BROADCASTING.** (Report {age_txt}.) This is not a lag: the host saw "
                "the flag and the unit did not stop. Stop it on the host directly:\n\n"
                f"`sudo systemctl stop {sw['unit'] or 'blob-ffmpeg.service'}`"
            )
        elif want_on and enc == "active":
            st.success("**◉ LIVE** — the encoder is active and pushing to YouTube.")

    if yt_on:
        st.caption("⚠︎ **YT filter is ON** — the Stream page is showing the design overlay, "
                   "not a clean capture.")

    _render_health()

    tab_sim, tab_bus, tab_pu, tab_pot, tab_afk, tab_aud, tab_pol, tab_plan = st.tabs(
        ["Simulate", "Bus", "Orbit", "Potions", "AFK", "Audio", "Policy", "Plan"])
    with tab_aud:
        _render_audio()
    with tab_pu:
        _render_powerups()
    with tab_pot:
        _render_potions()
    with tab_afk:
        _render_afk()
    with tab_sim:
        _render_sim()
    with tab_bus:
        _render_bus()
    with tab_pol:
        _render_policy()
    with tab_plan:
        _render_plan()
