#!/usr/bin/env bash
# Chromium, kiosked onto the virtual display, rendering the Stream page.
#
# Every flag below is load-bearing. Read the comments before removing any.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
[[ -f "$HERE/.env" ]] && source "$HERE/.env"

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

PROFILE="${CHROME_PROFILE:-/run/blob-stream/chrome}"
mkdir -p "$PROFILE"

exec chromium \
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
