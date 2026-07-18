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

# So ffmpeg (and pactl below) find blob's PulseAudio — the browser's SFX play
# into blob_sink and we capture blob_sink.monitor. Same runtime dir the browser
# and blob-pulse use.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# The two faders' STARTING values. The browser's WebAudio SFX come out quiet
# (peaks ~-18..-36 dB) against music normalised to -16 LUFS, so SFX get a boost
# and the music sits back as a bed. These are just the launch defaults now —
# faders.py adjusts them LIVE over ZMQ from Stream HQ, no ffmpeg restart (the
# volume filters below are NAMED, and azmq brokers commands to them by name).
MUSIC_VOL="${MUSIC_VOL:-0.6}"
SFX_VOL="${SFX_VOL:-2.0}"

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
  AUDIO_IN=(-thread_queue_size 1024 -f concat -safe 0 -stream_loop -1 -i "$PLAYLIST")
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
  echo "[stream] WARNING: no music in $MUSIC_DIR — streaming silence"
fi

# ── Browser SFX (input 2) + mix ─────────────────────────────────────────────
# The page synthesises its 8-bit sound in WebAudio; Chromium plays it into
# blob_sink (blob-pulse.service) and we capture blob_sink.monitor here, mixing it
# with the music bed. music = input 1, SFX = input 2, video = input 0.
#
# GRACEFUL: if pulse or the sink is not up, fall back to music-only rather than
# failing the whole encode. The stream ran without SFX its entire life before
# this; a missing sink must never be what takes the broadcast down.
SFX_IN=(); FILTER=(); MAP=(-map 0:v -map 1:a)
if pactl list sinks short 2>/dev/null | grep -qw blob_sink; then
  SFX_IN=(-thread_queue_size 1024 -f pulse -i blob_sink.monitor)
  # Named volume filters (volume@mvol / volume@svol) so faders.py can retarget
  # them live via the azmq broker on 127.0.0.1:$ZMQ_PORT. amix normalize=0 keeps
  # the sum from being auto-halved; the limiter catches any peak the boost pushes
  # over. azmq sits inline (it passes audio through, only listening for commands).
  # azmq with NO bind_address uses its default tcp://*:5555 — deliberately, to
  # dodge filtergraph escaping (a bind_address URL's colons need escaping that does
  # not survive the shell -> ffmpeg -> filtergraph chain cleanly). Binding all
  # interfaces is not an exposure here: Oracle's security list blocks every inbound
  # port, and faders.py reaches it over localhost. Port 5555 is azmq's default.
  FILTER=(-filter_complex \
    "[1:a]volume@mvol=${MUSIC_VOL}[m];[2:a]volume@svol=${SFX_VOL}[s];[m][s]amix=inputs=2:duration=first:normalize=0,azmq,alimiter=limit=0.95[aout]")
  MAP=(-map 0:v -map "[aout]")
  echo "[stream] SFX: mixing blob_sink.monitor (music ${MUSIC_VOL} / sfx ${SFX_VOL})"
else
  echo "[stream] SFX: blob_sink not found — music only (browser sound absent)"
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
# preset ultrafast + cabac=1 — the one combination that is BOTH cheap AND
# YouTube-compatible. The road here, all found on real broadcasts:
#
#  * veryfast went live but its full motion estimation ballooned on high-motion
#    event frames, saturating all 4 cores and stuttering the Blob.
#  * ultrafast is far cheaper — it does almost no ME, so its cost is nearly FLAT
#    across static and event frames — BUT it forces CAVLC, yielding H.264
#    BASELINE profile, and YouTube's "Preparing stream" step hangs on Baseline
#    forever (ingest reads "Excellent", the preview never goes live).
#  * superfast keeps CABAC (=> Main/High, YouTube-happy) but does real ME again,
#    so it ate ~1.9 of its 2 pinned cores and re-starved the render on spikes.
#
# The fix: keep ultrafast's cheap ME and just switch CABAC back ON explicitly.
# `-x264-params cabac=1` turns the profile Baseline -> MAIN (verified with
# ffprobe), which YouTube accepts, while the motion estimation stays ultrafast-
# cheap and FLAT through activity spikes — which is the whole point, since the
# spikes were the lag. -profile:v main makes it explicit.
#
# framerate STAYS 24. 20 also hangs "Preparing" — it is not one of YouTube's
# accepted live rates (24/25/30/48/50/60). -g 48 = 2s keyframe interval at 24.
#
# -draw_mouse 0 IS NOT COSMETIC. x11grab draws the pointer by default, and X
# parks it dead centre of the screen (540,960) — which on a 1080x1920 stage is
# exactly the Blob's face. Nobody will ever move it, because nobody is going to
# touch a headless browser, so without this an arrow sits on his forehead for the
# entire life of the stream. Caught by screenshotting the framebuffer; every
# health signal reads green through it.
# -thread_queue_size on EVERY input. ffmpeg's default is 8 packets, and the
# journal showed BOTH x11grab and pulse logging "Thread message queue blocking"
# within a second of every start: on 4 saturated ARM cores the input threads
# cannot hand off fast enough, so frames and audio arrive in bursts. That is not
# only a stutter — it ragged the A/V timeline enough that YouTube's ingest read
# "Excellent" and then sat on "Preparing stream" forever, never finalising the
# broadcast. 1024 is ~42s of video packets and costs a few MB of RAM.
exec ffmpeg -hide_banner -loglevel warning \
  -thread_queue_size 1024 \
  -f x11grab -framerate 24 -video_size 810x1440 -draw_mouse 0 -i "${DISPLAY_NUM}.0+0,0" \
  "${AUDIO_IN[@]}" \
  "${SFX_IN[@]}" \
  "${FILTER[@]}" \
  "${MAP[@]}" \
  -c:v libx264 -preset ultrafast -x264-params cabac=1 -tune zerolatency -profile:v main -pix_fmt yuv420p \
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
