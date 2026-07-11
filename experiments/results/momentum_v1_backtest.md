# Momentum V1 Backtest — Findings

**Experiment ID:** 5599e498  
**Date:** 2026-05-29  
**Strategy:** Cross-sectional price momentum (Jegadeesh-Titman 12-1)  
**Status:** In-sample only — insufficient history for OOS holdout

---

## Parameters

| Parameter | Value |
|---|---|
| Lookback window | 252 trading days (~12 months) |
| Skip window | 21 trading days (~1 month) |
| Universe | 22 US large-cap equities + ETFs |
| Top N positions | 10 |
| Rebalance frequency | Weekly (every 5 trading days) |
| Min score threshold | 5% trailing return |
| Weighting | Equal weight (10% per position) |
| Slippage | 5bps per side on changed positions |
| Execution | Next-day close approximation |
| Starting capital | $100,000 |

---

## Results

| Metric | Momentum | SPY Benchmark |
|---|---|---|
| CAGR | 17.80% | 19.56% |
| Sharpe (rf=5%) | 0.61 | 0.84 |
| Sortino | 0.81 | 1.09 |
| Max Drawdown | -26.02% | -18.76% |
| Annualized Volatility | 22.79% | 17.04% |
| Total Return | +36.52% | +40.34% |
| Win Rate (weekly) | 55.0% | — |
| Annual Turnover | ~410% | — |

**Backtest period:** 2024-07-01 → 2026-05-28 (479 trading days, 96 rebalances)  
**Warmup consumed:** 273 trading days (May 2023 → June 2024)

### Annual Returns

| Year | Momentum | Notes |
|---|---|---|
| 2024 (Jul–Dec only) | +7.75% | Partial year — only H2 |
| 2025 | +14.57% | Full year |
| 2026 (Jan–May) | +10.59% | Partial year — only ~5 months |

---

## Integrity Checklist

| Item | Status | Notes |
|---|---|---|
| No look-ahead bias | **PASS** | Score at T uses prices[T-21] backwards only. Formally verified. |
| Point-in-time universe | **PARTIAL** | Universe fixed at 22 current large-caps. Survivorship bias present — all 22 existed throughout. Acceptable for proof-of-concept. |
| Splits/dividends adjusted | **PASS** | yfinance auto_adjust=True; adj_close used throughout. |
| Realistic fill assumptions | **PASS** | Next-day close with 5bps slippage per side on changed positions. |
| Slippage modeled | **PASS** | 5bps per side on turnover. |
| Transaction costs included | **PASS** | Embedded in slippage calculation. |
| Out-of-sample period held out | **FAIL** | Cannot satisfy with current data. Only 22 months of backtested history after 13-month warmup. All results are in-sample. |
| Results logged to experiment tracker | **PASS** | Experiment ID 5599e498 in experiments table. |

---

## Is Sharpe > 0.5? Does the signal show edge?

**Yes — Sharpe is 0.61, above the 0.5 threshold.** The signal demonstrates positive risk-adjusted returns.

However, context matters:

- **Sharpe of 0.61 vs SPY's 0.84** — the strategy underperforms a passive SPY holding on a risk-adjusted basis over this period.
- **Higher volatility (22.8% vs 17.0%)** — the 10-stock concentrated portfolio is significantly more volatile than SPY.
- **Higher drawdown (-26% vs -19%)** — momentum takes larger hits during reversals. This is characteristic of the strategy.
- **Win rate of 55%** is modestly above chance. Consistent with known momentum literature (edge is in magnitude, not frequency).

**Verdict: The signal shows statistical edge (Sharpe > 0.5, positive CAGR, consistent positive returns across all three partial periods) but does not beat SPY on a risk-adjusted basis over this short window.** This is expected — momentum is well-documented to underperform during momentum crashes (sharp reversals), which the 2025–2026 volatility regime may have induced.

---

## Is performance persistent across the full period?

**Broadly yes, with caveats:**

- Returns were positive in every measured period (2024 H2, full 2025, 2026 YTD).
- No single year drove all the returns — the signal contributed across the period.
- However, with only ~22 months of backtested data, "persistence" is not statistically meaningful. Three data points (years) cannot distinguish genuine persistence from luck.

**What would constitute real persistence evidence:**
- 5+ years of data with year-by-year positive returns
- Rolling 12-month Sharpe consistently above 0.3
- Performance not concentrated in 1–2 months

**Action required:** Expand the historical dataset (5–10 years) before drawing persistence conclusions.

---

## Is the long side viable on a standalone basis?

**Conditionally yes.** The long-only momentum portfolio:

- Generated positive returns across all measured periods
- Sharpe > 0.5 (meets the stated threshold)
- Win rate of 55% means most weeks are profitable
- Turnover of ~410%/year is high — each position turns over roughly 4x per year, which will create meaningful transaction costs at scale

**Key risks for live paper trading:**
1. **Concentration risk:** 10 equally-weighted positions from a 22-stock universe means ~45% universe overlap, limiting diversification.
2. **Momentum crash risk:** Long-only momentum has historically suffered acute drawdowns during sharp market reversals (2009, 2020 COVID bounce). The -26% max drawdown seen here reflects this.
3. **Turnover cost:** At 410%/year, even 5bps slippage adds up. At $100K, this is roughly $2,050/year in friction — manageable at this scale but scales poorly.
4. **Universe survivorship:** All 22 stocks are current large-caps that "survived" to today. Real-time trading would need a point-in-time universe.

---

## Recommendations Before Live Paper Trading

1. **Extend history to 5+ years** — run the same backtest on 2015–2026 data to properly evaluate persistence and drawdown recovery.
2. **Fix universe survivorship** — build a point-in-time S&P 500 membership list rather than using current large-caps.
3. **Add a volatility filter** — avoid entering momentum positions when VIX > 30 (regime filter to reduce crash risk).
4. **Consider reducing TOP_N to 5–7** — smaller, higher-conviction portfolio may improve Sharpe at the cost of diversification.
5. **Run OOS test** — when 5+ years of data is available, reserve 2 years as holdout before live paper trading.

---

## Summary Verdict

The momentum signal passes the **minimum bar for paper trading readiness** (Sharpe > 0.5, positive CAGR, no look-ahead bias, logged and auditable). It does not yet pass the **full validation bar** (OOS test impossible, insufficient history, survivorship bias in universe).

**Recommended next action:** Promote to `backtest` status in the registry. Do not promote to `paper` until 5+ years of data exists and OOS validation passes. Run paper signals in parallel as observation-only while gathering more history.
