"""Data quality checks run at ingestion. Data must pass before entering pipeline."""
import pandas as pd
from loguru import logger


def validate_ohlcv(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Validate a raw OHLCV DataFrame. Returns cleaned frame or raises."""
    initial_rows = len(df)

    # Required columns
    required = {"open", "high", "low", "close", "volume", "adj_close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"[{symbol}] Missing columns: {missing}")

    # Drop rows with null prices
    df = df.dropna(subset=list(required))
    dropped = initial_rows - len(df)
    if dropped:
        logger.warning(f"[{symbol}] Dropped {dropped} rows with null values.")

    # Sanity: high >= low, close > 0
    invalid_hl = df[df["high"] < df["low"]]
    if not invalid_hl.empty:
        logger.warning(f"[{symbol}] {len(invalid_hl)} bars with high < low — dropping.")
        df = df[df["high"] >= df["low"]]

    invalid_close = df[df["close"] <= 0]
    if not invalid_close.empty:
        logger.warning(f"[{symbol}] {len(invalid_close)} bars with close <= 0 — dropping.")
        df = df[df["close"] > 0]

    # Detect suspicious price gaps (>50% day-over-day — likely unadjusted split)
    df = df.sort_index()
    pct_change = df["adj_close"].pct_change().abs()
    large_gaps = df[pct_change > 0.5]
    if not large_gaps.empty:
        logger.warning(
            f"[{symbol}] {len(large_gaps)} suspicious price gaps (>50%) detected. "
            f"Dates: {list(large_gaps.index[:5])}. Verify split adjustment."
        )

    # Volume check
    zero_vol = df[df["volume"] == 0]
    if not zero_vol.empty:
        logger.warning(f"[{symbol}] {len(zero_vol)} bars with zero volume.")

    logger.debug(f"[{symbol}] Validation passed. {len(df)} bars retained.")
    return df


def check_date_gaps(df: pd.DataFrame, symbol: str, max_gap_days: int = 5) -> None:
    """Warn on trading-day gaps larger than max_gap_days."""
    if df.empty:
        return
    df = df.sort_index()
    diffs = pd.Series(df.index).diff().dt.days.dropna()
    big_gaps = diffs[diffs > max_gap_days]
    if not big_gaps.empty:
        logger.warning(
            f"[{symbol}] {len(big_gaps)} date gaps > {max_gap_days} days detected."
        )
