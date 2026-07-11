"""Page 2 — Signals: today's top signals, full history, score distribution."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.data import load_signal_history


def render() -> None:
    st.title("Signals")

    df = load_signal_history()

    if df.empty:
        st.info("No signals recorded yet. Run `python run_pipeline.py` to generate signals.")
        return

    # ── Today's / most recent signals ─────────────────────────────────────────
    latest_date = df["date"].max()
    today_signals = df[df["date"] == latest_date].sort_values("score", ascending=False)

    st.subheader(f"Top Signals — {latest_date}")
    if today_signals.empty:
        st.info("No signals for the most recent date.")
    else:
        top = today_signals.head(5).copy()
        top["Score"]       = top["score"].map(lambda x: f"{x:.4f}")
        top["Confidence"]  = top["confidence"].map(lambda x: f"{x:.2%}")
        top["Exp. Return"] = top["expected_return"].map(
            lambda x: f"{x:.2%}" if x is not None else "n/a"
        )
        top["Rationale"]   = top["rationale"].fillna("")
        display_top = top[["symbol", "Score", "Confidence", "Exp. Return", "Rationale"]].rename(
            columns={"symbol": "Symbol"}
        )
        st.dataframe(display_top, use_container_width=True, hide_index=True)
        st.caption(f"{len(today_signals)} signals generated on {latest_date}")

    st.divider()

    # ── Score distribution ────────────────────────────────────────────────────
    st.subheader("Score Distribution")
    fig = px.histogram(
        df,
        x="score",
        nbins=40,
        color_discrete_sequence=["#00b4d8"],
        labels={"score": "Momentum Score"},
        height=280,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Full signal history ───────────────────────────────────────────────────
    st.subheader("Signal History")

    col_date, col_sym = st.columns(2)
    unique_dates = sorted(df["date"].unique(), reverse=True)
    unique_syms = sorted(df["symbol"].unique())

    selected_dates = col_date.multiselect(
        "Filter by date", unique_dates, default=[], placeholder="All dates"
    )
    selected_syms = col_sym.multiselect(
        "Filter by symbol", unique_syms, default=[], placeholder="All symbols"
    )

    filtered = df.copy()
    if selected_dates:
        filtered = filtered[filtered["date"].isin(selected_dates)]
    if selected_syms:
        filtered = filtered[filtered["symbol"].isin(selected_syms)]

    display = filtered[["date", "symbol", "direction", "score", "confidence", "expected_return"]].copy()
    display = display.rename(
        columns={
            "date": "Date",
            "symbol": "Symbol",
            "direction": "Direction",
            "score": "Score",
            "confidence": "Confidence",
            "expected_return": "Exp. Return",
        }
    )
    display["Score"] = display["Score"].map(lambda x: f"{x:.4f}")
    display["Confidence"] = display["Confidence"].map(lambda x: f"{x:.2%}")
    display["Exp. Return"] = display["Exp. Return"].map(
        lambda x: f"{x:.2%}" if x is not None else "n/a"
    )

    st.dataframe(
        display.sort_values(["Date", "Score"], ascending=[False, False]),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"{len(filtered)} signals shown")
