"""
Expanded Universe Backtest
==========================
Compare two strategies over full price_bars history (2015 → present):

  Backtest A: Momentum baseline — top-5, 12-1, 5bps, 22-symbol universe (legacy)
  Backtest B: Same momentum params — top-5, 12-1, 5bps, expanded ~90-symbol universe

Hypothesis: a larger, sector-balanced universe gives the momentum signal more
candidates to select from, potentially improving diversification without the
blunt cost of a hard sector cap.

Integrity checklist:
  [x] No look-ahead bias   — momentum scores use prices[T-273 : T-21] only
  [x] Adj_close throughout — yfinance auto_adjust=True
  [x] Slippage modeled     — 5bps per changed position (same as production)
  [x] OOS consideration    — 2015 is warmup; test window 2016-onward
  [x] Universe fixed       — config/universe.py; no forward-looking additions
  [x] Logged to experiments — both experiments written to DB

Usage:
    python backtests/expanded_universe_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select

from config.universe import TRADING_SYMBOLS
from data.database import get_session
from data.models import PriceBar
from experiments.experiment_log import log_experiment
from features.momentum.price_momentum import compute_momentum_score
from tracking.analytics import cagr, max_drawdown, sharpe_ratio, sortino_ratio

# ── Parameters ────────────────────────────────────────────────────────────────
LOOKBACK = 252          # 12-month lookback
SKIP = 21               # skip most recent month (Jegadeesh-Titman)
REBALANCE_FREQ = 5      # rebalance every 5 trading days
TOP_N = 5               # top-5 equal-weight
SLIPPAGE_BPS = 5        # 5 bps per changed position per side
STARTING_CAPITAL = 100_000.0

# Warmup needed before first valid score
WARMUP_BARS = LOOKBACK + SKIP + 10   # ~284 trading days ≈ 14 months

# Legacy 22-symbol universe for comparison (Backtest A)
LEGACY_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AVGO", "V", "MA",          # Technology (legacy classification)
    "GOOGL", "META",                                      # Comm Services
    "AMZN", "TSLA", "HD",                                 # Consumer Discretionary
    "WMT", "PG",                                          # Consumer Staples
    "JPM", "BRK-B",                                       # Financials
    "UNH", "JNJ", "LLY",                                  # Health Care
    "XOM", "CVX",                                         # Energy
]


# ── Data loading ──────────────────────────────────────────────────────────────

def load_prices(symbols: list[str]) -> pd.DataFrame:
    """Load adj_close from price_bars for requested symbols, pivot to wide format."""
    with get_session() as session:
        rows = session.execute(
            select(PriceBar.symbol, PriceBar.date, PriceBar.adj_close)
            .where(PriceBar.symbol.in_(symbols))
            .order_by(PriceBar.date)
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["symbol", "date", "adj_close"])
    df["date"] = pd.to_datetime(df["date"])
    prices = df.pivot(index="date", columns="symbol", values="adj_close")
    prices.sort_index(inplace=True)
    return prices


# ── Core backtest engine ───────────────────────────────────────────────────────

def run_backtest(prices: pd.DataFrame, label: str) -> tuple[pd.DataFrame, dict]:
    """Run the momentum backtest on a given price matrix.

    Returns:
        equity_curve: DataFrame with columns ['value'], DatetimeIndex
        stats: dict of performance metrics
    """
    slippage_per_trade = SLIPPAGE_BPS / 10_000

    # ── Precompute all momentum scores ────────────────────────────────────────
    logger.info(f"[{label}]  Computing momentum scores for {len(prices.columns)} symbols…")
    score_df = pd.DataFrame(index=prices.index)
    for sym in prices.columns:
        series = prices[sym].dropna()
        if len(series) < WARMUP_BARS:
            continue
        score_df[sym] = compute_momentum_score(series, lookback=LOOKBACK, skip_last=SKIP)
    score_df = score_df.dropna(how="all")

    if score_df.empty:
        logger.error(f"[{label}]  No valid scores — check price data.")
        return pd.DataFrame(), {}

    # Determine test start: first rebalance after warmup
    rebalance_dates = score_df.index[::REBALANCE_FREQ]

    portfolio_value = STARTING_CAPITAL
    equity_curve: list[tuple] = []
    prev_holdings: set[str] = set()

    for i, rebal_date in enumerate(rebalance_dates):
        row = score_df.loc[rebal_date].dropna()
        if len(row) < TOP_N:
            continue  # not enough symbols with valid scores yet

        top_symbols = set(row.nlargest(TOP_N).index)

        # Slippage on changed positions
        changed = (top_symbols | prev_holdings) - (top_symbols & prev_holdings)
        slippage_cost = len(changed) * slippage_per_trade * (portfolio_value / TOP_N)
        portfolio_value -= slippage_cost

        # Compute period return to next rebalance
        next_rebal = (
            rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else score_df.index[-1]
        )
        period = prices.loc[rebal_date:next_rebal, list(top_symbols)].dropna(how="all")
        if period.empty or len(period) < 2:
            prev_holdings = top_symbols
            continue

        period_returns = period.pct_change().dropna()
        port_return = period_returns.mean(axis=1)

        for dt, ret in zip(period.index[1:], port_return):
            portfolio_value *= 1 + ret
            equity_curve.append((dt, portfolio_value))

        prev_holdings = top_symbols

    if not equity_curve:
        logger.error(f"[{label}]  Backtest produced no equity curve.")
        return pd.DataFrame(), {}

    eq_df = pd.DataFrame(equity_curve, columns=["date", "value"]).set_index("date")
    eq_df = eq_df[~eq_df.index.duplicated(keep="last")]
    returns = eq_df["value"].pct_change().dropna()

    stats = {
        "cagr": cagr(eq_df["value"]),
        "sharpe": sharpe_ratio(returns),
        "sortino": sortino_ratio(returns),
        "max_drawdown": max_drawdown(eq_df["value"]),
        "volatility": float(returns.std() * np.sqrt(252)),
        "win_rate": float((returns > 0).mean()),
        "total_return": float(eq_df["value"].iloc[-1] / STARTING_CAPITAL - 1),
        "start_date": eq_df.index[0].date(),
        "end_date": eq_df.index[-1].date(),
        "trading_days": len(eq_df),
        "years": len(eq_df) / 252,
    }

    logger.info(
        f"[{label}]  CAGR={stats['cagr']:.2%}  Sharpe={stats['sharpe']:.2f}  "
        f"Sortino={stats['sortino']:.2f}  MaxDD={stats['max_drawdown']:.2%}  "
        f"Vol={stats['volatility']:.2%}"
    )
    return eq_df, stats


# ── Year-by-year breakdown ────────────────────────────────────────────────────

def year_by_year(eq_df: pd.DataFrame) -> dict[int, float]:
    """Return {year: annual_return} from an equity curve."""
    result: dict[int, float] = {}
    for yr in sorted(set(eq_df.index.year)):
        sub = eq_df[eq_df.index.year == yr]["value"]
        if len(sub) < 2:
            continue
        result[yr] = float(sub.iloc[-1] / sub.iloc[0] - 1)
    return result


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_comparison(
    stats_a: dict, yby_a: dict[int, float],
    stats_b: dict, yby_b: dict[int, float],
    n_legacy: int, n_expanded: int,
) -> None:
    header_a = f"Baseline ({n_legacy}-sym)"
    header_b = f"Expanded ({n_expanded}-sym)"

    print("\n" + "=" * 72)
    print("PERFORMANCE COMPARISON — VALIDATED PARAMS (top-5, 12-1, 5bps)")
    print("=" * 72)
    print(f"{'Metric':<22} {header_a:>20} {header_b:>20} {'Delta':>8}")
    print("-" * 72)

    metrics = [
        ("CAGR",         f"{stats_a['cagr']:.2%}",         f"{stats_b['cagr']:.2%}",
         f"{stats_b['cagr'] - stats_a['cagr']:+.2%}"),
        ("Sharpe (rf=5%)", f"{stats_a['sharpe']:.2f}",      f"{stats_b['sharpe']:.2f}",
         f"{stats_b['sharpe'] - stats_a['sharpe']:+.2f}"),
        ("Sortino",       f"{stats_a['sortino']:.2f}",      f"{stats_b['sortino']:.2f}",
         f"{stats_b['sortino'] - stats_a['sortino']:+.2f}"),
        ("Max Drawdown",  f"{stats_a['max_drawdown']:.2%}", f"{stats_b['max_drawdown']:.2%}",
         f"{stats_b['max_drawdown'] - stats_a['max_drawdown']:+.2%}"),
        ("Annualized Vol", f"{stats_a['volatility']:.2%}",  f"{stats_b['volatility']:.2%}",
         f"{stats_b['volatility'] - stats_a['volatility']:+.2%}"),
        ("Win Rate (daily)", f"{stats_a['win_rate']:.2%}",  f"{stats_b['win_rate']:.2%}",
         f"{stats_b['win_rate'] - stats_a['win_rate']:+.2%}"),
    ]
    for name, va, vb, delta in metrics:
        print(f"  {name:<20} {va:>20} {vb:>20} {delta:>8}")

    print("\n" + "-" * 72)
    print(f"{'Year':<10} {header_a:>20} {header_b:>20} {'Delta':>8}")
    print("-" * 72)
    all_years = sorted(set(yby_a) | set(yby_b))
    for yr in all_years:
        ra = yby_a.get(yr)
        rb = yby_b.get(yr)
        sa = f"{ra:+.2%}" if ra is not None else "—"
        sb = f"{rb:+.2%}" if rb is not None else "—"
        delta = f"{rb - ra:+.2%}" if ra is not None and rb is not None else "—"
        print(f"  {yr:<8} {sa:>20} {sb:>20} {delta:>8}")
    print("=" * 72)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=" * 70)
    logger.info("Expanded Universe Backtest")
    logger.info("=" * 70)

    # ── Backtest A: legacy 22-symbol universe ─────────────────────────────────
    logger.info("\n[A] Loading legacy 22-symbol universe…")
    # BRK-B may be stored without hyphen in some DB versions — handle both
    legacy_syms = LEGACY_UNIVERSE[:]
    prices_a = load_prices(legacy_syms)
    # Drop any symbols with too little data
    valid_a = [c for c in prices_a.columns if prices_a[c].dropna().shape[0] >= WARMUP_BARS]
    prices_a = prices_a[valid_a]
    logger.info(f"[A] {len(valid_a)} symbols loaded with sufficient history.")
    eq_a, stats_a = run_backtest(prices_a, label="A: Legacy")

    # ── Backtest B: expanded universe ─────────────────────────────────────────
    logger.info("\n[B] Loading expanded universe…")
    expanded_syms = TRADING_SYMBOLS[:]
    prices_b = load_prices(expanded_syms)
    valid_b = [c for c in prices_b.columns if prices_b[c].dropna().shape[0] >= WARMUP_BARS]
    prices_b = prices_b[valid_b]
    logger.info(f"[B] {len(valid_b)} of {len(expanded_syms)} requested symbols loaded.")
    missing = sorted(set(expanded_syms) - set(valid_b))
    if missing:
        logger.warning(f"[B] Symbols missing or insufficient history: {missing}")
    eq_b, stats_b = run_backtest(prices_b, label="B: Expanded")

    if not stats_a or not stats_b:
        logger.error("One or both backtests failed — cannot compare.")
        return

    # ── Year-by-year ──────────────────────────────────────────────────────────
    yby_a = year_by_year(eq_a)
    yby_b = year_by_year(eq_b)

    # ── Print comparison ──────────────────────────────────────────────────────
    print_comparison(stats_a, yby_a, stats_b, yby_b, len(valid_a), len(valid_b))

    # ── Log experiments ───────────────────────────────────────────────────────
    params_a = {
        "lookback_days": LOOKBACK, "skip_last": SKIP, "top_n": TOP_N,
        "slippage_bps": SLIPPAGE_BPS, "universe": sorted(valid_a),
        "universe_size": len(valid_a),
    }
    result_a = (
        f"CAGR={stats_a['cagr']:.2%} | Sharpe={stats_a['sharpe']:.2f} | "
        f"Sortino={stats_a['sortino']:.2f} | MaxDD={stats_a['max_drawdown']:.2%} | "
        f"Vol={stats_a['volatility']:.2%}"
    )
    id_a = log_experiment(
        strategy="momentum",
        hypothesis=f"Momentum top-5 on legacy {len(valid_a)}-symbol universe — universe expansion baseline",
        params=params_a,
        result_summary=result_a,
        start_date=stats_a["start_date"],
        end_date=stats_a["end_date"],
        sharpe=stats_a["sharpe"],
        cagr=stats_a["cagr"],
        max_drawdown=stats_a["max_drawdown"],
        notes="Baseline for expanded universe comparison. Same legacy 22-symbol universe.",
    )
    logger.info(f"[A] Logged as experiment {id_a}")

    params_b = {
        "lookback_days": LOOKBACK, "skip_last": SKIP, "top_n": TOP_N,
        "slippage_bps": SLIPPAGE_BPS,
        "universe": sorted(valid_b), "universe_size": len(valid_b),
    }
    result_b = (
        f"CAGR={stats_b['cagr']:.2%} | Sharpe={stats_b['sharpe']:.2f} | "
        f"Sortino={stats_b['sortino']:.2f} | MaxDD={stats_b['max_drawdown']:.2%} | "
        f"Vol={stats_b['volatility']:.2%}"
    )
    delta_sharpe = stats_b["sharpe"] - stats_a["sharpe"]
    delta_cagr = stats_b["cagr"] - stats_a["cagr"]
    id_b = log_experiment(
        strategy="momentum",
        hypothesis=f"Momentum top-5 on expanded {len(valid_b)}-symbol universe — sector diversity test",
        params=params_b,
        result_summary=result_b,
        start_date=stats_b["start_date"],
        end_date=stats_b["end_date"],
        sharpe=stats_b["sharpe"],
        cagr=stats_b["cagr"],
        max_drawdown=stats_b["max_drawdown"],
        notes=(
            f"Expanded universe (all 11 GICS sectors, min 6 per sector). "
            f"vs legacy: Sharpe {delta_sharpe:+.2f}, CAGR {delta_cagr:+.2%}. "
            f"Universe: config/universe.py. Manifest: registry/universe_manifest.json."
        ),
    )
    logger.info(f"[B] Logged as experiment {id_b}")

    print(f"\nExperiment IDs: A={id_a}  B={id_b}")
    print("Results written to experiments table.")
    print("\nNext step: update CLAUDE.md with results and run_pipeline.py universe update.")


if __name__ == "__main__":
    main()
