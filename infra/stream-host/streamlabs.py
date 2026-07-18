#!/usr/bin/env python3
"""Streamlabs Socket API -> stream_events, so the Blob reacts to money.

The sibling of chat.py. That one listens to YouTube's own chat (super chats,
memberships); this one listens to Streamlabs, and the difference is the whole
point:

    SUPER CHAT REQUIRES YOUTUBE PARTNER PROGRAM. Until the channel is monetised
    the button does not exist for viewers, so chat.py can be running perfectly
    and still never see a cent. A Streamlabs tip page takes money on ANY channel,
    at any subscriber count, from day one. This is how the Blob gets paid before
    YPP, and it is why `source` in data/models.py has always read
    `streamlabs | simulated | engine`.

Streamlabs also relays follows / subs / raids from the connected platform, so the
event_type vocabulary in models.py (donation | follow | subscription | bits |
raid) maps onto its Socket API one-for-one. Nothing downstream changes: this
writes the same rows stream_hq's simulator writes, so the popup -> potion ->
orbs -> crown chain is already tested against them.

WHY IT RUNS HERE
Same reason as chat.py: Streamlit Community Cloud sleeps when no browser holds a
session and has no process awake at 3am. This VM is up 24/7 next to the switch,
the watchdog and the chat listener.

⚠ THE SOCKET.IO VERSION PIN IS LOAD-BEARING.
Streamlabs speaks Socket.IO **v2**. python-socketio 5.x speaks v4 and will
connect, handshake, and then sit there receiving NOTHING — no error, no events,
which is indistinguishable from "nobody has tipped yet" and is a miserable thing
to debug. Install the v2-speaking pair explicitly:

    pip install "python-socketio[client]==4.6.1" "python-engineio==3.14.2"

TOKEN
Streamlabs dashboard -> Settings -> API Settings -> API Tokens -> **Socket API
Token**. NOT the OAuth client secret and NOT the "API Key". Put it in
/opt/blob-stream/.env as STREAMLABS_TOKEN. That token is a password to your
alert feed: .env is root:root 0600 and gitignored, same as YOUTUBE_KEY.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

SUPA_URL = os.environ.get("SUPA_URL", "https://seeevuklabvhkawawtxn.supabase.co")
SUPA_KEY = os.environ.get("SUPA_KEY", "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY")

TOKEN = os.environ.get("STREAMLABS_TOKEN", "").strip()
SOCKET_URL = "https://sockets.streamlabs.com"

# Streamlabs' event names -> the event_type vocabulary in data/models.py.
# `host` folds into raid: both mean "someone arrived with an audience", and the
# page already knows how to air a raid. Anything unmapped is ignored rather than
# guessed at — an unknown event_type would reach the page and render as a popup
# with no verb.
KIND_MAP = {
    "donation":     "donation",
    "subscription": "subscription",
    "resub":        "subscription",
    "follow":       "follow",
    "bits":         "bits",
    "raid":         "raid",
    "host":         "raid",
    "superchat":    "superchat",
    "membershipGift": "membership_gift",
}


def hold_policy() -> tuple[bool, int]:
    """(auto_release, hold_seconds) — the SAME strategy_params HQ writes.

    Read live rather than cached so flipping auto-release in HQ governs this
    listener too, exactly as the tooltip there promises.
    """
    url = (f"{SUPA_URL}/rest/v1/strategy_params"
           "?strategy=eq.stream&param=in.(auto_release,default_hold_s)&select=param,value")
    req = urllib.request.Request(url, headers={
        "apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read())
    except Exception:
        return True, 5                      # never block a tip on a network blip
    pol = {r["param"]: r["value"] for r in rows}
    return pol.get("auto_release", "1") == "1", int(pol.get("default_hold_s", "5") or 5)


def emit(event_type: str, payload: dict) -> bool:
    """Write one event onto the bus. Identical shape to chat.py's emit().

    source='streamlabs' is the discriminator models.py documents, so the bus can
    tell a real tip from the HQ simulator after the fact.
    """
    auto, hold = hold_policy()
    now = datetime.now(timezone.utc)
    body = {
        "event_type": event_type,
        "source": "streamlabs",
        "payload": payload,
        "status": "queued",
        "release_at": (now + timedelta(seconds=hold)).isoformat() if auto else None,
        "created_at": now.isoformat(),
    }
    req = urllib.request.Request(
        f"{SUPA_URL}/rest/v1/stream_events", data=json.dumps(body).encode(),
        method="POST",
        headers={"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
        return True
    except Exception as e:
        print(f"[streamlabs] emit {event_type} failed: {e}", flush=True)
        return False


def _num(v):
    """Streamlabs sends amounts as STRINGS ("10.00"). The page does
    Number(p.amount).toFixed(2) and prefixes '$' itself, so hand it a number —
    the same trap chat.py's _dollars() documents for YouTube's "$5.00"."""
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def to_payload(kind: str, m: dict) -> dict:
    """Map one Streamlabs message onto the payload shape stream.js reads.

    The contract is `p.from`, `p.amount`, `p.count`, `p.viewers`, `p.message` —
    NOT Streamlabs' field names. Keep this the only place that knows both.
    """
    p: dict = {"from": m.get("name") or m.get("from") or "SOMEONE"}
    msg = (m.get("message") or "")
    if isinstance(msg, str) and msg:
        p["message"] = msg[:200]

    if kind in ("donation", "superchat"):
        p["amount"] = _num(m.get("amount"))
        if m.get("currency"):
            p["currency"] = m["currency"]
    elif kind == "bits":
        p["amount"] = _num(m.get("amount"))
    elif kind == "subscription":
        # months is what a resub is bragging about; the page reads p.count.
        p["count"] = m.get("months") or m.get("streak_months") or 1
    elif kind == "raid":
        p["viewers"] = m.get("raiders") or m.get("viewers") or 0
    return p


def main() -> None:
    if not TOKEN:
        raise SystemExit("STREAMLABS_TOKEN missing — put the SOCKET API token in "
                         "/opt/blob-stream/.env (Streamlabs -> Settings -> API "
                         "Settings -> API Tokens -> Socket API Token)")
    try:
        import socketio            # noqa: PLC0415  (import here so the pin error is legible)
    except ImportError:
        raise SystemExit('python-socketio missing. Install the SOCKET.IO v2 pair:\n'
                         '  pip install "python-socketio[client]==4.6.1" '
                         '"python-engineio==3.14.2"')

    sio = socketio.Client(reconnection=True, reconnection_delay=5,
                          reconnection_delay_max=60, logger=False, engineio_logger=False)

    # Streamlabs replays recent alerts on reconnect. Without this a dropped
    # socket would re-air every tip of the session — the Blob thanking the same
    # person six times is worse than missing one.
    seen: set[str] = set()

    @sio.event
    def connect():
        print("[streamlabs] connected — listening for tips", flush=True)

    @sio.event
    def disconnect():
        print("[streamlabs] disconnected — will retry", flush=True)

    @sio.on("event")
    def on_event(data):
        try:
            kind = (data or {}).get("type")
            et = KIND_MAP.get(kind)
            if not et:
                return                                  # unknown -> ignore, never guess
            for m in (data.get("message") or []):
                # Streamlabs' own id, so a replay is idempotent.
                mid = str(m.get("_id") or m.get("id") or "")
                if mid and mid in seen:
                    continue
                if mid:
                    seen.add(mid)
                    if len(seen) > 2000:                # bounded; this runs for weeks
                        seen.clear()
                # A Streamlabs TEST alert has isTest — air it, that is the point
                # of the button, but say so in the log so a confusing $1 in the
                # history is traceable.
                if m.get("isTest"):
                    print(f"[streamlabs] TEST {kind}", flush=True)
                p = to_payload(et, m)
                if emit(et, p):
                    print(f"[streamlabs] {et} from {p.get('from')} "
                          f"{p.get('amount', '')}".rstrip(), flush=True)
        except Exception as e:
            # One malformed alert must never kill the listener.
            print(f"[streamlabs] handler error: {e}", flush=True)

    while True:
        try:
            sio.connect(f"{SOCKET_URL}?token={TOKEN}", transports=["websocket"])
            sio.wait()
        except Exception as e:
            print(f"[streamlabs] connect failed: {e} — retrying in 15s", flush=True)
            time.sleep(15)


if __name__ == "__main__":
    main()
