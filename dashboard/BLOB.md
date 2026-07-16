# THE BLOB — design contract

The character autonomously piloting the autotrader. Cute, funny, cyberpunk.

**Read this before editing `blob.js`.** The rules below are deliberate choices,
not accidents of implementation. Several of them look like bugs or missed
optimizations if you don't know why they're there. Breaking any of them is a
design decision, not a cleanup — make it on purpose.

| File | Purpose |
|---|---|
| `dashboard/blob.js` | The character. Self-contained, no deps, no assets. |
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

## Mood taxonomy

Transient moods take a duration in ticks and decay back to `IDLE`.

| Mood | Reads as | Should map to | Wired? |
|---|---|---|---|
| `IDLE` | breathing, occasional blink | flat / normal | — |
| `HAPPY` | bounce, `^^` eyes, sparks | up day | no |
| `SCARED` | squish, jitter, sweat, wide eyes | approaching drawdown limit | no |
| `ALERT` | pop, `!`, cyan | a fill just landed | no |
| `SLEEP` | flat, `z`, dimmed | market closed | no |
| `SMUG` | half-lidded, smirk | strong close | no |

`SMUG` currently maps to nothing real — it exists because a smug blob after a
good close felt right. Kept deliberately; formalize or cut it, don't leave it
ambiguous.

Continuous PnL is applied *underneath* whatever mood is active, so he reacts to
magnitude and category at the same time.

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
