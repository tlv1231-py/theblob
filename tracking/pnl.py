"""Daily PnL calculation — mark-to-market from portfolio snapshots."""
from datetime import date, datetime

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select

from data.database import get_session
from data.models import PnLRecord, PortfolioSnapshot

STARTING_CAPITAL = 100_000.0
RISK_FREE_RATE = 0.05
ROLLING_SHARPE_WINDOW = 63   # ~3 months of trading days


def compute_and_store_daily_pnl(strategy: str, as_of_date: date, total_value: float) -> dict:
    """Compute mark-to-market daily PnL and persist to pnl table.

    Args:
        strategy:    strategy name
        as_of_date:  the trading date this PnL covers
        total_value: today's total portfolio value (from snapshot)

    Returns dict with all computed metrics.
    """
    with get_session() as session:
        # All prior PnL records for rolling calculations
        prior_records = (
            session.execute(
                select(PnLRecord)
                .where(PnLRecord.strategy == strategy)
                .where(PnLRecord.date < as_of_date)
                .order_by(PnLRecord.date)
            )
            .scalars()
            .all()
        )

    # Yesterday's total portfolio value (for daily return)
    if prior_records:
        yesterday = prior_records[-1]
        prev_total = STARTING_CAPITAL + yesterday.cumulative_pnl
        cumulative_pnl = total_value - STARTING_CAPITAL
        daily_pnl = total_value - prev_total
    else:
        # First day
        prev_total = STARTING_CAPITAL
        cumulative_pnl = total_value - STARTING_CAPITAL
        daily_pnl = total_value - STARTING_CAPITAL

    # Peak equity for drawdown (high-water mark)
    all_values = [STARTING_CAPITAL + r.cumulative_pnl for r in prior_records] + [total_value]
    peak_equity = max(all_values)
    drawdown = (total_value - peak_equity) / peak_equity if peak_equity > 0 else 0.0

    # Rolling 63-day Sharpe from historical daily returns
    rolling_sharpe = _compute_rolling_sharpe(prior_records, daily_pnl, prev_total)

    with get_session() as session:
        # Skip if PnL row already exists for this date — prevents duplicates on double-run
        existing = session.execute(
            select(PnLRecord)
            .where(PnLRecord.strategy == strategy)
            .where(PnLRecord.date == as_of_date)
        ).first()
        if existing:
            logger.info(f"[pnl] PnL for {strategy} {as_of_date} already exists — skipping write.")
        else:
            rec = PnLRecord(
                strategy=strategy,
                date=as_of_date,
                daily_pnl=round(daily_pnl, 2),
                cumulative_pnl=round(cumulative_pnl, 2),
                drawdown=round(drawdown, 6),
                recorded_at=datetime.utcnow(),
            )
            session.add(rec)
            session.commit()

    result = {
        "date": as_of_date,
        "total_value": total_value,
        "daily_pnl": daily_pnl,
        "cumulative_pnl": cumulative_pnl,
        "drawdown": drawdown,
        "rolling_sharpe_63d": rolling_sharpe,
        "peak_equity": peak_equity,
    }

    logger.info(
        f"[pnl] {strategy} {as_of_date}: "
        f"value=${total_value:,.2f} | "
        f"daily={daily_pnl:+,.2f} ({daily_pnl/prev_total:+.2%}) | "
        f"cumulative={cumulative_pnl:+,.2f} ({cumulative_pnl/STARTING_CAPITAL:+.2%}) | "
        f"dd={drawdown:.2%} | sharpe(63d)={rolling_sharpe:.2f}"
    )
    return result


def _compute_rolling_sharpe(prior_records: list, today_pnl: float, prev_total: float) -> float:
    """Compute rolling 63-day Sharpe from the most recent records + today."""
    if not prior_records:
        return float("nan")

    # Reconstruct daily returns from cumulative PnL records
    values = []
    prev_val = STARTING_CAPITAL
    for r in prior_records:
        val = STARTING_CAPITAL + r.cumulative_pnl
        values.append(val)

    # Include today
    values.append(STARTING_CAPITAL + prior_records[-1].cumulative_pnl + today_pnl
                  if prior_records else STARTING_CAPITAL + today_pnl)

    # Take last ROLLING_SHARPE_WINDOW + 1 values to get WINDOW returns
    window_values = values[-(ROLLING_SHARPE_WINDOW + 1):]
    if len(window_values) < 5:
        return float("nan")

    returns = pd.Series(window_values).pct_change().dropna()
    daily_rf = RISK_FREE_RATE / 252
    excess = returns - daily_rf
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(252))


def load_pnl_history(strategy: str) -> pd.DataFrame:
    """Load all PnL records for a strategy as a DataFrame."""
    with get_session() as session:
        rows = session.execute(
            select(PnLRecord)
            .where(PnLRecord.strategy == strategy)
            .order_by(PnLRecord.date)
        ).scalars().all()

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([{
        "date": r.date,
        "daily_pnl": r.daily_pnl,
        "cumulative_pnl": r.cumulative_pnl,
        "drawdown": r.drawdown,
        "total_value": STARTING_CAPITAL + r.cumulative_pnl,
    } for r in rows]).set_index("date")
