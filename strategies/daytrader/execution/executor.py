"""Bracket order executor for the MFIM daytrading strategy.

Paper mode: simulates fills with slippage, writes to The Blob orders/fills tables.
Live mode:  submits bracket orders to Alpaca (entry + stop + take-profit legs).

A bracket order is atomic â€” entry, stop, and both targets are submitted
together so a fill can never be left unprotected.

Alpaca bracket order structure:
  POST /v2/orders
  {
    "side": "buy",
    "type": "limit",
    "order_class": "bracket",
    "stop_loss": {"stop_price": ...},
    "take_profit": {"limit_price": ...}   â† T2 only; T1 handled via partial close
  }
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import select

from data.database import get_session
from data.models import FillRecord, OrderRecord

STRATEGY = "daytrader"
_SLIPPAGE_BPS = 10   # 10 bps per side â€” overridden by config


class PaperBracketExecutor:
    """Simulates bracket order fills with configurable slippage.

    Writes every entry and exit to the The Blob orders + fills tables so
    the daytrader's P&L flows through the same tracking infrastructure
    as the momentum strategy.
    """

    def __init__(self, portfolio_value: float, slippage_bps: int = _SLIPPAGE_BPS) -> None:
        self.portfolio_value = portfolio_value
        self._slippage       = slippage_bps / 10_000

    def execute_action(self, action: dict) -> Optional[FillRecord]:
        """Route an action dict from MFIMStrategy to the appropriate fill method."""
        a = action["action"]
        if a == "enter":
            return self._fill_entry(action)
        elif a in ("exit_stop", "exit_t1", "exit_t2", "exit_eod"):
            return self._fill_exit(action)
        return None

    # â”€â”€ Entry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _fill_entry(self, action: dict) -> Optional[FillRecord]:
        symbol    = action["symbol"]
        direction = action["direction"]   # "long" | "short"
        shares    = int(action["shares"])
        side      = "buy" if direction == "long" else "sell"

        # Apply slippage against us: buys fill slightly higher, sells lower
        raw_price   = float(action["price"])
        fill_price  = raw_price * (1 + self._slippage) if side == "buy" \
                      else raw_price * (1 - self._slippage)
        fill_price  = round(fill_price, 4)

        order_id = str(uuid.uuid4())
        now      = datetime.now(timezone.utc)

        order = OrderRecord(
            order_id    = order_id,
            strategy    = STRATEGY,
            symbol      = symbol,
            side        = side,
            quantity    = shares,
            order_type  = "limit",
            limit_price = fill_price,
            status      = "filled",
            submitted_at= now,
        )
        fill = FillRecord(
            fill_id    = str(uuid.uuid4()),
            order_id   = order_id,
            symbol     = symbol,
            side       = side,
            quantity   = shares,
            fill_price = fill_price,
            filled_at  = now,
        )

        with get_session() as s:
            s.add(order)
            s.add(fill)
            s.commit()

        logger.info(
            f"[executor] PAPER FILL â€” {side.upper()} {shares}Ã— {symbol} "
            f"@ {fill_price:.4f} (slippage {self._slippage*1e4:.0f}bps)"
        )
        return fill

    # â”€â”€ Exit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _fill_exit(self, action: dict) -> Optional[FillRecord]:
        symbol    = action["symbol"]
        direction = action["direction"]
        shares    = int(action["shares"])
        reason    = action["action"]

        # Closing side is opposite of entry direction
        side = "sell" if direction == "long" else "buy"

        raw_price  = float(action["price"])
        fill_price = raw_price * (1 - self._slippage) if side == "sell" \
                     else raw_price * (1 + self._slippage)
        fill_price = round(fill_price, 4)

        order_id = str(uuid.uuid4())
        now      = datetime.now(timezone.utc)

        order = OrderRecord(
            order_id    = order_id,
            strategy    = STRATEGY,
            symbol      = symbol,
            side        = side,
            quantity    = shares,
            order_type  = "market",
            status      = "filled",
            submitted_at= now,
        )
        fill = FillRecord(
            fill_id    = str(uuid.uuid4()),
            order_id   = order_id,
            symbol     = symbol,
            side       = side,
            quantity   = shares,
            fill_price = fill_price,
            filled_at  = now,
        )

        with get_session() as s:
            s.add(order)
            s.add(fill)
            s.commit()

        pnl = action.get("pnl", 0.0)
        logger.info(
            f"[executor] PAPER FILL â€” {side.upper()} {shares}Ã— {symbol} "
            f"@ {fill_price:.4f} | reason={reason} | P&L {pnl:+.2f}"
        )
        return fill


class AlpacaLiveBracketExecutor:
    """Submits real bracket orders to Alpaca.

    NOT active until ALPACA_PAPER=false is set and strategy status = live.
    Every method is a no-op unless explicitly armed.
    """

    def __init__(
        self,
        portfolio_value: float,
        armed: bool = False,
    ) -> None:
        self.portfolio_value = portfolio_value
        self._armed          = armed

        if armed:
            try:
                from alpaca.trading.client import TradingClient
                import os
                self._client = TradingClient(
                    api_key    = os.environ["ALPACA_API_KEY"],
                    secret_key = os.environ["ALPACA_SECRET_KEY"],
                    paper      = os.getenv("ALPACA_PAPER", "true").lower() == "true",
                )
                logger.info("[executor] AlpacaLiveBracketExecutor ARMED")
            except Exception as e:
                logger.error(f"[executor] Alpaca init failed: {e}")
                self._armed = False

    def execute_action(self, action: dict) -> None:
        if not self._armed:
            logger.warning("[executor] Live executor not armed â€” action dropped")
            return

        if action["action"] != "enter":
            return   # exits are handled via OCO legs submitted with entry

        self._submit_bracket(action)

    def _submit_bracket(self, action: dict) -> None:
        from alpaca.trading.requests import LimitOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

        symbol    = action["symbol"]
        direction = action["direction"]
        shares    = int(action["shares"])
        side      = OrderSide.BUY if direction == "long" else OrderSide.SELL

        try:
            req = LimitOrderRequest(
                symbol      = symbol,
                qty         = shares,
                side        = side,
                time_in_force = TimeInForce.DAY,
                limit_price = action["price"],
                order_class = OrderClass.BRACKET,
                take_profit = TakeProfitRequest(limit_price=action["target2"]),
                stop_loss   = StopLossRequest(stop_price=action["stop"]),
            )
            order = self._client.submit_order(req)
            logger.info(
                f"[executor] LIVE ORDER submitted â€” {side} {shares}Ã— {symbol} "
                f"| order_id={order.id}"
            )
        except Exception as e:
            logger.error(f"[executor] Alpaca order submission failed: {e}")

