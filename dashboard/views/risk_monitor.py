"""Page 4 — Risk Monitor: exposure vs limits, drawdown state, breach history."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from config.risk_limits import (
    MAX_DAILY_DRAWDOWN,
    MAX_GROSS_EXPOSURE,
    MAX_NET_EXPOSURE,
    MAX_TOTAL_DRAWDOWN,
)
from dashboard.data import (
    STARTING_CAPITAL,
    load_latest_snapshot,
    load_pnl_history,
)


def render() -> None:
    st.title("Risk Monitor")

    snapshot = load_latest_snapshot()
    pnl_df = load_pnl_history()

    if snapshot is None:
        st.info("No portfolio data yet. Run `python run_pipeline.py` to generate the first snapshot.")
        return

    total_value = snapshot["total_value"]
    gross_exposure = snapshot["gross_exposure"]
    net_exposure = snapshot["net_exposure"]

    daily_pnl = pnl_df["daily_pnl"].iloc[-1] if not pnl_df.empty else 0.0
    current_drawdown = pnl_df["drawdown"].iloc[-1] if not pnl_df.empty else 0.0

    # ── Breach detection ──────────────────────────────────────────────────────
    breaches = []
    if abs(current_drawdown) >= MAX_TOTAL_DRAWDOWN:
        breaches.append(f"TOTAL DRAWDOWN HALT: {current_drawdown:.2%} ≥ {MAX_TOTAL_DRAWDOWN:.0%} limit")
    if total_value > 0 and daily_pnl / STARTING_CAPITAL <= -MAX_DAILY_DRAWDOWN:
        breaches.append(f"DAILY LOSS LIMIT: {daily_pnl/STARTING_CAPITAL:.2%} ≥ {MAX_DAILY_DRAWDOWN:.0%} daily limit")
    if total_value > 0 and gross_exposure / total_value > MAX_GROSS_EXPOSURE:
        breaches.append(f"GROSS EXPOSURE: {gross_exposure/total_value:.1%} > {MAX_GROSS_EXPOSURE:.0%} limit")

    if breaches:
        for b in breaches:
            st.error(f"🚨 **BREACH:** {b}")
    else:
        st.success("✅ No active risk limit breaches")

    st.divider()

    # ── Current exposure gauges ───────────────────────────────────────────────
    st.subheader("Current Exposure")

    gross_pct = gross_exposure / total_value if total_value > 0 else 0.0
    net_pct = net_exposure / total_value if total_value > 0 else 0.0
    dd_pct = abs(current_drawdown)

    col1, col2, col3 = st.columns(3)

    with col1:
        _gauge(
            col1,
            label="Gross Exposure",
            value=gross_pct * 100,
            limit=MAX_GROSS_EXPOSURE * 100,
            fmt=f"{gross_pct:.1%}",
            warning=80.0,
        )

    with col2:
        _gauge(
            col2,
            label="Net Exposure",
            value=net_pct * 100,
            limit=MAX_NET_EXPOSURE * 100,
            fmt=f"{net_pct:.1%}",
            warning=70.0,
        )

    with col3:
        _gauge(
            col3,
            label="Total Drawdown",
            value=dd_pct * 100,
            limit=MAX_TOTAL_DRAWDOWN * 100,
            fmt=f"{current_drawdown:.2%}",
            warning=MAX_TOTAL_DRAWDOWN * 100 * 0.6,
        )

    st.divider()

    # ── Exposure vs limits table ──────────────────────────────────────────────
    st.subheader("Limits Summary")
    limits_data = [
        {
            "Metric": "Gross Exposure",
            "Current": f"{gross_pct:.1%}",
            "Limit": f"{MAX_GROSS_EXPOSURE:.0%}",
            "Status": "🔴 BREACH" if gross_pct > MAX_GROSS_EXPOSURE else "🟢 OK",
        },
        {
            "Metric": "Net Exposure",
            "Current": f"{net_pct:.1%}",
            "Limit": f"{MAX_NET_EXPOSURE:.0%}",
            "Status": "🔴 BREACH" if net_pct > MAX_NET_EXPOSURE else "🟢 OK",
        },
        {
            "Metric": "Total Drawdown",
            "Current": f"{current_drawdown:.2%}",
            "Limit": f"{MAX_TOTAL_DRAWDOWN:.0%}",
            "Status": "🔴 HALT" if dd_pct >= MAX_TOTAL_DRAWDOWN else "🟢 OK",
        },
        {
            "Metric": "Daily Loss",
            "Current": f"{daily_pnl/STARTING_CAPITAL:+.2%}",
            "Limit": f"-{MAX_DAILY_DRAWDOWN:.0%}",
            "Status": (
                "🔴 BREACH"
                if daily_pnl / STARTING_CAPITAL <= -MAX_DAILY_DRAWDOWN
                else "🟢 OK"
            ),
        },
    ]
    import pandas as pd
    st.dataframe(pd.DataFrame(limits_data), use_container_width=True, hide_index=True)

    st.divider()

    # ── Historical drawdown chart ─────────────────────────────────────────────
    st.subheader("Drawdown History")
    if pnl_df.empty:
        st.info("No PnL history yet.")
    else:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=pnl_df.index,
                y=pnl_df["drawdown"] * 100,
                mode="lines",
                fill="tozeroy",
                name="Drawdown %",
                line=dict(color="#e63946", width=2),
                fillcolor="rgba(230,57,70,0.18)",
            )
        )
        fig.add_hline(
            y=-MAX_DAILY_DRAWDOWN * 100,
            line_dash="dot",
            line_color="orange",
            annotation_text=f"Daily halt ({-MAX_DAILY_DRAWDOWN:.0%})",
        )
        fig.add_hline(
            y=-MAX_TOTAL_DRAWDOWN * 100,
            line_dash="dash",
            line_color="red",
            annotation_text=f"Total halt ({-MAX_TOTAL_DRAWDOWN:.0%})",
        )
        fig.update_layout(
            yaxis_title="Drawdown (%)",
            xaxis_title="Date",
            hovermode="x unified",
            height=300,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)


def _gauge(container, label: str, value: float, limit: float, fmt: str, warning: float) -> None:
    """Render a simple metric with colored status indicator."""
    if value >= limit:
        status = "🔴"
    elif value >= warning:
        status = "🟡"
    else:
        status = "🟢"
    container.metric(
        label=f"{status} {label}",
        value=fmt,
        help=f"Limit: {limit:.0f}%",
    )
    # Mini progress bar
    bar_pct = min(value / limit, 1.0)
    container.progress(bar_pct)
    container.caption(f"Limit: {limit:.0f}%")
