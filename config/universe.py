"""Authoritative trading universe for the The Blob momentum strategy.

Single source of truth for:
  - Which symbols are in the trading universe
  - Each symbol's GICS sector
  - Which tickers are benchmark ETFs (excluded from signal generation)

DESIGN RULES
------------
- ETFs are never in UNIVERSE. They live in BENCHMARK_ETFS only.
- Minimum 6 symbols per GICS sector.
- All symbols must be: US-listed, large/mid-cap, liquid, 10+ years of history.
- GICS classifications as of 2026 (standard GICS, not MSCI custom sub-industries).
  Exception: Visa and Mastercard follow GICS standard (Financials / Payment Services)
  rather than the IT "data processing" sub-industry used in some legacy sector maps.

UPDATING THE UNIVERSE
---------------------
1. Add or remove symbols from UNIVERSE (with their sector string).
2. Run scripts/fetch_expanded_universe.py to ingest new data and update the manifest.
3. Re-run backtests to validate the change does not break edge.

Sectors present: Technology, Consumer Discretionary, Financials, Health Care,
Industrials, Energy, Consumer Staples, Materials, Real Estate, Utilities,
Communication Services  (all 11 GICS sectors).
"""
from __future__ import annotations

# â”€â”€ Trading universe (equities only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Symbol â†’ GICS sector string
UNIVERSE: dict[str, str] = {
    # â”€â”€ Technology (12 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "AAPL":  "Technology",
    "MSFT":  "Technology",
    "NVDA":  "Technology",
    "AVGO":  "Technology",
    "AMD":   "Technology",
    "ORCL":  "Technology",
    "CRM":   "Technology",
    "INTC":  "Technology",
    "QCOM":  "Technology",
    "TXN":   "Technology",

    # â”€â”€ Communication Services (11 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # GOOGL and META moved here per GICS 2023 reclassification
    "GOOGL": "Communication Services",
    "META":  "Communication Services",
    "NFLX":  "Communication Services",
    "DIS":   "Communication Services",
    "CMCSA": "Communication Services",
    "VZ":    "Communication Services",
    "T":     "Communication Services",
    "TMUS":  "Communication Services",

    # â”€â”€ Consumer Discretionary (10 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "AMZN":  "Consumer Discretionary",
    "TSLA":  "Consumer Discretionary",
    "HD":    "Consumer Discretionary",
    "MCD":   "Consumer Discretionary",
    "NKE":   "Consumer Discretionary",
    "SBUX":  "Consumer Discretionary",
    "TGT":   "Consumer Discretionary",
    "LOW":   "Consumer Discretionary",
    "BKNG":  "Consumer Discretionary",
    "GM":    "Consumer Discretionary",

    # â”€â”€ Consumer Staples (8 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "WMT":   "Consumer Staples",
    "PG":    "Consumer Staples",
    "KO":    "Consumer Staples",
    "PEP":   "Consumer Staples",
    "COST":  "Consumer Staples",
    "CL":    "Consumer Staples",
    "MDLZ":  "Consumer Staples",
    "GIS":   "Consumer Staples",

    # â”€â”€ Financials (12 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Visa and Mastercard: GICS Financials (Payment Services sub-industry)
    "JPM":   "Financials",
    "BAC":   "Financials",
    "WFC":   "Financials",
    "GS":    "Financials",
    "MS":    "Financials",
    "BLK":   "Financials",
    "AXP":   "Financials",
    "USB":   "Financials",
    "PNC":   "Financials",
    "SCHW":  "Financials",
    "V":     "Financials",
    "MA":    "Financials",

    # â”€â”€ Health Care (10 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "JNJ":   "Health Care",
    "UNH":   "Health Care",
    "LLY":   "Health Care",
    "ABBV":  "Health Care",
    "MRK":   "Health Care",
    "PFE":   "Health Care",
    "TMO":   "Health Care",
    "ABT":   "Health Care",
    "CVS":   "Health Care",
    "AMGN":  "Health Care",

    # â”€â”€ Industrials (10 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "CAT":   "Industrials",
    "HON":   "Industrials",
    "UPS":   "Industrials",
    "BA":    "Industrials",
    "LMT":   "Industrials",
    "GE":    "Industrials",
    "MMM":   "Industrials",
    "RTX":   "Industrials",
    "DE":    "Industrials",
    "FDX":   "Industrials",

    # â”€â”€ Energy (8 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "XOM":   "Energy",
    "CVX":   "Energy",
    "COP":   "Energy",
    "EOG":   "Energy",
    "SLB":   "Energy",
    "PSX":   "Energy",
    "VLO":   "Energy",
    "MPC":   "Energy",

    # â”€â”€ Materials (6 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "LIN":   "Materials",
    "APD":   "Materials",
    "ECL":   "Materials",
    "NEM":   "Materials",
    "FCX":   "Materials",
    "NUE":   "Materials",

    # â”€â”€ Real Estate (6 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "PLD":   "Real Estate",
    "AMT":   "Real Estate",
    "EQIX":  "Real Estate",
    "SPG":   "Real Estate",
    "O":     "Real Estate",
    "DLR":   "Real Estate",

    # â”€â”€ Utilities (6 symbols) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "NEE":   "Utilities",
    "DUK":   "Utilities",
    "SO":    "Utilities",
    "D":     "Utilities",
    "AEP":   "Utilities",
    "XEL":   "Utilities",
}

# â”€â”€ Benchmark ETFs (excluded from signal generation) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BENCHMARK_ETFS: list[str] = ["SPY", "QQQ", "IEF"]

# â”€â”€ Convenience accessors â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
TRADING_SYMBOLS: list[str] = sorted(UNIVERSE.keys())

ALL_SYMBOLS: list[str] = sorted(set(TRADING_SYMBOLS) | set(BENCHMARK_ETFS))


def get_sector(symbol: str) -> str | None:
    """Return GICS sector for a trading symbol, or None if not in universe."""
    return UNIVERSE.get(symbol)


def symbols_by_sector() -> dict[str, list[str]]:
    """Return {sector: [symbols]} mapping, sorted."""
    result: dict[str, list[str]] = {}
    for sym, sector in UNIVERSE.items():
        result.setdefault(sector, []).append(sym)
    return {k: sorted(v) for k, v in sorted(result.items())}


def sector_count() -> dict[str, int]:
    """Return {sector: count} for quick coverage check."""
    return {s: len(syms) for s, syms in symbols_by_sector().items()}

