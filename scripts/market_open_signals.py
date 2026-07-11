"""Re-run momentum signals at market open to preview today's likely rebalance.

Runs after market_open_check.py (gap analysis). Uses current prices already
in the DB (updated by yesterday's pipeline) to score the full universe and
predict what the 4:05pm pipeline will do.

Logs to terminal:
  - SIGNAL_PREVIEW: expected top-5 with ranks and scores
  - RANK_CHANGE: any symbol entering or leaving the top-5 vs yesterday
  - ACTION_PREVIEW: expected entries and exits at today's close
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from sqlalchemy import text

from ingestion.calendar import is_trading_day
from signals.momentum_signals import MomentumSignalGenerator
from data.pipeline_log import log_event
from data.database import get_session


def _get_current_positions() -> set[str]:
    with get_session() as s:
        row = s.execute(text("""
            SELECT positions FROM portfolio_snapshots
            ORDER BY snapshot_date DESC LIMIT 1
        """)).fetchone()
    if row and row.positions:
        return set(row.positions.keys())
    return set()


def _get_yesterday_top5() -> list[str]:
    """Top-5 from the most recent signal run."""
    with get_session() as s:
        rows = s.execute(text("""
            SELECT symbol FROM signals
            WHERE as_of_date = (SELECT MAX(as_of_date) FROM signals)
            ORDER BY score DESC LIMIT 5
        """)).fetchall()
    return [r.symbol for r in rows]


def run() -> None:
    today = date.today()

    if not is_trading_day(today):
        logger.info(f"{today} is not a trading day — skipping signal preview")
        return

    logger.info("[open-signals] Running morning signal preview...")

    try:
        gen = MomentumSignalGenerator()
        signals = gen.generate(today)
    except Exception as e:
        logger.warning(f"[open-signals] Signal generation failed: {e}")
        log_event(today, "SIGNAL_PREVIEW", "morning signal preview unavailable", detail=str(e))
        return

    if not signals:
        log_event(today, "SIGNAL_PREVIEW", "no signals generated at open")
        return

    top5 = signals[:5]
    yesterday_top5 = set(_get_yesterday_top5())
    current_positions = _get_current_positions()
    today_top5 = {s.symbol for s in top5}

    # Log the full expected top-5
    ranked = "  ".join(f"#{i+1} {s.symbol}" for i, s in enumerate(top5))
    log_event(today, "SIGNAL_PREVIEW",
              f"morning preview  ·  {ranked}",
              detail=f"scored {len(signals)} symbols  ·  top pick: {top5[0].symbol} ({top5[0].score:.3f})")
    logger.info(f"[open-signals] Top-5 preview: {[s.symbol for s in top5]}")

    # Flag rank changes vs yesterday
    entering = today_top5 - yesterday_top5
    exiting  = yesterday_top5 - today_top5
    for sym in entering:
        log_event(today, "RANK_CHANGE",
                  f"entered top-5  ·  new candidate for entry",
                  detail="not in yesterday's top-5", symbol=sym)
    for sym in exiting:
        log_event(today, "RANK_CHANGE",
                  f"dropped from top-5  ·  candidate for exit at close",
                  detail="was in yesterday's top-5", symbol=sym)

    # Preview expected actions at 4:05pm
    expected_entries = [s.symbol for s in top5 if s.symbol not in current_positions]
    expected_exits   = [sym for sym in current_positions if sym not in today_top5]
    expected_holds   = [s.symbol for s in top5 if s.symbol in current_positions]

    if expected_entries:
        log_event(today, "ACTION_PREVIEW",
                  f"expected entries at close: {', '.join(expected_entries)}",
                  detail="pending 4:05pm pipeline confirmation")
    if expected_exits:
        log_event(today, "ACTION_PREVIEW",
                  f"expected exits at close: {', '.join(expected_exits)}",
                  detail="pending 4:05pm pipeline confirmation")
    if expected_holds:
        log_event(today, "ACTION_PREVIEW",
                  f"holding: {', '.join(expected_holds)}",
                  detail="unchanged from current positions")

    logger.info("[open-signals] Morning signal preview complete")


if __name__ == "__main__":
    run()
