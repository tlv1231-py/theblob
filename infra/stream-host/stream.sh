#!/usr/bin/env bash
# ffmpeg: grab the virtual display, mix the music bed, push to YouTube RTMP.
#
# Assumes Xvfb is already up on $DISPLAY and Chromium is already rendering onto
# it — see blob-xvfb.service and blob-chromium.service. This unit only encodes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -r, NOT -f — see the same guard in chromium.sh. This runs as `blob` and .env is
# root:root 0600, so -f passes (stat works) and the source then dies on
# permissions, which set -e turns into a restart loop. YOUTUBE_KEY still arrives:
# systemd reads EnvironmentFile= as root before dropping privileges.
# shellcheck source=/dev/null
[[ -r "$HERE/.env" ]] && source "$HERE/.env"

: "${YOUTUBE_KEY:?YOUTUBE_KEY missing — put it in infra/stream-host/.env}"
DISPLAY_NUM="${DISPLAY_NUM:-:99}"
MUSIC_DIR="${MUSIC_DIR:-$HERE/music}"
PROGRESS="${FFMPEG_PROGRESS:-/run/blob-stream/progress}"
RTMP="rtmp://a.rtmp.youtube.com/live2/${YOUTUBE_KEY}"

mkdir -p "$(dirname "$PROGRESS")"
: > "$PROGRESS"

# ── Music playlist ────────────────────────────────────────────────────────────
# A concat playlist, not one track. A single 3-minute loop repeats ~480x/day and
# the AFK audience is precisely the one that notices. -stream_loop -1 loops the
# PLAYLIST, so the rotation only repeats once every N tracks.
PLAYLIST="/run/blob-stream/playlist.txt"

