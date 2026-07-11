"""Page 1 — Portfolio: equity curve, positions, PnL, drawdown, rolling Sharpe."""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.data import (
    STARTING_CAPITAL,
    add_capital_event,
    add_chart_annotation,
    delete_capital_event,
    delete_chart_annotation,
    load_capital_events,
    load_chart_annotations,
    load_fills,
    load_latest_prices,
    load_latest_snapshot,
    load_pnl_history,
    load_snapshot_history,
)


_BG   = "#08090c"
_BG2  = "#0d0f14"
_GRID = "#1a1d26"
_TEXT = "#8892a4"
_HI   = "#e8eaf0"


def _dark_layout(height: int = 360) -> dict:
    """Shared Plotly layout dict for the futurepunk dark theme."""
    return dict(
        height=height,
        paper_bgcolor=_BG,
        plot_bgcolor=_BG2,
        font=dict(family="Consolas, 'Courier New', monospace", size=11, color=_TEXT),
        xaxis=dict(
            gridcolor=_GRID, zerolinecolor=_GRID,
            tickfont=dict(size=10, color=_TEXT),
            title_font=dict(size=11, color=_TEXT),
        ),
        yaxis=dict(
            gridcolor=_GRID, zerolinecolor=_GRID,
            tickfont=dict(size=10, color=_TEXT),
            title_font=dict(size=11, color=_TEXT),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=_TEXT, size=11),
        ),
    )


