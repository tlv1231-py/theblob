"""Page 3 — Backtest Lab: parameter controls, run backtest, compare experiments."""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.data import load_experiments, load_price_bars, log_experiment
from features.momentum.price_momentum import compute_momentum_score
from tracking.analytics import cagr, max_drawdown, sharpe_ratio, sortino_ratio

# Inline universe — avoids importing ingestion/ which pulls in data.database
DEFAULT_UNIVERSE = [
    "SPY", "QQQ",
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "JNJ", "XOM", "LLY", "AVGO", "WMT", "MA", "PG",
    "HD", "CVX",
]

STARTING_CAPITAL = 100_000.0
VALIDATED_BASELINE = {
    "lookback_days": 252,
    "skip_month": True,
    "top_n": 5,
    "slippage_bps": 5,
}
OVERFITTING_THRESHOLDS = {
    "lookback_days": 63,   # ± 63 days from baseline
    "top_n": 3,            # ± 3 from baseline
    "slippage_bps": 10,    # > 10 bps deviation
}


def render() -> None:
    st.title("Backtest Lab")
    st.caption("Parameters run against full `price_bars` history. All results logged to the experiments table.")

    all_symbols = DEFAULT_UNIVERSE

    # ── Parameter controls ────────────────────────────────────────────────────
    st.subheader("Parameters")

    col1, col2 = st.columns(2)

    with col1:
        lookback_months = st.slider(
            "Lookback window (months)", min_value=3, max_value=24, value=12, step=1
        )
        lookback_days = lookback_months * 21  # approximate trading days

        skip_month = st.toggle("Skip-month (Jegadeesh-Titman)", value=True)
        skip_last = 21 if skip_month else 0

        top_n = st.slider("Top-N signals", min_value=3, max_value=10, value=5)

    with col2:
        universe = st.multiselect(
            "Universe",
            options=all_symbols,
            default=all_symbols,
            help="Symbols to include in the backtest",
        )
        slippage_bps = st.slider("Slippage (bps per side)", min_value=1, max_value=20, value=5)

    # Overfitting warning
    warnings = _overfitting_warnings(lookback_days, top_n, slippage_bps)
    if warnings:
        st.warning("⚠️ **Overfitting risk:** " + " | ".join(warnings))

    hypothesis = st.text_input(
        "Hypothesis / notes (required to run)",
        placeholder="e.g. Testing shorter 6-month lookback vs validated 12-month baseline",
    )

    run_btn = st.button("▶ Run Backtest", type="primary", disabled=not hypothesis or not universe)

    if run_btn and hypothesis and universe:
        _run_backtest(
            universe=universe,
            lookback_days=lookback_days,
            skip_last=skip_last,
            top_n=top_n,
            slippage_bps=slippage_bps,
            hypothesis=hypothesis,
        )

    st.divider()

    # ── Experiment comparison table ───────────────────────────────────────────
    st.subheader("All Experiments")
    _render_experiment_table()


