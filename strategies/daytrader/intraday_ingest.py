"""Fetch previous trading day's 1-minute bars from Alpaca and cache to parquet.

Called at the end of the evening pipeline so the daytrader backtest/replay
always has yesterday's data available without a live Alpaca connection.

Cache layout (same as MFIMBacktester):
  strategies/daytrader/.bar_cache/{symbol}/{start}_{end}.parquet
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
from loguru import logger

_CACHE_DIR = Path(__file__).resolve().parent / ".bar_cache"

# Daytrader universe — keep in sync with run_daytrader.py
_BASE_UNIVERSE = [
    "SPY", "QQQ", "IWM",
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
    "AMD", "AVGO",
    "JPM", "GS",
    "XLE", "GLD", "TLT",
]


def fetch_and_cache(as_of: date, symbols: list[str] | None = None) -> dict[str, int]:
    """Fetch 1m bars for `as_of` date and write to parquet cache.

    Returns {symbol: bar_count} for each symbol successfully cached.
    Skips symbols whose cache file already exists.
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed
    except ImportError:
        logger.error("[intraday] alpaca-py not installed — skipping intraday ingest")
        return {}

    syms = symbols or _BASE_UNIVERSE
    client = StockHistoricalDataClient(
        api_key=os.environ.get("ALPACA_API_KEY", ""),
        secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
    )

    results: dict[str, int] = {}

    for sym in syms:
        cache_file = _CACHE_DIR / sym / f"{as_of}_{as_of}.parquet"
        if cache_file.exists():
            logger.debug(f"[intraday] {sym} already cached for {as_of}")
            results[sym] = len(pd.read_parquet(cache_file))
            continue

        request = StockBarsRequest(
            symbol_or_symbols=sym,
            timeframe=TimeFrame.Minute,
            start=pd.Timestamp(as_of).tz_localize("America/New_York"),
            end=pd.Timestamp(as_of).replace(hour=23, minute=59).tz_localize("America/New_York"),
            feed=DataFeed.IEX,
        )
        try:
            raw = client.get_stock_bars(request).df
            if raw.empty:
                logger.debug(f"[intraday] No bars returned for {sym} on {as_of}")
                continue
            raw = raw.reset_index()
            raw = raw.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                                       "l": "low", "c": "close", "v": "volume"})
            raw["timestamp"] = pd.to_datetime(raw["timestamp"]).dt.tz_convert("America/New_York")
            bars = raw[["timestamp", "open", "high", "low", "close", "volume"]]
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            bars.to_parquet(cache_file)
            results[sym] = len(bars)
            logger.debug(f"[intraday] {sym}: cached {len(bars)} bars for {as_of}")
        except Exception as e:
            logger.warning(f"[intraday] Failed to fetch {sym} for {as_of}: {e}")

    return results
