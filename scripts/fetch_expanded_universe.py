"""Fetch 10 years of OHLCV data for the full expanded trading universe.

Steps:
  1. Fetch all symbols in config/universe.py (equities + benchmark ETFs)
  2. Append to price_bars â€” append-only, no overwrites
  3. Validate minimum history per symbol
  4. Write registry/universe_manifest.json with symbol metadata
  5. Print coverage report

Usage:
    python scripts/fetch_expanded_universe.py

Safe to re-run â€” existing rows are skipped via on_conflict_do_nothing.
"""
import sys
import json
import traceback
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from sqlalchemy import text

from config.universe import ALL_SYMBOLS, UNIVERSE, BENCHMARK_ETFS, symbols_by_sector
from data.database import get_session
from ingestion.market_data.yfinance_fetcher import fetch_and_store

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
START_DATE = date(2015, 1, 1)
END_DATE = date.today()
MIN_YEARS = 8          # flag symbols with fewer years
WARN_YEARS = 6         # hard-warn if below this threshold
MANIFEST_PATH = Path(__file__).parent.parent / "registry" / "universe_manifest.json"

TRADING_DAYS_PER_YEAR = 252


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_symbol_stats() -> dict[str, dict]:
    """Query price_bars for per-symbol: min_date, max_date, row_count, avg_volume."""
    sql = text("""
        SELECT
            symbol,
            MIN(date)::text             AS min_date,
            MAX(date)::text             AS max_date,
            COUNT(*)                    AS bars,
            ROUND(AVG(volume)::numeric) AS avg_volume
        FROM price_bars
        GROUP BY symbol
        ORDER BY symbol
    """)
    stats: dict[str, dict] = {}
    with get_session() as session:
        rows = session.execute(sql).fetchall()
    for row in rows:
        stats[row.symbol] = {
            "min_date": row.min_date,
            "max_date": row.max_date,
            "bars": row.bars,
            "avg_volume": int(row.avg_volume) if row.avg_volume else 0,
        }
    return stats


