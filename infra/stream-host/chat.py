#!/usr/bin/env python3
"""YouTube live chat -> stream_events, so the Blob reacts to viewers.

One call does almost all of it. `liveChatMessages.list` returns regular chat,
super chats, super stickers, new members and gifted memberships in a single
stream — so this is one integration, not four.

WHAT YOU CANNOT HAVE
"Follows" are Twitch. YouTube has subscribers, and offers no real-time
new-subscriber event to anyone — Streamlabs and StreamElements fake sub alerts by
polling a delayed, unreliable list. Paid memberships DO fire properly and arrive
here as newSponsorEvent. Plain subs are simply not on the menu.

WHY IT RUNS HERE AND NOT IN STREAMLIT
Streamlit Community Cloud is a request-scoped web app that sleeps when no browser
holds a session. It has no process awake at 3am when someone super-chats. This VM
is already up 24/7, so the listener lives next to the switch and the watchdog.
StreamEvent's own docstring anticipated this: "the stream renders in a headless
Chromium on the streaming host, while HQ runs wherever the operator is ... this
table IS the channel."

QUOTA IS THE WHOLE DESIGN — see poll_interval().
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

SUPA_URL = os.environ.get("SUPA_URL", "https://seeevuklabvhkawawtxn.supabase.co")
SUPA_KEY = os.environ.get("SUPA_KEY", "sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY")

API = "https://www.googleapis.com/youtube/v3"
API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

# Pin the broadcast if you know it; otherwise we discover it from the channel.
VIDEO_ID = os.environ.get("YOUTUBE_VIDEO_ID", "").strip()
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()

# ── Quota ────────────────────────────────────────────────────────────────────
# The free tier is 10,000 units/day and liveChatMessages.list costs 5. Polling
# every 5s costs 86,400/day — 8.6x over. So: poll fast only while someone is
# actually talking.
#
#   idle at 300s  ->    288 polls/day  ->  1,440 units
#   leaves       ~8,000 units  ->  ~1,600 fast polls  ->  ~2.2h of live chat/day
#
# An AFK stream is empty almost all the time, so this buys ~5s reactions during
# the exact minutes a human is there to see them, and costs nearly nothing the
# rest of the day. That is the whole trick.
# The RESOURCE is liveChatMessages; the URL PATH is liveChat/messages. Getting
# that wrong returns 404 with an EMPTY BODY — no error, no reason, no hint — and
# it returns exactly the same 404 for a valid chat id as for a deliberately bogus
# one, because the path is never reached. That is indistinguishable from "this
# broadcast has no chat" and reads like an auth problem. Found by asking for a
# nonsense id and noticing the failures were identical. Same shape for
# liveChat/bans and liveChat/moderators.
PATH_CHAT = "liveChat/messages"

COST = {"liveChatMessages.list": 5, "videos.list": 1, "search.list": 100,
        "channels.list": 1, "playlistItems.list": 1}

# How often to go looking for a broadcast when we do not have one. Discovery is
# cheap now (3 units) but it is still pure overhead while the channel is dark.
DISCOVER_SECONDS = int(os.environ.get("CHAT_DISCOVER", "300"))
DAILY_BUDGET = int(os.environ.get("YT_QUOTA_BUDGET", "10000"))
POLL_FAST = int(os.environ.get("CHAT_POLL_FAST", "5"))
POLL_IDLE = int(os.environ.get("CHAT_POLL_IDLE", "300"))
# Stay hot this long after the last message — a conversation has gaps, and
# dropping to 5-minute polls between two lines of chat would feel broken.
HOT_WINDOW = int(os.environ.get("CHAT_HOT_WINDOW", "120"))

REPORT_SECONDS = 30

# YouTube's chat event kinds -> the event_type vocabulary in data/models.py
KIND_MAP = {
    "textMessageEvent":       "chat",
    "superChatEvent":         "superchat",
    "superStickerEvent":      "supersticker",
    "newSponsorEvent":        "subscription",
    "membershipGiftingEvent": "membership_gift",
    "giftMembershipReceivedEvent": "membership_gift",
}


class Quota:
    """Spend tracker. YouTube's quota resets at midnight Pacific, not UTC."""

    def __init__(self) -> None:
        self.spent = 0
        self.day = self._pt_day()

    @staticmethod
    def _pt_day():
        # Good enough without pytz: PT is UTC-7/-8, and we only need the date to
        # roll at roughly the right time. Being an hour off across a DST boundary
        # costs one early or late reset, once a year.
        return (datetime.now(timezone.utc) - timedelta(hours=8)).date()

    def charge(self, method: str) -> None:
        if self._pt_day() != self.day:
            print(f"[chat] quota day rolled — spent {self.spent} yesterday", flush=True)
            self.spent = 0
            self.day = self._pt_day()
        self.spent += COST.get(method, 1)

    @property
    def exhausted(self) -> bool:
        return self.spent >= DAILY_BUDGET * 0.9


