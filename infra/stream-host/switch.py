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
import re
import shutil
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

# ── CHANGING THE CHANNEL ─────────────────────────────────────────────────────
# The stream host captures a URL and knows nothing about what is on it, so
# switching apps is entirely "rewrite STREAM_URL and restart the render". The
# page is chosen by Stream HQ writing `active_app`, exactly like the ON AIR
# button writes `broadcast_enabled`.
ENV_PATH = os.environ.get("STREAM_ENV", "/opt/blob-stream/.env")
CHROMIUM_UNIT = os.environ.get("CHROMIUM_UNIT", "blob-chromium.service")

# AN ALLOWLIST, NOT VALIDATION — this is the security boundary of the whole
# switch. `active_app` arrives from a database row and is interpolated into the
# URL that Chromium loads and that stream.sh derives the music path from. Anything
# permissive (a regex, an escape, a "sanitise") is one clever value away from
# pointing the broadcast at an arbitrary page. Membership in this dict is the
# only way to be on air, and adding an app is a deliberate code change.
STREAM_APPS = ("Stream", "RetroNews")

# Chromium cold-starts a Streamlit page in 60-90s. Without a gate, the poll loop
# would see want=on / ffmpeg=down 5s after the restart and immediately broadcast
# ~90s of an empty X display. Holding the encoder until the render is warm turns
# a switch into a clean cut instead of a minute and a half of black.
WARMUP_SECONDS = int(os.environ.get("SWITCH_WARMUP", "100"))

_PAGE_RE = re.compile(r"([?&]page=)([^&\s\"']*)")


def desired_app() -> str | None:
    """Which page HQ wants on air. None = no opinion (see desired_state)."""
    url = (f"{SUPA_URL}/rest/v1/strategy_params"
           "?strategy=eq.stream&param=eq.active_app&select=value&limit=1")
    req = urllib.request.Request(url, headers={
        "apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read())
    except Exception as e:
        print(f"[switch] cannot read active_app: {e}", flush=True)
        return None
    if not rows:
        return None                 # never set — leave whatever .env says alone
    want = str(rows[0].get("value", "")).strip()
    if want not in STREAM_APPS:
        print(f"[switch] REFUSING unknown app {want!r} — not in {STREAM_APPS}",
              flush=True)
        return None
    return want


def _env_text() -> str | None:
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[switch] cannot read {ENV_PATH}: {e}", flush=True)
        return None


def current_app() -> str | None:
    """The page actually configured on this host, read from .env.

    Deliberately reads the FILE rather than this process's environment: systemd
    injected STREAM_URL at start, so os.environ holds whatever was true when the
    switch booted and would go stale the first time we changed it.
    """
    txt = _env_text()
    if txt is None:
        return None
    for line in txt.splitlines():
        if line.strip().startswith("STREAM_URL="):
            m = _PAGE_RE.search(line)
            return m.group(2) if m else None
    return None


def switch_app(app: str) -> bool:
    """Point STREAM_URL at `app` and restart the render chain.

    RESTARTS BOTH UNITS, and that is not belt-and-braces. stream.sh derives the
    music bed from ?page= and reads it ONCE at ffmpeg start, so restarting only
    Chromium changes the picture and leaves the previous app's music playing
    underneath it, with nothing on screen to explain why.

    This is the one thing on the host that writes .env — deploy.sh explicitly
    refuses to. The file holds the stream key, so its mode is copied onto the
    replacement rather than inherited from a fresh temp file.
    """
    if app not in STREAM_APPS:                     # belt: callers are trusted,
        return False                               # this costs nothing
    txt = _env_text()
    if txt is None:
        return False

    out, hit = [], False
    for line in txt.splitlines(keepends=True):
        if line.strip().startswith("STREAM_URL=") and _PAGE_RE.search(line):
            line, n = _PAGE_RE.subn(lambda m: m.group(1) + app, line, count=1)
            hit = hit or bool(n)
        out.append(line)
    if not hit:
        print(f"[switch] no STREAM_URL with a ?page= in {ENV_PATH} — not switching",
              flush=True)
        return False

    tmp = ENV_PATH + ".switch.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("".join(out))
        shutil.copymode(ENV_PATH, tmp)   # .env holds the stream key — keep 0600
        os.replace(tmp, ENV_PATH)
    except Exception as e:
        print(f"[switch] failed writing {ENV_PATH}: {e}", flush=True)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False

    print(f"[switch] APP -> {app}; restarting render chain", flush=True)
    # Encoder DOWN first. Chromium is about to disappear for ~90s and there is no
    # value in shipping that to YouTube; the warm-up gate brings it back.
    subprocess.run(["systemctl", "stop", FFMPEG_UNIT], check=False)
    subprocess.run(["systemctl", "restart", CHROMIUM_UNIT], check=False)
    return True


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


def apply(verb: str, state: str) -> None:
    print(f"[switch] {verb} {FFMPEG_UNIT} (was {state})", flush=True)
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
    warm_until = 0.0                   # encoder held off until the render is up
    while True:
        want = desired_state()
        state = unit_state()

        # Channel change is checked BEFORE the on-air logic, so a switch and the
        # warm-up gate it sets are both visible to this same iteration rather
        # than racing a 5s poll.
        want_app, have_app = desired_app(), current_app()
        if want_app and have_app and want_app != have_app:
            if switch_app(want_app):
                warm_until = time.time() + WARMUP_SECONDS
                state = unit_state()   # we just stopped it; don't act on a stale read

        if want is None:
            pass                       # no opinion — see desired_state
        elif want and state not in LIVE_STATES and time.time() < warm_until:
            # Wanted on air, encoder down, render still cold. Not an error state
            # and not something to correct — it is the switch working.
            pass
        elif want and state not in LIVE_STATES:
            # Not already up or coming up. Deliberately does NOT fire while
            # state=="activating": ExecStartPre sleeps 8s, so re-issuing `start`
            # on every 5s poll would fill the journal with starts for a unit that
            # is already starting.
            apply("start", state)
        elif not want and state in LIVE_STATES:
            # Only stop what is actually up. "activating" is included because
            # that is what a crash loop looks like under Restart=always, and
            # stopping it is the whole point of the button.
            #
            # "failed" is NOT in LIVE_STATES, and that matters: `systemctl stop`
            # does not clear a failed state, so testing `state != "inactive"`
            # here re-issued a stop every 5s forever against a unit that had
            # already stopped. Failed is not running. There is nothing to stop.
            apply("stop", state)

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
                # What is ACTUALLY on air, read back from .env — not what HQ
                # asked for. Same principle as reporting the real systemd state:
                # HQ can then show that the host obeyed, instead of showing its
                # own click back to itself.
                "app": current_app(),
                "warming": max(0, int(warm_until - time.time())) or None,
            })
            last_report = now

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
