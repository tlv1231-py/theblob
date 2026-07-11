"""Opening Range Breakout (ORB) signal.

Defines the opening range as the high/low of the first N minutes after open
(default: 9:30â€“9:44 ET). Generates a directional signal when price closes a
1-minute bar above (long) or below (short) the range with meaningful volume.

The range is recalculated fresh each trading day.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Optional

import pandas as pd


class Direction(str, Enum):
    LONG  = "long"
    SHORT = "short"
    FLAT  = "flat"


@dataclass
class OpeningRange:
    symbol: str
    date: date
    high: float
    low: float
    midpoint: float = field(init=False)
    height: float   = field(init=False)

    def __post_init__(self) -> None:
        self.midpoint = (self.high + self.low) / 2
        self.height   = self.high - self.low

    def height_pct(self) -> float:
        return self.height / self.midpoint

    def breakout_long_level(self, buffer_pct: float = 0.0005) -> float:
        return self.high * (1 + buffer_pct)

    def breakout_short_level(self, buffer_pct: float = 0.0005) -> float:
        return self.low * (1 - buffer_pct)

    def stop_for_long(self) -> float:
        """Stop loss for a long entry = range midpoint."""
        return self.midpoint

    def stop_for_short(self) -> float:
        """Stop loss for a short entry = range midpoint."""
        return self.midpoint

    def target(self, direction: Direction, multiplier: float = 2.0) -> float:
        """Price target at NÃ— range height from entry."""
        if direction == Direction.LONG:
            return self.high + self.height * multiplier
        return self.low - self.height * multiplier


@dataclass
class ORBSignal:
    symbol: str
    direction: Direction
    bar_time: datetime
    bar_close: float
    opening_range: OpeningRange
    entry_price: float            # aggressive limit price
    stop_price: float
    target1_price: float          # 1:1 R:R
    target2_price: float          # 2:1 R:R
    rvol: float                   # relative volume at signal bar
    vwap: float                   # VWAP at signal bar
    momentum_aligned: bool        # True if The Blob momentum agrees
    score: float                  # composite 0â€“1 signal quality

    @property
    def risk_per_share(self) -> float:
        return abs(self.entry_price - self.stop_price)

    @property
    def reward_per_share(self) -> float:
        return abs(self.target2_price - self.entry_price)

    @property
    def rr_ratio(self) -> float:
        if self.risk_per_share == 0:
            return 0.0
        return self.reward_per_share / self.risk_per_share


class OpeningRangeDetector:
    """Builds and tracks the opening range for one symbol per day.

    Feed it 1-minute bars in chronological order. Once the range window
    closes it emits ORBSignal objects when breakout conditions are met.
    """

    def __init__(
        self,
        symbol: str,
        range_minutes: int       = 15,
        buffer_pct: float        = 0.0005,
        min_range_pct: float     = 0.002,
        max_range_pct: float     = 0.030,
        market_open: time        = time(9, 30),
    ) -> None:
        self.symbol         = symbol
        self.range_minutes  = range_minutes
        self.buffer_pct     = buffer_pct
        self.min_range_pct  = min_range_pct
        self.max_range_pct  = max_range_pct
        self.market_open    = market_open

        self._range_bars:  list[pd.Series] = []
        self._range:       Optional[OpeningRange] = None
        self._range_done   = False
        self._triggered    = False           # only one signal per day
        self._current_date: Optional[date] = None

    @property
    def opening_range(self) -> Optional[OpeningRange]:
        return self._range

    def reset(self) -> None:
        """Call at the start of each trading day."""
        self._range_bars  = []
        self._range       = None
        self._range_done  = False
        self._triggered   = False

    def feed(
        self,
        bar: pd.Series,
        vwap: float,
        rvol: float,
        momentum_aligned: bool,
    ) -> Optional[ORBSignal]:
        """Process one 1-minute bar. Returns ORBSignal if breakout fires, else None.

        bar must have: open, high, low, close, volume, timestamp (tz-aware ET)
        """
        ts: datetime = bar["timestamp"]
        bar_date = ts.date()

        # Reset on new day
        if bar_date != self._current_date:
            self.reset()
            self._current_date = bar_date

        bar_time = ts.time()
        range_close = time(
            self.market_open.hour,
            self.market_open.minute + self.range_minutes - 1,
            59,
        )

        # Accumulate opening range bars
        if not self._range_done:
            if bar_time >= self.market_open and bar_time <= range_close:
                self._range_bars.append(bar)
            if bar_time > range_close and self._range_bars:
                self._range = self._build_range(bar_date)
                self._range_done = True
            return None

        # Range is locked â€” check for breakout on subsequent bars
        if self._triggered or self._range is None:
            return None

        r = self._range

        # Quality filter: range too tight or too wide
        rng_pct = r.height_pct()
        if rng_pct < self.min_range_pct or rng_pct > self.max_range_pct:
            return None

        close = float(bar["close"])
        direction = Direction.FLAT

        if close > r.breakout_long_level(self.buffer_pct):
            direction = Direction.LONG
        elif close < r.breakout_short_level(self.buffer_pct):
            direction = Direction.SHORT

        if direction == Direction.FLAT:
            return None

        self._triggered = True

        # Entry price: aggressive limit just through breakout level
        if direction == Direction.LONG:
            entry  = r.breakout_long_level(self.buffer_pct * 1.4)
            stop   = r.stop_for_long()
            t1     = r.target(direction, multiplier=1.0)
            t2     = r.target(direction, multiplier=2.0)
        else:
            entry  = r.breakout_short_level(self.buffer_pct * 1.4)
            stop   = r.stop_for_short()
            t1     = r.target(direction, multiplier=1.0)
            t2     = r.target(direction, multiplier=2.0)

        # Composite score: weights rvol + momentum alignment
        rvol_score  = min(rvol / 3.0, 1.0)          # caps at 3Ã— RVOL = full score
        mom_score   = 0.20 if momentum_aligned else 0.0
        vwap_score  = 0.30 if (
            (direction == Direction.LONG  and close > vwap) or
            (direction == Direction.SHORT and close < vwap)
        ) else 0.0
        score = round(min(rvol_score * 0.50 + mom_score + vwap_score, 1.0), 3)

        return ORBSignal(
            symbol           = self.symbol,
            direction        = direction,
            bar_time         = ts,
            bar_close        = close,
            opening_range    = r,
            entry_price      = round(entry, 4),
            stop_price       = round(stop, 4),
            target1_price    = round(t1, 4),
            target2_price    = round(t2, 4),
            rvol             = round(rvol, 2),
            vwap             = round(vwap, 4),
            momentum_aligned = momentum_aligned,
            score            = score,
        )

    def _build_range(self, as_of: date) -> OpeningRange:
        highs = [float(b["high"])  for b in self._range_bars]
        lows  = [float(b["low"])   for b in self._range_bars]
        return OpeningRange(
            symbol = self.symbol,
            date   = as_of,
            high   = max(highs),
            low    = min(lows),
        )

