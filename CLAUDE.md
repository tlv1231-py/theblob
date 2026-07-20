# CLAUDE.md — Project Instructions for Claude Code

## What This Project Is

A quantitative market research and paper trading platform.
This is NOT a trading bot. It is a research and simulation system.

Current phase: **Phase 3 — Paper Trading (active)**
Current milestone: **20-trading-day monitoring period — Day 1 of 20 complete**
No real money. No auto-execution.

---

## Maintaining This File

After completing any milestone or phase, update:
- The V0 Milestone checklist below (check off completed items)
- The "Current phase" and "Current milestone" status lines above
- The "What NOT To Build Yet" section if scope has expanded
- The strategy registry section if a new strategy was added or promoted
- After every completed task or bug fix, update CLAUDE.md to reflect current state — mark completed items, add new known bugs if discovered, update Edge Enhancements status as features move from research → validated → production. This file is the source of truth for every Claude Code session.

Do NOT rewrite architectural rules, coding standards, or directory responsibilities without explicit human instruction.

---

## End Goal

Build a set-and-forget passive income machine that generates reliable, risk-adjusted returns superior to parking money in a HYSA or SPY index fund.

This requires, in order:
1. Validated signals with proven edge across multiple market regimes
2. A market regime filter that reduces exposure automatically in deteriorating conditions
3. Automated daily scheduling (no manual pipeline runs)
4. Cloud hosting (not dependent on local machine)
5. Failure alerting (Discord or email if pipeline fails or risk limits breach)
6. Streamlit dashboard with parameter tinkering and backtest visualization
7. Small real-money execution with human approval on every trade
8. Semi-automated execution with a proven live track record

The system is not "done" until it runs unattended, protects capital in bad markets, and compounds reliably over time.

**Long-term architectural goal — Ensemble Allocation (multi-model meta-strategy):**
Run multiple independent strategies sorted by risk profile (e.g. low / medium / high), each with
its own signals, positions, and PnL history. A master allocator watches rolling Sharpe and
drawdown across models in real time and shifts capital toward outperformers, away from
underperformers. This captures regime transitions automatically without binary on/off filters.

Prerequisites before building:
- 2+ validated strategies with independent backtests and live track records (6+ months each)
- Current architecture already supports this — `strategy` column exists on all tables,
  registry tracks multiple strategies, capital events table is broker-agnostic
- Do NOT build until single-strategy live trading is proven and stable

---

## Non-Negotiable Architecture Rules

1. **Never overwrite historical market data.** Append only. Timestamped snapshots always.
2. **No look-ahead bias.** Signals must only use data available at decision time.
3. **Risk logic lives in /risk only.** Never embed risk or sizing logic inside models or signals.
4. **Execution is modular.** The broker adapter is swappable. Never hardcode broker logic outside /execution.
5. **One source of truth for market calendar.** Always use `/ingestion/calendar.py`. Never reimplement trading hours or holiday logic elsewhere.
6. **All strategies must be registered** in `/registry/strategy_registry.yaml` with a status field: `research | backtest | paper | live`.
7. **All experiments must be logged** with hypothesis, parameters, result, and date — either to the DB experiment table or `/experiments/results`.
8. **Data validation runs at ingestion.** Data must pass validation before entering the pipeline.
9. **Pydantic schemas** must be defined in `/data/schemas` for all core data structures.
10. **Every trade decision must be logged.** Nothing executes (even on paper) without a DB record.

---

## Directory Responsibilities

| Directory | Purpose |
|---|---|
| `/config` | Global settings, risk limits, strategy params |
| `/registry` | Strategy manifest and loader |
| `/data/schemas` | Pydantic data models |
| `/ingestion` | Data fetching, validation, calendar utility |
| `/features` | Feature engineering only — no signals here |
| `/models` | Strategy logic only — no risk/sizing here |
| `/signals` | Signal generation and routing |
| `/portfolio` | Position sizing, allocation, correlation |
| `/risk` | All risk controls — centralized |
| `/execution` | Paper and live executors, order queue, broker adapters |
| `/tracking` | PnL, Sharpe, drawdown, analytics |
| `/experiments` | Experiment logging and stored results |
| `/tests` | pytest tests — required for all core modules |

---

## Known Bugs — OPEN

- **`nav_snapshots` has no account column — NAV history splices two books.**
  Table is `(id, recorded_at, nav)` only, and is written *client-side* from
  `home_nav.js`, which switches Alpaca wallets via `localStorage._alpacaActiveIdx`.
  Whichever wallet is active in whatever browser is open appends to one series.
  Observed 2026-07-16: a −$59,527 discontinuity between 07-12T16:44 and 07-16T00:20
  (daily last: 06-17 $104,654 → 07-12 $89,721 → 07-16 $25,526). **This is not
  performance** — `pnl.cumulative_pnl` for momentum is only −$1,211.89 over the same
  window. Any % return computed against the $100k model baseline off this series is
  fiction (renders as ~−72%). Blocks livestreaming until fixed: the Stream page would
  broadcast a loss that never happened.

- ~~`positions_data.entry_price` is 0 for all positions~~ **— FIXED, verified
  2026-07-18.** See Known Fixes Applied below. Do not re-chase this.

- **Two books are presented as one.** `_load_chart_data()` returns Alpaca account NAV
  (~$25k, mostly cash, crypto fills in the feed) alongside momentum paper-model
  positions (~$96k gross across 5 equities). The Command Center gets away with this
  because each HUD tile is separately labelled; any view that composes them into a
  single narrative (like Stream) will misrepresent. Decide which book a display
  surface represents before shipping it.

## Known Fixes Applied

- **`entry_price` = 0 / every position reading +0.00% — FIXED (verified
  2026-07-18).** The entry lookup in `home._load_chart_data()` queried
  `WHERE side = 'BUY'`, but `fills.side` is stored **lowercase** and in two
  vocabularies — `buy`/`sell` for equity, `entry`/`exit` for crypto (measured:
  36,926 `entry`, 36,651 `exit`, 13 `buy`, 8 `sell`). The uppercase compare
  matched zero rows, silently, so `entry_price` fell to 0 and both the Command
  Center and the Stream page showed +0.00% on every position. The query is now
  `WHERE LOWER(side) IN ('buy','entry')`. Verified against live data: all five
  held positions resolve (AMD 518.61, CAT 888.56, GOOGL 390.52, INTC 121.01,
  NUE 249.01), and no fill row has a null/zero `fill_price`.
  **Known remaining wrinkle, not the same bug:** the lookup takes
  `DISTINCT ON (symbol) ... ORDER BY filled_at ASC`, i.e. the EARLIEST entry
  ever. For the equity book (1 fill/symbol) that is correct. For a crypto symbol
  that rolls thousands of times it would return the first entry in history
  rather than the current position's — harmless today because the positions
  panel is fed from the momentum equity snapshot, but wrong the moment crypto
  positions render through this path.

- **np.float64 casting:** yfinance returns `np.float64` values. These must be cast to Python `float` before SQLAlchemy passes them to psycopg2. Apply at ingestion boundary.
- **Price lookup:** Use latest available date per symbol, not `date == today`. Intraday data is not available from yfinance.
- **OHLCV high≥low validator:** Pydantic v2 `@field_validator("high")` runs before `low` is validated. Must use `@model_validator(mode="after")` instead.
- **MomentumSignalGenerator params:** Now loads from `config/strategy_params/momentum.yaml` on init. Constructor kwargs override yaml values. Do not pass hardcoded params from run_pipeline.py.
- **MAX_POSITION_SIZE:** Updated to 0.20 (20%) to match top-5 equal-weight configuration (5 × 20% = 100% gross exposure).

