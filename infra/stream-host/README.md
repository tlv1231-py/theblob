# Stream host

Broadcasts the vertical Stream page to YouTube, 24/7, unattended.

```
Oracle ARM VM
  └─ Xvfb :99 @ 1080x1920      blob-xvfb.service
      └─ Chromium kiosk         blob-chromium.service  ← the watchdog reloads THIS
          └─ ffmpeg x11grab     blob-ffmpeg.service    → YouTube RTMP
  ├─ agent.py                   blob-agent.service     → stream_health
  ├─ watchdog.py                blob-watchdog.service  ← reads stream_health
  ├─ switch.py                  blob-switch.service    ← Stream HQ START/STOP
  └─ chat.py                    blob-chat.service      → stream_events (viewers)
```

Nothing here touches `dashboard/`. It only reads the deployed page and writes
`stream_health`.

## Install

```bash
git clone <repo> && cd tnd/infra/stream-host
sudo ./setup.sh          # prints the ordered checklist — follow it
```

`setup.sh` is idempotent. Re-run after editing any script.

## The seven things that will bite you

These cost real hours to find. None of them announce themselves.

**1. Both query params are mandatory — `?yt=0&live=1`.**
`chromium.sh` refuses to start without each of them.

`yt=0` — the Stream page ships a temporary design overlay drawing YouTube's own
chrome and safe zones on top of itself, and it **defaults ON**. Capture the
default URL and you broadcast a mockup of YouTube inside YouTube. The `YT FILTER`
toggle on Stream HQ must also read OFF.

`live=1` — marks this render as **the broadcast**, which is what makes it ignore
Stream HQ's mute toggle. Without it the VM's browser is just another window that
obeys the toggle, so muting the noise on your own desk silences the actual
YouTube stream. **The watchdog cannot catch this one**: the heartbeat's `audio`
field reports whether `AudioContext` is running, not whether the page is muted,
so a muted broadcast still beats `audio=on`. The guard is the only thing in front
of it.

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

