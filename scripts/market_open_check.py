"""Market open intelligence check — runs at 9:30am ET via GitHub Actions.

Fetches opening prices for all held positions, computes overnight gaps,
estimates portfolio value at open, and logs everything to the terminal feed.

Flags any position with a gap > GAP_ALERT_PCT as a GAP_ALERT so the
system feed surfaces risk immediately at open rather than waiting for
the 4:05pm pipeline.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import time
import yfinance as yf
from loguru import logger
from sqlalchemy import text

from ingestion.calendar import is_trading_day
from data.pipeline_log import log_event
from data.database import get_session

GAP_ALERT_PCT = 2.0   # flag if overnight gap exceeds ±2%
STARTING_CAPITAL = 100_000.0


def _get_held_positions() -> dict[str, int]:
    """Return {symbol: qty} from latest portfolio snapshot."""
    with get_session() as s:
        row = s.execute(text("""
            SELECT positions FROM portfolio_snapshots
            ORDER BY snapshot_date DESC LIMIT 1
        """)).fetchone()
    if row and row.positions:
        return dict(row.positions)
    return {}


def _get_prev_closes(symbols: list[str]) -> dict[str, float]:
    """Return previous close prices from price_bars (last stored bar per symbol)."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT ON (symbol) symbol, adj_close
            FROM price_bars WHERE symbol = ANY(:syms)
            ORDER BY symbol, date DESC
        """), {"syms": symbols}).fetchall()
    return {r.symbol: float(r.adj_close) for r in rows}


def _fetch_open_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch today's opening price for each symbol via yfinance 1m bars.

    Retries once if the market hasn't printed bars yet (can take 1-2 min at open).
    """
    for attempt in range(2):
        try:
            raw = yf.download(
                tickers=symbols,
                period="1d",
                interval="1m",
                progress=False,
                auto_adjust=True,
            )
            if raw.empty:
                if attempt == 0:
                    logger.info("No bars yet — waiting 90s and retrying")
                    time.sleep(90)
                    continue
                return {}

            # yfinance returns MultiIndex columns for multi-symbol
            if isinstance(raw.columns, __import__("pandas").MultiIndex):
                opens = raw["Open"].iloc[0]
                return {sym: float(opens[sym]) for sym in symbols if sym in opens.columns}
            else:
                # single symbol
                return {symbols[0]: float(raw["Open"].iloc[0])}
        except Exception as e:
            logger.warning(f"yfinance open fetch failed: {e}")
            if attempt == 0:
                time.sleep(60)
    return {}


def run() -> None:
    today = date.today()

    if not is_trading_day(today):
        logger.info(f"{today} is not a trading day — skipping open check")
        return

    # Log MARKET_OPEN first
    log_event(today, "MARKET_OPEN", "NYSE open  ·  9:30am ET")
    logger.info("[open] MARKET_OPEN logged")

    positions = _get_held_positions()
    if not positions:
        logger.info("[open] No held positions — nothing to price")
        return

    symbols = list(positions.keys())
    prev_closes = _get_prev_closes(symbols)

    logger.info(f"[open] Fetching opening prices for {symbols}")
    open_prices = _fetch_open_prices(symbols)

    if not open_prices:
        logger.warning("[open] Could not fetch opening prices")
        log_event(today, "OPEN_PRICE", "opening prices unavailable — yfinance delay")
        return

    # Per-position gap analysis
    total_open_value = 0.0
    for sym, qty in positions.items():
        op = open_prices.get(sym)
        prev = prev_closes.get(sym)
        if op is None:
            continue

        pos_value = qty * op
        total_open_value += pos_value

        if prev and prev > 0:
            gap_pct = (op - prev) / prev * 100
            gap_str = f"{gap_pct:+.2f}%"
            detail = f"prev close ${prev:.2f}  ·  qty {qty}  ·  value ${pos_value:,.0f}"

            log_event(today, "OPEN_PRICE",
                      f"opened ${op:.2f}  ·  {gap_str} overnight",
                      detail=detail, symbol=sym)

            if abs(gap_pct) >= GAP_ALERT_PCT:
                log_event(today, "GAP_ALERT",
                          f"gapped {gap_str} overnight  ·  ${prev:.2f} → ${op:.2f}",
                          detail=f"qty {qty}  ·  impact ${abs(qty*(op-prev)):,.0f}",
                          symbol=sym)
                logger.warning(f"[open] GAP ALERT {sym}: {gap_str}")
        else:
            log_event(today, "OPEN_PRICE", f"opened ${op:.2f}",
                      detail=f"qty {qty}  ·  value ${pos_value:,.0f}", symbol=sym)

    # Portfolio open estimate
    if total_open_value > 0:
        log_event(today, "OPEN_SNAPSHOT",
                  f"portfolio est. ${total_open_value:,.0f} at open",
                  detail=f"based on {len(open_prices)} of {len(symbols)} positions priced")
        logger.info(f"[open] Portfolio open estimate: ${total_open_value:,.0f}")

    logger.info("[open] Market open check complete")


if __name__ == "__main__":
    run()
