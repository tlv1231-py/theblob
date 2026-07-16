# Stream host

Broadcasts the vertical Stream page to YouTube, 24/7, unattended.

```
Oracle ARM VM
  └─ Xvfb :99 @ 1080x1920      blob-xvfb.service
      └─ Chromium kiosk         blob-chromium.service  ← the watchdog reloads THIS
          └─ ffmpeg x11grab     blob-ffmpeg.service    → YouTube RTMP
  ├─ agent.py                   blob-agent.service     → stream_health
  └─ watchdog.py                blob-watchdog.service  ← reads stream_health
```

Nothing here touches `dashboard/`. It only reads the deployed page and writes
`stream_health`.

## Install

```bash
git clone <repo> && cd tnd/infra/stream-host
sudo ./setup.sh          # prints the ordered checklist — follow it
```

`setup.sh` is idempotent. Re-run after editing any script.

## The five things that will bite you

These cost real hours to find. None of them announce themselves.

**1. `?yt=0` is mandatory.**
The Stream page ships a temporary design overlay drawing YouTube's own chrome
and safe zones on top of itself, and it **defaults ON**. Capture the default URL
and you broadcast a mockup of YouTube inside YouTube. `chromium.sh` refuses to
start without `yt=0` in the URL. The `YT FILTER` toggle on Stream HQ must also
read OFF.

**2. Exactly 1080x1920 or the art softens.**
The page renders a fixed 1080x1920 stage and letterboxes with a CSS transform.
At exactly that size the scale resolves to `1` and the pixel art is unresampled.
Any other geometry scales fractionally and the whole 8-bit look goes soft. Xvfb,
Chromium and ffmpeg must all agree on 1080x1920.

**3. Without `--autoplay-policy=no-user-gesture-required` the stream is silent.**
The page synthesises its 8-bit sound with WebAudio. `AudioContext` stays
suspended until a user gesture, and nobody is going to click a headless browser.
There is **no error** — it just plays nothing.
Check it: `journalctl -u blob-watchdog -f` prints the page's own audio state
every poll. It must say `audio=on`. `audio=blocked` means the flag isn't taking.

**4. Restarting ffmpeg does NOT fix a frozen page.**
The failure that kills this setup: Streamlit drops its idle websocket, the page
freezes, and ffmpeg keeps encoding a dead screenshot to YouTube for six hours.
ffmpeg is healthy. The VM is healthy. RTMP is connected. CPU is normal. Every
external signal says fine.
So the render reports on itself — the page writes a `stream_health` row every
15s with its own `{beats, nav, mood, tiles, audio}`. If those stop, it's frozen.
`watchdog.py` polls that and **reloads the browser**, which is what actually
died.

**5. `speed` must hold >= 1.0x.**
Below that ffmpeg encodes slower than real time, its buffer drains, and YouTube
stalls for viewers. It is the earliest warning the stack gives and nothing else
surfaces it. The agent reports it; Stream HQ shows it under ENCODER.
If it sags: drop `-framerate` to 20, or `-b:v` to 3500k, before anything else.

## Verify

```bash
journalctl -u blob-agent -f       # speed / fps / cpu — speed >= 1.0x
journalctl -u blob-watchdog -f    # beat age + audio state
journalctl -u blob-ffmpeg -f      # RTMP errors
x11vnc -display :99 -localhost -nopw   # actually look at it
#   ssh -L 5900:localhost:5900 <host>  then VNC to localhost:5900
```

Stream HQ (`?page=Stream+HQ`) should show all five lights green. ENCODER and
HOST are fed by `agent.py` and are black until it runs — that is deliberate, not
a bug. A health light that isn't measuring anything is worse than no light: it
reads "fine" during exactly the outage it exists to catch.

## Test the freeze recovery

Do this once, deliberately, before trusting it:

```bash
# Kill the render but leave ffmpeg running — simulates the real failure.
systemctl stop blob-chromium
# Within ~75s the watchdog should notice the beat went stale and restart it.
journalctl -u blob-watchdog -f
```

## Music

Drop 8-12 **licensed** tracks in `/opt/blob-stream/music`. WAV or FLAC — MP3 is
already lossy and re-encoding to AAC is lossy→lossy for no benefit.

`stream.sh` builds a concat playlist and loops the **playlist**, not a track: one
3-minute loop repeats ~480x/day and the AFK audience is precisely the one that
notices. `loudnorm` is applied across the set, without which volume jumps
between tracks — the most amateur-sounding defect a music-bed stream can have.

Royalty-free is **not** Content-ID-proof. Tracks get false-claimed because
someone else registered them. Keep the license PDF for disputes.

## Secrets

`YOUTUBE_KEY` lives in `/opt/blob-stream/.env` and nowhere else. It is a
credential: anyone holding it can broadcast to your channel. `.env` is gitignored
at any depth — verify with `git check-ignore -v infra/stream-host/.env`.

The Supabase key here is the **publishable/anon** key, already public in the
repo. The host never needs the database password.

## Untested

Everything above the agent is **written but not run** — there is no VM yet.
`agent.py`'s write path is verified against live Supabase (both lights confirmed
green from a dev machine). The Xvfb/Chromium/ffmpeg chain, the watchdog's
restart, and the RTMP push are all unexercised until a host exists.

One genuinely open question: whether `requestAnimationFrame` and CSS animations
run in the headless Chromium. Measured elsewhere, the animation clock stalls when
a page isn't considered "visible", which is what a virtual display looks like.
The page was deliberately built so everything essential runs on `setInterval`
(immune), and the flags in `chromium.sh` should keep the renderer awake — but
confirm on the VM: if the Blob is breathing and the starfield is drifting, the
timers are running and you are fine.