- **Stream dono board — repeat donors merge, don't stack (2026-07-17):** a second
  dono from a name already orbiting was opening a second row (board showed the
  same donor twice). `puAddOne` in `stream.js` now folds it into the existing
  entry — money and minutes add ($1:1min), `puSince` preserved so it keeps its
  slot; legacy stacked rows fold into the survivor; idempotency extended to
  merged donos via a `seen` id list.

- **Stream sun — bands off (2026-07-17):** the thin horizontal lines across the
  sun were unwanted. `SUN_SLIT_MIN/MAX = 0` in `stream_bg.js` makes `banded`
  always false → clean glowing disc. Restore the vaporwave banding with MIN 1 /
  MAX 4. The global `#scanlines` CRT overlay still crosses the sun, far fainter.

- **Blob mood wiring — confident default, expressive verdict (2026-07-17):**
  `syncBlobMood` no longer drives SCARED off day-P&L (it read the buggy NAV
  series and left him near-permanently scared); SCARED is now only the transient
  reaction to a real `risk_breach` event. Post-trade verdict: win → HAPPY
  (stoked), **loss → EXASPERATED** (new row-7 mood), enter → ALERT; BRACE is
  still the pre-trade wind-up. Also fixed a latent runtime bug: SMUG forced the
  half-lid column on top of its already-heavy-lidded art, rendering it nearly
  shut — `baseLid` is now `SLEEP ? 2 : 0` since each mood's resting lid is baked
  into its col-0 eye.

