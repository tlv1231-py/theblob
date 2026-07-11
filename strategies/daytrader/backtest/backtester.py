"""Minute-bar backtester for the MFIM daytrading strategy.

Pulls historical 1-minute bars from Alpaca (or a local CSV cache),
replays them through MFIMStrategy day by day, and records every
fill to the experiments table using The Blob's existing infrastructure.

Usage:
    bt = MFIMBacktester(
        symbols=["SPY", "QQQ", "AAPL", "NVDA", "MSFT"],
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        portfolio_value=100_000,
    )
    results = bt.run()
    bt.log_experiment(results)

Requires: alpaca-py  (pip install alpaca-py)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from strategies.daytrader.models.strategy import MFIMStrategy
from strategies.daytrader.execution.feed import ReplayFeed
from ingestion.calendar import is_trading_day, get_trading_days

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".bar_cache"


@dataclass
class BacktestResults:
    start: date
    end: date
    symbols: list[str]
    portfolio_value: float
    fills: list[dict] = field(default_factory=list)

    @property
    def total_trades(self) -> int:
        entries = [f for f in self.fills if f["action"] == "enter"]
        return len(entries)

    @property
    def exits(self) -> list[dict]:
        return [f for f in self.fills if f["action"].startswith("exit")]

    @property
    def pnl_series(self) -> pd.Series:
        """Daily P&L as a Series indexed by date."""
        if not self.exits:
            return pd.Series(dtype=float)
        df = pd.DataFrame(self.exits)
        df["date"] = pd.to_datetime(df.get("bar_date", pd.NaT))
        return df.groupby("date")["pnl"].sum()

    @property
    def total_pnl(self) -> float:
        return sum(f.get("pnl", 0) for f in self.exits)

    @property
    def win_rate(self) -> float:
        exits = self.exits
        if not exits:
            return 0.0
        wins = sum(1 for f in exits if f.get("pnl", 0) >= 0)
        return wins / len(exits)

    @property
    def cagr(self) -> float:
        days = (self.end - self.start).days
        if days < 1:
            return 0.0
        final_value = self.portfolio_value + self.total_pnl
        return (final_value / self.portfolio_value) ** (365.25 / days) - 1

    @property
    def sharpe(self) -> float:
        s = self.pnl_series
        if len(s) < 5:
            return float("nan")
        daily_returns = s / self.portfolio_value
        excess = daily_returns - (0.05 / 252)
        if excess.std() == 0:
            return 0.0
        return float(excess.mean() / excess.std() * np.sqrt(252))

    @property
    def max_drawdown(self) -> float:
        s = self.pnl_series
        if s.empty:
            return 0.0
        equity = self.portfolio_value + s.cumsum()
        peak = equity.cummax()
        dd = (equity - peak) / peak
        return float(dd.min())

    def summary(self) -> str:
        return (
            f"Trades: {self.total_trades} | "
            f"Win rate: {self.win_rate:.1%} | "
            f"Total P&L: ${self.total_pnl:+,.2f} | "
            f"CAGR: {self.cagr:.1%} | "
            f"Sharpe: {self.sharpe:.2f} | "
            f"Max DD: {self.max_drawdown:.1%}"
        )


class MFIMBacktester:
    """Runs the MFIM strategy against historical minute bars."""

    def __init__(
        self,
        symbols: list[str],
        start: date,
        end: date,
        portfolio_value: float = 100_000.0,
    ) -> None:
        self.symbols          = symbols
        self.start            = start
        self.end              = end
        self.portfolio_value  = portfolio_value
        self._strategy        = MFIMStrategy(portfolio_value=portfolio_value)

    def run(self) -> BacktestResults:
        results = BacktestResults(
            start            = self.start,
            end              = self.end,
            symbols          = self.symbols,
            portfolio_value  = self.portfolio_value,
        )

        trading_days = [
            d for d in (
                self.start + timedelta(days=i)
                for i in range((self.end - self.start).days + 1)
            )
            if is_trading_day(d)
        ]

        logger.info(
            f"[backtest] Running MFIM over {len(trading_days)} trading days "
            f"| {self.start} â†’ {self.end} | symbols: {self.symbols}"
        )

        for day in trading_days:
            day_bars = self._load_bars(day)
            if day_bars.empty:
                logger.debug(f"[backtest] No bars for {day} â€” skipping")
                continue

            self._strategy.new_day(as_of=day, symbols=self.symbols)

            # Load RVOL history for each symbol
            for sym in self.symbols:
                hist = self._load_bars_range(sym, day - timedelta(days=30), day)
                self._strategy.load_rvol_history(sym, hist)

            all_actions: list[dict] = []

            def _collect(action: dict) -> None:
                action["bar_date"] = day
                all_actions.append(action)

            feed = ReplayFeed(
                bars      = day_bars,
                on_bar    = self._strategy.on_bar,
                on_action = _collect,
            )
            feed.run()

            results.fills.extend(all_actions)
            stats = self._strategy.day_stats
            if stats and stats.trades > 0:
                logger.info(
                    f"[backtest] {day}: {self._strategy.summary()}"
                )

        logger.info(f"[backtest] Complete. {results.summary()}")
        return results

    def log_experiment(self, results: BacktestResults) -> str:
        """Log backtest results to the The Blob experiments table."""
        from experiments.experiment_log import log_experiment
        exp_id = log_experiment(
            strategy       = MFIMStrategy.STRATEGY_NAME,
            hypothesis     = "MFIM: ORB + VWAP + RVOL multi-factor intraday momentum",
            params         = {
                "symbols":          self.symbols,
                "start":            str(self.start),
                "end":              str(self.end),
                "portfolio_value":  self.portfolio_value,
            },
            result_summary = (
                f"CAGR={results.cagr:.1%} | "
                f"Sharpe={results.sharpe:.2f} | "
                f"MaxDD={results.max_drawdown:.1%} | "
                f"WinRate={results.win_rate:.1%} | "
                f"Trades={results.total_trades}"
            ),
            start_date     = self.start,
            end_date       = self.end,
            sharpe         = results.sharpe,
            cagr           = results.cagr,
            max_drawdown   = results.max_drawdown,
            notes          = results.summary(),
        )
        logger.info(f"[backtest] Logged to experiments table: {exp_id}")
        return exp_id

    def _load_bars(self, day: date) -> pd.DataFrame:
        """Load all symbols' 1-minute bars for a single day.

        Checks local cache first, then fetches from Alpaca if missing.
        """
        frames = []
        for sym in self.symbols:
            bars = self._load_bars_range(sym, day, day)
            if not bars.empty:
                bars["symbol"] = sym
                frames.append(bars)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _load_bars_range(
        self, symbol: str, start: date, end: date
    ) -> pd.DataFrame:
        """Load minute bars for one symbol over a date range.

        Cache: strategies/daytrader/.bar_cache/{symbol}/{YYYY-MM-DD}.parquet
        """
        cache_file = _CACHE_DIR / symbol / f"{start}_{end}.parquet"
        if cache_file.exists():
            return pd.read_parquet(cache_file)

        bars = self._fetch_from_alpaca(symbol, start, end)
        if not bars.empty:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            bars.to_parquet(cache_file)
        return bars

    def _fetch_from_alpaca(
        self, symbol: str, start: date, end: date
    ) -> pd.DataFrame:
        """Fetch minute bars from Alpaca historical API."""
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            from alpaca.data.enums import DataFeed
        except ImportError:
            logger.error("[backtest] alpaca-py not installed â€” cannot fetch bars")
            return pd.DataFrame()

        client = StockHistoricalDataClient(
            api_key    = os.environ.get("ALPACA_API_KEY", ""),
            secret_key = os.environ.get("ALPACA_SECRET_KEY", ""),
        )
        request = StockBarsRequest(
            symbol_or_symbols = symbol,
            timeframe         = TimeFrame.Minute,
            start             = pd.Timestamp(start).tz_localize("America/New_York"),
            end               = pd.Timestamp(end).replace(hour=23, minute=59)
                                  .tz_localize("America/New_York"),
            feed              = DataFeed.IEX,
        )
        try:
            raw = client.get_stock_bars(request).df
            if raw.empty:
                return pd.DataFrame()
            raw = raw.reset_index()
            raw = raw.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                                       "l": "low", "c": "close", "v": "volume"})
            if "timestamp" not in raw.columns and "symbol" in raw.columns:
                # Multi-symbol response has (symbol, timestamp) MultiIndex
                raw = raw.reset_index()
            raw["timestamp"] = pd.to_datetime(raw["timestamp"]).dt.tz_convert(
                "America/New_York"
            )
            return raw[["timestamp", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.warning(f"[backtest] Alpaca fetch failed for {symbol}: {e}")
            return pd.DataFrame()

