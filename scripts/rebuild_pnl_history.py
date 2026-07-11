"""scripts/rebuild_pnl_history.py

Deletes all portfolio_snapshots and pnl rows and rebuilds them cleanly
from the fills table, using actual cash-flow tracking and mark-to-market
prices at each date.

Usage:
    python scripts/rebuild_pnl_history.py            # dry run
    python scripts/rebuild_pnl_history.py --confirm  # apply
"""
import sys
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import func, select, text
from data.database import get_session
from data.models import FillRecord, OrderRecord, PortfolioSnapshot, PnLRecord, PriceBar

STRATEGY      = "momentum"
STARTING_CAP  = 100_000.0
RISK_FREE_RATE = 0.05


def _positions_as_of(fills: list, as_of: date) -> dict[str, int]:
    """Net positions from fills up to and including as_of date."""
    pos: dict[str, int] = {}
    for f in fills:
        if f.filled_at.date() <= as_of:
            delta = f.quantity if f.side == "buy" else -f.quantity
            pos[f.symbol] = pos.get(f.symbol, 0) + delta
    return {sym: qty for sym, qty in pos.items() if qty != 0}


def _cash_as_of(fills: list, as_of: date) -> float:
    """Actual cash balance: starting capital +/- all fill costs up to as_of."""
    cash = STARTING_CAP
    for f in fills:
        if f.filled_at.date() <= as_of:
            if f.side == "buy":
                cash -= f.fill_price * f.quantity
            else:
                cash += f.fill_price * f.quantity
    return cash


def _prices_at(symbols: list[str], as_of: date) -> dict[str, float]:
    """Latest adj_close per symbol up to as_of date."""
    if not symbols:
        return {}
    with get_session() as s:
        sub = (
            select(PriceBar.symbol, func.max(PriceBar.date).label("max_date"))
            .where(PriceBar.symbol.in_(symbols))
            .where(PriceBar.date <= as_of)
            .group_by(PriceBar.symbol)
            .subquery()
        )
        rows = s.execute(
            select(PriceBar.symbol, PriceBar.adj_close)
            .join(sub, (PriceBar.symbol == sub.c.symbol) & (PriceBar.date == sub.c.max_date))
        ).fetchall()
    return {r.symbol: float(r.adj_close) for r in rows}


def _build_history(fills: list) -> list[dict]:
    """Compute clean snapshot + PnL for every distinct fill date."""
    dates = sorted({f.filled_at.date() for f in fills})
    history = []
    prev_value = STARTING_CAP
    peak_value = STARTING_CAP

    for d in dates:
        positions = _positions_as_of(fills, d)
        cash      = _cash_as_of(fills, d)
        prices    = _prices_at(list(positions.keys()), d)

        market_value  = sum(qty * prices.get(sym, 0.0) for sym, qty in positions.items())
        total_value   = cash + market_value
        gross_exp     = market_value
        net_exp       = market_value

        cumulative_pnl = total_value - STARTING_CAP
        daily_pnl      = total_value - prev_value
        peak_value     = max(peak_value, total_value)
        drawdown       = (total_value - peak_value) / peak_value if peak_value > 0 else 0.0

        history.append({
            "date":           d,
            "positions":      positions,
            "prices":         prices,
            "cash":           round(cash, 2),
            "gross_exposure": round(gross_exp, 2),
            "net_exposure":   round(net_exp, 2),
            "total_value":    round(total_value, 2),
            "daily_pnl":      round(daily_pnl, 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "drawdown":       round(drawdown, 6),
        })
        prev_value = total_value

    return history


def _preview(history: list[dict]) -> None:
    print("\n=== CLEAN PNL / SNAPSHOT HISTORY (DRY RUN) ===\n")
    for h in history:
        pos_str = ", ".join(f"{s}({q})" for s, q in sorted(h["positions"].items()))
        print(f"  {h['date']}  total=${h['total_value']:>12,.2f}  "
              f"daily={h['daily_pnl']:>+10,.2f}  "
              f"cumul={h['cumulative_pnl']:>+10,.2f}  "
              f"dd={h['drawdown']:.2%}")
        print(f"    cash=${h['cash']:,.2f}  positions: {pos_str}")
        print()
    print("Run with --confirm to apply.\n")


def _apply(history: list[dict]) -> None:
    print("\n=== REBUILDING SNAPSHOT + PNL HISTORY ===\n")
    with get_session() as s:
        snap_del = s.execute(text("DELETE FROM portfolio_snapshots WHERE strategy = :strat"),
                             {"strat": STRATEGY})
        pnl_del  = s.execute(text("DELETE FROM pnl WHERE strategy = :strat"),
                             {"strat": STRATEGY})
        s.commit()
        print(f"  Deleted {snap_del.rowcount} snapshot rows and {pnl_del.rowcount} pnl rows.\n")

        for h in history:
            snap = PortfolioSnapshot(
                strategy      = STRATEGY,
                snapshot_date = h["date"],
                cash          = h["cash"],
                gross_exposure= h["gross_exposure"],
                net_exposure  = h["net_exposure"],
                total_value   = h["total_value"],
                positions     = h["positions"],
                recorded_at   = datetime.utcnow(),
            )
            pnl = PnLRecord(
                strategy       = STRATEGY,
                date           = h["date"],
                daily_pnl      = h["daily_pnl"],
                cumulative_pnl = h["cumulative_pnl"],
                drawdown       = h["drawdown"],
                recorded_at    = datetime.utcnow(),
            )
            s.add(snap)
            s.add(pnl)
            pos_str = ", ".join(f"{sym}({qty})" for sym, qty in sorted(h["positions"].items()))
            print(f"  {h['date']}  ${h['total_value']:>10,.2f}  "
                  f"daily={h['daily_pnl']:>+9,.2f}  "
                  f"dd={h['drawdown']:.2%}  [{pos_str}]")

        s.commit()

    print("\n  Done. Reload the dashboard to see clean PnL history.\n")


if __name__ == "__main__":
    confirm = "--confirm" in sys.argv

    # Load all fills ordered by time
    with get_session() as s:
        fills = s.execute(
            select(FillRecord)
            .join(OrderRecord, FillRecord.order_id == OrderRecord.order_id)
            .where(OrderRecord.strategy == STRATEGY)
            .order_by(FillRecord.filled_at)
        ).scalars().all()

    if not fills:
        print("No fills found. Run clean_paper_fills.py first.")
        sys.exit(1)

    history = _build_history(fills)

    if confirm:
        _apply(history)
    else:
        _preview(history)
