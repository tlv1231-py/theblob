"""Daily paper portfolio report. Appends to paper_portfolio_log.md."""
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from config.risk_limits import MAX_DAILY_DRAWDOWN, MAX_TOTAL_DRAWDOWN
from tracking.pnl import load_pnl_history

_LOG_PATH = Path(__file__).parent.parent / "experiments" / "results" / "paper_portfolio_log.md"

STARTING_CAPITAL = 100_000.0


def generate_report(
    strategy: str,
    as_of_date: date,
    snapshot: dict,
    pnl: dict,
    rolling_sharpe: float,
) -> str:
    """Build the plain-text daily report string."""
    positions = snapshot.get("positions", {})
    market_values = snapshot.get("market_values", {})
    weights = snapshot.get("weights", {})
    prices = snapshot.get("prices", {})
    total_value = snapshot.get("total_value", STARTING_CAPITAL)
    cash = snapshot.get("cash", STARTING_CAPITAL)
    gross_exposure = snapshot.get("gross_exposure", 0.0)
    net_exposure = snapshot.get("net_exposure", 0.0)

    daily_pnl = pnl.get("daily_pnl", 0.0)
    cumulative_pnl = pnl.get("cumulative_pnl", 0.0)
    drawdown = pnl.get("drawdown", 0.0)
    peak_equity = pnl.get("peak_equity", STARTING_CAPITAL)

    # Risk limit breach checks
    breaches: list[str] = []
    if abs(drawdown) >= MAX_TOTAL_DRAWDOWN:
        breaches.append(f"TOTAL DRAWDOWN HALT: {drawdown:.2%} >= {MAX_TOTAL_DRAWDOWN:.0%} limit")
    if daily_pnl / STARTING_CAPITAL <= -MAX_DAILY_DRAWDOWN:
        breaches.append(
            f"DAILY LOSS LIMIT: {daily_pnl/STARTING_CAPITAL:.2%} >= {MAX_DAILY_DRAWDOWN:.0%} daily limit"
        )
    if total_value > 0 and gross_exposure / total_value > 1.0:
        breaches.append(f"GROSS EXPOSURE: {gross_exposure/total_value:.1%} > 100% limit")

    lines = [
        f"## {as_of_date} — {strategy.title()} Paper Portfolio",
        "",
        "### Portfolio Summary",
        f"  Total Value:       ${total_value:>12,.2f}",
        f"  Cash:              ${cash:>12,.2f}  ({cash/total_value:.1%} of portfolio)",
        f"  Gross Exposure:    ${gross_exposure:>12,.2f}  ({gross_exposure/total_value:.1%})" if total_value else "  Gross Exposure:    $0.00",
        f"  Net Exposure:      ${net_exposure:>12,.2f}  ({net_exposure/total_value:.1%})" if total_value else "  Net Exposure:      $0.00",
        "",
        "### Positions",
    ]

    if positions:
        lines.append(f"  {'Symbol':<8} {'Shares':>6} {'Price':>9} {'Mkt Value':>12} {'Weight':>7}")
        lines.append(f"  {'─'*8} {'─'*6} {'─'*9} {'─'*12} {'─'*7}")
        for sym in sorted(positions.keys(), key=lambda s: -market_values.get(s, 0)):
            qty = positions[sym]
            price = prices.get(sym, 0.0)
            mv = market_values.get(sym, 0.0)
            wt = weights.get(sym, 0.0)
            lines.append(f"  {sym:<8} {qty:>6} {price:>9.2f} {mv:>12,.2f} {wt:>6.1%}")
    else:
        lines.append("  (no open positions)")

    lines += [
        "",
        "### PnL",
        f"  Daily P&L:         ${daily_pnl:>+12,.2f}  ({daily_pnl/STARTING_CAPITAL:+.2%})",
        f"  Cumulative P&L:    ${cumulative_pnl:>+12,.2f}  ({cumulative_pnl/STARTING_CAPITAL:+.2%})",
        f"  Peak Equity:       ${peak_equity:>12,.2f}",
        f"  Drawdown vs Peak:  {drawdown:>+12.2%}",
        f"  Rolling Sharpe (63d): {rolling_sharpe:>8.2f}" if not (rolling_sharpe != rolling_sharpe) else "  Rolling Sharpe (63d):      n/a (< 5 days)",
        "",
        "### Risk",
    ]

    if breaches:
        for b in breaches:
            lines.append(f"  ⚠ BREACH: {b}")
    else:
        lines.append("  No risk limit breaches.")

    lines.append("")
    lines.append(f"  Reported: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def write_report(
    strategy: str,
    as_of_date: date,
    snapshot: dict,
    pnl: dict,
) -> None:
    """Generate report, log to console, append to paper_portfolio_log.md."""
    rolling_sharpe = pnl.get("rolling_sharpe_63d", float("nan"))
    report = generate_report(strategy, as_of_date, snapshot, pnl, rolling_sharpe)

    # Console output
    for line in report.split("\n"):
        logger.info(line)

    # Append to log file — create header if first entry
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _LOG_PATH.exists():
        header = (
            "# Paper Portfolio Daily Log\n\n"
            f"Strategy: {strategy} | Started: {as_of_date} | Capital: ${STARTING_CAPITAL:,.0f}\n\n"
            "---\n\n"
        )
        _LOG_PATH.write_text(header, encoding="utf-8")

    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(report)

    logger.info(f"[report] Appended to {_LOG_PATH}")