**6. Chromium does not run as root, and on Ubuntu it is a snap.**
Two failures with one fix. Chromium hard-refuses to start as root ("Running as
root without --no-sandbox is not supported"), and Ubuntu's `chromium` deb is a
transitional package that installs the **snap** — which is confined and may only
touch its own user's `$HOME`, so a profile under `/run` is refused outright.
Google ships no Chrome for linux-arm64, so on an Ampere box the snap is the only
option on Ubuntu. Hence: the units run as the unprivileged `blob` user
(`setup.sh` creates it) with the profile at `/home/blob/chrome-profile`, which
satisfies snap and native alike. `.env` deliberately stays `root:root 0600` —
systemd reads `EnvironmentFile=` as root before dropping privileges, so the
services still get `YOUTUBE_KEY` while the browser's own user cannot read the
credential that owns your channel.

**7. The fonts come from Google, at load time.**
The page requests Press Start 2P and VT323 from `fonts.googleapis.com`. Neither is
packaged in apt, and with nothing local `fc-match` resolves **both to DejaVu
Sans** — not even a monospace. One Google Fonts blip during a watchdog reload and
the whole pixel-art stream renders in generic sans while every light stays green:
the page beats, ffmpeg holds speed, RTMP is connected. `setup.sh` installs both
locally (SIL Open Font License, redistribution permitted, licences alongside), so
the fetch is an optimisation and not a dependency. Check it:

```bash
fc-match 'Press Start 2P'   # must NOT say DejaVu
```

## The START/STOP button

Stream HQ starts and stops the broadcast by writing one row:

```
strategy_params (strategy='stream', param='broadcast_enabled', value='1'|'0')
```

`switch.py` polls it every 5s and runs `systemctl start|stop blob-ffmpeg`. Same
mechanism as the existing `preview_muted` and `yt_overlay` toggles.

**It polls; it does not listen.** The VM has no inbound ports and is not getting
any. The alternative is a control endpoint on a public IP that can start and stop
a broadcast — worth authenticating, rate-limiting and patching forever, to save
five seconds. `watchdog.py` already works this way.

Four decisions worth knowing:

- **It switches the encoder, not the browser.** Off means "not broadcasting", not
  "everything is dead". Stopping the render too would save little on an idle box
  and cost a 60–90s Streamlit cold start on every flick, while blinding the
  watchdog and freezing the Blob on Stream HQ.
- **Unreachable Supabase means no opinion.** A network blip is not a request to
  stop; it is evidence we cannot tell what was requested. A running broadcast is
  left alone.
- **No row means off.** A host that has just been handed a stream key should not
  start broadcasting because nobody told it not to. That is only true before the
  first click — afterwards the row persists, so a reboot resumes whatever you
  last chose rather than coming back dark.
- **`switch.py` reports its own heartbeat** (`component='switch'`). This is the
  difference between a button and a placebo: if the daemon dies, HQ's click still
  writes the row and still looks like it worked, while nothing on the host is
  listening.

When the switch is off, `agent.py` reports the encoder as **degraded**, not down,
with `reason: broadcast switch is off`. A red light for a system doing exactly
what it was told is how you learn to ignore red lights. (`off` is deliberately
not used — HQ's `_DOT` maps only ok/degraded/down/absent/unknown and would
KeyError on anything else.)

## Viewer events (chat.py)

`liveChatMessages.list` returns regular chat, super chats, super stickers, new
members and gifted memberships in **one** stream, so this is one integration
rather than four. Each becomes a `stream_events` row and the Blob reacts.

**"Follows" are Twitch.** YouTube has subscribers and offers no real-time
new-subscriber event to anyone — Streamlabs and StreamElements fake sub alerts by
polling a delayed list. Paid **memberships** fire properly and arrive as
`newSponsorEvent`. Plain subs are not on the menu, from any vendor.

**Quota is the entire design.** Free tier is 10,000 units/day;
`liveChatMessages.list` costs 5. Polling every 5s costs 86,400/day — **8.6× over**.
So it idles at 300s (~1,440 units/day) and only sprints to 5s while someone is
actually talking, staying hot for 120s after the last message because
conversations have gaps. That buys ~2.2h of live chat a day at ~5s latency, and
an AFK stream is empty almost all of the time. `search.list` costs 100 units — 2%
of the day's budget per call — so it is only ever used to *find* a broadcast we do
not have. Pin `YOUTUBE_VIDEO_ID` and discovery stays at 1 unit.

Two things that are easy to get wrong and were:

- **The first poll returns the backlog, not what's new.** Uncorrected, every
  restart — and the watchdog does restart things — replays a pile of old messages
  and the Blob reacts to a conversation that ended an hour ago. `chat.py` takes
  the page token from the first batch and drops the messages.
- **The payload contract is `p.from` / `p.amount`, not what YouTube calls them.**
  The page reads `p.from` (not `author`) and does `Number(p.amount)` (so
  YouTube's ready-made `"$5.00"` yields NaN and the amount silently vanishes).
  Both were found by emitting an event and photographing the render: the name
  came out as the literal fallback `SOMEONE`.

The host writes the bus with the **publishable** key — verified, RLS permits it —
so the streaming box still never needs the database password.

Events land as `status='queued'` with a `release_at`, which is what makes this
work unattended: the page airs anything whose `release_at` has passed, so no HQ
browser needs to be open for a super chat to reach the Blob at 3am. With HQ's
`auto_release` off, `release_at` stays NULL and the row waits for a human —
exactly what that toggle promises.

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
# ffmpeg must still be running throughout — that is the point of the drill:
systemctl is-active blob-ffmpeg    # -> active
```

This drill only tells the truth because `blob-ffmpeg` **Wants** rather than
**Requires** `blob-chromium`. It originally required it, and `Requires=`
propagates deactivation — so `systemctl stop blob-chromium` also stopped the
encoder, and `Restart=` does not fire for a dependency-initiated stop. The
watchdog would bring the browser back while the broadcast stayed dead. Worse, it
was inconsistent: systemd does not propagate *restarts*, so the watchdog's own
`systemctl restart` never tripped it — only the manual drill did, which is the
one place you would conclude everything was fine.

## Music

**Source: YouTube's own Audio Library** (`studio.youtube.com` → Audio Library).
Decided 2026-07-17, and it is the only part of this that is not a preference.

Royalty-free is **not** Content-ID-proof, and "licensed" does not mean
"unclaimed" — they are unrelated facts. The concrete case: a Pixabay synthwave
track was picked for this stream, and its own page carries both

    Free for use under the Pixabay Content License
    Content ID Registered

at the same time. The licence grants the right to use it; Content ID claims it
anyway. Pixabay added that badge because users kept getting claimed on tracks
they were licensed to use.

On a **live** stream a claim is not a revenue footnote — it can mute or interrupt
the broadcast in real time. And nothing here would catch it: the page beats,
ffmpeg holds ≥1.0x, RTMP is connected, HOST is green, and YouTube has silently
muted you. It is the watchdog's exact failure shape in a dimension we do not
measure. **If you ever add claim detection, it needs the YouTube Data API and
OAuth — there is no way to see a claim from this host.**

YouTube does not Content-ID-claim its own library. That removes the risk rather
than reducing it, which is why it wins over "a Pixabay track without the badge".

Two things to watch when picking:

- Some Audio Library tracks **require attribution** (marked with an icon); most
  do not. Prefer the ones that do not, or the credit has to live in the stream
  description forever.
- Grab **8–12**. `stream.sh` builds a concat playlist and loops the **playlist**,
  not a track: one 2–3 minute loop repeats ~500x/day and the AFK audience is
  precisely the one that notices.

`loudnorm` is applied across the set, without which volume jumps between tracks —
the most amateur-sounding defect a music-bed stream can have.

The Audio Library ships MP3. That is fine for the encode path (ffmpeg decodes to
PCM and encodes AAC either way, so converting first buys no quality) but **loop
points are worth checking**: MP3 carries encoder delay and padding, and a gap at
the seam repeats ~500x/day. Verify with `silencedetect` over a couple of loops
rather than assuming; convert to WAV if a seam shows.

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

Verified on a dev machine since, without a VM:

- `agent.py`'s **encoder parser**, against synthetic progress files. It was
  broken: each ffmpeg block *ends* with `progress=continue`, so splitting on that
  marker and taking the last chunk yielded the bare word `continue` and no keys
  at all — a healthy 1.01x stream reported `speed=0` / `down`, permanently. Now
  reads the tail and lets the last occurrence of each key win. Confirmed against
  healthy, degraded, mid-write and 600KB-file cases.
- `chromium.sh`'s URL guards, all four combinations of the two params.

The `requestAnimationFrame` question is **narrower than it looks**: there is no
`requestAnimationFrame` anywhere in `stream.js`, `blob.js` or `stream_bg.js` —
zero call sites. The page already assumes the animation clock is dead, because it
is: `stream.css` and `stream.js` both record that CSS animations never advance in
Streamlit's iframe, which is why the Blob, the starfield, the meter and the
arcade hit were all moved onto `setInterval`. The virtual display therefore
introduces no *new* failure mode — the remaining risk is only whether
`setInterval` itself gets throttled, which the flags in `chromium.sh` target.
Confirm by eye over VNC: **if the Blob is breathing and the starfield is
drifting, the timers are running and you are fine.** The 8 surviving `@keyframes`
are decorative and are already inert in a normal browser today.
