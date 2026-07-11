"""Cached data-access helpers for the dashboard.

Uses dashboard.db (standalone session) and raw SQL so that no module under
data/ is imported. This avoids the namespace conflict where Python resolves
'data' as the data/ directory package when Streamlit is the entry point.

All functions are read-only except log_experiment(), which writes one row to
the experiments table (required by architecture rule 7).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st
from sqlalchemy import text

from dashboard.db import get_session

STARTING_CAPITAL = 100_000.0
STRATEGY = "momentum"


# ── PnL ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_pnl_history(strategy: str = STRATEGY) -> pd.DataFrame:
    sql = text("""
        SELECT date, daily_pnl, cumulative_pnl, drawdown
        FROM pnl
        WHERE strategy = :strategy
        ORDER BY date
    """)
    with get_session() as s:
        rows = s.execute(sql, {"strategy": strategy}).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "daily_pnl", "cumulative_pnl", "drawdown"])
    df["total_value"] = STARTING_CAPITAL + df["cumulative_pnl"]
    df = df.set_index("date")
    # Guard against duplicate dates from double pipeline runs — keep latest row
    df = df[~df.index.duplicated(keep="last")]
    return df


# ── Portfolio snapshot ────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_latest_snapshot(strategy: str = STRATEGY) -> dict | None:
    sql = text("""
        SELECT snapshot_date, cash, gross_exposure, net_exposure, total_value, positions
        FROM portfolio_snapshots
        WHERE strategy = :strategy
        ORDER BY snapshot_date DESC
        LIMIT 1
    """)
    with get_session() as s:
        row = s.execute(sql, {"strategy": strategy}).fetchone()
    if row is None:
        return None
    positions = row.positions
    if isinstance(positions, str):
        positions = json.loads(positions)
    return {
        "snapshot_date": row.snapshot_date,
        "cash": row.cash,
        "gross_exposure": row.gross_exposure,
        "net_exposure": row.net_exposure,
        "total_value": row.total_value,
        "positions": positions or {},
    }


# ── Snapshot history ─────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_snapshot_history(strategy: str = STRATEGY) -> pd.DataFrame:
    """All portfolio snapshots ordered by date — cash + invested over time."""
    sql = text("""
        SELECT snapshot_date, cash, gross_exposure, total_value
        FROM portfolio_snapshots
        WHERE strategy = :strategy
        ORDER BY snapshot_date
    """)
    with get_session() as s:
        rows = s.execute(sql, {"strategy": strategy}).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "cash", "invested", "total_value"])
    return df.set_index("date")


# ── Prices ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_latest_prices(symbols: tuple[str, ...], as_of: date | None = None) -> dict[str, float]:
    as_of = as_of or date.today()
    if not symbols:
        return {}
    placeholders = ", ".join(f":sym{i}" for i in range(len(symbols)))
    sql = text(f"""
        SELECT pb.symbol, pb.adj_close
        FROM price_bars pb
        JOIN (
            SELECT symbol, MAX(date) AS max_date
            FROM price_bars
            WHERE symbol IN ({placeholders})
              AND date <= :as_of
            GROUP BY symbol
        ) latest ON pb.symbol = latest.symbol AND pb.date = latest.max_date
    """)
    params = {f"sym{i}": sym for i, sym in enumerate(symbols)}
    params["as_of"] = as_of
    with get_session() as s:
        rows = s.execute(sql, params).fetchall()
    return {r.symbol: r.adj_close for r in rows}


# ── Signals ───────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_signal_history(strategy: str = STRATEGY) -> pd.DataFrame:
    # DISTINCT ON deduplicates rows with the same (symbol, date) — keeps the
    # highest-score row per symbol per date. Handles duplicate rows caused by
    # running the pipeline more than once on the same day.
    sql = text("""
        SELECT DISTINCT ON (symbol, as_of_date)
               as_of_date AS date, symbol, direction, score, confidence,
               expected_return, rationale
        FROM signals
        WHERE strategy = :strategy
        ORDER BY symbol, as_of_date DESC, score DESC
    """)
    with get_session() as s:
        rows = s.execute(sql, {"strategy": strategy}).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        rows,
        columns=["date", "symbol", "direction", "score", "confidence", "expected_return", "rationale"],
    )


# ── Experiments ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_experiments() -> pd.DataFrame:
    sql = text("""
        SELECT experiment_id, strategy, hypothesis, sharpe, cagr, max_drawdown,
               start_date, end_date, params, notes, logged_at
        FROM experiments
        ORDER BY logged_at DESC
    """)
    with get_session() as s:
        rows = s.execute(sql).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        rows,
        columns=["id", "strategy", "hypothesis", "sharpe", "cagr", "max_drawdown",
                 "start", "end", "params", "notes", "logged_at"],
    )


def log_experiment(
    strategy: str,
    hypothesis: str,
    params: dict,
    result_summary: str,
    start_date: date,
    end_date: date,
    sharpe: float | None = None,
    cagr_val: float | None = None,
    max_drawdown_val: float | None = None,
    notes: str = "",
) -> str:
    """Insert one experiment row. Returns the experiment_id."""
    experiment_id = str(uuid.uuid4())[:8]
    sql = text("""
        INSERT INTO experiments
            (experiment_id, strategy, hypothesis, params, result_summary,
             start_date, end_date, sharpe, cagr, max_drawdown, notes, logged_at)
        VALUES
            (:experiment_id, :strategy, :hypothesis, :params, :result_summary,
             :start_date, :end_date, :sharpe, :cagr, :max_drawdown, :notes, :logged_at)
    """)
    with get_session() as s:
        s.execute(sql, {
            "experiment_id": experiment_id,
            "strategy": strategy,
            "hypothesis": hypothesis,
            "params": json.dumps(params),
            "result_summary": result_summary,
            "start_date": start_date,
            "end_date": end_date,
            "sharpe": sharpe,
            "cagr": cagr_val,
            "max_drawdown": max_drawdown_val,
            "notes": notes,
            "logged_at": datetime.utcnow(),
        })
        s.commit()
    load_experiments.clear()  # invalidate cache so table refreshes immediately
    return experiment_id


# ── Price bars (for Backtest Lab) ─────────────────────────────────────────────

# ── Fills ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_fills(strategy: str = STRATEGY) -> pd.DataFrame:
    """All fills for a strategy, joined to orders to filter by strategy."""
    sql = text("""
        SELECT
            f.filled_at,
            f.symbol,
            f.side,
            f.quantity,
            f.fill_price
        FROM fills f
        JOIN orders o ON f.order_id = o.order_id
        WHERE o.strategy = :strategy
        ORDER BY f.filled_at
    """)
    with get_session() as s:
        rows = s.execute(sql, {"strategy": strategy}).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["filled_at", "symbol", "side", "quantity", "fill_price"])
    df["filled_at"] = pd.to_datetime(df["filled_at"])
    return df


# ── Capital events (deposits / withdrawals) ───────────────────────────────────

@st.cache_data(ttl=30)
def load_capital_events() -> pd.DataFrame:
    """All capital deposits/withdrawals ordered by date."""
    sql = text("""
        SELECT id, event_date, amount, note
        FROM capital_events
        ORDER BY event_date
    """)
    with get_session() as s:
        rows = s.execute(sql).fetchall()
    if not rows:
        return pd.DataFrame(columns=["id", "date", "amount", "note"])
    df = pd.DataFrame(rows, columns=["id", "date", "amount", "note"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def add_capital_event(event_date: date, amount: float, note: str = "") -> None:
    """Insert one capital event and clear the cache."""
    sql = text("""
        INSERT INTO capital_events (event_date, amount, note, created_at)
        VALUES (:event_date, :amount, :note, :created_at)
    """)
    with get_session() as s:
        s.execute(sql, {
            "event_date": event_date,
            "amount": amount,
            "note": note,
            "created_at": datetime.utcnow(),
        })
        s.commit()
    load_capital_events.clear()


def delete_capital_event(event_id: int) -> None:
    sql = text("DELETE FROM capital_events WHERE id = :id")
    with get_session() as s:
        s.execute(sql, {"id": event_id})
        s.commit()
    load_capital_events.clear()


# ── Chart annotations ────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_chart_annotations() -> pd.DataFrame:
    """All equity-curve annotations ordered by date."""
    sql = text("""
        SELECT id, annotation_date, label, color
        FROM chart_annotations
        ORDER BY annotation_date
    """)
    with get_session() as s:
        rows = s.execute(sql).fetchall()
    if not rows:
        return pd.DataFrame(columns=["id", "date", "label", "color"])
    df = pd.DataFrame(rows, columns=["id", "date", "label", "color"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def add_chart_annotation(annotation_date: date, label: str, color: str = "orange") -> None:
    """Insert one annotation row and clear the cache."""
    sql = text("""
        INSERT INTO chart_annotations (annotation_date, label, color, created_at)
        VALUES (:annotation_date, :label, :color, :created_at)
    """)
    with get_session() as s:
        s.execute(sql, {
            "annotation_date": annotation_date,
            "label": label,
            "color": color,
            "created_at": datetime.utcnow(),
        })
        s.commit()
    load_chart_annotations.clear()


def delete_chart_annotation(annotation_id: int) -> None:
    """Delete an annotation by id and clear the cache."""
    sql = text("DELETE FROM chart_annotations WHERE id = :id")
    with get_session() as s:
        s.execute(sql, {"id": annotation_id})
        s.commit()
    load_chart_annotations.clear()


# ── Price bars (for Backtest Lab) ─────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_price_bars(symbols: tuple[str, ...]) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    placeholders = ", ".join(f":sym{i}" for i in range(len(symbols)))
    sql = text(f"""
        SELECT symbol, date, adj_close
        FROM price_bars
        WHERE symbol IN ({placeholders})
        ORDER BY date
    """)
    params = {f"sym{i}": sym for i, sym in enumerate(symbols)}
    with get_session() as s:
        rows = s.execute(sql, params).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["symbol", "date", "adj_close"])
    df["date"] = pd.to_datetime(df["date"])
    return df.pivot(index="date", columns="symbol", values="adj_close")
