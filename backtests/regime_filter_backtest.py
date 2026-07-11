"""
Regime Filter Backtest — V1
============================
Compare two strategies over full price_bars history (2015 → 2026):

  Backtest A: Momentum baseline — top-5, 12-1, 5bps, no regime filter
  Backtest B: Momentum + SPY 200-day MA regime filter
              → Long top-5 when regime = BULL
              → 100% cash when regime = BEAR

Integrity checklist:
  [x] No look-ahead bias   — regime at T uses SMA(prices[T-199:T]);
                              regime decision is applied on T+1 execution
  [x] Adj_close throughout — price_bars uses yfinance auto_adjust=True
  [x] Slippage modeled     — 5bps per changed position
  [x] Transaction costs    — embedded in slippage; regime switch also charged
  [x] OOS consideration    — 2015 is MA warmup; test window 2016-2026
  [x] Logged to experiments — both experiments written to DB

Cash drag accounting:
  - Bear regime days contribute 0% return (cash earns nothing, conservative)
  - Slippage charged on entries/exits triggered by regime switches
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select, text

from data.database import get_session
from data.models import PriceBar
from experiments.experiment_log import log_experiment
from features.market_regime.regime_filter import compute_regime
from tracking.analytics import summary as perf_summary

# ── Constants ─────────────────────────────────────────────────────────────────
LOOKBACK = 252
SKIP = 21
REBALANCE_FREQ = 5
MIN_SCORE = 0.05
TOP_N = 5
SLIPPAGE_BPS = 5
STARTING_CAPITAL = 100_000.0
RISK_FREE_RATE = 0.05


# ── Data loading ──────────────────────────────────────────────────────────────

def load_prices() -> pd.DataFrame:
    """Load all price_bars adj_close, pivoted to (date × symbol)."""
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


def load_regime_series(prices: pd.DataFrame) -> pd.Series:
    """Derive regime from SPY column in the already-loaded prices DataFrame.

    Using the in-memory prices avoids a second DB round trip and ensures
    the regime is computed over the exact same date range as the backtest.
    """
    spy = prices["SPY"].dropna()
    regime = compute_regime(spy, ma_window=200, validate=True)
    logger.info(
        f"Regime series: {len(regime)} days | "
        f"bull={( regime=='bull').sum()} | bear={(regime=='bear').sum()}"
    )
    return regime


# ── Momentum score ─────────────────────────────────────────────────────────────

def compute_scores(prices_to_date: pd.DataFrame) -> pd.Series:
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


# ── Core backtest engine ───────────────────────────────────────────────────────

def run_backtest(
    prices: pd.DataFrame,
    label: str,
    regime: pd.Series | None = None,
) -> dict:
    """Run one backtest pass.

    Args:
        prices:  Full price matrix (date × symbol).
        label:   Experiment label string.
        regime:  Optional pd.Series indexed by pd.Timestamp with 'bull'/'bear'.
                 If None → baseline (always invested).
    """
    trading_dates = prices.index.tolist()
    warmup = LOOKBACK + SKIP

    # Find first date where we have enough history AND (if filtered) regime is defined
    first_idx = warmup
    if regime is not None:
        # Advance start until regime is available too
        for idx in range(warmup, len(trading_dates)):
            if trading_dates[idx] in regime.index:
                first_idx = idx
                break

    logger.info(
        f"[{label}] Warmup: {warmup} days → backtest starts "
        f"{trading_dates[first_idx].date()} "
        f"({len(trading_dates) - first_idx} days in test window)."
    )

    weights: dict[str, float] = {}
    daily_returns: list[float] = []
    turnover_list: list[float] = []
    bear_days = 0
    regime_switches = 0
    prev_regime: str | None = None

    for i in range(first_idx, len(trading_dates)):
        dt = trading_dates[i]
        prev_dt = trading_dates[i - 1]

        # Determine today's regime (using previous day's regime for T+1 execution)
        if regime is not None and prev_dt in regime.index:
            today_regime = regime.loc[prev_dt]
        else:
            today_regime = "bull"  # default to invested if no regime data

        in_bear = (today_regime == "bear")
        if in_bear:
            bear_days += 1

        # Track regime switches for slippage accounting
        if prev_regime is not None and today_regime != prev_regime:
            regime_switches += 1
        prev_regime = today_regime

        # Daily portfolio return
        if weights and not in_bear:
            day_rets = prices.loc[dt] / prices.loc[prev_dt] - 1
            port_ret = float(sum(
                w * float(day_rets.get(sym, 0.0))
                for sym, w in weights.items()
            ))
        else:
            port_ret = 0.0  # in cash

        # Rebalance on schedule
        steps_since_start = i - first_idx
        if steps_since_start % REBALANCE_FREQ == 0:
            if in_bear:
                # Liquidate all positions — charge slippage on exits
                if weights:
                    slippage_cost = len(weights) * (SLIPPAGE_BPS / 10_000) / TOP_N
                    port_ret -= slippage_cost
                new_weights: dict[str, float] = {}
            else:
                scores = compute_scores(prices.loc[:prev_dt])
                if not scores.empty:
                    new_holdings = scores.nlargest(TOP_N).index.tolist()
                    new_weights = {sym: 1.0 / len(new_holdings) for sym in new_holdings}
                else:
                    new_weights = {}

                old_set = set(weights.keys())
                new_set = set(new_weights.keys())
                added = new_set - old_set
                removed = old_set - new_set
                turnover = (len(added) + len(removed)) / max(TOP_N * 2, 1)
                slippage_cost = turnover * (SLIPPAGE_BPS / 10_000)
                port_ret -= slippage_cost
                turnover_list.append(turnover)

            weights = new_weights

        daily_returns.append(port_ret)

    ret_series = pd.Series(daily_returns, index=trading_dates[first_idx:])
    equity_curve = (1 + ret_series).cumprod() * STARTING_CAPITAL

    # SPY benchmark over the same window
    spy_prices = prices["SPY"].loc[trading_dates[first_idx]:]
    spy_ret = spy_prices.pct_change().dropna()
    spy_equity = (1 + spy_ret).cumprod() * STARTING_CAPITAL

    metrics = perf_summary(equity_curve)
    spy_metrics = perf_summary(spy_equity)

    weekly_rets = ret_series.resample("W").apply(lambda x: (1 + x).prod() - 1)
    win_rate = float((weekly_rets > 0).sum() / len(weekly_rets)) if len(weekly_rets) > 0 else 0.0
    annual_turnover = float(np.mean(turnover_list) * (252 / REBALANCE_FREQ)) if turnover_list else 0.0

    annual_rets = ret_series.groupby(ret_series.index.year).apply(
        lambda x: float((1 + x).prod() - 1)
    )
    spy_annual = spy_ret.groupby(spy_ret.index.year).apply(
        lambda x: float((1 + x).prod() - 1)
    )

    n_test_days = len(daily_returns)
    cash_pct = bear_days / n_test_days if n_test_days else 0.0

    return {
        "equity_curve": equity_curve,
        "returns": ret_series,
        "metrics": metrics,
        "spy_metrics": spy_metrics,
        "win_rate": win_rate,
        "annual_turnover": annual_turnover,
        "annual_returns": annual_rets,
        "spy_annual": spy_annual,
        "backtest_start": trading_dates[first_idx].date(),
        "backtest_end": trading_dates[-1].date(),
        "n_rebalances": len(turnover_list),
        "n_trading_days": n_test_days,
        "bear_days": bear_days,
        "cash_pct": cash_pct,
        "regime_switches": regime_switches,
        "label": label,
    }


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_results(r: dict) -> None:
    m = r["metrics"]
    spy = r["spy_metrics"]
    label = r["label"]
    cash_pct = r.get("cash_pct", 0.0)

    logger.info(f"\n{'='*65}")
    logger.info(f"  {label.upper()}")
    logger.info(f"  Top-{TOP_N} | Slippage {SLIPPAGE_BPS}bps | "
                f"Period {r['backtest_start']} → {r['backtest_end']}")
    if cash_pct > 0:
        logger.info(f"  Cash (bear regime): {cash_pct:.1%} of time | "
                    f"Regime switches: {r['regime_switches']}")
    logger.info(f"{'='*65}")
    logger.info(f"{'Metric':<26} {'Strategy':>10} {'SPY':>10}")
    logger.info(f"{'─'*26} {'─'*10} {'─'*10}")
    logger.info(f"{'CAGR':<26} {m['cagr']:>10.2%} {spy['cagr']:>10.2%}")
    logger.info(f"{'Sharpe (rf=5%)':<26} {m['sharpe']:>10.2f} {spy['sharpe']:>10.2f}")
    logger.info(f"{'Sortino':<26} {m['sortino']:>10.2f} {spy['sortino']:>10.2f}")
    logger.info(f"{'Max Drawdown':<26} {m['max_drawdown']:>10.2%} {spy['max_drawdown']:>10.2%}")
    logger.info(f"{'Annualized Vol':<26} {m['volatility_annualized']:>10.2%} {spy['volatility_annualized']:>10.2%}")
    logger.info(f"{'Total Return':<26} {m['total_return']:>10.2%} {spy['total_return']:>10.2%}")
    logger.info(f"{'Win Rate (weekly)':<26} {r['win_rate']:>10.2%}")
    logger.info(f"{'Annual Turnover':<26} {r['annual_turnover']:>10.2%}")
    if cash_pct > 0:
        logger.info(f"{'% Time in Cash':<26} {cash_pct:>10.2%}")

    logger.info(f"\n  Year-by-Year Returns (Strategy vs SPY):")
    logger.info(f"  {'Year':<6} {'Strategy':>10} {'SPY':>10} {'vs SPY':>10}  Flag")
    logger.info(f"  {'─'*6} {'─'*10} {'─'*10} {'─'*10}  {'─'*20}")
    for yr in sorted(r["annual_returns"].index):
        strat = r["annual_returns"][yr]
        bench = r["spy_annual"].get(yr, float("nan"))
        diff = strat - bench if not np.isnan(bench) else float("nan")
        flag = ""
        if strat < -0.10:
            flag = "⚠ loss year"
        elif strat < -0.20:
            flag = "⚠ DD>20%"
        elif not np.isnan(diff) and diff < -0.10:
            flag = "⚠ underperform"
        logger.info(f"  {yr:<6} {strat:>10.2%} {bench:>10.2%} {diff:>+10.2%}  {flag}")


def log_to_db(r: dict, name: str, hypothesis: str, extra_notes: str = "") -> str:
    m = r["metrics"]
    spy = r["spy_metrics"]
    cash_pct = r.get("cash_pct", 0.0)

    experiment_id = log_experiment(
        strategy="momentum",
        hypothesis=hypothesis,
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
            "regime_filter": "SPY_200MA" if cash_pct > 0 else "none",
            "cash_in_bear": cash_pct > 0,
            "pct_time_in_cash": round(cash_pct, 4),
            "regime_switches": r.get("regime_switches", 0),
            "experiment_name": name,
        },
        result_summary=(
            f"CAGR {m['cagr']:.2%} vs SPY {spy['cagr']:.2%}. "
            f"Sharpe {m['sharpe']:.2f} vs SPY {spy['sharpe']:.2f}. "
            f"Sortino {m['sortino']:.2f}. "
            f"Max DD {m['max_drawdown']:.2%}. "
            f"Vol {m['volatility_annualized']:.2%}. "
            f"Win rate {r['win_rate']:.2%}. "
            f"Annual turnover {r['annual_turnover']:.0%}. "
            f"Time in cash: {cash_pct:.1%}."
        ),
        start_date=r["backtest_start"],
        end_date=r["backtest_end"],
        sharpe=m["sharpe"],
        cagr=m["cagr"],
        max_drawdown=m["max_drawdown"],
        notes=(
            f"Experiment: {name}. "
            f"Regime filter: {'SPY 200-day SMA' if cash_pct > 0 else 'none (baseline)'}. "
            f"Survivorship bias: universe fixed at current 22 large-caps. "
            + extra_notes
        ),
    )
    logger.info(f"[{name}] Logged as experiment {experiment_id}")
    return experiment_id


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> dict[str, dict]:
    prices = load_prices()
    regime = load_regime_series(prices)

    # ── Backtest A: Baseline (no filter) ──────────────────────────────────────
    logger.info("\nRunning Backtest A — Baseline (no regime filter)...")
    ra = run_backtest(prices, label="regime_v1_baseline", regime=None)
    print_results(ra)
    ra["experiment_id"] = log_to_db(
        ra,
        name="regime_v1_baseline",
        hypothesis=(
            "Momentum baseline — no regime filter. "
            "Top-5 JT 12-1 momentum, 5bps slippage, equal-weight. "
            "Full 2015→2026 history. Reference point for regime filter comparison."
        ),
        extra_notes="Baseline for regime filter experiment.",
    )

    # ── Backtest B: Momentum + SPY 200MA regime filter ────────────────────────
    logger.info("\nRunning Backtest B — Momentum + SPY 200MA regime filter...")
    rb = run_backtest(prices, label="regime_v1_spy200ma", regime=regime)
    print_results(rb)
    rb["experiment_id"] = log_to_db(
        rb,
        name="regime_v1_spy200ma",
        hypothesis=(
            "Momentum + SPY 200-day MA regime filter — cash in bear regime. "
            "Long top-5 momentum when SPY close > 200-day SMA (bull). "
            "100% cash when SPY close < 200-day SMA (bear). "
            "Tests whether avoiding bear markets reduces drawdown enough to "
            "justify the CAGR cost of cash drag."
        ),
        extra_notes="Regime filter v1 — SPY 200MA. Compare vs regime_v1_baseline.",
    )

    # ── Side-by-side comparison ───────────────────────────────────────────────
    ma = ra["metrics"]
    mb = rb["metrics"]
    logger.info(f"\n{'='*65}")
    logger.info("  SIDE-BY-SIDE COMPARISON")
    logger.info(f"{'='*65}")
    logger.info(f"{'Metric':<28} {'Baseline':>10} {'+ Regime':>10} {'Delta':>10}")
    logger.info(f"{'─'*28} {'─'*10} {'─'*10} {'─'*10}")
    logger.info(f"{'CAGR':<28} {ma['cagr']:>10.2%} {mb['cagr']:>10.2%} "
                f"{mb['cagr']-ma['cagr']:>+10.2%}")
    logger.info(f"{'Sharpe':<28} {ma['sharpe']:>10.2f} {mb['sharpe']:>10.2f} "
                f"{mb['sharpe']-ma['sharpe']:>+10.2f}")
    logger.info(f"{'Sortino':<28} {ma['sortino']:>10.2f} {mb['sortino']:>10.2f} "
                f"{mb['sortino']-ma['sortino']:>+10.2f}")
    logger.info(f"{'Max Drawdown':<28} {ma['max_drawdown']:>10.2%} {mb['max_drawdown']:>10.2%} "
                f"{mb['max_drawdown']-ma['max_drawdown']:>+10.2%}")
    logger.info(f"{'Volatility':<28} {ma['volatility_annualized']:>10.2%} "
                f"{mb['volatility_annualized']:>10.2%} "
                f"{mb['volatility_annualized']-ma['volatility_annualized']:>+10.2%}")
    logger.info(f"{'Win Rate':<28} {ra['win_rate']:>10.2%} {rb['win_rate']:>10.2%} "
                f"{rb['win_rate']-ra['win_rate']:>+10.2%}")
    logger.info(f"{'% Time in Cash':<28} {'0.00%':>10} {rb['cash_pct']:>10.2%}")
    logger.info(f"{'Regime Switches':<28} {'—':>10} {rb['regime_switches']:>10}")
    logger.info(f"{'='*65}")

    return {"baseline": ra, "regime_filter": rb}


if __name__ == "__main__":
    results = main()
