# Regime Filter V1 — Findings

**Date:** 2026-05-29  
**Experiments:** `666eab98` (baseline), `431fcdbf` (regime filter)  
**Data:** 2,867 trading days × 22 symbols | 2015-01-02 → 2026-05-28  
**Test window:** 2016-02-03 → 2026-05-28 (2,594 days, ~10.4 years)  
**Strategy:** Top-5 JT 12-1 momentum | 5bps slippage | equal-weight

---

## Filter Definition

- **Benchmark:** SPY
- **Signal:** 200-day simple moving average of adj_close
- **BULL:** SPY close > 200-day SMA → stay long top-5 momentum
- **BEAR:** SPY close < 200-day SMA → liquidate, hold 100% cash
- **Execution:** Regime at T-1 determines positions at T (no look-ahead)
- **Regime series:** 2,668 valid days | bull=2,205 (82.6%) | bear=463 (17.4%)

---

## Results

| Metric               | Baseline (A) | + Regime Filter (B) | Delta     |
|---|---|---|---|
| CAGR                 | 40.98%       | 32.11%              | **-8.87%** |
| Sharpe (rf=5%)       | 1.21         | 1.17                | -0.04     |
| Sortino              | 1.57         | 1.53                | -0.05     |
| Max Drawdown         | -36.95%      | **-26.38%**         | **+10.57pp** |
| Annualized Vol       | 27.35%       | 21.51%              | -5.85pp   |
| Win Rate (weekly)    | 58.81%       | 49.91%              | -8.91pp   |
| Annual Turnover      | 469%         | 517%                | +48pp     |
| % Time in Cash       | 0%           | 16.5%               | —         |
| Regime Switches      | —            | 53                  | —         |

---

## Year-by-Year Breakdown

| Year | Baseline | + Filter | Delta    | Notable |
|---|---|---|---|---|
| 2016 | +66.70%  | +41.04%  | -25.66%  | Filter cautious early in year |
| 2017 | +37.77%  | +37.77%  | 0%       | All-bull year, no filter effect |
| 2018 | +6.70%   | +18.87%  | **+12.17%** | Filter avoided Q4 selloff ✓ |
| 2019 | +36.39%  | +23.21%  | -13.18%  | Cash drag during recovery |
| 2020 | +99.07%  | +70.88%  | -28.19%  | Filter missed V-shaped recovery |
| 2021 | +36.26%  | +36.26%  | 0%       | All-bull year |
| 2022 | -5.17%   | -12.94%  | -7.77%   | ⚠ Filter hurt — exited then re-entered at worse prices |
| 2023 | +45.24%  | +35.92%  | -9.32%   | Cash drag during strong bull |
| 2024 | +82.06%  | +82.06%  | 0%       | All-bull year |
| 2025 | +24.12%  | +7.69%   | -16.43%  | ⚠ Filter underperformed |
| 2026 | +21.58%  | +14.32%  | -7.26%   | YTD partial year |

---

## Analysis

### Does the filter improve Sharpe?
**No — marginally worse.** Sharpe drops from 1.21 → 1.17 (−0.04). The cash drag costs
more in risk-adjusted terms than the drawdown reduction provides. The baseline Sharpe of
1.21 is already exceptional; the filter does not push past it.

### Does it reduce max drawdown?
**Yes — meaningfully.** Max drawdown improves from −36.95% → −26.38%, a +10.57pp reduction.
This is the filter's clearest win. It correctly avoided or reduced exposure during the 2018 Q4
selloff, part of the 2020 COVID crash, and portions of the 2022 bear market.

### What is the cost in CAGR?
**−8.87pp per year.** Over a 10-year period this compounds dramatically: baseline turns
$100K → $3.43M (+3,330%), filtered turns $100K → $1.76M (+1,658%). The filter roughly
halves terminal wealth by staying in cash during sharp recoveries (2019, 2020, 2023).

### Key failure modes
1. **V-shaped recoveries (2020):** SPY crashed below 200-day MA in March 2020, triggering
   cash exit. The recovery was so fast (V-shape) that the filter missed most of the upside
   before SPY recrossed the MA. Cost: −28pp in 2020.

2. **Whipsaw (2022):** During the 2022 bear market the strategy exited on SPY MA crossovers
   but the momentum stocks it was holding were still outperforming (energy, healthcare). Exiting
   and re-entering cost more than staying invested. Net effect: −7.77pp vs baseline.

3. **Bull-market cash drag (2016, 2019, 2023):** Any time spent in cash during a strong bull
   market is a direct CAGR penalty with no offsetting protection. 2016 alone cost 25pp.

### When does the filter win?
The filter adds the most value in **prolonged bear markets** (not crashes). It would have excelled
in 2000–2002 and 2008–2009 — both sustained bear markets where SPY stayed below its 200-day MA
for 12–24 months. In our 10-year dataset (2015–2026), such sustained bears were largely absent.
The only sustained bear was 2022, and even there the filter underperformed because momentum
factors continued working even as SPY declined.

---

## Verdict: **Do not promote to production in current form**

The 200-day MA regime filter is a valid risk-reduction mechanism but fails the
cost-benefit test against our current validated baseline:

- **Sharpe is lower:** 1.17 vs 1.21 — the filter does not improve risk-adjusted returns
- **CAGR cost is too high:** −8.87pp/year halves terminal wealth over a decade
- **The drawdown improvement (+10.57pp) does not justify the return sacrifice** at this
  strategy's risk tolerance (10% total DD halt already enforced by risk engine)

The filter is most appropriate for strategies with lower inherent Sharpe (<0.8) that
need explicit bear protection. Our momentum strategy already has strong cross-sectional
defence — in 2022 it lost only −5.2% vs SPY's −18.2% without any regime filter.

### Recommended path if revisiting:
1. **Test a tighter filter:** 50-day MA or price vs 200-day MA with a 2% buffer (reduce whipsaw)
2. **Test partial exposure:** 50% cash in bear regime instead of 100% (reduce cash drag)
3. **Combine with volatility filter:** Only go to cash when regime = BEAR AND VIX > 30
4. **Test on a longer dataset** that includes 2000–2010 where sustained bears are the norm

---

## Status: `research` — not validated for production
