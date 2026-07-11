"""yfinance market data fetcher. Append-only — never overwrites existing rows."""
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf
from loguru import logger
from sqlalchemy.dialects.postgresql import insert

from data.database import get_session
from data.models import PriceBar
from ingestion.validators import validate_ohlcv, check_date_gaps

# Symbols to ingest by default (SPY, QQQ + ~20 liquid equities)
DEFAULT_UNIVERSE = [
    "SPY", "QQQ",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "JNJ", "XOM", "LLY", "AVGO", "WMT", "MA", "PG",
    "HD", "CVX",
]


def fetch_and_store(
    symbols: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    run_date: date | None = None,
) -> dict[str, int]:
    """Fetch OHLCV from yfinance and upsert into price_bars.

    Returns dict of {symbol: rows_inserted}.
    """
    symbols = symbols or DEFAULT_UNIVERSE
    end = end or date.today()
    start = start or (end - timedelta(days=365 * 3))  # default: 3 years

    results: dict[str, int] = {}

    for symbol in symbols:
        try:
            rows = _fetch_symbol(symbol, start, end, run_date=run_date)
            results[symbol] = rows
        except Exception as exc:
            logger.error(f"[{symbol}] Ingestion failed: {exc}")
            results[symbol] = 0

    return results


def _fetch_symbol(symbol: str, start: date, end: date, run_date: date | None = None) -> int:
    logger.info(f"[{symbol}] Fetching {start} → {end}")
    ticker = yf.Ticker(symbol)
    # yfinance end date is exclusive — add one day so today's bar is included
    fetch_end = end + timedelta(days=1)
    raw = ticker.history(
        start=start.strftime("%Y-%m-%d"),
        end=fetch_end.strftime("%Y-%m-%d"),
        auto_adjust=True,
        actions=False,
    )

    if raw.empty:
        logger.warning(f"[{symbol}] No data returned from yfinance.")
        return 0

    # Normalize columns
    raw = raw.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    raw["adj_close"] = raw["close"]  # auto_adjust=True means close IS adjusted
    raw.index = pd.to_datetime(raw.index).normalize()

    raw = validate_ohlcv(raw, symbol)
    check_date_gaps(raw, symbol)

    rows = _upsert_bars(symbol, raw)
    logger.info(f"[{symbol}] Inserted/updated {rows} bars.")

    if run_date is not None and rows > 0:
        try:
            from data.pipeline_log import log_event
            log_event(run_date, "FETCH", f"{symbol} · {rows} bars stored", symbol=symbol)
        except Exception:
            pass

    return rows


def _upsert_bars(symbol: str, df: pd.DataFrame) -> int:
    records = [
        {
            "symbol": symbol,
            "date": idx.date(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "adj_close": float(row["adj_close"]),
            "volume": int(row["volume"]),
            "ingested_at": datetime.utcnow(),
        }
        for idx, row in df.iterrows()
    ]

    if not records:
        return 0

    with get_session() as session:
        stmt = insert(PriceBar).values(records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "date"])
        result = session.execute(stmt)
        session.commit()
        return result.rowcount
