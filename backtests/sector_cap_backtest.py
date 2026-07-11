"""
Sector Cap Backtest — V1
========================
Compare two strategies over full price_bars history (2015 → 2026):

  Backtest A: Momentum baseline — top-5, 12-1, 5bps, no sector cap
  Backtest B: Same momentum but max 1 stock per GICS sector in top-5

Selection algorithm for B (greedy, rank-order):
  - Rank all signals by momentum score descending
  - Walk the ranked list; add a symbol only if its GICS sector is not yet
    represented in the portfolio
  - Promotes lower-ranked stocks from underrepresented sectors as needed

Integrity checklist:
  [x] No look-ahead bias   — sector assignments are static (no future data used)
  [x] Adj_close throughout — price_bars uses yfinance auto_adjust=True
  [x] Slippage modeled     — 5bps per changed position
  [x] Transaction costs    — embedded in slippage
  [x] OOS consideration    — 2015 is warmup; test window 2016-2026
  [x] Logged to experiments — both experiments written to DB
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select

from data.database import get_session
from data.models import PriceBar
from experiments.experiment_log import log_experiment
from features.sector.sector_filter import apply_sector_cap, SECTOR_MAP
from tracking.analytics import summary as perf_summary

# ── Constants ─────────────────────────────────────────────────────────────────
LOOKBACK = 252
SKIP = 21
REBALANCE_FREQ = 5
MIN_SCORE = 0.05
TOP_N = 5
SLIPPAGE_BPS = 5
STARTING_CAPITAL = 100_000.0


# ── Data loading ──────────────────────────────────────────────────────────────

def load_prices() -> pd.DataFrame:
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
    use_sector_cap: bool = False,
) -> dict:
    trading_dates = prices.index.tolist()
    warmup = LOOKBACK + SKIP
    first_idx = warmup

    logger.info(
        f"[{label}] Warmup: {warmup} days → backtest starts "
        f"{trading_dates[first_idx].date()} "
        f"({len(trading_dates) - first_idx} days in test window)."
    )

    weights: dict[str, float] = {}
    daily_returns: list[float] = []
    turnover_list: list[float] = []
    cap_fire_count = 0          # rebalances where sector cap changed composition
    cap_promotion_total = 0     # total symbols promoted across all rebalances

    for i in range(first_idx, len(trading_dates)):
        dt = trading_dates[i]
        prev_dt = trading_dates[i - 1]

        # Daily portfolio return
        if weights:
            day_rets = prices.loc[dt] / prices.loc[prev_dt] - 1
            port_ret = float(sum(
                w * float(day_rets.get(sym, 0.0))
                for sym, w in weights.items()
            ))
        else:
            port_ret = 0.0

        # Rebalance on schedule
        steps_since_start = i - first_idx
        if steps_since_start % REBALANCE_FREQ == 0:
            scores = compute_scores(prices.loc[:prev_dt])

            if scores.empty:
                new_weights: dict[str, float] = {}
            elif use_sector_cap:
                result = apply_sector_cap(scores, top_n=TOP_N, verbose=False)
                new_holdings = [a.symbol for a in result.selected]
                new_weights = {sym: 1.0 / len(new_holdings) for sym in new_holdings} if new_holdings else {}
                if result.cap_applied:
                    cap_fire_count += 1
                    cap_promotion_total += sum(1 for a in result.selected if a.displaced)
            else:
                new_holdings = scores.nlargest(TOP_N).index.tolist()
                new_weights = {sym: 1.0 / len(new_holdings) for sym in new_holdings}

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
        "n_trading_days": len(daily_returns),
        "cap_fire_count": cap_fire_count,
        "cap_promotion_total": cap_promotion_total,
        "label": label,
        "use_sector_cap": use_sector_cap,
    }


# ── Snapshot: what sectors did the cap change? ────────────────────────────────

def sector_composition_snapshot(prices: pd.DataFrame) -> None:
    """Show sector composition of a typical rebalance near end of dataset."""
    logger.info("\n  Sector composition — final rebalance snapshot:")
    sample_date = prices.index[-REBALANCE_FREQ * 2]
    scores = compute_scores(prices.loc[:sample_date])
    if scores.empty:
        return

    # Baseline top-5
    baseline = scores.nlargest(TOP_N).index.tolist()
    baseline_sectors = [(s, SECTOR_MAP.get(s, "?")) for s in baseline]

    # Sector-capped top-5
    result = apply_sector_cap(scores, top_n=TOP_N, verbose=False)
    capped = [(a.symbol, a.sector, "promoted" if a.displaced else "") for a in result.selected]

    logger.info(f"  {'Rank':<5} {'Baseline':>8} {'Sector':>25}    {'Capped':>8} {'Sector':>25} {'Note':>10}")
    logger.info(f"  {'─'*5} {'─'*8} {'─'*25}    {'─'*8} {'─'*25} {'─'*10}")
    for i in range(TOP_N):
        b_sym, b_sec = baseline_sectors[i] if i < len(baseline_sectors) else ("—", "—")
        c_sym, c_sec, c_note = capped[i] if i < len(capped) else ("—", "—", "")
        changed = "← changed" if b_sym != c_sym else ""
        logger.info(f"  {i+1:<5} {b_sym:>8} {b_sec:>25}    {c_sym:>8} {c_sec:>25} {c_note or changed:>10}")
    if result.cap_applied:
        logger.info(f"  → Cap fired. Dropped: {[a.symbol for a in result.dropped]}")
    else:
        logger.info("  → No cap changes at this snapshot date.")


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_results(r: dict) -> None:
    m = r["metrics"]
    spy = r["spy_metrics"]
    label = r["label"]

    logger.info(f"\n{'='*65}")
    logger.info(f"  {label.upper()}")
    logger.info(f"  Top-{TOP_N} | Slippage {SLIPPAGE_BPS}bps | "
                f"Period {r['backtest_start']} → {r['backtest_end']}")
    if r["use_sector_cap"]:
        pct_fired = r["cap_fire_count"] / r["n_rebalances"] if r["n_rebalances"] else 0
        logger.info(
            f"  Sector cap fired: {r['cap_fire_count']}/{r['n_rebalances']} rebalances "
            f"({pct_fired:.1%}) | Total promotions: {r['cap_promotion_total']}"
        )
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
    logger.info(f"\n  Year-by-Year Returns (Strategy vs SPY):")
    logger.info(f"  {'Year':<6} {'Strategy':>10} {'SPY':>10} {'vs SPY':>10}  Flag")
    logger.info(f"  {'─'*6} {'─'*10} {'─'*10} {'─'*10}  {'─'*20}")
    for yr in sorted(r["annual_returns"].index):
        strat = r["annual_returns"][yr]
        bench = r["spy_annual"].get(yr, float("nan"))
        diff = strat - bench if not np.isnan(bench) else float("nan")
        flag = "⚠ loss year" if strat < -0.10 else ("⚠ underperform" if not np.isnan(diff) and diff < -0.10 else "")
        logger.info(f"  {yr:<6} {strat:>10.2%} {bench:>10.2%} {diff:>+10.2%}  {flag}")


def log_to_db(r: dict, name: str, hypothesis: str, extra_notes: str = "") -> str:
    m = r["metrics"]
    spy = r["spy_metrics"]
    pct_fired = r["cap_fire_count"] / r["n_rebalances"] if r["n_rebalances"] else 0

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
            "sector_cap": "1_per_sector" if r["use_sector_cap"] else "none",
            "cap_fire_rate": round(pct_fired, 4),
            "cap_promotions_total": r["cap_promotion_total"],
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
            f"Sector cap fired {pct_fired:.1%} of rebalances."
        ),
        start_date=r["backtest_start"],
        end_date=r["backtest_end"],
        sharpe=m["sharpe"],
        cagr=m["cagr"],
        max_drawdown=m["max_drawdown"],
        notes=(
            f"Experiment: {name}. "
            f"Sector cap: {'1 per GICS sector' if r['use_sector_cap'] else 'none (baseline)'}. "
            f"Survivorship bias: universe fixed at current 22 large-caps. "
            + extra_notes
        ),
    )
    logger.info(f"[{name}] Logged as experiment {experiment_id}")
    return experiment_id


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> dict[str, dict]:
    prices = load_prices()

    # ── Backtest A: Baseline (no sector cap) ──────────────────────────────────
    logger.info("\nRunning Backtest A — Baseline (no sector cap)...")
    ra = run_backtest(prices, label="sector_v1_baseline", use_sector_cap=False)
    print_results(ra)
    ra["experiment_id"] = log_to_db(
        ra,
        name="sector_v1_baseline",
        hypothesis=(
            "Momentum baseline — no sector cap. "
            "Top-5 JT 12-1 momentum, 5bps slippage, equal-weight. "
            "Full 2015→2026 history. Reference for sector cap comparison."
        ),
        extra_notes="Baseline for sector diversification cap experiment.",
    )

    # ── Backtest B: Sector cap (1 per GICS sector) ────────────────────────────
    logger.info("\nRunning Backtest B — Sector cap (max 1 per GICS sector)...")
    rb = run_backtest(prices, label="sector_v1_1per_sector", use_sector_cap=True)
    print_results(rb)
    rb["experiment_id"] = log_to_db(
        rb,
        name="sector_v1_1per_sector",
        hypothesis=(
            "Momentum top-5 with 1-stock-per-sector diversification cap. "
            "Greedy rank-order selection: highest-ranked stock per sector wins; "
            "lower-ranked same-sector stocks replaced by next eligible sector. "
            "Tests whether forced sector diversity improves Sharpe or reduces "
            "drawdown vs unconstrained top-5."
        ),
        extra_notes=(
            "Sector map: 22 symbols across Technology, Communication Services, "
            "Consumer Discretionary, Consumer Staples, Financials, Health Care, Energy. "
            "V and MA classified as Technology (GICS IT sub-industry). "
            "BRK-B classified as Financials."
        ),
    )

    # ── Sector snapshot ───────────────────────────────────────────────────────
    sector_composition_snapshot(prices)

    # ── Side-by-side comparison ───────────────────────────────────────────────
    ma = ra["metrics"]
    mb = rb["metrics"]
    pct_fired = rb["cap_fire_count"] / rb["n_rebalances"] if rb["n_rebalances"] else 0

    logger.info(f"\n{'='*65}")
    logger.info("  SIDE-BY-SIDE COMPARISON")
    logger.info(f"{'='*65}")
    logger.info(f"{'Metric':<28} {'Baseline':>10} {'+ Sector':>10} {'Delta':>10}")
    logger.info(f"{'─'*28} {'─'*10} {'─'*10} {'─'*10}")
    logger.info(f"{'CAGR':<28} {ma['cagr']:>10.2%} {mb['cagr']:>10.2%} {mb['cagr']-ma['cagr']:>+10.2%}")
    logger.info(f"{'Sharpe':<28} {ma['sharpe']:>10.2f} {mb['sharpe']:>10.2f} {mb['sharpe']-ma['sharpe']:>+10.2f}")
    logger.info(f"{'Sortino':<28} {ma['sortino']:>10.2f} {mb['sortino']:>10.2f} {mb['sortino']-ma['sortino']:>+10.2f}")
    logger.info(f"{'Max Drawdown':<28} {ma['max_drawdown']:>10.2%} {mb['max_drawdown']:>10.2%} {mb['max_drawdown']-ma['max_drawdown']:>+10.2%}")
    logger.info(f"{'Volatility':<28} {ma['volatility_annualized']:>10.2%} {mb['volatility_annualized']:>10.2%} {mb['volatility_annualized']-ma['volatility_annualized']:>+10.2%}")
    logger.info(f"{'Win Rate':<28} {ra['win_rate']:>10.2%} {rb['win_rate']:>10.2%} {rb['win_rate']-ra['win_rate']:>+10.2%}")
    logger.info(f"{'Cap Fire Rate':<28} {'—':>10} {pct_fired:>10.2%}")
    logger.info(f"{'Cap Promotions':<28} {'—':>10} {rb['cap_promotion_total']:>10}")
    logger.info(f"{'='*65}")

    return {"baseline": ra, "sector_cap": rb}


if __name__ == "__main__":
    results = main()
