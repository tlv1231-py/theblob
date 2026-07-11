"""Sector diversification cap for portfolio construction.

LOGIC
-----
- Each symbol is assigned a GICS sector via a hardcoded map (22 universe symbols).
- When selecting top-N, enforce: at most 1 stock per sector.
- Selection algorithm (greedy, rank-order):
    1. Sort candidates by momentum score descending.
    2. Walk down the ranked list; add a symbol only if its sector has not
       yet been taken.
    3. Continue until N positions are filled or candidates are exhausted.
- Returns a SectorCapResult with selected slots, dropped slots, and a flag
  indicating whether the cap actually changed composition.

GICS SOURCE
-----------
Standard GICS classifications as of 2026. Hardcoded for the 22-symbol universe.
SPY and QQQ are excluded from sector assignment (they are index ETFs, not
individual equities, and are typically not in the signal universe).
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from data.schemas.sector import SectorAllocation, SectorCapResult

# ── GICS sector map for the 22-symbol universe ────────────────────────────────
SECTOR_MAP: dict[str, str] = {
    # Technology
    "AAPL":  "Technology",
    "MSFT":  "Technology",
    "NVDA":  "Technology",
    "AVGO":  "Technology",
    "V":     "Technology",        # Visa — GICS classifies as IT (transaction processing)
    "MA":    "Technology",        # Mastercard — same GICS sub-industry as Visa

    # Communication Services
    "GOOGL": "Communication Services",
    "META":  "Communication Services",

    # Consumer Discretionary
    "AMZN":  "Consumer Discretionary",
    "TSLA":  "Consumer Discretionary",
    "HD":    "Consumer Discretionary",

    # Consumer Staples
    "WMT":   "Consumer Staples",
    "PG":    "Consumer Staples",

    # Financials
    "JPM":   "Financials",
    "BRK-B": "Financials",

    # Health Care
    "UNH":   "Health Care",
    "JNJ":   "Health Care",
    "LLY":   "Health Care",

    # Energy
    "XOM":   "Energy",
    "CVX":   "Energy",

    # Index ETFs — not assigned to a GICS sector; excluded from sector cap logic
    "SPY":   "ETF",
    "QQQ":   "ETF",
}


def get_sector(symbol: str) -> str | None:
    """Return the GICS sector for a symbol, or None if unknown/ETF."""
    s = SECTOR_MAP.get(symbol)
    if s == "ETF":
        return None
    return s


def apply_sector_cap(
    scores: pd.Series,
    top_n: int,
    verbose: bool = False,
) -> SectorCapResult:
    """Select top-N symbols with at most one per GICS sector.

    Args:
        scores:  pd.Series of {symbol: momentum_score}, unsorted.
        top_n:   Number of positions to fill.
        verbose: If True, log selection decisions.

    Returns:
        SectorCapResult with selected and dropped allocations.
    """
    ranked = scores.sort_values(ascending=False)
    selected: list[SectorAllocation] = []
    dropped: list[SectorAllocation] = []
    sectors_used: set[str] = set()
    cap_applied = False

    for rank_idx, (sym, score) in enumerate(ranked.items(), start=1):
        sector = get_sector(sym)

        if sector is None:
            # ETF (SPY, QQQ) — skip entirely; not individual equity signals
            if verbose:
                logger.debug(f"  [{rank_idx}] {sym} (ETF) → skipped")
            continue

        if sector in sectors_used:
            # Sector already taken — drop this symbol
            cap_applied = True
            dropped.append(SectorAllocation(
                symbol=sym, sector=sector, rank=rank_idx,
                score=float(score), displaced=False,
            ))
            if verbose:
                logger.debug(
                    f"  [{rank_idx}] {sym} ({sector}) → DROPPED (sector already held)"
                )
        else:
            # Sector available — select if we still need slots
            if len(selected) < top_n:
                sectors_used.add(sector)
                selected.append(SectorAllocation(
                    symbol=sym, sector=sector, rank=rank_idx,
                    score=float(score), displaced=(rank_idx > top_n),
                ))
                if verbose:
                    tag = " [promoted]" if rank_idx > top_n else ""
                    logger.debug(
                        f"  [{rank_idx}] {sym} ({sector}) → selected{tag}"
                    )
            else:
                # Portfolio full
                break

        if len(selected) == top_n:
            break

    result = SectorCapResult(
        selected=selected,
        dropped=dropped,
        cap_applied=cap_applied,
    )
    return result


def sector_cap_symbols(scores: pd.Series, top_n: int) -> list[str]:
    """Convenience wrapper — returns just the list of selected symbols."""
    result = apply_sector_cap(scores, top_n)
    return [a.symbol for a in result.selected]
