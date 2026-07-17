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

- **`positions_data.entry_price` is 0 for all positions** → `entry_pnl` and
  `entry_pnl_pct` are all 0, so every position P&L reads +0.00%. Affects Home and
  Stream (both consume `_load_chart_data()`). Entry lookup against fills is not
  resolving.

- **Two books are presented as one.** `_load_chart_data()` returns Alpaca account NAV
  (~$25k, mostly cash, crypto fills in the feed) alongside momentum paper-model
  positions (~$96k gross across 5 equities). The Command Center gets away with this
  because each HUD tile is separately labelled; any view that composes them into a
  single narrative (like Stream) will misrepresent. Decide which book a display
  surface represents before shipping it.

## Known Fixes Applied

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

## Pending Infrastructure Tasks

- [ ] Dashboard cosmetic overhaul — hyper-tech, modern, premium fintech aesthetic.
  Direction: dark theme, tight data density, monospace numbers, minimal chrome,
  one or two accent colors max. Less Streamlit boilerplate, more Bloomberg terminal
  meets modern SaaS dashboard. In progress — font/CSS pass done, deeper layout
  work remaining.

- [~] The Blob — 8-bit pixel character that reacts to live trader state.
  **Read `dashboard/BLOB.md` before touching `dashboard/blob.js`.** It is the
  design contract: the 10fps tick, the locked palette and the always-pink rule
  are deliberate and look like bugs if you don't know why.
  Status (2026-07-17): **now sprite-driven** — the goofy-slime redesign, two
  48×48 sheets (`blob_body.png` + `blob_eyes.png`) blitted by blob.js, inlined
  as base64. Shading is cel + gloss now, **not Bayer dither** (see BLOB.md's
  STATUS banner). Regenerate with `scripts/gen_blobby_ref.py`, re-embed with
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

    **The pointer** (`.t-point`, `pointAt()`) is the Gen-1 menu cursor, parked on the slot
    during the 500ms wind-up. **Sells/rolls only** — a constraint, not a preference: an
    entry has no tile to point at until the impact creates it.

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