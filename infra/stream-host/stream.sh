#!/usr/bin/env bash
# ffmpeg: grab the virtual display, mix the music bed, push to YouTube RTMP.
#
# Assumes Xvfb is already up on $DISPLAY and Chromium is already rendering onto
# it — see blob-xvfb.service and blob-chromium.service. This unit only encodes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
[[ -f "$HERE/.env" ]] && source "$HERE/.env"

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
if compgen -G "$MUSIC_DIR/*" > /dev/null; then
  : > "$PLAYLIST"
  for f in "$MUSIC_DIR"/*.{wav,flac,mp3,m4a}; do
    [[ -e "$f" ]] && printf "file '%s'\n" "$f" >> "$PLAYLIST"
  done
  AUDIO_IN=(-f concat -safe 0 -stream_loop -1 -i "$PLAYLIST")
  # loudnorm: without it, volume jumps between tracks — the single most
  # amateur-sounding defect a music-bed stream can have.
  AUDIO_FILTER=(-af "loudnorm=I=-16:TP=-1.5:LRA=11")
  echo "[stream] music: $(wc -l < "$PLAYLIST") track(s) from $MUSIC_DIR"
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
# -r 24 / veryfast / 4500k: this is a mostly-static pixel-art scene on 4 free ARM
# cores. The binding constraint is keeping `speed` >= 1.0x — below that ffmpeg
# encodes slower than real time and YouTube buffers. Raise fps/bitrate only after
# watching the agent's reported speed hold.
#
# -g 48 = 2s keyframe interval at 24fps, which is what YouTube wants for live.
exec ffmpeg -hide_banner -loglevel warning \
  -f x11grab -framerate 24 -video_size 1080x1920 -i "${DISPLAY_NUM}.0+0,0" \
  "${AUDIO_IN[@]}" \
  "${AUDIO_FILTER[@]}" \
  -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p \
  -b:v 4500k -maxrate 4500k -bufsize 9000k \
  -g 48 -keyint_min 48 -sc_threshold 0 \
  -c:a aac -b:a 128k -ar 44100 -ac 2 \
  -shortest_buf_duration 0 \
  -progress "$PROGRESS" \
  -f flv "$RTMP"
