"""Market regime filter based on SPY 200-day simple moving average.

LOGIC
-----
- Regime = BULL when SPY adj_close > 200-day SMA
- Regime = BEAR when SPY adj_close < 200-day SMA
- Dates where the MA is undefined (first 199 days) are excluded from output

DATA SOURCE
-----------
Reads from price_bars table only — no external API calls.
Uses ingestion/calendar.py for trading-day awareness.

NO LOOK-AHEAD
-------------
SMA at date T uses prices[T-199 : T] (200 bars ending at T, inclusive).
The regime for date T is known at market close on T, before any signal
generation for T+1. Used by the backtest as a filter on T-1 regime → T
execution, which is strictly no look-ahead.

OUTPUT
------
Returns a pd.Series indexed by date (datetime.date) with values 'bull'/'bear'.
Each row is also validated as a RegimeSignal Pydantic schema.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from loguru import logger
from sqlalchemy import text

from data.database import get_session
from data.schemas.regime import RegimeSignal

BENCHMARK = "SPY"
MA_WINDOW = 200


def load_spy_prices(as_of: date | None = None) -> pd.Series:
    """Load all SPY adj_close from price_bars up to as_of date.

    Returns a pd.Series indexed by date, sorted ascending.
    """
    as_of = as_of or date.today()
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT date, adj_close
                FROM price_bars
                WHERE symbol = :symbol
                  AND date <= :as_of
                ORDER BY date
            """),
            {"symbol": BENCHMARK, "as_of": as_of},
        ).fetchall()

    if not rows:
        raise ValueError(f"No {BENCHMARK} price data found in price_bars up to {as_of}.")

    series = pd.Series(
        {r.date: float(r.adj_close) for r in rows},
        name="adj_close",
    )
    series.index = pd.to_datetime(series.index)
    return series


def compute_regime(
    prices: pd.Series,
    ma_window: int = MA_WINDOW,
    validate: bool = True,
) -> pd.Series:
    """Compute daily regime from a price series.

    Args:
        prices:    pd.Series indexed by date, values = adj_close.
        ma_window: SMA lookback in days. Default 200.
        validate:  If True, validate each row as a RegimeSignal schema.

    Returns:
        pd.Series indexed by date with string values 'bull' or 'bear'.
        Only dates where MA is defined (>= ma_window bars of history) are included.
    """
    ma = prices.rolling(window=ma_window, min_periods=ma_window).mean()

    # Drop dates where MA is undefined
    valid = prices[ma.notna()].copy()
    valid_ma = ma[ma.notna()].copy()

    regimes = pd.Series(
        index=valid.index,
        data=["bull" if p > m else "bear" for p, m in zip(valid, valid_ma)],
        name="regime",
        dtype=str,
    )

    if validate:
        errors = 0
        for dt, regime_val in regimes.items():
            price_val = float(valid.loc[dt])
            ma_val = float(valid_ma.loc[dt])
            try:
                RegimeSignal(
                    symbol=BENCHMARK,
                    as_of_date=dt.date() if hasattr(dt, "date") else dt,
                    regime=regime_val,
                    price=price_val,
                    ma_value=ma_val,
                    ma_window=ma_window,
                    distance_pct=(price_val - ma_val) / ma_val,
                )
            except Exception as exc:
                logger.warning(f"RegimeSignal validation failed for {dt}: {exc}")
                errors += 1
        if errors:
            logger.warning(f"[regime] {errors} validation errors in {len(regimes)} rows.")
        else:
            logger.debug(f"[regime] All {len(regimes)} RegimeSignal rows validated.")

    return regimes


def get_regime_series(as_of: date | None = None, ma_window: int = MA_WINDOW) -> pd.Series:
    """Top-level entry point: load SPY prices from DB and return daily regime Series.

    Returns:
        pd.Series indexed by pd.Timestamp with values 'bull' or 'bear'.
    """
    prices = load_spy_prices(as_of=as_of)
    regimes = compute_regime(prices, ma_window=ma_window)

    bull_days = (regimes == "bull").sum()
    bear_days = (regimes == "bear").sum()
    total = len(regimes)
    logger.info(
        f"[regime] {BENCHMARK} {ma_window}-day SMA filter | "
        f"{total} days | bull={bull_days} ({bull_days/total:.1%}) | "
        f"bear={bear_days} ({bear_days/total:.1%}) | "
        f"range={regimes.index[0].date()} → {regimes.index[-1].date()}"
    )
    return regimes
