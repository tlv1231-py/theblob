"""One-time script: fetch IEF (iShares 7-10 Year Treasury Bond ETF) into price_bars.

IEF is used as the bond proxy in the 60/40 benchmark on the Benchmarks dashboard page.

Usage:
    python scripts/fetch_ief.py

Fetches from 2015-01-01 to today and upserts into price_bars via the same
append-only path used by the main ingestion pipeline.
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from datetime import date

from loguru import logger

from ingestion.market_data.yfinance_fetcher import fetch_and_store


def main() -> None:
    logger.info("Fetching IEF (bond proxy for 60/40 benchmark)...")
    results = fetch_and_store(
        symbols=["IEF"],
        start=date(2015, 1, 1),
        end=date.today(),
    )
    rows = results.get("IEF", 0)
    if rows > 0:
        logger.info(f"IEF: {rows} bars inserted into price_bars.")
    else:
        logger.info("IEF: 0 new bars inserted (already up to date, or no data returned).")


if __name__ == "__main__":
    main()
