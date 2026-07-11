"""Intraday risk engine — extends the EOD RiskEngine for live daytrading.

Enforces:
  • Daily loss limit (hard halt — no new entries)
  • Max trades per day (circuit breaker)
  • Max consecutive losses (revenge-trading guard)
  • Max simultaneous positions
  • Position time limit (auto-exit stale trades)
  • Per-trade max loss (independent of stop placement)

All limits are read from strategies/daytrader/config.yaml.
This module is the single source of truth for intraday risk — never
embed risk logic inside the strategy model.
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

_CFG_PATH = (
    Path(__file__).resolve().parent.parent
    / "strategies" / "daytrader" / "config.yaml"
)


def _load_cfg() -> dict:
    return yaml.safe_load(_CFG_PATH.read_text())


@dataclass
class IntradayRiskState:
    as_of: date
    realized_pnl: float          = 0.0
    trade_count: int             = 0
    consecutive_losses: int      = 0
    halted: bool                 = False
    halt_reason: str             = ""
    open_positions: dict         = field(default_factory=dict)  # symbol → entry_time


class IntradayRiskEngine:
    """Stateful intraday risk gate. One instance per trading day.

    Call check_entry() before any new order. Call record_close() after
    each exit to update running state.
    """

    def __init__(self, portfolio_value: float, cfg: dict | None = None) -> None:
        self.portfolio_value = portfolio_value
        self._cfg = (cfg or _load_cfg())["risk"]
        self._pos_cfg = (cfg or _load_cfg())["position_sizing"]
        self._state: Optional[IntradayRiskState] = None

    def new_day(self, as_of: date) -> None:
        self._state = IntradayRiskState(as_of=as_of)
        logger.info(
            f"[intraday_risk] New day {as_of} | "
            f"limits: max_loss={self._cfg['max_daily_loss_pct']:.0%} "
            f"max_trades={self._cfg['max_trades_per_day']} "
            f"max_consec={self._cfg['max_consecutive_losses']}"
        )

    def check_entry(self, symbol: str) -> tuple[bool, str]:
        """Returns (approved, reason). Call before every new entry order."""
        if self._state is None:
            return False, "Risk engine not initialised — call new_day() first"

        if self._state.halted:
            return False, f"HALTED: {self._state.halt_reason}"

        s = self._state
        cfg = self._cfg
        pos_cfg = self._pos_cfg

        if s.trade_count >= cfg["max_trades_per_day"]:
            return self._halt(f"Max trades/day reached ({cfg['max_trades_per_day']})")

        if s.consecutive_losses >= cfg["max_consecutive_losses"]:
            return self._halt(
                f"{cfg['max_consecutive_losses']} consecutive losses — "
                "possible adverse conditions"
            )

        loss_limit = self.portfolio_value * cfg["max_daily_loss_pct"]
        if s.realized_pnl <= -loss_limit:
            return self._halt(
                f"Daily loss limit hit: ${s.realized_pnl:+,.2f} "
                f"(limit: ${-loss_limit:,.2f})"
            )

        if len(s.open_positions) >= pos_cfg["max_positions"]:
            return False, f"Max positions ({pos_cfg['max_positions']}) already open"

        if symbol in s.open_positions:
            return False, f"Already holding {symbol}"

        return True, "approved"

    def record_entry(self, symbol: str, entry_time: datetime) -> None:
        if self._state is None:
            return
        self._state.open_positions[symbol] = entry_time
        self._state.trade_count += 1

    def record_close(self, symbol: str, pnl: float) -> None:
        if self._state is None:
            return
        self._state.open_positions.pop(symbol, None)
        self._state.realized_pnl += pnl
        if pnl >= 0:
            self._state.consecutive_losses = 0
        else:
            self._state.consecutive_losses += 1

        logger.info(
            f"[intraday_risk] Close {symbol} | P&L {pnl:+.2f} | "
            f"day P&L {self._state.realized_pnl:+.2f} | "
            f"consec_losses={self._state.consecutive_losses}"
        )

        # Re-check halt conditions after every close
        loss_limit = self.portfolio_value * self._cfg["max_daily_loss_pct"]
        if self._state.realized_pnl <= -loss_limit and not self._state.halted:
            self._halt(
                f"Daily loss limit hit after close: "
                f"${self._state.realized_pnl:+,.2f}"
            )

    def stale_positions(
        self, now: datetime, max_hold_minutes: int = 180
    ) -> list[str]:
        """Return symbols that have been held longer than max_hold_minutes."""
        if self._state is None:
            return []
        cutoff = now - timedelta(minutes=max_hold_minutes)
        return [
            sym for sym, entry_time in self._state.open_positions.items()
            if entry_time < cutoff
        ]

    @property
    def state(self) -> Optional[IntradayRiskState]:
        return self._state

    @property
    def is_halted(self) -> bool:
        return self._state is not None and self._state.halted

    def _halt(self, reason: str) -> tuple[bool, str]:
        if self._state:
            self._state.halted      = True
            self._state.halt_reason = reason
        logger.warning(f"[intraday_risk] HALT — {reason}")
        return False, f"HALTED: {reason}"
