"""End-of-day portfolio snapshot. Runs after all fills are written for the day."""
from datetime import date, datetime

from loguru import logger
from sqlalchemy import func, select

from data.database import get_session
from data.models import FillRecord, PortfolioSnapshot, PriceBar

STARTING_CAPITAL = 100_000.0


def compute_net_positions(strategy: str) -> dict[str, int]:
    """Aggregate all fills for a strategy to get current net share counts."""
    from data.models import OrderRecord
    with get_session() as session:
        fills = (
            session.execute(
                select(FillRecord.symbol, FillRecord.side, FillRecord.quantity)
                .join(OrderRecord, FillRecord.order_id == OrderRecord.order_id)
                .where(OrderRecord.strategy == strategy)
            )
            .fetchall()
        )

    positions: dict[str, int] = {}
    for row in fills:
        delta = row.quantity if row.side == "buy" else -row.quantity
        positions[row.symbol] = positions.get(row.symbol, 0) + delta

    # Drop positions that have been fully closed (net 0)
    return {sym: qty for sym, qty in positions.items() if qty != 0}


def get_latest_prices(symbols: list[str], as_of_date: date) -> dict[str, float]:
    """Latest adj_close per symbol up to as_of_date."""
    if not symbols:
        return {}
    with get_session() as session:
        latest_subq = (
            select(PriceBar.symbol, func.max(PriceBar.date).label("max_date"))
            .where(PriceBar.symbol.in_(symbols))
            .where(PriceBar.date <= as_of_date)
            .group_by(PriceBar.symbol)
            .subquery()
        )
        rows = session.execute(
            select(PriceBar.symbol, PriceBar.adj_close)
            .join(
                latest_subq,
                (PriceBar.symbol == latest_subq.c.symbol)
                & (PriceBar.date == latest_subq.c.max_date),
            )
        ).fetchall()
    return {row.symbol: row.adj_close for row in rows}


def write_snapshot(strategy: str, as_of_date: date) -> dict:
    """Compute and persist an end-of-day portfolio snapshot.

    Returns the snapshot dict (useful for chaining into PnL calculation).
    """
    positions = compute_net_positions(strategy)
    prices = get_latest_prices(list(positions.keys()), as_of_date)

    # Market values
    market_values: dict[str, float] = {
        sym: qty * prices.get(sym, 0.0)
        for sym, qty in positions.items()
    }
    gross_exposure = sum(abs(v) for v in market_values.values())
    net_exposure = sum(market_values.values())  # long-only → same as gross

    # Cash = actual cash flows: starting capital +/- every fill (buy reduces, sell adds)
    from data.models import OrderRecord
    with get_session() as session:
        all_fills = session.execute(
            select(FillRecord.side, FillRecord.quantity, FillRecord.fill_price)
            .join(OrderRecord, FillRecord.order_id == OrderRecord.order_id)
            .where(OrderRecord.strategy == strategy)
        ).fetchall()
    cash = float(STARTING_CAPITAL)
    for f in all_fills:
        if f.side == "buy":
            cash -= f.fill_price * f.quantity
        else:
            cash += f.fill_price * f.quantity
    total_value = cash + net_exposure

    # Weights (fraction of total portfolio)
    weights = (
        {sym: v / total_value for sym, v in market_values.items()}
        if total_value > 0 else {}
    )

    snapshot_data = {
        "strategy": strategy,
        "snapshot_date": as_of_date,
        "cash": round(cash, 2),
        "gross_exposure": round(gross_exposure, 2),
        "net_exposure": round(net_exposure, 2),
        "total_value": round(total_value, 2),
        "positions": {sym: qty for sym, qty in positions.items()},
        "recorded_at": datetime.utcnow(),
    }

    with get_session() as session:
        # Skip if snapshot already exists for this date — prevents duplicate rows on double-run
        existing = session.execute(
            select(PortfolioSnapshot).where(
                PortfolioSnapshot.strategy == strategy,
                PortfolioSnapshot.snapshot_date == as_of_date,
            )
        ).first()
        if existing:
            logger.info(f"[snapshot] Snapshot for {strategy} {as_of_date} already exists — skipping write.")
            return {**snapshot_data, "market_values": market_values, "weights": weights, "prices": prices}
        rec = PortfolioSnapshot(**snapshot_data)
        session.add(rec)
        session.commit()

    logger.info(
        f"[snapshot] {strategy} {as_of_date}: "
        f"total=${total_value:,.2f} | cash=${cash:,.2f} | "
        f"gross={gross_exposure/total_value:.1%} | "
        f"positions={list(positions.keys())}"
    )

    return {**snapshot_data, "market_values": market_values, "weights": weights, "prices": prices}