def _run_backtest(
    universe: list[str],
    lookback_days: int,
    skip_last: int,
    top_n: int,
    slippage_bps: float,
    hypothesis: str,
) -> None:
    with st.spinner("Loading price data and running backtest…"):
        price_df = load_price_bars(tuple(sorted(universe)))

    if price_df.empty:
        st.error("No price data found in DB. Ingest data first.")
        return

    # ── Run backtest ──────────────────────────────────────────────────────────
    slippage_per_trade = slippage_bps / 10_000

    # Compute momentum scores for each symbol across all dates
    score_df = pd.DataFrame(index=price_df.index)
    for sym in price_df.columns:
        series = price_df[sym].dropna()
        if len(series) < lookback_days + skip_last + 5:
            continue
        scores = compute_momentum_score(series, lookback=lookback_days, skip_last=skip_last)
        score_df[sym] = scores

    score_df = score_df.dropna(how="all")

    if score_df.empty:
        st.error("Not enough history to compute momentum scores with these parameters.")
        return

    # Resample to monthly rebalance (approximate — use ~21-day steps)
    rebalance_dates = score_df.index[::21]

    portfolio_value = STARTING_CAPITAL
    equity_curve: list[tuple] = []
    prev_holdings: set[str] = set()

    for i, rebal_date in enumerate(rebalance_dates):
        row = score_df.loc[rebal_date].dropna()
        if row.empty:
            continue

        # Select top-N
        top_symbols = set(row.nlargest(top_n).index)

        # Apply slippage on changed positions
        changed = (top_symbols | prev_holdings) - (top_symbols & prev_holdings)
        slippage_cost = len(changed) * slippage_per_trade * (portfolio_value / top_n)
        portfolio_value -= slippage_cost

        # Next rebalance date (or end of data)
        next_rebal = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else score_df.index[-1]
        period = price_df.loc[rebal_date:next_rebal, list(top_symbols)].dropna(how="all")

        if period.empty or len(period) < 2:
            prev_holdings = top_symbols
            continue

        # Equal-weight return over period
        period_returns = period.pct_change().dropna()
        portfolio_return = period_returns.mean(axis=1)

        for dt, ret in zip(period.index[1:], portfolio_return):
            portfolio_value *= (1 + ret)
            equity_curve.append((dt, portfolio_value))

        prev_holdings = top_symbols

    if len(equity_curve) < 20:
        st.error("Backtest produced too few data points. Try a wider universe or longer lookback.")
        return

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
    }

    # ── Display results ───────────────────────────────────────────────────────
    st.success("Backtest complete")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("CAGR", f"{stats['cagr']:.1%}")
    m2.metric("Sharpe", f"{stats['sharpe']:.2f}")
    m3.metric("Sortino", f"{stats['sortino']:.2f}")
    m4.metric("Max DD", f"{stats['max_drawdown']:.1%}")
    m5.metric("Volatility", f"{stats['volatility']:.1%}")
    m6.metric("Win Rate", f"{stats['win_rate']:.1%}")

    # Equity curve + SPY benchmark
    spy_data = load_price_bars(("SPY",))
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=eq_df.index, y=eq_df["value"],
            name="Strategy", line=dict(color="#00b4d8", width=2),
        )
    )
    if not spy_data.empty and "SPY" in spy_data.columns:
        spy = spy_data["SPY"].reindex(eq_df.index, method="ffill").dropna()
        spy_eq = spy / spy.iloc[0] * STARTING_CAPITAL
        fig.add_trace(
            go.Scatter(
                x=spy_eq.index, y=spy_eq,
                name="SPY (buy & hold)", line=dict(color="gray", width=1.5, dash="dash"),
            )
        )
    fig.update_layout(
        yaxis_title="Portfolio Value ($)", height=340,
        hovermode="x unified", margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Year-by-year breakdown
    eq_df["year"] = eq_df.index.year
    yearly = (
        eq_df.groupby("year")["value"]
        .agg(["first", "last"])
        .assign(cagr=lambda d: d["last"] / d["first"] - 1)
    )
    yearly_display = yearly[["cagr"]].reset_index()
    yearly_display.columns = ["Year", "Return"]
    yearly_display["Return"] = yearly_display["Return"].map(lambda x: f"{x:.1%}")
    st.subheader("Year-by-Year Returns")
    st.dataframe(yearly_display, use_container_width=True, hide_index=True)

    # ── Log to experiments table ──────────────────────────────────────────────
    params = {
        "lookback_days": lookback_days,
        "skip_last": skip_last,
        "top_n": top_n,
        "slippage_bps": slippage_bps,
        "universe": sorted(universe),
        "universe_size": len(universe),
    }
    result_summary = (
        f"CAGR={stats['cagr']:.2%} | Sharpe={stats['sharpe']:.2f} | "
        f"Sortino={stats['sortino']:.2f} | MaxDD={stats['max_drawdown']:.2%} | "
        f"Vol={stats['volatility']:.2%} | WinRate={stats['win_rate']:.2%}"
    )
    exp_id = log_experiment(
        strategy="momentum",
        hypothesis=hypothesis,
        params=params,
        result_summary=result_summary,
        start_date=eq_df.index[0].date(),
        end_date=eq_df.index[-1].date(),
        sharpe=stats["sharpe"],
        cagr_val=stats["cagr"],
        max_drawdown_val=stats["max_drawdown"],
        notes="Run from Backtest Lab dashboard",
    )
    st.caption(f"Logged as experiment `{exp_id}`")

    # Invalidate experiment cache so the table below refreshes
    load_experiments.clear()


def _render_experiment_table() -> None:
    df = load_experiments()
    if df.empty:
        st.info("No experiments logged yet.")
        return

    display = df[["id", "strategy", "hypothesis", "sharpe", "cagr", "max_drawdown", "start", "end", "logged_at"]].copy()
    display.columns = ["ID", "Strategy", "Hypothesis", "Sharpe", "CAGR", "Max DD", "Start", "End", "Logged"]
    display["Sharpe"] = display["Sharpe"].map(lambda x: f"{x:.2f}" if x is not None else "—")
    display["CAGR"] = display["CAGR"].map(lambda x: f"{x:.1%}" if x is not None else "—")
    display["Max DD"] = display["Max DD"].map(lambda x: f"{x:.1%}" if x is not None else "—")
    display["Logged"] = pd.to_datetime(display["Logged"]).dt.strftime("%Y-%m-%d %H:%M")

    st.dataframe(display, use_container_width=True, hide_index=True)


def _overfitting_warnings(lookback_days: int, top_n: int, slippage_bps: float) -> list[str]:
    warnings = []
    baseline_lookback = VALIDATED_BASELINE["lookback_days"]
    if abs(lookback_days - baseline_lookback) > OVERFITTING_THRESHOLDS["lookback_days"]:
        warnings.append(
            f"Lookback {lookback_days}d deviates >63d from validated {baseline_lookback}d"
        )
    if abs(top_n - VALIDATED_BASELINE["top_n"]) > OVERFITTING_THRESHOLDS["top_n"]:
        warnings.append(f"Top-N={top_n} deviates >{OVERFITTING_THRESHOLDS['top_n']} from validated {VALIDATED_BASELINE['top_n']}")
    if abs(slippage_bps - VALIDATED_BASELINE["slippage_bps"]) > OVERFITTING_THRESHOLDS["slippage_bps"]:
        warnings.append(f"Slippage {slippage_bps}bps differs significantly from validated {VALIDATED_BASELINE['slippage_bps']}bps")
    return warnings