def api(method: str, path: str, quota: Quota, **params) -> dict:
    params["key"] = API_KEY
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    quota.charge(method)
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


# ── Finding the broadcast ────────────────────────────────────────────────────

def discover_video(quota: Quota) -> str | None:
    """The channel's currently-live video, WITHOUT search.list.

    search.list is the obvious way to do this and it costs 100 units — 1% of the
    entire day per call. Asking "are we live yet?" every 5 minutes while the
    channel is dark would cost 28,800 units/day against a 10,000 budget: the
    quota would be gone before lunch, every day, having read no chat at all.

    This route costs 3, by walking the channel's own uploads instead — a live
    broadcast is a video in that playlist like any other:

        channels.list      (1)  -> the uploads playlist id
        playlistItems.list (1)  -> the most recent uploads
        videos.list        (1)  -> which of those is live right now

    3 units per check at 300s is 864/day. Affordable. 100 was not.
    """
    try:
        r = api("channels.list", "channels", quota, part="contentDetails", id=CHANNEL_ID)
        items = r.get("items") or []
        if not items:
            print(f"[chat] channel {CHANNEL_ID} not found", flush=True)
            return None
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        r = api("playlistItems.list", "playlistItems", quota, part="contentDetails",
                playlistId=uploads, maxResults=5)
        ids = [i["contentDetails"]["videoId"] for i in (r.get("items") or [])]
        if not ids:
            return None

        # One call for all of them — videos.list takes a comma-separated id list
        # and still costs 1 unit.
        #
        # Match "live" OR "upcoming". YouTube opens the chat during the
        # pre-show (broadcast state "upcoming") before ffmpeg ever connects, and
        # that waiting-room chat is real engagement — confirmed against the
        # actual channel, where a message typed pre-live flowed all the way to
        # the Blob. Prefer a truly-live broadcast if both exist; fall back to an
        # upcoming one with an open chat.
        # .get() throughout — a video in the uploads list can come back without a
        # snippet (private, deleted, still processing), and indexing it["snippet"]
        # directly crashed the whole listener on one bad item. Every other lookup
        # in this file already guards this way; this line did not.
        live_id = upcoming_id = None
        for it in r.get("items") or []:
            state = (it.get("snippet") or {}).get("liveBroadcastContent")
            if state == "live":
                live_id = it.get("id")
            elif state == "upcoming":
                upcoming_id = it.get("id")
        return live_id or upcoming_id
    except urllib.error.HTTPError as e:
        print(f"[chat] discovery failed: {e.code} {e.read()[:160]!r}", flush=True)
    return None


def resolve_chat_id(quota: Quota) -> tuple[str | None, str | None]:
    """(liveChatId, videoId).

    Pinning YOUTUBE_VIDEO_ID keeps this at 1 unit and is worth doing: a 24/7
    broadcast reusing one stream key keeps the same video id, so there is usually
    nothing to discover.
    """
    vid = VIDEO_ID or (discover_video(quota) if CHANNEL_ID else None)
    if not vid:
        if not VIDEO_ID and not CHANNEL_ID:
            print("[chat] no YOUTUBE_VIDEO_ID and no YOUTUBE_CHANNEL_ID — nothing to watch",
                  flush=True)
        return None, None

    try:
        r = api("videos.list", "videos", quota, part="liveStreamingDetails", id=vid)
    except urllib.error.HTTPError as e:
        print(f"[chat] videos.list failed: {e.code} {e.read()[:160]!r}", flush=True)
        return None, vid
    items = r.get("items") or []
    if not items:
        return None, vid
    chat_id = (items[0].get("liveStreamingDetails") or {}).get("activeLiveChatId")
    return chat_id, vid


# ── Policy (shared with the START/STOP switch) ───────────────────────────────

