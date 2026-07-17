#!/usr/bin/env python3
"""Host agent — reports the streaming stack's health to Supabase.

Runs ON the streaming host. Writes two rows to stream_health every INTERVAL:

    component='encoder'  {speed, fps, bitrate, dropped, total_frames}
    component='host'     {cpu, mem, load, uptime, disk}

This exists because Stream HQ cannot see them. ffmpeg's throughput and the VM's
CPU are physically unobservable from a Streamlit app, so HQ renders them as
BLACK/ABSENT until something on this side reports in. That was deliberate: a
health light that isn't measuring anything is worse than no light, because it
reads "fine" during exactly the outage it exists to catch.

The number that matters is `speed`. Below 1.0x, ffmpeg is encoding slower than
real time, its buffer drains, and YouTube starts stalling for viewers. It is the
earliest warning the stack gives and nothing else surfaces it.

Talks to Supabase over PostgREST with the PUBLISHABLE key on purpose — the host
never needs the database password. Read-only on everything except stream_health.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Publishable/anon key — already public in the repo (dashboard/home_nav.js).
# Safe on the host; it is not the DB password.
SUPA_URL = os.environ.get("SUPA_URL", "https://seeevuklabvhkawawtxn.supabase.co")
SUPA_KEY = os.environ.get("SUPA_KEY", "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY")

# ffmpeg -progress writes key=value lines here; see stream.sh.
PROGRESS = Path(os.environ.get("FFMPEG_PROGRESS", "/run/blob-stream/progress"))

# Only ever read this much of the tail. The file is append-only for the life of
# the stream and sits on tmpfs, so reading it whole would mean pulling an
# ever-growing blob of RAM through here every INTERVAL. A block is ~200 bytes;
# 8 KiB is dozens of blocks, far more than the one we need.
TAIL_BYTES = 8192

INTERVAL = int(os.environ.get("AGENT_INTERVAL", "30"))

# Stream HQ treats a heartbeat older than 90s as down, so report well inside it.
assert INTERVAL < 60, "INTERVAL must stay under HQ's 90s staleness window"


def post_health(component: str, status: str, detail: dict) -> bool:
    body = json.dumps({
        "component": component,
        "status": status,
        "detail": detail,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }).encode()
    req = urllib.request.Request(
        f"{SUPA_URL}/rest/v1/stream_health",
        data=body,
        method="POST",
        headers={
            "apikey": SUPA_KEY,
            "Authorization": f"Bearer {SUPA_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status < 300
    except urllib.error.HTTPError as e:
        print(f"[agent] {component} HTTP {e.code}: {e.read()[:200]!r}", flush=True)
    except Exception as e:
        print(f"[agent] {component} failed: {e}", flush=True)
    return False


# ── encoder ───────────────────────────────────────────────────────────────────

def read_encoder() -> tuple[str, dict]:
    """Parse ffmpeg's -progress file.

    ffmpeg appends a block of key=value lines every stats period and TERMINATES
    each block with `progress=continue` (or `=end`).

    That terminator is the trap. Splitting on "progress=" and taking [-1] looks
    like "the newest block" and is actually the bare word "continue" — every
    real key lives BEFORE the marker, so the parse came back empty and a healthy
    1.01x stream reported speed=0.0 -> "down", permanently. Reproduced against a
    synthetic progress file before this was rewritten.

    Instead: regex every key=value in the tail and let dict() keep the LAST
    occurrence of each, which is by definition the newest block's value.

    Read only the tail — this file grows for the life of the stream and lives on
    tmpfs, i.e. in RAM.
    """
    if not PROGRESS.exists():
        return "down", {"error": "no progress file — ffmpeg not running"}

    try:
        size = PROGRESS.stat().st_size
        with PROGRESS.open("rb") as fh:
            fh.seek(max(0, size - TAIL_BYTES))
            raw = fh.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return "unknown", {"error": str(e)[:80]}

    # dict() keeps the last occurrence of each key = the newest reported value.
    kv = dict(re.findall(r"^(\w+)=(\S+)$", raw, re.MULTILINE))
    if not kv:
        return "unknown", {"error": "no progress keys yet"}

    def f(key, default=0.0):
        try:
            return float(str(kv.get(key, default)).rstrip("x"))
        except ValueError:
            return default

    speed = f("speed")
    fps = f("fps")
    drop = int(f("drop_frames"))
    frames = int(f("frame"))
    bitrate = kv.get("bitrate", "?")

    # Staleness beats content: a progress file that stopped growing means ffmpeg
    # died without cleaning up, and its last block would otherwise look healthy
    # forever.
    age = time.time() - PROGRESS.stat().st_mtime
    if age > 20:
        return "down", {"error": f"progress stale {int(age)}s — ffmpeg stopped",
                        "speed": speed}

    detail = {"speed": round(speed, 3), "fps": round(fps, 1),
              "bitrate": bitrate, "dropped": drop, "frames": frames}

    # speed < 1.0 = encoding slower than real time = YouTube will buffer.
    if speed <= 0:
        return "down", detail
    if speed < 0.97:
        return "degraded", detail
    return "ok", detail


# ── host ──────────────────────────────────────────────────────────────────────

def read_host() -> tuple[str, dict]:
    detail: dict = {}
    status = "ok"
    try:
        load1, load5, _ = os.getloadavg()
        cores = os.cpu_count() or 1
        detail["load"] = round(load1, 2)
        detail["cores"] = cores
        # Load per core is the honest CPU figure on a shared ARM box.
        per_core = load1 / cores
        detail["cpu"] = f"{min(100, per_core * 100):.0f}%"
        if per_core > 0.9:
            status = "degraded"

        mem = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            mem[k] = int(v.strip().split()[0])
        total, avail = mem.get("MemTotal", 1), mem.get("MemAvailable", 0)
        used_pct = (1 - avail / total) * 100
        detail["mem"] = f"{used_pct:.0f}%"
        if used_pct > 92:
            status = "degraded"

        detail["uptime"] = int(float(Path("/proc/uptime").read_text().split()[0]))

        st = os.statvfs("/")
        disk_pct = (1 - st.f_bavail / st.f_blocks) * 100
        detail["disk"] = f"{disk_pct:.0f}%"
        if disk_pct > 90:
            status = "degraded"
    except Exception as e:
        return "unknown", {"error": str(e)[:80]}
    return status, detail


def main() -> None:
    print(f"[agent] reporting to {SUPA_URL} every {INTERVAL}s", flush=True)
    print(f"[agent] reading ffmpeg progress from {PROGRESS}", flush=True)
    while True:
        e_status, e_detail = read_encoder()
        h_status, h_detail = read_host()
        post_health("encoder", e_status, e_detail)
        post_health("host", h_status, h_detail)
        print(f"[agent] encoder={e_status} {e_detail}  host={h_status} {h_detail}",
              flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