- **Blob reactions + sunglasses + eye occlusion (2026-07-17):** enter →
  **HOPEFUL** (row-8, looks up at the fresh pickup); a donation drops **deal-with-it
  sunglasses** onto a smirk (`blob.cool()`, `coolUntil` holds the pose past
  `syncBlobMood`'s 1s tick). Eye pupils are now drawn BEFORE the lid so a
  rolled-up pupil tucks under it (fixed "pupils through eyelids" on EXASPERATED).

- **Stream background live control (2026-07-17):** Stream HQ gained a **BG
  ON/OFF toggle + opacity fader** (`bg_enabled` / `bg_opacity` in
  `strategy_params`, default 68 = the tuned `#bgCanvas` opacity). stream.js polls
  ~2s and EASES the opacity in JS (CSS transitions are inert in the component
  iframe); when faded fully off it stops the 24fps `stream_bg` loop, so OFF is a
  real toggle, not an invisible canvas still rendering.

- **Blob "hi-bit" FX layer (2026-07-17):** the crisp pixel sprite now gets SMOOTH
  wrapping FX in `blob.js` — squash-and-stretch spring bounce on mood landings,
  a mood-coloured neon `drop-shadow` bloom, a chromatic-aberration punch on big
  hits, and a gloss sweep. Runs on a separate ~30fps `fxLoop` (element-level
  `transform`/`filter`, capture-safe; CSS transitions would freeze). Impacts fire
  from `setMood`/`cool`, so no upstream change; `opts.fx=false` disables it. Tune
  with `MOOD_GLOW`/`MOOD_KICK`. Not yet eyeballed on a real capture — the headless
  screenshot pane can't settle on the continuous filter updates.

---

## What Has Been Built (V0)

54 files across the full architecture. All V0 milestone items confirmed working.

| Module | Key files |
|---|---|
| Config | `config/settings.py`, `risk_limits.py`, `strategy_params/momentum.yaml`, `universe.py` (94 symbols, all 11 GICS sectors), `enhancement_queue.yaml` (source of truth for queued edge enhancements) |
| Registry | `registry/strategy_registry.yaml`, `registry.py`, `universe_manifest.json` (symbol metadata, sectors, history length, avg volume) |
| Schemas | `data/schemas/` — OHLCV, Signal, Order, Fill, ExperimentLog (Pydantic v2) |
| Database | `data/database.py`, `data/models.py` (7 ORM tables), `data/migrate.py` |
| Ingestion | `ingestion/calendar.py` (NYSE), `validators.py`, `market_data/yfinance_fetcher.py` |
| Features | `features/momentum/price_momentum.py` — Jegadeesh-Titman 12-1 momentum |
| Signals | `signals/momentum_signals.py`, `base_signal.py`, `router.py` |
| Risk | `risk/risk_engine.py` — position sizing, drawdown halts, exposure limits |
| Execution | `execution/broker_adapter.py` (abstract), `paper_executor.py` (5bps slippage) |
| Tracking | `tracking/analytics.py` (CAGR/Sharpe/Sortino/drawdown), `pnl.py`, `alerts.py` |
| Experiments | `experiments/experiment_log.py` |
| Tests | 4 test files: validators, calendar, analytics, schemas |
| Entry point | `run_pipeline.py` — full daily loop |

---

## Current V0 Milestone

- [x] PostgreSQL schema created and migrated (PostgreSQL 17, `tnd` database)
- [x] yfinance ingesting SPY, QQQ, ~20 liquid equities (22 symbols, 16,544 bars, 3 years)
- [x] Data validation passing at ingestion (0 bars dropped)
- [x] Market calendar utility working
- [x] One momentum signal generating output (10 signals for 2026-05-29, GOOGL top-ranked)
- [x] Paper executor logging trades to DB (10 orders, 10 fills, 5bps slippage)
- [x] Basic PnL tracking live
- [ ] Discord alert firing on signal (skipped — not required)

---

## DB State as of 2026-05-29

| Table | State |
|---|---|
| `price_bars` | 280,966 bars, 97 symbols (94 equity + SPY/QQQ/IEF), 10+ years history (2015-01-01 → 2026-05-29) |
| `signals` | 10 momentum signals |
| `orders` | 10 paper orders |
| `fills` | 10 fills, 5bps slippage (~$4.80–$5.00/trade) |
| `portfolio_snapshots` | 1 row — 2026-05-29, $197,641 total, 10 positions (Phase 2+3 fills accumulated) |
| `pnl` | 1 row — 2026-05-29, cumulative P&L +$97,641 (inflated by double-run fills; will normalize next day) |
| `experiments` | 10 rows — v1, 10yr baseline, 15bps, top-5, regime filter (×2), sector cap (×2), expanded universe (×2) |

---

## Stream Infrastructure Is Multi-App (architecture — read before adding a stream)

**The stream host is not "the Blob's". It captures a URL.** Nothing in Xvfb,
Chromium, ffmpeg, `switch.py`, `watchdog.py`, `agent.py`, `chat.py`,
`streamlabs.py` or `deploy.sh` knows what a trade or a Blob is. The page is
chosen by ONE env var on the VM:

```
STREAM_URL=https://<app>.streamlit.app/?page=Stream&yt=0&live=1
```

**The intended shape:** several vertical "stream apps" live as ordinary pages of
this same Streamlit app (`?page=Stream`, `?page=Stream2`, …), and **Stream HQ
picks which one is on air**. The switcher is the same mechanism the ON AIR button
already uses — HQ writes a param, `switch.py` polls it and acts — just rewriting
`STREAM_URL` + restarting `blob-chromium` instead of starting ffmpeg.

**BUILT (2026-07-20), NOT YET DEPLOYED.** HQ has a **Channel** selector writing
`strategy_params (strategy='stream', param='active_app')`; `switch.py` polls it,
rewrites `page=` inside `STREAM_URL` in `/opt/blob-stream/.env`, and restarts the
render chain. Notes that matter:
- **`STREAM_APPS` in `switch.py` is an ALLOWLIST and is the security boundary.**
  The value arrives from a DB row and is interpolated into the URL Chromium
  loads and the path the music bed derives from. Membership is the only way to
  be on air; adding an app is a deliberate code change. HQ's `_STREAM_APPS` must
  stay in step — a name only in HQ writes a row the host refuses.
- **It restarts BOTH units.** Picture and music must move together (rule 2).
- **The encoder is held for `SWITCH_WARMUP` (100s) after a switch**, because
  Chromium cold-starts a Streamlit page in 60–90s and the poll loop would
  otherwise broadcast ~90s of an empty X display.
- **This is the one thing on the host that writes `.env`** — `deploy.sh`
  explicitly refuses to. The file holds the stream key, so its mode is copied
  onto the replacement rather than inherited from a fresh temp file.
- **Switching is ~90s of downtime.** A channel change, not a crossfade.
- The switch reports `app` (read back from `.env`) in its health detail, so HQ
  shows what the host actually obeyed rather than echoing the click. Deploy with
  `./deploy.sh`; until then the control writes a row nothing obeys, and HQ says
  so.

**THE TWO RULES, and they are opposites. Get these wrong and two apps corrupt
each other:**

1. **CONFIG IS NAMESPACED PER APP.** Everything in `strategy_params` today is
   `strategy='stream'` — `bg_enabled`, `bg_opacity`, `potions`, `afk_phrases`,
   `ticker_colors`. Two apps sharing that namespace fight over each other's
   settings. The primary key is `(strategy, param)`, so namespacing is FREE and
   needs no migration: use `strategy='stream:blob'`, `'stream:app2'`, … Decide
   this before the second app exists; retrofitting is miserable.
2. **THE MUSIC BED SWITCHES WITH THE APP, derived from `STREAM_URL`.**
   `stream.sh` parses `?page=X` out of the URL and looks for
   `music/<x>/` — so `?page=RetroNews` plays `music/retronews/`, and anything
   without its own folder falls back to the shared `music/` root. Deliberately
   DERIVED rather than a second `.env` variable: the URL is already the single
   source of truth for what is on air, and a separate `STREAM_APP` would
   eventually drift and play the wrong bed with nothing to explain why.
   Normalise into the per-app folder:
   `sudo ./normalize-music.sh /tmp/incoming /opt/blob-stream/music/retronews`.
   **Read once at ffmpeg start — switching apps must restart `blob-ffmpeg` as
   well as `blob-chromium`, or the picture changes and the music does not.**
3. **EVERY STREAM APP MUST SEND THE `stream_page` HEARTBEAT.** Not optional and
   not just for the health strip: `watchdog.py` restarts Chromium whenever the
   newest **live** `stream_page` beat is older than 75s. An app that does not
   beat is therefore restarted *forever* — the reload takes ~90s to come back,
   still says nothing, trips the watchdog again. It presents as a mysterious
   90-second reboot loop **with every systemd unit reporting healthy**, which is
   about the worst failure signature available. Post every 15s with
   `detail.live` set from `?live=1` (the watchdog filters on it, because every
   open copy of the page beats — a phone, a preview tab — and the newest beat of
   *any* of them would mask a frozen broadcast). Use the SAME component name:
   the question is "is the captured render alive", which is about the render,
   not which app is in it, and only one is ever on air. Carry `detail.app` so
   you can still tell them apart. RetroNews shipped without this and could never
   have stayed on air; see the beat at the end of `retronews.js`.
4. **EVENTS ARE SHARED, DELIBERATELY.** `stream_events` has no app column and
   should not get one. A tip is a tip regardless of which app is on screen, so
   one bus means the donation chain keeps working straight through a switch.
   `streamlabs.py` / `chat.py` are decoupled from presentation entirely — same
   account, same token, same bus, and whichever page is rendering reacts. The
   same $5 can drive Blobby's potion chain on one app and something completely
   different on another; that is each page's own rendering code, not infra.

**ONE STREAM AT A TIME — this is a hardware fact, not a design choice.** Measured
on the 4-core ARM host: a single 810x1440 render pegs `chrome --type=gpu-process`
at ~98% of one core doing SOFTWARE compositing (no GPU), and that cost is
per-PIXEL, not per-animation (proven by an A/B that switched a full-screen 24fps
starfield off and moved it 0.1%). Two concurrent broadcasts do not fit on this
box; a second needs a second VM. Switching pages costs a ~90s Chromium restart —
it is "changing the channel", not a crossfade.

**Every hard-won constraint in `dashboard/stream.css` / `stream.js` applies to any
new stream page** — the 1080x1920 letterboxed stage, the YouTube safe zone
(870x1160 at 90,380), and above all: **`requestAnimationFrame` and CSS
transitions/animations are INERT inside the component iframe. Anything that must
move uses `setInterval`.** `dashboard/views/stream2.py` is the scaffold that
already encodes all of this — start from it, do not start from scratch.

### Design every visual for the framerate we ACTUALLY have (~24fps)

**The budget, measured on the real host (2026-07-18):**

| | unique painted fps |
|---|---|
| 1080x1920 | ~6, swinging 5.3–12.3 |
| **810x1440 (current)** | **~22–23.6, dead stable** |
| ffmpeg capture / ceiling | 24 |

So **24fps is the ceiling and ~22–23 is the working number.** A frame is ~42ms.
Design to that, not to the 60fps a phone gives you — the page looking perfect on
your phone tells you nothing, because a phone composites on a GPU and the
broadcast VM does it in software.

**THE COUNTERINTUITIVE PART — DO NOT "OPTIMISE" VISUALS FOR FRAMERATE.**
Animation complexity is FREE. Proven by A/B on the live host: switching a
full-screen 24fps starfield OFF moved the compositor from 98.6% to 98.7% and
changed painted frames by ~0. The renderer sits at **0.0% CPU**; the cost is
`chrome --type=gpu-process` compositing the surface in software, and it is
**per-PIXEL, not per-animation**. Stripping effects to "save frames" buys
nothing and costs the show. Add all the effects you want.

Only two things actually move the number:
1. **Resolution** (surface area) — the one lever in software. 44% fewer pixels
   bought ~2.5x the frames.
2. **Faster cores.** Not more — the compositor is single-threaded.

**What this means for how motion is DESIGNED:**

- **Nothing may depend on smooth interpolation.** At 42ms/frame, fine easing and
  fast small movements strobe. Anything crossing the stage in under ~0.5s will
  judder no matter what.
- **Quantized, stepped, held motion reads BETTER here** — which is why the 8-bit
  aesthetic suits this hardware. Lean into poses and cuts, not tweens. The Blob's
  10fps sprite-art cadence against a 24fps draw rate is the model: the ART steps,
  the POSITION glides.
- **Coarse position grids read as choppy at ANY framerate — a separate axis from
  fps.** The Blob's bob was rounded to whole 48px-sprite pixels displayed at 16x,
  i.e. 16-SCREEN-PIXEL leaps; raising the framerate did nothing because the steps
  themselves were coarse. Move things in SCREEN pixels (element `transform`),
  which does not resample pixel art. See `blob.js` `fxLoop`.
- **Budget motion in frames, not milliseconds.** A 100ms effect is 2–3 frames.
  If it needs to be seen, give it 6+.

### RetroNews — the era rule (binding for `?page=RetroNews`)

RetroNews is a **fake 90s cable channel** (WeatherSTAR 4000 / late-night
infomercial / broadcast chyron). Reference: <https://weather.com/retro/>.
**Everything on that page must obey the era AND the framerate — they agree.**

1. **CUTS, NOT TWEENS.** Tiles change by hard cut or a hard wipe, never a fade
   or slide. This is both authentic (the WeatherSTAR swapped pages on a timer)
   and the correct motion strategy for a 24fps software compositor.
2. **Ambient motion is palette-based, not positional.** Colour cycling, blinking,
   a slow crawl. It costs nothing and needs no framerate. Do NOT animate position
   to create life.
3. **THE CONCEIT IS A GAME BOY ADVANCE RENDERING A CABLE CHANNEL** — not a cable
   channel.
   That mashup decides everything below, and it **reverses** the rule that was
   here first. A straight 90s-broadcast homage wants a real bold sans with a hard
   offset shadow, and a pixel font would read "video game, wrong era". Here the
   machine IS a video game machine, so **Press Start 2P is correct** and a smooth
   sans would break the joke. If the concept ever shifts back, flip this rule too
   — it follows the conceit, it is not an absolute.
4. **EVERYTHING lives on the pixel grid — the whole page, not just sprites.**
   Stage is 1080×1920 broadcasting at 810×1440 (×0.75), so a logical pixel must
   be whole in BOTH spaces. `gcd(1080, 810) = 270`, so the grid is
   **270×480 logical, 1 logical px = 4px stage = 3px device**. `--px: 4px` in
   `retronews.css`; every size is a multiple of it. The safe box is snapped to
   **864×1152 at (88, 376)**, which is *safer* than the raw numbers (128px right
   margin vs 90, 392 bottom vs 380). The host portrait is 72×90 logical, one art
   pixel per logical pixel, never resampled.
5. **GBA palette and GBA panel treatment** (upscaled from DMG 2026-07-19):
   - A **saturated 15-bit-era palette**, defined once in `retronews.css` `:root`.
     The saturation is deliberate — the original hardware had no backlight, so
     its games pushed brightness and chroma hard, and that is the remembered look.
   - **EVERY panel is BEVELLED.** One logical pixel of light on the top-left, one
     of shadow on the bottom-right, plus a hard outline — four flat rectangles,
     which is how the hardware faked depth. Raised (`.bevel`) for things that sit
     ON the console; recessed (`.bevel-in`) for things set INTO it (the host
     portrait, the dialogue box). **A new tile that is not bevelled will not look
     like it belongs.**
   - **Banded gradients are allowed** — in visible hard steps, never smooth ramps.
   - Still no blur, no radius, no anti-aliasing, no soft shadow. Type gets a
     1-logical-px hard offset shadow, never a glow.
6. **Tile changes use the DISSOLVE, never a fade** (`cutTo()` in
   `retronews.js`): a chunky block dissolve covers the panel in 8 discrete
   steps, the tile is swapped at full cover behind a one-frame gold flash, then
   it uncovers in 8 steps. Quantised by construction, which is both the
   authentic hardware effect (mosaic/window wipes) and the only motion a 24fps
   software compositor renders cleanly. ~935ms ≈ 22 frames — comfortably above
   the 6-frame floor. **Never add a CSS fade or slide**; they are inert in the
   iframe anyway.
7. **Type has a legibility floor.** Vertical video is watched on phones, and
   stage px × 0.75 = device px, then the phone shrinks it again. Anything under
   ~24px stage is unreadable on air — measured: a 20px face came out around 8px
   on a phone. Body/data ≥ 8 logical (32px stage); labels ≥ 6 logical (24px).
   A Game Boy fit ~20 characters across; our 216-logical safe box fits 27 at
   8 logical, which is the same density AND legible.
8. **Everything visible lives inside the safe box.** The Blob stream's known
   cost — 8 of 14 tiles sitting behind YouTube's chrome — is not repeated here.
   **THE BOX IS MEASURED** (2026-07-20). It got there the hard way — first a
   near-symmetric 88 left / 128 right, then an aggressive 16 left / 200 top to
   reclaim the margins, then a real livestream screenshot showed the published
   guides are wrong about live in every direction and that the aggressive box was
   over on three edges (top by 52, left by 95, bottom by 7). See rule 10.

   | | left | right | top | bottom | canvas |
   |---|---|---|---|---|---|
   | required | 111 | 135 | 252 | 391 | — |
   | **actual** | **112** | **136** | **252** | **392** | **51.2%** |

   Rounded INWARD onto the 4px grid so rounding can never eat a margin; every
   edge lands exactly 1px clear. **51.2% is LESS than the 59.3% it replaced, and
   that is the correct direction** — the old number was optimistic, not earned.
   **The LEFT is the one that bit and the one no guide mentions**: YouTube's back
   arrow (x57-110) and crown (x68-111) sit exactly where the layout had been
   pushed. The RIGHT is cheap because live has no Shorts action rail. The BOTTOM
   is set by chat MESSAGES at y1529, not the input at y1786, so it moves if chat
   collapses.
   Allocation (logical, safe box = 208x319, fully packed): brand 24 · gap 4 ·
   **content 195, ONE panel** · gap 4 · host 92.
   **The host strip is TOGGLEABLE** (`host_visible`, RetroNews HQ, polled ~3s).
   Hidden, the content panel absorbs his 96 and runs **291** logical. This works
   because `#rn-content` is a **flex filler, not a fixed height** — there is no
   second set of numbers to keep in sync. Only an explicit `'0'` hides him, so a
   missing row or a failed fetch leaves the stage as designed. It is a **CUT**:
   CSS transitions are inert in this iframe and a hard cut is the era anyway.
   Two things must move WITH the toggle, and both are silent failures if missed:
   **(a) type scales up** (`.no-host` bumps the faces) — growing the box while
   leaving 8-logical text in it just adds emptiness; **(b) `WIPE_ROWS` is sized
   for the TALLER state** (25, not 17) or the dissolve covers the small panel and
   leaves the bottom third of the big one live.
   **Weather rows are whole logical px per state (17 / 26), never `1fr`** — 1fr
   divides 171 and 267 into 17.1 and 26.7, putting every alternating band edge
   off the pixel grid to be antialiased into a soft seam. One big panel beats a split at
   this size — a single tile is what reads across a room, which is the point of a
   channel you leave on. The `Slot` machinery in `retronews.js` is generic and
   instantiated once, so rotation, dissolve and the duplicate guard are all still
   one code path if a second is ever wanted. The portrait is UNCLIPPED at 72x90.
   **The guides overlay is driven by the safe-box CSS vars, never by literals** —
   a guide that disagrees with the layout is worse than no guide, because it is a
   measurement you trust that is wrong. Double-tap the top-left on a phone.
   If the strip is ever shortened, **clip the portrait window, never scale the
   sprite**: only whole multiples keep one art pixel on one logical pixel
   (3x = 67.5 logical, off-grid). Collar begins at art y66.
10. **The measuring overlay (`dashboard/retronews_yt.js`) is MEASURED, not
    reconstructed** — calibrated 2026-07-20 against a real YouTube mobile
    livestream screenshot (1080x2340 phone, immersive layout, chat expanded).
    It replaced three published *Shorts* readings that disagreed by 260px on the
    top margin, **and all three were wrong about live, in the same direction**:

    | | Shorts guides said | LIVE actually is |
    |---|---|---|
    | top | 120–380 | **252** (crown button is the deepest) |
    | bottom | 300–390 | **391** (chat MESSAGES, not the input at 1786) |
    | left | 60 | **111** (back arrow + crown — no guide mentions these) |
    | right | 60–120 | **135** (one react button) |

    **There is NO vertical action rail on live.** Shorts stacks like/dislike/
    comment/share down the right edge; a livestream does not — it has a top bar
    with Subscribe, a chat input, and a single react button. The old overlay drew
    a 130px rail that does not exist.
    **The app's bottom nav sits BELOW the video, not over it**, and the phone's
    status bar above it — neither costs anything.
    **The intrusions that actually bite are on the LEFT**, which is precisely
    where the layout was pushed to reclaim room.
    Screen px became stage px by FRACTION of the player box (reference video was
    screen y81-2051, 1:1.824; ours is a true 9:16) because chrome anchors to the
    container's edges. x maps 1:1 — both 1080 wide.
    Toggled from RetroNews HQ (`yt_overlay`, polled ~3s, live, no reload);
    `?yt=1` sets the initial state and **no row = no opinion**, so the URL param
    survives until HQ is first pressed. Defaults OFF.
    **Covered area is split HARD vs VARIABLE, and the distinction is worth
    257px.** HARD is chrome that is always there — top row, the two left buttons,
    the react button, and the chat INPUT (pinned to the player bottom, never goes
    away) = top 252 · bottom 134 · left 111 · right 135. VARIABLE is the chat
    MESSAGE feed, **y1529–1786**, present only while chat is expanded. So there
    are two honest boxes: **ALWAYS SAFE 834x1277** and **IF CHAT COLLAPSED
    834x1534**. Entering the variable band is a TRADE-OFF, not an error — the
    verdict says "uses Npx of the chat band", and only breaking HARD chrome reads
    as over. Put anything that must always read outside the band; anything that
    can afford intermittent occlusion may use it.
    **Still assumed:** one device, one shot, chat expanded — that collapsing chat
    frees the whole band is inference, not measurement. The top row may also
    auto-hide on idle, which would make it variable too; deliberately NOT
    modelled, since inventing a second variable zone would undo the point of
    measuring.
    **RESOLVED 2026-07-20:** the layout was moved onto the measured box and now
    reports `✓ CLEARS MEASURED CHROME` with zero collisions against every
    measured footprint. See rule 8 for the geometry.

---

## Pending Infrastructure Tasks

- [ ] **RetroNews host — remaining ChatGPT art (Tyler's queue).** Five of six
  moods are real art; SLEEPY is derived from NEUTRAL (closed eyes ARE the whole
  expression at 72x90, and deriving it cannot drift). Generate in the SAME
  ChatGPT thread as EDITS of the existing portrait — never regenerations —
  changing ONLY eyes/eyebrows/mouth, and say "exaggerate it clearly" every time
  (at 72x90 each eye is ~6px, so naturalistic expressions vanish in the
  downscale). Wanted, in value order:
  1. **TALKING** (open mouth mid-speech) — buys the most: nothing currently
     animates while the ticker narrates. Needs a new row + `MOOD_ROW` entry.
  2. SLEEPY as real art, if the derived version ever looks weak on air.
  Prep each with
  `python scripts/prep_art.py IN.png dashboard/art/host/NAME.png --size 72x90
  --colors 22 --key-corners --crop 228,3,1141,1145 --palette-from
  dashboard/art/host/NEUTRAL.png`
  then rebuild the sheet with `scripts/build_host_sheet.py`. **`--palette-from`
  is mandatory** — MEDIANCUT picks a palette from the image, so quantizing
  expressions independently gave six palettes (98 colours) and the visible
  symptom is his skin tone shifting whenever his mood changes.
  Expect a systematic crop offset (measured -1..-2 x, +2..+3 y); correct it in
  `--crop`, before the downscale, which is the only place sub-output-pixel
  precision exists.

- [ ] Dashboard cosmetic overhaul — hyper-tech, modern, premium fintech aesthetic.
  Direction: dark theme, tight data density, monospace numbers, minimal chrome,
  one or two accent colors max. Less Streamlit boilerplate, more Bloomberg terminal
  meets modern SaaS dashboard. In progress — font/CSS pass done, deeper layout
  work remaining.

- [~] The Blob — 8-bit pixel character that reacts to live trader state.
  **Read `dashboard/BLOB.md` before touching `dashboard/blob.js`.** It is the
  design contract: the 10fps tick, the locked palette and the always-pink rule
  are deliberate and look like bugs if you don't know why.
  Status (2026-07-17): **sprite-driven, EYES-ONLY** — a small pink circle + one
  line mouth + cartoonishly large over-the-top eyes, no arm/fangs/tongue/brows/
  particles. Two 48×48 sheets (`blob_body.png` + `blob_eyes.png`) blitted by
  blob.js, inlined as base64; cel + gloss, **not Bayer dither**. **9 moods** now
  (`IDLE HAPPY SCARED ALERT SLEEP SMUG BRACE EXASPERATED HOPEFUL`); **IDLE is the
  confident default**, EXASPERATED is the loss reaction, HOPEFUL the fresh pickup.
  A donation drops **sunglasses** (`blob.cool()`) — the one surviving accessory.
  Regenerate with `scripts/gen_blobby_eyes.py`, re-embed with
  `scripts/embed_blob_sheets.py`. **Wired to live state on the Stream page**
  (stream.js drives setMood/setPnl); Home (`home_nav.js`) not yet. Streamlit is
  deliberately not involved — see BLOB.md.

- [ ] Feature queue — professional quant tooling (build in priority order):
  1. [ ] Correlation matrix — live heatmap of current position price correlations
  2. [ ] Alpha decay tracker — live Sharpe vs backtest Sharpe trend; early warning if edge degrades
  3. [ ] Mobile alerts — Telegram/Discord bot for risk breaches, rebalances, daily PnL ±2%
  4. [ ] Stress testing — run current positions through 2008, 2020, 2022 crash scenarios
  5. [ ] Factor exposure dashboard — decompose returns into momentum/size/sector/beta (Fama-French)
  6. [ ] Greeks-style position risk — cost of 1% market move per position, sector rotation impact
  7. [ ] Slippage & cost attribution — actual fills vs model assumptions, tracks execution drift
  8. [ ] Monte Carlo simulation — probabilistic drawdown forecasting from historical return distribution
  9. [ ] Signal decay analysis — how long does momentum signal stay predictive; optimize rebalance freq
  10. [ ] Regime detection — VIX-based or HMM volatility regime classifier for dynamic position sizing
  11. [ ] Walk-forward optimization — rolling parameter stability testing, anti-overfit validation
  12. [ ] Peer benchmark — compare vs MTUM and other momentum ETFs, not just SPY/QQQ
  13. [ ] Alternative data — SEC EDGAR insider buying, short interest, earnings sentiment
  14. [ ] Investor report generator — one-click PDF monthly report, Claude API writes commentary
  15. [ ] Trade journal — mandatory per-fill annotation, feeds hypothesis generator

- [ ] Migrate to cloud (free tier) — chosen stack: Supabase + Streamlit Community Cloud + GitHub Actions
  - DB: Supabase free tier (confirmed user has room — only 1 of 2 free-project slots used)
  - Dashboard: Streamlit Community Cloud (free, deploys from GitHub repo)
  - Scheduler: GitHub Actions cron (free tier, 2,000 min/month) — replaces manual run_pipeline.py clicks
  - Steps:
    - Push repo to GitHub (confirm .env gitignored, never committed)
    - Create new Supabase project (2nd of 2 free slots)
    - Export local PostgreSQL with pg_dump, restore into Supabase
    - Update DATABASE_URL in .env to Supabase connection string
    - Deploy Streamlit dashboard from GitHub repo to Streamlit Community Cloud; set DATABASE_URL as a secret
    - Add GitHub Actions workflow: cron trigger ~4:05pm ET (account for DST — UTC offset shifts), checkout repo, install deps, run run_pipeline.py, DATABASE_URL from repo secret
    - Confirm full pipeline runs clean in GitHub Actions before relying on it
    - Known risk: yfinance occasionally rate-limits/blocks cloud datacenter IPs (AWS/GCP) — watch first few automated runs closely
    - DELETE local PostgreSQL database and data after confirmed migration
    - DELETE local Streamlit instance after confirmed cloud deployment
  - This replaces manual python run_pipeline.py

- [ ] Push all code to GitHub before migration
- [ ] Confirm .env is in .gitignore and never committed

- [ ] Multi-investor / pooled fund support (post-live, when first outside investor is ready)
  - Prerequisites: live Alpaca account active, at least one friend ready to contribute
  - Data model additions:
    - `investors` table — id, name, email, join_date
    - `capital_events` gains `investor_id` foreign key (nullable — untagged until assigned)
  - NAV unit accounting:
    - Pool starts at N units @ $1.00/unit on first deposit
    - Each new deposit buys units at current NAV (portfolio_value / units_outstanding)
    - Each withdrawal redeems units at current NAV
    - Unit ledger stored in new `nav_units` table: investor_id, date, units_delta, nav_at_transaction
  - Alpaca deposit auto-detection:
    - Poll `GET /v1/account/activities?activity_type=JNLC` daily in run_pipeline.py
    - Auto-insert untagged capital_events rows when new transfers are detected
  - Dashboard: new "Investors" tab on Portfolio page
    - Surfaces untagged deposits as "who is this?" assignment prompt
    - Per-investor table: name, units held, current value, return since entry, % of pool
    - Read-only shareable view per investor (Streamlit query param auth)
  - Legal note: confirm friends-and-family exemption applies before onboarding any outside investor
    (number of investors, no advertising, no performance fees without RIA registration)

- [ ] Build automated post-mortem review system (after 60+ days of live fills)
  - tracking/post_mortem.py — weekly self-audit of fills vs outcomes
    - Which positions were entered/exited at good or bad times?
    - Did high-score signals outperform low-score signals as expected?
    - Systematic patterns in losers (sector, market cap, volatility regime)?
    - Did momentum score predict actual forward returns?
    - Output: weekly report appended to experiments/results/post_mortem_log.md
  - research/hypothesis_generator.py — pattern detection that proposes new experiments
    - Detects systematic failure patterns in fill history
    - Logs proposed parameter changes as hypotheses to experiments table
    - Auto-triggers backtest against full price_bars history
    - Nothing changes in production without explicit human approval
  - Dashboard: new "Insights" page
    - Surfaces auto-generated hypotheses for human review
    - Shows post-mortem findings in plain English
    - Approve or reject proposed changes from the dashboard
  - AI integration via Anthropic API
    - Claude reads post-mortem data and writes plain-English explanations
    - Proposes specific parameter changes with reasoning
    - Summarizes weekly performance for human review and approval
    - Uses existing API infrastructure — no new dependencies needed

  Prerequisites before building:
  - 20-day monitoring period complete
  - 60+ days of live fills to pattern-match against
  - Sector cap and volume confirmation validated and in production

---

## Phase 2 — Momentum Validation (COMPLETE)

- [x] Confirm no look-ahead bias in `price_momentum.py` — formally audited, CLEAN
- [x] Run backtest against historical data and log results to experiment tracker (experiment 5599e498)
- [x] Confirm backtest passes full integrity checklist (PASS with documented OOS caveat)
- [x] Extend historical data to 10 years (63,074 bars, 2015-01-02 → 2026-05-28)
- [x] Run sensitivity analysis — 3 backtests on 10-year dataset (2b5e6dd7, 0dc5e1c2, b6de4389)
- [x] Promote momentum `research` → `backtest` → `paper` in registry
- [x] Configured top-5 signals, 20% position sizing, 5bps slippage

## Phase 3 — Paper Trading (ACTIVE since 2026-05-29)

Paper portfolio start date: **2026-05-29**

- [x] Momentum promoted to `paper` in registry (2026-05-29)
- [x] Top-5 signal config active (`momentum.yaml: top_n_stocks: 5`)
- [x] Risk limits enforcing: 1% risk/trade, 2% daily DD halt, 10% total DD halt, 20% max position
- [x] 5bps slippage active in paper_executor.py
- [x] End-of-day portfolio snapshot writing to `portfolio_snapshots` table
- [x] Mark-to-market PnL with rolling 63-day Sharpe writing to `pnl` table
- [x] Daily report appending to `experiments/results/paper_portfolio_log.md`
- [~] Streamlit dashboard — in progress (`dashboard/app.py`, 6 pages)
  - **Home**: Strategy Command Center — default landing page. Fully autonomous — zero hardcoded values. Sources: CLAUDE.md (phase), strategy_registry.yaml (status), momentum.yaml (rebalance), risk_limits.py (limits), experiments table (performance + completed enhancements), config/enhancement_queue.yaml (queued items).
  - **Portfolio**: equity curve, positions, drawdown, trade history
  - **Benchmarks**: live portfolio vs SPY/QQQ; historical backtest vs SPY/QQQ/60-40; metrics table; rolling Sharpe. IEF added via `python scripts/fetch_ief.py`
  - **Signals**: latest signals, score distribution, filterable history
  - **Backtest Lab**: parameter sliders, inline backtest, experiment comparison
  - **Risk Monitor**: exposure vs limits, drawdown history
  - **Stream**: vertical 1080×1920 display page for autonomous livestreaming (`?page=Stream`).
    Files: `dashboard/views/stream.py`, `stream.css`, `stream.js`, `yt_overlay.js`.
    **This is the first surface where the Blob is wired to live state.**

    **The safe zone governs this page, not the canvas.** YouTube vertical live surfaces
    in the Shorts feed, so Shorts safe zones apply: top 380 and bottom 380 are reserved
    (on a *live* stream the chat input is permanent down there), and the right ~120 is the
    action rail. Usable area is **870 × 1160 at (90, 380)** — ~49% of the canvas — declared
    once as `--safe-*` in stream.css.

    **The safe box no longer contains everything, on purpose.** Inside `#safe`:
    padding-top 220 / Blob 768 / score 172 = 1160. Above it, in the reserved top band,
    sit the nameplate + status line (y12–112) and the tile board (y120–600) — so the
    board straddles y380 and 8 of 14 tiles plus the whole `blob <x>` sentence are behind
    YouTube's chrome. This was chosen deliberately (the tiles are the most interesting
    thing on the stream and were wanted large); it is a **known cost, not an oversight**.
    Revisit it the first time the page is seen on a real broadcast. Measured, not eyeballed:
    nameplate y12–66 left x90, board y120–600 left x90, left-aligned to within 2px.

    Stage is fixed 1080×1920 and letterboxes via CSS transform — at a true 1080×1920
    capture the scale resolves to exactly 1 and the Blob's pixel art is unresampled
    (he renders at 768px = 48×16, an integer scale — keep any resize on a 48px multiple).

    **`blob <x>` — the status line.** Reads as one sentence: `blob sold XTZ for −$0.54`.
    Nameplate is static; `x` decodes between states (per-segment scramble, staggered 90ms,
    `setInterval` because CSS animation is inert here). `setStatus()` fires from
    `applyTrade()` so it lands with the sound and the tile — measured 0.5–3.4ms against a
    `createOscillator` hook. Ticker colour comes from `ticker_colors` (set on the Command
    Center, polled 30s, white if unassigned). **A buy shows qty × price, not the per-unit
    price** — the template says "total P&L" but a buy has none, and the per-unit price
    rendered "bought CRV for $0.2161" on a $204 position. Decays to `is trading` after 20s.

    Reuses `home._load_chart_data()` and `blob.js` verbatim; deliberately does NOT reuse
    `home_nav.js` (173 getElementById bindings to Command Center nodes, and margins tuned
    for a wide stage). No feed or footer ticker: both sat in the bottom 380 and no
    arrangement saves them. The NAV chart and the background terminal feed were both
    **deleted** — he is the streamer, not the charts. Background is `stream_bg.js`:
    purple cyberpunk stars rising bottom→top on a half-res 540×960 buffer, plus drones
    and an LED rack, all reacting via `bg.pulse()`. `pollEvents()` drives the Blob's moods.

    **Standing rule for this page: anything that must move uses `setInterval`.** `rAF`
    never fires inside the component iframe and CSS transitions/animations share that same
    clock, so they are all inert here. This is not a preference — a CSS animation written
    on this page silently does nothing.

    **Event lanes.** Everything animated belongs to one of three, ranked — `stagePump()`
    is the single arbiter and one lane owns the floor at a time:
    1. **popup** — the Gameboy window (`annQ`); a *viewer* did something (dono/sub/raid).
    2. **speaks** — the same window, Blobby's voice (`speakQ`, `blobSpeak()`, `blob_speak`
       event type). Same box on purpose: a Gameboy has one text box, so who is talking is
       carried by the `speaking` skin, never by position.
    3. **trade** — the beat (`tradeQ`).

    Popups and speaks **pause trades**. Pause means *the queue* pauses, not the frame: a
    beat in flight has fired its sound and has a tile mid-animation, so the unit of work is
    atomic and only the order is arbitrated. The trade lane takes **one beat per acquire**
    (not its whole queue) — that is what bounds a donation's wait to ~1.6s. The reorder is
    atomic for a harder reason: FLIP parks tiles on a transform, so killing it mid-play
    strands them permanently; it can only be waited out.

    Each lane holds the floor for its whole **burst** — the popup queue drains before the
    box closes, because closing and reopening between two donations reads as a glitch.

    **Reactions fire from the lane, not on arrival.** `applyStreamEvent` used to set mood
    and play sound the moment a row was polled, then queue the box separately — so an event
    behind another sounded seconds before its window opened. Mood/sfx/pulse now fire inside
    `annNext()` with the box.

    **The book does not trade, it ROLLS — and that governs the batching.** Measured over
    6h/3,210 fills: **798 of 799 batches are pure rolls** — the engine exits a set of
    symbols on `timeout` and re-enters the identical set within ~1.5s, board unchanged.
    Batch sizes are always even (2,4,…,16) because every fill is half a round trip.
    So `tradeIngest()` **pairs exit→re-entry into one `ROLL` beat** (`rolled BTC for
    −$0.38`): the tile stays put, the realised P&L is the news, 16 legs become 8 true
    beats. Pairing is at poll time because the batch must be visible *as* a batch —
    ~63% land in one poll, and the ~37% that straddle the 4s boundary wait one cycle
    (`ROLL_WAIT`) rather than airing as a sale that didn't happen.
    **Do not "simplify" this back to per-leg narration.** It was per-leg, and it lied:
    the cap kept the newest 6 of 16 — all ENTERs — so a roll played as "bought SOL,
    bought AVAX…" with every exit and its P&L dropped (62% of the batch). Cap is 8 =
    the largest roll; lowering it re-creates the fiction.

    **The pick + the reveal** (`pickAt()` / `revealExit()`, replacing the old `.t-point`
    Gen-1 cursor). A sell is staged as a gamble in three moments. **PICK** (the 500ms
    wind-up): a ring in his body pink locks around the target tile and *charges* — glow
    ramps up, a `?` pulses above it — so attention converges on that ticker before it pops.
    **REEL** (`REVEAL_MS` = 420ms, EXIT only): at the impact the ticker does NOT print the
    P&L; it spins through random ±$ values in neutral gold (`.t-spin`), sign included, so
    win/loss is genuinely unknown. **LOCK**: the reel stops on the real number, white-pops,
    then the arcade hit restains it green/red. **The verdict is held to the lock** — mood
    (HAPPY/EXASPERATED), win/loss sound, the horizon `bg.pulse`, the NAV move, and the
    `blob <x>` sentence all fire in `onLock`, not at the impact, so his face never gives the
    result away early. `applyTrade` returns `REVEAL_MS` so `tradeStart` pushes the POST
    release out by it. **Sells/rolls only** — a constraint, not a preference: an entry has no
    tile to lock onto (and no P&L to reveal) until its impact creates the slot. Sounds:
    `SFX.charge` (rising run under the wind-up) → `SFX.reelTick` (per spin frame) →
    `SFX.win/loss` (at the lock). The reel is per-sym (`_reelT`) and self-terminating.

    **Ticker colour is three tiers, and `ticker_colors` is only the top one.**
    `tickerColor()` is ported from `home_nav.js` `symCol()` and must stay identical or the
    same ticker is two colours on two screens: `ticker_colors` row → `TICKER_OVR` built-in
    → `_hashCol()` into a 10-colour `PALETTE`. **The hash is what guarantees every ticker
    has a colour** — the table holds 3 rows against 9 board symbols, so a table-only lookup
    (the original bug) coloured CRV and left the other 8 white. `'BTC/USD'` → `'BTC'`
    normalises fine; there was simply never a row, and there needn't be.
    Known collision: **LINK and SOL both hash to `#ff9900`**. That is what the override
    tier is *for* — assign one on the Command Center to separate them.

    **`x` never goes quiet: the AFK cycle.** Silent >2s (`AFK_AFTER`) and it decodes
    through a random line from `AFK[]` every 4.2s, completing the nameplate ("blob" + "is
    cooking"). **Copy is capped at 25 characters** — measured (640px of runway at
    25.5px/glyph) and `#s-title` is `overflow:hidden`, so a 26th character silently
    vanishes rather than wrapping; the list `.filter()`s its own overlong entries.
    The cycle re-arms instead of firing while `tradeQ` is non-empty: beat-to-beat is 1.6s
    against the 2s timer, only 400ms of margin, so a beat delayed by a reorder would
    otherwise flash an AFK line mid-roll.

    **System text is white** (`.xs-verb`, `.xs-for`, `.ttl-x.idle`). Only the two things
    carrying information get colour: the ticker (its assigned hue) and the P&L (green/red).

    **A roll narrates in TWO moments inside its ONE beat** — `sold X for −$0.16` then, after
    `ROLL_HOLD_MS`, `bought X for $195.13`. Entry text was previously *unreachable*: every
    ENTER paired away into a ROLL, so `bought` could never fire. Still one beat per round
    trip, so the pairing (and the no-drop guarantee) holds. `ROLL_HOLD_MS` is **derived**
    (`SEG_STAGGER*3 + DECODE_FRAMES*DECODE_STEP + 800`) because x needs ~576ms just to
    decode and the entry moment rebuilds the spans — a guessed 650ms left the finished sell
    readable for 74ms. `ROLL_WAIT` is likewise derived from `POLL_MS` (2 polls + 1s): a
    straddled batch pairs across polls, so anything under one interval cannot pair at all.

    **Tickers are per-glyph** (`setSym()`, one `<i>` per character) so a 1px wave ripples
    through each word — one interval for the whole board at 10fps. **Never set
    `.t-sym.textContent` directly**; it drops the glyphs and kills the wave on that tile only.

    **The stage is a LEASE, not a lock.** `stageWatchdog` force-releases any lane held
    >45s — a lane that never calls `stageDone` would otherwise freeze the broadcast to a
    still frame forever, with nobody there to reload it.

    **The box has ONE arrival and ONE death, shared by both window lanes**
    (`boxOpen()` / `boxDecay()`). A popup and a line of dialogue are different messages in
    the same window — opening them differently makes it two windows. **In:** a hot slit at
    the floor thrown open in 7 quantized frames with an overshoot (~240ms), bottom-origin
    because that is where a Gameboy box comes from. **Out:** ~880ms of decay — text rots
    back into `SCRAM` (the decode played backwards, per-glyph rolls), `--lcd-a` ramps
    0.30→1.0 so the panel is eaten by its own pixel lattice, opacity drops in *discrete*
    steps (a linear ramp is a dissolve, not chaos), and an intermittent whole-pixel tear.
    Out is deliberately ~4× In: arriving is an event, leaving is an afterthought.
    **The lane holds the stage until `boxDecay` finishes**, or the next thing plays over a
    corpse. `boxOpen` fires only on true arrival — mid-burst events replace contents.

    **The background is a vaporwave sidescroller and its HORIZON IS THE P&L**
    (`stream_bg.js`). `camY` kicks ±34 per win/loss, decays ~0.994/frame so a *run*
    compounds, and clamps at ±130 (without a ceiling a losing session drives the horizon
    off the buffer in a minute and the scene becomes plain sky). **The direction inverts
    once and then reads wrong forever, so:** *we* ascend on a gain → the world moves DOWN
    in frame → horizon screen-y **increases**. `'enter'` moves the camera deliberately —
    buying is not yet good or bad news. Scroll speed is *not* tied to P&L; direction is the
    signal and modulating both makes neither legible. Read it with `_TND_DBG.bg.getCam()`.

    **"SCARED" and "PORTFOLIO VALUE" are deleted on purpose** — both captioned things the
    stage already said, in the one gap between the Blob and his score. The mood writes
    still run through `showMood()` and surface at `_TND_DBG.mood()`; restore the
    `#blob-mood` element and it lights up again.

    **⚠ `clearTimeout(true)` is `clearTimeout(1)` — it silently kills timer ID 1.**
    `ghostT[sym]` is a **marker** (`true`), not a timer id; three sites still cleared it as
    one after it changed, and since the Blob's 10fps loop is started early it *owns a very
    low timer id*. He ran ~30s then died on the first exit batch, no error, while every
    other interval kept going. **Never pass a non-timer to clearTimeout/clearInterval** —
    JS coerces it and the call is silently valid.

    **⚠ Timing cannot be measured from an automated browser.** Its tab is always
    `document.hidden`, and Chrome throttles background timers hard — a 3s beat straddles a
    minute and is indistinguishable from a deadlock. This produced hours of phantom bugs
    this session: a "wedged trade lane", a "frozen x", a 53s watchdog trip, all artifacts.
    `stageWatchdog` skips while `document.hidden` for exactly this reason. **Verify timing
    from a real foreground window, or via `_TND_DBG.q().beat` — not by sampling the DOM.**

    `dashboard/yt_overlay.js` is a **TEMP** design aid drawing YouTube's chrome + safe
    zones over the stage. Geometry is sourced and exact; the chrome art is approximate and
    per-element placement is reconstructed (no published pixel map exists). **Defaults ON
    (`?yt=0` to disable) — must be off for a real capture.** Delete that file plus the
    hook in stream.py to remove.

    Streaming host not yet chosen. Safe-zone numbers are from published Shorts guides and
    reconcile arithmetically (380+1160+380=1920, 90+900+90=1080) but are **not verified
    against a real YouTube test stream** — live chat behaviour especially may push the
    usable bottom edge above y1540.
