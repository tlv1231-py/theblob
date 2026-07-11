"""Multi-Factor Intraday Momentum (MFIM) â€” main strategy orchestrator.

Signal stack (all conditions must pass for an entry):
  1. Opening Range Breakout  â€” directional commitment post-open chaos
  2. VWAP alignment          â€” only trade with institutional flow
  3. Relative Volume â‰¥ 1.5Ã—  â€” confirms institutional participation
  4. Session filter           â€” no trades before 9:46am or after 3:30pm ET
  5. Risk gate               â€” daily loss limit / max trades not breached

Bonus (score enhancement, not a hard gate):
  â€¢ The Blob momentum alignment   â€” top-N momentum stock in same direction

Position management:
  Entry  â†’ aggressive limit at breakout level
  Stop   â†’ opening range midpoint (hard, no exceptions)
  T1     â†’ 1Ã— range height above/below entry (take 50% off, move stop to BE)
  T2     â†’ 2Ã— range height (trail remainder with 0.5Ã— trailing stop)
  Hard exit â†’ 3:45pm ET regardless of P&L
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional

from loguru import logger
from zoneinfo import ZoneInfo

from strategies.daytrader.signals.opening_range import (
    Direction, OpeningRangeDetector, ORBSignal,
)
from strategies.daytrader.signals.vwap import VWAPCalculator, RVOLCalculator
from strategies.daytrader.signals.momentum_bias import is_momentum_aligned

import pandas as pd

_ET    = ZoneInfo("America/New_York")
_CFG   = Path(__file__).resolve().parent.parent / "config.yaml"


def _load_config() -> dict:
    return yaml.safe_load(_CFG.read_text())


@dataclass
class Position:
    symbol: str
    direction: Direction
    entry_price: float
    stop_price: float
    target1_price: float
    target2_price: float
    shares: int
    entry_time: datetime
    t1_hit: bool = False
    trailing_stop: Optional[float] = None

    @property
    def is_open(self) -> bool:
        return self.shares > 0

    def mark(self, price: float) -> float:
        """Unrealized P&L at current price."""
        if self.direction == Direction.LONG:
            return (price - self.entry_price) * self.shares
        return (self.entry_price - price) * self.shares

    def should_stop(self, price: float) -> bool:
        """True if price has hit the current stop level."""
        stop = self.trailing_stop if self.trailing_stop is not None else self.stop_price
        if self.direction == Direction.LONG:
            return price <= stop
        return price >= stop

    def should_take_t1(self, price: float) -> bool:
        if self.t1_hit:
            return False
        if self.direction == Direction.LONG:
            return price >= self.target1_price
        return price <= self.target1_price

    def should_take_t2(self, price: float) -> bool:
        if not self.t1_hit:
            return False
        if self.direction == Direction.LONG:
            return price >= self.target2_price
        return price <= self.target2_price


@dataclass
class DayStats:
    as_of: date
    trades: int = 0
    wins: int = 0
    losses: int = 0
    realized_pnl: float = 0.0
    consecutive_losses: int = 0

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.0


class MFIMStrategy:
    """Multi-Factor Intraday Momentum â€” orchestrates signals and positions.

    Designed to run against a live 1-minute bar feed (Alpaca WebSocket)
    or a historical minute bar replay for backtesting.

    Usage:
        strat = MFIMStrategy(portfolio_value=100_000)
        strat.new_day(as_of_date)
        for bar in minute_bars:
            actions = strat.on_bar(bar)
            for action in actions:
                executor.submit(action)
    """

    STRATEGY_NAME = "daytrader"

    def __init__(
        self,
        portfolio_value: float,
        config: dict | None = None,
    ) -> None:
        self._cfg            = config or _load_config()
        self.portfolio_value = portfolio_value

        # Per-symbol state â€” populated in new_day()
        self._detectors: dict[str, OpeningRangeDetector] = {}
        self._vwaps:     dict[str, VWAPCalculator]       = {}
        self._rvols:     dict[str, RVOLCalculator]       = {}

        # Active positions
        self._positions: dict[str, Position] = {}

        # Daily stats
        self._day_stats: Optional[DayStats] = None

        # Momentum universe (loaded once per day)
        self._momentum_top_n: set[str] = set()

        self._as_of: Optional[date] = None

    # â”€â”€ Day lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def new_day(self, as_of: date, symbols: list[str]) -> None:
        """Call at the start of each trading day before feeding any bars."""
        self._as_of      = as_of
        self._positions  = {}
        self._day_stats  = DayStats(as_of=as_of)

        orb_cfg  = self._cfg["opening_range_breakout"]
        self._detectors = {
            sym: OpeningRangeDetector(
                symbol          = sym,
                range_minutes   = orb_cfg["range_minutes"],
                buffer_pct      = orb_cfg["breakout_buffer_pct"],
                min_range_pct   = orb_cfg["min_range_pct"],
                max_range_pct   = orb_cfg["max_range_pct"],
            )
            for sym in symbols
        }
        self._vwaps = {sym: VWAPCalculator() for sym in symbols}
        self._rvols = {sym: RVOLCalculator(
            lookback_days=self._cfg["relative_volume"]["lookback_days"]
        ) for sym in symbols}

        # Load The Blob momentum universe for cross-strategy bias
        if self._cfg["momentum_bias"]["enabled"]:
            from strategies.daytrader.signals.momentum_bias import get_momentum_universe
            top_n   = self._cfg["momentum_bias"]["top_n_long"]
            universe = get_momentum_universe(as_of=as_of, top_n=top_n)
            self._momentum_top_n = set(universe.keys())
            logger.info(
                f"[MFIM] Momentum bias loaded â€” {len(self._momentum_top_n)} aligned symbols: "
                f"{sorted(self._momentum_top_n)}"
            )

        logger.info(f"[MFIM] New day: {as_of} | {len(symbols)} symbols in universe")

    def load_rvol_history(self, symbol: str, historical_bars: pd.DataFrame) -> None:
        """Pre-load historical bars for RVOL baseline. Call after new_day()."""
        if symbol in self._rvols:
            self._rvols[symbol].load_historical(historical_bars)

    # â”€â”€ Bar processing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def on_bar(self, symbol: str, bar: pd.Series) -> list[dict]:
        """Process one 1-minute bar. Returns list of action dicts.

        Action dict schema:
          {action: "enter"|"exit_stop"|"exit_t1"|"exit_t2"|"exit_eod",
           symbol, direction, price, shares, reason}
        """
        if symbol not in self._detectors:
            return []

        actions: list[dict] = []

        vwap = self._vwaps[symbol].update(bar)
        rvol = self._rvols[symbol].compute(bar)
        mom_aligned = symbol in self._momentum_top_n

        ts: datetime = bar["timestamp"]
        bar_time = ts.astimezone(_ET).time()

        # â”€â”€ Hard exit â€” end of day â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        hard_exit = time(*[int(x) for x in
                           self._cfg["session"]["hard_exit"].split(":")])
        if bar_time >= hard_exit and symbol in self._positions:
            pos = self._positions.pop(symbol)
            close = float(bar["close"])
            pnl = pos.mark(close)
            self._record_close(pnl)
            actions.append({
                "action": "exit_eod",
                "symbol": symbol,
                "direction": pos.direction.value,
                "price": close,
                "shares": pos.shares,
                "reason": "hard_exit_eod",
                "pnl": pnl,
            })
            logger.info(f"[MFIM] EOD exit {symbol} @ {close:.2f} | P&L {pnl:+.2f}")
            return actions

        # â”€â”€ Manage open position â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if symbol in self._positions:
            pos   = self._positions[symbol]
            close = float(bar["close"])

            if pos.should_stop(close):
                pnl = pos.mark(close)
                self._positions.pop(symbol)
                self._record_close(pnl)
                actions.append({
                    "action": "exit_stop",
                    "symbol": symbol,
                    "direction": pos.direction.value,
                    "price": close,
                    "shares": pos.shares,
                    "reason": "stop_hit",
                    "pnl": pnl,
                })
                logger.info(f"[MFIM] Stop hit {symbol} @ {close:.2f} | P&L {pnl:+.2f}")

            elif pos.should_take_t1(close):
                half = max(1, pos.shares // 2)
                pos.shares   -= half
                pos.t1_hit    = True
                # Move stop to breakeven
                pos.trailing_stop = pos.entry_price
                pnl_partial = (close - pos.entry_price) * half if pos.direction == Direction.LONG \
                              else (pos.entry_price - close) * half
                actions.append({
                    "action": "exit_t1",
                    "symbol": symbol,
                    "direction": pos.direction.value,
                    "price": close,
                    "shares": half,
                    "reason": "target1_hit",
                    "pnl": pnl_partial,
                })
                logger.info(f"[MFIM] T1 hit {symbol} @ {close:.2f} | partial exit {half} shares")

            elif pos.should_take_t2(close):
                pnl = pos.mark(close)
                self._positions.pop(symbol)
                self._record_close(pnl)
                actions.append({
                    "action": "exit_t2",
                    "symbol": symbol,
                    "direction": pos.direction.value,
                    "price": close,
                    "shares": pos.shares,
                    "reason": "target2_hit",
                    "pnl": pnl,
                })
                logger.info(f"[MFIM] T2 hit {symbol} @ {close:.2f} | P&L {pnl:+.2f}")

            return actions

        # â”€â”€ Check for new entry signal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        trade_start  = time(*[int(x) for x in
                               self._cfg["session"]["trade_start"].split(":")])
        trade_cutoff = time(*[int(x) for x in
                               self._cfg["session"]["trade_cutoff"].split(":")])

        if bar_time < trade_start or bar_time > trade_cutoff:
            self._detectors[symbol].feed(bar, vwap, rvol, mom_aligned)
            return actions

        if not self._can_enter():
            return actions

        signal: Optional[ORBSignal] = self._detectors[symbol].feed(
            bar, vwap, rvol, mom_aligned
        )

        if signal is None:
            return actions

        # VWAP filter
        vwap_cfg = self._cfg["vwap"]
        max_dev   = vwap_cfg["max_vwap_deviation_pct"]
        if abs(signal.bar_close - signal.vwap) / signal.vwap > max_dev:
            logger.debug(f"[MFIM] {symbol} VWAP deviation too large â€” skip")
            return actions

        # RVOL filter
        rvol_threshold = self._cfg["relative_volume"]["rvol_threshold"]
        if signal.rvol < rvol_threshold:
            logger.debug(f"[MFIM] {symbol} RVOL {signal.rvol:.2f} < {rvol_threshold} â€” skip")
            return actions

        # Size the position
        shares = self._size_position(signal)
        if shares < 1:
            logger.debug(f"[MFIM] {symbol} position size < 1 share â€” skip")
            return actions

        pos = Position(
            symbol        = symbol,
            direction     = signal.direction,
            entry_price   = signal.entry_price,
            stop_price    = signal.stop_price,
            target1_price = signal.target1_price,
            target2_price = signal.target2_price,
            shares        = shares,
            entry_time    = ts,
        )
        self._positions[symbol] = pos
        self._day_stats.trades += 1

        actions.append({
            "action":    "enter",
            "symbol":    symbol,
            "direction": signal.direction.value,
            "price":     signal.entry_price,
            "shares":    shares,
            "stop":      signal.stop_price,
            "target1":   signal.target1_price,
            "target2":   signal.target2_price,
            "score":     signal.score,
            "rvol":      signal.rvol,
            "vwap":      signal.vwap,
            "momentum_aligned": signal.momentum_aligned,
            "reason":    f"ORB {signal.direction.value} | score={signal.score:.2f} "
                         f"| rvol={signal.rvol:.2f}x | mom={'âœ“' if signal.momentum_aligned else 'â€”'}",
        })

        logger.info(
            f"[MFIM] ENTRY {signal.direction.value.upper()} {symbol} "
            f"@ {signal.entry_price:.2f} | stop {signal.stop_price:.2f} "
            f"| T1 {signal.target1_price:.2f} | T2 {signal.target2_price:.2f} "
            f"| {shares} shares | score {signal.score:.2f} | rvol {signal.rvol:.2f}x"
        )

        return actions

    # â”€â”€ Internal helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _can_enter(self) -> bool:
        """Check daily risk gates before allowing a new entry."""
        if self._day_stats is None:
            return False

        cfg_risk = self._cfg["risk"]
        max_trades = cfg_risk["max_trades_per_day"]
        max_consec = cfg_risk["max_consecutive_losses"]
        max_loss   = cfg_risk["max_daily_loss_pct"]
        max_pos    = self._cfg["position_sizing"]["max_positions"]

        if self._day_stats.trades >= max_trades:
            logger.debug("[MFIM] Max trades per day reached â€” no new entries")
            return False

        if self._day_stats.consecutive_losses >= max_consec:
            logger.warning(
                f"[MFIM] {max_consec} consecutive losses â€” halting for the day"
            )
            return False

        if self._day_stats.realized_pnl <= -(self.portfolio_value * max_loss):
            logger.warning(
                f"[MFIM] Daily loss limit hit "
                f"(${self._day_stats.realized_pnl:+,.2f}) â€” halting"
            )
            return False

        if len(self._positions) >= max_pos:
            logger.debug(f"[MFIM] Max positions ({max_pos}) held â€” no new entries")
            return False

        return True

    def _size_position(self, signal: ORBSignal) -> int:
        """Risk-based position sizing: risk 1% of portfolio per trade."""
        risk_pct  = self._cfg["position_sizing"]["risk_per_trade_pct"]
        risk_dollars = self.portfolio_value * risk_pct
        risk_per_share = signal.risk_per_share
        if risk_per_share <= 0:
            return 0
        return int(risk_dollars / risk_per_share)

    def _record_close(self, pnl: float) -> None:
        if self._day_stats is None:
            return
        self._day_stats.realized_pnl += pnl
        if pnl >= 0:
            self._day_stats.wins += 1
            self._day_stats.consecutive_losses = 0
        else:
            self._day_stats.losses += 1
            self._day_stats.consecutive_losses += 1

    # â”€â”€ Introspection â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @property
    def open_positions(self) -> dict[str, Position]:
        return dict(self._positions)

    @property
    def day_stats(self) -> Optional[DayStats]:
        return self._day_stats

    def summary(self) -> str:
        if self._day_stats is None:
            return "No active session."
        s = self._day_stats
        return (
            f"Day {s.as_of} | trades={s.trades} | "
            f"W/L={s.wins}/{s.losses} | "
            f"P&L={s.realized_pnl:+,.2f} | "
            f"open={len(self._positions)}"
        )

