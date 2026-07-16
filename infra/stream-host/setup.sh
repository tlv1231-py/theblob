#!/usr/bin/env bash
# Bootstrap the streaming host. Run ON the VM as root, from this directory.
#
#   sudo ./setup.sh
#
# Idempotent — safe to re-run after editing scripts.
set -euo pipefail

DEST=/opt/blob-stream
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "run as root: sudo ./setup.sh" >&2; exit 1; }

echo "==> packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
  xvfb chromium ffmpeg python3 x11vnc fonts-dejavu-core ca-certificates

echo "==> install to $DEST"
mkdir -p "$DEST/music"
install -m 755 "$HERE/chromium.sh" "$HERE/stream.sh" "$DEST/"
install -m 755 "$HERE/agent.py" "$HERE/watchdog.py" "$DEST/"

if [[ ! -f "$DEST/.env" ]]; then
  install -m 600 "$HERE/.env.example" "$DEST/.env"
  echo
  echo "  !! $DEST/.env created from the example."
  echo "  !! Put your YouTube stream key in it before starting:"
  echo "  !!     nano $DEST/.env"
  echo
else
  echo "    .env already exists — left untouched"
fi

echo "==> systemd units"
install -m 644 "$HERE"/systemd/*.service /etc/systemd/system/
systemctl daemon-reload

echo "==> enable"
systemctl enable blob-xvfb blob-chromium blob-ffmpeg blob-agent blob-watchdog

cat <<'EOF'

Installed. Before starting, do these IN ORDER — each step proves the one before:

  1. Put your YouTube stream key in /opt/blob-stream/.env

  2. PROVE RTMP WORKS FIRST, with a test pattern and no browser involved.
     If RTMP is broken you want to know now, not while also debugging Xvfb:

       source /opt/blob-stream/.env
       ffmpeg -re -f lavfi -i testsrc2=size=1080x1920:rate=24 \
              -f lavfi -i sine=frequency=440 \
              -c:v libx264 -preset veryfast -b:v 4500k -pix_fmt yuv420p -g 48 \
              -c:a aac -b:a 128k -ar 44100 \
              -f flv "rtmp://a.rtmp.youtube.com/live2/$YOUTUBE_KEY"

     Watch YouTube Studio. You should see colour bars and hear a tone.
     Ctrl-C when confirmed.

  3. Drop 8-12 licensed tracks (WAV/FLAC preferred) in /opt/blob-stream/music
     One 3-minute loop repeats ~480x/day — the AFK audience is exactly the one
     that notices.

  4. Start the stack:
       systemctl start blob-xvfb blob-chromium
       # look at it before you broadcast it:
       x11vnc -display :99 -localhost -nopw -once &
       #   then from your machine:  ssh -L 5900:localhost:5900 <host>
       #   and point a VNC client at localhost:5900
       systemctl start blob-ffmpeg blob-agent blob-watchdog

  5. Confirm on the Stream HQ page: ENCODER and HOST should turn green.
     If they stay BLACK, the agent is not reaching Supabase:
       journalctl -u blob-agent -f

  6. Confirm the stream is not silent — the single easiest thing to get
     silently wrong:
       journalctl -u blob-watchdog -f
     It prints the page's own audio state each poll. It must say audio=on.
     audio=blocked means Chromium's --autoplay-policy flag is not taking.

  7. Watch `speed` in the agent log. It MUST hold >= 1.0x. Below that ffmpeg
     encodes slower than real time and YouTube buffers for viewers:
       journalctl -u blob-agent -f

EOF