def render() -> None:
    st.title("Portfolio")

    # Reduce metric value font size so dollar amounts don't truncate in 5-column layout
    st.markdown(
        """
        <style>
        [data-testid="stMetricValue"] {
            font-size: 1.1rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    pnl_df = load_pnl_history()
    snapshot = load_latest_snapshot()

    if snapshot is None or pnl_df.empty:
        st.info("No portfolio data yet. Run `python run_pipeline.py` to generate the first snapshot.")
        return

    # ── Summary metrics ───────────────────────────────────────────────────────
    total_value = snapshot["total_value"]
    cumulative_pnl = total_value - STARTING_CAPITAL
    daily_pnl = pnl_df["daily_pnl"].iloc[-1] if not pnl_df.empty else 0.0
    drawdown = pnl_df["drawdown"].iloc[-1] if not pnl_df.empty else 0.0
    peak = pnl_df["total_value"].max() if not pnl_df.empty else STARTING_CAPITAL

    # Rolling Sharpe (last value if we have ≥5 days)
    rolling_sharpe = _compute_rolling_sharpe(pnl_df)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Value", f"${total_value:,.2f}")
    col2.metric(
        "Daily P&L",
        f"${daily_pnl:+,.2f}",
        delta=f"{daily_pnl / STARTING_CAPITAL:+.2%}",
    )
    col3.metric(
        "Cumulative P&L",
        f"${cumulative_pnl:+,.2f}",
        delta=f"{cumulative_pnl / STARTING_CAPITAL:+.2%}",
    )
    col4.metric("Drawdown", f"{drawdown:.2%}", delta_color="inverse")
    col5.metric(
        "Rolling Sharpe (63d)",
        f"{rolling_sharpe:.2f}" if not math.isnan(rolling_sharpe) else "n/a",
        help="Requires ≥5 trading days of history",
    )

    st.divider()

    # ── Equity curve ──────────────────────────────────────────────────────────
    st.subheader("Equity Curve")
    annotations_df = load_chart_annotations()
    capital_df     = load_capital_events()

    if not pnl_df.empty:
        fig = go.Figure()

        # Invested-capital step line — steps up/down on each deposit/withdrawal
        if not capital_df.empty:
            all_dates = sorted(pnl_df.index.tolist())
            cap_step_x, cap_step_y = [], []
            running_capital = 0.0
            cap_by_date = {}
            for _, ev in capital_df.iterrows():
                cap_by_date[ev["date"]] = cap_by_date.get(ev["date"], 0.0) + ev["amount"]
            for d in all_dates:
                if d in cap_by_date:
                    running_capital += cap_by_date[d]
                cap_step_x.append(d)
                cap_step_y.append(running_capital)
            fig.add_trace(go.Scatter(
                x=cap_step_x,
                y=cap_step_y,
                mode="lines",
                name="Invested Capital",
                line=dict(color="rgba(180,180,180,0.7)", width=1.5, dash="dot"),
                hovertemplate="%{x}<br>Capital in: $%{y:,.0f}<extra></extra>",
            ))

        fig.add_trace(
            go.Scatter(
                x=pnl_df.index,
                y=pnl_df["total_value"],
                mode="lines+markers",
                name="Portfolio Value",
                line=dict(color="#00ff9d", width=2),
                marker=dict(size=5, color="#00ff9d"),
            )
        )
        fig.add_hline(
            y=STARTING_CAPITAL,
            line_dash="dash",
            line_color=_GRID,
            annotation_text="Starting Capital",
            annotation_font_color=_TEXT,
        )

        # Annotation vlines
        for _, ann in annotations_df.iterrows():
            x_ts = pd.Timestamp(ann["date"]).value / 1e6  # ms since epoch — what Plotly expects for date axes
            fig.add_vline(
                x=x_ts,
                line_dash="dot",
                line_color=ann["color"],
                line_width=1.5,
                annotation_text=ann["label"],
                annotation_position="top left",
                annotation=dict(
                    font=dict(size=11, color=ann["color"]),
                    textangle=-90,
                    showarrow=False,
                    yanchor="top",
                ),
            )

        fig.update_layout(
            **_dark_layout(height=360),
            yaxis_title="Portfolio Value ($)",
            xaxis_title="Date",
            hovermode="x unified",
            margin=dict(l=0, r=0, t=10, b=60),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Chart tools (annotations + capital events) ────────────────────────────
    ann_tab, cap_tab = st.tabs(["📌 Chart Annotations", "💵 Capital Events"])

    with ann_tab:
        with st.form("add_annotation", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns([2, 4, 2, 1])
            ann_date  = c1.date_input("Date", value=pd.Timestamp.today().date())
            ann_label = c2.text_input("Label", placeholder="e.g. Fixed duplicate fills")
            ann_color = c3.selectbox("Color", ["orange", "#e74c3c", "#2ecc71", "#00b4d8", "#9b59b6"],
                                     format_func=lambda x: {
                                         "orange": "🟠 Orange",
                                         "#e74c3c": "🔴 Red",
                                         "#2ecc71": "🟢 Green",
                                         "#00b4d8": "🔵 Blue",
                                         "#9b59b6": "🟣 Purple",
                                     }.get(x, x))
            if c4.form_submit_button("Add", use_container_width=True) and ann_label.strip():
                add_chart_annotation(ann_date, ann_label.strip(), ann_color)
                st.rerun()

        if annotations_df.empty:
            st.caption("No annotations yet.")
        else:
            for _, row in annotations_df.iterrows():
                col_info, col_del = st.columns([9, 1])
                col_info.markdown(
                    f'<span style="color:{row["color"]}">▏</span> '
                    f'**{row["date"]}** — {row["label"]}',
                    unsafe_allow_html=True,
                )
                if col_del.button("🗑", key=f"del_ann_{row['id']}", help="Delete"):
                    delete_chart_annotation(int(row["id"]))
                    st.rerun()

    with cap_tab:
        st.caption("Track money going into or out of the account. Shows as a dotted baseline on the equity curve so you can see true returns vs capital additions.")
        with st.form("add_capital_event", clear_on_submit=True):
            cc1, cc2, cc3, cc4 = st.columns([2, 2, 4, 1])
            cap_date   = cc1.date_input("Date", value=pd.Timestamp.today().date(), key="cap_date")
            cap_amount = cc2.number_input("Amount ($)", value=0.0, step=1000.0,
                                          help="Positive = deposit, negative = withdrawal")
            cap_note   = cc3.text_input("Note", placeholder="e.g. Added $5k from savings")
            if cc4.form_submit_button("Add", use_container_width=True) and cap_amount != 0:
                add_capital_event(cap_date, float(cap_amount), cap_note.strip())
                st.rerun()

        if capital_df.empty:
            st.caption("No capital events recorded.")
        else:
            running = 0.0
            for _, row in capital_df.iterrows():
                running += row["amount"]
                col_info, col_del = st.columns([9, 1])
                sign = "+" if row["amount"] >= 0 else ""
                col_info.markdown(
                    f'**{row["date"]}** &nbsp; {sign}${row["amount"]:,.0f} &nbsp;'
                    f'<span style="color:#888;font-size:0.85rem;">{row["note"]}</span>'
                    f'&nbsp;&nbsp; → total in: **${running:,.0f}**',
                    unsafe_allow_html=True,
                )
                if col_del.button("🗑", key=f"del_cap_{row['id']}", help="Delete"):
                    delete_capital_event(int(row["id"]))
                    st.rerun()

    # ── Cash vs Invested stacked area ────────────────────────────────────────
    snap_df = load_snapshot_history()
    if not snap_df.empty:
        fig_stack = go.Figure()
        fig_stack.add_trace(go.Scatter(
            x=snap_df.index,
            y=snap_df["invested"],
            name="Invested",
            mode="lines",
            fill="tozeroy",
            line=dict(color="#00ff9d", width=2),
            fillcolor="rgba(0,255,157,0.12)",
            stackgroup="one",
        ))
        fig_stack.add_trace(go.Scatter(
            x=snap_df.index,
            y=snap_df["cash"],
            name="Cash",
            mode="lines",
            fill="tonexty",
            line=dict(color="#00b4d8", width=2),
            fillcolor="rgba(0,180,216,0.12)",
            stackgroup="one",
        ))
        fig_stack.update_layout(
            **_dark_layout(height=300),
            title=dict(text="Capital Allocation — Invested vs Cash", font=dict(size=13, color="#8892a4")),
            yaxis_title="Value ($)",
            xaxis_title="Date",
            hovermode="x unified",
            margin=dict(l=0, r=0, t=36, b=0),
        )
        fig_stack.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                            xanchor="right", x=1, font=dict(color="#8892a4", size=11)))
        st.plotly_chart(fig_stack, use_container_width=True)

    # ── Drawdown chart ────────────────────────────────────────────────────────
    st.subheader("Drawdown from Peak")
    if not pnl_df.empty:
        fig2 = go.Figure()
        fig2.add_trace(
            go.Scatter(
                x=pnl_df.index,
                y=pnl_df["drawdown"] * 100,
                mode="lines",
                fill="tozeroy",
                name="Drawdown %",
                line=dict(color="#e63946", width=2),
                fillcolor="rgba(230,57,70,0.2)",
            )
        )
        fig2.add_hline(y=-10, line_dash="dash", line_color="#ff4560", annotation_text="10% halt",
                       annotation_font_color="#ff4560")
        fig2.update_layout(
            **_dark_layout(height=240),
            yaxis_title="Drawdown (%)",
            xaxis_title="Date",
            hovermode="x unified",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── Positions table ───────────────────────────────────────────────────────
    st.subheader("Current Positions")
    positions: dict = snapshot.get("positions", {})

    if not positions:
        st.info("No open positions.")
    else:
        symbols_tuple = tuple(positions.keys())
        prices = load_latest_prices(symbols_tuple)

        rows = []
        for sym, qty in sorted(positions.items(), key=lambda x: -abs(x[1])):
            price = prices.get(sym, 0.0)
            mkt_value = qty * price
            weight = mkt_value / total_value if total_value else 0.0
            rows.append(
                {
                    "Symbol": sym,
                    "Shares": qty,
                    "Price": f"${price:,.2f}",
                    "Market Value": f"${mkt_value:,.2f}",
                    "Weight": f"{weight:.1%}",
                }
            )

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Weights bar chart
        weight_fig = go.Figure(
            go.Bar(
                x=[r["Symbol"] for r in rows],
                y=[float(r["Weight"].strip("%")) for r in rows],
                marker_color="#00ff9d",
                marker_line_color="#00b4d8",
                marker_line_width=0.5,
                text=[r["Weight"] for r in rows],
                textposition="auto",
                textfont=dict(color="#08090c", size=10),
            )
        )
        weight_fig.update_layout(
            **_dark_layout(height=260),
            yaxis_title="Weight (%)",
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(weight_fig, use_container_width=True)

    st.divider()

    # ── Trade History ─────────────────────────────────────────────────────────
    st.subheader("Trade History")
    _render_trade_history(total_value)

    st.divider()

    # ── PnL history table ─────────────────────────────────────────────────────
    st.subheader("PnL History")
    if not pnl_df.empty:
        display = pnl_df.copy().reset_index()
        display.columns = ["Date", "Daily P&L", "Cumulative P&L", "Drawdown", "Total Value"]
        display["Daily P&L"] = display["Daily P&L"].map(lambda x: f"${x:+,.2f}")
        display["Cumulative P&L"] = display["Cumulative P&L"].map(lambda x: f"${x:+,.2f}")
        display["Drawdown"] = display["Drawdown"].map(lambda x: f"{x:.2%}")
        display["Total Value"] = display["Total Value"].map(lambda x: f"${x:,.2f}")
        st.dataframe(display.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)


def _render_trade_history(total_value: float) -> None:
    fills_df = load_fills()
    if fills_df.empty:
        st.info("No fills recorded yet.")
        return

    # Latest price per symbol across all filled symbols
    all_symbols = tuple(fills_df["symbol"].unique())
    current_prices = load_latest_prices(all_symbols)

    rows = []
    for _, row in fills_df.iterrows():
        sym = row["symbol"]
        side = row["side"].upper()
        qty = int(row["quantity"])
        fill_price = float(row["fill_price"])
        current_price = current_prices.get(sym, fill_price)

        # Treat sells as reducing cost basis — flip sign for unrealized calc
        signed_qty = qty if side == "BUY" else -qty
        market_value = signed_qty * current_price
        cost_basis = signed_qty * fill_price
        unrealized_pnl = market_value - cost_basis
        unrealized_pct = (current_price - fill_price) / fill_price if fill_price else 0.0
        if side == "SELL":
            unrealized_pct = -unrealized_pct  # sells gain when price falls

        rows.append(
            {
                "Date": row["filled_at"].strftime("%Y-%m-%d"),
                "Symbol": sym,
                "Side": side,
                "Shares": qty,
                "Fill Price": fill_price,
                "Current Price": current_price,
                "Market Value": market_value,
                "Unrealized P&L": unrealized_pnl,
                "Unrealized P&L %": unrealized_pct,
            }
        )

    if not rows:
        st.info("No fills recorded yet.")
        return

    trade_df = pd.DataFrame(rows)

    # ── Summary line ──────────────────────────────────────────────────────────
    total_upnl = trade_df["Unrealized P&L"].sum()
    best_idx = trade_df["Unrealized P&L %"].idxmax()
    worst_idx = trade_df["Unrealized P&L %"].idxmin()
    best_sym = trade_df.loc[best_idx, "Symbol"]
    best_pct = trade_df.loc[best_idx, "Unrealized P&L %"]
    worst_sym = trade_df.loc[worst_idx, "Symbol"]
    worst_pct = trade_df.loc[worst_idx, "Unrealized P&L %"]

    s1, s2, s3 = st.columns(3)
    s1.metric(
        "Total Unrealized P&L",
        f"${total_upnl:+,.2f}",
        delta=f"{total_upnl / total_value:.2%} of portfolio" if total_value else None,
    )
    s2.metric("Best Performer", best_sym, delta=f"{best_pct:+.2%}")
    s3.metric("Worst Performer", worst_sym, delta=f"{worst_pct:+.2%}", delta_color="inverse")

    # ── Colour-coded table via Styler ─────────────────────────────────────────
    display = trade_df.copy()
    display["Fill Price"] = display["Fill Price"].map(lambda x: f"${x:,.2f}")
    display["Current Price"] = display["Current Price"].map(lambda x: f"${x:,.2f}")
    display["Market Value"] = display["Market Value"].map(lambda x: f"${x:,.2f}")

    # Keep numeric columns for styling, format last
    pnl_col = display["Unrealized P&L"].copy()
    pct_col = display["Unrealized P&L %"].copy()
    display["Unrealized P&L"] = pnl_col.map(lambda x: f"${x:+,.2f}")
    display["Unrealized P&L %"] = pct_col.map(lambda x: f"{x:+.2%}")

    def _colour_pnl(val: str) -> str:
        try:
            numeric = float(val.replace("$", "").replace(",", "").replace("%", ""))
        except ValueError:
            return ""
        return "color: #2ecc71" if numeric >= 0 else "color: #e74c3c"

    styled = (
        display.style
        .applymap(_colour_pnl, subset=["Unrealized P&L", "Unrealized P&L %"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _compute_rolling_sharpe(pnl_df: pd.DataFrame, window: int = 63) -> float:
    import math
    import numpy as np

    if pnl_df.empty or len(pnl_df) < 5:
        return float("nan")
    values = pnl_df["total_value"].values
    window_vals = values[-(window + 1):]
    returns = pd.Series(window_vals).pct_change().dropna()
    if len(returns) < 4 or returns.std() == 0:
        return float("nan")
    daily_rf = 0.05 / 252
    excess = returns - daily_rf
    return float(excess.mean() / excess.std() * np.sqrt(252))
