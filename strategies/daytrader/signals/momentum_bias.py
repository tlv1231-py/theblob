"""Cross-strategy momentum bias signal.

Reads The Blob momentum rankings from the signals table to give intraday
trades a directional bias. If a stock is in the top-N momentum rankings,
long ORB setups on that stock get a score bonus. This is the first
inter-strategy signal â€” the beginning of the ensemble layer.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from loguru import logger
from sqlalchemy import text

# Import dashboard DB session (works from both pipeline and dashboard contexts)
try:
    from data.database import get_session
except ImportError:
    from dashboard.db import get_session


_TOP_N_DEFAULT = 10


def get_momentum_universe(
    as_of: date | None = None,
    top_n: int = _TOP_N_DEFAULT,
) -> dict[str, float]:
    """Return a dict of {symbol: momentum_score} for the top-N momentum stocks.

    Looks back up to 5 trading days to find the most recent signal batch,
    so a weekend or holiday doesn't return empty results.

    Returns empty dict if no momentum signals exist yet.
    """
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=7)

    try:
        with get_session() as s:
            rows = s.execute(text("""
                SELECT DISTINCT ON (symbol)
                       symbol, score, as_of_date
                FROM signals
                WHERE strategy = 'momentum'
                  AND as_of_date::date >= :cutoff
                  AND as_of_date::date <= :as_of
                  AND direction = 'long'
                ORDER BY symbol, as_of_date DESC, score DESC
            """), {"cutoff": cutoff, "as_of": as_of}).fetchall()
    except Exception as e:
        logger.warning(f"[momentum_bias] DB query failed: {e}")
        return {}

    if not rows:
        return {}

    # Sort by score descending, take top_n
    ranked = sorted(rows, key=lambda r: float(r.score), reverse=True)[:top_n]
    return {r.symbol: float(r.score) for r in ranked}


def is_momentum_aligned(
    symbol: str,
    direction: str,
    as_of: date | None = None,
    top_n: int = _TOP_N_DEFAULT,
) -> bool:
    """Return True if this trade direction aligns with The Blob momentum signal.

    Long trades on top-N momentum stocks â†’ aligned.
    Short trades on bottom-N momentum stocks â†’ aligned (future: when short selling enabled).
    Everything else â†’ not aligned (neutral, not a veto).
    """
    universe = get_momentum_universe(as_of=as_of, top_n=top_n)

    if direction == "long" and symbol in universe:
        logger.debug(
            f"[momentum_bias] {symbol} in The Blob top-{top_n} "
            f"(score={universe[symbol]:.3f}) â†’ long aligned"
        )
        return True

    return False


def momentum_score_for(
    symbol: str,
    as_of: date | None = None,
    top_n: int = _TOP_N_DEFAULT,
) -> float | None:
    """Return the raw The Blob momentum score for a symbol, or None if not ranked."""
    universe = get_momentum_universe(as_of=as_of, top_n=top_n)
    return universe.get(symbol)

