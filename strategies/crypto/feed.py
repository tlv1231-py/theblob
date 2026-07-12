"""Alpaca crypto WebSocket feed — streams 1-min bars to strategy.

Uses CryptoDataStream (not StockDataStream) — different auth, different
symbol format (BTC/USD), available 24/7 with free Alpaca account.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable

import pandas as pd
from loguru import logger

try:
    from alpaca.data.live import CryptoDataStream
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    logger.error("[feed] alpaca-py not installed. Run: pip install alpaca-py")


class CryptoFeed:
    """Streams 1-min bars for all symbols and routes to strategy.on_bar."""

    def __init__(self, symbols: list[str], on_bar: Callable) -> None:
        if not _AVAILABLE:
            raise ImportError("alpaca-py required: pip install alpaca-py")

        self._symbols = symbols
        self._on_bar  = on_bar
        self._stream  = CryptoDataStream(
            api_key    = os.environ["ALPACA_API_KEY"],
            secret_key = os.environ["ALPACA_SECRET_KEY"],
        )

    async def _handle_bar(self, bar) -> None:
        sym = bar.symbol  # arrives as "BTC/USD"
        s = pd.Series({
            "open":      float(bar.open),
            "high":      float(bar.high),
            "low":       float(bar.low),
            "close":     float(bar.close),
            "volume":    float(bar.volume),
            "timestamp": bar.timestamp,
        }, name=bar.timestamp)

        try:
            self._on_bar(sym, s)
        except Exception as e:
            logger.error(f"[feed] on_bar error ({sym}): {e}")

    async def run(self) -> None:
        logger.info(f"[feed] Subscribing to {len(self._symbols)} crypto pairs")
        self._stream.subscribe_bars(self._handle_bar, *self._symbols)
        await self._stream._run_forever()
