"""Daytrader entry point â€” runs the MFIM strategy live via Alpaca WebSocket.

Modes:
  live      â€” streams real-time 1-minute bars from Alpaca, executes paper fills
  backtest  â€” replays historical minute bars, logs results to experiments table

Usage:
  python run_daytrader.py                          # live paper mode
  python run_daytrader.py --mode backtest          # backtest 2024
  python run_daytrader.py --mode backtest \\
      --start 2024-01-01 --end 2024-12-31

Requirements:
  pip install alpaca-py
  ALPACA_API_KEY and ALPACA_SECRET_KEY in .env
"""
import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from zoneinfo import ZoneInfo

load_dotenv()

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ET = ZoneInfo("America/New_York")

# Universe: liquid mega-caps + index ETFs + The Blob momentum top-10
# All symbols on a single Alpaca WebSocket connection â€” no extra cost.
# Min ADTV ~10M shares so 10bps slippage assumption holds.
_BASE_UNIVERSE = [
    # Index ETFs â€” always included, highest intraday volume
    "SPY", "QQQ", "IWM",
    # Mega-cap tech â€” deepest order books, cleanest ORB setups
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
    # High-beta semiconductors + hardware
    "AMD", "AVGO",
    # Financials â€” move hard on macro/rate news
    "JPM", "GS",
    # Sector ETFs â€” diversify setup sources
    "XLE", "GLD", "TLT",
]
_TOP_MOMENTUM_N = 10


def _build_universe(as_of: date | None = None) -> list[str]:
    """Combine index ETFs with today's top momentum stocks."""
    from strategies.daytrader.signals.momentum_bias import get_momentum_universe
    momentum = get_momentum_universe(as_of=as_of, top_n=_TOP_MOMENTUM_N)
    combined = list(dict.fromkeys(_BASE_UNIVERSE + list(momentum.keys())))
    logger.info(f"[universe] {len(combined)} symbols: {combined}")
    return combined


# â”€â”€ Live mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async def run_live() -> None:
    from strategies.daytrader.models.strategy import MFIMStrategy
    from strategies.daytrader.execution.feed import AlpacaBarFeed
    from strategies.daytrader.execution.executor import PaperBracketExecutor
    from strategies.daytrader.signals.vwap import RVOLCalculator
    from risk.intraday_risk import IntradayRiskEngine
    import yaml

    cfg      = yaml.safe_load((_ROOT / "strategies/daytrader/config.yaml").read_text())
    today    = datetime.now(_ET).date()
    symbols  = _build_universe(as_of=today)

    portfolio_value = 100_000.0   # TODO: read from latest portfolio snapshot

    strategy  = MFIMStrategy(portfolio_value=portfolio_value, config=cfg)
    executor  = PaperBracketExecutor(
        portfolio_value = portfolio_value,
        slippage_bps    = cfg["execution"]["slippage_bps"],
    )
    risk      = IntradayRiskEngine(portfolio_value=portfolio_value, cfg=cfg)

    strategy.new_day(as_of=today, symbols=symbols)
    risk.new_day(as_of=today)

    def on_action(action: dict) -> None:
        sym = action["symbol"]
        a   = action["action"]

        if a == "enter":
            approved, reason = risk.check_entry(sym)
            if not approved:
                logger.warning(f"[risk] Entry blocked for {sym}: {reason}")
                return
            fill = executor.execute_action(action)
            if fill:
                risk.record_entry(sym, datetime.now(_ET))
        else:
            fill = executor.execute_action(action)
            if fill:
                risk.record_close(sym, action.get("pnl", 0.0))

    feed = AlpacaBarFeed(
        symbols   = symbols,
        on_bar    = strategy.on_bar,
        on_action = on_action,
    )

    logger.info(f"[daytrader] Live session starting â€” {today} | {len(symbols)} symbols")
    await feed.run()


# â”€â”€ Backtest mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_backtest(start: date, end: date, symbols: list[str] | None = None) -> None:
    from strategies.daytrader.backtest.backtester import MFIMBacktester

    symbols = symbols or _build_universe()

    bt = MFIMBacktester(
        symbols          = symbols,
        start            = start,
        end              = end,
        portfolio_value  = 100_000.0,
    )

    logger.info(f"[backtest] MFIM {start} â†’ {end} | {len(symbols)} symbols")
    results = bt.run()

    print("\n" + "=" * 60)
    print("  MFIM BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Period:      {start} to {end}")
    print(f"  Symbols:     {len(symbols)}")
    print(f"  Total trades:{results.total_trades}")
    print(f"  Win rate:    {results.win_rate:.1%}")
    print(f"  Total P&L:   ${results.total_pnl:+,.2f}")
    print(f"  CAGR:        {results.cagr:.1%}")
    print(f"  Sharpe:      {results.sharpe:.2f}")
    print(f"  Max DD:      {results.max_drawdown:.1%}")
    print("=" * 60)

    exp_id = bt.log_experiment(results)
    print(f"  Logged to experiments: {exp_id}")
    print()


# â”€â”€ CLI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="The Blob Daytrader â€” MFIM strategy runner")
    p.add_argument("--mode",    choices=["live", "backtest"], default="live")
    p.add_argument("--start",   default="2024-01-01", help="Backtest start (YYYY-MM-DD)")
    p.add_argument("--end",     default="2024-12-31", help="Backtest end (YYYY-MM-DD)")
    p.add_argument("--symbols", default=None, help="Comma-separated symbol list override")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.mode == "backtest":
        syms = args.symbols.split(",") if args.symbols else None
        run_backtest(
            start   = date.fromisoformat(args.start),
            end     = date.fromisoformat(args.end),
            symbols = syms,
        )
    else:
        logger.info("[daytrader] Starting live session...")
        asyncio.run(run_live())