# Build the playlist FIRST, then decide based on whether it actually has tracks.
# The old order asked `compgen -G "$MUSIC_DIR/*"` — true for ANY file, including
# a README or a stray .gitkeep — and only then filtered by extension. A music dir
# holding one non-audio file therefore produced an EMPTY playlist that ffmpeg was
# still told to read, which fails instantly and lands the unit in a restart loop.
: > "$PLAYLIST"
shopt -s nullglob nocaseglob
for f in "$MUSIC_DIR"/*.{wav,flac,mp3,m4a}; do
  # concat's parser treats ' as a quote. A track called "Don't Stop.wav" would
  # otherwise truncate the playlist at that line.
  printf "file '%s'\n" "${f//\'/\'\\\'\'}" >> "$PLAYLIST"
done
shopt -u nullglob nocaseglob

if [[ -s "$PLAYLIST" ]]; then
  AUDIO_IN=(-f concat -safe 0 -stream_loop -1 -i "$PLAYLIST")
  # NO runtime loudnorm. The tracks are normalised OFFLINE to -16 LUFS by
  # normalize-music.sh, which is both better and cheaper:
  #
  #   * Better — offline level-matching by measured integrated loudness is exact
  #     and static. Runtime single-pass `loudnorm` is a DYNAMIC processor: pointed
  #     at already-normalised audio it has nothing to correct but still gates and
  #     adjusts over a ~3s window, which can PUMP on transients. It would degrade
  #     the very consistency the offline pass established. (Measured: the 8-track
  #     bed spanned -9.0 to -14.4 LUFS raw; offline it is dead flat at -16.0.)
  #   * Cheaper — one less filter on 4 ARM cores whose binding constraint is
  #     holding `speed` >= 1.0x.
  #   * Gapless — normalize-music.sh outputs WAV, so decoding drops MP3 encoder
  #     padding and the concat seams are sample-accurate. loudnorm never fixed
  #     that anyway.
  #
  # The invariant this assumes: everything in MUSIC_DIR is already normalised.
  # Drop raw files in and re-run normalize-music.sh; do NOT copy unprocessed
  # tracks straight into MUSIC_DIR.
  AUDIO_FILTER=()
  echo "[stream] music: $(wc -l < "$PLAYLIST") pre-normalised track(s) from $MUSIC_DIR"
else
  # Silence rather than no audio track at all. YouTube flags streams with no
  # audio stream as unhealthy, and a missing track is harder to notice than a
  # quiet one.
  AUDIO_IN=(-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100)
  AUDIO_FILTER=()
  echo "[stream] WARNING: no music in $MUSIC_DIR — streaming silence"
fi

# ── Encode ────────────────────────────────────────────────────────────────────
# 1080x1920 EXACTLY. The page renders a fixed 1080x1920 stage and letterboxes via
# CSS transform; at exactly this size the scale resolves to 1 and the pixel art
# is unresampled. Any other size softens the whole 8-bit look.
#
# -r 20 / ultrafast / 4500k. The FIRST real broadcast saturated all 4 cores
# during events (measured: 34% idle -> 100% at an event burst, load 4.38) and the
# Blob stuttered — the render, starved of CPU, could not paint new frames while
# ffmpeg captured the same one 24x/s. `speed` stayed 1.0x throughout, so every
# metric read green while the picture lagged.
#
# preset superfast, NOT ultrafast, and NOT veryfast:
#
#  * ultrafast forces CAVLC (no CABAC), which yields H.264 BASELINE profile.
#    YouTube's live "Preparing stream" step wants Main/High and hangs on Baseline
#    — the exact failure seen: ingest "Excellent", preview stuck on "Preparing"
#    forever, never offering Go Live. superfast is the FASTEST preset that keeps
#    CABAC, so it produces High profile and YouTube goes live on it.
#  * veryfast is the known-good profile too, but heavier: it does full motion
#    estimation, so a high-motion event frame costs far more than a static one and
#    that spike is what saturated the box on the first broadcast. superfast does
#    far less ME, keeping the event-time encode cost down, while staying CABAC.
#
# So superfast is the sweet spot: YouTube-compatible profile AND light. Kept from
# the ultrafast attempt: nothing — this is a different lever.
#
# framerate STAYS 24. A first attempt at 20 to shave CPU also hung "Preparing":
# 20 is not one of YouTube's accepted live rates (24/25/30/48/50/60). Two separate
# ways to hang the prep step, found the hard way; both are avoided here.
#
# -g 48 = 2s keyframe interval at 24fps, which is what YouTube wants for live.
#
# -draw_mouse 0 IS NOT COSMETIC. x11grab draws the pointer by default, and X
# parks it dead centre of the screen (540,960) — which on a 1080x1920 stage is
# exactly the Blob's face. Nobody will ever move it, because nobody is going to
# touch a headless browser, so without this an arrow sits on his forehead for the
# entire life of the stream. Caught by screenshotting the framebuffer; every
# health signal reads green through it.
exec ffmpeg -hide_banner -loglevel warning \
  -f x11grab -framerate 24 -video_size 1080x1920 -draw_mouse 0 -i "${DISPLAY_NUM}.0+0,0" \
  "${AUDIO_IN[@]}" \
  "${AUDIO_FILTER[@]}" \
  -c:v libx264 -preset superfast -tune zerolatency -profile:v high -pix_fmt yuv420p \
  -b:v 4500k -maxrate 4500k -bufsize 9000k \
  -g 48 -keyint_min 48 -sc_threshold 0 \
  -c:a aac -b:a 128k -ar 44100 -ac 2 \
  `# -progress feeds agent.py, which is the ONLY thing that surfaces speed.` \
  `# -stats_period throttles it to one block per 5s: the default is 0.5s, and` \
  `# this file is append-only for the life of the stream on tmpfs — i.e. in RAM.` \
  `# At the default cadence an uninterrupted week costs well over a gigabyte of` \
  `# memory to report a number that changes slowly.` \
  -stats_period 5 \
  -progress "$PROGRESS" \
  -f flv "$RTMP"
