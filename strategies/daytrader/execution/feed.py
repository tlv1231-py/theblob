"""Alpaca WebSocket feed handler — streams live 1-minute bars.

Connects to Alpaca's market data WebSocket and routes incoming bars
to the MFIM strategy. Supports paper and live environments.

Requires: alpaca-py  (pip install alpaca-py)
Env vars:
    ALPACA_API_KEY
    ALPACA_SECRET_KEY
    ALPACA_FEED        — "iex" (free) or "sip" (paid, full tape)
    ALPACA_PAPER       — "true" (default) or "false"

Usage:
    feed = AlpacaBarFeed(symbols=["SPY", "AAPL"], on_bar=strategy.on_bar)
    asyncio.run(feed.run())
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Callable, Awaitable

import pandas as pd
from loguru import logger

try:
    from alpaca.data.live import StockDataStream
    from alpaca.data.enums import DataFeed
    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False
    logger.warning(
        "[feed] alpaca-py not installed. "
        "Run: pip install alpaca-py  to enable live streaming."
    )

from zoneinfo import ZoneInfo
_ET = ZoneInfo("America/New_York")


OnBarCallback = Callable[[str, pd.Series], list[dict]]


class AlpacaBarFeed:
    """Streams 1-minute bars from Alpaca and calls on_bar for each symbol.

    on_bar(symbol, bar) → list of action dicts from the strategy.
    Actions are logged; execution is handled by BracketExecutor.
    """

    def __init__(
        self,
        symbols: list[str],
        on_bar: OnBarCallback,
        on_action: Callable[[dict], None] | None = None,
    ) -> None:
        if not _ALPACA_AVAILABLE:
            raise ImportError("alpaca-py required. pip install alpaca-py")

        self.symbols   = symbols
        self._on_bar   = on_bar
        self._on_action = on_action or _log_action

        api_key    = os.environ["ALPACA_API_KEY"]
        secret_key = os.environ["ALPACA_SECRET_KEY"]
        feed_str   = os.getenv("ALPACA_FEED", "iex").lower()
        feed       = DataFeed.IEX if feed_str == "iex" else DataFeed.SIP

        self._stream = StockDataStream(
            api_key    = api_key,
            secret_key = secret_key,
            feed       = feed,
        )

    async def run(self) -> None:
        """Start the WebSocket stream. Blocks until cancelled or market close."""
        self._stream.subscribe_bars(self._handle_bar, *self.symbols)
        logger.info(f"[feed] Connecting to Alpaca stream | symbols: {self.symbols}")
        # Run the stream in a thread so asyncio cancellation can interrupt it.
        # stream.run() is safe to call from a thread (it creates its own event loop).
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._stream.run)

    async def _handle_bar(self, bar) -> None:
        """Alpaca callback — converts to pd.Series and routes to strategy."""
        try:
            series = pd.Series({
                "timestamp": pd.Timestamp(bar.timestamp).tz_convert(_ET),
                "open":      float(bar.open),
                "high":      float(bar.high),
                "low":       float(bar.low),
                "close":     float(bar.close),
                "volume":    float(bar.volume),
                "symbol":    bar.symbol,
            })
            actions = self._on_bar(bar.symbol, series)
            for action in actions:
                self._on_action(action)
        except Exception as e:
            logger.error(f"[feed] Error processing bar {bar.symbol}: {e}")


def _log_action(action: dict) -> None:
    """Default action handler — logs to console."""
    a = action["action"]
    sym = action["symbol"]
    price = action.get("price", 0)
    shares = action.get("shares", 0)
    reason = action.get("reason", "")

    if a == "enter":
        logger.info(
            f"[ACTION] ENTER {action['direction'].upper()} {sym} "
            f"× {shares} @ {price:.2f} | {reason}"
        )
    elif a.startswith("exit"):
        pnl = action.get("pnl", 0)
        logger.info(
            f"[ACTION] EXIT {sym} × {shares} @ {price:.2f} "
            f"| P&L {pnl:+.2f} | {reason}"
        )


class ReplayFeed:
    """Replays historical minute bars through the strategy for backtesting.

    Simulates the same on_bar interface as AlpacaBarFeed but runs
    synchronously from a DataFrame of historical bars.
    """

    def __init__(
        self,
        bars: pd.DataFrame,
        on_bar: OnBarCallback,
        on_action: Callable[[dict], None] | None = None,
    ) -> None:
        self.bars       = bars.sort_values("timestamp")
        self._on_bar    = on_bar
        self._on_action = on_action or _log_action

    def run(self) -> list[dict]:
        """Replay all bars. Returns flat list of all actions generated."""
        all_actions: list[dict] = []
        for _, row in self.bars.iterrows():
            symbol = str(row["symbol"])
            actions = self._on_bar(symbol, row)
            for a in actions:
                self._on_action(a)
                all_actions.append(a)
        return all_actions
