"""Reset the paper portfolio by clearing all trading state for a strategy.

Usage:
    python scripts/reset_paper_portfolio.py              # dry run (safe, default)
    python scripts/reset_paper_portfolio.py --dry-run    # same as above
    python scripts/reset_paper_portfolio.py --confirm    # EXECUTES deletions after countdown

Tables cleared (strategy-filtered):
    signals, orders, fills, portfolio_snapshots, pnl

Tables NEVER touched:
    price_bars, experiments

An audit entry is written to the experiments table on successful reset.
"""
import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from loguru import logger
from sqlalchemy import text

from data.database import get_session

STRATEGY = "momentum"
RESET_REASON = "Paper portfolio reset — clearing double-run test data from 2026-05-29. Clean restart for 20-day monitoring period beginning 2026-06-02."

# Tables to wipe (strategy-filtered) — ORDER MATTERS: fills before orders (FK)
CLEARABLE_TABLES = [
    ("fills",                "JOIN orders o ON fills.order_id = o.order_id WHERE o.strategy = :strategy"),
    ("orders",               "WHERE strategy = :strategy"),
    ("signals",              "WHERE strategy = :strategy"),
    ("portfolio_snapshots",  "WHERE strategy = :strategy"),
    ("pnl",                  "WHERE strategy = :strategy"),
]

