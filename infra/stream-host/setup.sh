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

command -v apt-get >/dev/null 2>&1 || {
  echo "This installer is apt-based (Debian/Ubuntu). On the EL family you would" >&2
  echo "need EPEL for chromium and RPM Fusion for ffmpeg — not wired up here." >&2
  exit 1
}

echo "==> packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
  xvfb ffmpeg python3 x11vnc fonts-dejavu-core ca-certificates curl fontconfig

# ── Fonts are a dependency, not a download ───────────────────────────────────
# The page asks fonts.googleapis.com for Press Start 2P and VT323 at load time.
# Neither is packaged in apt, and without them present fc-match resolves BOTH to
# DejaVu Sans — not even a monospace. So a Google Fonts blip during a watchdog
# reload renders the entire pixel-art stream in generic sans, and not one health
# signal notices: the page still beats, ffmpeg still holds speed, RTMP stays
# connected, every light stays green.
#
# Installing them locally demotes that fetch from dependency to optimisation.
# Both are SIL Open Font License, which explicitly permits redistribution; the
# licences are installed alongside them.
#
# Verified by blackholing fonts.googleapis.com in /etc/hosts and confirming the
# render came back pixel-identical.
echo "==> fonts (local fallback for Press Start 2P / VT323)"
FONTDIR=/usr/local/share/fonts/blob
if [[ -f "$FONTDIR/PressStart2P-Regular.ttf" && -f "$FONTDIR/VT323-Regular.ttf" ]]; then
  echo "    already installed"
else
  mkdir -p "$FONTDIR"
  GF=https://raw.githubusercontent.com/google/fonts/main
  curl -fsSL -o "$FONTDIR/PressStart2P-Regular.ttf" "$GF/ofl/pressstart2p/PressStart2P-Regular.ttf"
  curl -fsSL -o "$FONTDIR/VT323-Regular.ttf"        "$GF/ofl/vt323/VT323-Regular.ttf"
  curl -fsSL -o "$FONTDIR/OFL-PressStart2P.txt"     "$GF/ofl/pressstart2p/OFL.txt"
  curl -fsSL -o "$FONTDIR/OFL-VT323.txt"            "$GF/ofl/vt323/OFL.txt"
  fc-cache -f >/dev/null 2>&1
  echo "    installed to $FONTDIR"
fi
fc-match 'Press Start 2P' | grep -q PressStart2P \
  || echo "    !! Press Start 2P does not resolve — the stream will render in DejaVu"
fc-match 'VT323' | grep -q VT323 \
  || echo "    !! VT323 does not resolve — the stream will render in DejaVu"

# ── Chromium is not an apt package on Ubuntu ─────────────────────────────────
# Verified on the host: `apt-cache policy chromium` returns Candidate: (none) —
# that package name does not exist. Ubuntu ships `chromium-browser`, a
# transitional deb (2:1snap1-0ubuntu2) whose entire job is to install the SNAP,
# and Google publishes no Chrome for linux-arm64 at all. On an Ampere box the
# snap is genuinely the only option, so install it directly rather than
# laundering it through a transitional package that just calls snap anyway.
echo "==> chromium (snap — the only option on Ubuntu/arm64)"
if snap list chromium >/dev/null 2>&1; then
  echo "    chromium snap already installed"
else
  snap install chromium
fi

# Fail here, at install time, rather than at 3am inside a restart loop.
if [[ -x /snap/bin/chromium ]]; then CHROMIUM_FOUND=/snap/bin/chromium
elif command -v chromium >/dev/null 2>&1; then CHROMIUM_FOUND=$(command -v chromium)
elif command -v chromium-browser >/dev/null 2>&1; then CHROMIUM_FOUND=$(command -v chromium-browser)
else
  echo "!! no chromium binary after install. Try by hand: snap install chromium" >&2
  exit 1
fi
echo "    chromium binary: $CHROMIUM_FOUND"

# ── The unprivileged user the browser runs as ────────────────────────────────
# Not cosmetic. Chromium refuses to run as root outright, and on Ubuntu the snap
# may only touch its own user's $HOME — which is why the profile lives in
# /home/blob and not /run. A real home dir is therefore required, not optional.
echo "==> user"
if id blob >/dev/null 2>&1; then
  echo "    user 'blob' already exists"
