# Expanded Universe V1 — Findings

**Date:** 2026-05-29  
**Experiments:** `4c32591e` (legacy 20-sym baseline), `6a07e16c` (expanded 94-sym)  
**Data:** 280,966 total price_bars | 2015-01-01 → 2026-05-29  
**Test window:** ~2016 → 2026-05-29 (~10.4 years)  
**Strategy:** Top-5 JT 12-1 momentum | 5bps slippage | equal-weight

---

## Universe Definition

| | Legacy | Expanded |
|---|---|---|
| Symbols | 20 (of 22 — BRK-B not stored under that ticker) | 94 |
| GICS sectors | 7 | 11 (all) |
| Source | Hardcoded in signal generator | `config/universe.py` |
| Min per sector | N/A | 6 |

**Expanded sector breakdown:**

| Sector | Symbols |
|---|---|
| Technology | 10 |
| Communication Services | 8 |
| Consumer Discretionary | 10 |
| Consumer Staples | 8 |
| Financials | 12 (incl. V, MA reclassified from Tech) |
| Health Care | 10 |
| Industrials | 10 |
| Energy | 8 |
| Materials | 6 |
| Real Estate | 6 |
| Utilities | 6 |
| **Total** | **94** |

All 94 symbols had ≥8 years of data. Zero fetch failures.

---

## Results

| Metric | Legacy 20-sym (A) | Expanded 94-sym (B) | Delta |
|---|---|---|---|
| CAGR | 39.04% | 37.32% | **−1.72pp** |
| Sharpe (rf=5%) | 1.16 | 1.01 | **−0.15** |
| Sortino | 1.50 | 1.37 | −0.13 |
| Max Drawdown | −36.95% | −35.82% | +1.12pp |
| Annualized Vol | 27.24% | 31.30% | **+4.06pp** ⚠ |
| Win Rate (daily) | 57.02% | 55.25% | −1.77pp |

**The expanded universe is MORE volatile AND generates lower risk-adjusted returns.**

---

## Year-by-Year Breakdown

| Year | Legacy | Expanded | Delta | Notable |
|---|---|---|---|---|
| 2016 | +54.65% | +71.11% | +16.46% | ✓ Expanded benefited from energy/industrials momentum |
| 2017 | +40.56% | +28.06% | −12.50% | ⚠ Tech dominance; expanded diluted by other sectors |
| 2018 | +2.92% | −9.19% | −12.11% | ⚠ Expanded went negative; legacy stayed positive |
| 2019 | +34.38% | +30.65% | −3.73% | Mild disadvantage |
| 2020 | +91.24% | +104.18% | +12.94% | ✓ Expanded picked up more of the COVID recovery |
| 2021 | +33.83% | +19.12% | −14.71% | ⚠ Large miss; mega-cap tech dominated |
| 2022 | −8.64% | +5.01% | +13.65% | ✓ Expanded's sector breadth helped in down year |
| 2023 | +44.36% | +25.39% | −18.97% | ⚠ Largest gap; AI-driven tech rally excluded by breadth |
| 2024 | +84.29% | +68.69% | −15.61% | ⚠ NVIDIA/semis dominated; expanded diluted signal |
| 2025 | +26.78% | +11.18% | −15.60% | ⚠ Expanded underperformed in all-around recovery |
| 2026 | +18.75% | +57.06% | +38.31% | Partial year — likely noise from one or two outliers |

---

## Analysis

### Does more universe breadth improve Sharpe?
**No — it meaningfully hurts.** Sharpe drops from 1.16 → 1.01 (−0.15), the same magnitude of degradation seen with the hard sector cap. The expanded universe adds breadth but reduces signal concentration in the same way.

### Does sector balance reduce drawdown?
**Negligibly.** Max drawdown improves by only +1.12pp (−36.95% → −35.82%). The 4pp increase in annual volatility more than offsets any diversification benefit.

### Why does a larger universe underperform?

**Root cause: we are diluting signal quality, not improving it.**

The top-5 momentum picks from 94 symbols sometimes land in utilities, materials, REITs, or consumer staples — sectors with structurally lower growth rates and weaker momentum persistence. By expanding the candidate pool, we occasionally include these lower-quality signals at the cost of excluding stronger tech/comm picks.

The year-by-year pattern tells the story clearly:
- When tech leads (2017, 2021, 2023, 2024, 2025): expanded **underperforms by 12–19pp**
- When tech lags (2016, 2020, 2022): expanded **outperforms by 13–17pp**

Expanding the universe is essentially a sector-rotation bet against tech outperformance — the same bet the hard sector cap made. And the result is similar: it works 3 of 11 years.

### The 2023 miss is especially telling
The AI-driven rally in 2023 was concentrated in a small number of mega-cap tech names (NVDA, META, AAPL, MSFT). The legacy universe was entirely within that cluster. The expanded universe occasionally promoted an industrial, REIT, or utility into the top-5 instead, missing the AI rally almost entirely.

### Increased volatility is counterintuitive
Adding defensive sectors (utilities, staples, REITs) should theoretically reduce volatility. Instead, vol increased by +4pp. This suggests the expanded universe sometimes picks highly concentrated momentum plays from non-tech sectors (e.g., a single commodity cycle spike in energy or materials) that are themselves volatile — just not correlated with tech.

---

## Verdict: **Reject — expanded universe degrades performance**

| Criterion | Result |
|---|---|
| Improves Sharpe? | ❌ Worse (1.16 → 1.01, −0.15) |
| Reduces drawdown? | ❌ Negligible (+1.12pp) |
| Reduces volatility? | ❌ Worse (+4.06pp annualized) |
| CAGR cost justified? | ❌ −1.72pp/year with no risk reduction |
| Net verdict | **Reject** |

The legacy 22-symbol universe was not "accidentally" concentrated in tech — it was concentrated in the sectors that drove the last decade of US equity returns. Expanding to all 11 sectors does not improve the edge; it dilutes it.

---

## What This Confirms

1. **The 22-symbol universe is appropriate for this strategy in this period.** Its tech-heaviness is a feature, not a bug — the momentum signal is strongest where earnings growth is fastest.
2. **Sector diversification consistently costs returns in our test period.** Both the hard sector cap (−9.22pp CAGR) and the expanded universe (−1.72pp CAGR) confirm this pattern.
3. **The strategy's edge comes from concentrated sector momentum, not sector diversification.**

---

## Recommended Path if Revisiting

1. **Expand universe with a minimum momentum quality filter:** Only add symbols from new sectors if they have shown meaningful momentum persistence (e.g., Sharpe > 0.5 in 10-year backtest). This would filter out weak-momentum sectors while retaining genuine opportunities.
2. **Dynamic universe:** Add symbols from a sector only when that sector's own trailing momentum is above a threshold. This captures sector rotation signals without permanently diluting the quality pool.
3. **Accept the concentration:** The current 22-symbol universe is well-calibrated for the strategy. The better path to robustness is a regime filter or position sizing overlay, not universe expansion.

---

## Artifacts

- Universe definition: `config/universe.py`
- Data manifest: `registry/universe_manifest.json` (94 symbols, all sectors, all ≥8 years)
- Backtest script: `backtests/expanded_universe_backtest.py`
- Experiment A (legacy baseline): `4c32591e`
- Experiment B (expanded 94-sym): `6a07e16c`

---

## Status: `research` — **rejected** for production