def years_of_data(stats_row: dict) -> float:
    if not stats_row:
        return 0.0
    return stats_row["bars"] / TRADING_DAYS_PER_YEAR


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main() -> None:
    logger.info("=" * 70)
    logger.info("The Blob Universe Expansion â€” Fetch & Validate")
    logger.info(f"Target: {len(ALL_SYMBOLS)} symbols  |  {START_DATE} â†’ {END_DATE}")
    logger.info("=" * 70)

    # â”€â”€ Pre-fetch stats (to calculate new bars per symbol) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    pre_stats = get_symbol_stats()

    # â”€â”€ Fetch all symbols â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info(f"\nFetching {len(ALL_SYMBOLS)} symbols from yfinanceâ€¦")
    fetch_results: dict[str, int] = {}
    failed: list[str] = []

    for sym in sorted(ALL_SYMBOLS):
        try:
            result = fetch_and_store(
                symbols=[sym],
                start=START_DATE,
                end=END_DATE,
            )
            inserted = result.get(sym, 0)
            fetch_results[sym] = inserted
            status = f"+{inserted:,} new bars" if inserted > 0 else "already current"
            logger.info(f"  {sym:<8}  {status}")
        except Exception as exc:
            logger.error(f"  {sym:<8}  FAILED: {exc}")
            failed.append(sym)
            fetch_results[sym] = 0

    # â”€â”€ Post-fetch stats â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    post_stats = get_symbol_stats()

    total_new_bars = sum(fetch_results.values())
    total_bars = sum(s["bars"] for s in post_stats.values())

    logger.info("\n" + "=" * 70)
    logger.info("FETCH SUMMARY")
    logger.info("=" * 70)
    logger.info(f"  Symbols attempted : {len(ALL_SYMBOLS)}")
    logger.info(f"  Symbols failed    : {len(failed)}  {failed if failed else ''}")
    logger.info(f"  New bars inserted : {total_new_bars:,}")
    logger.info(f"  Total bars in DB  : {total_bars:,}")

    # â”€â”€ Validate history length â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("\n" + "=" * 70)
    logger.info("HISTORY VALIDATION")
    logger.info("=" * 70)

    short_history: list[tuple[str, float]] = []
    critical_history: list[tuple[str, float]] = []

    for sym in UNIVERSE:
        stats = post_stats.get(sym)
        yrs = years_of_data(stats) if stats else 0.0
        if yrs < WARN_YEARS:
            critical_history.append((sym, yrs))
        elif yrs < MIN_YEARS:
            short_history.append((sym, yrs))

    if critical_history:
        logger.warning(f"  â›” < {WARN_YEARS} years of data (may be too new for strategy):")
        for sym, yrs in critical_history:
            logger.warning(f"     {sym:<8}  {yrs:.1f} yrs")
    if short_history:
        logger.warning(f"  âš  {WARN_YEARS}-{MIN_YEARS} years of data (flagged, but usable):")
        for sym, yrs in short_history:
            logger.warning(f"     {sym:<8}  {yrs:.1f} yrs")
    if not critical_history and not short_history:
        logger.info(f"  âœ“ All trading symbols have â‰¥{MIN_YEARS} years of data.")

    # â”€â”€ Sector coverage check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("\n" + "=" * 70)
    logger.info("SECTOR COVERAGE (minimum 6 per sector required)")
    logger.info("=" * 70)

    by_sector = symbols_by_sector()
    all_ok = True
    for sector, syms in by_sector.items():
        loaded = [s for s in syms if s in post_stats]
        count = len(loaded)
        ok = "âœ“" if count >= 6 else "â›”"
        if count < 6:
            all_ok = False
        logger.info(f"  {ok}  {sector:<30}  {count:>2} symbols  {loaded}")
    if all_ok:
        logger.info("\n  âœ“ All sectors meet minimum coverage requirement.")

    # â”€â”€ Build universe manifest â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    manifest: dict = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "universe_size": len(UNIVERSE),
        "etf_benchmarks": BENCHMARK_ETFS,
        "fetch_start": str(START_DATE),
        "fetch_end": str(END_DATE),
        "failed_symbols": failed,
        "symbols": {},
    }

    for sym, sector in UNIVERSE.items():
        stats = post_stats.get(sym, {})
        yrs = years_of_data(stats) if stats else 0.0
        manifest["symbols"][sym] = {
            "sector": sector,
            "min_date": stats.get("min_date"),
            "max_date": stats.get("max_date"),
            "bars": stats.get("bars", 0),
            "years_of_data": round(yrs, 1),
            "avg_daily_volume": stats.get("avg_volume", 0),
            "status": (
                "ok" if yrs >= MIN_YEARS
                else "short_history" if yrs >= WARN_YEARS
                else "critical" if yrs > 0
                else "missing"
            ),
        }

    # Add benchmark ETFs to manifest (separate section)
    manifest["benchmarks"] = {}
    for sym in BENCHMARK_ETFS:
        stats = post_stats.get(sym, {})
        manifest["benchmarks"][sym] = {
            "min_date": stats.get("min_date"),
            "max_date": stats.get("max_date"),
            "bars": stats.get("bars", 0),
        }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"\n  âœ“ Manifest written â†’ {MANIFEST_PATH}")

    # â”€â”€ Final summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("\n" + "=" * 70)
    logger.info("DONE")
    logger.info("=" * 70)
    logger.info(f"  Trading universe : {len(UNIVERSE)} symbols across {len(by_sector)} sectors")
    logger.info(f"  Benchmark ETFs   : {BENCHMARK_ETFS}")
    logger.info(f"  Total price_bars : {total_bars:,} rows")
    logger.info(
        "\nNext step: python backtests/expanded_universe_backtest.py"
    )


if __name__ == "__main__":
    main()

