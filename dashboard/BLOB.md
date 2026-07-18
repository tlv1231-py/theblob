# THE BLOB — design contract

The character autonomously piloting the autotrader. Cute, funny, cyberpunk.

**Read this before editing `blob.js`.** The rules below are deliberate choices,
not accidents of implementation. Several of them look like bugs or missed
optimizations if you don't know why they're there. Breaking any of them is a
design decision, not a cleanup — make it on purpose.

## STATUS — sprite-driven, EYES-ONLY (2026-07-17; supersedes the procedural sections below)

The body and face are now **hand-authored sprite sheets** (`blob_body.png` +
`blob_eyes.png`), not computed procedurally. `blob.js` blits them. The current
design is **eyes-only**: a small pink circle, one tasteful line mouth, and
cartoonishly large over-the-top eyes that carry every mood. **No arm, no fangs,
no tongue, no brows, no particles** — the eyes do all the expressing (which is
what "Rules of the character → eyes carry the comedy" always said). The earlier
googly-slime pass (fangs/tongue/arm) was a step on the way; the eyes-only face is
the one that shipped.

The sections below are kept as **design history** and remain the reference for
the constraints that make him read as 8-bit — **low logical resolution, locked
palette, 10fps** all still hold — but the original arguments were overridden on
purpose:

- **"Why procedural and not sprite sheets" is reversed.** The art is a fixed look
  now, and continuous PnL is **bucketed into the mood rows** — the cost this file
  warned about. Accepted, eyes open.
- **Shading is cel + a couple of gloss dots, not Bayer dither.** The **always-pink
  rule and the locked 10-colour palette still hold** — MID is still the bulk of
  him in every mood.
- **Moods are 9, not 7.** Order (row index, non-negotiable): `IDLE HAPPY SCARED
  ALERT SLEEP SMUG BRACE EXASPERATED HOPEFUL`. **IDLE is the confident-dumb-guy
  face and is the DEFAULT.** `EXASPERATED` (row 7) is the loss reaction — a
  dead-eyed up-roll; `HOPEFUL` (row 8) is the fresh-pickup "gonna win" face,
  looking up at the tile. Ambient P&L no longer drives SCARED (it read the buggy
  NAV series); SCARED is now only the transient reaction to a real `risk_breach`.
- **Eye occlusion is deliberate order.** The pupil + glints are drawn BEFORE the
  eyelid so a rolled-up pupil tucks UNDER the lid — drawing the lid last was the
  fix for "his pupils go through his eyelids". Keep that order in the generator.
- **One accessory survives the no-particles rule: the dono sunglasses.** On a
  donation, `blob.cool(durTicks)` drops deal-with-it shades from overhead onto a
  smirk, holds, then lifts them off — an accessory ON him, not a separate mark.

What did **not** change: the engine still applies bob, jitter, the eyes-only
glance, the travelling blink, and the outer bloom (`onAccent`); the public API is
byte-identical — so "The beat" and most of "Rules of the character" below still
hold. Regenerate the art with `scripts/gen_blobby_eyes.py`, then re-embed it into
blob.js (as base64 data URIs) with `scripts/embed_blob_sheets.py`.

| File | Purpose |
|---|---|
| `dashboard/blob.js` | The character. No deps; the two sheets are inlined as base64 data URIs. |
| `dashboard/blob_body.png` / `blob_eyes.png` | The sprite sheets — 48×48 cells, 4 breath × 8 mood / 3 lid × 8 mood. |
| `scripts/gen_blobby_eyes.py` / `embed_blob_sheets.py` | Regenerate the sheets, then re-embed them into blob.js. |
| `dashboard/blob_preview.html` | Standalone harness — look at him without Streamlit or the DB. |
| `dashboard/home_nav.js` | Where he gets wired to live state (not yet done). |

---

## Why procedural and not sprite sheets

