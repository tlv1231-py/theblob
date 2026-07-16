#!/usr/bin/env python3
"""Watchdog — reloads Chromium when the RENDER dies.

This is the piece that keeps the stream honest, and it guards a failure nothing
else can see:

    Streamlit drops its idle websocket -> the page freezes -> ffmpeg keeps
    encoding a dead screenshot to YouTube for six hours.

During that, ffmpeg is healthy. The VM is healthy. RTMP is connected. CPU is
normal. YouTube receives a perfect stream of a still image. Every external
signal says fine.

So the render reports on ITSELF: the Stream page writes a stream_health row with
component='stream_page' every 15s carrying its own {beats, nav, mood, tiles,
audio}. If those rows stop, the page is frozen — full stop. That is the only
reliable detector, and this polls it.

RELOADS THE BROWSER, NOT ffmpeg. Restarting the encoder against a frozen
Chromium just re-encodes the same dead frame. The browser is what died.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SUPA_URL = os.environ.get("SUPA_URL", "https://seeevuklabvhkawawtxn.supabase.co")
SUPA_KEY = os.environ.get("SUPA_KEY", "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY")

# The page beats every 15s. 75s tolerates several dropped requests without
# calling a healthy render dead, while still catching a real freeze inside ~1
# minute of stream time.
STALE_SECONDS = int(os.environ.get("WATCHDOG_STALE", "75"))
POLL_SECONDS = int(os.environ.get("WATCHDOG_POLL", "20"))

# Give a fresh browser time to boot, load Streamlit and emit its first beat
# before judging it. Too short and the watchdog reload-loops forever.
GRACE_SECONDS = int(os.environ.get("WATCHDOG_GRACE", "90"))

CHROMIUM_UNIT = os.environ.get("CHROMIUM_UNIT", "blob-chromium.service")


def latest_page_beat() -> tuple[float | None, dict]:
    """Age in seconds of the newest stream_page heartbeat, and its detail."""
    url = (f"{SUPA_URL}/rest/v1/stream_health"
           "?component=eq.stream_page&select=recorded_at,detail"
           "&order=recorded_at.desc&limit=1")
    req = urllib.request.Request(url, headers={
        "apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read())
    except Exception as e:
        # A network failure is NOT evidence the page is dead — it is evidence we
        # cannot tell. Returning None means "no opinion", and the caller leaves
        # the browser alone. Reloading on our own connectivity blip would take a
        # working stream down.
        print(f"[watchdog] cannot reach Supabase: {e}", flush=True)
        return None, {}
    if not rows:
        return None, {}

    ts = rows[0]["recorded_at"]
    if not ts.endswith("Z") and "+" not in ts[10:]:
        ts += "+00:00"
    ts = ts.replace("Z", "+00:00")
    try:
        beat = datetime.fromisoformat(ts)
    except ValueError:
        return None, {}
    age = (datetime.now(timezone.utc) - beat).total_seconds()
    return age, rows[0].get("detail") or {}


def reload_browser() -> None:
    print(f"[watchdog] RELOADING {CHROMIUM_UNIT} — render is frozen", flush=True)
    subprocess.run(["systemctl", "restart", CHROMIUM_UNIT], check=False)


def main() -> None:
    print(f"[watchdog] stale>{STALE_SECONDS}s triggers reload of {CHROMIUM_UNIT}",
          flush=True)
    last_reload = 0.0
    while True:
        age, detail = latest_page_beat()

        if age is None:
            pass                              # no opinion — see latest_page_beat
        elif age > STALE_SECONDS:
            # Don't reload again while the last one is still booting.
            if time.time() - last_reload > GRACE_SECONDS:
                reload_browser()
                last_reload = time.time()
            else:
                print(f"[watchdog] stale {int(age)}s but within boot grace",
                      flush=True)
        else:
            # Surface the render's own view of itself — this is how you catch
            # the silent one: audio='blocked' means the autoplay flag is missing
            # and the stream has been mute this whole time with no error anywhere.
            audio = detail.get("audio")
            note = "  AUDIO BLOCKED — check --autoplay-policy" if audio == "blocked" else ""
            print(f"[watchdog] ok  beat {int(age)}s ago  "
                  f"nav={detail.get('nav')} mood={detail.get('mood')} "
                  f"tiles={detail.get('tiles')} audio={audio}{note}", flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
