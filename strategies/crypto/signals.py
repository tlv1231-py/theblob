"""Signal logic for crypto_momentum strategy.

Three conditions must all pass for an entry:
  1. Breakout — close above N-bar high (long) or below N-bar low (short)
  2. VWAP    — price on correct side of rolling 24h VWAP
  3. RVOL    — current bar volume >= rvol_min × 20-bar average volume

All computed from the in-memory bar buffer maintained per symbol.
No I/O here — pure signal math.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd


class Direction(str, Enum):
    LONG  = "long"
    SHORT = "short"


@dataclass
class Signal:
    symbol:    str
    direction: Direction
    price:     float
    rvol:      float
    vwap:      float
    bar_time:  datetime


class SymbolBuffer:
    """Rolling bar buffer + live signal math for one symbol."""

    def __init__(self, breakout_bars: int, vwap_window_hours: int, rvol_min: float) -> None:
        self.breakout_bars     = breakout_bars
        self.vwap_window_hours = vwap_window_hours
        self.rvol_min          = rvol_min

        # 1-min bars: keep enough for VWAP window (60 * hours) + breakout lookback
        maxlen = max(vwap_window_hours * 60 + 1, breakout_bars + 21)
        self._bars: deque[dict] = deque(maxlen=maxlen)

    def push(self, bar: pd.Series) -> Optional[Signal]:
        """Add a new 1-min bar and return a Signal if conditions are met, else None."""
        self._bars.append({
            "time":   bar.name if isinstance(bar.name, datetime) else bar.get("timestamp"),
            "open":   float(bar["open"]),
            "high":   float(bar["high"]),
            "low":    float(bar["low"]),
            "close":  float(bar["close"]),
            "volume": float(bar.get("volume", 0)),
        })

        if len(self._bars) < self.breakout_bars + 21:
            return None  # not enough history yet

        closes  = [b["close"]  for b in self._bars]
        volumes = [b["volume"] for b in self._bars]
        highs   = [b["high"]   for b in self._bars]
        lows    = [b["low"]    for b in self._bars]

        close   = closes[-1]
        vol     = volumes[-1]

        # ── RVOL ─────────────────────────────────────────────────────────────
        avg_vol = sum(volumes[-21:-1]) / 20
        rvol    = (vol / avg_vol) if avg_vol > 0 else 0.0
        if rvol < self.rvol_min:
            return None

        # ── Rolling 24h VWAP ─────────────────────────────────────────────────
        window  = min(self.vwap_window_hours * 60, len(self._bars))
        w_bars  = list(self._bars)[-window:]
        tp_vol  = sum(((b["high"]+b["low"]+b["close"])/3) * b["volume"] for b in w_bars)
        tot_vol = sum(b["volume"] for b in w_bars)
        vwap    = tp_vol / tot_vol if tot_vol > 0 else close

        # ── Breakout ─────────────────────────────────────────────────────────
        # Compare close against the N bars BEFORE this one (no look-ahead)
        prior_highs = highs[-(self.breakout_bars + 1):-1]
        prior_lows  = lows[ -(self.breakout_bars + 1):-1]

        long_break  = close > max(prior_highs) and close > vwap
        short_break = close < min(prior_lows)  and close < vwap

        if long_break:
            return Signal(
                symbol    = "",  # filled by caller
                direction = Direction.LONG,
                price     = close,
                rvol      = rvol,
                vwap      = vwap,
                bar_time  = self._bars[-1]["time"],
            )
        if short_break:
            return Signal(
                symbol    = "",
                direction = Direction.SHORT,
                price     = close,
                rvol      = rvol,
                vwap      = vwap,
                bar_time  = self._bars[-1]["time"],
            )
        return None
