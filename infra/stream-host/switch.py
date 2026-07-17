#!/usr/bin/env python3
"""Broadcast switch — starts and stops the encoder from Stream HQ.

The button on Stream HQ writes one row:

    strategy_params (strategy='stream', param='broadcast_enabled', value='1'|'0')

and this polls it and runs `systemctl start|stop blob-ffmpeg`. That is the whole
mechanism.

WHY POLL, RATHER THAN LISTEN
The VM has no inbound ports open, and it is not getting any. The alternative is
exposing a control endpoint on a public IP that can start and stop a broadcast —
a thing worth authenticating, rate-limiting and patching forever, so that a web
page can avoid a 5 second delay. Polling costs one small GET every few seconds
and keeps the host's attack surface at zero. watchdog.py already works this way.

WHAT IT SWITCHES
Only blob-ffmpeg — the encoder. NOT the browser. Stopping the render too would
save a little CPU on a box with nothing else to do, and cost 60-90s of Streamlit
cold start every time you flick it back on, while blinding the watchdog and
freezing the Blob on Stream HQ. Off should mean "not broadcasting", not
"everything is dead".

Note `systemctl stop` is honoured: Restart=always does not fight an explicit
stop, only a crash. That is exactly the distinction we want.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone

SUPA_URL = os.environ.get("SUPA_URL", "https://seeevuklabvhkawawtxn.supabase.co")
SUPA_KEY = os.environ.get("SUPA_KEY", "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY")

FFMPEG_UNIT = os.environ.get("FFMPEG_UNIT", "blob-ffmpeg.service")

# Poll fast so the button feels like a button.
POLL_SECONDS = int(os.environ.get("SWITCH_POLL", "5"))

# But report FAR less often than we poll. stream_health is append-only and already
# grows ~11.5k rows/day against a 500MB free tier; a 5s heartbeat would add 17k/day
# on its own to report a value that changes when a human clicks something.
REPORT_SECONDS = int(os.environ.get("SWITCH_REPORT", "30"))


def desired_state() -> bool | None:
    """True=broadcast, False=don't, None=no opinion.

    None is load-bearing. A network blip is not a request to stop: it is evidence
    that we cannot tell what was requested, and the only safe response to that is
    to leave a running broadcast exactly as it is. Same rule as watchdog.py.
    """
    url = (f"{SUPA_URL}/rest/v1/strategy_params"
           "?strategy=eq.stream&param=eq.broadcast_enabled&select=value&limit=1")
    req = urllib.request.Request(url, headers={
        "apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read())
    except Exception as e:
        print(f"[switch] cannot reach Supabase: {e}", flush=True)
        return None

    if not rows:
        # No row has ever been written — the button has never been pressed. Off:
        # a host that has just been handed a stream key should not start
        # broadcasting because nobody has told it not to.
        #
        # This is only ever true before the first click. Afterwards the row
        # persists, which is what makes a reboot resume whatever you last chose
        # instead of coming back dark.
        return False

    return str(rows[0].get("value", "0")) == "1"


def unit_state() -> str:
    """active | activating | inactive | failed | deactivating | ...

    The full string, NOT `is-active --quiet`'s exit code, and the distinction is
    the difference between a working stop button and a decorative one.

    `is-active` only exits 0 for "active". A unit that is crash-looping under
    Restart=always sits in "activating" indefinitely, so the exit code says
    not-running. The switch then compared want=off against running=False, decided
    there was nothing to do, and never issued the stop — while ffmpeg restarted
    every 5s underneath it. Pressing STOP on a failing encoder did nothing, which
    is exactly the moment you would be leaning on it.
    """
    r = subprocess.run(["systemctl", "is-active", FFMPEG_UNIT],
                       capture_output=True, text=True)
    return (r.stdout or "").strip() or "unknown"


# Anything that is not settled-inactive still needs stopping. "activating" is a
# crash loop; "failed" will become one the moment systemd's timer fires.
LIVE_STATES = ("active", "activating", "reloading", "deactivating")


def apply(verb: str) -> None:
    print(f"[switch] {verb}ing {FFMPEG_UNIT}", flush=True)
    subprocess.run(["systemctl", verb, FFMPEG_UNIT], check=False)


def post_health(status: str, detail: dict) -> None:
    body = json.dumps({
        "component": "switch",
        "status": status,
        "detail": detail,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }).encode()
    req = urllib.request.Request(
        f"{SUPA_URL}/rest/v1/stream_health", data=body, method="POST",
        headers={"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as e:
        print(f"[switch] health post failed: {e}", flush=True)


def main() -> None:
    print(f"[switch] polling broadcast_enabled every {POLL_SECONDS}s "
          f"-> {FFMPEG_UNIT}", flush=True)
    last_report = 0.0
    while True:
        want = desired_state()
        state = unit_state()

        if want is None:
            pass                       # no opinion — see desired_state
        elif want and state not in LIVE_STATES:
            # Not already up or coming up. Note this deliberately does NOT fire
            # while state=="activating": ExecStartPre sleeps 8s, so a naive
            # equality check re-issued `start` on every 5s poll and filled the
            # journal with starts for a unit that was already starting.
            apply("start")
        elif not want and state != "inactive":
            # Anything other than settled-inactive gets stopped — including
            # "activating", which is what a crash loop looks like, and "failed",
            # which is about to become one.
            apply("stop")

        # This heartbeat is the difference between a button and a placebo. If
        # this process dies, Stream HQ's click still writes the row and still
        # looks like it worked — the DB happily accepts it — while nothing on the
        # host is listening. Reporting means HQ can show that the VM is actually
        # obeying, rather than that the row was written.
        now = time.time()
        if now - last_report >= REPORT_SECONDS:
            post_health("ok", {
                "desired": "on" if want else ("off" if want is False else "unknown"),
                # The real systemd state, not a boolean. "activating" here means
                # a crash loop and is worth being able to see from HQ.
                "encoder": unit_state(),
                "unit": FFMPEG_UNIT,
            })
            last_report = now

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
