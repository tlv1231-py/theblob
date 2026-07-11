"""Main entry point: ingest → signal → risk → paper execute → snapshot → PnL → report.

Run daily after market close. Phase 3: Paper Trading.
"""
from datetime import date

from loguru import logger

from ingestion.calendar import is_trading_day, previous_trading_day
from ingestion.market_data.yfinance_fetcher import fetch_and_store
from config.universe import UNIVERSE as _UNIVERSE_MAP
# Full 94-symbol universe + benchmarks (SPY/QQQ not in tradeable universe but needed for comparisons)
DEFAULT_UNIVERSE = list(_UNIVERSE_MAP.keys()) + ["SPY", "QQQ", "IEF"]
from risk.risk_engine import RiskEngine, RiskVeto
from signals.momentum_signals import MomentumSignalGenerator
from execution.paper_executor import PaperExecutor
from portfolio.snapshot import write_snapshot
from tracking.pnl import compute_and_store_daily_pnl
from tracking.report import write_report
from tracking.alerts import alert_signal, alert_fill, alert_risk_veto, alert_system

STRATEGY = "momentum"
STARTING_CAPITAL = 100_000.0


def run(as_of_date: date | None = None) -> None:
    as_of_date = as_of_date or date.today()

    if not is_trading_day(as_of_date):
        as_of_date = previous_trading_day(as_of_date)
        logger.info(f"Not a trading day. Using {as_of_date}.")

    logger.info(f"=== Pipeline run for {as_of_date} ===")
    alert_system(f"Pipeline starting for {as_of_date}")

    # ── 1. Ingest ─────────────────────────────────────────────────────────────
    logger.info("Step 1: Ingesting market data...")
    results = fetch_and_store(symbols=DEFAULT_UNIVERSE, end=as_of_date)
    total_bars = sum(results.values())
    logger.info(f"Ingested {total_bars} new bars across {len(results)} symbols.")

    # ── 2. Load prices (used for execution sizing and snapshot) ───────────────
    from sqlalchemy import select, func
    from data.database import get_session
    from data.models import PriceBar

    with get_session() as session:
        latest_subq = (
            select(PriceBar.symbol, func.max(PriceBar.date).label("max_date"))
            .where(PriceBar.date <= as_of_date)
            .group_by(PriceBar.symbol)
            .subquery()
        )
        price_rows = session.execute(
            select(PriceBar.symbol, PriceBar.adj_close)
            .join(
                latest_subq,
                (PriceBar.symbol == latest_subq.c.symbol)
                & (PriceBar.date == latest_subq.c.max_date),
            )
        ).fetchall()
    prices = {row.symbol: row.adj_close for row in price_rows}
    logger.debug(f"Loaded prices for {len(prices)} symbols.")

    # ── 3. Generate signals ───────────────────────────────────────────────────
    logger.info("Step 2: Generating signals (params from momentum.yaml)...")
    gen = MomentumSignalGenerator()   # reads top_n from config/strategy_params/momentum.yaml
    signals = gen.generate(as_of_date)
    logger.info(f"Generated {len(signals)} signals (top_n={gen.top_n}).")

    if not signals:
        logger.info("No signals today — running snapshot and PnL only.")
    else:
        # ── 4. Rebalance: sell exits, buy entries ─────────────────────────────
        logger.info("Step 3: Rebalancing portfolio...")
        risk = RiskEngine(portfolio_value=STARTING_CAPITAL)
        executor = PaperExecutor(portfolio_value=STARTING_CAPITAL)

        # Current holdings and today's target symbols
        current_positions = executor.broker.get_all_positions()
        target_symbols = {s.symbol for s in signals}

        logger.info(
            f"Current positions: {list(current_positions.keys())} | "
            f"Target: {list(target_symbols)}"
        )

        # Step 1 — Sell positions that are no longer in the top-N
        exits = {sym: qty for sym, qty in current_positions.items()
                 if sym not in target_symbols}
        if exits:
            logger.info(f"Exiting {len(exits)} position(s): {list(exits.keys())}")
        for symbol, qty in exits.items():
            price = prices.get(symbol)
            if price is None:
                logger.warning(f"[{symbol}] No exit price available — skipping sell.")
                continue
            fill = executor.execute_sell(symbol, qty, price, STRATEGY)
            if fill:
                alert_fill(fill)

        # Step 2 — Buy positions that are new to the top-N
        entries = [s for s in signals if s.symbol not in current_positions]
        if entries:
            logger.info(f"Entering {len(entries)} new position(s): "
                        f"{[s.symbol for s in entries]}")
        for signal in entries:
            alert_signal(signal)
            price = prices.get(signal.symbol)
            if price is None:
                logger.warning(f"[{signal.symbol}] No price available — skipping.")
                continue
            try:
                qty = risk.approve_signal(signal, price)
                fill = executor.execute_signal(signal, price, qty)
                if fill:
                    alert_fill(fill)
            except RiskVeto as e:
                logger.warning(f"[risk veto] {e}")
                alert_risk_veto(str(e))

        holds = target_symbols & set(current_positions.keys())
        if holds:
            logger.info(f"Holding unchanged: {list(holds)}")

    # ── 5. Portfolio snapshot (after all fills) ───────────────────────────────
    logger.info("Step 4: Writing portfolio snapshot...")
    snapshot = write_snapshot(strategy=STRATEGY, as_of_date=as_of_date)

    # ── 6. PnL tracking ──────────────────────────────────────────────────────
    logger.info("Step 5: Computing daily PnL...")
    pnl = compute_and_store_daily_pnl(
        strategy=STRATEGY,
        as_of_date=as_of_date,
        total_value=snapshot["total_value"],
    )

    # ── 7. Daily report ───────────────────────────────────────────────────────
    logger.info("Step 6: Generating daily report...")
    write_report(strategy=STRATEGY, as_of_date=as_of_date, snapshot=snapshot, pnl=pnl)

    alert_system(f"Pipeline complete for {as_of_date}. Portfolio=${snapshot['total_value']:,.2f}")
    logger.info(f"=== Pipeline complete ===")


if __name__ == "__main__":
    run()
