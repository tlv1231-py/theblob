#!/usr/bin/env bash
# Level-match music to a common loudness and install it, gapless, for the stream.
#
#   sudo ./normalize-music.sh <source-dir> [dest-dir]
#   sudo ./normalize-music.sh /tmp/incoming            # -> /opt/blob-stream/music
#
# WHY THIS EXISTS, AND WHY stream.sh NO LONGER NORMALISES AT RUNTIME
# A music bed's most amateur defect is volume lurching between tracks. The 8-track
# debut bed spanned -9.0 to -14.4 LUFS raw — a 5.4 dB jump. stream.sh used to fix
# this with a runtime `loudnorm` filter, but that is a dynamic processor: it pumps
# on transients and, pointed at already-even audio, degrades the consistency it is
# meant to create. Doing it ONCE, offline, statically, is both better and cheaper
# (one less filter on the 4 cores that also encode).
#
# METHOD: measure each track's integrated loudness, apply the exact linear gain to
# land it on the target, and cap true peak with a limiter as a safety for any
# track that needs BOOSTING (a limiter never engages on attenuation, which is the
# common case for mastered library tracks). Output is lossless WAV, so decoding
# also drops MP3 encoder-delay padding and the concat seams come out
# sample-accurate — the loop no longer clicks.
set -euo pipefail

SRC="${1:?usage: normalize-music.sh <source-dir> [dest-dir]}"
DEST="${2:-/opt/blob-stream/music}"
TARGET_LUFS="${TARGET_LUFS:--16}"      # -16 LUFS: comfortable for a music bed
TARGET_TP="${TARGET_TP:--1.5}"         # true-peak ceiling, dBFS

[[ -d "$SRC" ]] || { echo "no such source dir: $SRC" >&2; exit 1; }
mkdir -p "$DEST"

# -1.5 dBTP as a linear alimiter ceiling: 10^(dB/20).
LIMIT=$(awk -v tp="$TARGET_TP" 'BEGIN{printf "%.4f", 10 ^ (tp/20)}')

shopt -s nullglob nocaseglob
found=0
for f in "$SRC"/*.{mp3,wav,flac,m4a,ogg,opus}; do
  [[ -e "$f" ]] || continue
  found=$((found+1))
  base="$(basename "${f%.*}")"

  # Measure integrated loudness.
  m=$(ffmpeg -i "$f" -af ebur128 -f null - 2>&1 \
      | grep -A1 "Integrated loudness" | grep -oP "I:\s*\K-?[0-9.]+" | tail -1)
  if [[ -z "$m" ]]; then
    echo "  !! could not measure loudness of $base — skipped" >&2
    continue
  fi

  gain=$(awk -v m="$m" -v t="$TARGET_LUFS" 'BEGIN{printf "%.2f", t - m}')
  ffmpeg -hide_banner -loglevel error -y -i "$f" \
    -af "volume=${gain}dB,alimiter=limit=${LIMIT}" \
    -ar 44100 -ac 2 -c:a pcm_s16le "$DEST/${base}.wav"
  printf "  %-42s %6s LUFS  %+sdB -> %s.wav\n" "$base" "$m" "$gain" "$base"
done
shopt -u nullglob nocaseglob

[[ $found -gt 0 ]] || { echo "no audio files in $SRC" >&2; exit 1; }

# Let blob read them, same as the rest of MUSIC_DIR.
if id blob >/dev/null 2>&1; then
  chown blob:blob "$DEST"/*.wav 2>/dev/null || true
fi

echo
echo "done — $found track(s) normalised to ${TARGET_LUFS} LUFS in $DEST"
echo "verify:  for f in \"$DEST\"/*.wav; do ffmpeg -i \"\$f\" -af ebur128 -f null - 2>&1 | grep -A1 'Integrated' | tail -1; done"
