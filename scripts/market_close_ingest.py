"""Pre-ingest closing data at market close so the 4:05pm pipeline runs fast.

Waits 2 minutes for yfinance to populate final closing prices, then ingests
all symbols. By the time run_pipeline.py fires at 4:05pm, the DB is already
current and the ingest step completes near-instantly.

Runs via GitHub Actions at 4:00pm ET (20:00 UTC) Mon-Fri.
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from ingestion.calendar import is_trading_day
from ingestion.market_data.yfinance_fetcher import fetch_and_store
from data.pipeline_log import log_event
from config.universe import UNIVERSE as _UNIVERSE_MAP

SYMBOLS = list(_UNIVERSE_MAP.keys()) + ["SPY", "QQQ", "IEF"]
WAIT_SECONDS = 120  # give yfinance time to publish final prices


def run() -> None:
    today = date.today()

    if not is_trading_day(today):
        logger.info(f"{today} is not a trading day — skipping")
        return

    # Log market close immediately
    log_event(today, "MARKET_CLOSE", "NYSE closed  ·  4:00pm ET  ·  pipeline incoming")

    logger.info(f"[close-ingest] Waiting {WAIT_SECONDS}s for closing prices to settle...")
    time.sleep(WAIT_SECONDS)

    logger.info(f"[close-ingest] Pre-ingesting {len(SYMBOLS)} symbols...")
    results = fetch_and_store(symbols=SYMBOLS, end=today, run_date=today)
    total = sum(results.values())

    log_event(today, "CLOSE_INGEST",
              f"pre-ingested {total} bars across {len(results)} symbols",
              detail="pipeline at 4:05pm will skip re-fetch")
    logger.info(f"[close-ingest] Done — {total} bars stored. Pipeline will run fast.")


if __name__ == "__main__":
    run()