# Tables that are never touched
PRESERVED_TABLES = ["price_bars", "experiments"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _count(session, table: str, where: str) -> int:
    """Count rows that would be affected by the delete."""
    # Convert the DELETE-style WHERE clause into a SELECT COUNT(*)
    # For fills the join is embedded; handle separately.
    if table == "fills":
        sql = text("""
            SELECT COUNT(*) FROM fills
            JOIN orders o ON fills.order_id = o.order_id
            WHERE o.strategy = :strategy
        """)
    else:
        sql = text(f"SELECT COUNT(*) FROM {table} WHERE strategy = :strategy")
    return session.execute(sql, {"strategy": STRATEGY}).scalar()


def _count_all(session, table: str) -> int:
    sql = text(f"SELECT COUNT(*) FROM {table}")
    return session.execute(sql).scalar()


def _get_counts(session) -> dict:
    counts = {}
    for table, where in CLEARABLE_TABLES:
        counts[table] = _count(session, table, where)
    for table in PRESERVED_TABLES:
        counts[table] = _count_all(session, table)
    return counts


def _log_audit(session, counts_deleted: dict) -> None:
    """Write a reset event to the experiments table as an immutable audit record."""
    import json, uuid
    exp_id = str(uuid.uuid4())[:8]
    rows_deleted_summary = ", ".join(f"{t}={n}" for t, n in counts_deleted.items())
    sql = text("""
        INSERT INTO experiments
            (experiment_id, strategy, hypothesis, params, result_summary,
             start_date, end_date, sharpe, cagr, max_drawdown, notes, logged_at)
        VALUES
            (:experiment_id, :strategy, :hypothesis, :params, :result_summary,
             :start_date, :end_date, NULL, NULL, NULL, :notes, :logged_at)
    """)
    session.execute(sql, {
        "experiment_id": exp_id,
        "strategy": STRATEGY,
        "hypothesis": "SYSTEM: Paper portfolio reset",
        "params": json.dumps({
            "reset_reason": RESET_REASON,
            "rows_deleted": counts_deleted,
            "strategy": STRATEGY,
        }),
        "result_summary": f"Reset executed. Deleted: {rows_deleted_summary}",
        "start_date": date(2026, 5, 29),
        "end_date": date.today(),
        "notes": RESET_REASON,
        "logged_at": datetime.utcnow(),
    })
    logger.info(f"[audit] Reset event logged to experiments table as {exp_id}")


# ── Dry run ───────────────────────────────────────────────────────────────────

def dry_run() -> None:
    logger.info("=" * 60)
    logger.info("PAPER PORTFOLIO RESET — DRY RUN")
    logger.info(f"Strategy: {STRATEGY}")
    logger.info("=" * 60)

    with get_session() as session:
        counts = _get_counts(session)

    logger.info("")
    logger.info("Tables that WOULD BE CLEARED (strategy-filtered):")
    total_to_delete = 0
    for table, _ in CLEARABLE_TABLES:
        n = counts[table]
        total_to_delete += n
        logger.info(f"  {table:<25} {n:>6} rows would be deleted")

    logger.info("")
    logger.info("Tables that will NOT be touched (preserved):")
    for table in PRESERVED_TABLES:
        n = counts[table]
        logger.info(f"  {table:<25} {n:>6} rows preserved")

    logger.info("")
    logger.info(f"Total rows that would be deleted: {total_to_delete}")
    logger.info("")
    logger.info("DRY RUN COMPLETE — no data was modified.")
    logger.info("To execute, re-run with: python scripts/reset_paper_portfolio.py --confirm")
    logger.info("=" * 60)


# ── Execute ───────────────────────────────────────────────────────────────────

def execute() -> None:
    logger.warning("=" * 60)
    logger.warning("PAPER PORTFOLIO RESET — EXECUTE MODE")
    logger.warning(f"Strategy:  {STRATEGY}")
    logger.warning(f"Reason:    {RESET_REASON}")
    logger.warning("=" * 60)

    with get_session() as session:
        counts_before = _get_counts(session)

    logger.warning("")
    logger.warning("The following rows WILL BE PERMANENTLY DELETED:")
    for table, _ in CLEARABLE_TABLES:
        logger.warning(f"  {table:<25} {counts_before[table]:>6} rows")
    logger.warning("")
    logger.warning("The following tables will NOT be touched:")
    for table in PRESERVED_TABLES:
        logger.warning(f"  {table:<25} {counts_before[table]:>6} rows (preserved)")
    logger.warning("")

    # 5-second countdown with cancel option
    logger.warning("Executing in 5 seconds. Press Ctrl+C to cancel.")
    for i in range(5, 0, -1):
        logger.warning(f"  {i}...")
        time.sleep(1)
    logger.warning("Executing now.")
    logger.warning("")

    counts_deleted: dict[str, int] = {}

    with get_session() as session:
        # Delete fills first (references orders via FK)
        r = session.execute(text("""
            DELETE FROM fills
            WHERE order_id IN (
                SELECT order_id FROM orders WHERE strategy = :strategy
            )
        """), {"strategy": STRATEGY})
        counts_deleted["fills"] = r.rowcount
        logger.info(f"  Deleted {r.rowcount} rows from fills")

        r = session.execute(text("DELETE FROM orders WHERE strategy = :strategy"), {"strategy": STRATEGY})
        counts_deleted["orders"] = r.rowcount
        logger.info(f"  Deleted {r.rowcount} rows from orders")

        r = session.execute(text("DELETE FROM signals WHERE strategy = :strategy"), {"strategy": STRATEGY})
        counts_deleted["signals"] = r.rowcount
        logger.info(f"  Deleted {r.rowcount} rows from signals")

        r = session.execute(text("DELETE FROM portfolio_snapshots WHERE strategy = :strategy"), {"strategy": STRATEGY})
        counts_deleted["portfolio_snapshots"] = r.rowcount
        logger.info(f"  Deleted {r.rowcount} rows from portfolio_snapshots")

        r = session.execute(text("DELETE FROM pnl WHERE strategy = :strategy"), {"strategy": STRATEGY})
        counts_deleted["pnl"] = r.rowcount
        logger.info(f"  Deleted {r.rowcount} rows from pnl")

        # Audit log — written in same transaction so it's atomic with the deletes
        _log_audit(session, counts_deleted)

        session.commit()

    logger.info("")
    total = sum(counts_deleted.values())
    logger.success(f"Total rows deleted: {total}")
    logger.success("")
    logger.success("RESET COMPLETE — paper portfolio cleared. Ready for clean start 2026-06-02.")
    logger.success("=" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset the paper portfolio trading state. Dry run by default."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview what would be deleted without modifying anything (default behavior)",
    )
    group.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="EXECUTE the reset. Deletes all trading state for the strategy.",
    )
    args = parser.parse_args()

    try:
        if args.confirm:
            execute()
        else:
            # Default and --dry-run both go here
            dry_run()
    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("Cancelled by user. No data was modified.")
        sys.exit(0)


if __name__ == "__main__":
    main()
