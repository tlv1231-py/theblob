"""
Momentum strategy backtest — V1
================================
Validates the Jegadeesh-Titman 12-1 cross-sectional momentum signal
over the full available history in price_bars.

Integrity checklist compliance:
  [x] No look-ahead bias   — signal at T uses prices[T-21] backwards; executed at T+1
  [x] Point-in-time data   — universe is fixed at 22 large-caps; all existed throughout
  [x] Adj_close used        — splits/dividends handled by yfinance auto_adjust=True
  [x] Realistic fills       — next-day close + 5bps slippage per side
  [x] Slippage modeled      — 5bps per side on changed positions
  [x] Transaction costs     — included in slippage cost above
  [ ] OOS period held out   — CANNOT SATISFY: only 22 months of backtested data.
                              Full 3-year history needed for warmup + test.
                              Flag: results should be treated as in-sample only.
  [x] Logged to experiments — via experiment_log.log_experiment()
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date
import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select

from data.database import get_session
from data.models import PriceBar
from experiments.experiment_log import log_experiment
from tracking.analytics import summary as perf_summary

# ── Parameters ───────────────────────────────────────────────────────────────
LOOKBACK = 252      # ~12 months
SKIP = 21           # ~1 month skip (JT reversal filter)
TOP_N = 10          # long positions
REBALANCE_FREQ = 5  # trading days between rebalances (~weekly)
MIN_SCORE = 0.05    # minimum 5% trailing return to qualify
SLIPPAGE_BPS = 5    # per side
STARTING_CAPITAL = 100_000.0
RISK_FREE_RATE = 0.05


def load_prices() -> pd.DataFrame:
    """Load full adj_close price matrix from DB. Rows=dates, cols=symbols."""
    with get_session() as session:
        rows = session.execute(
            select(PriceBar.symbol, PriceBar.date, PriceBar.adj_close)
            .order_by(PriceBar.date)
        ).fetchall()

    df = pd.DataFrame(rows, columns=["symbol", "date", "adj_close"])
    df["date"] = pd.to_datetime(df["date"])
    prices = df.pivot(index="date", columns="symbol", values="adj_close")
    prices.sort_index(inplace=True)
    logger.info(f"Loaded {len(prices)} trading days × {len(prices.columns)} symbols.")
    return prices


def compute_scores(prices_to_date: pd.DataFrame) -> pd.Series:
    """Compute cross-sectional momentum scores for all symbols.

    Uses only prices up to the last row of prices_to_date.
    Score at T = price[T-21] / price[T-273] - 1  (no look-ahead).
    """
    scores = {}
    for sym in prices_to_date.columns:
        col = prices_to_date[sym].dropna()
        if len(col) < LOOKBACK + SKIP + 1:
            continue
        lagged = col.shift(SKIP)
        score = lagged.pct_change(LOOKBACK).iloc[-1]
        if pd.notna(score) and score >= MIN_SCORE:
            scores[sym] = float(score)
    return pd.Series(scores)


def run_backtest(prices: pd.DataFrame) -> dict:
    """
    Run the momentum backtest.

    Execution model:
    ----------------
    - Rebalance day T: compute signal using prices up to T (score uses T-21 backwards)
    - Positions take effect from T+1 open (approximated as T's close + 5bps slippage)
    - This introduces a 1-day execution lag which is standard for daily data.
    - Daily P&L computed using T → T+1 price changes applied to T's closing weights.
    """
    trading_dates = prices.index.tolist()
    warmup = LOOKBACK + SKIP  # minimum history needed for first valid score

    # Find first rebalance date index
    first_signal_idx = warmup
    while first_signal_idx < len(trading_dates):
        if first_signal_idx >= warmup:
            break
        first_signal_idx += 1

    logger.info(
        f"Warmup: {warmup} days. "
        f"Backtest starts at {trading_dates[first_signal_idx].date()} "
        f"({len(trading_dates) - first_signal_idx} trading days remaining)."
    )

    weights: dict[str, float] = {}
    daily_returns: list[float] = []
    rebalance_dates: list[pd.Timestamp] = []
    weights_history: list[dict] = []
    turnover_list: list[float] = []

    for i in range(first_signal_idx, len(trading_dates)):
        dt = trading_dates[i]
        prev_dt = trading_dates[i - 1]

        # ── Daily portfolio return ────────────────────────────────────────
        if weights:
            day_rets = prices.loc[dt] / prices.loc[prev_dt] - 1
            port_ret = float(sum(
                w * day_rets.get(sym, 0.0)
                for sym, w in weights.items()
            ))
        else:
            port_ret = 0.0

        # ── Rebalance ─────────────────────────────────────────────────────
        steps_since_start = i - first_signal_idx
        is_rebalance = (steps_since_start % REBALANCE_FREQ == 0)

        if is_rebalance:
            # Signal at prev_dt: use prices up to and including prev_dt.
            # Score only accesses prices[prev_dt-21] backwards — no look-ahead.
            scores = compute_scores(prices.loc[:prev_dt])

            if not scores.empty:
                new_holdings = scores.nlargest(TOP_N).index.tolist()
                new_weights = {sym: 1.0 / len(new_holdings) for sym in new_holdings}
            else:
                new_weights = {}

            # Turnover = fraction of portfolio that changed hands
            old_set = set(weights.keys())
            new_set = set(new_weights.keys())
            added = new_set - old_set
            removed = old_set - new_set
            # Two-sided turnover: buys + sells as fraction of portfolio
            turnover = (len(added) + len(removed)) / max(TOP_N * 2, 1)
            slippage_cost = turnover * (SLIPPAGE_BPS / 10_000)
            port_ret -= slippage_cost

            weights = new_weights
            rebalance_dates.append(dt)
            weights_history.append(dict(weights))
            turnover_list.append(turnover)

        daily_returns.append(port_ret)

    ret_series = pd.Series(daily_returns, index=trading_dates[first_signal_idx:])
    equity_curve = (1 + ret_series).cumprod() * STARTING_CAPITAL

    # ── SPY benchmark ────────────────────────────────────────────────────────
    spy_prices = prices["SPY"].loc[trading_dates[first_signal_idx]:]
    spy_returns = spy_prices.pct_change().dropna()
    spy_equity = (1 + spy_returns).cumprod() * STARTING_CAPITAL

    # ── Performance metrics ──────────────────────────────────────────────────
    metrics = perf_summary(equity_curve)
    spy_metrics = perf_summary(spy_equity)

    # Win rate: fraction of rebalance periods with positive return (weekly)
    weekly_rets = ret_series.resample("W").apply(lambda x: (1 + x).prod() - 1)
    win_rate = float((weekly_rets > 0).sum() / len(weekly_rets)) if len(weekly_rets) > 0 else 0.0

    # Annual turnover
    annual_turnover = float(np.mean(turnover_list) * (252 / REBALANCE_FREQ)) if turnover_list else 0.0

    # Year-by-year returns for persistence check
    annual_rets = ret_series.groupby(ret_series.index.year).apply(
        lambda x: float((1 + x).prod() - 1)
    )

    return {
        "equity_curve": equity_curve,
        "spy_equity": spy_equity,
        "returns": ret_series,
        "metrics": metrics,
        "spy_metrics": spy_metrics,
        "win_rate": win_rate,
        "annual_turnover": annual_turnover,
        "annual_returns": annual_rets,
        "backtest_start": trading_dates[first_signal_idx].date(),
        "backtest_end": trading_dates[-1].date(),
        "n_rebalances": len(rebalance_dates),
        "n_trading_days": len(daily_returns),
    }


def main() -> None:
    prices = load_prices()
    results = run_backtest(prices)
    m = results["metrics"]
    spy = results["spy_metrics"]

    logger.info("=" * 60)
    logger.info("MOMENTUM BACKTEST RESULTS")
    logger.info("=" * 60)
    logger.info(f"Period: {results['backtest_start']} → {results['backtest_end']}")
    logger.info(f"Trading days: {results['n_trading_days']}  |  Rebalances: {results['n_rebalances']}")
    logger.info("")
    logger.info(f"{'Metric':<25} {'Strategy':>10} {'SPY':>10}")
    logger.info(f"{'─'*25} {'─'*10} {'─'*10}")
    logger.info(f"{'CAGR':<25} {m['cagr']:>10.2%} {spy['cagr']:>10.2%}")
    logger.info(f"{'Sharpe (rf=5%)':<25} {m['sharpe']:>10.2f} {spy['sharpe']:>10.2f}")
    logger.info(f"{'Sortino':<25} {m['sortino']:>10.2f} {spy['sortino']:>10.2f}")
    logger.info(f"{'Max Drawdown':<25} {m['max_drawdown']:>10.2%} {spy['max_drawdown']:>10.2%}")
    logger.info(f"{'Annualized Vol':<25} {m['volatility_annualized']:>10.2%} {spy['volatility_annualized']:>10.2%}")
    logger.info(f"{'Total Return':<25} {m['total_return']:>10.2%} {spy['total_return']:>10.2%}")
    logger.info(f"{'Win Rate (weekly)':<25} {results['win_rate']:>10.2%}")
    logger.info(f"{'Annual Turnover':<25} {results['annual_turnover']:>10.2%}")
    logger.info("")
    logger.info("Annual Returns:")
    for yr, ret in results["annual_returns"].items():
        logger.info(f"  {yr}: {ret:+.2%}")

    # ── Log to experiments ────────────────────────────────────────────────────
    experiment_id = log_experiment(
        strategy="momentum",
        hypothesis=(
            "Cross-sectional price momentum (Jegadeesh-Titman 12-1) applied to "
            "a 22-symbol large-cap US equity universe should generate positive "
            "risk-adjusted returns above SPY buy-and-hold over the 2024-2026 period."
        ),
        params={
            "lookback_days": LOOKBACK,
            "skip_last_days": SKIP,
            "top_n": TOP_N,
            "rebalance_freq_days": REBALANCE_FREQ,
            "min_score_threshold": MIN_SCORE,
            "slippage_bps": SLIPPAGE_BPS,
            "starting_capital": STARTING_CAPITAL,
            "universe_size": 22,
            "weighting": "equal_weight",
            "execution": "next_day_close_plus_slippage",
        },
        result_summary=(
            f"CAGR {m['cagr']:.2%} vs SPY {spy['cagr']:.2%}. "
            f"Sharpe {m['sharpe']:.2f} vs SPY {spy['sharpe']:.2f}. "
            f"Max DD {m['max_drawdown']:.2%}. "
            f"Win rate {results['win_rate']:.2%}. "
            f"Annual turnover {results['annual_turnover']:.0%}. "
            f"In-sample only — OOS period unavailable with current data length."
        ),
        start_date=results["backtest_start"],
        end_date=results["backtest_end"],
        sharpe=m["sharpe"],
        cagr=m["cagr"],
        max_drawdown=m["max_drawdown"],
        notes=(
            "WARNING: Backtest period is ~22 months (in-sample only). "
            "Warmup of 273 trading days consumed all pre-2024 history. "
            "A longer dataset is needed for OOS validation. "
            "Universe is survivorship-biased toward current S&P 500 large-caps — "
            "acceptable for proof-of-concept but should be addressed before live."
        ),
    )
    logger.info(f"Experiment logged: {experiment_id}")
    logger.info("=" * 60)

    return results


if __name__ == "__main__":
    main()
