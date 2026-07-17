#!/usr/bin/env bash
# Chromium, kiosked onto the virtual display, rendering the Stream page.
#
# Every flag below is load-bearing. Read the comments before removing any.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -r, NOT -f. Under systemd this runs as the unprivileged `blob` user while .env
# is deliberately root:root 0600 — it holds YOUTUBE_KEY, and a browser rendering
# a page all day has no business reading the credential that owns the channel.
# The variables are already in the environment by the time this runs: systemd
# reads EnvironmentFile= as root and then drops privileges. This source exists
# only so the script still works when run by hand.
#
# -f asks "does it exist" — and it does; blob can stat it fine because
# /opt/blob-stream is 0755. So the guard passed, the source then died with
# "Permission denied", set -e turned that into exit 1, and the unit sat in a
# restart loop. Ask whether we can READ it, which is the thing we're about to do.
# shellcheck source=/dev/null
[[ -r "$HERE/.env" ]] && source "$HERE/.env"

DISPLAY_NUM="${DISPLAY_NUM:-:99}"
export DISPLAY="$DISPLAY_NUM"

# ?yt=0 IS MANDATORY.
# The Stream page ships a temporary design overlay that draws YouTube's own
# chrome and safe zones on top of itself, and it defaults ON. Capturing the
# default URL would broadcast a mockup of YouTube inside YouTube. There is also
# a "YT FILTER" toggle on the Stream HQ page that must read OFF — the query
# param only overrides for this page load.
STREAM_URL="${STREAM_URL:?STREAM_URL missing — put it in infra/stream-host/.env}"
case "$STREAM_URL" in
  *yt=0*) ;;
  *) echo "[chromium] REFUSING TO START: STREAM_URL must contain yt=0, else the" >&2
     echo "           stream broadcasts the design overlay. Got: $STREAM_URL" >&2
     exit 1 ;;
esac

# ?live=1 IS ALSO MANDATORY.
# It marks this render as THE BROADCAST, which is what makes it ignore Stream
# HQ's mute toggle. Without it the VM's browser is just another window obeying
# that toggle: muting the noise on your own desk would silence the YouTube
# stream, and nothing would report it — the heartbeat's audio field tracks
# whether AudioContext is running, not whether the page is muted, so a muted
# broadcast still beats audio=on and the watchdog stays happy. This guard is the
# only thing in front of that failure, which is why it refuses rather than warns.
case "$STREAM_URL" in
  *live=1*) ;;
  *) echo "[chromium] REFUSING TO START: STREAM_URL must contain live=1, else the" >&2
     echo "           broadcast obeys Stream HQ's mute toggle and can go silently" >&2
     echo "           mute with no health signal. Got: $STREAM_URL" >&2
     exit 1 ;;
esac

# ── Which chromium binary? ───────────────────────────────────────────────────
# Debian and the EL family ship a native `chromium`. On Ubuntu there is no
# `chromium` package at all — only `chromium-browser`, a transitional deb that
# installs the SNAP. Google ships no Chrome for linux-arm64, so on an Ampere box
# the snap is the only option.
#
# /snap/bin/chromium is checked BY ABSOLUTE PATH on purpose. systemd gives units
# a minimal PATH (/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin)
# which does NOT include /snap/bin. So `command -v chromium` succeeds when you
# test it in an interactive login shell and fails inside the unit — the script
# works perfectly by hand and dies under systemd. Absolute path first, so the
# thing that actually runs in production is the thing that resolves.
BIN="${CHROMIUM_BIN:-}"
if [[ -z "$BIN" ]]; then
  for c in /snap/bin/chromium chromium chromium-browser; do
    command -v "$c" >/dev/null 2>&1 && { BIN="$c"; break; }
  done
fi
[[ -n "$BIN" ]] || {
  echo "[chromium] no chromium binary found (looked for: /snap/bin/chromium," >&2
  echo "           chromium, chromium-browser). Try: snap install chromium" >&2
  exit 1
}

# ── Profile location is not a preference ─────────────────────────────────────
# This used to default to /run/blob-stream/chrome, which cannot work under snap:
# the snap is confined and may only touch the calling user's $HOME. A profile
# anywhere else is refused and Chromium dies on startup. Keeping it under $HOME
# satisfies snap and native alike, so there is no detection to get wrong.
PROFILE="${CHROME_PROFILE:-${HOME:-/home/blob}/chrome-profile}"
mkdir -p "$PROFILE" || {
  echo "[chromium] cannot create profile dir $PROFILE" >&2
  echo "           Under snap it MUST live under \$HOME (\$HOME=${HOME:-unset})." >&2
  exit 1
}

# ── Sandbox / root ───────────────────────────────────────────────────────────
# Chromium hard-refuses to start as root: "Running as root without --no-sandbox
# is not supported." The units run this as the unprivileged `blob` user, which
# is the right answer anyway — a browser rendering a page 24/7 has no business
# being root, and snap will not run as root at all. If someone runs this by hand
# as root, degrade loudly instead of dying with a confusing message.
SANDBOX=()
if [[ $EUID -eq 0 ]]; then
  echo "[chromium] WARNING: running as root — adding --no-sandbox to start at all." >&2
  echo "           blob-chromium.service runs as 'blob' and does not need this." >&2
  SANDBOX=(--no-sandbox)
fi

echo "[chromium] $BIN  profile=$PROFILE  display=$DISPLAY"

exec "$BIN" \
  "${SANDBOX[@]}" \
  --user-data-dir="$PROFILE" \
  --window-position=0,0 \
  --window-size=1080,1920 \
  --kiosk \
  --start-fullscreen \
  --hide-scrollbars \
  \
  `# WITHOUT THIS THE STREAM IS SILENT. The page synthesises its 8-bit sound` \
  `# with WebAudio, and AudioContext stays suspended until a user gesture —` \
  `# which will never come, because nobody is going to click a headless` \
  `# browser. There is no error when this is missing; it just plays nothing.` \
  `# Verify via the stream_page heartbeat: detail.audio must read "on".` \
  --autoplay-policy=no-user-gesture-required \
  \
  `# A headless/offscreen page can be treated as "not visible", which stalls` \
  `# the animation clock — requestAnimationFrame stops firing and CSS` \
  `# animations report "running" while never advancing. The page was built so` \
  `# everything essential runs on setInterval (immune), but these keep the` \
  `# renderer awake regardless and cost nothing.` \
  --disable-backgrounding-occluded-windows \
  --disable-renderer-backgrounding \
  --disable-background-timer-throttling \
  --disable-features=CalculateNativeWinOcclusion \
  \
  `# Kiosk hygiene — no first-run dialogs, no infobars, no crash-restore` \
  `# bubble parked over the Blob's face after a watchdog reload.` \
  --no-first-run \
  --no-default-browser-check \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-notifications \
  --noerrdialogs \
  --check-for-update-interval=31536000 \
  \
  `# 4 free ARM cores encode this AND render it. GPU compositing off is` \
  `# usually the right trade on a VM with no GPU.` \
  --disable-gpu \
  --disable-dev-shm-usage \
  \
  "$STREAM_URL"
