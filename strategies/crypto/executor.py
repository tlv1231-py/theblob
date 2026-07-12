"""Crypto paper executor — Alpaca REST orders + DB logging.

Paper mode: submits real orders to Alpaca paper endpoint (no real money).
Position sizing scales automatically from live account NAV so deposits
and withdrawals are reflected in the next trade without any config change.

Alpaca crypto symbol format for orders: "BTCUSD" (no slash).
Alpaca crypto symbol format for WebSocket: "BTC/USD" (with slash).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from data.database import get_session
from data.models import FillRecord, OrderRecord

STRATEGY = "crypto_momentum"


def _order_symbol(ws_symbol: str) -> str:
    """BTC/USD → BTCUSD for Alpaca order API."""
    return ws_symbol.replace("/", "")


class CryptoExecutor:
    """Executes paper bracket logic for crypto_momentum.

    Submits market orders to Alpaca paper, tracks stop/target in memory,
    exits programmatically on each bar. This is more reliable than
    Alpaca bracket orders on the paper crypto endpoint.
    """

    def __init__(
        self,
        account_value: float,
        risk_pct: float,
        stop_pct: float,
        target_pct: float,
        slippage_bps: int = 15,
    ) -> None:
        self.account_value = account_value
        self.risk_pct      = risk_pct / 100.0
        self.stop_pct      = stop_pct
        self.target_pct    = target_pct
        self.slippage      = slippage_bps / 10_000

        self._client = self._build_client()

    def _build_client(self):
        try:
            from alpaca.trading.client import TradingClient
            return TradingClient(
                api_key    = os.environ["ALPACA_API_KEY"],
                secret_key = os.environ["ALPACA_SECRET_KEY"],
                paper      = True,
            )
        except Exception as e:
            logger.warning(f"[executor] Alpaca client unavailable: {e}")
            return None

    def refresh_account_value(self) -> float:
        """Read live NAV from Alpaca — called on startup and after each fill."""
        if not self._client:
            return self.account_value
        try:
            acct = self._client.get_account()
            self.account_value = float(acct.equity)
            logger.info(f"[executor] Account NAV: ${self.account_value:,.2f}")
        except Exception as e:
            logger.warning(f"[executor] Could not refresh account value: {e}")
        return self.account_value

    def position_qty(self, price: float) -> float:
        """Fractional qty based on risk_pct × account NAV."""
        position_value = self.account_value * self.risk_pct
        return round(position_value / price, 8)

    def enter(self, symbol: str, direction: str, price: float) -> Optional[dict]:
        """Submit a market entry order. Returns fill dict or None."""
        qty = self.position_qty(price)
        if qty <= 0:
            return None

        slipped = price * (1 + self.slippage) if direction == "long" else price * (1 - self.slippage)
        stop    = slipped * (1 - self.stop_pct)   if direction == "long" else slipped * (1 + self.stop_pct)
        target  = slipped * (1 + self.target_pct) if direction == "long" else slipped * (1 - self.target_pct)

        order_id = str(uuid.uuid4())
        now      = datetime.now(timezone.utc)

        # Submit to Alpaca paper
        if self._client:
            try:
                from alpaca.trading.requests import MarketOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce
                req = MarketOrderRequest(
                    symbol       = _order_symbol(symbol),
                    qty          = qty,
                    side         = OrderSide.BUY if direction == "long" else OrderSide.SELL,
                    time_in_force= TimeInForce.GTC,
                )
                resp = self._client.submit_order(req)
                order_id = str(resp.id)
            except Exception as e:
                logger.warning(f"[executor] Alpaca order failed ({symbol}): {e}")

        fill = {
            "order_id":  order_id,
            "symbol":    symbol,
            "direction": direction,
            "qty":       qty,
            "entry":     slipped,
            "stop":      stop,
            "target":    target,
            "entered_at": now,
        }

        self._log_order(fill, "enter", now)
        logger.info(
            f"[fill] ENTER {direction.upper()} {symbol} "
            f"qty={qty:.6f} @ ${slipped:,.4f} | stop=${stop:,.4f} target=${target:,.4f}"
        )
        return fill

    def exit(self, position: dict, price: float, reason: str) -> dict:
        """Submit market exit. Returns updated position dict with pnl."""
        symbol    = position["symbol"]
        direction = position["direction"]
        qty       = position["qty"]

        slipped = price * (1 - self.slippage) if direction == "long" else price * (1 + self.slippage)
        pnl     = (slipped - position["entry"]) * qty * (1 if direction == "long" else -1)

        if self._client:
            try:
                from alpaca.trading.requests import MarketOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce
                req = MarketOrderRequest(
                    symbol        = _order_symbol(symbol),
                    qty           = qty,
                    side          = OrderSide.SELL if direction == "long" else OrderSide.BUY,
                    time_in_force = TimeInForce.GTC,
                )
                self._client.submit_order(req)
            except Exception as e:
                logger.warning(f"[executor] Exit order failed ({symbol}): {e}")

        now = datetime.now(timezone.utc)
        self._log_fill(position, slipped, pnl, reason, now)

        logger.info(
            f"[fill] EXIT  {direction.upper()} {symbol} "
            f"@ ${slipped:,.4f} | pnl={pnl:+,.4f} | reason={reason}"
        )
        return {**position, "exit": slipped, "pnl": pnl, "exited_at": now, "reason": reason}

    def _log_order(self, fill: dict, side: str, ts: datetime) -> None:
        try:
            with get_session() as s:
                s.add(OrderRecord(
                    id         = fill["order_id"],
                    strategy   = STRATEGY,
                    symbol     = fill["symbol"],
                    side       = side,
                    qty        = fill["qty"],
                    price      = fill["entry"],
                    status     = "filled",
                    created_at = ts,
                ))
                s.commit()
        except Exception as e:
            logger.warning(f"[executor] DB order log failed: {e}")

    def _log_fill(self, position: dict, exit_price: float, pnl: float, reason: str, ts: datetime) -> None:
        try:
            with get_session() as s:
                s.add(FillRecord(
                    id         = str(uuid.uuid4()),
                    order_id   = position["order_id"],
                    strategy   = STRATEGY,
                    symbol     = position["symbol"],
                    side       = "exit",
                    qty        = position["qty"],
                    price      = exit_price,
                    pnl        = pnl,
                    filled_at  = ts,
                    note       = reason,
                ))
                s.commit()
        except Exception as e:
            logger.warning(f"[executor] DB fill log failed: {e}")
