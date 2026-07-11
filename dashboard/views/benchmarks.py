"""Page 2 — Benchmarks: strategy vs SPY, QQQ, and 60/40.

Section 1 — Live paper portfolio vs SPY / QQQ (normalized to same start)
Section 2 — Historical backtest vs SPY / QQQ / 60-40
Section 3 — Key comparison metrics table (CAGR, Sharpe, MaxDD, best/worst year)
Section 4 — Rolling 63-day Sharpe: strategy vs SPY
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.data import STARTING_CAPITAL, load_pnl_history, load_price_bars
from dashboard.db import get_session
from sqlalchemy import text as _sql
from features.momentum.price_momentum import compute_momentum_score
from tracking.analytics import cagr, max_drawdown, sharpe_ratio

# Validated backtest parameters (matches production strategy)
_LOOKBACK = 252   # 12-month lookback
_SKIP = 21        # skip most recent month (Jegadeesh-Titman)
_TOP_N = 5
_SLIPPAGE = 5 / 10_000  # 5 bps per side
_REBAL_FREQ = 5   # every 5 trading days

_BG   = "#08090c"
_BG2  = "#0d0f14"
_GRID = "#1a1d26"
_TEXT = "#8892a4"


def _dark_layout(height: int = 380) -> dict:
    return dict(
        height=height,
        paper_bgcolor=_BG,
        plot_bgcolor=_BG2,
        font=dict(family="Consolas, 'Courier New', monospace", size=11, color=_TEXT),
        xaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID,
                   tickfont=dict(size=10, color=_TEXT), title_font=dict(size=11, color=_TEXT)),
        yaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID,
                   tickfont=dict(size=10, color=_TEXT), title_font=dict(size=11, color=_TEXT)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=_TEXT, size=11)),
    )


def _ief_in_db() -> bool:
    """Direct DB check for IEF — bypasses st.cache_data entirely."""
    with get_session() as s:
        row = s.execute(
            _sql("SELECT COUNT(*) FROM price_bars WHERE symbol = 'IEF'")
        ).scalar()
    return (row or 0) > 0


_EQUITY_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "JNJ", "XOM", "LLY", "AVGO", "WMT", "MA", "PG",
    "HD", "CVX",
]


# ── Cached backtest runner ────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner="Running validated backtest…")
def _run_validated_backtest() -> pd.DataFrame:
    """Return daily equity curve for the validated momentum strategy.

    Uses: 12-1 JT momentum, top-5 equal-weight, 5bps slippage, 5-day rebalance.
    Cached for 1 hour — deterministic on price_bars contents.
    Returns a DataFrame with a DatetimeIndex and column 'value'.
    """
    price_df = load_price_bars(tuple(sorted(_EQUITY_UNIVERSE)))
    if price_df.empty:
        return pd.DataFrame()

    # Compute momentum scores
    score_df = pd.DataFrame(index=price_df.index)
    for sym in price_df.columns:
        series = price_df[sym].dropna()
        if len(series) < _LOOKBACK + _SKIP + 10:
            continue
        score_df[sym] = compute_momentum_score(series, lookback=_LOOKBACK, skip_last=_SKIP)
    score_df = score_df.dropna(how="all")

    if score_df.empty:
        return pd.DataFrame()

    rebalance_dates = score_df.index[::_REBAL_FREQ]
    portfolio_value = STARTING_CAPITAL
    equity_curve: list[tuple] = []
    prev_holdings: set[str] = set()

    for i, rebal_date in enumerate(rebalance_dates):
        row = score_df.loc[rebal_date].dropna()
        if row.empty:
            continue

        top_symbols = set(row.nlargest(_TOP_N).index)
        changed = (top_symbols | prev_holdings) - (top_symbols & prev_holdings)
        slippage_cost = len(changed) * _SLIPPAGE * (portfolio_value / _TOP_N)
        portfolio_value -= slippage_cost

        next_rebal = (
            rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else score_df.index[-1]
        )
        period = price_df.loc[rebal_date:next_rebal, list(top_symbols)].dropna(how="all")
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
        return pd.DataFrame()

    eq_df = pd.DataFrame(equity_curve, columns=["date", "value"]).set_index("date")
    eq_df = eq_df[~eq_df.index.duplicated(keep="last")]
    return eq_df


# ── Analytics helpers ─────────────────────────────────────────────────────────

def _normalize(series: pd.Series, start_value: float = STARTING_CAPITAL) -> pd.Series:
    """Normalize a price series to start_value at its first observation."""
    return series / series.iloc[0] * start_value


def _best_worst_year(eq: pd.Series) -> tuple[float, float]:
    """Return (best_annual_return, worst_annual_return)."""
    if eq.empty:
        return float("nan"), float("nan")
    years = eq.index.year
    annual = {}
    for yr in sorted(set(years)):
        sub = eq[eq.index.year == yr]
        if len(sub) < 2:
            continue
        annual[yr] = sub.iloc[-1] / sub.iloc[0] - 1
    if not annual:
        return float("nan"), float("nan")
    vals = list(annual.values())
    return max(vals), min(vals)


def _rolling_sharpe(values: pd.Series, window: int = 63, rf_annual: float = 0.05) -> pd.Series:
    """Compute rolling annualized Sharpe on a value series."""
    daily_rf = rf_annual / 252
    returns = values.pct_change().dropna()
    excess = returns - daily_rf
    roll_mean = excess.rolling(window).mean()
    roll_std = excess.rolling(window).std()
    return (roll_mean / roll_std * np.sqrt(252)).replace([np.inf, -np.inf], np.nan)


def _metrics_row(
    name: str,
    eq: pd.Series,
    rf: float = 0.05,
) -> dict:
    if eq.empty or len(eq) < 5:
        return {
            "Name": name, "CAGR": "—", "Sharpe": "—",
            "Max DD": "—", "Best Year": "—", "Worst Year": "—",
        }
    returns = eq.pct_change().dropna()
    best, worst = _best_worst_year(eq)
    return {
        "Name": name,
        "CAGR": f"{cagr(eq):.1%}",
        "Sharpe": f"{sharpe_ratio(returns, risk_free_rate=rf):.2f}",
        "Max DD": f"{max_drawdown(eq):.1%}",
        "Best Year": f"{best:+.1%}" if not np.isnan(best) else "—",
        "Worst Year": f"{worst:+.1%}" if not np.isnan(worst) else "—",
    }


# ── Page render ───────────────────────────────────────────────────────────────

def render() -> None:
    st.title("Benchmarks")
    st.caption("Strategy performance measured against passive market benchmarks.")

    _render_live_comparison()
    st.divider()
    _render_historical_comparison()
    st.divider()
    _render_metrics_table()
    st.divider()
    _render_rolling_sharpe()


# ── Section 1 ─────────────────────────────────────────────────────────────────

def _render_live_comparison() -> None:
    st.subheader("Section 1 — Live Paper Portfolio vs Benchmarks")
    st.caption("⚠️ Live paper trading — no real money")

    pnl_df = load_pnl_history()
    if pnl_df.empty:
        st.info(
            "No live paper trading data yet. Run `python run_pipeline.py` to generate the first day."
        )
        return

    # Index is date objects from pnl table; convert to DatetimeIndex
    pnl_df.index = pd.to_datetime(pnl_df.index)
    start_date = pnl_df.index[0]

    # Load SPY and QQQ from price_bars, aligned to paper portfolio start
    bm_df = load_price_bars(("QQQ", "SPY"))
    if bm_df.empty:
        st.warning("Benchmark price data not found. Ingest SPY/QQQ first.")
        return

    bm_df = bm_df[bm_df.index >= start_date]

    # Align benchmarks to pnl dates (forward-fill any gaps)
    # Deduplicate pnl index (guard against double pipeline runs on same day)
    pnl_df = pnl_df[~pnl_df.index.duplicated(keep="last")]
    combined_idx = pnl_df.index.union(bm_df.index)
    strategy_eq = pnl_df["total_value"].reindex(combined_idx).ffill().dropna()
    strategy_eq = strategy_eq[strategy_eq.index >= start_date]

    fig = go.Figure()

    # Strategy line
    fig.add_trace(go.Scatter(
        x=strategy_eq.index, y=strategy_eq,
        name="Momentum Strategy",
        line=dict(color="#00ff9d", width=2.5),
    ))

    # SPY normalized
    if "SPY" in bm_df.columns:
        spy = bm_df["SPY"].reindex(strategy_eq.index, method="ffill").dropna()
        if not spy.empty:
            spy_norm = _normalize(spy, start_value=STARTING_CAPITAL)
            fig.add_trace(go.Scatter(
                x=spy_norm.index, y=spy_norm,
                name="SPY (buy & hold)",
                line=dict(color="#f4a261", width=1.8, dash="dash"),
            ))

    # QQQ normalized
    if "QQQ" in bm_df.columns:
        qqq = bm_df["QQQ"].reindex(strategy_eq.index, method="ffill").dropna()
        if not qqq.empty:
            qqq_norm = _normalize(qqq, start_value=STARTING_CAPITAL)
            fig.add_trace(go.Scatter(
                x=qqq_norm.index, y=qqq_norm,
                name="QQQ (buy & hold)",
                line=dict(color="#a8dadc", width=1.8, dash="dot"),
            ))

    fig.add_hline(
        y=STARTING_CAPITAL,
        line_dash="dash", line_color=_GRID,
        annotation_text="Starting Capital", annotation_font_color=_TEXT,
    )

    n_days = len(pnl_df)
    fig.update_layout(
        **_dark_layout(height=380),
        yaxis_title="Portfolio Value ($)",
        xaxis_title="Date",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=10, b=0),
        title_text=f"Live paper trading — {n_days} day{'s' if n_days != 1 else ''} — no real money",
        title_font_color=_TEXT,
        title_font_size=11,
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Section 2 ─────────────────────────────────────────────────────────────────

def _render_historical_comparison() -> None:
    st.subheader("Section 2 — Historical Backtest vs Benchmarks")
    st.caption("⚠️ Historical backtest — hypothetical results, not actual trading")

    eq_df = _run_validated_backtest()
    if eq_df.empty:
        st.warning(
            "Could not run backtest. Ensure price_bars contains the full equity universe "
            "with at least 2 years of history."
        )
        return

    start_date = eq_df.index[0]
    end_date = eq_df.index[-1]

    # Load benchmark bars.
    # Guard against stale cache: if IEF is in the DB but missing from the
    # cached result, clear the cache and rerun so the fresh query picks it up.
    bm_raw = load_price_bars(("IEF", "QQQ", "SPY"))
    if "IEF" not in bm_raw.columns and _ief_in_db():
        load_price_bars.clear()
        st.rerun()

    fig = go.Figure()

    # Strategy
    fig.add_trace(go.Scatter(
        x=eq_df.index, y=eq_df["value"],
        name="Momentum Strategy",
        line=dict(color="#00ff9d", width=2.5),
    ))

    # SPY buy & hold
    if not bm_raw.empty and "SPY" in bm_raw.columns:
        spy = bm_raw["SPY"].reindex(eq_df.index, method="ffill").dropna()
        if not spy.empty:
            spy_eq = _normalize(spy)
            fig.add_trace(go.Scatter(
                x=spy_eq.index, y=spy_eq,
                name="SPY (buy & hold)",
                line=dict(color="#f4a261", width=1.8, dash="dash"),
            ))

    # QQQ buy & hold
    if not bm_raw.empty and "QQQ" in bm_raw.columns:
        qqq = bm_raw["QQQ"].reindex(eq_df.index, method="ffill").dropna()
        if not qqq.empty:
            qqq_eq = _normalize(qqq)
            fig.add_trace(go.Scatter(
                x=qqq_eq.index, y=qqq_eq,
                name="QQQ (buy & hold)",
                line=dict(color="#a8dadc", width=1.8, dash="dot"),
            ))

    # 60/40: 60% SPY + 40% IEF
    if (
        not bm_raw.empty
        and "SPY" in bm_raw.columns
        and "IEF" in bm_raw.columns
    ):
        spy_r = bm_raw["SPY"].reindex(eq_df.index, method="ffill").pct_change()
        ief_r = bm_raw["IEF"].reindex(eq_df.index, method="ffill").pct_change()
        if not spy_r.dropna().empty and not ief_r.dropna().empty:
            blended = (0.6 * spy_r + 0.4 * ief_r).fillna(0)
            portfolio_6040 = STARTING_CAPITAL * (1 + blended).cumprod()
            fig.add_trace(go.Scatter(
                x=portfolio_6040.index, y=portfolio_6040,
                name="60/40 (SPY + IEF)",
                line=dict(color="#e9c46a", width=1.8, dash="dashdot"),
            ))
    elif not bm_raw.empty and "IEF" not in bm_raw.columns:
        # Reaches here only when IEF is genuinely absent from price_bars.
        st.info(
            "60/40 benchmark omitted — IEF not in price_bars. "
            "Run `python scripts/fetch_ief.py` once to add it, then refresh this page."
        )

    fig.add_hline(
        y=STARTING_CAPITAL,
        line_dash="dash", line_color=_GRID,
        annotation_text="Starting Capital", annotation_font_color=_TEXT,
    )
    fig.update_layout(
        **_dark_layout(height=400),
        yaxis_title="Portfolio Value ($)",
        xaxis_title="Date",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=10, b=0),
        title_text=(
            f"Historical backtest — hypothetical results — "
            f"{start_date.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')}"
        ),
        title_font_color=_TEXT,
        title_font_size=11,
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Section 3 ─────────────────────────────────────────────────────────────────

def _render_metrics_table() -> None:
    st.subheader("Section 3 — Key Comparison Metrics (Historical Backtest Period)")

    eq_df = _run_validated_backtest()
    if eq_df.empty:
        st.info("Backtest data unavailable — run Section 2 first.")
        return

    bm_raw = load_price_bars(("IEF", "QQQ", "SPY"))
    if "IEF" not in bm_raw.columns and _ief_in_db():
        load_price_bars.clear()
        st.rerun()
    strategy_eq = eq_df["value"]

    rows = [_metrics_row("Momentum Strategy", strategy_eq)]

    if not bm_raw.empty:
        if "SPY" in bm_raw.columns:
            spy = bm_raw["SPY"].reindex(strategy_eq.index, method="ffill").dropna()
            if not spy.empty:
                rows.append(_metrics_row("SPY (buy & hold)", _normalize(spy)))

        if "QQQ" in bm_raw.columns:
            qqq = bm_raw["QQQ"].reindex(strategy_eq.index, method="ffill").dropna()
            if not qqq.empty:
                rows.append(_metrics_row("QQQ (buy & hold)", _normalize(qqq)))

        if "SPY" in bm_raw.columns and "IEF" in bm_raw.columns:
            spy_r = bm_raw["SPY"].reindex(strategy_eq.index, method="ffill").pct_change()
            ief_r = bm_raw["IEF"].reindex(strategy_eq.index, method="ffill").pct_change()
            blended = (0.6 * spy_r + 0.4 * ief_r).fillna(0)
            eq_6040 = STARTING_CAPITAL * (1 + blended).cumprod()
            rows.append(_metrics_row("60/40 (SPY + IEF)", eq_6040))

    metrics_df = pd.DataFrame(rows)

    def _color_cagr(val: str) -> str:
        try:
            numeric = float(val.strip("%+").replace("—", "nan"))
            if numeric > 15:
                return "color: #2ecc71; font-weight: bold"
            if numeric > 0:
                return "color: #2ecc71"
        except ValueError:
            pass
        return ""

    styled = (
        metrics_df.style
        .applymap(_color_cagr, subset=["CAGR"])
        .set_properties(**{"text-align": "right"}, subset=["CAGR", "Sharpe", "Max DD", "Best Year", "Worst Year"])
        .set_properties(**{"text-align": "left"}, subset=["Name"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ── Section 4 ─────────────────────────────────────────────────────────────────

def _render_rolling_sharpe() -> None:
    st.subheader("Section 4 — Rolling 63-Day Sharpe: Strategy vs SPY")
    st.caption("Positive and stable rolling Sharpe indicates a consistent, not luck-driven, edge.")

    eq_df = _run_validated_backtest()
    if eq_df.empty:
        st.info("Backtest data unavailable.")
        return

    bm_raw = load_price_bars(("SPY",))
    strategy_sharpe = _rolling_sharpe(eq_df["value"])

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=strategy_sharpe.index,
        y=strategy_sharpe,
        name="Momentum Strategy (63d Sharpe)",
        line=dict(color="#00ff9d", width=2),
    ))

    if not bm_raw.empty and "SPY" in bm_raw.columns:
        spy = bm_raw["SPY"].reindex(eq_df.index, method="ffill").dropna()
        if not spy.empty:
            spy_sharpe = _rolling_sharpe(spy)
            fig.add_trace(go.Scatter(
                x=spy_sharpe.index,
                y=spy_sharpe,
                name="SPY (63d Sharpe)",
                line=dict(color="#f4a261", width=1.5, dash="dash"),
            ))

    fig.add_hline(y=0, line_dash="dash", line_color=_GRID)
    fig.add_hline(
        y=1.0, line_dash="dot", line_color="#00ff9d",
        annotation_text="Sharpe = 1.0", annotation_position="bottom right",
        annotation_font_color="#00ff9d",
    )
    fig.update_layout(
        **_dark_layout(height=360),
        yaxis_title="Rolling 63-Day Sharpe (rf=5%)",
        xaxis_title="Date",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary: % of time strategy Sharpe > SPY Sharpe
    strat_clean = strategy_sharpe.dropna()
    if not bm_raw.empty and "SPY" in bm_raw.columns:
        spy = bm_raw["SPY"].reindex(eq_df.index, method="ffill").dropna()
        spy_sharpe = _rolling_sharpe(spy)
        aligned = pd.concat([strat_clean, spy_sharpe], axis=1, join="inner").dropna()
        aligned.columns = ["strategy", "spy"]
        pct_above = (aligned["strategy"] > aligned["spy"]).mean()
        pct_positive = (aligned["strategy"] > 0).mean()

        c1, c2, c3 = st.columns(3)
        c1.metric("Avg Rolling Sharpe (Strategy)", f"{strat_clean.mean():.2f}")
        c2.metric("% Periods: Strategy > SPY", f"{pct_above:.0%}")
        c3.metric("% Periods: Strategy Sharpe > 0", f"{pct_positive:.0%}")