- [ ] Complete 20-trading-day monitoring period
- [ ] Confirm daily PnL and snapshot writes are clean each day
- [ ] Review rolling Sharpe once 5+ days accumulate
- [ ] Review full performance summary at day 20
- [ ] Decide: extend paper trading or begin Phase 4 planning (assisted execution)

---

## Strategy Registry Status

| Strategy | Status | Backtest Sharpe | Notes |
|---|---|---|---|
| Momentum | `paper` | 1.21 (10yr, top-5) | JT 12-1, **top-5 config**. Positive every year 2016-2026. Promoted to paper 2026-05-29. |
| Daytrader | `research` | TBD | MFIM: ORB + VWAP + RVOL. Scaffolded 2026-07-02. Requires `alpaca-py` + Alpaca API keys. Run backtest before promoting. Cross-references momentum signals for directional bias. |

---

## Paper Trading Monitor

| Field | Value |
|---|---|
| Start date | 2026-05-29 |
| Target | 20 consecutive clean trading days |
| Days complete | 1 |
| Days remaining | 19 |
| Risk breaches to date | 0 |
| Pipeline failures to date | 0 |

---

## Edge Enhancements

Features being researched or validated for production integration. Do not add to `run_pipeline.py` until status = `validated`.

| Enhancement | Status | Experiments | Notes |
|---|---|---|---|
| Market Regime Filter (SPY 200MA) | `rejected` | `666eab98` (baseline), `431fcdbf` (filtered) | Sharpe 1.21→1.17, CAGR −8.87pp, MaxDD +10.57pp. V-shaped recoveries destroy value (2020: −28pp). Not justified. See `experiments/results/regime_filter_v1.md`. Revisit: 50% cash exposure, VIX overlay, longer dataset. |
| Sector Diversification Cap (1/sector) | `rejected` | `219be0de` (baseline), `4f09f27e` (capped) | Sharpe 1.21→1.06 (worst of any enhancement), CAGR −9.22pp, MaxDD +0.78pp (negligible). Cap fired 93.4% of rebalances — universe is structurally tech-heavy. See `experiments/results/sector_cap_v1.md`. Revisit: expand universe to 40–60 symbols, or soft-cap weighting. |
| Expanded Universe (94-sym, all 11 GICS) | `rejected` | `4c32591e` (legacy 20-sym), `6a07e16c` (expanded 94-sym) | Sharpe 1.16→1.01 (−0.15), CAGR −1.72pp, Vol +4.06pp (worse). Adding defensive sectors dilutes signal quality. Legacy concentration is a feature, not a bug. See `experiments/results/expanded_universe_v1.md`. Universe data retained in DB (280,966 bars, 97 symbols) for future research. |

---

## What NOT To Build Yet

- No live trading or real-money execution
- No deep learning or ML models
- No cloud infrastructure (yet — cloud migration queued)
- Do not promote daytrader to `paper` until momentum 20-day period complete + daytrader backtest validated
- Do not build ensemble allocator until both strategies have independent live track records (6+ months each)

---

## Backtest Integrity Checklist

Before any backtest result is considered valid, confirm:

- [ ] No look-ahead bias
- [ ] Point-in-time universe (no survivorship bias)
- [ ] Splits/dividends adjusted
- [ ] Realistic fill assumptions (not mid-price)
- [ ] Slippage modeled
- [ ] Transaction costs included
- [ ] Out-of-sample period held out
- [ ] Logged to experiment tracker

---

## Key Libraries

| Purpose | Library |
|---|---|
| Data validation | `pydantic` |
| Logging | `loguru` |
| Testing | `pytest` |
| Market calendar | `pandas_market_calendars` |
| Scheduling (later) | `Prefect` |
| Market data | `yfinance`, `Finnhub`, `Alpha Vantage` |
| Execution | `Alpaca` (paper first) |
| ORM | `SQLAlchemy` |
| DB | `PostgreSQL` |