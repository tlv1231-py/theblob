"""crypto_momentum strategy orchestrator.

Wires together:
  SymbolBuffer (signals) → CryptoExecutor (fills) → pipeline_events (dashboard feed)

One instance runs for the lifetime of the Fly.io process. Each 1-min bar
from the WebSocket calls on_bar(symbol, bar). Position management (stop,
target, max-hold) is checked on every bar for every open position.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import yaml
from loguru import logger
from pathlib import Path
from sqlalchemy import text

from data.database import get_session
from strategies.crypto.signals import Direction, SymbolBuffer
from strategies.crypto.executor import CryptoExecutor

_CFG_PATH = Path(__file__).resolve().parent / "config.yaml"


def _load_cfg() -> dict:
    return yaml.safe_load(_CFG_PATH.read_text())


def _post_event(event_type: str, symbol: str, message: str, detail: str = "") -> None:
    """Write to pipeline_events so the dashboard Status bar fires."""
    try:
        with get_session() as s:
            s.execute(text("""
                INSERT INTO pipeline_events (run_date, event_type, symbol, message, detail, recorded_at)
                VALUES (:rd, :et, :sym, :msg, :det, :ts)
            """), {
                "rd":  datetime.now(timezone.utc).date(),
                "et":  event_type,
                "sym": symbol,
                "msg": message,
                "det": detail,
                "ts":  datetime.now(timezone.utc),
            })
            s.commit()
    except Exception as e:
        logger.warning(f"[events] DB write failed: {e}")


class CryptoMomentumStrategy:
    """Main strategy loop for crypto_momentum."""

    def __init__(self) -> None:
        self.cfg      = _load_cfg()
        sig           = self.cfg["signals"]
        pos           = self.cfg["position"]
        risk          = self.cfg["risk"]
        exe           = self.cfg["execution"]

        self._max_pos       = pos["max_positions"]
        self._stop_pct      = pos["stop_pct"]
        self._target_pct    = pos["target_pct"]
        self._max_hold_mins = pos["max_hold_minutes"]
        self._max_daily_loss= risk["max_daily_loss_pct"]
        self._max_daily_trd = risk["max_daily_trades"]

        self._buffers: dict[str, SymbolBuffer] = {
            sym: SymbolBuffer(
                breakout_bars     = sig["breakout_bars"],
                vwap_window_hours = sig["vwap_window_hours"],
                rvol_min          = sig["rvol_min"],
            )
            for sym in self.cfg["universe"]
        }

        self._positions: dict[str, dict] = {}   # symbol → open position
        self._daily_trades  = 0
        self._daily_pnl     = 0.0
        self._halted        = False
        self._session_date  = datetime.now(timezone.utc).date()

        self.executor = CryptoExecutor(
            account_value = 100_000.0,   # overwritten by refresh_account_value()
            risk_pct      = pos["risk_pct"],
            stop_pct      = self._stop_pct,
            target_pct    = self._target_pct,
            slippage_bps  = exe["slippage_bps"],
        )
        self.executor.refresh_account_value()

        logger.info(
            f"[strategy] crypto_momentum ready | "
            f"{len(self._buffers)} pairs | "
            f"risk_pct={pos['risk_pct']}% | "
            f"NAV=${self.executor.account_value:,.2f}"
        )
        _post_event("START", "", f"crypto_momentum started · {len(self._buffers)} pairs · NAV ${self.executor.account_value:,.0f}")

    def _new_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._session_date:
            self._session_date = today
            self._daily_trades = 0
            self._daily_pnl    = 0.0
            self._halted       = False
            self.executor.refresh_account_value()
            logger.info(f"[strategy] New day {today} | NAV=${self.executor.account_value:,.2f}")
            _post_event("UPDATE", "", f"new session · {today} · NAV ${self.executor.account_value:,.0f}")

    def on_bar(self, symbol: str, bar) -> None:
        """Called by feed on every 1-min bar. Core loop."""
        self._new_day()

        if self._halted:
            return

        # ── Check open position for this symbol first ─────────────────────
        if symbol in self._positions:
            self._manage_position(symbol, bar)
            return   # never enter a new position while one is open in same symbol

        # ── Risk gates ────────────────────────────────────────────────────
        if len(self._positions) >= self._max_pos:
            return
        if self._daily_trades >= self._max_daily_trd:
            return

        # ── Signal check ─────────────────────────────────────────────────
        buf    = self._buffers.get(symbol)
        signal = buf.push(bar) if buf else None
        if signal is None:
            return

        signal.symbol = symbol
        direction = signal.direction.value

        fill = self.executor.enter(symbol, direction, signal.price)
        if fill is None:
            return

        self._positions[symbol] = {**fill, "symbol": symbol}
        self._daily_trades += 1

        msg = (
            f"{'▲' if direction == 'long' else '▼'} ENTER {direction.upper()} "
            f"{symbol} @ ${signal.price:,.4f} · "
            f"RVOL {signal.rvol:.1f}× · stop ${fill['stop']:,.4f}"
        )
        _post_event("TRADE", symbol, msg, f"target=${fill['target']:,.4f}")

    def _manage_position(self, symbol: str, bar) -> None:
        """Check stop, target, max-hold on every bar for an open position."""
        pos   = self._positions[symbol]
        close = float(bar["close"]) if hasattr(bar, "__getitem__") else float(bar.close)
        now   = datetime.now(timezone.utc)
        age   = (now - pos["entered_at"]).total_seconds() / 60

        direction = pos["direction"]
        reason    = None

        if direction == "long":
            if close <= pos["stop"]:   reason = "stop"
            elif close >= pos["target"]: reason = "target"
        else:
            if close >= pos["stop"]:   reason = "stop"
            elif close <= pos["target"]: reason = "target"

        if reason is None and age >= self._max_hold_mins:
            reason = "max_hold"

        if reason:
            result = self.executor.exit(pos, close, reason)
            pnl    = result["pnl"]
            self._daily_pnl += pnl
            del self._positions[symbol]

            emoji = "✓" if pnl >= 0 else "✗"
            msg   = (
                f"{emoji} EXIT {direction.upper()} {symbol} "
                f"@ ${close:,.4f} · pnl {pnl:+,.4f} · {reason}"
            )
            _post_event("TRADE", symbol, msg, f"daily_pnl={self._daily_pnl:+,.2f}")

            # Daily loss halt
            if self._daily_pnl / self.executor.account_value <= -self._max_daily_loss:
                self._halted = True
                logger.warning(f"[risk] Daily loss limit hit — halted for today")
                _post_event("RISK", "", f"daily loss limit hit · halted · resume tomorrow")
