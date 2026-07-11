"""
Price momentum features. Pure feature engineering — no signal logic here.

LOOK-AHEAD BIAS AUDIT (completed 2026-05-29)
=============================================
Function: compute_momentum_score(prices, lookback=252, skip_last=21)

Formal proof of no look-ahead bias
-----------------------------------
At signal date T, prices series contains data through T (inclusive).

Step 1:  lagged = prices.shift(skip_last)
         → lagged[T] = prices[T - 21]

Step 2:  lagged.pct_change(lookback).iloc[-1]
         = lagged[T] / lagged[T - 252] - 1
         = prices[T - 21] / prices[T - 273] - 1

The score at T uses prices from the window [T-273, T-21] only.
Prices in [T-20, T] — the most recent 21 trading days — never enter
the calculation. This is structurally guaranteed by .shift(skip_last)
applied before .pct_change().

The skip window (skip_last=21 ≈ 1 month) implements the Jegadeesh-Titman
"skip month" that removes the short-term reversal effect.

Loader constraint: _load_prices() filters .where(date <= as_of_date),
so no future prices are loaded either.

Verdict: CLEAN — no look-ahead bias.

Notes
------
- The score is a TRAILING return, not a prediction. No future data assumed.
- Only adj_close is used (split/dividend adjusted).
- The universe is fixed at ingestion time — no forward-looking universe
  selection within signal generation.
"""
import pandas as pd


def compute_total_return(prices: pd.Series, lookback: int) -> pd.Series:
    """Total return over lookback bars."""
    return prices.pct_change(periods=lookback)


def compute_momentum_score(
    prices: pd.Series,
    lookback: int = 252,
    skip_last: int = 21,
) -> pd.Series:
    """Jegadeesh-Titman 12-1 momentum score.

    Returns the trailing (lookback)-bar return, excluding the most recent
    (skip_last) bars. Score at index T = prices[T-skip_last] / prices[T-lookback-skip_last] - 1.
    """
    if len(prices) < lookback + skip_last:
        return pd.Series(dtype=float)
    lagged = prices.shift(skip_last)
    return lagged.pct_change(periods=lookback)


def rank_cross_sectional(scores: pd.Series) -> pd.Series:
    """Percentile rank within cross-section (0=worst, 1=best)."""
    return scores.rank(pct=True)