The original plan was to draw a set of pixel-art PNGs and tween between them.
Rejected, because **sprite frames encode a fixed number of discrete states but
the trader's state is continuous.** PnL, drawdown, exposure and signal strength
are real numbers. Sprites force you to bucket them, and "+0.4%" vs "+1.9%"
either needs separate art or collapses to the same frame. Every new mood becomes
an art task plus another binary asset to inline into the page.

Procedural instead: his shape is a function of live state. `squish = f(pnl)`,
`jitter = f(volatility)`, `eyes = f(signal)`. Infinite frames, one text file.

Load-bearing side effect: **a text file is also the only thing that hands off
cleanly** — between sessions, in git, in review. Binary sprite assets don't.

## The three constraints that make it read as 8-bit

The look does not come from the file format. It comes from these, and it
survives only as long as all three hold:

1. **Low logical resolution.** Canvas is 48×48 actual pixels, scaled up by CSS
   with `image-rendering: pixelated` and `ctx.imageSmoothingEnabled = false`.
   Never render at display resolution.
2. **Locked palette.** Five body colours, ramped. Sourced from the dashboard's
   existing cyberpunk palette so he doesn't look bolted on.
   **Known deviation:** the body ramp is properly quantized, but the rim-accent
   blend is a smooth lerp, so ~32% of his opaque pixels are off-ramp
   intermediates (measured: 501 pure / 238 off, idle frame). A purist would
   quantize the rim to the ramp too. It currently reads fine because the
   intermediates are all pink-adjacent and confined to the rim — but if he ever
   looks subtly "too modern" and you can't say why, this is the first suspect.
3. **Quantized framerate.** `setInterval` at **10fps**, not `requestAnimationFrame`.
   *This is the one that matters most and the one most likely to get
   "fixed" by someone.* Same code at 60fps instantly reads as a modern web toy
   instead of an arcade cabinet. If you want to see it, raise FPS and look.
   Related: his position snaps to whole pixels (`Math.round` on `bob`, `look`,
   `cx`). Subpixel motion breaks the illusion the same way.

## Rules of the character

- **He is always pink.** `#ff00cc` is his identity. Mood reads through shape,
  eyes, FX and the **rim-light accent** — never a body-colour swap. A blob that
  turns fully green on a good day has stopped being The Blob.
- **Dither, don't gradient.** Shading is quantized to the 5-colour ramp with a
  4×4 Bayer matrix. The stippled banding is the single most period-correct
  detail in the whole thing. Do not replace it with a smooth gradient.
- **The aliasing is the aesthetic.** His silhouette is three sine harmonics
  sampled against the pixel grid. The jaggies are the point. Do not anti-alias.
- **Eyes carry the comedy.** ~90% of personality is in the eyes and the
  specular glint. Spend detail budget there before anywhere else.
- **Brows are the opinion.** An eye is a shape; a brow is a *stance*. Anger is
  not a rounder eye, it is a brow driven down and in. Before they existed every
  mood had to be carried by swapping the whole eye for a preset, which made the
  eye do a job that was never its own. `BROWS` in `blob.js` is the table.
  - `tilt` drives the **inner** end: `+` down (anger, focus), `-` up (worry).
    Inner is the right end of the left brow and the left end of the right brow,
    so the right brow takes the **negated** slope and starts where the left one
    ended. Mirroring the *number*, not the geometry, is what keeps them reading
    as one pair rather than two independent marks.
  - **They do not track `look`.** Brows sit on the head, not the eyeball. The
    eye sliding *under* a held brow is most of what makes a glance read as one.
  - **Drawn after the eyes, and allowed to overlap them.** That overlap is what
    a scowl *is* — `BRACE`'s brow descends as a wedge into the narrowed eye, and
    the glint is what keeps the eye legible inside the mass. Verified, not
    assumed: it reads as a scowl and not a blob.
  - `SMUG` lifts **only the right brow**. A symmetric smirk is just a face; the
    asymmetry *is* the smugness, and it costs one number.