else
  useradd --system --create-home --home-dir /home/blob --shell /usr/sbin/nologin blob
  echo "    created user 'blob' (home /home/blob)"
fi
install -d -o blob -g blob -m 755 /home/blob/chrome-profile

# Linger is required, not hygiene. `snap run` asks systemd over D-Bus to create
# a transient tracking scope for itself, and a system user that never logs in
# has no session, no /run/user/<uid>, and no bus to ask. Chromium then refuses:
#
#   ... is not a snap cgroup for tag snap.chromium.chromium
#
# Linger makes logind maintain a user manager and /run/user/<uid> for blob across
# reboots, with no login. chromium.sh points XDG_RUNTIME_DIR at it.
loginctl enable-linger blob
echo "    linger enabled for 'blob' (snap needs the session bus)"

echo "==> install to $DEST"
mkdir -p "$DEST/music"
install -m 755 "$HERE/chromium.sh" "$HERE/stream.sh" "$HERE/normalize-music.sh" "$DEST/"
install -m 755 "$HERE/agent.py" "$HERE/watchdog.py" "$HERE/switch.py" "$HERE/chat.py" "$DEST/"

# Stays root:root 0600 on purpose. systemd reads EnvironmentFile= as root before
# it drops to the 'blob' user, so the services still get YOUTUBE_KEY while the
# browser's own user cannot read the credential that owns your channel.
if [[ ! -f "$DEST/.env" ]]; then
  install -m 600 "$HERE/.env.example" "$DEST/.env"
  echo
  echo "  !! $DEST/.env created from the example."
  echo "  !! Put your YouTube stream key in it before starting:"
  echo "  !!     nano $DEST/.env"
  echo
else
  # Merge in any keys the example has gained since this .env was written.
  #
  # "Never overwrite .env" is right — it holds YOUTUBE_KEY. But left at that, the
  # example grows a key, every existing host silently never receives it, and the
  # failure is invisible: a script quietly falls back to a default, or dies on a
  # variable that is demonstrably "in the example". Exactly what happened with
  # YOUTUBE_API_KEY, which sat in .env.example while chat.py idled on the host for
  # want of it.
  #
  # Only missing KEYS are appended. Existing values are never touched, so your
  # stream key and anything you have tuned survive untouched.
  added=0
  while IFS= read -r line; do
    [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]] || continue
    k="${BASH_REMATCH[1]}"
    grep -q "^${k}=" "$DEST/.env" && continue
    if [[ $added -eq 0 ]]; then
      printf '\n# ── merged from .env.example by setup.sh ──\n' >> "$DEST/.env"
    fi
    printf '%s\n' "$line" >> "$DEST/.env"
    added=$((added + 1))
    echo "    + $k"
  done < "$HERE/.env.example"
  if [[ $added -gt 0 ]]; then
    echo "    .env kept; merged $added new key(s) — fill in any blanks"
  else
    echo "    .env already has every key from the example"
  fi
fi

echo "==> systemd units"
install -m 644 "$HERE"/systemd/*.service /etc/systemd/system/
systemctl daemon-reload

echo "==> enable"
# blob-ffmpeg is enabled but NOT started by the switch's design — blob-switch
# owns whether the encoder runs, driven by the button on Stream HQ.
systemctl enable blob-xvfb blob-chromium blob-ffmpeg blob-agent blob-watchdog blob-switch blob-chat

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

  4. Start the RENDER and look at it before you broadcast it:
       systemctl start blob-xvfb blob-chromium
       x11vnc -display :99 -localhost -nopw -once &
       #   then from your machine:  ssh -L 5900:localhost:5900 <host>
       #   and point a VNC client at localhost:5900
       #
       #   Confirm with your eyes: is the Blob BREATHING and the starfield
       #   DRIFTING? Everything on the page rides setInterval, so motion means
       #   the timers survived the virtual display. A perfect still frame is the
       #   one failure that looks identical to success from every other angle.

     Then start the broadcast:
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
