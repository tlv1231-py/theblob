#!/usr/bin/env bash
# Make the host actually RUN what the repo says.
#
# WHY THIS EXISTS
# The units run /opt/blob-stream/*, which are COPIES of infra/stream-host/*.
# Nothing keeps them in sync, so the repo being correct tells you nothing about
# what is broadcasting. This bit real time: a YouTube "Preparing stream" hang was
# chased for hours on the theory that the host had stale code, and toggling ON
# AIR "to pick up the fix" cannot possibly work — the switch runs `systemctl
# restart`, which re-executes the same stale copy. Only a copy changes anything.
#
# Run this after every push. It is the missing step.
#
#   ./deploy.sh            # pull + copy + daemon-reload, restart NOTHING
#   ./deploy.sh --restart  # ...and restart the render chain (drops the picture
#                          #    for ~90s: Xvfb -> Chromium -> Streamlit cold start)
#
# Restarting is opt-in ON PURPOSE. A deploy must never silently drop a live
# broadcast; you should choose that moment.
set -euo pipefail

REPO="${REPO:-/home/ubuntu/theblob}"
DEST="${DEST:-/opt/blob-stream}"
SRC="$REPO/infra/stream-host"

[[ -d "$SRC" ]] || { echo "no $SRC — set REPO=/path/to/checkout"; exit 1; }

echo "[deploy] repo $REPO"
git -C "$REPO" pull --ff-only
echo "[deploy] now at: $(git -C "$REPO" log --oneline -1)"

# NOTE: .env is deliberately NOT touched. It holds YOUTUBE_KEY and
# STREAMLABS_TOKEN, is root:root 0600, and is gitignored — there is nothing in
# the repo to copy over it, and clobbering it would take the stream off air.
echo "[deploy] scripts -> $DEST"
sudo install -m 755 -o root -g root "$SRC"/*.sh "$DEST"/
sudo install -m 755 -o root -g root "$SRC"/*.py "$DEST"/

echo "[deploy] units -> /etc/systemd/system"
sudo install -m 644 -o root -g root "$SRC"/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Listeners are cheap to bounce and carry no picture, so they always restart —
# leaving them on old code is how you get a listener that silently stopped
# matching the schema it writes.
for u in blob-agent blob-switch blob-chat blob-faders blob-streamlabs; do
  if systemctl is-enabled "$u" >/dev/null 2>&1; then
    sudo systemctl restart "$u" 2>/dev/null || true
    echo "[deploy] restarted $u ($(systemctl is-active "$u"))"
  fi
done

if [[ "${1:-}" == "--restart" ]]; then
  echo "[deploy] restarting the render chain — picture drops for ~90s"
  sudo systemctl restart blob-xvfb;    sleep 5
  sudo systemctl restart blob-chromium; sleep 8
  sudo systemctl restart blob-ffmpeg
  echo "[deploy] xvfb=$(systemctl is-active blob-xvfb) chromium=$(systemctl is-active blob-chromium) ffmpeg=$(systemctl is-active blob-ffmpeg)"
else
  echo "[deploy] render chain NOT restarted."
  echo "[deploy]   dashboard/ changes  -> sudo systemctl restart blob-chromium"
  echo "[deploy]   stream.sh changes   -> sudo systemctl restart blob-ffmpeg"
  echo "[deploy]   resolution changes  -> ./deploy.sh --restart (all three)"
fi

echo "[deploy] done."
