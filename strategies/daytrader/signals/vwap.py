"""VWAP and Relative Volume (RVOL) calculators.

VWAP resets at 9:30 ET each day. Feed it bars in order.
RVOL compares current bar volume to the historical average volume
for the same time-of-day window across the last N trading days.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from typing import Optional

import numpy as np
import pandas as pd


class VWAPCalculator:
    """Session VWAP — resets every trading day at market open.

    VWAP = cumulative(price × volume) / cumulative(volume)
    where price = (high + low + close) / 3 (typical price).
    """

    def __init__(self) -> None:
        self._cum_pv: float = 0.0
        self._cum_v:  float = 0.0
        self._current_date: Optional[date] = None

    def reset(self) -> None:
        self._cum_pv = 0.0
        self._cum_v  = 0.0

    def update(self, bar: pd.Series) -> float:
        """Feed one bar, return current VWAP."""
        ts: datetime = bar["timestamp"]
        bar_date = ts.date()

        if bar_date != self._current_date:
            self.reset()
            self._current_date = bar_date

        typical = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3
        volume  = float(bar["volume"])

        self._cum_pv += typical * volume
        self._cum_v  += volume

        if self._cum_v == 0:
            return float(bar["close"])
        return self._cum_pv / self._cum_v

    @property
    def value(self) -> float:
        if self._cum_v == 0:
            return 0.0
        return self._cum_pv / self._cum_v


class RVOLCalculator:
    """Relative Volume — compares current bar volume to same-time historical average.

    Requires a historical bar DataFrame to compute the baseline.
    RVOL = current_volume / avg_volume_at_same_time_of_day

    RVOL > 1.5 signals elevated institutional participation.
    """

    def __init__(self, lookback_days: int = 20) -> None:
        self.lookback_days = lookback_days
        # {time_bucket (HH:MM) → list of historical volumes}
        self._historical: dict[str, list[float]] = defaultdict(list)
        self._averages:   dict[str, float] = {}

    def load_historical(self, bars: pd.DataFrame) -> None:
        """Pre-load historical minute bars to build the same-time averages.

        bars must have: timestamp (tz-aware), volume
        """
        if bars.empty:
            return

        bars = bars.copy()
        bars["_time_key"] = bars["timestamp"].dt.strftime("%H:%M")
        bars["_date"]     = bars["timestamp"].dt.date

        # Keep only the most recent N trading days
        unique_dates = sorted(bars["_date"].unique())[-self.lookback_days:]
        bars = bars[bars["_date"].isin(unique_dates)]

        grouped = bars.groupby("_time_key")["volume"].mean()
        self._averages = grouped.to_dict()

    def compute(self, bar: pd.Series) -> float:
        """Return RVOL for this bar. Returns 1.0 if no historical baseline."""
        ts: datetime = bar["timestamp"]
        time_key = ts.strftime("%H:%M")
        avg = self._averages.get(time_key)
        if not avg or avg == 0:
            return 1.0
        return float(bar["volume"]) / avg


class VWAPBandCalculator:
    """VWAP with standard-deviation bands (institutional support/resistance levels).

    Upper band 1/2: VWAP ± 1σ, ± 2σ
    Used to identify mean-reversion zones and breakout confirmation.
    """

    def __init__(self) -> None:
        self._vwap_calc  = VWAPCalculator()
        self._cum_pv2:   float = 0.0   # cumulative (price² × volume)
        self._cum_v:     float = 0.0
        self._current_date: Optional[date] = None

    def update(self, bar: pd.Series) -> dict[str, float]:
        """Returns dict with vwap, upper1, lower1, upper2, lower2."""
        ts: datetime = bar["timestamp"]
        bar_date = ts.date()
        if bar_date != self._current_date:
            self._cum_pv2 = 0.0
            self._cum_v   = 0.0
            self._current_date = bar_date

        vwap   = self._vwap_calc.update(bar)
        vol    = float(bar["volume"])
        price  = (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3

        self._cum_pv2 += price ** 2 * vol
        self._cum_v   += vol

        variance = max(0.0, self._cum_pv2 / self._cum_v - vwap ** 2) if self._cum_v > 0 else 0.0
        sigma    = variance ** 0.5

        return {
            "vwap":   vwap,
            "upper1": vwap + sigma,
            "lower1": vwap - sigma,
            "upper2": vwap + 2 * sigma,
            "lower2": vwap - 2 * sigma,
        }
