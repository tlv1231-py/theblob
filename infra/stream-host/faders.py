#!/usr/bin/env python3
"""Audio faders — Stream HQ's music/SFX sliders, applied LIVE to the encoder.

HQ writes two rows:

    strategy_params (strategy='stream', param='music_vol', value=<gain>)
    strategy_params (strategy='stream', param='sfx_vol',   value=<gain>)

This polls them and retargets ffmpeg's NAMED volume filters over ZMQ — no restart,
so moving a slider is heard within a poll with no blip on the broadcast. The
filters are volume@mvol / volume@svol in stream.sh; ffmpeg's azmq filter brokers
commands to them, and we are the ZMQ REQ client to that REP socket.

Runs on the VM for the same reason as switch.py and chat.py: the box has no
inbound ports, so control flows DB -> poll -> apply, never HQ -> VM directly.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

import zmq

SUPA_URL = os.environ.get("SUPA_URL", "https://seeevuklabvhkawawtxn.supabase.co")
SUPA_KEY = os.environ.get("SUPA_KEY", "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY")

ZMQ_ADDR = os.environ.get("FADER_ZMQ", "tcp://127.0.0.1:5555")  # azmq default port
POLL = int(os.environ.get("FADER_POLL", "3"))

# Launch defaults, matching stream.sh. Also the fallback when a row is missing or
# Supabase is unreachable — never leave the mix at a surprise level.
DEFAULTS = {"music_vol": 0.6, "sfx_vol": 2.0}
TARGET = {"music_vol": "volume@mvol", "sfx_vol": "volume@svol"}
# Clamp: a slider can't drive a filter to something absurd. 0 = silent, 8 = +18dB.
VOL_MAX = 8.0


def read_faders() -> dict:
    url = (f"{SUPA_URL}/rest/v1/strategy_params"
           "?strategy=eq.stream&param=in.(music_vol,sfx_vol)&select=param,value")
    req = urllib.request.Request(url, headers={
        "apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}"})
    out = dict(DEFAULTS)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read())
    except Exception:
        return out                       # defaults on any read failure
    for row in rows:
        try:
            out[row["param"]] = max(0.0, min(VOL_MAX, float(row["value"])))
        except (TypeError, ValueError):
            pass
    return out


def send(ctx: "zmq.Context", target: str, vol: float) -> bool:
    """One ZMQ REQ->REP. Fresh socket each call, so a missed reply (e.g. ffmpeg
    restarted mid-exchange) never wedges a persistent REQ in its send state."""
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.LINGER, 0)
    s.setsockopt(zmq.RCVTIMEO, 1500)
    s.setsockopt(zmq.SNDTIMEO, 1500)
    try:
        s.connect(ZMQ_ADDR)
        s.send_string(f"{target} volume {vol}")
        s.recv_string()                  # azmq replies with a status line
        return True
    except Exception:
        return False                     # ffmpeg down / not listening yet
    finally:
        s.close()


def main() -> None:
    ctx = zmq.Context()
    applied: dict = {}
    down_logged = False
    print(f"[faders] polling music_vol/sfx_vol every {POLL}s -> {ZMQ_ADDR}", flush=True)
    while True:
        faders = read_faders()
        # Send EVERY poll, not just on change: after an ffmpeg restart the filters
        # reset to the launch defaults, and re-sending is how the live mix
        # re-converges on the slider values without anyone touching them. Cheap —
        # two local ZMQ round-trips. Only the log is change-gated.
        any_ok = False
        for param, vol in faders.items():
            if send(ctx, TARGET[param], vol):
                any_ok = True
                if applied.get(param) != vol:
                    print(f"[faders] {param} -> {vol}", flush=True)
                    applied[param] = vol
        if any_ok:
            down_logged = False
        elif not down_logged:
            print("[faders] ffmpeg azmq not answering — encoder down? (will retry)",
                  flush=True)
            down_logged = True
            applied.clear()              # force a resend once it's back
        time.sleep(POLL)


if __name__ == "__main__":
    main()