def hold_policy() -> tuple[bool, int]:
    """(auto_release, hold_seconds) from the same strategy_params HQ writes."""
    url = (f"{SUPA_URL}/rest/v1/strategy_params"
           "?strategy=eq.stream&param=in.(auto_release,default_hold_s)&select=param,value")
    req = urllib.request.Request(url, headers={
        "apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            rows = json.loads(r.read())
    except Exception:
        return True, 5                      # sensible default; never block on a blip
    pol = {r["param"]: r["value"] for r in rows}
    return pol.get("auto_release", "1") == "1", int(pol.get("default_hold_s", "5") or 5)


def emit(event_type: str, payload: dict) -> bool:
    """Write one event onto the bus.

    status='queued' with a release_at is what makes this work unattended: the
    page airs anything whose release_at has passed, so no HQ browser needs to be
    open for a viewer's super chat to reach the Blob at 3am. With auto_release
    off, release_at stays NULL and the row waits for a human — which is exactly
    what that toggle promises.
    """
    auto, hold = hold_policy()
    now = datetime.now(timezone.utc)
    body = {
        "event_type": event_type,
        "source": "youtube",
        "payload": payload,
        "status": "queued",
        "release_at": (now + timedelta(seconds=hold)).isoformat() if auto else None,
        "created_at": now.isoformat(),
    }
    req = urllib.request.Request(
        f"{SUPA_URL}/rest/v1/stream_events", data=json.dumps(body).encode(),
        method="POST",
        headers={"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
        return True
    except Exception as e:
        print(f"[chat] emit {event_type} failed: {e}", flush=True)
        return False


def _dollars(micros) -> float | None:
    """amountMicros -> a NUMBER. Not a display string.

    The page does `Number(p.amount).toFixed(2)` and prefixes '$' itself, so
    handing it YouTube's ready-made "$5.00" yields NaN and the amount silently
    vanishes from the popup. Send the number; the page owns the formatting.
    """
    try:
        return round(int(micros) / 1_000_000, 2)
    except (TypeError, ValueError):
        return None


def to_event(item: dict) -> tuple[str, dict] | None:
    """Map a YouTube chat item onto the payload shape stream.js actually reads.

    The contract is `p.from`, `p.amount`, `p.count`, `p.viewers` — NOT the names
    YouTube uses, and not the ones that felt natural. Verified by emitting an
    event and photographing the render: `author` came out as the literal fallback
    "SOMEONE", and "$5.00" came out as nothing at all.
    """
    sn = item.get("snippet") or {}
    author = (item.get("authorDetails") or {}).get("displayName", "someone")
    kind = sn.get("type")
    et = KIND_MAP.get(kind)
    if not et:
        return None

    # `from` is what the popup reads for the name; everything else here is extra
    # context that costs nothing to carry and may be worth having later.
    payload: dict = {"from": author, "kind": kind}

    if kind == "textMessageEvent":
        payload["text"] = (sn.get("textMessageDetails") or {}).get("messageText", "")
    elif kind == "superChatEvent":
        d = sn.get("superChatDetails") or {}
        payload.update(text=d.get("userComment", ""),
                       amount=_dollars(d.get("amountMicros")),
                       amount_display=d.get("amountDisplayString"),
                       currency=d.get("currency"))
    elif kind == "superStickerEvent":
        d = sn.get("superStickerDetails") or {}
        payload.update(amount=_dollars(d.get("amountMicros")),
                       amount_display=d.get("amountDisplayString"),
                       currency=d.get("currency"))
    elif kind == "newSponsorEvent":
        payload["tier"] = (sn.get("newSponsorDetails") or {}).get("memberLevelName")
    elif kind in ("membershipGiftingEvent", "giftMembershipReceivedEvent"):
        d = sn.get("membershipGiftingDetails") or {}
        payload["count"] = d.get("giftMembershipsCount")
    return et, payload


def post_health(status: str, detail: dict) -> None:
    body = json.dumps({"component": "chat", "status": status, "detail": detail,
                       "recorded_at": datetime.now(timezone.utc).isoformat()}).encode()
    req = urllib.request.Request(
        f"{SUPA_URL}/rest/v1/stream_health", data=body, method="POST",
        headers={"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except Exception:
        pass


def main() -> None:
    if not API_KEY:
        # Idle, do NOT exit. Restart=always would turn a missing key into a crash
        # loop that fills the journal forever and drowns real errors. Report
        # degraded instead and say why — an unconfigured listener should look
        # unconfigured on Stream HQ, not dead, and not absent.
        print("[chat] YOUTUBE_API_KEY missing — idling. Add it to "
              "/opt/blob-stream/.env and: systemctl restart blob-chat", flush=True)
        while True:
            post_health("degraded", {"reason": "YOUTUBE_API_KEY not set — viewer "
                                               "events are not being read"})
            time.sleep(300)

    quota = Quota()
    chat_id: str | None = None
    video_id: str | None = None
    page: str | None = None
    last_msg = 0.0
    last_report = 0.0
    seeded = False          # see the backlog note below

    print(f"[chat] budget {DAILY_BUDGET}/day  fast {POLL_FAST}s  idle {POLL_IDLE}s",
          flush=True)

    while True:
        # FIRST, before anything spends. This used to sit below the discovery
        # branch, which meant a dark channel looped through resolve_chat_id
        # forever and never once reached the guard meant to stop it.
        #
        # Never blow the free quota. Going over costs no money — it returns 403
        # quotaExceeded and the listener is simply deaf until midnight Pacific,
        # which is worse than being slow.
        if quota.exhausted:
            print(f"[chat] quota {quota.spent}/{DAILY_BUDGET} — idling", flush=True)
            post_health("degraded", {"reason": "daily quota nearly spent",
                                     "quota_spent": quota.spent})
            time.sleep(POLL_IDLE)
            continue

        if not chat_id:
            chat_id, video_id = resolve_chat_id(quota)
            if not chat_id:
                print(f"[chat] no active broadcast — retry in {DISCOVER_SECONDS}s "
                      f"(quota {quota.spent}/{DAILY_BUDGET})", flush=True)
                post_health("degraded", {"reason": "no active broadcast",
                                         "quota_spent": quota.spent})
                time.sleep(DISCOVER_SECONDS)
                continue
            print(f"[chat] watching video={video_id} chat={chat_id[:24]}...", flush=True)
            page, seeded = None, False

        try:
            params = dict(part="snippet,authorDetails", liveChatId=chat_id, maxResults=200)
            if page:
                params["pageToken"] = page
            r = api("liveChatMessages.list", PATH_CHAT, quota, **params)
        except urllib.error.HTTPError as e:
            raw = e.read()[:200].decode(errors="ignore")
            print(f"[chat] poll failed: {e.code} {raw}", flush=True)
            # 403/404 usually means the broadcast ended or the chat id went stale.
            if e.code in (403, 404):
                chat_id = None
            post_health("down", {"error": f"{e.code}", "detail": raw[:120]})
            time.sleep(POLL_IDLE)
            continue
        except Exception as e:
            print(f"[chat] poll error: {e}", flush=True)
            time.sleep(POLL_FAST)
            continue

        page = r.get("nextPageToken")
        items = r.get("items") or []

        if not seeded:
            # DISCARD THE FIRST BATCH. A cold liveChat/messages returns the
            # chat's recent backlog, not just what is new — so every restart
            # (and the watchdog does restart things) would replay a pile of old
            # messages and the Blob would react to a conversation that finished
            # an hour ago. Measured against a real broadcast: 75 of them. Take
            # the page token, drop the messages.
            seeded = True
            print(f"[chat] seeded past {len(items)} backlog message(s)", flush=True)
            items = []
            # Start HOT, do not fall straight to a 5-minute sleep. last_msg=0.0
            # means (now - last_msg) is ~1.7e9, which is never < HOT_WINDOW — so
            # a freshly started listener seeded the backlog and then went deaf for
            # five minutes, on a chat with a message every few seconds. Anyone
            # talking at startup got silence. Being attentive for the first
            # HOT_WINDOW costs ~24 polls (120 units) per restart and buys the
            # thing the listener exists for.
            last_msg = time.time()

        for it in items:
            mapped = to_event(it)
            if not mapped:
                continue
            et, payload = mapped
            if emit(et, payload):
                # 'from', not 'author' — the payload key was renamed to match what
                # stream.js reads, and this log kept asking for the old one and
                # printing None against every message it correctly delivered.
                who = payload.get("from")
                extra = payload.get("amount") or payload.get("text", "")[:40]
                print(f"[chat] {et} <- {who} {extra!r}", flush=True)

        if items:
            last_msg = time.time()

        now = time.time()
        if now - last_report >= REPORT_SECONDS:
            post_health("ok", {
                "video": video_id,
                "quota_spent": quota.spent,
                "quota_budget": DAILY_BUDGET,
                "hot": (now - last_msg) < HOT_WINDOW,
            })
            last_report = now

        hot = (now - last_msg) < HOT_WINDOW
        time.sleep(POLL_FAST if hot else POLL_IDLE)


if __name__ == "__main__":
    main()
