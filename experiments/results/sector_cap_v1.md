# Sector Cap V1 — Findings

**Date:** 2026-05-29  
**Experiments:** `219be0de` (baseline), `4f09f27e` (sector cap)  
**Data:** 2,867 trading days × 22 symbols | 2015-01-02 → 2026-05-28  
**Test window:** 2016-02-03 → 2026-05-28 (2,594 days, ~10.4 years)  
**Strategy:** Top-5 JT 12-1 momentum | 5bps slippage | equal-weight

---

## Cap Definition

- **Rule:** At most 1 stock per GICS sector in the top-5 portfolio
- **Algorithm:** Greedy rank-order — walk the momentum-ranked list; include a symbol only if its sector is not yet represented
- **Sector map:** 22-symbol universe across Technology, Communication Services, Consumer Discretionary, Consumer Staples, Financials, Health Care, Energy
- **V/MA:** Classified as Technology (GICS IT sub-industry: data processing & outsourced services)
- **BRK-B:** Classified as Financials

### Final rebalance snapshot (2026-05-28 proxy)

| Rank | Baseline | Sector | → Capped | Sector | Note |
|---|---|---|---|---|---|
| 1 | AVGO | Technology | AVGO | Technology | unchanged |
| 2 | GOOGL | Comm. Services | GOOGL | Comm. Services | unchanged |
| 3 | **NVDA** | **Technology** | **JNJ** | **Health Care** | ← DROPPED (Tech collision) |
| 4 | JNJ | Health Care | TSLA | Consumer Disc. | reordered |
| 5 | TSLA | Consumer Disc. | XOM | Energy | promoted from rank 6+ |

Cap fired; NVDA dropped because AVGO already held the Technology slot.

---

## Results

| Metric | Baseline (A) | + Sector Cap (B) | Delta |
|---|---|---|---|
| CAGR | 40.98% | 31.76% | **−9.22%** |
| Sharpe (rf=5%) | 1.21 | 1.06 | **−0.15** |
| Sortino | 1.57 | 1.40 | −0.18 |
| Max Drawdown | −36.95% | −36.16% | +0.78pp |
| Annualized Vol | 27.35% | 24.02% | −3.33pp |
| Win Rate (weekly) | 58.81% | 58.81% | 0.00% |
| Annual Turnover | 469% | 512% | +43pp |
| Cap Fire Rate | — | **93.4%** | — |
| Cap Promotions | — | 802 total | — |

---

## Year-by-Year Breakdown

| Year | Baseline | + Cap | Delta | Notable |
|---|---|---|---|---|
| 2016 | +66.70% | +55.48% | −11.22% | Cap displaced strong tech momentum |
| 2017 | +37.77% | +30.60% | −7.17% | Tech sector dominance suppressed by cap |
| 2018 | +6.70% | −2.67% | −9.37% | ⚠ Cap introduced losing positions |
| 2019 | +36.39% | +24.28% | −12.11% | Forced sector diversity underperformed |
| 2020 | +99.07% | +54.63% | −44.44% | ⚠ Largest gap — cap blocked FAANG/tech during COVID rally |
| 2021 | +36.26% | +34.52% | −1.74% | Near-neutral; diverse sectors both up |
| 2022 | −5.17% | −15.12% | −9.95% | ⚠ Capped positions included weaker sectors |
| 2023 | +45.24% | +45.85% | +0.61% | Near-neutral; sector breadth helped slightly |
| 2024 | +82.06% | +74.89% | −7.17% | Tech cap cost NVIDIA gains |
| 2025 | +24.12% | +33.27% | +9.15% | ✓ Cap helped — diversified portfolio outperformed |
| 2026 | +21.58% | +15.95% | −5.63% | YTD partial year |

---

## Analysis

### Does the cap improve Sharpe?
**No — it meaningfully hurts.** Sharpe drops from 1.21 → 1.06 (−0.15), the largest Sharpe penalty of any enhancement tested so far. The cap actively degrades risk-adjusted returns, not just raw returns.

### Does it reduce drawdown?
**Negligibly.** Max drawdown improves by only +0.78pp (−36.95% → −36.16%). This is essentially noise — the cap provides almost zero downside protection despite dramatically changing portfolio composition.

### Does diversification improve or hurt returns?
**Hurts across nearly every year.** The cap fired in 93.4% of all rebalances (485 of 519), displacing 802 positions across the test window. This means the sector constraint was almost always binding — the top momentum stocks in our universe are persistently concentrated in Technology and Communication Services.

**Root cause — our universe is structurally tech-heavy:**
- Technology: AAPL, MSFT, NVDA, AVGO, V, MA (6 of 20 equities = 30%)
- Communication Services: GOOGL, META (10%)
- These two sectors account for 40% of our universe AND dominate momentum rankings in 8 of 11 test years

The cap's effect is not genuine diversification — it's forced exclusion of the highest-momentum signals in favour of lower-momentum stocks from energy, consumer staples, and financials. The promoted stocks (rank 6–10) don't have better risk-adjusted returns; they're simply from different sectors.

**2020 is the clearest proof:** The baseline captured the COVID-era FAANG/tech/growth rally (+99%), while the cap forced inclusion of energy, consumer staples, and financials that lagged the recovery by 6–12 months (net +54.6%). This alone is nearly 45pp of terminal wealth destroyed by the constraint.

**2025 is the only year the cap helped (+9.15pp):** The sector-diverse portfolio benefited from energy/staples outperformance while tech pulled back. This is the scenario the cap was designed for — but it represents 1 of 11 years.

### Why the penalty is so severe in this specific universe
Our 22-symbol universe was selected for liquidity and market-cap representation, not sector balance. It happens to be heavily tilted toward the sectors that have driven the last decade of US equity returns. A sector cap imposes a structural bet against tech/comm outperformance — which is the dominant factor in this period.

A sector-balanced universe (3–4 symbols per sector across 8+ sectors) would likely show different results.

---

## Verdict: **Reject — do not promote to production**

The sector diversification cap fails on every relevant dimension:

| Criterion | Result |
|---|---|
| Improves Sharpe? | ❌ Worse (1.21 → 1.06) |
| Reduces drawdown? | ❌ Negligible (+0.78pp) |
| CAGR cost justified? | ❌ −9.22pp/year not justified by protection |
| Active in practice? | ⚠️ 93% fire rate — almost always constraining |
| Net verdict | **Reject** |

The constraint is too blunt for our specific universe and time period. It removes the signal (sector momentum concentration) rather than the risk.

### Recommended path if revisiting:
1. **Expand the universe** to 40–60 symbols with deliberate sector balance (4–5 per sector). The current 22-symbol universe is structurally inappropriate for a hard sector cap.
2. **Soft cap instead of hard cap:** Penalise concentration rather than forbidding it (e.g., reduce weight for a second stock from the same sector rather than excluding it entirely).
3. **Sector momentum overlay:** Rather than capping at 1 per sector, weight sectors by their own trailing momentum — overweight outperforming sectors, underweight lagging ones.
4. **Revisit after universe expansion:** If the universe grows to include materials, industrials, utilities, real estate, sector balance becomes achievable without sacrificing signal quality.

---

## Status: `research` — **rejected** for production