- **Two glints, not one.** The key sits upper-left (matching `LX`/`LY`); a
  dimmer `HI` bounce sits lower-right. One glint reads as a dot painted *on* the
  eye, two read as light wrapping a sphere. The bounce is `HI` and not `WHT` on
  purpose — a second full white competes with the key and flattens both.
- **The blink travels.** Three ticks: half, shut, half. It used to hard-cut from
  a full eye to a 1px line, which at 10fps reads as the eye *vanishing* for two
  frames rather than as a blink. At this framerate those in-between frames are
  the only ones a blink has.

## Mood taxonomy

Transient moods take a duration in ticks and decay back to `IDLE`.

| Mood | Reads as | Should map to | Wired? |
|---|---|---|---|
| `IDLE` | breathing, occasional blink | flat / normal | yes |
| `HAPPY` | bounce, `^^` eyes, sparks | a winning exit | yes |
| `SCARED` | squish, jitter, sweat, wide eyes | approaching drawdown limit | yes |
| `ALERT` | pop, `!`, cyan | a fill just landed | yes |
| `SLEEP` | flat, `z`, dimmed | the *system* is idle (not market hours) | yes |
| `SMUG` | half-lidded, smirk | day P&L above +1% | yes |
| `BRACE` | crouch, squat wide, narrowed eyes, held still | **the ~500ms before a trade lands** | yes |

`SMUG` is now formalized: it fires from `syncBlobMood` when day P&L is above +1%.

`BRACE` is the anticipation beat and the reason the rest reads as a performance
rather than a twitch. It is the OPPOSITE deformation to HAPPY/ALERT — he
compresses so the impact has something to release. Its bob is nearly killed:
holding still is what makes the wind-up read as held breath. Eyes narrow rather
than widen, because wide eyes here would read as SCARED — the wind-up is focus,
not fear.

Continuous PnL is applied *underneath* whatever mood is active, so he reacts to
magnitude and category at the same time.

## The beat (stream.js)

A trade is not one moment, it is three:

```
PRE 500ms (BRACE + glance)  ->  EVENT (sound + tile + score)  ->  POST 800ms  ->  gap 300ms
```

1.6s per trade, played one at a time from a queue. The verdict mood set at the
impact IS the follow-through, so its duration is derived from `POST_TICKS` — not
a constant. Set it shorter and he snaps to idle while the beat is still running.

**`BRACE` must stay in `syncBlobMood`'s protected list.** That function runs
every 1000ms and the wind-up is only 500ms, so without the guard roughly half of
every anticipation would be overwritten with IDLE mid-crouch.

## Wiring plan (not yet done)

Streamlit is not involved and must not be. Streamlit reruns the whole Python
script per interaction — animating from Python would mean one DB-querying rerun
per frame. `home_nav.js` already sidesteps this: it runs inside a single
`components.html` iframe with its own polling. **The Blob is another canvas in
that iframe.** Streamlit serves the shell once and never learns he exists.

Everything he needs already exists in `home_nav.js`:

| Hook (already present) | Drives |
|---|---|
| `window._onLiveTrade` | `setMood('ALERT', 12)` on a fill |
| `_fetchNavDb` poll (10s) | `setPnl(pct)` continuously |
| `window._navTradeMarkers` | glance toward newest entry |
| market-closed check | `SLEEP` |
| risk / drawdown state | `SCARED` |

## Open design questions

- **Visor vs bare eyes.** The visor sells "he is piloting the thing" and the
  sweep reads as scanning the market, but it costs the eyes — where the comedy
  lives. Possible middle: visor during market hours, eyes when idle or asleep.
- **Silhouette.** Currently a fairly clean lit sphere-blob. The reference art
  was a lumpier, more asymmetric egg. Lumpier is uglier and funnier, less
  mascot-logo.
- **Placement.** Centrepiece on Home, or a persistent ~64px guy in the corner of
  the nav chart reacting while the line moves? Changes how much detail is worth
  rendering at all.
