"""Command Center — full-screen DAW-style scrubbing timeline.

Three live tracks: portfolio value / SPY / QQQ.
Playhead at current date. Scroll to zoom, drag to pan.
Floating metric strip + terminal feed overlaid.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, date as _date
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import text

from dashboard.db import get_session

_ROOT    = Path(__file__).resolve().parent.parent.parent
_ET      = ZoneInfo("America/New_York")
_REG_YAML = _ROOT / "registry" / "strategy_registry.yaml"
_MOM_YAML = _ROOT / "config" / "strategy_params" / "momentum.yaml"
_STARTING_CAPITAL = 100_000.0
_MONITOR_TARGET   = 20


# ── Alpaca order execution ──────────────────────────────────────────────────────

def _submit_alpaca_order(sym: str, side: str, notional: float, strategy: str = "user") -> None:
    """Submit a notional market order to Alpaca and write the fill to DB."""
    import os
    from config.settings import settings

    api_key    = settings.alpaca_api_key    or os.environ.get("ALPACA_API_KEY", "")
    secret_key = settings.alpaca_secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
    base_url   = settings.alpaca_base_url   or os.environ.get("ALPACA_BASE_URL",
                                                               "https://paper-api.alpaca.markets")
    if not api_key or not secret_key:
        return  # keys not configured — fail silently in UI

    try:
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        client = TradingClient(api_key=api_key, secret_key=secret_key,
                               paper="paper-api" in base_url)
        req = MarketOrderRequest(
            symbol=sym,
            notional=round(notional, 2),
            side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(req)

        # Write to DB so dashboard and pipeline pick it up
        with get_session() as db:
            db.execute(text("""
                INSERT INTO orders (strategy, symbol, side, quantity, order_type, status, created_at)
                VALUES (:strategy, :symbol, :side, :qty, 'market', 'filled', NOW())
            """), {
                "strategy": strategy,
                "symbol":   sym,
                "side":     side.lower(),
                "qty":      float(getattr(order, "filled_qty", 0) or 0),
            })
            db.commit()
    except Exception:
        pass  # order errors surface in the feed via optimistic tile; don't crash dashboard


# ── Terminal feed ───────────────────────────────────────────────────────────────

def _render_terminal() -> None:
    try:
        events: list[dict] = []
        with get_session() as s:
            fills = s.execute(text("""
                SELECT symbol, UPPER(side) as side, quantity,
                       ROUND(fill_price::numeric,2) as price, filled_at as ts
                FROM fills ORDER BY filled_at DESC LIMIT 10
            """)).fetchall()
            for r in fills:
                action = "bought" if r.side == "BUY" else "sold"
                events.append({"type": "fill", "sym": r.symbol,
                                "line1": f"{action} {r.quantity} shares",
                                "line2": f"filled at ${r.price}", "ts": r.ts})

            sigs = s.execute(text("""
                SELECT symbol, ROUND(score::numeric,3) as score, as_of_date::timestamp as ts
                FROM signals ORDER BY as_of_date DESC LIMIT 10
            """)).fetchall()
            for r in sigs:
                events.append({"type": "signal", "sym": r.symbol,
                                "line1": "flagged for entry",
                                "line2": f"momentum score {r.score}", "ts": r.ts})

            snaps = s.execute(text("""
                SELECT ROUND(total_value::numeric,0) as nav, snapshot_date::timestamp as ts
                FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 3
            """)).fetchall()
            for r in snaps:
                events.append({"type": "snapshot", "sym": "PORTFOLIO",
                                "line1": f"valued at ${int(r.nav):,}",
                                "line2": "end of day snapshot", "ts": r.ts})

        events.sort(key=lambda e: e["ts"] if e["ts"] else "", reverse=True)
        events = events[:20]

        css = {"fill": "ev-fill", "signal": "ev-signal", "snapshot": "ev-snapshot"}
        tag = {"fill": "TRADE", "signal": "SIGNAL", "snapshot": "UPDATE"}

        rows = ""
        for ev in events:  # newest first → column-reverse floats them to bottom
            ts = str(ev["ts"])[5:16] if ev["ts"] else ""
            rows += (
                f'<div class="bt-e">'
                f'<div class="bt-m {css.get(ev["type"],"")}"> '
                f'{tag.get(ev["type"],"EVT")}  {ev["sym"]}  —  {ev.get("line1","")}</div>'
                f'<div class="bt-s">{ts}  ·  {ev.get("line2","")}</div>'
                f'</div>'
            )

        term_html = f"""<!DOCTYPE html><html><head><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{height:100%;background:#040006;font-family:Consolas,'Courier New',monospace}}
#wrap{{height:100%;display:flex;flex-direction:column;border-top:2px solid #ff00cc}}
#hdr{{flex-shrink:0;padding:5px 16px;border-bottom:1px solid #2a003d;
      font-size:8px;letter-spacing:.22em;color:#ff00cc;
      text-shadow:0 0 8px rgba(255,0,204,.5);
      display:flex;align-items:center;gap:10px}}
.dot{{width:6px;height:6px;border-radius:50%;background:#ff00cc;
      box-shadow:0 0 6px #ff00cc;animation:bl 2s ease-in-out infinite}}
#body{{flex:1;overflow:visible;display:flex;flex-direction:column;padding:0}}
.bt-e{{padding:4px 18px 3px;border-top:1px solid rgba(42,0,61,.3);flex-shrink:0}}
.bt-m{{font-size:13px;font-weight:600;line-height:1.4;
       white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.bt-s{{font-size:9px;color:#3a1a4a;margin-top:1px;letter-spacing:.04em}}
.ev-fill{{color:#ff00cc}}.ev-signal{{color:#00e5ff}}.ev-snapshot{{color:#9400ff}}
#cur{{padding:4px 18px;flex-shrink:0;color:#ff00cc;animation:bl 1s step-start infinite}}
@keyframes bl{{0%,100%{{opacity:1}}50%{{opacity:0}}}}
</style></head><body>
<div id="wrap">
  <div id="hdr"><div class="dot"></div></div>
  <div id="body">
    <div id="cur">█</div>
    {rows}
  </div>
</div>
</body></html>"""

        components.html(term_html, height=240, scrolling=False)

    except Exception:
        pass


# ── Data loaders ───────────────────────────────────────────────────────────────

def _load_chart_data() -> dict:
    with get_session() as s:
        # Portfolio track — from portfolio_snapshots
        port_rows = s.execute(text("""
            SELECT snapshot_date::text as d, total_value
            FROM portfolio_snapshots
            ORDER BY snapshot_date
        """)).fetchall()

        # Fallback: reconstruct from pnl table
        if not port_rows:
            port_rows = s.execute(text("""
                SELECT date::text as d,
                       COALESCE(cumulative_pnl, 0) + :start as total_value
                FROM pnl WHERE strategy = 'momentum'
                ORDER BY date
            """), {"start": _STARTING_CAPITAL}).fetchall()

        port_dates  = [r.d              for r in port_rows]
        port_values = [float(r.total_value) for r in port_rows]

        # Intraday marks — "marked the book at $X" pipeline events (dense price history)
        mark_rows = s.execute(text("""
            SELECT recorded_at, message FROM pipeline_events
            WHERE message ILIKE '%marked the book at%'
            ORDER BY recorded_at DESC LIMIT 500
        """)).fetchall()
        mark_ts, mark_vals = [], []
        import re as _re
        for r in reversed(mark_rows):
            m = _re.search(r'\$([\d,]+\.?\d*)', r.message)
            if m:
                mark_ts.append(r.recorded_at.isoformat())
                mark_vals.append(float(m.group(1).replace(',', '')))

        # Benchmark tracks — SPY / QQQ
        start_cutoff = port_dates[0] if port_dates else "2026-01-01"
        bench_rows = s.execute(text("""
            SELECT symbol, date::text as d, close
            FROM price_bars
            WHERE symbol IN ('SPY','QQQ')
              AND date >= :cut
            ORDER BY symbol, date
        """), {"cut": start_cutoff}).fetchall()

        spy_dates  = [r.d    for r in bench_rows if r.symbol == "SPY"]
        spy_prices = [float(r.close) for r in bench_rows if r.symbol == "SPY"]
        qqq_dates  = [r.d    for r in bench_rows if r.symbol == "QQQ"]
        qqq_prices = [float(r.close) for r in bench_rows if r.symbol == "QQQ"]

        # Nav snapshots — last 6h, seeded into JS so chart renders immediately on load
        nav_snap_rows = s.execute(text("""
            SELECT recorded_at, nav FROM nav_snapshots
            WHERE recorded_at >= NOW() - INTERVAL '6 hours'
            ORDER BY recorded_at ASC
            LIMIT 2000
        """)).fetchall()
        nav_snap_pts = [
            {"t": r.recorded_at.isoformat() + "Z", "v": float(r.nav)}
            for r in nav_snap_rows
        ]

        # Status scalars
        mon_days = s.execute(text(
            "SELECT COUNT(DISTINCT date) FROM pnl WHERE strategy='momentum'"
        )).scalar() or 0
        last_run = s.execute(text("SELECT MAX(date) FROM price_bars")).scalar()

        best = s.execute(text("""
            SELECT sharpe, cagr, max_drawdown
            FROM experiments
            WHERE strategy='momentum' AND sharpe IS NOT NULL
            ORDER BY sharpe DESC LIMIT 1
        """)).fetchone()

        latest_pnl = s.execute(text("""
            SELECT daily_pnl, cumulative_pnl
            FROM pnl WHERE strategy='momentum'
            ORDER BY date DESC LIMIT 1
        """)).fetchone()

    # Terminal feed events
    with get_session() as s:
        term_events: list[dict] = []

        # Primary source: structured pipeline_events (logged since pipeline_events table was added)
        _EVENT_MAP = {
            "START":      ("ev-pipeline", "RUN"),
            "COMPLETE":   ("ev-pipeline", "RUN"),
            "INGEST":     ("ev-pipeline", "DATA"),
            "FETCH":      ("ev-pipeline", "FETCH"),
            "INTRADAY":   ("ev-pipeline", "INTRADAY"),
            "SIGNAL":     ("ev-signal",   "SIGNAL"),
            "ENTRY":      ("ev-fill",     "BUY"),
            "EXIT":       ("ev-fill",     "SELL"),
            "HOLD":       ("ev-snapshot", "HOLD"),
            "SNAPSHOT":   ("ev-snapshot", "NAV"),
            "PNL":        ("ev-pipeline", "PNL"),
            "RISK_VETO":  ("ev-fill",     "VETO"),
            "UPDATE":       ("ev-signal",   "UPDATE"),
            "MARKET_OPEN":    ("ev-signal",   "MARKET_OPEN"),
            "MARKET_CLOSE":   ("ev-pipeline", "MARKET_CLOSE"),
            "OPEN_PRICE":      ("ev-fill",     "OPEN_PRICE"),
            "GAP_ALERT":       ("ev-fill",     "GAP_ALERT"),
            "OPEN_SNAPSHOT":   ("ev-snapshot", "OPEN_SNAPSHOT"),
            "CLOSE_INGEST":    ("ev-pipeline", "CLOSE_INGEST"),
            "SIGNAL_PREVIEW":  ("ev-signal",   "SIGNAL_PREVIEW"),
            "RANK_CHANGE":     ("ev-signal",   "RANK_CHANGE"),
            "ACTION_PREVIEW":  ("ev-snapshot", "ACTION_PREVIEW"),
            "TRADE":           ("ev-fill",     "TRADE"),
        }
        try:
            pipe_rows = s.execute(text("""
                SELECT event_type, symbol, message, detail, recorded_at as ts
                FROM pipeline_events
                WHERE event_type != 'UPDATE'
                ORDER BY recorded_at DESC LIMIT 500
            """)).fetchall()
            _ev_seen = set()
            for r in pipe_rows:
                _dedup_key = (r.event_type, r.symbol or "", (r.message or "")[:80])
                if _dedup_key in _ev_seen:
                    continue
                _ev_seen.add(_dedup_key)
                cls, tag = _EVENT_MAP.get(r.event_type, ("ev-pipeline", r.event_type))
                term_events.append({
                    "cls": cls, "tag": tag,
                    "sym": r.symbol or r.event_type,
                    "line1": r.message,
                    "line2": r.detail or "",
                    "ts": r.ts,
                })
        except Exception:
            pass  # table doesn't exist yet — falls back to legacy sources below

        # Legacy fallback: fills and snapshots predating pipeline_events table
        _have_dates = {str(e["ts"])[:10] for e in term_events}
        fills = s.execute(text("""
            SELECT symbol, UPPER(side) as side, quantity,
                   ROUND(fill_price::numeric,2) as price, filled_at as ts
            FROM fills ORDER BY filled_at DESC LIMIT 60
        """)).fetchall()
        for r in fills:
            if str(r.ts)[:10] not in _have_dates:
                action = "bought" if r.side == "BUY" else "sold"
                term_events.append({"cls":"ev-fill","sym":r.symbol,
                    "line1":f"{action} {r.quantity} shares","line2":f"filled at ${r.price}","ts":r.ts,"tag":"TRADE"})
        snaps = s.execute(text("""
            SELECT ROUND(total_value::numeric,0) as nav, snapshot_date::timestamp as ts
            FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 30
        """)).fetchall()
        for r in snaps:
            if str(r.ts)[:10] not in _have_dates:
                term_events.append({"cls":"ev-snapshot","sym":"PORTFOLIO",
                    "line1":f"valued at ${int(r.nav):,}","line2":"end of day snapshot","ts":r.ts,"tag":"NAV"})

    term_events.sort(key=lambda e: e["ts"] if e["ts"] else "", reverse=True)  # newest first → newest at top
    term_events = term_events[:200]
    # Newest event timestamp — passed to JS so the live poller skips re-inserting already-rendered history
    _newest_ev_ts = str(term_events[0]["ts"]) if term_events else ""

    # Next trading day (for plain-English position subtext)
    from datetime import timedelta as _td
    try:
        import pandas_market_calendars as _mcal
        _nyse = _mcal.get_calendar("NYSE")
        _today = __import__("datetime").date.today()
        _sched = _nyse.schedule(
            start_date=_today + _td(days=1),
            end_date=_today + _td(days=10),
        )
        _next_td = _sched.index[0].date() if len(_sched) else _today + _td(days=1)
        _next_td_str = f"{_next_td.month}/{_next_td.day}"
    except Exception:
        _next_td_str = "next close"
        _next_td = __import__("datetime").date.today() + _td(days=1)

    # Positions panel data
    positions_data: list[dict] = []
    _pos_map_outer: dict = {}
    _predicted_entries: list[str] = []
    with get_session() as s:
        snap = s.execute(text("""
            SELECT positions FROM portfolio_snapshots
            WHERE strategy = 'momentum'
            ORDER BY snapshot_date DESC LIMIT 1
        """)).fetchone()
        if snap and snap.positions:
            pos_map: dict = snap.positions  # {symbol: qty}
            syms = list(pos_map.keys())
            if syms:
                # Latest prices
                price_rows = s.execute(text("""
                    SELECT DISTINCT ON (symbol) symbol, adj_close, date
                    FROM price_bars
                    WHERE symbol = ANY(:syms)
                    ORDER BY symbol, date DESC
                """), {"syms": syms}).fetchall()
                prices_map = {r.symbol: float(r.adj_close) for r in price_rows}

                # Entry fills — earliest BUY per symbol (full timestamp preserved)
                entry_rows = s.execute(text("""
                    SELECT DISTINCT ON (symbol) symbol, fill_price, filled_at,
                                                filled_at::date as entry_date
                    FROM fills WHERE side = 'BUY' AND symbol = ANY(:syms)
                    ORDER BY symbol, filled_at ASC
                """), {"syms": syms}).fetchall()
                entry_map = {
                    r.symbol: {
                        "price": float(r.fill_price),
                        "date": str(r.entry_date),
                        "filled_at": r.filled_at.isoformat() if r.filled_at else None,
                    }
                    for r in entry_rows
                }

                # Latest signals to get score + rank for each symbol
                sig_rows = s.execute(text("""
                    SELECT symbol, score, as_of_date
                    FROM signals
                    WHERE as_of_date = (SELECT MAX(as_of_date) FROM signals)
                    ORDER BY score DESC
                """)).fetchall()
                sig_map = {r.symbol: {"score": float(r.score), "rank": i+1}
                           for i, r in enumerate(sig_rows)}

                # Predicted entries: top-5 signals not currently held
                _pos_map_outer = pos_map
                _predicted_entries = [r.symbol for r in sig_rows[:5] if r.symbol not in pos_map]

                for sym, qty in pos_map.items():
                    price = prices_map.get(sym, 0.0)
                    value = qty * price
                    sig  = sig_map.get(sym)
                    entry = entry_map.get(sym, {})
                    entry_price = entry.get("price", 0.0)
                    entry_date  = entry.get("date", "—")
                    entry_cost  = qty * entry_price if entry_price else 0.0
                    entry_pnl   = value - entry_cost if entry_cost else 0.0
                    entry_pnl_pct = (entry_pnl / entry_cost * 100) if entry_cost else 0.0

                    rank = sig["rank"] if sig else None
                    if sig:
                        hold_text = f"ranked #{rank} · stays in until it drops out of top 5"
                    else:
                        hold_text = f"fell out of top 5 · the blob sells this at {_next_td_str} close"

                    # Days held
                    from datetime import date as _date_cls
                    try:
                        _entry_d = _date_cls.fromisoformat(str(entry_date))
                        days_held = (_date_cls.today() - _entry_d).days
                    except Exception:
                        days_held = 0

                    # Stop / target for proximity bar
                    stop_price   = entry_price * 0.95 if entry_price else 0
                    target_price = entry_price * 1.10 if entry_price else 0

                    positions_data.append({
                        "sym": sym, "qty": qty, "price": price,
                        "value": value, "hold_text": hold_text,
                        "in_signal": bool(sig), "rank": rank,
                        "entry_price": entry_price,
                        "entry_date": entry_date,
                        "entry_filled_at": entry.get("filled_at"),
                        "entry_cost": entry_cost,
                        "entry_pnl": entry_pnl,
                        "entry_pnl_pct": entry_pnl_pct,
                        "days_held": days_held,
                        "stop_price": stop_price,
                        "target_price": target_price,
                    })
                positions_data.sort(key=lambda x: -x["value"])

    # Queued actions panel — computed from known schedule + current positions
    from datetime import datetime as _dtt, time as _time_cls
    _now_et     = _dtt.now(_ET)
    _today_et   = _now_et.date()
    _pipeline_dt = _dtt.combine(_next_td, _time_cls(16, 5), tzinfo=_ET)
    _pipeline_ms = int(_pipeline_dt.timestamp() * 1000)
    _open_dt  = _dtt.combine(_today_et, _time_cls(9, 30),  tzinfo=_ET)
    _close_dt = _dtt.combine(_today_et, _time_cls(16, 0),  tzinfo=_ET)
    if _now_et >= _close_dt:
        _open_dt  = _dtt.combine(_next_td, _time_cls(9, 30),  tzinfo=_ET)
        _close_dt = _dtt.combine(_next_td, _time_cls(16, 0),  tzinfo=_ET)
    _open_ms  = int(_open_dt.timestamp() * 1000)
    _close_ms = int(_close_dt.timestamp() * 1000)
    _market_open = _open_dt <= _now_et < _close_dt

    # Which event types already fired today → filter them out of the queue
    _done_today: set[str] = set()
    try:
        with get_session() as s:
            _done_rows = s.execute(text("""
                SELECT DISTINCT event_type FROM pipeline_events
                WHERE run_date = :today
            """), {"today": _today_et}).fetchall()
            _done_today = {r.event_type for r in _done_rows}
    except Exception:
        pass

    def _q(badge, label, detail, target_ms, color, done_key):
        if done_key in _done_today:
            return None
        return {"badge": badge, "label": label, "detail": detail,
                "target_ms": target_ms, "color": color}

    # Full day sequence — items filter themselves out as they execute
    _seq = [
        # ── Morning ──────────────────────────────────────────────────────
        _q("OPEN",    "market opens",          "NYSE  9:30am ET",
           _open_ms,               "#00e5ff", "MARKET_OPEN"),
        _q("PRICE",   "price all positions",   "gap analysis vs prev close",
           _open_ms + 90_000,      "#00e5ff", "OPEN_PRICE"),
        _q("PREVIEW", "score the universe",    "rank top-5  ·  predict today's moves",
           _open_ms + 180_000,     "#9400ff", "SIGNAL_PREVIEW"),
        _q("PLAN",    "preview today's trades","expected entries  ·  exits  ·  holds",
           _open_ms + 240_000,     "#9400ff", "ACTION_PREVIEW"),
        # ── Close ────────────────────────────────────────────────────────
        _q("CLOSE",   "market closes",         "NYSE  4:00pm ET",
           _close_ms,              "#6a3a8a", "MARKET_CLOSE"),
        _q("INGEST",  "pre-ingest data",       f"97 symbols  ·  feeds 4:05 pipeline",
           _close_ms + 120_000,    "#9400ff", "CLOSE_INGEST"),
        # ── Pipeline ─────────────────────────────────────────────────────
        _q("RUN",     "daily pipeline",        "signal → rebalance → snapshot → PnL",
           _pipeline_ms,           "#ff00cc", "START"),
        _q("DONE",    "pipeline complete",     "book marked  ·  performance logged",
           _pipeline_ms + 180_000, "#ff00cc", "COMPLETE"),
    ]
    queued_actions: list[dict] = [q for q in _seq if q is not None]

    # Position-level actions — sourced from morning ACTION_PREVIEW when available,
    # otherwise derived from live signal/position diff at render time.
    _action_exits: list[str] = []
    _action_entries: list[str] = []
    _action_holds: list[str] = []
    _from_preview = False

    if "COMPLETE" not in _done_today:
        # Try to read morning signal preview results from pipeline_events
        try:
            with get_session() as _qs:
                _ap_rows = _qs.execute(text("""
                    SELECT message FROM pipeline_events
                    WHERE run_date = :today AND event_type = 'ACTION_PREVIEW'
                    ORDER BY created_at ASC
                """), {"today": _today_et}).fetchall()
            for _ap in _ap_rows:
                _msg = (_ap.message or "").strip()
                if _msg.startswith("expected exits at close:"):
                    _action_exits = [x.strip() for x in _msg.split(":", 1)[1].split(",") if x.strip()]
                    _from_preview = True
                elif _msg.startswith("expected entries at close:"):
                    _action_entries = [x.strip() for x in _msg.split(":", 1)[1].split(",") if x.strip()]
                    _from_preview = True
                elif _msg.startswith("holding:"):
                    _action_holds = [x.strip() for x in _msg.split(":", 1)[1].split(",") if x.strip()]
                    _from_preview = True
        except Exception:
            pass

        # Fall back: derive from live positions vs latest signal scores
        if not _from_preview:
            _action_exits   = [p["sym"] for p in positions_data if not p["in_signal"]]
            _action_holds   = [p["sym"] for p in positions_data if p["in_signal"]]
            _action_entries = _predicted_entries

        _src = "preview confirmed" if _from_preview else "fell out of top-5"
        _src_e = "preview confirmed" if _from_preview else "entering top-5"

        for _sym in _action_exits:
            queued_actions.append({"badge": "EXIT", "label": _sym,
                "detail": f"exits at {_next_td_str} close  ·  {_src}",
                "target_ms": _pipeline_ms, "color": "#ff9900"})
        for _sym in _action_entries:
            queued_actions.append({"badge": "ENTRY", "label": _sym,
                "detail": f"enters at {_next_td_str} close  ·  {_src_e}",
                "target_ms": _pipeline_ms, "color": "#00ff9d"})
        if _action_holds:
            queued_actions.append({"badge": "HOLD", "label": "  ·  ".join(_action_holds),
                "detail": "continuing  ·  still ranked top 5",
                "target_ms": _pipeline_ms, "color": "#40c4ff"})

    return {
        "portfolio":   {"dates": port_dates,  "values": port_values},
        "marks":       {"ts": mark_ts,        "vals": mark_vals},
        "spy":         {"dates": spy_dates,   "prices": spy_prices},
        "qqq":         {"dates": qqq_dates,   "prices": qqq_prices},
        "monitoring_days": int(mon_days),
        "last_run":    str(last_run) if last_run else "—",
        "sharpe":      float(best.sharpe)       if best and best.sharpe       else None,
        "cagr":        float(best.cagr)         if best and best.cagr         else None,
        "max_drawdown":float(best.max_drawdown) if best and best.max_drawdown else None,
        "day_pnl":        float(latest_pnl.daily_pnl)      if latest_pnl else 0.0,
        "cumulative_pnl": float(latest_pnl.cumulative_pnl) if latest_pnl else 0.0,
        "rolling_sharpe": None,
        "term_events": term_events,
        "newest_ev_ts": _newest_ev_ts,
        "positions_data": positions_data,
        "queued_actions": queued_actions,
        "nav_snap_pts": nav_snap_pts,
    }


def _read_strategy_status() -> str:
    try:
        reg = yaml.safe_load(_REG_YAML.read_text())
        for s in reg.get("strategies", []):
            if s.get("name") == "momentum":
                return s.get("status", "unknown").upper()
    except Exception:
        pass
    return "PAPER"


# ── HTML builder ───────────────────────────────────────────────────────────────

def _build_daw_html(data: dict) -> str:
    import json as _json
    from config.universe import TRADING_SYMBOLS
    import yaml as _yaml

    # All known tickers for the buy console dropdown
    _crypto_syms = []
    try:
        _crypto_cfg = _yaml.safe_load((_ROOT / "strategies" / "crypto" / "config.yaml").read_text())
        _crypto_syms = _crypto_cfg.get("universe", [])
    except Exception:
        _crypto_syms = ["BTC/USD", "ETH/USD", "SOL/USD"]
    _all_tickers_j = _json.dumps({
        "equity": sorted(TRADING_SYMBOLS),
        "crypto": _crypto_syms,
    })

    port  = data["portfolio"]
    marks = data.get("marks", {"ts": [], "vals": []})
    mark_ts   = marks["ts"]
    mark_vals = marks["vals"]
    spy   = data["spy"]
    qqq   = data["qqq"]
    mon   = data["monitoring_days"]
    sharpe = f'{data["rolling_sharpe"]:.2f}' if data.get("rolling_sharpe") else "—"
    last_nav  = port["values"][-1]     if port["values"] else _STARTING_CAPITAL
    return_pct = (last_nav - _STARTING_CAPITAL) / _STARTING_CAPITAL
    ret_str    = f'{return_pct*100:+.2f}%'
    ret_color  = "#00ff9d" if return_pct >= 0 else "#ff3366"
    nav_str    = f'${last_nav:,.0f}'
    spy_latest = f'${spy["prices"][-1]:.2f}'  if spy["prices"]  else "—"
    qqq_latest = f'${qqq["prices"][-1]:.2f}'  if qqq["prices"]  else "—"
    status     = _read_strategy_status()
    last_run   = data["last_run"][:10] if data["last_run"] else "—"
    day_pnl      = data["day_pnl"]
    dpnl_str     = f'{day_pnl:+,.0f}'
    n_positions  = len(data.get("positions_data", []))

    # ── Terminal feed rows ────────────────────────────────────────────────────
    import re as _re
    from datetime import datetime as _dt

    # Canonical cyberpunk ticker palette — no greens, no reds (those are PnL colors).
    # JS side uses the same palette + same djb2-style hash so colors match everywhere.
    _TICKER_PALETTE = ["#00e5ff","#cc00ff","#ff9900","#e040fb","#40c4ff","#ff6b35","#00ffcc","#f7b731","#7c4dff","#18ffff"]
    # Manual overrides for tickers whose hash collides with another open position.
    # Must be kept in sync with _TICKER_OVERRIDES_JS below.
    _TICKER_OVERRIDES = {
        "ETH": "#e040fb",   # electric magenta
        "CRV": "#f7b731",   # amber
        "XTZ": "#00bfff",   # electric sky blue
        "NUE": "#ff4dd2",   # neon rose
    }
    _SYSTEM_SYMS = {"PIPELINE", "PORTFOLIO", "RUN", "INGEST", "SIGNAL", "HOLD",
                    "SNAPSHOT", "PNL", "NAV", "UPDATE", "DATA", "START", "COMPLETE", "VETO"}

    def _tc(sym: str) -> str:
        if not sym or sym.upper() in _SYSTEM_SYMS:
            return "#f0e0ff"
        s = sym.replace("/USD", "").replace("USD", "")
        if s in _TICKER_OVERRIDES:
            return _TICKER_OVERRIDES[s]
        h = 0
        for c in s:
            h = (h * 31 + ord(c)) & 0xffff
        return _TICKER_PALETTE[h % len(_TICKER_PALETTE)]

    def _ts(sym: str) -> str:
        """Wrap a ticker symbol in its color span. data-sym enables popup on click."""
        return f'<span data-sym="{sym}" style="color:{_tc(sym)};font-weight:700;cursor:pointer">{sym}</span>'

    def _humanize(ev: dict, nav_col: str | None) -> str:
        """Convert a pipeline event into natural inner-monologue prose."""
        tag  = ev.get("tag", "")
        sym  = ev.get("sym", "")
        msg  = ev.get("line1", "")
        det  = ev.get("line2", "")

        # Parse numbers we'll reuse
        dollar_m = _re.search(r'\$([\d,]+(?:\.\d+)?)', msg)
        num_m    = _re.search(r'(\d[\d,]*)', msg)

        if tag in ("START", "RUN") and "started" in msg:
            d = msg.split("for ")[-1] if "for " in msg else msg
            return f'<span style="color:#5a3a7a">waking up for {d}</span>'

        if tag in ("RUN", "COMPLETE") and "complete" in msg:
            nav = _re.search(r'\$([\d,]+)', msg)
            nav_s = f'<span style="color:{nav_col or "#f0e0ff"}">${nav.group(1)}</span>' if nav else ""
            return f'all done. book closed at {nav_s}'

        if tag == "DATA":
            bars_m = _re.search(r'(\d+) bars', msg)
            sym_m  = _re.search(r'(\d+) symbols', msg)
            bars = bars_m.group(1) if bars_m else "?"
            syms = sym_m.group(1) if sym_m else "?"
            return f'<span style="color:#5a3a7a">pulled {bars} bars across {syms} symbols. clean.</span>'

        if tag == "FETCH":
            bars_m = _re.search(r'(\d+) bars', msg)
            count = bars_m.group(1) if bars_m else "0"
            return f'<span style="color:#1e0c30">{_ts(sym)} &nbsp;{count} bars</span>'

        if tag == "INTRADAY":
            bars_m = _re.search(r'([\d,]+) 1m bars', msg)
            sym_m  = _re.search(r'(\d+) symbols', msg)
            bars = bars_m.group(1) if bars_m else "?"
            syms = sym_m.group(1) if sym_m else "?"
            return f'<span style="color:#3a2a5a">cached {bars} intraday 1m bars across {syms} symbols</span>'

        if tag == "SIGNAL":
            # "universe scored · top pick: GOOGL (0.823)"
            pick_m = _re.search(r'top pick[:\s]+(\w+)[^\d]*([\d.]+)', msg)
            if pick_m:
                ticker, score = pick_m.group(1), pick_m.group(2)
                return f'scored the universe. {_ts(ticker)} leads at {score}'
            return f'<span style="color:#5a3a7a">{msg}</span>'

        if tag == "BUY":
            qty_m   = _re.search(r'(\d+) shares', msg)
            price_m = _re.search(r'\$([\d.]+)', msg)
            qty   = qty_m.group(1)   if qty_m   else "?"
            price = price_m.group(1) if price_m else "?"
            slip_m = _re.search(r'slippage \$([\d.]+)', det)
            slip_s = f' &nbsp;<span style="color:#3a1a4a">slip ${slip_m.group(1)}</span>' if slip_m else ""
            return f'<span style="color:#00ff9d">bought</span> {qty} shares of {_ts(sym)} @ ${price}{slip_s}'

        if tag == "SELL":
            qty_m   = _re.search(r'(\d+) shares', msg)
            price_m = _re.search(r'\$([\d.]+)', msg)
            qty   = qty_m.group(1)   if qty_m   else "?"
            price = price_m.group(1) if price_m else "?"
            return f'<span style="color:#ff9900">sold</span> {qty} shares of {_ts(sym)} @ ${price}'

        if tag == "HOLD":
            # "holding AAPL, MSFT, GOOGL, NVDA, AMZN unchanged"
            tickers_raw = _re.sub(r'\s*unchanged.*', '', msg.replace("holding ", ""))
            tickers = [t.strip().rstrip(",") for t in tickers_raw.split(",") if t.strip()]
            colored = "  ".join(_ts(t) for t in tickers)
            return f'holding  {colored}'

        if tag in ("NAV", "UPDATE", "SNAPSHOT"):
            val_m = _re.search(r'\$([\d,]+)', msg)
            if val_m:
                val_s = f'<span style="color:{nav_col or "#f0e0ff"}">${val_m.group(1)}</span>'
                return f'marked the book at {val_s}'
            return msg

        if tag == "PNL":
            dpnl_m = _re.search(r'([+-]\$[\d,]+(?:\.\d+)?)', msg)
            cpnl_m = _re.search(r'([+-]\$[\d,]+(?:\.\d+)?)', det) if det else None
            dpnl_s = dpnl_m.group(1) if dpnl_m else msg
            sign   = dpnl_s[0] if dpnl_s else "+"
            dcol   = "#00ff9d" if sign == "+" else "#ff3366"
            dpnl_colored = f'<span style="color:{dcol}">{dpnl_s}</span>'
            cpnl_s = f'  <span style="color:#3a1a4a">({cpnl_m.group(1)} total)</span>' if cpnl_m else ""
            return f'{dpnl_colored} on the day{cpnl_s}'

        if tag == "RISK_VETO":
            return f'<span style="color:#ff3366">blocked</span> {_ts(sym)}  —  {msg}'

        if tag == "UPDATE":
            return f'<span style="color:#00e5ff">↑ deployed</span>  <span style="color:#7a5a9a">{msg}</span>'

        if tag == "MARKET_OPEN":
            return f'<span style="color:#00e5ff">market open</span>  <span style="color:#3a2a5a">NYSE  9:30am ET  ·  pricing positions</span>'

        if tag == "MARKET_CLOSE":
            return f'<span style="color:#4a2a6a">market closed</span>  <span style="color:#2a1a3a">NYSE  4:00pm ET  ·  pipeline incoming</span>'

        if tag == "OPEN_PRICE":
            price_m = _re.search(r'\$([\d.]+)', msg)
            gap_m   = _re.search(r'([+-][\d.]+%)', msg)
            price_s = f'${price_m.group(1)}' if price_m else "?"
            gap_s   = gap_m.group(1) if gap_m else ""
            gap_col = "#00ff9d" if gap_s.startswith("+") else "#ff9900" if gap_s else "#9060b8"
            gap_fmt = f'  <span style="color:{gap_col}">{gap_s}</span>' if gap_s else ""
            return f'{_ts(sym)}  opened {price_s}{gap_fmt}'

        if tag == "GAP_ALERT":
            gap_m = _re.search(r'([+-][\d.]+%)', msg)
            gap_s = gap_m.group(1) if gap_m else msg
            gap_col = "#00ff9d" if gap_s.startswith("+") else "#ff3366"
            return (f'<span style="color:#ff3366">gap alert</span>  {_ts(sym)}  '
                    f'<span style="color:{gap_col}">{gap_s}</span>  overnight')

        if tag == "OPEN_SNAPSHOT":
            val_m = _re.search(r'\$([\d,]+)', msg)
            val_s = f'<span style="color:#9060b8">${val_m.group(1)}</span>' if val_m else ""
            return f'portfolio est. {val_s} at open'

        if tag == "CLOSE_INGEST":
            bars_m = _re.search(r'(\d+) bars', msg)
            sym_m  = _re.search(r'(\d+) symbols', msg)
            bars = bars_m.group(1) if bars_m else "?"
            syms = sym_m.group(1) if sym_m else "?"
            return f'<span style="color:#3a2a5a">pre-loaded {bars} bars across {syms} symbols  ·  pipeline ready</span>'

        if tag == "SIGNAL_PREVIEW":
            # "morning preview  ·  #1 NVDA  #2 AAPL ..."
            picks = _re.findall(r'#\d+\s+(\w+)', msg)
            colored = "  ".join(f'<span style="color:#5a3a7a">#{i+1}</span> {_ts(p)}' for i, p in enumerate(picks))
            return f'<span style="color:#5a3a7a">morning preview  ·</span>  {colored}' if colored else f'<span style="color:#5a3a7a">{msg}</span>'

        if tag == "RANK_CHANGE":
            entered = "entered" in msg
            col = "#00e5ff" if entered else "#ff9900"
            verb = "↑ entered top-5" if entered else "↓ dropped from top-5"
            return f'<span style="color:{col}">{verb}</span>  {_ts(sym)}'

        if tag == "ACTION_PREVIEW":
            if "entries" in msg:
                tickers = _re.sub(r'expected entries at close:\s*', '', msg)
                colored = "  ".join(_ts(t.strip()) for t in tickers.split(",") if t.strip())
                return f'<span style="color:#5a3a7a">expected entries at close  ·</span>  {colored}'
            if "exits" in msg:
                tickers = _re.sub(r'expected exits at close:\s*', '', msg)
                colored = "  ".join(_ts(t.strip()) for t in tickers.split(",") if t.strip())
                return f'<span style="color:#5a3a7a">expected exits at close  ·</span>  {colored}'
            if "holding" in msg:
                tickers = _re.sub(r'holding:\s*', '', msg)
                colored = "  ".join(_ts(t.strip()) for t in tickers.split(",") if t.strip())
                return f'<span style="color:#2a1a3a">holding  {colored}</span>'
            return f'<span style="color:#5a3a7a">{msg}</span>'

        if tag == "TRADE":
            # Crypto runner format: "▲ ENTER long BTC/USD @ $99999 · stop $99499"
            if "ENTER" in msg or "EXIT" in msg:
                is_entry = "ENTER" in msg
                verb_col = "#00ff9d" if is_entry else "#ff9900"
                verb = "enter" if is_entry else "exit"
                price_m = _re.search(r'@\s*\$([\d,]+(?:\.\d+)?)', msg)
                price_s = f'@ ${price_m.group(1)}' if price_m else ""
                pnl_m = _re.search(r'pnl\s*([+-][\d,.]+)', msg)
                pnl_s = f' · pnl <span style="color:{"#00ff9d" if pnl_m and pnl_m.group(1).startswith("+") else "#ff4444"}">{pnl_m.group(1)}</span>' if pnl_m else ""
                return f'<span style="color:{verb_col}">{verb}</span> {_ts(sym)} {price_s}{pnl_s}'
            # Equity format: "bought/sold N shares"
            verb = "bought" if "bought" in msg else "sold"
            verb_col = "#00ff9d" if verb == "bought" else "#ff9900"
            qty_m = _re.search(r'(\d+)\s+shares', msg)
            qty = qty_m.group(1) if qty_m else "?"
            return f'<span style="color:{verb_col}">{verb}</span> {qty} shares {_ts(sym)}'

        # fallback
        return f'<span style="color:#5a3a7a">{msg}</span>'

    _term_evs      = data.get("term_events", [])
    _last_ev_i     = 0
    _newest_ev_ts_js = data.get("newest_ev_ts", "").replace("+00:00", "Z").replace(" ", "T")

    # Collect NAV values oldest-first for up/down coloring
    _snap_vals: list[float] = []
    for ev in _term_evs:
        if ev["tag"] in ("NAV", "UPDATE", "SNAPSHOT"):
            _m = _re.search(r'\$([\d,]+)', ev.get("line1",""))
            if _m:
                _snap_vals.append(float(_m.group(1).replace(",","")))

    term_rows = ""
    _last_date = None
    _snap_idx  = 0

    for _ev_i, ev in enumerate(_term_evs):
        ts_raw = str(ev["ts"]) if ev.get("ts") else ""
        ev_date = ts_raw[:10]

        if ev_date and ev_date != _last_date:
            _last_date = ev_date
            try:
                _d = _dt.strptime(ev_date, "%Y-%m-%d")
                date_label = f"{_d.month}/{_d.day}/{str(_d.year)[2:]}"
            except Exception:
                date_label = ev_date
            term_rows += f'<div class="te-date">{date_label}</div>'

        # Convert UTC → NYC (EDT = UTC-4; EST = UTC-5)
        hhmm = ""
        if len(ts_raw) >= 16:
            try:
                import re as _re2
                from datetime import timedelta as _tdd2
                _m = _re2.match(r'(\d{4})-(\d{2})-(\d{2})[\sT](\d{2}):(\d{2}):(\d{2})', ts_raw)
                if _m:
                    _utc_dt = _dt(*[int(x) for x in _m.groups()])
                    # DST: second Sunday March → first Sunday November (approx: months 4-10 = EDT)
                    _is_edt = 3 < _utc_dt.month < 11
                    _et_dt  = _utc_dt + _tdd2(hours=-4 if _is_edt else -5)
                    hhmm = _et_dt.strftime("%H:%M")
            except Exception:
                pass
        if not hhmm and len(ts_raw) >= 16:
            hhmm = ts_raw[11:16]  # fallback: raw UTC HH:MM

        tag = ev.get("tag", "")
        nav_col = None
        if tag in ("NAV", "UPDATE", "SNAPSHOT"):
            curr = _snap_vals[_snap_idx] if _snap_idx < len(_snap_vals) else None
            prev = _snap_vals[_snap_idx - 1] if 0 < _snap_idx <= len(_snap_vals) else None
            nav_col = "#00ff9d" if (prev is None or curr is None or curr >= prev) else "#ff3366"
            if _snap_idx < len(_snap_vals):
                _snap_idx += 1

        prose = _humanize(ev, nav_col)

        term_rows += (
            f'<div class="te">'
            f'<span class="te-ts">{hhmm}<span style="font-size:7px;opacity:.4;letter-spacing:.08em"> ET</span>&nbsp;&nbsp;</span>'
            f'{prose}'
            f'</div>'
        )

    # ── Positions panel HTML ──────────────────────────────────────────────────
    # Queue panel items
    q_items = ""
    for qa in data.get("queued_actions", []):
        q_items += (
            f'<div class="q-item">'
            f'<div class="q-badge" style="color:{qa["color"]}">{qa["badge"]}</div>'
            f'<div class="q-label" style="color:{qa["color"]}">{qa["label"]}</div>'
            f'<div class="q-detail">{qa["detail"]}</div>'
            f'<div class="q-timer" data-target="{qa["target_ms"]}">—</div>'
            f'</div>'
        )

    # P&L banner values
    last_nav_fmt = f'${last_nav:,.0f}'
    _total_pnl     = last_nav - _STARTING_CAPITAL
    _total_pnl_pct = (_total_pnl / _STARTING_CAPITAL) * 100
    _pnl_col       = "#00ff9d" if _total_pnl >= 0 else "#ff3366"
    _pnl_sign      = "+" if _total_pnl >= 0 else "−"
    _pnl_str       = f'{_pnl_sign}${abs(_total_pnl):,.0f}'
    _pnl_pct_str   = f'{_total_pnl_pct:+.2f}% since $100K start'

    # ── Blob sprite SVG (defined as a plain string to avoid f-string brace escaping) ──
    _BLOB_SVG = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 38" width="28" height="33"'
        ' overflow="visible" style="display:block;flex-shrink:0">'
        '<defs>'
        '<radialGradient id="bs-bd" cx="36%" cy="25%" r="74%">'
        '<stop offset="0%" stop-color="#FFCAF0"/>'
        '<stop offset="22%" stop-color="#FF5ECB"/>'
        '<stop offset="58%" stop-color="#FF0A8A"/>'
        '<stop offset="100%" stop-color="#8A0050"/>'
        '</radialGradient>'
        '<radialGradient id="bs-gg" cx="50%" cy="50%" r="50%">'
        '<stop offset="0%" stop-color="#FF0A8A" stop-opacity="0.55"/>'
        '<stop offset="100%" stop-color="#FF0A8A" stop-opacity="0"/>'
        '</radialGradient>'
        '<filter id="bs-gf" x="-80%" y="-80%" width="260%" height="260%">'
        '<feGaussianBlur stdDeviation="3"/>'
        '</filter>'
        '<radialGradient id="bs-gg-happy" cx="50%" cy="50%" r="50%">'
        '<stop offset="0%" stop-color="#00ff9d" stop-opacity="0.8"/>'
        '<stop offset="100%" stop-color="#00ff9d" stop-opacity="0"/>'
        '</radialGradient>'
        '<radialGradient id="bs-gg-sad" cx="50%" cy="50%" r="50%">'
        '<stop offset="0%" stop-color="#0066ff" stop-opacity="0.5"/>'
        '<stop offset="100%" stop-color="#0066ff" stop-opacity="0"/>'
        '</radialGradient>'
        '</defs>'
        '<style>'
        '@keyframes bs-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-2px)}}'
        '@keyframes bs-breathe{0%,100%{transform:scale(1,1)}45%{transform:scale(1.03,.975)}80%{transform:scale(.985,1.02)}}'
        '@keyframes bs-blink{0%,87%,100%{transform:scaleY(1)}92%{transform:scaleY(.07)}}'
        '@keyframes bs-gp{0%,100%{opacity:.22}50%{opacity:.48}}'
        '@keyframes bs-happy-float{0%,100%{transform:translateY(0)}40%{transform:translateY(-4px)}60%{transform:translateY(-2px)}}'
        '@keyframes bs-happy-squish{0%,100%{transform:scale(1,1)}30%{transform:scale(1.08,.93)}60%{transform:scale(.96,1.05)}}'
        '@keyframes bs-happy-glow{0%,100%{opacity:.55}50%{opacity:.9}}'
        '@keyframes bs-sad-droop{0%,100%{transform:translateY(0) scaleY(1)}50%{transform:translateY(2px) scaleY(.96)}}'
        '@keyframes bs-sad-glow{0%,100%{opacity:.12}50%{opacity:.28}}'
        '#bs-g{animation:bs-float 3.8s ease-in-out infinite,bs-breathe 3.1s ease-in-out infinite;transform-box:fill-box;transform-origin:center}'
        '#bs-g.bs-happy{animation:bs-happy-float 1.4s ease-in-out infinite,bs-happy-squish 1.1s ease-in-out infinite}'
        '#bs-g.bs-sad{animation:bs-sad-droop 2.6s ease-in-out infinite;filter:saturate(.4) brightness(.8) hue-rotate(200deg)}'
        '.bs-eye{animation:bs-blink 5.5s ease-in-out infinite;transform-box:fill-box;transform-origin:center}'
        '.bs-happy .bs-eye{transform:scaleY(.35);transform-box:fill-box;transform-origin:center;animation:none}'
        '.bs-sad .bs-eye{transform:scaleY(.6) translateY(1px);transform-box:fill-box;transform-origin:center;animation:none}'
        '#bs-hl{animation:bs-gp 2.4s ease-in-out infinite}'
        '#bs-hl.bs-hl-happy{animation:bs-happy-glow 1.4s ease-in-out infinite;fill:url(#bs-gg-happy)}'
        '#bs-hl.bs-hl-sad{animation:bs-sad-glow 2.6s ease-in-out infinite;fill:url(#bs-gg-sad)}'
        '</style>'
        '<ellipse id="bs-hl" cx="16" cy="22" rx="15" ry="17" fill="url(#bs-gg)"/>'
        '<path d="M16,4 C21.5,4 27.5,9.5 27.5,18 C27.5,26 24,34 16,36 C8,34 4.5,26 4.5,18 C4.5,9.5 10.5,4 16,4Z"'
        ' fill="#FF0A8A" opacity="0.28" filter="url(#bs-gf)"/>'
        '<g id="bs-g">'
        '<path d="M16,4 C21.5,4 27.5,9.5 27.5,18 C27.5,26 24,34 16,36 C8,34 4.5,26 4.5,18 C4.5,9.5 10.5,4 16,4Z"'
        ' fill="url(#bs-bd)" stroke="#1C002C" stroke-width="0.8"/>'
        '<ellipse cx="11.5" cy="12.5" rx="4.4" ry="2.7" fill="white" opacity="0.30"'
        ' transform="rotate(-22 11.5 12.5)"/>'
        '<circle cx="20.5" cy="9.5" r="1.2" fill="white" opacity="0.22"/>'
        '<path d="M27.5,18 C27.5,26 24,34 16,36" stroke="#FF8AD7" stroke-width="1.1"'
        ' fill="none" opacity="0.42" stroke-linecap="round"/>'
        '<rect class="bs-eye" x="9" y="20" width="5.2" height="3.8" rx="1.2" fill="#0E0018"/>'
        '<rect class="bs-eye" x="17.8" y="20" width="5.2" height="3.8" rx="1.2" fill="#0E0018"/>'
        '<rect x="9.9" y="20.7" width="1.6" height="1.3" rx="0.5" fill="rgba(255,255,255,.68)"/>'
        '<rect x="18.7" y="20.7" width="1.6" height="1.3" rx="0.5" fill="rgba(255,255,255,.68)"/>'
        '</g>'
        '</svg>'
    )

    # Build equity positions map for JS satellites
    import json as _json
    _TICKER_PAL_PY = ["#00e5ff","#cc00ff","#ff9900","#e040fb","#40c4ff","#ff6b35","#00ffcc","#f7b731","#7c4dff","#18ffff"]
    _eq_pos_js = _json.dumps({
        p["sym"]: {
            "entry_price":  float(p["entry_price"] or p.get("value") or 1),
            "stop_price":   float(p["entry_price"] or p.get("value") or 1) * 0.95,
            "target_price": float(p["entry_price"] or p.get("value") or 1) * 1.10,
            "current_value": float(p["value"] or 0),
            "is_equity": True,
        }
        for p in data.get("positions_data", [])
    })
    # Canvas tile seed data — all fields needed to paint tiles on load
    _eq_canvas_tiles_j = _json.dumps([
        {
            "sym":        p["sym"],
            "col":        _tc(p["sym"]),
            "val":        float(p["value"] or 0),
            "pnl":        float(p["entry_pnl"] or 0),
            "pnlPct":     float(p["entry_pnl_pct"] or 0),
            "entry":      float(p["entry_price"] or 0),
            "qty":        float(p.get("qty") or 0),
            "stop":       float(p.get("stop_price") or 0),
            "target":     float(p.get("target_price") or 0),
            "curPrice":   float(p.get("price") or p["entry_price"] or 0),
            "days":       int(p.get("days_held") or 0),
            "enteredAt":  int(datetime.fromisoformat(p["entry_filled_at"]).timestamp() * 1000) if p.get("entry_filled_at") else int((datetime.now().timestamp() - (p.get("days_held") or 0) * 86400) * 1000),
            "inSignal":   bool(p.get("in_signal", True)),
            "rank":       int(p.get("rank") or 0),
            "holdText":   str(p.get("hold_text") or ""),
            "strategy":   "momentum",
        }
        for p in data.get("positions_data", [])
    ])

    _queued_actions_js = _json.dumps(data.get("queued_actions", []))

    def _orb_hue(pnl, pct):
        if abs(pnl) < 0.01: return 0
        mag = min(abs(pct) / 5, 1)
        return int(140 - mag * 60) if pnl >= 0 else 20
    def _orb_sat(pnl): return "0%" if abs(pnl) < 0.01 else "80%"
    def _orb_lit(pnl, pct):
        if abs(pnl) < 0.01: return "26%"
        return str(int(42 + min(abs(pct)/5,1)*10)) + "%"
    def _orb_dur(days): return round(max(0.5, 1.4 - min(days,30)/30 * 0.9), 2)

    pos_cards = ""
    _pc_idx = 0
    _TICKER_PAL = ["#00e5ff","#9400ff","#ff9900","#e040fb","#40c4ff","#b2ff59","#ff6b35","#00ffcc"]
    for p in data.get("positions_data", []):
        tcol   = _TICKER_PAL[hash(p["sym"]) % len(_TICKER_PAL)]
        ep     = p["entry_price"]
        epnl   = p["entry_pnl"]
        epct   = p["entry_pnl_pct"]
        pnl_col = "#00c880" if epnl >= 0 else "#e03355"
        pnl_arrow = "▲" if epnl >= 0 else "▼"
        pnl_sign  = "+" if epnl >= 0 else "−"

        # Status badge
        if p["in_signal"]:
            rank_n = p.get("rank") or "?"
            badge_html = f'<span class="pc-badge pc-badge-hold">#{rank_n} HOLD</span>'
        else:
            badge_html = '<span class="pc-badge pc-badge-sell">EXIT</span>'

        # Proximity bar: 0=at stop, 1=at target
        prox_pct = 0
        stop_p  = p.get("stop_price", 0)
        tgt_p   = p.get("target_price", 0)
        cur_p   = p.get("price", ep or 0)
        if tgt_p > stop_p > 0 and cur_p:
            prox_pct = max(0, min(100, (cur_p - stop_p) / (tgt_p - stop_p) * 100))
        prox_col = ("#a03050" if prox_pct < 33 else "#4080b0" if prox_pct < 66 else "#00a060")
        prox_bar = (
            f'<div class="pc-prox-wrap">'
            f'  <div class="pc-prox-labels">'
            f'    <span class="pc-prox-stop">STP ${stop_p:,.0f}</span>'
            f'    <span class="pc-prox-cur" style="left:{max(5,min(90,prox_pct)):.0f}%">${cur_p:,.0f}</span>'
            f'    <span class="pc-prox-tgt">TGT ${tgt_p:,.0f}</span>'
            f'  </div>'
            f'  <div class="pc-prox-track">'
            f'    <div class="pc-prox-fill" style="width:{prox_pct:.1f}%;background:{prox_col};box-shadow:0 0 6px {prox_col}88"></div>'
            f'    <div class="pc-prox-dot" style="left:{max(0,min(100,prox_pct)):.1f}%;background:{prox_col};box-shadow:0 0 8px {prox_col}"></div>'
            f'  </div>'
            f'</div>'
        ) if ep else ""

        # Days held ticker
        days = p.get("days_held", 0)
        day_lbl = "day" if days == 1 else "days"
        entry_fmt = f'${ep:,.2f}' if ep else "—"
        edate_raw = str(p.get("entry_date","—"))
        try:
            from datetime import date as _dc
            _ed = _dc.fromisoformat(edate_raw)
            edate_fmt = _ed.strftime("%-d %b")
        except Exception:
            edate_fmt = edate_raw[:7]

        scan_delay = f'{(_pc_idx % 5) * 0.8:.1f}s'
        _pc_idx += 1
        pos_cards += (
            f'<div class="pos-card pc-eq pos-card-active" data-sym="{p["sym"]}"'
            f' data-entry="{p.get("entry_price", 0)}" data-qty="{p.get("qty", 0)}"'
            f' style="border-left:3px solid {tcol};--pc-scan-delay:{scan_delay}">'
            f'<span class="pos-corner tl" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner tr" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner bl" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner br" style="border-color:{tcol}"></span>'
            # Row 1: sym (left, unique color) + value (right, white)
            f'<div class="pc-row1">'
            f'  <span class="pc-sym" style="color:{tcol}">{p["sym"]}</span>'
            f'  <span class="pc-val" id="pcval-{p["sym"]}" data-raw="{p["value"]:.0f}">${p["value"]:,.0f}</span>'
            f'</div>'
            # Row 2: entry price in unique color
            f'<div class="pc-entry-price" style="color:{tcol}">@${ep:,.2f}</div>'
            # Row 3: hold timer + XP bar
            f'<div class="pc-bottom-row">'
            f'  <span class="pc-hold-timer">{days}d</span>'
            f'  <div class="pc-xp-wrap"><div class="pc-xp-fill" style="width:{min(int(days/60*100),100)}%"></div></div>'
            f'</div>'
            f'</div>'
        )
    equity_label = '<div class="pos-section-label">equity</div>'
    if not pos_cards:
        pos_cards = equity_label + '<div class="pos-hold" style="padding:8px 14px">no equity positions</div>'
    else:
        pos_cards = equity_label + pos_cards

    # Report panel equity cards — larger, richer layout
    rp_equity_cards = ""
    for p in data.get("positions_data", []):
        tcol = _TICKER_PAL[hash(p["sym"]) % len(_TICKER_PAL)]
        ep, epnl, epct = p["entry_price"], p["entry_pnl"], p["entry_pnl_pct"]
        pnl_col = "#00ff9d" if epnl >= 0 else "#ff3366"
        pnl_sign = "+" if epnl >= 0 else "−"
        pnl_str = f'{pnl_sign}${abs(epnl):,.0f} ({epct:+.1f}%)' if ep else "—"
        rp_equity_cards += (
            f'<div class="rp-pos rp-pos-entering" data-sym="{p["sym"]}">'
            f'<span class="pos-corner tl" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner tr" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner bl" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner br" style="border-color:{tcol}"></span>'
            f'<div class="rp-pos-stripe" style="background:{tcol};box-shadow:0 0 8px {tcol}55"></div>'
            f'<div class="rp-pos-top">'
            f'  <span class="rp-pos-sym" style="color:{tcol}">{p["sym"]}</span>'
            f'  <span class="rp-pos-type">EQUITY</span>'
            f'</div>'
            f'<div class="rp-pos-val">${p["value"]:,.0f}</div>'
            f'<div class="rp-pos-sub">'
            f'  <span class="rp-pos-qty">{p["qty"]} sh</span>'
            f'  <span class="rp-pos-hold">{p["hold_text"]}</span>'
            f'</div>'
            f'<div class="rp-pos-pnl" style="color:{pnl_col}">{pnl_str}</div>'
            f'</div>'
        )
    if not rp_equity_cards:
        rp_equity_cards = '<div style="padding:12px 14px;font-size:9px;color:#2a1a3a;letter-spacing:.04em">no equity positions</div>'

    # Normalize SPY and QQQ to $100K at portfolio start date
    # so all 3 lines are directly comparable on one axis
    spy_norm: list[float] = []
    if spy["prices"]:
        spy_base = spy["prices"][0] or 1.0
        spy_norm = [p / spy_base * _STARTING_CAPITAL for p in spy["prices"]]

    qqq_norm: list[float] = []
    if qqq["prices"]:
        qqq_base = qqq["prices"][0] or 1.0
        qqq_norm = [p / qqq_base * _STARTING_CAPITAL for p in qqq["prices"]]

    # Latest normalized values for display
    spy_norm_latest = f'${spy_norm[-1]:,.0f}' if spy_norm else "—"
    qqq_norm_latest = f'${qqq_norm[-1]:,.0f}' if qqq_norm else "—"
    spy_ret = f'{(spy_norm[-1]/_STARTING_CAPITAL - 1)*100:+.1f}%' if spy_norm else "—"
    qqq_ret = f'{(qqq_norm[-1]/_STARTING_CAPITAL - 1)*100:+.1f}%' if qqq_norm else "—"

    # Serialize chart data as JSON (safe for embedding)
    port_dates_j  = json.dumps(port["dates"])
    port_values_j = json.dumps(port["values"])
    mark_ts_j     = json.dumps(mark_ts)
    mark_vals_j   = json.dumps(mark_vals)
    spy_dates_j   = json.dumps(spy["dates"])
    spy_norm_j    = json.dumps(spy_norm)
    qqq_dates_j   = json.dumps(qqq["dates"])
    qqq_norm_j    = json.dumps(qqq_norm)
    nav_snap_pts_j = json.dumps(data.get("nav_snap_pts", []))

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Orbitron:wght@700;900&family=Bangers&family=Silkscreen:wght@400;700&family=VT323&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html {{
  background:#060008; overflow:hidden;
  height:100%; width:100%; margin:0; padding:0;
}}
body {{
  background:#060008; overflow:visible;
  font-family:Consolas,'Courier New',monospace;
  color:#f0e0ff; height:100%; width:100%; margin:0; padding:0;
  display:flex; flex-direction:column;
}}
body::after {{
  content:''; position:fixed; inset:0;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,0,0,0.07) 3px,rgba(0,0,0,0.07) 4px);
  pointer-events:none; z-index:200;
}}
@keyframes chroma-shift {{
  0%,90%,100% {{ text-shadow:0 0 12px rgba(255,0,204,.9),0 0 30px rgba(255,0,204,.4),0 0 60px rgba(255,0,204,.15); }}
  95% {{ text-shadow:-2px 0 rgba(0,229,255,.5),2px 0 rgba(255,0,204,.5),0 0 20px rgba(255,0,204,.6); }}
}}
@keyframes pdot {{
  0%,100% {{ opacity:1; box-shadow:0 0 10px rgba(255,0,204,.9); }}
  50% {{ opacity:.25; box-shadow:0 0 3px rgba(255,0,204,.2); }}
}}
@keyframes shimmer {{
  0%,100% {{ opacity:1; text-shadow:0 0 16px rgba(255,0,204,.5); }}
  50% {{ opacity:.85; text-shadow:0 0 24px rgba(255,0,204,.8); }}
}}
/* flex children */
#main-area {{ flex:1; position:relative; overflow:hidden; min-height:0; }}
#chart {{ position:absolute; inset:0; width:100%; height:100%; opacity:0; pointer-events:none; }}
#pulse-canvas {{ position:absolute; inset:0; pointer-events:none; z-index:8; }}
#particle-canvas {{ position:absolute; inset:0; pointer-events:none; z-index:1; width:100%; height:100%; }}

/* ── Left feed overlay ── */
#feed-overlay {{
  position:absolute; left:0; top:0; bottom:0; width:280px; z-index:15;
  display:flex; flex-direction:column;
  background:linear-gradient(90deg,rgba(1,0,6,.9) 0%,rgba(1,0,6,.55) 75%,transparent 100%);
  pointer-events:none;
}}
#feed-overlay .panel-hdr {{ pointer-events:auto; flex-shrink:0; padding:6px 8px 5px; border-bottom:1px solid #1a0022; }}
#feed-overlay #term-body {{
  flex:1; overflow-y:auto; display:flex; flex-direction:column; padding:4px 0 6px; scrollbar-width:none; background:transparent;
  pointer-events:auto;
  -webkit-mask-image:linear-gradient(to bottom,black 0%,black 75%,transparent 100%);
  mask-image:linear-gradient(to bottom,black 0%,black 75%,transparent 100%);
}}
#feed-overlay #term-body::-webkit-scrollbar {{ display:none; }}
#feed-overlay .te {{ padding:3px 6px; font-size:11px; }}
#feed-bottom-bar {{ flex-shrink:0; padding:4px 8px; pointer-events:auto; display:flex; align-items:center; }}
#mute-btn {{
  background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.12);
  cursor:pointer; padding:4px 10px; display:flex; align-items:center; gap:5px;
  font-family:Consolas,'Courier New',monospace; font-size:9px; font-weight:700;
  letter-spacing:.18em; color:rgba(255,255,255,.55); transition:all .15s;
  pointer-events:auto;
}}
#mute-btn:hover {{ background:rgba(255,255,255,.09); color:#fff; border-color:rgba(255,255,255,.3); }}
#mute-btn.muted {{ color:rgba(255,255,255,.2); border-color:rgba(255,255,255,.06); background:transparent; }}
#mute-icon {{ font-size:11px; }}
#mute-label {{ font-size:8px; letter-spacing:.22em; }}

/* ── Right positions overlay ── */
#pos-overlay {{
  position:absolute; right:0; top:0; bottom:0; width:130px; z-index:15;
  display:flex; flex-direction:column;
  background:transparent;
}}
#pos-overlay .panel-hdr {{ flex-shrink:0; padding:6px 12px 5px; border-bottom:1px solid #1a0022; display:none; }}
#pos-overlay #pos-body {{ flex:1; overflow:hidden; display:flex; flex-direction:row; gap:0; }}
#pos-right {{
  background:transparent;
  position:relative;
}}
#tile-headings {{
  position:absolute; top:0; left:0; pointer-events:none; z-index:10;
}}
.tile-group-hdr {{
  position:absolute; top:0; display:flex; align-items:center; gap:5px;
  height:16px; padding:0 6px; box-sizing:border-box;
  border-bottom:1px solid rgba(255,255,255,0.06);
  background:rgba(0,0,8,0.70);
  font:700 7px Consolas,monospace; letter-spacing:.18em; text-transform:uppercase;
  white-space:nowrap; overflow:hidden;
}}
#pos-left {{ flex:0 0 auto !important; overflow:hidden; width:0 !important; display:none; }}
#pos-left .pos-section-label {{ display:none; }}
#pos-overlay #particle-canvas {{ position:absolute; inset:0; pointer-events:none; z-index:1; width:100%; height:100%; }}

/* ── Top bar ── */
.topbar {{
  height:44px; flex-shrink:0;
  background:rgba(6,0,8,.9); border-bottom:1px solid #2a003d;
  backdrop-filter:blur(12px);
  display:flex; align-items:center; padding:0 20px; gap:14px; z-index:10;
  overflow:hidden; position:relative;
}}
/* 90s Jazz-era geometric decoration — teal/magenta swooshes at low opacity */
.topbar::before {{
  content:''; position:absolute; inset:0; pointer-events:none; z-index:0;
  background:
    linear-gradient(128deg, transparent 0%,  rgba(0,210,200,.055) 22%, transparent 42%),
    linear-gradient(110deg, transparent 38%, rgba(255,10,138,.035) 56%, transparent 74%),
    linear-gradient(95deg,  transparent 58%, rgba(148,0,255,.04)   76%, transparent 92%);
}}
.topbar > * {{ position:relative; z-index:1; }}
.wordmark {{ font-size:15px; font-weight:700; letter-spacing:-.02em; color:#ff00cc; animation:chroma-shift 6s ease-in-out infinite; white-space:nowrap; }}
.pulse-dot {{ width:6px; height:6px; border-radius:50%; background:#ff00cc; box-shadow:0 0 8px rgba(255,0,204,.9); animation:pdot 1.3s ease-in-out infinite; flex-shrink:0; }}
.pill {{ font-size:8px; letter-spacing:.18em; padding:3px 9px; border:1px solid currentColor; white-space:nowrap; display:inline-flex; align-items:center; gap:5px; }}
.pill-m {{ color:#ff00cc; border-color:rgba(255,0,204,.35); text-shadow:0 0 8px rgba(255,0,204,.5); }}
.pill-c {{ color:#00e5ff; border-color:rgba(0,229,255,.3); }}
.pill-d {{ color:#8060a0; border-color:rgba(128,96,160,.25); }}

/* ── Wallet selector ── */
#wallet-selector {{
  display:inline-flex; align-items:center; gap:6px;
  background:rgba(255,0,204,.08); border:1px solid rgba(255,0,204,.3);
  border-radius:2px; padding:4px 10px; cursor:pointer;
  transition:background .2s, border-color .2s; user-select:none;
}}
#wallet-selector:hover {{ background:rgba(255,0,204,.16); border-color:rgba(255,0,204,.6); }}
#wallet-mode-icon {{ font-size:11px; color:#ff00cc; text-shadow:0 0 8px rgba(255,0,204,.7); }}
#wallet-mode-label {{
  font:700 9px Consolas,monospace; letter-spacing:.22em; color:#ff00cc;
  text-transform:uppercase; text-shadow:0 0 8px rgba(255,0,204,.5);
}}
#wallet-mode-chevron {{ font-size:8px; color:#4a2a6a; }}
#wallet-selector.live {{
  background:rgba(0,229,100,.08); border-color:rgba(0,229,100,.4);
}}
#wallet-selector.live #wallet-mode-icon,
#wallet-selector.live #wallet-mode-label {{ color:#00e564; text-shadow:0 0 8px rgba(0,229,100,.7); }}
#strat-health {{
  display:inline-flex; align-items:center; gap:5px;
  padding:3px 8px; border:1px solid rgba(255,255,255,.08);
  cursor:default;
}}
#strat-health-dot {{
  width:7px; height:7px; border-radius:50%;
  background:#3a3a3a;
  transition:background .4s, box-shadow .4s;
}}
#strat-health-dot.green  {{ background:#00c880; box-shadow:0 0 6px rgba(0,200,128,.7); animation:health-pulse 2s ease-in-out infinite; }}
#strat-health-dot.yellow {{ background:#ffaa00; box-shadow:0 0 6px rgba(255,170,0,.7); animation:health-pulse 1s ease-in-out infinite; }}
#strat-health-dot.red    {{ background:#e03355; box-shadow:0 0 8px rgba(224,51,85,.8); animation:health-pulse .5s ease-in-out infinite; }}
@keyframes health-pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.45}} }}
#strat-health-label {{ font-size:8px; letter-spacing:.2em; color:rgba(255,255,255,.35); font-family:Consolas,monospace; }}

/* ── NAV card (top-left of main-area) ── */
.nav-card {{
  position:absolute; top:10px; left:110px;
  background:rgba(6,0,8,.82); border:1px solid #2a003d; border-top:2px solid #ff00cc;
  backdrop-filter:blur(10px); padding:10px 16px; z-index:10; min-width:160px;
}}
.nv-label {{ font-size:7px; letter-spacing:.22em; color:#3a1a4a; text-transform:uppercase; display:block; }}
.nv-val {{ font-size:24px; font-weight:700; letter-spacing:-.03em; color:#ff00cc; display:block; line-height:1.1; animation:shimmer 3s ease-in-out infinite; }}
.nv-ret {{ font-size:11px; font-weight:700; display:block; margin-top:2px; }}
.nv-dpnl {{ font-size:9px; color:#8060a0; display:block; margin-top:4px; letter-spacing:.04em; }}

/* ── Legend chips (top-right of main-area) — hidden, redundant with pos overlay ── */
.legend-strip {{ display:none; }}
.leg-item {{
  display:flex; align-items:center; gap:8px;
  background:rgba(6,0,8,.82); border:1px solid #2a003d;
  backdrop-filter:blur(8px); padding:6px 12px;
  min-width:140px;
}}
.leg-dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
.leg-name {{ font-size:8px; letter-spacing:.16em; color:#8060a0; flex:1; }}
.leg-val {{ font-size:11px; font-weight:700; letter-spacing:-.01em; }}
.leg-ret {{ font-size:9px; margin-left:4px; }}

/* ── Topbar stat chips (right side) ── */
.tb-sep {{ width:1px; height:18px; background:#2a003d; flex-shrink:0; }}
.tb-stat {{ display:flex; flex-direction:column; gap:0; padding:0 12px; flex-shrink:0; }}
.tb-stat-label {{ font-size:6.5px; letter-spacing:.22em; color:#3a1a4a; text-transform:uppercase; line-height:1; }}
.tb-stat-val {{ font-size:12px; font-weight:700; letter-spacing:-.02em; line-height:1.4; }}
.tb-hg {{ display:flex; flex-direction:column; gap:2px; padding:0 10px; flex-shrink:0; border-left:1px solid #1a0028; }}
.tb-hg-label {{ font-size:6px; letter-spacing:.2em; color:rgba(255,255,255,.55); text-transform:uppercase; line-height:1; }}
.tb-hg-val {{ font-size:10px; font-weight:700; letter-spacing:.02em; line-height:1.3; color:rgba(255,255,255,.38); font-family:Consolas,monospace; }}
.tb-hg-row {{ display:flex; align-items:center; gap:4px; }}
.spacer {{ flex:1; }}
.hint {{ font-size:8px; letter-spacing:.1em; color:#2a003d; white-space:nowrap; }}

/* ── Terminal overlay — hidden (data elements kept for JS) ── */
#term-overlay {{
  display:none !important;
}}
/* ── Trade veil — full chart-area flash on every trade ── */
#trade-veil {{
  position:absolute; inset:0; pointer-events:none; z-index:50;
  opacity:0;
}}
@keyframes veil-entry {{
  0%   {{ opacity:.28; background:radial-gradient(ellipse at 50% 50%, rgba(255,255,255,.38) 0%, rgba(255,255,255,0) 70%); }}
  100% {{ opacity:0; }}
}}
@keyframes veil-win {{
  0%   {{ opacity:.30; background:radial-gradient(ellipse at 50% 50%, rgba(0,255,157,.42) 0%, rgba(0,255,157,0) 70%); }}
  100% {{ opacity:0; }}
}}
@keyframes veil-loss {{
  0%   {{ opacity:.30; background:radial-gradient(ellipse at 50% 50%, rgba(255,51,102,.42) 0%, rgba(255,51,102,0) 70%); }}
  100% {{ opacity:0; }}
}}
#trade-veil.veil-entry {{ animation:veil-entry .85s ease-out forwards; }}
#trade-veil.veil-win   {{ animation:veil-win   .85s ease-out forwards; }}
#trade-veil.veil-loss  {{ animation:veil-loss  .85s ease-out forwards; }}
/* CRT scanlines */
#term-overlay::before {{
  content:'';
  position:absolute; inset:0;
  background:repeating-linear-gradient(
    0deg, transparent, transparent 2px,
    rgba(0,255,65,.03) 2px, rgba(0,255,65,.03) 3px
  );
  pointer-events:none; z-index:100;
}}
/* vertical resize handle */
#vert-drag {{
  height:5px; flex-shrink:0; cursor:ns-resize;
  background:transparent; transition:background .15s; z-index:10;
}}
#vert-drag:hover, #vert-drag.dragging {{ background:rgba(0,255,65,.2); }}

/* ── Tracker bar — orange bar between header and chart ── */
#tracker-bar {{ display:none; }}

/* ── System health strip ── */
#sys-health-bar {{
  height:18px; flex-shrink:0; display:flex; align-items:center; padding:0 10px; gap:0;
  background:rgba(0,0,4,.96); border-bottom:1px solid rgba(80,0,120,.18);
  position:relative; z-index:99998; overflow:hidden;
}}
.sysh-item {{ display:flex; align-items:center; gap:4px; padding:0 8px; }}
.sysh-dot {{
  width:5px; height:5px; border-radius:50%; flex-shrink:0;
  background:#3a1a5a; transition:background .4s, box-shadow .4s;
}}
.sysh-dot.ok  {{ background:#00ff9d; box-shadow:0 0 4px rgba(0,255,157,.8); }}
.sysh-dot.warn {{ background:#ffaa00; box-shadow:0 0 4px rgba(255,170,0,.8); }}
.sysh-dot.dead {{ background:#ff3366; box-shadow:0 0 4px rgba(255,51,102,.8); }}
.sysh-lbl {{ font:700 6px Consolas,monospace; letter-spacing:.16em; color:rgba(255,255,255,.22); text-transform:uppercase; }}
.sysh-val {{ font:700 8px Consolas,monospace; letter-spacing:.06em; color:rgba(255,255,255,.55); margin-left:3px; }}
.sysh-sep {{ width:1px; height:10px; background:rgba(148,0,255,.15); flex-shrink:0; }}

/* ═══════════════════════════════════════════════════════════════
   STRATAGEM HUD — Helldivers-style process-status bar
   ═══════════════════════════════════════════════════════════════ */
#strat-bar {{
  height:46px; flex-shrink:0;
  display:flex; align-items:stretch;
  background:linear-gradient(180deg,rgba(2,0,12,.98) 0%,rgba(5,0,18,.95) 100%);
  border-bottom:1px solid rgba(148,0,255,.18);
  position:relative; z-index:99999;
  overflow:visible;
  gap:0;
}}
/* scanline overlay */
#strat-bar::before {{
  content:''; position:absolute; inset:0; pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,0,0,.08) 3px,rgba(0,0,0,.08) 4px);
}}
.strat-slot {{
  flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center;
  padding:4px 6px; position:relative; cursor:default;
  border-right:1px solid rgba(148,0,255,.12);
  transition:background .3s;
  min-width:0;
}}
.strat-slot:last-child {{ border-right:none; }}
#strat-bar > .strat-slot::before {{
  content:''; position:absolute; left:0; top:0; bottom:0; width:2px;
  background:transparent;
  transition:background .4s, box-shadow .4s;
}}
#strat-bar > .strat-slot.ss-active::before  {{ background:#00e5ff; box-shadow:0 0 3px rgba(0,229,255,.7); }}
#strat-bar > .strat-slot.ss-ready::before   {{ background:#00ff9d; box-shadow:0 0 3px rgba(0,255,157,.7); }}
#strat-bar > .strat-slot.ss-exec::before    {{ background:#ffaa00; box-shadow:0 0 3px rgba(255,170,0,.8); }}
#strat-bar > .strat-slot.ss-warn::before    {{ background:#ff3366; box-shadow:0 0 3px rgba(255,51,102,.7); }}
.strat-slot.ss-exec {{ background:rgba(255,170,0,.04); }}
.strat-slot.ss-ready {{ background:rgba(0,255,157,.03); }}
.ss-icon {{
  font-size:13px; line-height:1; margin-bottom:1px;
  opacity:.55; transition:opacity .3s;
}}
.strat-slot.ss-active .ss-icon,
.strat-slot.ss-exec   .ss-icon,
.strat-slot.ss-ready  .ss-icon {{ opacity:1; }}
.ss-name {{
  font:700 6px Consolas,monospace; letter-spacing:.2em; text-transform:uppercase;
  color:rgba(255,255,255,.28); margin-bottom:2px;
}}
.ss-status {{
  font:700 9px Consolas,monospace; letter-spacing:.06em;
  color:rgba(148,0,255,.6); transition:color .3s;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%;
  text-align:center;
}}
.strat-slot.ss-active .ss-status {{ color:#00e5ff; text-shadow:0 0 8px rgba(0,229,255,.5); }}
.strat-slot.ss-ready  .ss-status {{ color:#00ff9d; text-shadow:0 0 8px rgba(0,255,157,.5); }}
.strat-slot.ss-exec   .ss-status {{ color:#ffaa00; text-shadow:0 0 10px rgba(255,170,0,.8); animation:ss-exec-pulse .4s ease-in-out infinite alternate; }}
.strat-slot.ss-warn   .ss-status {{ color:#ff3366; text-shadow:0 0 8px rgba(255,51,102,.5); }}
@keyframes ss-exec-pulse {{ from{{opacity:.7}} to{{opacity:1}} }}
/* ── Trades slot ── */
.ss-trades-row {{ display:flex; justify-content:center; }}
.ss-trades-anchor {{ position:relative; display:inline-flex; align-items:baseline; }}
.ss-trades-chip {{
  position:absolute; left:calc(100% + 5px); top:50%; transform:translateY(-50%);
  font:700 9px Consolas,monospace; letter-spacing:.04em;
  color:#ff9900; opacity:0; transition:opacity .15s;
  text-shadow:0 0 8px rgba(255,153,0,.7); white-space:nowrap;
}}
/* ── Wallet slot ── */
.ss-wallet-row {{ display:flex; justify-content:center; align-items:center; height:100%; }}
.ss-wallet-anchor {{ position:relative; display:inline-flex; flex-direction:column; align-items:center; }}
.ss-wallet-val {{
  font-family:'Press Start 2P',monospace; font-size:14px; font-weight:400;
  letter-spacing:.04em; font-variant-numeric:tabular-nums;
  color:#ffe566;
  -webkit-text-stroke:1px rgba(0,0,0,.6);
  text-shadow:
    1px 1px 0 #b85c00,
    2px 2px 0 #9a4a00,
    3px 3px 0 #7a3600,
    4px 4px 0 rgba(0,0,0,.7),
    0 0 18px rgba(255,180,0,.5),
    0 0 6px  rgba(255,200,0,.3);
  white-space:nowrap; line-height:1;
  transition:color .4s ease, text-shadow .4s ease;
}}
.ss-wallet-val.gain {{
  color:#b6ffdd;
  -webkit-text-stroke:1px rgba(0,0,0,.6);
  text-shadow:
    1px 1px 0 #006633,
    2px 2px 0 #004d26,
    3px 3px 0 #003319,
    4px 4px 0 rgba(0,0,0,.7),
    0 0 20px rgba(0,255,157,.7),
    0 0 8px  rgba(0,255,157,.4);
}}
.ss-wallet-val.loss {{
  color:#ffb3c6;
  -webkit-text-stroke:1px rgba(0,0,0,.6);
  text-shadow:
    1px 1px 0 #880022,
    2px 2px 0 #660019,
    3px 3px 0 #440011,
    4px 4px 0 rgba(0,0,0,.7),
    0 0 20px rgba(255,51,102,.7),
    0 0 8px  rgba(255,51,102,.4);
}}
@keyframes dmg-pop {{
  0%   {{ opacity:0; transform:translateY(0px) scale(1.5); }}
  4%   {{ opacity:1; transform:translateY(-2px) scale(1.08); }}
  8%   {{ opacity:1; transform:translateY(-4px) scale(1); }}
  80%  {{ opacity:1; transform:translateY(-10px) scale(1); }}
  100% {{ opacity:0; transform:translateY(-16px) scale(.92); }}
}}
.ss-wallet-chip {{
  display:block; text-align:center;
  font-family:'Press Start 2P',monospace;
  font-size:9px; font-weight:400; letter-spacing:.02em;
  font-variant-numeric:tabular-nums;
  opacity:0; white-space:nowrap; pointer-events:none;
  text-shadow:1px 1px 0 rgba(0,0,0,.9), 0 0 10px currentColor;
  line-height:1.4; margin-top:2px;
}}
.ss-wallet-chip.dmg-active {{
  animation: dmg-pop 5s cubic-bezier(.22,1,.36,1) forwards;
}}

/* ── Callout rail — zero-height sibling after strat-bar; cards overflow down ─ */
/* ── Callout rail — drops from bottom of portfolio HUD tile ── */
#callout-rail {{
  position:absolute;
  bottom:0; left:0;
  height:0; overflow:visible;
  display:flex; flex-direction:column; align-items:flex-start;
  gap:1px; padding-top:0;
  pointer-events:none; z-index:99999;
}}
/* Enter: wipe up from bottom */
@keyframes cc-in {{
  0%   {{ opacity:0; clip-path:inset(100% 0 0 0); transform:translateX(-4px); }}
  40%  {{ opacity:1; clip-path:inset(0% 0 0 0);   transform:translateX(2px); }}
  100% {{ opacity:1; clip-path:inset(0% 0 0 0);   transform:translateX(0); }}
}}
/* Exit: arcade glitch → scanline wipe right */
@keyframes cc-out {{
  0%   {{ opacity:1; transform:translateX(0);    filter:brightness(1);              clip-path:inset(0 0% 0 0); }}
  12%  {{ opacity:1; transform:translateX(7px);  filter:brightness(2.5) hue-rotate(160deg); clip-path:inset(0 0% 0 0); }}
  20%  {{ opacity:1; transform:translateX(-4px); filter:brightness(1) hue-rotate(0deg);     clip-path:inset(0 0% 0 0); }}
  28%  {{ opacity:1; transform:translateX(3px);  filter:brightness(4) saturate(6);  clip-path:inset(0 0% 0 0); }}
  38%  {{ opacity:1; transform:translateX(0);    filter:brightness(1.5);            clip-path:inset(0 20% 0 0); }}
  55%  {{ opacity:1; transform:translateX(0);    filter:brightness(2);              clip-path:inset(0 60% 0 0); }}
  72%  {{ opacity:1; transform:translateX(0);    filter:brightness(5);              clip-path:inset(0 88% 0 0); }}
  85%  {{ opacity:1; transform:translateX(0);    filter:brightness(12);             clip-path:inset(0 97% 0 0); }}
  100% {{ opacity:0; transform:translateX(0);    filter:brightness(0);              clip-path:inset(0 100% 0 0); }}
}}
.callout-card {{
  display:flex; align-items:center; gap:0;
  padding:3px 8px 3px 8px;
  background:transparent; border:none;
  border-left:1px solid rgba(255,255,255,.06);
  opacity:0;
  pointer-events:none;
  font-family:Consolas,'Courier New',monospace;
  white-space:nowrap;
  transform-origin:center;
  width:190px;
}}
.callout-card.cc-show {{
  animation: cc-in .18s cubic-bezier(.2,.9,.3,1) forwards;
}}
.callout-card.cc-exit {{
  animation: cc-out .55s cubic-bezier(.6,0,1,1) forwards;
}}
/* 8-bit pixel sell icon — replaces "sold" text */
.cc-verb {{
  font-size:10px; flex-shrink:0; margin-right:5px; line-height:1;
  opacity:.7;
}}
.cc-sym {{
  font-size:13px; font-weight:700; letter-spacing:.06em;
  text-shadow:0 0 12px currentColor;
  flex:1;
}}
.cc-pnl {{
  font-family:'Press Start 2P',monospace;
  font-size:9px; letter-spacing:.02em;
  font-variant-numeric:tabular-nums;
  text-shadow:0 0 8px currentColor, 1px 1px 0 rgba(0,0,0,.95);
  text-align:right; flex-shrink:0; min-width:54px;
}}
.cc-count {{ display:none; }}

/* ── Terminal row appear ── */
@keyframes te-appear {{
  from {{ opacity:0; transform:translateY(-6px); }}
  to   {{ opacity:1; transform:translateY(0); }}
}}
.te-new {{ animation:te-appear 120ms ease-out forwards; }}

/* ── System Feed panel (bottom-left) ── */
#feed-panel {{
  flex:1; min-width:160px;
  background:#010006;
  display:flex; flex-direction:column;
  overflow:hidden;
}}
#term-body {{
  flex:1; overflow-y:auto;
  display:flex; flex-direction:column;
  padding:4px 0 6px;
  scrollbar-width:none; background:#010006;
}}
#term-body::-webkit-scrollbar {{ display:none; }}
.te {{ padding:3px 12px; flex-shrink:0;
       font-size:11px; line-height:1.65; color:#5a3a7a;
       white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.te-ts  {{ color:#3a2a4a; font-size:9px; margin-right:4px; }}
.te-date {{ padding:5px 12px 1px; flex-shrink:0;
            font-size:7.5px; font-weight:700; letter-spacing:.28em;
            color:#1a0028; text-transform:uppercase; }}
/* clock line hidden — status bar handles cursor */
#term-cursor {{ animation:term-cur 1s step-start infinite; }}
@keyframes term-cur {{ 0%,100%{{opacity:1}} 50%{{opacity:0}} }}
#clock-line {{ display:none; }}

/* ── Lower panels row ── */
#lower-panels {{
  flex:1; display:flex; overflow:hidden; min-height:0;
}}
/* ── Drag handles ── */
.col-drag {{
  width:5px; flex-shrink:0; cursor:col-resize;
  background:transparent; transition:background .15s; position:relative; z-index:10;
}}
.col-drag:hover, .col-drag.dragging {{ background:rgba(255,0,204,.25); }}
/* shared panel header row */
#lower-hdr {{
  display:none; /* headers embedded in each panel */
}}
.panel-hdr {{
  flex-shrink:0; padding:6px 12px 5px;
  border-bottom:1px solid #1a0022;
  font-size:9px; letter-spacing:.22em; color:#ff00cc;
  text-shadow:0 0 10px rgba(255,0,204,.45);
  display:flex; align-items:center; gap:7px;
  background:#02000a; text-transform:uppercase;
  font-weight:700;
}}
.term-dot {{
  width:6px; height:6px; border-radius:50%;
  background:#ff00cc;
  box-shadow:0 0 8px rgba(255,0,204,.9);
  animation:pdot 1.6s ease-in-out infinite;
  flex-shrink:0;
}}
/* ── Queue panel ── */
/* ── HUD overlay (fixed, drops over feed panel only) ── */
#hud-overlay {{
  position:fixed; top:0; left:0; width:300px; z-index:300;
  background:rgba(2,0,10,.97);
  border-bottom:1px solid rgba(0,229,255,.22);
  border-right:1px solid rgba(0,229,255,.1);
  box-shadow:0 2px 32px rgba(0,229,255,.12), 0 12px 48px rgba(0,0,0,.7);
  transform:translateY(-100%);
  transition:transform .2s cubic-bezier(.22,1,.36,1);
  display:flex; flex-direction:column; gap:0;
  padding-top:1px; overflow:hidden;
}}
#hud-overlay::before {{
  content:''; position:absolute; top:0; left:0; right:0; height:1px;
  background:linear-gradient(90deg,transparent,rgba(0,229,255,.9) 30%,rgba(255,0,204,.5) 70%,transparent);
  box-shadow:0 0 14px rgba(0,229,255,.7);
}}
#hud-overlay.hud-open {{ transform:translateY(0); }}
#hud-label {{
  flex-shrink:0; display:flex; align-items:center;
  padding:4px 12px 3px; border-bottom:1px solid rgba(0,229,255,.1); gap:7px;
}}
#hud-label-text {{
  font-size:7px; letter-spacing:.32em; color:rgba(0,229,255,.5);
  text-transform:uppercase; white-space:nowrap;
}}
#hud-items {{
  display:flex; flex-direction:column; overflow:hidden;
}}
.hud-item {{
  display:flex; align-items:center; gap:10px;
  padding:5px 12px; border-bottom:1px solid rgba(255,255,255,.03);
  position:relative; overflow:hidden;
}}
.hud-item:last-child {{ border-bottom:none; }}
.hud-item::before {{ /* left accent stripe */
  content:''; flex-shrink:0; width:2px; height:28px; border-radius:1px;
  background:currentColor; opacity:.6;
}}
.hud-item.hud-imminent::before {{ animation:hud-imminent-blink .45s ease-in-out infinite; }}
@keyframes hud-imminent-blink {{ 0%,100%{{opacity:.7}} 50%{{opacity:.1}} }}
.hud-badge {{
  font-size:6.5px; letter-spacing:.22em; font-weight:700;
  text-transform:uppercase; opacity:.75; white-space:nowrap;
}}
.hud-sym {{
  font-size:11px; font-weight:700; letter-spacing:.04em; flex:1;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}
.hud-detail {{
  font-size:7px; color:rgba(255,255,255,.2);
  letter-spacing:.02em; white-space:nowrap;
}}
.hud-timer {{
  font-size:14px; font-weight:700; letter-spacing:-.01em; margin-left:auto;
  font-variant-numeric:tabular-nums; white-space:nowrap;
}}
.hud-timer.hud-urgent {{ color:#ff9900; }}
.hud-timer.hud-imminent {{ color:#ff3366; animation:q-pulse .5s ease-in-out infinite; }}
@keyframes q-pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}
/* ── Report panel — Alpaca wallet display ── */
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Press+Start+2P&family=Bangers&family=Silkscreen:wght@400;700&family=VT323&display=swap');
#report-panel {{
  flex:1.4; min-width:200px; max-width:460px;
  background:#000308; display:flex; flex-direction:column;
  border-right:1px solid #08001a; position:relative; overflow:hidden;
  align-items:center; justify-content:center;
}}
/* scanline overlay on the wallet panel */
#report-panel::after {{
  content:''; position:absolute; inset:0; pointer-events:none; z-index:10;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.18) 2px,rgba(0,0,0,.18) 4px);
}}
#wallet-block {{
  position:relative; z-index:2;
  display:flex; flex-direction:column; align-items:center;
  gap:6px; padding:20px 24px;
  width:100%;
}}
#wallet-label {{
  font-family:'Orbitron',Consolas,monospace;
  font-size:7.5px; letter-spacing:.45em; font-weight:700;
  color:rgba(0,229,255,.35); text-transform:uppercase;
  text-shadow:0 0 12px rgba(0,229,255,.3);
}}
#wallet-nav {{
  font-family:'Orbitron',Consolas,monospace;
  font-size:clamp(28px,4.5vw,52px); font-weight:900; letter-spacing:-.02em;
  line-height:1; font-variant-numeric:tabular-nums;
  color:#00ff9d;
  text-shadow:
    0 0 20px rgba(0,255,157,.9),
    0 0 50px rgba(0,255,157,.5),
    0 0 100px rgba(0,255,157,.2),
    2px 0 0 rgba(255,0,204,.25),
    -2px 0 0 rgba(0,229,255,.2);
  position:relative;
}}
/* chromatic aberration ghost layers */
#wallet-nav::before,#wallet-nav::after {{
  content:attr(data-val);
  position:absolute; top:0; left:0; width:100%; pointer-events:none;
  font-family:inherit; font-size:inherit; font-weight:inherit; letter-spacing:inherit;
  white-space:nowrap;
}}
#wallet-nav::before {{
  color:rgba(255,0,204,.18);
  transform:translate(-3px,0);
  clip-path:polygon(0 30%,100% 30%,100% 55%,0 55%);
}}
#wallet-nav::after {{
  color:rgba(0,229,255,.18);
  transform:translate(3px,0);
  clip-path:polygon(0 55%,100% 55%,100% 75%,0 75%);
}}
@keyframes wallet-glitch {{
  0%,94%,100% {{ transform:none; text-shadow:0 0 20px rgba(0,255,157,.9),0 0 50px rgba(0,255,157,.5),0 0 100px rgba(0,255,157,.2),2px 0 0 rgba(255,0,204,.25),-2px 0 0 rgba(0,229,255,.2); }}
  95%          {{ transform:translate(-2px,0) skewX(-1deg); text-shadow:-4px 0 rgba(255,0,204,.6),4px 0 rgba(0,229,255,.6),0 0 30px rgba(0,255,157,.9); }}
  97%          {{ transform:translate(2px,0) skewX(1deg); text-shadow:4px 0 rgba(255,0,204,.5),-4px 0 rgba(0,229,255,.5),0 0 40px rgba(0,255,157,.7); }}
}}
#wallet-nav.glitch-active {{ animation:wallet-glitch 4s ease-in-out infinite; }}
#wallet-pnl {{
  font-family:'Orbitron',Consolas,monospace;
  font-size:clamp(13px,1.8vw,20px); font-weight:700; letter-spacing:.04em;
  font-variant-numeric:tabular-nums;
}}
#wallet-sub {{
  font-family:Consolas,monospace;
  font-size:8px; letter-spacing:.22em; color:rgba(255,255,255,.2);
  text-transform:uppercase; margin-top:4px;
}}
/* wallet canvas — full panel background */
#wallet-canvas {{
  position:absolute; inset:0; width:100%; height:100%;
  pointer-events:none; z-index:1;
}}
/* momentum bar */
#wallet-momentum-bar {{
  display:flex; flex-direction:column; align-items:center; gap:4px;
  width:100%; margin-top:8px;
}}
#wallet-vel-track {{
  width:140px; height:3px; background:rgba(255,255,255,.06);
  border-radius:2px; position:relative; overflow:visible;
}}
#wallet-vel-fill {{
  position:absolute; top:0; height:100%; border-radius:2px;
  transition:left .6s cubic-bezier(.22,1,.36,1), width .6s cubic-bezier(.22,1,.36,1), background .4s ease;
  box-shadow:0 0 8px currentColor;
}}
#wallet-vel-label {{
  font-size:6px; letter-spacing:.35em; color:rgba(255,255,255,.18);
  font-family:Consolas,monospace; text-transform:uppercase;
}}
/* ── Speedometer gauge ── */
#gauge-wrap {{
  width:100%; display:flex; flex-direction:column; align-items:center;
  gap:2px; margin-bottom:6px;
}}
#speed-gauge {{ width:min(150px,70%); overflow:visible; }}
#gauge-label {{
  font-family:'Orbitron',Consolas,monospace;
  font-size:11px; font-weight:700; letter-spacing:.04em; font-variant-numeric:tabular-nums;
  color:#00e5ff; text-shadow:0 0 10px rgba(0,229,255,.55);
  transition:color .6s ease, text-shadow .6s ease;
}}
#gauge-sub {{
  font-size:5.5px; letter-spacing:.4em; color:rgba(255,255,255,.15);
  font-family:Consolas,monospace; text-transform:uppercase;
}}
#gauge-needle {{ transition:transform 2.8s cubic-bezier(.23,.95,.49,1), stroke .8s ease; }}
/* ── Streak chip ── */
#wallet-streak {{
  font-size:8px; letter-spacing:.16em; font-family:Consolas,monospace;
  min-height:13px; text-align:center; transition:color .4s ease;
}}
/* event ticker — latest action */
#wallet-event-ticker {{
  font-size:8.5px; letter-spacing:.08em; color:rgba(255,255,255,.25);
  font-family:Consolas,monospace; min-height:14px; margin-top:2px;
  transition:color .3s ease, text-shadow .3s ease;
  text-align:center;
}}
/* noise band that sweeps across the wallet on update */
@keyframes wallet-noise-sweep {{
  0%   {{ top:-4px; opacity:0; }}
  10%  {{ opacity:1; }}
  90%  {{ opacity:.7; }}
  100% {{ top:calc(100% + 4px); opacity:0; }}
}}
#wallet-noise {{
  position:absolute; left:-10px; right:-10px; height:6px; top:-4px;
  background:linear-gradient(90deg,transparent,rgba(0,229,255,.4) 20%,rgba(0,255,157,.8) 50%,rgba(0,229,255,.4) 80%,transparent);
  box-shadow:0 0 12px rgba(0,229,255,.6);
  opacity:0; pointer-events:none; z-index:15;
}}
#wallet-noise.sweep {{ animation:wallet-noise-sweep .6s ease-in-out forwards; }}
/* section dividers (kept for rp-section-hdr class used elsewhere) */
.rp-section-hdr {{
  font-size:7px; letter-spacing:.22em; color:#2a1a3a; text-transform:uppercase;
  padding:5px 14px 4px 14px; border-bottom:1px solid #080018; background:#01000a;
  position:sticky; top:0; z-index:2;
}}
/* live q-items still used in the queue panel (hidden) — keep styles */
.q-item {{ display:none; }}
.q-badge {{ font-size:7px; letter-spacing:.2em; font-weight:700; margin-bottom:2px; }}
.q-label {{ font-size:11px; font-weight:700; line-height:1.3; word-break:break-all; }}
.q-detail {{ font-size:8px; color:#3a2a5a; margin-top:1px; letter-spacing:.02em; }}
.q-timer {{ font-size:11.5px; font-weight:700; letter-spacing:.04em; margin-top:4px; color:#6a4a8a; font-variant-numeric:tabular-nums; }}
.q-timer.urgent {{ color:#ff9900; }}
.q-timer.imminent {{ color:#ff3366; animation:q-pulse .6s ease-in-out infinite; }}
.q-item-live {{ border-top:1px solid rgba(0,229,255,.12); }}
.q-item-live .q-badge {{ color:#00e5ff; }}
/* ── Panel scan sweep ── */
@keyframes panel-sweep {{
  0%   {{ top:-5px; opacity:0; }}
  6%   {{ opacity:1; }}
  94%  {{ opacity:1; }}
  100% {{ top:calc(100% + 5px); opacity:0; }}
}}
@keyframes panel-border-pulse {{
  0%   {{ box-shadow:none; border-color:#1a0028; }}
  25%  {{ box-shadow:0 0 18px rgba(0,229,255,.35),inset 0 0 8px rgba(0,229,255,.08); border-color:#00e5ff; }}
  100% {{ box-shadow:none; border-color:#1a0028; }}
}}
#pos-panel.panel-scanning {{ animation:panel-border-pulse .9s ease-out forwards; }}
#pos-panel.panel-scanning::after {{
  content:''; position:absolute; pointer-events:none; z-index:25;
  left:-2px; right:-2px; height:4px; top:-5px;
  background:linear-gradient(90deg,transparent 0%,rgba(0,229,255,.5) 20%,#fff 50%,rgba(0,229,255,.5) 80%,transparent 100%);
  box-shadow:0 0 10px #00e5ff,0 0 24px rgba(0,229,255,.5);
  animation:panel-sweep .9s ease-in-out forwards;
}}
/* ── Positions panel (gamified scorecard) ── */
#pos-panel {{
  flex:1; min-width:240px;
  overflow:visible; scrollbar-width:none;
  background:#010008; position:relative;
  display:flex; flex-direction:column;
}}
#pos-panel::-webkit-scrollbar {{ display:none; }}
#pos-body {{
  flex:1; overflow:hidden;
  display:flex; flex-direction:row; gap:0;
}}
#pos-left, #pos-right {{
  flex:1; overflow-y:auto; scrollbar-width:thin; scrollbar-color:rgba(148,0,255,.25) transparent;
  display:flex; flex-direction:column; padding-bottom:6px; min-height:0;
}}
#pos-right {{ overflow:hidden; }} /* equity wraps into columns — no vertical scroll */
#pos-equity-section .pos-card,
#pos-equity-section .pos-card-ghost-space {{ width:130px; flex-shrink:0; }}
#pos-left {{ border-right:none; }}
/* Crypto cards — transparent column, left accent stripe only */
#pos-left .pos-card {{
  border-left:3px solid; border-right:none; border-top:none; border-bottom:1px solid rgba(13,0,32,.4);
  background:transparent !important; backdrop-filter:none !important;
}}
#pos-overlay {{ transition:none; }}
#pos-left::-webkit-scrollbar, #pos-right::-webkit-scrollbar {{ width:2px; }}
#pos-left::-webkit-scrollbar-thumb, #pos-right::-webkit-scrollbar-thumb {{ background:rgba(148,0,255,.3); border-radius:1px; }}
/* position count badge */
.pos-count-badge {{
  flex-shrink:0; display:flex; align-items:center; justify-content:center;
  padding:3px 6px; margin:3px 10px;
  border:1px solid rgba(0,229,255,.15); border-radius:2px;
  font-size:7px; letter-spacing:.2em; color:rgba(0,229,255,.4);
  background:rgba(0,229,255,.03);
}}
/* ── HUD — fixed just below the topbar, horizontally centered ── */
#pnl-float {{
  position:absolute; pointer-events:none;
  left:50%; top:68px; transform:translateX(-50%);
  background:rgba(4,0,10,.88); border:1px solid #2a003d; border-top:2px solid #ff00cc;
  backdrop-filter:blur(14px);
  padding:8px 20px 10px;
  opacity:0; transition:opacity .4s ease;
  z-index:120;
}}
#pnl-float.visible {{ opacity:1; }}
/* three-column metric layout */
#pnl-float-cols {{
  display:flex; align-items:flex-start; gap:24px;
}}
.pnl-col {{
  display:flex; flex-direction:column; align-items:center; gap:1px; min-width:64px;
}}
.pnl-col-center {{ min-width:120px; }}
.pnl-col-label {{
  font-family:Consolas,monospace; font-size:6.5px; letter-spacing:.22em;
  color:rgba(190,150,255,.6); text-transform:uppercase; white-space:nowrap;
}}
/* value + combo chip sit inline */
.pnl-val-row {{
  display:flex; align-items:baseline; gap:5px;
}}
.pnl-col-val {{
  font-family:Consolas,monospace; font-size:16px; font-weight:700;
  color:#ff00cc; letter-spacing:.02em; white-space:nowrap;
  transition:color .3s;
}}
.pnl-col-center .pnl-col-val {{ font-size:26px; }}
.pnl-combo-chip {{
  font-family:Consolas,monospace; font-size:11px; font-weight:700;
  opacity:0; transition:opacity .15s; min-height:14px; min-width:1px;
  text-shadow:0 0 8px currentColor; white-space:nowrap;
}}
.om-row {{
  display:flex; align-items:baseline; justify-content:space-between; gap:10px;
  padding:1.5px 0;
}}
.om-label {{
  font-size:7px; letter-spacing:.18em; color:rgba(190,150,255,.75); white-space:nowrap;
  font-family:Consolas,monospace; text-transform:uppercase;
}}
#total-pnl-block {{
  margin-top:6px; padding:8px 0 2px; text-align:right;
}}
#total-pnl-label {{
  font-size:6.5px; letter-spacing:.22em; color:rgba(190,150,255,.6);
  font-family:Consolas,monospace; text-transform:uppercase; margin-bottom:3px;
}}
#total-pnl-val {{
  font-family:Consolas,monospace; font-size:22px; font-weight:700;
  letter-spacing:-.01em; line-height:1;
  text-shadow:0 0 18px currentColor;
  transition:color .3s ease;
}}
#total-pnl-sub {{
  font-family:Consolas,monospace; font-size:7.5px; letter-spacing:.06em;
  opacity:.7; margin-top:3px; transition:color .3s ease;
}}
@keyframes pnl-flash-pos {{
  0%   {{ text-shadow:0 0 60px #00ff9d,0 0 24px #00ff9d,0 0 6px #fff; transform:scale(1.18); }}
  40%  {{ text-shadow:0 0 40px #00ff9d,0 0 12px #00ff9d; transform:scale(1.06); }}
  100% {{ text-shadow:0 0 14px currentColor; transform:scale(1); }}
}}
@keyframes pnl-flash-neg {{
  0%   {{ text-shadow:0 0 60px #ff3366,0 0 24px #ff3366,0 0 6px #fff; transform:scale(1.18); }}
  40%  {{ text-shadow:0 0 40px #ff3366,0 0 12px #ff3366; transform:scale(1.06); }}
  100% {{ text-shadow:0 0 14px currentColor; transform:scale(1); }}
}}
.pnl-flash-pos {{ animation:pnl-flash-pos .55s cubic-bezier(.22,1,.36,1) forwards; }}
.pnl-flash-neg {{ animation:pnl-flash-neg .55s cubic-bezier(.22,1,.36,1) forwards; }}
.om-val {{
  font-size:11px; font-weight:700; font-family:Consolas,monospace;
  color:#ff00cc; letter-spacing:.04em; white-space:nowrap;
  font-variant-numeric:tabular-nums;
}}
.om-divider {{ height:1px; background:#1a0028; margin:4px 0; }}
/* ── Recovery meter ── */
#rc-widget {{ margin-top:5px; }}
#rc-top {{ display:flex; align-items:baseline; gap:5px; margin-bottom:3px; }}
#rc-label {{
  font-size:6.5px; letter-spacing:.2em; text-transform:uppercase; color:#ff3366;
  text-shadow:0 0 6px rgba(255,51,102,.5);
}}
#rc-amount {{
  font-size:13px; font-weight:700; color:#ff3366; letter-spacing:-.01em;
  font-family:Consolas,monospace;
  text-shadow:0 0 10px rgba(255,51,102,.6);
}}
#rc-bar-bg {{
  height:3px; background:#1a0010; border-radius:1px; overflow:hidden;
  margin-bottom:3px;
}}
@keyframes rc-pulse {{
  0%,100% {{ opacity:1; }} 50% {{ opacity:.55; }}
}}
#rc-bar {{
  height:100%; width:0%; border-radius:1px;
  background:linear-gradient(90deg,#ff3366,#ff9900,#ffff00);
  transition:width .6s cubic-bezier(.22,1,.36,1);
  animation:rc-pulse 2s ease-in-out infinite;
}}
#rc-bar.recovered {{ background:linear-gradient(90deg,#00ff9d,#00e5ff); animation:none; }}
#rc-stats {{ display:flex; justify-content:space-between; }}
#rc-rate, #rc-eta {{
  font-size:7px; letter-spacing:.08em; color:#3a1a3a;
  font-family:Consolas,monospace;
}}
/* pos-cards */
.pos-section-label {{ display:none; }}
.pos-card {{ padding:5px 10px; cursor:default; position:relative; overflow:hidden;
             background:rgba(0,0,8,.88); border-bottom:1px solid rgba(255,255,255,.04);
             will-change:transform,opacity; }}

/* ── Equity position cards — terminal row style ── */
.pc-eq {{
  padding:5px 10px 5px 12px !important;
  background:rgba(0,0,8,.88) !important;
  border:none !important;
  border-left:3px solid !important;
  border-bottom:1px solid rgba(255,255,255,.04) !important;
  transition:background .2s ease;
  position:relative; overflow:hidden;
}}
.pc-eq:hover {{ background:rgba(6,0,20,.95) !important; }}
.pc-eq .pos-corner {{ display:none; }}
.pc-row1 {{
  display:flex; align-items:center; gap:8px;
}}
.pc-sym {{
  font-family:Consolas,'Courier New',monospace; font-size:11px; font-weight:700;
  letter-spacing:.06em; flex-shrink:0;
}}
.pc-badge {{
  font-family:Consolas,monospace; font-size:8px; font-weight:400;
  letter-spacing:.08em; padding:1px 4px;
  border-radius:0; flex-shrink:0; text-transform:uppercase;
}}
.pc-badge-hold {{ color:rgba(0,200,140,.65); border:1px solid rgba(0,200,140,.2); }}
.pc-badge-sell {{ color:rgba(220,160,0,.65);  border:1px solid rgba(220,160,0,.2); }}
.pc-val {{
  margin-left:auto; font-family:'Orbitron',Consolas,monospace; font-size:11px;
  font-weight:700; color:#ffffff; font-variant-numeric:tabular-nums;
  letter-spacing:-.01em;
}}
/* ── Equity tile new layout ── */
.pc-entry-price {{
  font-family:Consolas,monospace; font-size:8px; margin-top:3px;
  font-variant-numeric:tabular-nums;
}}
.pc-bottom-row {{
  display:flex; align-items:center; gap:8px; margin-top:6px;
}}
.pc-hold-timer {{
  font-family:Consolas,monospace; font-size:8px; color:rgba(255,255,255,0.75);
  font-variant-numeric:tabular-nums; white-space:nowrap;
}}
.pc-xp-wrap {{
  flex:1; height:3px; background:rgba(255,255,255,0.08); border-radius:2px; overflow:hidden;
}}
.pc-xp-fill {{
  height:100%; background:linear-gradient(90deg,#4488ff,#9944ff);
  border-radius:2px; transition:width 4s cubic-bezier(.1,0,.2,1);
}}
/* value scramble flash */
@keyframes pc-val-flash {{
  0%,100% {{ opacity:1; }} 50% {{ opacity:.4; }}
}}
.pc-val-flashing {{ animation:pc-val-flash .06s steps(2,end) 3 forwards; }}
.pc-pnl-pct {{
  font-family:Consolas,monospace; font-size:9px; opacity:.55; margin-left:3px;
}}
.pc-prox-wrap  {{ position:relative; margin-top:4px; }}
.pc-prox-labels {{ display:flex; justify-content:space-between; height:10px; margin-bottom:2px; }}
.pc-prox-stop,.pc-prox-tgt {{
  font-family:Consolas,monospace; font-size:8px; color:rgba(200,200,210,.35);
}}
.pc-prox-cur {{
  position:absolute; transform:translateX(-50%);
  font-family:Consolas,monospace; font-size:8px; color:rgba(255,255,255,.6); white-space:nowrap;
}}
.pc-prox-track {{
  position:relative; height:2px; background:rgba(255,255,255,.06); overflow:visible;
}}
.pc-prox-fill  {{ height:100%; transition:width 1.2s ease; opacity:.6; }}
.pc-prox-dot {{
  position:absolute; top:50%; transform:translate(-50%,-50%);
  width:5px; height:5px; border-radius:50%;
  border:1px solid rgba(0,0,0,.4); transition:left 1.2s ease;
}}
.pc-meta  {{ display:flex; justify-content:space-between; margin-top:4px; }}
.pc-days  {{ font-family:Consolas,monospace; font-size:8px; color:rgba(0,200,220,.5); }}
.pc-entry {{ font-family:Consolas,monospace; font-size:8px; color:rgba(140,110,170,.4); }}
.pc-status {{
  font-family:Consolas,monospace; font-size:8px; letter-spacing:.06em;
  padding-top:4px; border-top:1px solid rgba(255,255,255,.04);
  text-transform:uppercase;
}}
.pc-status-hold {{ color:rgba(0,170,100,.5); }}
.pc-status-sell {{ color:rgba(210,160,0,.5); }}

/* ── Equity tile game-feel: sweeping scanline + flash animations ── */
@keyframes pc-scan {{
  0%   {{ left:-100%; }}
  100% {{ left:200%; }}
}}
@keyframes pc-tick-up {{
  0%   {{ color:#00ff9d; text-shadow:0 0 12px #00ff9d, 0 0 4px #00ff9d; }}
  80%  {{ color:#00ff9d; }}
  100% {{ color:inherit; text-shadow:none; }}
}}
@keyframes pc-tick-down {{
  0%   {{ color:#ff3366; text-shadow:0 0 12px #ff3366, 0 0 4px #ff3366; }}
  80%  {{ color:#ff3366; }}
  100% {{ color:inherit; text-shadow:none; }}
}}
.pc-eq {{ overflow:hidden; }}
.pc-eq::after {{
  content:'';
  position:absolute; top:0; left:-100%; width:40%; height:100%;
  background:linear-gradient(90deg,transparent,rgba(255,0,204,.06),transparent);
  pointer-events:none;
  animation:pc-scan 4s linear infinite;
  animation-delay:var(--pc-scan-delay,0s);
}}
.pc-val.pc-tick-up   {{ animation:pc-tick-up   .6s ease-out forwards; }}
.pc-val.pc-tick-down {{ animation:pc-tick-down  .6s ease-out forwards; }}
.pc-live-dot {{
  display:inline-block; width:4px; height:4px; border-radius:50%;
  background:#ff00cc; margin-right:5px; flex-shrink:0;
  animation:pdot 1.4s ease-in-out infinite;
  box-shadow:0 0 6px rgba(255,0,204,.8);
}}

/* ── Crypto tiles — terminal row style ── */
#pos-left .pos-card {{
  padding:5px 10px 5px 10px;
  background:rgba(0,0,8,.88) !important;
  border:none !important;
  border-left:3px solid !important; /* ticker color inline */
  border-bottom:1px solid rgba(255,255,255,.04) !important;
  transition:background .2s ease;
  position:relative; overflow:hidden;
}}
#pos-left .pos-card::before {{ display:none; }} /* no scanlines */
#pos-left .pos-card > * {{ position:relative; z-index:1; }}
#pos-left .pos-card:hover {{ background:rgba(6,0,20,.95) !important; }}
#pos-left .pos-corner {{ display:none; }}
#pos-left .pos-acq-flash {{
  font:600 8px Consolas,monospace; letter-spacing:.14em; text-transform:uppercase;
}}
#pos-left .pos-top {{
  display:flex; justify-content:space-between; align-items:center; gap:6px;
}}
#pos-left .pos-sym {{
  font-family:Consolas,'Courier New',monospace; font-size:11px; font-weight:700;
  letter-spacing:.06em;
}}
#pos-left .pos-qty {{ display:none; }}
#pos-left .pos-val {{
  font-family:Consolas,monospace; font-size:9px; font-variant-numeric:tabular-nums;
  color:rgba(255,255,255,.28); margin-left:auto;
}}
#pos-left .pos-hval {{
  font-family:Consolas,monospace; font-size:11px; font-weight:700;
  font-variant-numeric:tabular-nums; color:#00ff9d; margin-left:auto;
}}
#pos-left .pos-entry-sub {{
  display:flex; justify-content:space-between; align-items:center; margin-top:2px;
}}
#pos-left .pos-epx {{
  font-family:Consolas,monospace; font-size:9px; opacity:.5;
}}
#pos-left .pos-pnl-live {{
  font-family:Consolas,monospace; font-size:10px; font-weight:600;
  font-variant-numeric:tabular-nums; transition:color .3s;
}}
#pos-left .pos-hold {{ display:none; }}
#pos-left .pos-hold-sub {{ display:none; }}
#pos-left .pos-prox-wrap {{ margin-top:4px; padding:0; }}
#pos-left .pos-age-bar {{ display:none !important; }}

/* Scan spark — tiny white flare on proximity dot */
@keyframes prox-dot-spark {{
  0%   {{ box-shadow:0 0 0 0 rgba(255,255,255,0); transform:translate(-50%,-50%) scale(1); }}
  25%  {{ box-shadow:0 0 6px 3px rgba(255,255,255,.55); transform:translate(-50%,-50%) scale(1.55); }}
  100% {{ box-shadow:0 0 0 0 rgba(255,255,255,0); transform:translate(-50%,-50%) scale(1); }}
}}
.pos-card-scanning .pos-prox-dot,
.pos-card-scanning .pc-prox-dot {{
  animation:prox-dot-spark .55s ease-out forwards;
}}

.pos-top {{ display:flex; align-items:baseline; gap:6px; line-height:1.3; }}
.pos-sym {{ font-weight:700; font-size:15px; }}
.pos-qty {{ color:#3a1a5a; font-size:10px; }}
.pos-val {{ color:#9060b8; font-size:12px; font-weight:700; margin-left:auto; }}
.pos-pnl-line {{ font-size:10px; margin-top:1px; }}
.pos-hold {{ font-size:8.5px; color:#4a2a6a; margin-top:2px; letter-spacing:.02em; }}
.pos-hold.active  {{ color:#1a6a2a; }}
.pos-hold.exiting {{ color:#7a3a0a; }}
/* ── Buy console (bottom-right) ── */
/* Buy console — single inline row in arcade font */
#buy-console {{
  position:fixed; bottom:16px; right:16px; z-index:300;
  display:flex; align-items:center; gap:0;
  font-family:'Press Start 2P',monospace; font-size:9px;
  color:rgba(0,255,157,.55);
  background:transparent;
  white-space:nowrap;
}}
#buy-console .bc-lbl {{
  letter-spacing:.04em; pointer-events:none; padding-right:6px;
}}
#bc-amt {{
  background:transparent; border:none; border-bottom:1px solid rgba(0,255,157,.25);
  outline:none; width:64px; text-align:center;
  font:inherit; font-size:9px; color:#00ff9d; padding:1px 2px;
  text-shadow:0 0 8px rgba(0,255,157,.5);
}}
#bc-amt::placeholder {{ color:rgba(0,255,157,.18); font-family:'Press Start 2P',monospace; font-size:9px; }}
#bc-sym {{
  background:transparent; border:none; border-bottom:1px solid rgba(64,196,255,.25);
  outline:none; width:72px; text-align:center;
  font:inherit; font-size:9px; color:#40c4ff; padding:1px 2px; text-transform:uppercase;
  text-shadow:0 0 8px rgba(64,196,255,.4);
}}
#bc-sym::placeholder {{ color:rgba(64,196,255,.18); font-family:'Press Start 2P',monospace; font-size:9px; }}
datalist {{ display:none; }}
#bc-buy {{
  background:transparent; border:none; outline:none;
  font:inherit; font-size:9px; color:#00ff9d; letter-spacing:.06em;
  cursor:pointer; padding-left:8px;
  text-shadow:0 0 10px rgba(0,255,157,.6);
  transition:text-shadow .1s;
}}
#bc-buy:hover {{ text-shadow:0 0 18px rgba(0,255,157,1); }}
#bc-buy:disabled {{ opacity:.3; cursor:default; }}
#bc-status {{
  font-family:'Press Start 2P',monospace; font-size:7px;
  letter-spacing:.04em; padding-left:8px;
  color:rgba(0,255,157,.4); transition:color .2s;
  min-width:0;
}}
/* Double-click hint on tiles */
.tc-dblclick-hint {{
  position:fixed; z-index:400; pointer-events:none;
  font:700 8px Consolas,monospace; letter-spacing:.14em;
  color:#ff3366; text-shadow:0 0 8px rgba(255,51,102,.6);
  animation:tc-hint-fade .6s ease forwards;
}}
@keyframes tc-hint-fade {{
  0% {{ opacity:1; transform:translateY(0); }}
  100% {{ opacity:0; transform:translateY(-18px); }}
}}
/* ── Runner health chip ── */
#runner-health {{
  display:flex; align-items:center; gap:5px; padding:0 10px; flex-shrink:0;
}}
#runner-dot {{
  width:6px; height:6px; border-radius:50%; flex-shrink:0;
  transition:background .4s, box-shadow .4s;
}}
#runner-dot.ok  {{ background:#00ff9d; box-shadow:0 0 8px rgba(0,255,157,.8); animation:pdot 1.6s ease-in-out infinite; }}
#runner-dot.warn {{ background:#ff9900; box-shadow:0 0 8px rgba(255,153,0,.8); animation:pdot .8s ease-in-out infinite; }}
#runner-dot.dead {{ background:#ff3366; box-shadow:0 0 8px rgba(255,51,102,.8); animation:pdot .4s ease-in-out infinite; }}
#runner-age {{ font:700 9px Consolas,monospace; letter-spacing:.04em; transition:color .4s; }}
#runner-trades {{ font-size:6.5px; color:#3a1a4a; letter-spacing:.18em; text-transform:uppercase; }}
/* ── Position age bar ── */
.pos-age-bar {{
  height:4px; margin-top:5px; border-radius:2px;
  background:rgba(255,255,255,.14);
  position:relative; overflow:visible;
}}
.pos-age-fill {{
  height:100%; border-radius:2px;
  transition:width 1.2s linear, background .4s, box-shadow .4s;
  background:#00c8ff;
  box-shadow:0 0 7px rgba(0,200,255,.75);
}}
.pos-age-sell {{
  position:absolute; right:0; top:-10px;
  font-size:7px; font-weight:900; letter-spacing:.25em;
  color:#ff3355; opacity:0; pointer-events:none;
  transition:opacity .2s;
}}
.pos-age-sell.show {{ opacity:1; animation:sell-pulse .45s ease-in-out infinite; }}
@keyframes sell-pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}
/* ── Stop / Target range bar ── */
}}
.pos-range-bar {{
  height:3px; margin-top:3px; display:flex; overflow:hidden; border-radius:1px;
}}
.pos-range-stop   {{ background:rgba(255,51,102,.38); }}
.pos-range-marker {{ width:1px; background:rgba(255,255,255,.4); flex-shrink:0; }}
.pos-range-target {{ background:rgba(0,255,157,.28); }}
.pos-range-labels {{
  display:flex; justify-content:space-between;
  font-size:6.5px; color:#2a1a4a; letter-spacing:.03em; margin-top:1px;
}}
/* ── Live proximity meter — 3-zone stop/target bar ── */
.pos-prox-wrap {{ margin-top:5px; padding:0; }}
.pos-prox-labels-row {{
  display:flex; justify-content:space-between; align-items:center;
  margin-bottom:3px; font:400 8px Consolas,monospace; letter-spacing:.02em;
}}
.prox-lbl-stop  {{ color:#ff3366; opacity:.7; }}
.prox-lbl-arrow {{ color:rgba(255,255,255,.25); font-size:8px; }}
.prox-lbl-tgt   {{ color:#00ff9d; opacity:.7; }}
/* pixel-block track — no rounded corners */
.pos-prox-track {{
  position:relative; height:6px; border-radius:0; overflow:visible;
  background:rgba(255,255,255,.06);
  image-rendering:pixelated;
}}
/* zone segments */
.pos-prox-zone-stop {{
  position:absolute; left:0; top:0; height:100%; border-radius:0;
  background:rgba(255,51,102,.22);
}}
.pos-prox-zone-tgt {{
  position:absolute; right:0; top:0; height:100%; border-radius:0;
  background:rgba(0,255,157,.15);
}}
/* pixel fill — segmented look via repeating-linear-gradient */
.pos-prox-fill {{
  position:absolute; left:0; top:0; height:100%; border-radius:0;
  transition:width .5s steps(20,end), background .4s;
  background:linear-gradient(90deg,rgba(255,51,102,.7) 0%,rgba(255,153,0,.8) 45%,rgba(0,229,255,.9) 100%);
  overflow:hidden;
}}
.pos-prox-fill::after {{
  content:''; position:absolute; inset:0;
  background:repeating-linear-gradient(90deg,transparent 0px,transparent 3px,rgba(0,0,0,.25) 3px,rgba(0,0,0,.25) 4px);
}}
/* square pixel cursor */
.pos-prox-cursor {{
  position:absolute; top:50%; transform:translate(-50%,-50%);
  width:6px; height:10px; border-radius:0;
  transition:left .5s steps(20,end), background .4s, box-shadow .4s;
  background:#fff; box-shadow:0 0 8px #fff, 0 0 3px #fff;
  z-index:2;
}}
@keyframes prox-danger {{
  0%,100%{{box-shadow:0 0 5px #ff3366,0 0 12px rgba(255,51,102,.6)}}
  50%{{box-shadow:0 0 10px #ff3366,0 0 22px rgba(255,51,102,.9)}}
}}
@keyframes prox-target {{
  0%,100%{{box-shadow:0 0 5px #00ff9d,0 0 12px rgba(0,255,157,.6)}}
  50%{{box-shadow:0 0 10px #00ff9d,0 0 22px rgba(0,255,157,.9)}}
}}
.pos-prox-cursor.danger {{ background:#ff3366; animation:prox-danger .7s ease-in-out infinite; }}
.pos-prox-cursor.target {{ background:#00ff9d; animation:prox-target .7s ease-in-out infinite; }}
/* price label that floats above cursor */
.pos-prox-live {{
  position:absolute; top:-13px; transform:translateX(-50%);
  font:700 6px Consolas,monospace; letter-spacing:.04em;
  white-space:nowrap; pointer-events:none;
  transition:left .7s cubic-bezier(.22,1,.36,1), color .4s;
}}
@keyframes prox-tick-up {{ 0%{{transform:translateX(-50%) translateY(0)}} 35%{{transform:translateX(-50%) translateY(-2px)}} 100%{{transform:translateX(-50%) translateY(0)}} }}
@keyframes prox-tick-dn {{ 0%{{transform:translateX(-50%) translateY(0)}} 35%{{transform:translateX(-50%) translateY(2px)}} 100%{{transform:translateX(-50%) translateY(0)}} }}
.prox-tick-up {{ animation:prox-tick-up .22s ease-out; }}
.prox-tick-dn {{ animation:prox-tick-dn .22s ease-out; }}
/* ── Equity pipeline countdown ── */
#equity-countdown {{
  padding:6px 12px 4px; font-size:7px; letter-spacing:.18em;
  text-transform:uppercase; color:#2a1a4a; border-top:1px solid #0d0020;
  display:flex; align-items:center; gap:6px; margin-top:auto;
}}
#equity-countdown .eq-pip-bar {{
  flex:1; height:2px; background:#0d0020; border-radius:1px; overflow:hidden;
}}
#equity-countdown .eq-pip-fill {{
  height:100%; border-radius:1px; background:#9060b8;
  transition:width 1s linear;
}}
.eq-pip-label {{ white-space:nowrap; }}
/* ── Crypto cycle label in pos-left ── */
#crypto-cycle-chip {{
  padding:4px 12px; font-size:7px; letter-spacing:.18em;
  text-transform:uppercase; color:#2a1a4a; border-top:1px solid #0d0020;
  display:flex; align-items:center; gap:6px; margin-top:auto;
}}
#crypto-cycle-chip .cc-bar {{
  flex:1; height:2px; background:#0d0020; border-radius:1px; overflow:hidden;
}}
#crypto-cycle-chip .cc-fill {{
  height:100%; border-radius:1px; background:#00e5ff;
  transition:width .25s linear;
}}
/* ── Position card corner brackets ── */
.pos-corner {{ position:absolute; width:10px; height:10px; border-style:solid; pointer-events:none; z-index:5; opacity:0; transition:opacity .2s; }}
.pos-corner.tl {{ top:-1px; left:-1px; border-width:2px 0 0 2px; }}
.pos-corner.tr {{ top:-1px; right:-1px; border-width:2px 2px 0 0; }}
.pos-corner.bl {{ bottom:-1px; left:-1px; border-width:0 0 2px 2px; }}
.pos-corner.br {{ bottom:-1px; right:-1px; border-width:0 2px 2px 0; }}
.pos-card:hover .pos-corner, .pos-card.pos-card-active .pos-corner {{ opacity:1; }}
/* ── Acquired flash ── */
.pos-acq-flash {{ position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:7px;letter-spacing:.28em;text-transform:uppercase;font-weight:700;pointer-events:none;z-index:10;opacity:0; }}
@keyframes acq-flash {{ 0%{{opacity:1}} 50%{{opacity:.7}} 100%{{opacity:0}} }}
.pos-acq-flash.show {{ animation:acq-flash .7s ease-out forwards; }}
/* ── Active breathing glow ── */
@keyframes pos-breathe {{ 0%,100%{{box-shadow:none}} 50%{{box-shadow:0 0 10px rgba(0,229,255,.12)}} }}
.pos-card.pos-card-active {{ animation:pos-breathe 3s ease-in-out infinite; }}
/* ── Position card enter/exit animations ── */
/* ── Card enter: pixel scanline wipe from top ── */
@keyframes card-enter {{
  0%   {{ opacity:0; transform:scaleY(0); filter:brightness(5) saturate(0); }}
  20%  {{ opacity:1; transform:scaleY(1); filter:brightness(3) saturate(0); }}
  60%  {{ filter:brightness(2) saturate(2); }}
  100% {{ filter:brightness(1) saturate(1); }}
}}
@keyframes card-arcade-in {{
  0%   {{ clip-path:inset(0 0 100% 0); filter:brightness(6) saturate(0); }}
  40%  {{ clip-path:inset(0 0 55% 0);  filter:brightness(3) saturate(.5); }}
  70%  {{ clip-path:inset(0 0 15% 0);  filter:brightness(1.5) saturate(1); }}
  100% {{ clip-path:inset(0 0 0% 0);   filter:brightness(1) saturate(1); }}
}}
.pos-card-entering {{
  clip-path:inset(0 0 100% 0);
  animation:card-arcade-in .28s steps(12,end) forwards;
  transform-origin:top;
}}
@keyframes card-clip-reveal {{
  0%   {{ clip-path:inset(0 0 100% 0); box-shadow:0 0 0 1px rgba(0,180,255,0); filter:brightness(2.5) saturate(0); }}
  30%  {{ box-shadow:0 0 20px 2px rgba(0,180,255,.55), inset 0 0 12px rgba(0,180,255,.15); filter:brightness(1.8) saturate(1.5); }}
  70%  {{ clip-path:inset(0 0 0% 0); box-shadow:0 0 12px 1px rgba(0,180,255,.3); filter:brightness(1.2) saturate(1.2); }}
  100% {{ clip-path:inset(0 0 0% 0); box-shadow:none; filter:brightness(1) saturate(1); }}
}}

/* ── Phase 1: Target-lock overlay that appears ON the tile ── */
.card-target-lock {{
  position:absolute; inset:-2px; z-index:50; pointer-events:none;
  border:2px solid transparent;
  animation:card-target-in .3s steps(4,end) forwards;
}}
@keyframes card-target-in {{
  0%   {{ border-color:transparent; box-shadow:none; opacity:0; }}
  30%  {{ border-color:rgba(255,255,255,.5); opacity:.6; }}
  60%  {{ border-color:#fff; box-shadow:inset 0 0 10px rgba(255,255,255,.25); opacity:1; }}
  85%  {{ border-color:#fff; box-shadow:inset 0 0 22px rgba(255,255,255,.45), 0 0 28px rgba(255,255,255,.7); opacity:1; }}
  100% {{ border-color:var(--tc,#fff); box-shadow:inset 0 0 32px rgba(255,255,255,.6), 0 0 40px var(--tc,#fff); opacity:1; }}
}}
/* Crosshair corner brackets inside the overlay */
.card-target-lock::before,
.card-target-lock::after {{
  content:''; position:absolute;
  width:8px; height:8px;
  border-color:var(--tc,#fff); border-style:solid;
  opacity:.9;
}}
.card-target-lock::before {{ top:2px; left:2px; border-width:2px 0 0 2px; }}
.card-target-lock::after  {{ bottom:2px; right:2px; border-width:0 2px 2px 0; }}

/* ── Phase 1: white flash → B&W quantized fade — compositor-only (no layout/paint) ── */
@keyframes card-flash-bw {{
  0%   {{ opacity:1; }}
  14%  {{ opacity:1; }}   /* hold white */
  28%  {{ opacity:.6; }}  /* step down */
  42%  {{ opacity:1; }}   /* flicker */
  57%  {{ opacity:.3; }}  /* step */
  71%  {{ opacity:.7; }}  /* flicker */
  85%  {{ opacity:.1; }}
  100% {{ opacity:0; }}
}}
.pos-card-flash-exit {{
  animation:card-flash-bw .22s steps(7,end) forwards;
  /* cheap white-out via outline rather than filter */
  outline:3px solid rgba(255,255,255,.9);
  outline-offset:-1px;
}}
/* ── Legacy hit/destroy — kept for non-exit uses ── */
@keyframes card-hit-blink {{
  0%,100% {{ opacity:1; }}
  50%     {{ opacity:.05; }}
}}
.pos-card-hit {{ animation:card-hit-blink .08s steps(2,end) 5 forwards; }}
@keyframes card-8bit-destroy {{
  0%   {{ opacity:1; }}
  20%  {{ opacity:0; }}
  40%  {{ opacity:1; }}
  60%  {{ opacity:0; }}
  80%  {{ opacity:.4; }}
  100% {{ opacity:0; }}
}}
/* Placeholder that holds the dead tile's space in the flex column */
.pos-card-ghost-space {{
  flex-shrink:0; pointer-events:none; overflow:hidden; background:transparent;
  width:130px; box-sizing:border-box;
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  padding:4px 8px; opacity:0; transition:opacity .12s;
  font-family:Consolas,monospace; font-size:9px;
}}
.pos-card-ghost-space.ghost-pnl-showing {{ opacity:1; }}
.pos-card-ghost-space .gc-sym {{ color:rgba(255,255,255,.25); letter-spacing:.1em; font-size:7px; text-transform:uppercase; }}
.pos-card-ghost-space .gc-pnl {{
  font-family:'Orbitron',Consolas,monospace; font-weight:900; letter-spacing:.04em;
  font-size:13px; font-variant-numeric:tabular-nums;
  text-shadow:0 0 12px currentColor, 0 0 28px currentColor;
}}
@keyframes ghost-pnl-exit {{
  0%   {{ opacity:1; transform:none; filter:none; }}
  60%  {{ opacity:1; transform:translateX(-2px); filter:brightness(1); }}
  70%  {{ opacity:1; transform:translateX(3px) scaleX(1.04); filter:brightness(8) saturate(0); }}
  80%  {{ opacity:.5; transform:translateX(-4px) scaleX(.96); filter:brightness(0); }}
  90%  {{ opacity:.2; transform:translateX(2px); filter:brightness(4) saturate(0); }}
  100% {{ opacity:0; transform:translateX(0) scaleY(0); filter:brightness(0); }}
}}
.pos-card-ghost-space.ghost-pnl-exiting {{
  animation:ghost-pnl-exit .45s steps(6,end) forwards;
}}
/* Ghost collapses in quantized steps — feels like a board clearing, not a scroll */
.pos-card-ghost-collapsing {{
  transition:height .32s steps(7,end) !important;
  height:0 !important; opacity:0 !important;
}}
/* Equity section — multi-column wrap, new columns grow leftward */
#pos-equity-section {{
  display:flex; flex-direction:column; flex-wrap:wrap;
  align-content:flex-end;  /* columns stack from right edge leftward */
  height:100%; overflow:hidden;
}}
/* Remaining tiles glitch-snap when they receive new space */
@keyframes tile-shuffle-land {{
  0%   {{ transform:translateX(-4px); filter:brightness(2) saturate(0); }}
  25%  {{ transform:translateX(3px);  filter:brightness(3) saturate(0); }}
  50%  {{ transform:translateX(-2px); filter:brightness(1.5); }}
  75%  {{ transform:translateX(1px);  filter:brightness(1.2); }}
  100% {{ transform:translateX(0);    filter:brightness(1); }}
}}
.pos-card-shuffle-land {{ animation:tile-shuffle-land .18s steps(4,end) forwards; }}
.pos-card-exiting,
.pos-card-exit-target,
.pos-card-exit-stop,
.pos-card-exit-timeout,
.pos-card-exit-rev     {{ animation:card-8bit-destroy .72s linear forwards; }}
/* ── PnL ghost — video-game exit ── */
/* ── P&L ghost — 80s arcade score-popup, floats left of tile column ── */
@keyframes pnl-ghost-pop {{
  0%   {{ transform:translateY(0);   opacity:0; }}
  10%  {{ transform:translateY(-4px); opacity:1; }}
  70%  {{ transform:translateY(-18px); opacity:1; }}
  100% {{ transform:translateY(-32px); opacity:0; }}
}}
@keyframes pnl-particle {{
  0%   {{ transform:translate(0,0); opacity:1; }}
  100% {{ transform:translate(var(--px),var(--py)); opacity:0; }}
}}
@keyframes card-flash-exit {{
  0%   {{ box-shadow:inset 0 0 0 1px transparent; }}
  15%  {{ box-shadow:inset 0 0 0 2px var(--flash-col,#fff), 0 0 24px 4px var(--flash-col,#fff); filter:brightness(2.2); }}
  100% {{ box-shadow:inset 0 0 0 1px transparent; filter:brightness(1); }}
}}
.pnl-ghost {{
  position:fixed; pointer-events:none; z-index:9999;
  display:flex; flex-direction:column; align-items:flex-end; gap:2px;
  white-space:nowrap;
  animation:pnl-ghost-pop 1.1s ease-out forwards;
}}
.pnl-ghost .pg-val {{
  font-family:'Bangers','Silkscreen',Consolas,monospace;
  font-size:20px; letter-spacing:.08em; font-variant-numeric:tabular-nums;
  text-shadow:0 0 18px currentColor, 0 0 6px currentColor;
}}
.pnl-ghost .pg-price {{
  font-family:'Silkscreen',Consolas,monospace;
  font-size:9px; letter-spacing:.04em; opacity:.7; text-align:right;
}}
.pnl-particle {{
  position:fixed; pointer-events:none; z-index:9998; border-radius:0;
  animation:pnl-particle var(--dur,.6s) steps(6,end) forwards;
}}
/* ── Ambient canvas (behind chart content) ── */
#ambient-canvas {{
  position:absolute; inset:0; pointer-events:none; z-index:10;
}}
/* ── CRT scanlines over chart ── */
#main-area::before {{
  content:''; position:absolute; inset:0; pointer-events:none; z-index:11;
  background:repeating-linear-gradient(
    0deg,
    transparent 0px, transparent 2px,
    rgba(30,0,50,.028) 3px
  );
  animation:scan-drift 8s linear infinite;
}}
@keyframes scan-drift {{
  from {{ background-position:0 0; }}
  to   {{ background-position:0 -12px; }}
}}
/* ── Crosshair overlay ── */
#crosshair-overlay {{
  position:absolute; inset:0; pointer-events:none; z-index:15;
  opacity:0;
}}
#xhair-canvas {{ position:absolute; inset:0; }}
/* ── Portfolio line oscillating glow ── */
@keyframes port-glow {{
  0%,100% {{ filter:drop-shadow(0 0 2px #ff00cc) drop-shadow(0 0 6px rgba(255,0,204,.4)); }}
  50%      {{ filter:drop-shadow(0 0 10px #ff00cc) drop-shadow(0 0 28px rgba(255,0,204,.65)) drop-shadow(0 0 50px rgba(255,0,204,.25)); }}
}}
.portfolio-glow {{ animation:port-glow 2.4s ease-in-out infinite; }}
/* ── Daily PnL bar ── */
#daily-bar {{
  height:3px; flex-shrink:0; background:#0a0018; position:relative; overflow:visible; z-index:20;
}}
#daily-bar-fill {{
  position:absolute; top:0; left:0; height:100%;
  transition:width .8s cubic-bezier(.22,1,.36,1), background .4s;
  background:linear-gradient(90deg,#00ff9d,#00e5ff);
}}
#daily-bar-label {{
  position:absolute; right:10px; top:-12px;
  font:700 8px Consolas,monospace; letter-spacing:.08em;
  color:#3a1a5a; white-space:nowrap;
}}
/* ── Streak chip ── */
#streak-chip {{
  display:flex; align-items:center; gap:5px; padding:0 10px;
  flex-shrink:0;
}}
.streak-val {{
  font:700 11px Consolas,monospace; letter-spacing:.04em;
}}
.streak-label {{ font-size:6.5px; color:#3a1a4a; letter-spacing:.22em; text-transform:uppercase; }}
/* ── Win rate badge on position cards ── */
.win-badge {{
  font-size:8px; font-weight:700; letter-spacing:.06em;
  padding:1px 4px; border-radius:2px; margin-left:auto; flex-shrink:0;
}}
/* ── Projected return label ── */
.nv-proj {{
  font-size:8px; color:#3a1a5a; display:block; margin-top:5px; letter-spacing:.04em;
  border-top:1px solid #1a0028; padding-top:4px;
}}
/* ── Orb-side batch P&L popup ── */
#orb-batch-popup {{
  position:absolute; pointer-events:none; z-index:30;
  font-family:'Bangers','Silkscreen',Consolas,monospace;
  font-size:18px; letter-spacing:.08em; font-variant-numeric:tabular-nums;
  opacity:0; white-space:nowrap;
  text-shadow:0 0 18px currentColor, 0 0 6px currentColor;
  transition:opacity 1.2s ease;
}}
@keyframes orb-popup-drift {{
  from {{ transform:translate(-100%,-50%) translateX(0px);   }}
  to   {{ transform:translate(-100%,-50%) translateX(-60px); }}
}}
</style>
</head>
<body>

<!-- flex child 1: topbar -->
<div class="topbar">
  <div style="align-self:flex-start;display:flex;line-height:0;flex-shrink:0">{_BLOB_SVG}</div>
  <div id="wallet-selector" onclick="_cycleWallet()" title="Switch portfolio">
    <span id="wallet-mode-icon">◈</span>
    <span id="wallet-mode-label">PAPER</span>
    <span id="wallet-mode-chevron">▾</span>
  </div>
  <div class="tb-hg" style="border-left:none">
    <span class="tb-hg-label">STRATEGY</span>
    <div class="tb-hg-row">
      <div id="strat-health-dot"></div>
      <span id="strat-health-label" class="tb-hg-val">—</span>
    </div>
  </div>
  <div class="tb-hg">
    <span class="tb-hg-label">NET DATA</span>
    <div class="tb-hg-row">
      <span class="sysh-dot" id="sysh-mktdata"></span>
      <span class="tb-hg-val" id="sysh-mktdata-val">—</span>
    </div>
  </div>
  <div class="tb-hg">
    <span class="tb-hg-label">DATABASE</span>
    <div class="tb-hg-row">
      <span class="sysh-dot" id="sysh-db"></span>
      <span class="tb-hg-val" id="sysh-db-val">—</span>
    </div>
  </div>
  <div class="tb-hg">
    <span class="tb-hg-label">HEARTBEAT</span>
    <span class="tb-hg-val" id="sysh-hb">—</span>
  </div>
  <div class="tb-hg">
    <span class="tb-hg-label">LATENCY</span>
    <span class="tb-hg-val" id="sysh-lat">—</span>
  </div>
  <div class="tb-hg">
    <span class="tb-hg-label">API REQ/MIN</span>
    <span class="tb-hg-val" id="sysh-rpm">—</span>
  </div>
  <div class="tb-hg">
    <span class="tb-hg-label">CLOCK DRIFT</span>
    <span class="tb-hg-val" id="sysh-drift">—</span>
  </div>
  <div class="spacer"></div>
  <!-- hidden elements kept for JS read-backs -->
  <div id="runner-health" style="display:none">
    <div id="runner-dot" class="warn"></div>
    <div>
      <div id="runner-age" style="color:#3a1a5a">—</div>
      <div id="runner-trades" class="runner-trades">0 trades today</div>
      <div id="runner-countdown" style="font:700 8px Consolas,monospace;letter-spacing:.06em;color:#2a1040">next: —</div>
    </div>
  </div>
  <span id="hdr-winrate" style="display:none">—</span>
  <span id="streak-val" style="display:none">—</span>
  <button id="fs-btn" onclick="_toggleFullscreen()" title="Fullscreen (borderless)" style="
    background:none;border:1px solid #2a003d;color:#3a1a5a;cursor:pointer;
    font:700 8px Consolas,monospace;letter-spacing:.12em;padding:3px 7px;
    border-radius:2px;transition:color .2s,border-color .2s,box-shadow .2s;
    flex-shrink:0;text-transform:uppercase;
  ">⛶ FS</button>
</div>
<!-- sys-health-bar retired — all indicators now live in topbar -->
<!-- ── Stratagem HUD bar ── -->
<div id="strat-bar">
  <div class="strat-slot" id="ss-runner">
    <div class="ss-icon">⚡</div>
    <div class="ss-name">RUNNER</div>
    <div class="ss-status" id="ss-runner-st">—</div>
  </div>
  <div class="strat-slot" id="ss-pipeline">
    <div class="ss-icon">↯</div>
    <div class="ss-name">TRADES</div>
    <div class="ss-trades-row">
      <div class="ss-trades-anchor">
        <span class="ss-status" id="ss-pipeline-st">—</span>
        <span class="ss-trades-chip" id="ss-trades-chip"></span>
      </div>
    </div>
  </div>
  <div class="strat-slot" id="ss-positions" style="position:relative;overflow:visible">
    <div class="ss-wallet-row">
      <div class="ss-wallet-anchor">
        <span class="ss-wallet-chip" id="ss-wallet-chip"></span>
        <span class="ss-wallet-val" id="ss-wallet-val">—</span>
      </div>
    </div>
    <!-- callout rail drops from the bottom of this tile -->
    <div id="callout-rail"></div>
  </div>
  <div class="strat-slot" id="ss-queue" style="cursor:pointer;position:relative;user-select:none" onclick="window._toggleQueueDropdown()">
    <div class="ss-icon">⚡</div>
    <div class="ss-name">QUEUED EVENTS</div>
    <div class="ss-status" id="ss-queue-st">—</div>
  </div>
  <!-- Queued events dropdown -->
  <div id="queue-dropdown" style="display:none;position:fixed;z-index:9999;background:rgba(4,0,12,.97);border:1px solid rgba(148,0,255,.35);border-radius:2px;min-width:340px;padding:6px 0;font-family:Consolas,monospace;box-shadow:0 8px 32px rgba(0,0,0,.8)">
    <div style="font-size:7px;letter-spacing:.2em;color:rgba(148,0,255,.5);padding:6px 14px 4px;text-transform:uppercase">upcoming events</div>
    <div id="queue-dropdown-items"></div>
  </div>
  <div class="strat-slot" id="ss-nav">
    <div class="ss-icon">◉</div>
    <div class="ss-name">CURRENT POS</div>
    <div class="ss-trades-row">
      <div class="ss-trades-anchor">
        <span class="ss-status" id="ss-nav-st">—</span>
        <span class="ss-wallet-chip" id="ss-nav-chip"></span>
      </div>
    </div>
  </div>
  <div class="strat-slot" id="ss-exposure" style="cursor:pointer;position:relative;user-select:none" onclick="window._toggleStratDropdown()">
    <div class="ss-icon">◈</div>
    <div class="ss-name">STRATEGIES</div>
    <div class="ss-status" id="ss-exposure-st">—</div>
  </div>
  <!-- Strategies dropdown -->
  <div id="strat-dropdown" style="display:none;position:fixed;z-index:9999;background:rgba(4,0,12,.97);border:1px solid rgba(148,0,255,.35);border-radius:2px;min-width:280px;padding:6px 0;font-family:Consolas,monospace;box-shadow:0 8px 32px rgba(0,0,0,.8)">
    <div style="font-size:7px;letter-spacing:.2em;color:rgba(148,0,255,.5);padding:6px 14px 4px;text-transform:uppercase">active strategies</div>
    <div id="strat-dropdown-items"></div>
  </div>
  <div class="strat-slot" id="ss-tph">
    <div class="ss-icon">⚡</div>
    <div class="ss-name">$/HR</div>
    <div class="ss-status" id="ss-tph-st">—</div>
  </div>
</div>
<div id="daily-bar" style="display:none">
  <div id="daily-bar-fill" style="width:0%"></div>
  <span id="daily-bar-label"></span>
</div>

<!-- flex child 2: chart + floating overlays -->
<div id="main-area">
  <div id="chart"></div>
  <canvas id="nav-canvas" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:12"></canvas>
  <canvas id="ambient-canvas"></canvas>
  <canvas id="pulse-canvas"></canvas>
  <div id="orb-batch-popup"></div>
  <div id="trade-veil"></div>
  <div id="crosshair-overlay"><canvas id="xhair-canvas"></canvas></div>
  <!-- hidden compat stubs — JS refs still work, nothing visible -->
  <span id="om-today" style="display:none">0</span>
  <span id="trades-combo-chip" style="display:none"></span>
  <span id="total-pnl-val" style="display:none" data-raw="{_total_pnl}">{_pnl_str}</span>
  <span id="batch-pnl-chip" style="display:none"></span>
  <span id="om-openpos" style="display:none">{n_positions}</span>
  <span id="pos-combo-chip" style="display:none"></span>
  <span id="om-dpnl" style="display:none">{dpnl_str}</span>
  <span id="om-tph" style="display:none">—</span>
  <span id="om-winrate" style="display:none">—</span>
  <span id="om-streak-orb" style="display:none">—</span>
  <span id="total-pnl-sub" style="display:none">{_pnl_pct_str}</span>
  <div class="legend-strip">
    <div class="leg-item">
      <div class="leg-dot" style="background:#ff00cc;box-shadow:0 0 6px rgba(255,0,204,.7);"></div>
      <span class="leg-name">PORTFOLIO</span>
      <span class="leg-val" style="color:#ff00cc">{nav_str}</span>
      <span class="leg-ret" style="color:{ret_color}">{ret_str}</span>
    </div>
    <div class="leg-item">
      <div class="leg-dot" style="background:#00e5ff;box-shadow:0 0 6px rgba(0,229,255,.7);"></div>
      <span class="leg-name">SPY</span>
      <span class="leg-val" style="color:#00e5ff">{spy_norm_latest}</span>
      <span class="leg-ret" style="color:#00e5ff">{spy_ret}</span>
    </div>
    <div class="leg-item">
      <div class="leg-dot" style="background:#9400ff;box-shadow:0 0 6px rgba(148,0,255,.7);"></div>
      <span class="leg-name">QQQ</span>
      <span class="leg-val" style="color:#9400ff">{qqq_norm_latest}</span>
      <span class="leg-ret" style="color:#9400ff">{qqq_ret}</span>
    </div>
  </div>

  <!-- Left overlay: System Feed -->
  <div id="feed-overlay">
    <div id="term-clock" class="te" style="flex-shrink:0;border-bottom:1px solid rgba(255,255,255,.06);padding-bottom:5px;margin-bottom:2px"></div>
    <div id="term-body">
      {term_rows}
    </div>
    <div id="feed-bottom-bar">
      <span id="feed-last-ago" style="font:700 7px Consolas,monospace;letter-spacing:.14em;color:#3a1a5a;flex:1;display:none">—</span>
      <button id="mute-btn" onclick="_toggleMute()" title="Toggle sound">
        <span id="mute-icon">♪</span>
        <span id="mute-label">ON</span>
      </button>
      <button id="fs-btn2" onclick="_toggleFullscreen()" title="Fullscreen — keeps screen on, click other monitors freely" style="
        background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.12);
        cursor:pointer;padding:4px 9px;display:flex;align-items:center;gap:4px;
        font-family:Consolas,'Courier New',monospace;font-size:9px;font-weight:700;
        letter-spacing:.18em;color:rgba(255,255,255,.55);transition:all .15s;
        pointer-events:auto;margin-left:4px;
      ">⛶</button>
    </div>
  </div>

  <!-- Right overlay: Positions -->
  <div id="pos-overlay">
    <canvas id="particle-canvas"></canvas>
    <div class="panel-hdr"><div class="term-dot"></div>POSITIONS</div>
    <div id="pos-body">
      <div id="pos-left">
        <div class="pos-section-label">crypto</div>
        <div id="pos-crypto-section"></div>
        <div id="crypto-cycle-chip">
          <span class="eq-pip-label" id="crypto-cycle-label">next scan</span>
          <div class="cc-bar"><div class="cc-fill" id="crypto-cycle-fill" style="width:0%"></div></div>
          <span id="crypto-cycle-eta" style="font-size:7px;color:#2a1a4a;letter-spacing:.04em">—</span>
        </div>
      </div>
      <div id="pos-right">
        <div id="tile-headings"></div>
        <canvas id="eq-tiles-canvas" style="display:block;flex-shrink:0;margin-top:16px"></canvas>
        <div id="equity-countdown">
          <span class="eq-pip-label" id="eq-pip-label">equity pipeline</span>
          <div class="eq-pip-bar"><div class="eq-pip-fill" id="eq-pip-fill" style="width:0%"></div></div>
          <span id="eq-pip-eta" style="font-size:7px;color:#2a1a4a;letter-spacing:.04em">—</span>
        </div>
      </div>
    </div>
  </div>

</div>


<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script>
// Supabase credentials — declared here so all block-1 functions can reach them
var SUPA_URL = 'https://seeevuklabvhkawawtxn.supabase.co';
var SUPA_KEY = 'sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY';

var _eqCanvasInitData = {_eq_canvas_tiles_j};
var _queuedActionsData = {_queued_actions_js};
var _allTickers = {_all_tickers_j};
var portDates  = {port_dates_j};
var portValues = {port_values_j};
var markTs     = {mark_ts_j};
var markVals   = {mark_vals_j};
// Strip initial inflated value from May 2026 double-run (> 1.5x starting capital)
(function() {{
  var cap = 150000;
  var clean = []; var cleanD = [];
  for (var i = 0; i < portValues.length; i++) {{
    if (portValues[i] <= cap) {{ clean.push(portValues[i]); cleanD.push(portDates[i]); }}
  }}
  // Only apply filter if at least one clean value remains; otherwise keep all data
  if (clean.length) {{ portValues = clean; portDates = cleanD; }}
}})();
window._portfolioBaseline = portValues.length ? portValues[portValues.length-1] : 100000;
var spyDates   = {spy_dates_j};
var spyNorm    = {spy_norm_j};
var qqqDates   = {qqq_dates_j};
var qqqNorm    = {qqq_norm_j};

// Nav snapshots seeded at render time — chart draws immediately, no wait for Supabase poll
window._navDbPts = {nav_snap_pts_j};

var latestDate = portDates.length ? portDates[portDates.length-1] : null;

// Right edge: tomorrow as date string (Plotly date axis uses date-only strings throughout)
function _datePlus(days) {{
  var d = new Date(); d.setDate(d.getDate() + days);
  return d.toISOString().slice(0,10);
}}
function _dateMinus(isoDateStr, days) {{
  var d = new Date(isoDateStr + 'T00:00:00Z');
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0,10);
}}
function _datePlus_from(isoDateStr, days) {{
  var d = new Date(isoDateStr + 'T00:00:00Z');
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0,10);
}}

var latestPortDate = portDates.length ? portDates[portDates.length - 1] : null;
// Fixed x range: portfolio start → tomorrow. No auto-scrolling.
var xStart = portDates.length ? portDates[0] : '2026-05-29';
var xEnd   = _datePlus(1);

// ── Benchmark trajectories ───────────────────────────────────────────────
var _benchStart = portDates.length ? new Date(portDates[0]+'T00:00:00Z') : new Date('2026-05-29T00:00:00Z');
var _benchEnd   = new Date();
var _hysaDates = [], _hysaVals = [], _tgt20Dates = [], _tgt20Vals = [];
(function() {{
  var d = new Date(_benchStart);
  var msPerYear = 365.25 * 24 * 3600 * 1000;
  while (d <= _benchEnd) {{
    var iso = d.toISOString().split('T')[0];
    var yr  = (d - _benchStart) / msPerYear;
    _hysaDates.push(iso);  _hysaVals.push(100000 * Math.pow(1.048, yr));
    _tgt20Dates.push(iso); _tgt20Vals.push(100000 * Math.pow(1.20,  yr));
    d.setDate(d.getDate() + 1);
  }}
}})();

var traces = [
  // 0-5: hidden stubs — keep index positions for any code that references them
  {{ x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' }},
  {{ x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' }},
  {{ x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' }},
  {{ x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' }},
  {{ x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' }},
  {{ x:[], y:[], visible:false, showlegend:false, hoverinfo:'skip', type:'scatter' }},
  // Index 6: Portfolio — the only visible line
  {{
    x:[], y:[], name:'PORTFOLIO',
    type:'scatter', mode:'lines',
    line:{{ color:'rgba(255,0,204,0.9)', width:2 }},
    hovertemplate:'<b style="color:#ff00cc">PORTFOLIO $%{{y:,.0f}}</b><extra></extra>',
    showlegend:false,
  }},
  // Trade event markers — ENTER (index 7), EXIT (index 8)
  {{
    x:[], y:[], text:[], name:'ENTER',
    type:'scatter', mode:'markers+text',
    marker:{{ symbol:'triangle-up', size:18, color:'rgba(0,255,157,0.92)',
              line:{{ color:'rgba(0,255,157,.9)', width:2.5 }},
              gradient:{{ type:'none' }} }},
    textposition:'top center',
    textfont:{{ family:'Consolas', size:8.5, color:'rgba(0,255,157,1)' }},
    hovertemplate:'<b style="color:#00ff9d">ENTER %{{text}}</b><extra></extra>',
  }},
  {{
    x:[], y:[], text:[], name:'EXIT',
    type:'scatter', mode:'markers+text',
    marker:{{ symbol:'triangle-down', size:18, color:'rgba(255,51,102,0.92)',
              line:{{ color:'rgba(255,51,102,.9)', width:2.5 }} }},
    textposition:'bottom center',
    textfont:{{ family:'Consolas', size:8.5, color:'rgba(255,51,102,1)' }},
    hovertemplate:'<b style="color:#ff3366">EXIT %{{text}}</b><extra></extra>',
  }},
];

// Milestone y-levels
var _milestones = [97000,98000,99000,101000,102000,103000,104000,105000];
var _milestoneShapes = _milestones.map(function(v) {{
  return {{
    type:'line', xref:'paper', yref:'y',
    x0:0, x1:1, y0:v, y1:v,
    line:{{ color:'rgba(120,0,160,0.18)', width:1, dash:'dot' }},
  }};
}});
// Breakeven zone band ($99.5k – $100.5k)
var _bkZone = [
  {{ type:'rect', xref:'paper', yref:'y', x0:0, x1:1, y0:99500, y1:100500,
     fillcolor:'rgba(255,0,204,0.04)', line:{{ width:0 }}, layer:'below' }},
  {{ type:'line', xref:'paper', yref:'y', x0:0, x1:1, y0:100000, y1:100000,
     line:{{ color:'rgba(255,0,204,0.35)', width:1, dash:'dot' }} }},
];
var shapes = [].concat(_milestoneShapes, _bkZone, latestDate ? [{{
  type:'line', xref:'x', yref:'paper',
  x0:latestDate, x1:latestDate, y0:0, y1:1,
  line:{{ color:'rgba(255,255,255,0.15)', width:1, dash:'dot' }},
}}] : []);

var annotations = latestDate ? [{{
  xref:'x', yref:'paper',
  x:latestDate, y:1.01,
  text:'▶ NOW',
  showarrow:false,
  font:{{ family:'Consolas', size:8, color:'rgba(255,255,255,0.3)' }},
  xanchor:'left',
}}] : [];

var layout = {{
  paper_bgcolor:'#060008',
  plot_bgcolor:'#060008',
  margin:{{ t:30, b:50, l:60, r:16 }},

  xaxis:{{
    autorange:true,
    showgrid:true, gridcolor:'rgba(42,0,61,0.5)', gridwidth:1,
    tickfont:{{ family:'Consolas', size:8, color:'#3a1a4a' }},
    tickformat:'%b %d %H:%M', zeroline:false, showline:false, type:'date', fixedrange:false,
  }},
  yaxis:{{
    autorange:true,
    showgrid:true, gridcolor:'rgba(42,0,61,0.5)', gridwidth:1,
    tickfont:{{ family:'Consolas', size:8, color:'#3a1a4a' }},
    tickformat:'$,.0f',
    zeroline:false, showline:false, fixedrange:false,
    tickprefix:'', nticks:6,
  }},

  shapes, annotations,
  showlegend:false,
  dragmode:'pan',
  hoverlabel:{{ bgcolor:'#0d0010', bordercolor:'#2a003d', font:{{ family:'Consolas', size:9, color:'#f0e0ff' }} }},
  hovermode:'x unified',
}};

var config = {{ scrollZoom:true, displayModeBar:false, responsive:true }};
var gd = document.getElementById('chart');

// ── Ambient canvas — night sky + drifting blobs ─────────
var ambCanvas = document.getElementById('ambient-canvas');
(function() {{
  function resizeAmb() {{ ambCanvas.width=window.innerWidth; ambCanvas.height=window.innerHeight; }}
  resizeAmb();
  window.addEventListener('resize', resizeAmb);
  var t = 0;

  // ── Star field: three depth layers moving right→left ──────────────────────
  var _starLayers = [
    {{ count:140, speed:0.25, r:0.55, a:0.22, cr:220, cg:220, cb:255 }}, // far — blue-white
    {{ count:55,  speed:1.1,  r:0.9,  a:0.30, cr:0,   cg:220, cb:255 }}, // mid — cyan
    {{ count:20,  speed:2.8,  r:1.4,  a:0.38, cr:180, cg:0,   cb:255 }}, // near — purple
  ];
  var _stars = [];
  _starLayers.forEach(function(l) {{
    for (var i = 0; i < l.count; i++) {{
      _stars.push({{
        x: Math.random(), y: Math.random(),
        speed: l.speed + Math.random() * l.speed * 0.4,
        r: l.r + Math.random() * 0.3,
        a: l.a * (0.6 + Math.random() * 0.4),
        cr: l.cr, cg: l.cg, cb: l.cb,
      }});
    }}
  }});

  // Hyperspeed streaks
  var _streaks = [];

  var blobs = [
    {{ rx:.18, ry:.55, cr:148, cg:0,   cb:255, a:.11,  sx:.00017, sy:.00011 }},
    {{ rx:.78, ry:.28, cr:0,   cg:229, cb:255, a:.08,  sx:-.00013,sy:.00009 }},
    {{ rx:.45, ry:.80, cr:255, cg:0,   cb:204, a:.065, sx:.00009, sy:-.00015}},
    {{ rx:.88, ry:.65, cr:0,   cg:255, cb:157, a:.05,  sx:-.00011,sy:.00007 }},
  ];
  var phases = blobs.map(function(_,i){{ return i * 1.57; }});
  function drawAmb() {{
    var ctx = ambCanvas.getContext('2d');
    var W = ambCanvas.width, H = ambCanvas.height;
    ctx.clearRect(0,0,W,H);
    t += 0.005;

    // ── Stars moving right→left ────────────────────────────────────────────
    _stars.forEach(function(s) {{
      s.x -= s.speed / W;
      if (s.x < -0.01) {{ s.x = 1.02 + Math.random() * 0.05; s.y = Math.random(); }}
      ctx.beginPath();
      ctx.arc(s.x * W, s.y * H, s.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + s.cr + ',' + s.cg + ',' + s.cb + ',' + s.a + ')';
      ctx.fill();
    }});

    // ── Hyperspeed streaks (rare, fast layer) ──────────────────────────────
    if (Math.random() < 0.018) {{
      var _spLen = 0.04 + Math.random() * 0.10;
      _streaks.push({{
        x: 1.0 + Math.random() * 0.05, y: Math.random(),
        len: _spLen, a: 0.45 + Math.random() * 0.2,
        speed: 5 + Math.random() * 8,
        cr: Math.random() < 0.5 ? 0 : 180,
        cg: Math.random() < 0.5 ? 229 : 0,
        cb: 255,
      }});
    }}
    for (var si = _streaks.length - 1; si >= 0; si--) {{
      var str = _streaks[si];
      str.x -= str.speed / W;
      str.a -= 0.014;
      if (str.a <= 0 || str.x < -str.len) {{ _streaks.splice(si, 1); continue; }}
      var sg = ctx.createLinearGradient(str.x * W, str.y * H, (str.x + str.len) * W, str.y * H);
      sg.addColorStop(0, 'rgba(' + str.cr + ',' + str.cg + ',' + str.cb + ',0)');
      sg.addColorStop(1, 'rgba(' + str.cr + ',' + str.cg + ',' + str.cb + ',' + str.a + ')');
      ctx.save();
      ctx.strokeStyle = sg;
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo((str.x + str.len) * W, str.y * H);
      ctx.lineTo(str.x * W, str.y * H);
      ctx.stroke();
      ctx.restore();
    }}

    blobs.forEach(function(b,i) {{
      var px = (b.rx + Math.sin(t * b.sx * 1000 + phases[i]) * .15) * W;
      var py = (b.ry + Math.cos(t * b.sy * 1000 + phases[i]) * .12) * H;
      var rr = Math.min(W,H) * (.22 + .06 * Math.sin(t + i));
      var g  = ctx.createRadialGradient(px,py,0,px,py,rr);
      g.addColorStop(0, 'rgba('+b.cr+','+b.cg+','+b.cb+','+b.a+')');
      g.addColorStop(1, 'rgba('+b.cr+','+b.cg+','+b.cb+',0)');
      ctx.beginPath();
      ctx.arc(px,py,rr,0,Math.PI*2);
      ctx.fillStyle = g;
      ctx.fill();
    }});
    // Heartbeat flatline — drawn on same canvas after blobs
    (function() {{
      var baseY = H * 0.88;
      var now2 = Date.now();
      var idle = (now2 - (window._hbLastTrade||now2)) / 1000;
      var alpha = Math.min(1, Math.max(0, (idle - 8) / 4)) * 0.5;
      if (alpha > 0 && !window._hbSpike) {{
        var t2 = now2 / 1000;
        var drift = Math.sin(t2 * 0.4) * 3;
        ctx.save();
        ctx.strokeStyle = 'rgba(0,229,255,' + (alpha * 0.55) + ')';
        ctx.lineWidth = 1;
        ctx.shadowColor = 'rgba(0,229,255,' + (alpha * 0.25) + ')';
        ctx.shadowBlur = 5;
        ctx.beginPath();
        ctx.moveTo(0, baseY + drift);
        for (var x = 0; x <= W; x += 4) {{
          var noise = Math.sin(x * 0.08 + t2 * 1.2) * 0.8 + Math.sin(x * 0.31 + t2 * 0.7) * 0.4;
          ctx.lineTo(x, baseY + drift + noise * alpha * 3);
        }}
        ctx.stroke();
        ctx.restore();
      }}
      if (window._hbSpike) {{
        var sp = window._hbSpike;
        sp.t += 0.022;
        var col2 = sp.col;
        var spA = Math.max(0, 1 - sp.t / 0.7);
        var spikeH = H * 0.28 * Math.min(1, sp.t * 8);
        var cx2 = W * 0.5;
        ctx.save();
        ctx.strokeStyle = 'rgba('+col2[0]+','+col2[1]+','+col2[2]+','+spA+')';
        ctx.lineWidth = 1.5;
        ctx.shadowColor = 'rgba('+col2[0]+','+col2[1]+','+col2[2]+','+(spA*0.7)+')';
        ctx.shadowBlur = 10;
        ctx.beginPath();
        ctx.moveTo(0, baseY); ctx.lineTo(cx2-60, baseY); ctx.lineTo(cx2-20, baseY);
        ctx.lineTo(cx2, baseY - spikeH); ctx.lineTo(cx2+8, baseY + spikeH*0.3);
        ctx.lineTo(cx2+24, baseY); ctx.lineTo(W, baseY);
        ctx.stroke();
        ctx.restore();
        if (sp.t >= 0.7) window._hbSpike = null;
      }}
    }})();
    requestAnimationFrame(drawAmb);
  }}
  // Heartbeat state (shared with drawAmb)
  window._hbLastTrade = Date.now();
  window._hbSpike = null;
  window._triggerHeartbeat = function(isWin) {{
    window._hbLastTrade = Date.now();
    window._hbSpike = {{ t: 0, col: isWin ? [0,255,157] : [255,51,102] }};
  }};
  drawAmb();
}})();


// ── Pulsing canvas dots ────────────────────────────────
var canvas = document.getElementById('pulse-canvas');
function resizeCanvas() {{ var ma=document.getElementById('main-area'); if(!ma) return; var r=ma.getBoundingClientRect(); canvas.width=r.width||800; canvas.height=r.height||500; }}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

var pulseTargets = [];

// ── Orb state ─────────────────────────────────────────────────────────────────
var _orbFlash = {{ active: false, isEntry: true, isWin: false, t: 0, dur: 1400 }};
var _orbBurstCount = 0;
var _liveTip = {{ pts: [] }};

// Shockwaves: array of {{age, col, cx, cy}}
var _shockWaves = [];

// Smoothed orb position — lerped toward true Plotly position each frame
var _smoothPcx = null, _smoothPcy = null;
// Smoothed orbit radii per symbol
var _smoothOrbitR = {{}};
// Entry age per symbol (frames since first seen) — drives fade-in
var _satEntryAge = {{}};

// Combo streak display
var _comboCount = 0;
var _comboFlash = null; // {{age, text, col}}
var _comboLastAt = 0;  // timestamp of last _comboCount increment — drives auto-fade

// Satellite orbit angles: symbol → angle (radians)
var _satAngles = {{}};
// Satellites currently animating out: symbol → {{angle, orbitR, sr, sg, sb, age}}
var _satExiting = {{}};

// NAV particle system — small sparks that react to live price ticks
var _navParticles = [];  // {{x,y,vx,vy,life,maxLife,r,g,b,size}}
var _lastNavForParticles = null;

window._spawnNavParticles = function(cx, cy, isUp) {{
  var col = isUp ? [0,255,157] : [255,51,102];
  var count = 6 + Math.floor(Math.random()*4);
  for (var i=0; i<count; i++) {{
    var angle  = Math.random() * Math.PI * 2;
    var speed  = 0.4 + Math.random() * 1.2;
    var drift  = isUp ? -1 : 1;  // float up for gains, fall for losses
    _navParticles.push({{
      x: cx + (Math.random()-0.5)*8,
      y: cy + (Math.random()-0.5)*8,
      vx: Math.cos(angle)*speed*0.6,
      vy: Math.sin(angle)*speed*0.4 + drift*(0.3+Math.random()*0.5),
      life: 1.0,
      decay: 0.018 + Math.random()*0.012,
      r: col[0], g: col[1], b: col[2],
      size: 1.2 + Math.random()*1.8,
    }});
  }}
  // Trim to max 120 particles
  if (_navParticles.length > 120) _navParticles = _navParticles.slice(-120);
}};

window._orbTradeFlash = function(isEntry, isWin) {{
  _orbFlash.active = true;
  _orbFlash.isEntry = isEntry;
  _orbFlash.isWin   = isWin;
  _orbFlash.t = Date.now();
  _orbBurstCount = isEntry ? 6 : 5;
  // Spawn 5 shockwave rings staggered — use nav-canvas center (same coord space)
  {{
    try {{
      var scx = (window._navOrbFracX !== undefined ? window._navOrbFracX : 0.5) * canvas.width;
      var scy = (window._navOrbFracY !== undefined ? window._navOrbFracY : 0.5) * canvas.height;
      if (isFinite(scx) && isFinite(scy)) {{
        var scol = isEntry ? [255,255,255] : (isWin ? [0,255,157] : [255,51,102]);
        for (var si=0; si<5; si++) {{
          (function(delay,offset) {{
            setTimeout(function() {{
              _shockWaves.push({{ age:offset, col:scol, cx:scx, cy:scy }});
            }}, delay);
          }})(si*75, si*0.06);
        }}
      }}
    }} catch(e) {{}}
  }}
}};

// Called by block 2 on EXIT result (win/loss) to drive combo counter
window._orbComboResult = function(isWin) {{
  if (isWin) {{
    _comboCount++;
    _comboLastAt = Date.now();
    var txt = _comboCount >= 10 ? '⚡ SURGE' : _comboCount >= 5 ? 'HOT STREAK' : '+WIN';
    _comboFlash = {{ age:0, text:txt, col:[0,255,157] }};
  }} else {{
    if (_comboCount > 1) {{
      _comboFlash = {{ age:0, text:'CHAIN BROKEN', col:[255,51,102] }};
    }}
    _comboCount = 0;
  }}
}};

function buildTargets() {{
  pulseTargets = [];
  // trace order: 0=baseline(skip), 1=SPY, 2=QQQ, 3=PORTFOLIO ghost, 4=PORTFOLIO
  [[1,[0,229,255]], [2,[148,0,255]], [4,[255,0,204]]].forEach(function(ic) {{
    var tr = gd.data[ic[0]];
    if (tr && tr.x && tr.x.length) {{
      var pt = {{ x: tr.x[tr.x.length-1], y: tr.y[tr.y.length-1], rgb: ic[1] }};
      pulseTargets.push(pt);
    }}
  }});
  // If intraday trace (6) has newer data, update portfolio orb position
  var intra = gd.data[6];
  if (intra && intra.x && intra.x.length) {{
    // Move portfolio dot to latest intraday position
    var pi = pulseTargets.findIndex(function(p) {{ return p.rgb[0]===255 && p.rgb[2]===204; }});
    if (pi >= 0 && intra.y && intra.y.length) {{
      pulseTargets[pi].x = intra.x[intra.x.length-1];
      pulseTargets[pi].y = intra.y[intra.y.length-1];
    }}
  }}
  // Portfolio trace [4] is an empty stub — synthesize portT from live nav so orb still works
  var _hasPortT = pulseTargets.some(function(t) {{ return t.rgb[0]===255 && t.rgb[2]===204; }});
  if (!_hasPortT && window._lastKnownNav && window._lastKnownTs) {{
    pulseTargets.push({{ x: window._lastKnownTs, y: window._lastKnownNav, rgb: [255,0,204] }});
  }}
  positionPnlFloat();
}}

function positionPnlFloat() {{
  // Dot is always center-screen — panel is CSS-anchored, just ensure visible
  var pf = document.getElementById('pnl-float');
  if (pf) pf.classList.add('visible');
}}

var phase = 0;
var rafId = null;

// ── Compute pressure from live proximity meters (0=calm, 1=at stop) ──────────
function _computePressure() {{
  var maxDanger = 0;
  document.querySelectorAll('.pos-prox-wrap[data-entry]').forEach(function(wrap) {{
    var fill = wrap.querySelector('.pos-prox-fill');
    if (!fill) return;
    var t = parseFloat(fill.style.width) / 100; // 0=at stop, 1=at target
    var danger = 1 - t;
    if (danger > maxDanger) maxDanger = danger;
  }});
  return Math.max(0, Math.min(1, maxDanger));
}}

function drawPulse() {{
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  phase += 0.03;

  // Flash blend state
  var flashAlpha = 0;
  var flashRgb = [255, 0, 204];
  if (_orbFlash.active) {{
    var elapsed = Date.now() - _orbFlash.t;
    flashAlpha = Math.max(0, 1 - elapsed / _orbFlash.dur);
    if (flashAlpha <= 0) {{ _orbFlash.active = false; _orbBurstCount = 0; }}
    else flashRgb = _orbFlash.isEntry ? [255,255,255] : (_orbFlash.isWin ? [0,255,157] : [255,51,102]);
  }}

  // Pressure 0=calm, 1=danger — modulates ring speed, color, tightness
  var pressure = _computePressure();

  // ── SPY / QQQ orbs (unchanged) ────────────────────────────────────────────
  pulseTargets.forEach(function(t) {{
    if (t.rgb[0]===255 && t.rgb[2]===204) return; // portfolio handled separately
    try {{
      var fl = gd._fullLayout;
      if (!fl || !fl.xaxis || !fl.yaxis) return;
      var cx = fl.xaxis.l2p(fl.xaxis.d2l(t.x)) + fl.margin.l;
      var cy = fl.yaxis.l2p(fl.yaxis.d2l(t.y)) + fl.margin.t;
      if (!isFinite(cx) || !isFinite(cy)) return;
      var r=t.rgb[0], g=t.rgb[1], b=t.rgb[2];
      for (var k=0; k<3; k++) {{
        var p = (Math.sin(phase - k*0.9)+1)/2;
        ctx.beginPath();
        ctx.arc(cx, cy, 5+p*22, 0, Math.PI*2);
        ctx.strokeStyle='rgba('+r+','+g+','+b+','+(0.55*(1-p))+')';
        ctx.lineWidth=1.5; ctx.stroke();
      }}
      ctx.shadowColor='rgba('+r+','+g+','+b+',1)'; ctx.shadowBlur=18;
      ctx.beginPath(); ctx.arc(cx,cy,5,0,Math.PI*2);
      ctx.fillStyle='rgba('+r+','+g+','+b+',1)'; ctx.fill();
      ctx.shadowBlur=0;
      ctx.beginPath(); ctx.arc(cx,cy,2,0,Math.PI*2);
      ctx.fillStyle='rgba(255,255,255,.9)'; ctx.fill();
    }} catch(e) {{}}
  }});

  // ── Portfolio orb — pressure aura + flash ─────────────────────────────────
  var portT = pulseTargets.find(function(t) {{ return t.rgb[0]===255 && t.rgb[2]===204; }});
  if (portT) {{
    try {{
      // Nav-canvas always draws curNav at (W/2, H/2) of main-area.
      // Pulse-canvas shares the same coordinate space (both inset:0 in #main-area).
      // Use nav-canvas center directly — avoids Plotly yaxis mismatch (NAV $66K vs SPY $750).
      var _rawPcx, _rawPcy;
      if (window._navOrbFracX !== undefined) {{
        _rawPcx = window._navOrbFracX * canvas.width;
        _rawPcy = window._navOrbFracY * canvas.height;
      }} else {{
        // Fallback: center of main-area via Plotly chart dimensions
        var fl0 = gd._fullLayout;
        if (!fl0) throw '';
        _rawPcx = (fl0.width  || canvas.width)  / 2;
        _rawPcy = (fl0.height || canvas.height) / 2;
      }}
      if (!isFinite(_rawPcx) || !isFinite(_rawPcy)) throw '';
      // Lerp toward true position — smooths discrete Plotly axis jumps
      var _lerpK = 0.12;
      if (_smoothPcx === null) {{ _smoothPcx = _rawPcx; _smoothPcy = _rawPcy; }}
      _smoothPcx += (_rawPcx - _smoothPcx) * _lerpK;
      _smoothPcy += (_rawPcy - _smoothPcy) * _lerpK;
      var pcx = _smoothPcx, pcy = _smoothPcy;

      // ── Comet trail — leftward gradient fade behind the dot ──────────────
      var trailLen = 220;
      var trailGrad = ctx.createLinearGradient(pcx - trailLen, pcy, pcx, pcy);
      trailGrad.addColorStop(0,   'rgba(255,0,204,0)');
      trailGrad.addColorStop(0.5, 'rgba(255,0,204,0.05)');
      trailGrad.addColorStop(1,   'rgba(255,0,204,0.28)');
      // Body of comet — tapered ellipse
      var halfH = 3.5 + pressure * 3;
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(pcx - trailLen/2, pcy, trailLen/2, halfH, 0, 0, Math.PI*2);
      ctx.fillStyle = trailGrad;
      ctx.fill();
      // Bright leading edge glow
      var edgeGrad = ctx.createRadialGradient(pcx, pcy, 0, pcx, pcy, 22);
      edgeGrad.addColorStop(0,   'rgba(255,0,204,0.18)');
      edgeGrad.addColorStop(1,   'rgba(255,0,204,0)');
      ctx.beginPath(); ctx.arc(pcx, pcy, 22, 0, Math.PI*2);
      ctx.fillStyle = edgeGrad; ctx.fill();
      ctx.restore();
      // ─────────────────────────────────────────────────────────────────────

      // Base color: interpolate pink→red with pressure
      var pr = Math.round(255);
      var pg = Math.round(204*(1-pressure)*0.0);
      var pb = Math.round(204*(1-pressure));
      // Flash overrides
      if (flashAlpha > 0) {{
        pr = Math.round(pr*(1-flashAlpha) + flashRgb[0]*flashAlpha);
        pg = Math.round(pg*(1-flashAlpha) + flashRgb[1]*flashAlpha);
        pb = Math.round(pb*(1-flashAlpha) + flashRgb[2]*flashAlpha);
      }}

      // ── Trade flash: radiant glow bloom instead of exploding rings ───────────
      if (flashAlpha > 0) {{
        var bloomR = 14 + flashAlpha * 18;
        var bloomG = ctx.createRadialGradient(pcx, pcy, 2, pcx, pcy, bloomR);
        bloomG.addColorStop(0,   'rgba('+pr+','+pg+','+pb+','+(0.55*flashAlpha)+')');
        bloomG.addColorStop(0.4, 'rgba('+pr+','+pg+','+pb+','+(0.18*flashAlpha)+')');
        bloomG.addColorStop(1,   'rgba('+pr+','+pg+','+pb+',0)');
        ctx.beginPath(); ctx.arc(pcx, pcy, bloomR, 0, Math.PI*2);
        ctx.fillStyle = bloomG; ctx.fill();
        if (_orbBurstCount > 0) _orbBurstCount = Math.max(0, _orbBurstCount-0.04);
      }}

      // Normal pressure rings (always visible, never huge)
      var ringSpeed = 2.0 + pressure * 3.5;
      var ringMax   = 28 - pressure*8;
      var ringCount = 3;

      for (var k=0; k<ringCount; k++) {{
        var p2 = (Math.sin(phase*ringSpeed - k*0.9)+1)/2;
        ctx.beginPath();
        ctx.arc(pcx, pcy, 5+p2*ringMax, 0, Math.PI*2);
        ctx.strokeStyle='rgba('+pr+','+pg+','+pb+','+(0.7*(1-p2))+')';
        ctx.lineWidth=2-k*0.3; ctx.stroke();
      }}

      // Pressure danger pulse — extra outer ring when near stop
      if (pressure > 0.6) {{
        var dp = (Math.sin(phase*6)+1)/2;
        ctx.beginPath();
        ctx.arc(pcx, pcy, 8+dp*(ringMax+16), 0, Math.PI*2);
        ctx.strokeStyle='rgba(255,51,102,'+(0.35*(1-dp)*(pressure-0.6)/0.4)+')';
        ctx.lineWidth=1; ctx.stroke();
      }}

      // Core
      var coreSize = 6;
      ctx.shadowColor='rgba('+pr+','+pg+','+pb+',1)';
      ctx.shadowBlur = 18+pressure*12;
      ctx.beginPath(); ctx.arc(pcx,pcy,coreSize,0,Math.PI*2);
      ctx.fillStyle='rgba('+pr+','+pg+','+pb+',1)'; ctx.fill();
      ctx.shadowBlur=0;
      ctx.beginPath(); ctx.arc(pcx,pcy,2.5,0,Math.PI*2);
      ctx.fillStyle='rgba(255,255,255,.95)'; ctx.fill();

      // ── Scanning pulse — slow dim ring between trades ─────────────────────
      if (!_orbFlash.active || flashAlpha < 0.05) {{
        var scanPhase = (phase * 0.12) % 1;
        var scanR = 10 + scanPhase * 52;
        var scanOp = 0.20 * (1 - scanPhase) * (1 - pressure * 0.5);
        ctx.beginPath(); ctx.arc(pcx, pcy, scanR, 0, Math.PI*2);
        ctx.strokeStyle = 'rgba(255,0,204,' + scanOp.toFixed(3) + ')';
        ctx.lineWidth = 1.2; ctx.stroke();
      }}

      // ── Satellite dots — one per open position (crypto + equity) ─────────
      var cryptoMap  = window._cryptoPositionsMap  || {{}};
      var equityMap  = window._equityPositionsMap  || {{}};
      var posMap = Object.assign({{}}, cryptoMap);
      Object.keys(equityMap).forEach(function(sym) {{
        posMap[sym] = equityMap[sym];
      }});
      var prices  = window._liveProxPrices    || {{}};
      var posSyms = Object.keys(posMap);
      posSyms.forEach(function(sym, idx) {{
        var pos = posMap[sym];
        if (!pos) return;
        var isEquity = !!pos.is_equity;
        var entry  = parseFloat(pos.entry_price);
        var stop   = parseFloat(pos.stop_price);
        var tgt    = parseFloat(pos.target_price || 0) || entry*1.008;
        // Equity: use current_value as live price proxy; crypto: use live proxy prices
        var price  = isEquity ? (parseFloat(pos.current_value) || entry) : (prices[sym] || entry);
        var range  = tgt - stop;
        var t2     = range ? Math.max(0, Math.min(1, (price-stop)/range)) : 0.5;

        // Equity orbs orbit further out so they're visually distinct from crypto
        var _minR = isEquity ? 52 : 20;
        var _maxR = isEquity ? 68 : 44;
        var _targetR = _minR + t2 * (_maxR - _minR);
        if (_smoothOrbitR[sym] === undefined) _smoothOrbitR[sym] = _targetR;
        _smoothOrbitR[sym] += (_targetR - _smoothOrbitR[sym]) * 0.06;
        var orbitR = _smoothOrbitR[sym];

        // Speed: equity slower (long-term hold), crypto faster
        var satSpeed = isEquity
          ? 0.004 + pressure*0.004
          : 0.012 + (1-t2)*0.022 + pressure*0.018;

        if (_satAngles[sym] === undefined) {{
          // New satellite — spawn far out and spiral in
          _satAngles[sym] = idx * (Math.PI*2/Math.max(posSyms.length,1));
          _smoothOrbitR[sym] = _targetR * 3.5;
          _satEntryAge[sym] = 0;
        }}
        if (_satEntryAge[sym] !== undefined && _satEntryAge[sym] < 60) _satEntryAge[sym]++;
        _satAngles[sym] += satSpeed;

        var sx = pcx + Math.cos(_satAngles[sym]) * orbitR;
        var sy = pcy + Math.sin(_satAngles[sym]) * orbitR;

        // Equity: cyan palette. Crypto: red→orange→green by proximity to target
        var sr, sg, sb;
        if (isEquity) {{
          // Cyan-white for equity — always clearly distinct
          sr = Math.round(0   + t2*40);
          sg = Math.round(200 + t2*55);
          sb = Math.round(255);
        }} else {{
          sr = Math.round(255*Math.max(0,1-t2*1.5));
          sg = Math.round(255*Math.min(1,t2*1.8));
          sb = Math.round(102*(1-t2));
        }}

        // Entry fade-in opacity (0→1 over 40 frames)
        var entryAge = _satEntryAge[sym] !== undefined ? _satEntryAge[sym] : 60;
        var entryOp  = Math.min(1, entryAge / 40);
        var isEntering = entryAge < 40;

        // Faint orbit trail
        ctx.beginPath();
        ctx.arc(pcx, pcy, orbitR, 0, Math.PI*2);
        ctx.strokeStyle='rgba('+sr+','+sg+','+sb+','+(0.06*entryOp)+')';
        ctx.lineWidth=.5; ctx.stroke();

        // Entry streak — bright trail behind satellite as it spirals in
        if (isEntering) {{
          var streakLen = (1 - entryOp) * 0.6;
          var sx2 = pcx + Math.cos(_satAngles[sym] - streakLen) * (orbitR * 1.15);
          var sy2 = pcy + Math.sin(_satAngles[sym] - streakLen) * (orbitR * 1.15);
          var sg2 = ctx.createLinearGradient(sx2, sy2, sx, sy);
          sg2.addColorStop(0, 'rgba('+sr+','+sg+','+sb+',0)');
          sg2.addColorStop(1, 'rgba('+sr+','+sg+','+sb+','+(0.7*entryOp)+')');
          ctx.beginPath(); ctx.moveTo(sx2, sy2); ctx.lineTo(sx, sy);
          ctx.strokeStyle = sg2; ctx.lineWidth = 1.5; ctx.stroke();
        }}

        // Satellite dot
        var satPulse = (Math.sin(phase*4 + idx*2.1)+1)/2;
        var satSize  = (2.5 + satPulse*1.5 + (pressure>0.7&&t2<0.2 ? satPulse*2 : 0)) * entryOp;
        ctx.shadowColor='rgba('+sr+','+sg+','+sb+',1)';
        ctx.shadowBlur = (8 + t2*4) * entryOp;
        ctx.beginPath(); ctx.arc(sx,sy,Math.max(0.1,satSize),0,Math.PI*2);
        ctx.fillStyle='rgba('+sr+','+sg+','+sb+','+(0.92*entryOp)+')'; ctx.fill();
        ctx.shadowBlur=0;

        // Connector thread to orb
        ctx.beginPath(); ctx.moveTo(pcx,pcy); ctx.lineTo(sx,sy);
        ctx.strokeStyle='rgba('+sr+','+sg+','+sb+','+(0.08*entryOp)+')';
        ctx.lineWidth=.5; ctx.stroke();
      }});

      // ── Exiting satellites — shoot outward and fade ───────────────────────
      Object.keys(_satExiting).forEach(function(sym) {{
        var e = _satExiting[sym];
        e.age += 0.032;
        var r  = e.orbitR + e.age * 80;   // shoot outward fast
        var op = Math.max(0, 1 - e.age * 2.5);
        if (op <= 0) {{ delete _satExiting[sym]; return; }}
        var sx = pcx + Math.cos(e.angle) * r;
        var sy = pcy + Math.sin(e.angle) * r;
        // Fading streak from orb to satellite
        var streakG = ctx.createLinearGradient(pcx, pcy, sx, sy);
        streakG.addColorStop(0,   'rgba('+e.sr+','+e.sg+','+e.sb+','+(op*0.3)+')');
        streakG.addColorStop(1,   'rgba('+e.sr+','+e.sg+','+e.sb+',0)');
        ctx.beginPath(); ctx.moveTo(pcx, pcy); ctx.lineTo(sx, sy);
        ctx.strokeStyle = streakG; ctx.lineWidth = 1.5; ctx.stroke();
        // Fading dot
        ctx.shadowColor = 'rgba('+e.sr+','+e.sg+','+e.sb+',1)';
        ctx.shadowBlur  = 8 * op;
        ctx.beginPath(); ctx.arc(sx, sy, 2.5*op+0.5, 0, Math.PI*2);
        ctx.fillStyle = 'rgba('+e.sr+','+e.sg+','+e.sb+','+op+')';
        ctx.fill(); ctx.shadowBlur = 0;
      }});

      // ── Combo markers — spawn LEFT of orb, drift further left as they fade ──
      // Positive (win) markers float slightly ABOVE orb Y; losses slightly BELOW.
      if (!window._comboParticles) window._comboParticles = [];
      var _cp = window._comboParticles;
      var _cpNow = Date.now();

      // Spawn combo streak label as a new particle
      if (_comboCount > 0) {{
        var _comboAge2 = (_cpNow - _comboLastAt) / 1000;
        var _comboA2   = _comboAge2 < 3 ? 0.9 : Math.max(0, 0.9 - (_comboAge2 - 3) * 0.6);
        if (_comboA2 > 0 && !window._comboStreakParticle) {{
          // pin the persistent streak label to a stable particle slot
          window._comboStreakParticle = {{
            text: '\xd7'+_comboCount+' COMBO',
            col: _comboCount>=10 ? '0,229,255' : _comboCount>=5 ? '255,170,0' : '255,0,204',
            isWin: true, born: _cpNow, lifetime: 6000, sticky: true
          }};
          _cp.push(window._comboStreakParticle);
        }} else if (window._comboStreakParticle) {{
          // Update streak text as count changes
          window._comboStreakParticle.text = '\xd7'+_comboCount+' COMBO';
          window._comboStreakParticle.col  = _comboCount>=10 ? '0,229,255' : _comboCount>=5 ? '255,170,0' : '255,0,204';
          window._comboStreakParticle.born = _cpNow;
        }}
      }} else {{
        window._comboStreakParticle = null;
      }}
      if (_comboFlash) {{
        _cp.push({{
          text: _comboFlash.text,
          col: _comboFlash.col[0]+','+_comboFlash.col[1]+','+_comboFlash.col[2],
          isWin: _comboFlash.col[1] > 100, // green = win
          born: _cpNow, lifetime: 900, sticky: false
        }});
        _comboFlash = null;
      }}

      // Draw and age all combo particles
      window._comboParticles = _cp.filter(function(p) {{ return _cpNow - p.born < p.lifetime; }});
      window._comboParticles.forEach(function(p) {{
        var age = (_cpNow - p.born) / p.lifetime;
        var alpha = Math.max(0, 1 - age * 1.1);
        if (alpha <= 0) return;
        // Drift left over lifetime; pos above, neg below orb Y
        var drift = age * 90;                          // drifts 90px left over lifetime
        var yOff  = p.isWin ? -14 : 10;               // win=above, loss=below orb center
        var px2   = pcx - 30 - drift;                 // start 30px left of orb center
        var py2   = pcy + yOff;
        var fsize = p.sticky ? Math.min(9 + (_comboCount||1)*0.6, 16) : 8;
        ctx.save();
        ctx.font = 'bold '+Math.round(fsize)+'px Consolas';
        ctx.fillStyle   = 'rgba('+p.col+','+alpha+')';
        ctx.shadowColor = 'rgba('+p.col+','+alpha+')';
        ctx.shadowBlur  = 10 * alpha;
        ctx.textAlign   = 'right';
        ctx.fillText(p.text, px2, py2);
        ctx.restore();
      }});

    }} catch(e) {{}}
  }}

  // ── Shockwave rings — small, local, subtle ───────────────────────────────
  _shockWaves = _shockWaves.filter(function(w) {{ return w.age < 1; }});
  _shockWaves.forEach(function(w) {{
    w.age += 0.04;
    var radius = w.age * 40;
    var alpha  = Math.pow(1-w.age, 2) * 0.3;
    ctx.beginPath();
    ctx.arc(w.cx, w.cy, radius, 0, Math.PI*2);
    ctx.strokeStyle='rgba('+w.col[0]+','+w.col[1]+','+w.col[2]+','+alpha+')';
    ctx.lineWidth = 1;
    ctx.stroke();
  }});

  // ── NAV particles — sparks reacting to live price ticks ─────────────────
  _navParticles = _navParticles.filter(function(p) {{ return p.life > 0; }});
  _navParticles.forEach(function(p) {{
    p.life -= p.decay;
    p.x += p.vx; p.y += p.vy;
    p.vy *= 0.97; p.vx *= 0.96;
    var alpha = p.life * p.life;
    ctx.shadowColor = 'rgba('+p.r+','+p.g+','+p.b+','+(alpha*.9)+')';
    ctx.shadowBlur  = 6 + (1-p.life)*4;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.size*(0.4+p.life*0.6), 0, Math.PI*2);
    ctx.fillStyle = 'rgba('+p.r+','+p.g+','+p.b+','+alpha+')';
    ctx.fill();
    ctx.shadowBlur = 0;
  }});

  // ── Brownian live-tip ─────────────────────────────────────────────────────
  if (portT) {{
    try {{
      var tcx = (window._navOrbFracX !== undefined ? window._navOrbFracX : 0.5) * canvas.width;
      var tcy = (window._navOrbFracY !== undefined ? window._navOrbFracY : 0.5) * canvas.height;
      if (isFinite(tcx) && isFinite(tcy)) {{
        if (!_liveTip.pts.length) _liveTip.pts.push({{dx:0,dy:0}});
        var last2 = _liveTip.pts[_liveTip.pts.length-1];
        var ndx = Math.min(last2.dx + (Math.random()-0.48)*1.1, 52);
        var ndy = last2.dy*0.93 + (Math.random()-0.5)*1.4;
        _liveTip.pts.push({{dx:ndx,dy:ndy}});
        if (_liveTip.pts.length > 80) _liveTip.pts.shift();
        var tn = _liveTip.pts.length;
        ctx.save();
        for (var ti=1; ti<tn; ti++) {{
          var ta = (ti/tn)*0.55;
          var tp0=_liveTip.pts[ti-1], tp1=_liveTip.pts[ti];
          ctx.beginPath();
          ctx.moveTo(tcx+tp0.dx, tcy+tp0.dy);
          ctx.lineTo(tcx+tp1.dx, tcy+tp1.dy);
          ctx.strokeStyle='rgba(255,0,204,'+ta+')';
          ctx.lineWidth=1.1;
          ctx.shadowColor='rgba(255,0,204,'+(ta*.8)+')';
          ctx.shadowBlur=5;
          ctx.stroke();
        }}
        ctx.restore();
      }}
    }} catch(e) {{}}
  }}

  rafId = requestAnimationFrame(drawPulse);
}}

// ── Sound system ─────────────────────────────────────────────────────────
var _audioCtx = null;
var _audioReady = false;
var _audioMuted = false;
function _unlockAudio() {{
  if (_audioReady) return;
  try {{
    _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    var buf = _audioCtx.createBuffer(1, 1, 22050);
    var src = _audioCtx.createBufferSource();
    src.buffer = buf; src.connect(_audioCtx.destination); src.start(0);
    _audioCtx.resume().then(function() {{ _audioReady = true; }});
  }} catch(e) {{}}
}}
// Try to unlock immediately, then on first interaction as fallback
_unlockAudio();
['click','keydown','touchstart'].forEach(function(ev) {{
  document.addEventListener(ev, function _u() {{
    _unlockAudio();
    document.removeEventListener(ev, _u);
  }});
}});
function _toggleMute() {{
  _audioMuted = !_audioMuted;
  var btn   = document.getElementById('mute-btn');
  var icon  = document.getElementById('mute-icon');
  var label = document.getElementById('mute-label');
  if (btn)   btn.classList.toggle('muted', _audioMuted);
  if (icon)  icon.textContent = _audioMuted ? '♪' : '♪';
  if (label) label.textContent = _audioMuted ? 'OFF' : 'ON';
  if (!_audioMuted) _unlockAudio();
}}
function _playTones(freqs, dur, type, stagger, vol) {{
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {{
    if (_audioCtx.state === 'suspended') {{ _audioCtx.resume(); return; }}
    var _stagger = stagger !== undefined ? stagger : 0.09;
    var _vol     = vol     !== undefined ? vol     : 0.12;
    freqs.forEach(function(f, i) {{
      var osc = _audioCtx.createOscillator(), g = _audioCtx.createGain();
      osc.connect(g); g.connect(_audioCtx.destination);
      osc.type = type || 'sine';
      osc.frequency.value = f;
      var t0 = _audioCtx.currentTime + i * _stagger;
      g.gain.setValueAtTime(0, t0);
      g.gain.linearRampToValueAtTime(_vol, t0 + 0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      osc.start(t0); osc.stop(t0 + dur + 0.05);
    }});
  }} catch(e) {{}}
}}
// Acquisition: neutral rising 8-bit blip — two square notes, subtle
window._soundEntry = function() {{
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {{
    var ctx = _audioCtx;
    if (ctx.state === 'suspended') {{ ctx.resume(); return; }}
    [[330, 0], [440, 0.055]].forEach(function(p) {{
      var osc = ctx.createOscillator(), g = ctx.createGain();
      osc.type = 'square'; osc.frequency.value = p[0];
      var t = ctx.currentTime + p[1];
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.055, t+0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, t+0.08);
      osc.connect(g); g.connect(ctx.destination);
      osc.start(t); osc.stop(t+0.10);
    }});
  }} catch(e) {{}}
}};
// Win exit: ascending 8-bit arpeggio (E5→G5→B5) — bright, punchy
window._soundWin = function() {{
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {{
    var ctx = _audioCtx;
    if (ctx.state === 'suspended') {{ ctx.resume(); return; }}
    [[659, 0], [784, 0.07], [988, 0.14]].forEach(function(p) {{
      var osc = ctx.createOscillator(), g = ctx.createGain();
      osc.type = 'square'; osc.frequency.value = p[0];
      var t = ctx.currentTime + p[1];
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.07, t+0.005);
      g.gain.exponentialRampToValueAtTime(0.0001, t+0.11);
      osc.connect(g); g.connect(ctx.destination);
      osc.start(t); osc.stop(t+0.13);
    }});
  }} catch(e) {{}}
}};
// Loss exit: descending 8-bit bloop (G4→Eb4→Bb3) — muted, downward
window._soundLoss = function() {{
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {{
    var ctx = _audioCtx;
    if (ctx.state === 'suspended') {{ ctx.resume(); return; }}
    [[392, 0], [311, 0.07], [233, 0.14]].forEach(function(p) {{
      var osc = ctx.createOscillator(), g = ctx.createGain();
      osc.type = 'square'; osc.frequency.value = p[0];
      var lp = ctx.createBiquadFilter(); lp.type='lowpass'; lp.frequency.value=700;
      var t = ctx.currentTime + p[1];
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.055, t+0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t+0.12);
      osc.connect(lp); lp.connect(g); g.connect(ctx.destination);
      osc.start(t); osc.stop(t+0.14);
    }});
  }} catch(e) {{}}
}};

// ── Fullscreen mode (borderless — keeps screen active, click-through to other monitors) ─
var _wakeLock = null;
async function _acquireWakeLock() {{
  try {{
    if (navigator.wakeLock) {{
      _wakeLock = await navigator.wakeLock.request('screen');
    }}
  }} catch(e) {{}}
}}
function _fsSetActive(on) {{
  var btn  = document.getElementById('fs-btn');
  var btn2 = document.getElementById('fs-btn2');
  if (on) {{
    if (btn)  {{ btn.textContent = '⛶ EXIT'; btn.style.color = '#ff00cc'; btn.style.borderColor = '#ff00cc'; btn.style.boxShadow = '0 0 6px rgba(255,0,204,.4)'; }}
    if (btn2) {{ btn2.textContent = '⛶'; btn2.style.color = '#ff00cc'; btn2.style.borderColor = '#ff00cc'; btn2.style.boxShadow = '0 0 6px rgba(255,0,204,.35)'; }}
  }} else {{
    if (btn)  {{ btn.textContent = '⛶ FS'; btn.style.color = '#3a1a5a'; btn.style.borderColor = '#2a003d'; btn.style.boxShadow = 'none'; }}
    if (btn2) {{ btn2.textContent = '⛶'; btn2.style.color = 'rgba(255,255,255,.55)'; btn2.style.borderColor = 'rgba(255,255,255,.12)'; btn2.style.boxShadow = 'none'; }}
  }}
}}
function _toggleFullscreen() {{
  if (!document.fullscreenElement) {{
    document.documentElement.requestFullscreen().then(function() {{
      _fsSetActive(true);
      _acquireWakeLock();
    }}).catch(function() {{}});
  }} else {{
    document.exitFullscreen().then(function() {{
      _fsSetActive(false);
      if (_wakeLock) {{ _wakeLock.release(); _wakeLock = null; }}
    }}).catch(function() {{}});
  }}
}}
document.addEventListener('visibilitychange', function() {{
  if (document.visibilityState === 'visible' && document.fullscreenElement) _acquireWakeLock();
}});
document.addEventListener('fullscreenchange', function() {{
  if (!document.fullscreenElement) {{
    _fsSetActive(false);
    if (_wakeLock) {{ _wakeLock.release(); _wakeLock = null; }}
  }}
}});

// ── Wallet canvas engine ──────────────────────────────────────────────────────
(function() {{
  var wc = document.getElementById('wallet-canvas');
  if (!wc) return;
  var ctx = wc.getContext('2d');

  // ── State ─────────────────────────────────────────────────────────────────
  var rings    = [];   // {{ r, maxR, alpha, col, speed }}
  var particles= [];   // {{ x,y,vx,vy,r,life,decay,col }}
  var bursts   = [];   // {{ t, isEntry, isWin, x, y }}
  var scanLines= [];   // {{ y, alpha, speed, col }}
  var _velSmooth = 0;  // exponentially smoothed velocity
  var _lastNavVal = null;
  var _trend = 0;      // −1..+1 smoothed P&L trend

  // ── Public API ────────────────────────────────────────────────────────────
  window._walletScan = function() {{
    var W = wc.width, H = wc.height;
    // Expand rings from panel center
    for (var i=0; i<3; i++) {{
      rings.push({{ r:0, maxR:Math.max(W,H)*0.7, alpha:0.55-i*0.12,
                    col:[0,229,255], speed:2.2+i*0.5, delay:i*60 }});
    }}
    // Scanning horizontal lines sweeping downward
    for (var j=0; j<2; j++) {{
      scanLines.push({{ y:-4+(j*8), alpha:0.7, speed:2.5+j, col:[0,229,255,0.4] }});
    }}
  }};

  window._walletTrade = function(isEntry, isWin, sym, price) {{
    var W = wc.width, H = wc.height;
    var cx = W/2, cy = H*0.42;
    var col = isEntry ? [0,255,157] : (isWin ? [255,153,0] : [255,51,102]);

    // Burst ring
    rings.push({{ r:0, maxR:W*0.6, alpha:0.8, col:col, speed:4 }});

    // Directional particles
    var count = 18;
    for (var i=0; i<count; i++) {{
      var angle = (Math.PI*2/count)*i + (Math.random()-.5)*.4;
      var speed = 1.5 + Math.random()*2.5;
      var vy0 = isEntry ? -Math.abs(Math.sin(angle)*speed)-0.3 : Math.abs(Math.sin(angle)*speed)+0.3;
      particles.push({{
        x:cx + (Math.random()-.5)*20, y:cy,
        vx:Math.cos(angle)*speed*0.6,
        vy:vy0,
        r:1.2+Math.random()*2, life:1,
        decay:0.012+Math.random()*0.016, col:col
      }});
    }}

    // Update event ticker
    var ticker = document.getElementById('wallet-event-ticker');
    if (ticker) {{
      var arrow = isEntry ? '▲ ENTER' : '▼ EXIT';
      var tCol = isEntry ? '#00ff9d' : (isWin ? '#ff9900' : '#ff3366');
      ticker.textContent = arrow + (sym ? '  ' + sym.replace('/USD','') : '') + (price ? '  $' + price : '');
      ticker.style.color = tCol;
      ticker.style.textShadow = '0 0 10px ' + tCol;
      setTimeout(function() {{
        ticker.style.color = 'rgba(255,255,255,.2)';
        ticker.style.textShadow = 'none';
      }}, 4000);
    }}
  }};

  // Called every time NAV updates — feed into velocity smoothing
  window._walletNavUpdate = function(newNav) {{
    if (_lastNavVal !== null) {{
      var delta = newNav - _lastNavVal;
      var pct   = delta / 100000; // fraction of starting capital
      _velSmooth = _velSmooth * 0.75 + pct * 0.25; // EMA
    }}
    _lastNavVal = newNav;
    _trend = Math.max(-1, Math.min(1, (_velSmooth * 2000)));

    // Update momentum bar
    var track = document.getElementById('wallet-vel-track');
    var fill  = document.getElementById('wallet-vel-fill');
    if (track && fill) {{
      var tw = track.offsetWidth || 140;
      var half = tw / 2;
      var bar = Math.abs(_trend) * half;
      if (_trend >= 0) {{
        fill.style.left = half + 'px';
        fill.style.width = bar + 'px';
        fill.style.background = 'linear-gradient(90deg,rgba(0,255,157,.6),rgba(0,255,157,1))';
        fill.style.color = '#00ff9d';
      }} else {{
        fill.style.left = (half - bar) + 'px';
        fill.style.width = bar + 'px';
        fill.style.background = 'linear-gradient(90deg,rgba(255,51,102,1),rgba(255,51,102,.6))';
        fill.style.color = '#ff3366';
      }}
    }}
  }};

  // ── Resize ────────────────────────────────────────────────────────────────
  function resize() {{ wc.width = wc.offsetWidth; wc.height = wc.offsetHeight; }}
  resize();
  window.addEventListener('resize', resize);

  // ── Helpers ───────────────────────────────────────────────────────────────
  var _t = 0;

  function _trendCols() {{
    // primary color shifts from red → neutral → green based on _trend
    var r = _trend < 0 ? 255 : Math.round(255*(1-_trend));
    var g = _trend > 0 ? 255 : Math.round(255*(1+_trend));
    return [r, g, 80];
  }}

  function _drawSparkline(W, H) {{
    var nh = window._navHistory || [];
    if (nh.length < 2) return;
    var pts = nh.slice().reverse(); // oldest first

    var minV = Infinity, maxV = -Infinity;
    pts.forEach(function(p) {{ if(p.nav<minV)minV=p.nav; if(p.nav>maxV)maxV=p.nav; }});
    var range = maxV - minV || 2000;
    var pad = range * 0.2;
    minV -= pad; maxV += pad;

    var sx = W * 0.08, ex = W * 0.92;
    var sy = H * 0.72, ey = H * 0.88;

    function px(i) {{ return sx + (i/(pts.length-1))*(ex-sx); }}
    function py(v) {{ return ey - ((v-minV)/(maxV-minV))*(ey-sy); }}

    // Glow pass
    var lastVal = pts[pts.length-1].nav;
    var isUp = lastVal >= 100000;
    var glowCol = isUp ? 'rgba(0,255,157,' : 'rgba(255,51,102,';

    ctx.save();
    ctx.lineWidth = 2;
    ctx.strokeStyle = glowCol + '0.7)';
    ctx.shadowColor  = glowCol + '0.5)';
    ctx.shadowBlur   = 12;
    ctx.beginPath();
    for (var i=0; i<pts.length; i++) {{
      var x=px(i), y=py(pts[i].nav);
      if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }}
    ctx.stroke();

    // Fill under curve
    ctx.beginPath();
    for (var i=0; i<pts.length; i++) {{
      var x=px(i), y=py(pts[i].nav);
      if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }}
    ctx.lineTo(px(pts.length-1), ey);
    ctx.lineTo(px(0), ey);
    ctx.closePath();
    ctx.fillStyle = glowCol + '0.06)';
    ctx.fill();

    // Endpoint dot
    var endX = px(pts.length-1), endY = py(lastVal);
    ctx.beginPath();
    ctx.arc(endX, endY, 3, 0, Math.PI*2);
    ctx.fillStyle = isUp ? '#00ff9d' : '#ff3366';
    ctx.shadowColor = isUp ? 'rgba(0,255,157,.9)' : 'rgba(255,51,102,.9)';
    ctx.shadowBlur = 10;
    ctx.fill();

    ctx.restore();
  }}

  function _drawParticles() {{
    for (var i=particles.length-1; i>=0; i--) {{
      var p = particles[i];
      p.x += p.vx; p.y += p.vy;
      p.vy *= 0.97; p.vx *= 0.98;
      p.life -= p.decay;
      if (p.life <= 0) {{ particles.splice(i,1); continue; }}
      var a = p.life * 0.7;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * p.life, 0, Math.PI*2);
      ctx.fillStyle = 'rgba('+p.col[0]+','+p.col[1]+','+p.col[2]+','+a+')';
      ctx.shadowColor= 'rgba('+p.col[0]+','+p.col[1]+','+p.col[2]+','+(a*.5)+')';
      ctx.shadowBlur = 6;
      ctx.fill();
    }}
  }}

  function _drawRings(W, H) {{
    var cx = W/2, cy = H*0.42;
    for (var i=rings.length-1; i>=0; i--) {{
      var ring = rings[i];
      if (ring.delay > 0) {{ ring.delay -= 16; continue; }}
      ring.r += ring.speed;
      ring.alpha *= 0.975;
      if (ring.r > ring.maxR || ring.alpha < 0.005) {{ rings.splice(i,1); continue; }}
      ctx.beginPath();
      ctx.arc(cx, cy, ring.r, 0, Math.PI*2);
      ctx.strokeStyle = 'rgba('+ring.col[0]+','+ring.col[1]+','+ring.col[2]+','+ring.alpha+')';
      ctx.lineWidth = 1.5;
      ctx.shadowColor = 'rgba('+ring.col[0]+','+ring.col[1]+','+ring.col[2]+','+(ring.alpha*.6)+')';
      ctx.shadowBlur = 8;
      ctx.stroke();
    }}
  }}

  function _drawScanLines(W, H) {{
    for (var i=scanLines.length-1; i>=0; i--) {{
      var sl = scanLines[i];
      sl.y += sl.speed; sl.alpha *= 0.97;
      if (sl.y > H || sl.alpha < 0.01) {{ scanLines.splice(i,1); continue; }}
      var g = ctx.createLinearGradient(0,0,W,0);
      g.addColorStop(0,'transparent');
      g.addColorStop(0.2,'rgba('+sl.col[0]+','+sl.col[1]+','+sl.col[2]+','+sl.alpha*0.6+')');
      g.addColorStop(0.5,'rgba('+sl.col[0]+','+sl.col[1]+','+sl.col[2]+','+sl.alpha+')');
      g.addColorStop(0.8,'rgba('+sl.col[0]+','+sl.col[1]+','+sl.col[2]+','+sl.alpha*0.6+')');
      g.addColorStop(1,'transparent');
      ctx.fillStyle = g;
      ctx.fillRect(0, sl.y, W, 2);
    }}
  }}

  function _drawBackground(W, H) {{
    // Ambient radial that breathes with trend
    var breath = 0.5 + 0.5*Math.sin(_t*0.4);
    var isUp = _trend >= 0;
    var bgCol = isUp ? '0,255,157' : '255,51,102';
    var grad = ctx.createRadialGradient(W/2, H*0.42, 0, W/2, H*0.42, W*0.55);
    grad.addColorStop(0,   'rgba('+bgCol+','+(0.025+breath*0.015)+')');
    grad.addColorStop(0.6, 'rgba('+bgCol+',0.005)');
    grad.addColorStop(1,   'rgba('+bgCol+',0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);
  }}

  // ── Main draw loop ─────────────────────────────────────────────────────────
  function draw() {{
    var W = wc.width, H = wc.height;
    ctx.clearRect(0, 0, W, H);
    _t += 0.016;
    ctx.shadowBlur = 0;

    _drawBackground(W, H);
    _drawScanLines(W, H);
    _drawSparkline(W, H);
    _drawRings(W, H);
    _drawParticles();

    requestAnimationFrame(draw);
  }}
  draw();
}})();

// ── C: Particle drift — upward drifting motes in the positions panel ─────────
(function() {{
  var pc = document.getElementById('particle-canvas');
  if (!pc) return;
  var pCtx = pc.getContext('2d');

  // ── Canonical ticker color system ────────────────────────────────────────────
  // Single palette + override map shared by every _symCol site in this file.
  // Override map wins over hash — keeps colliding tickers visually distinct.
  // Override map is persisted to Supabase ticker_colors table so it survives
  // across sessions and machines.
  var PALETTE = ['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
  window._TICKER_OVR = {{ ETH:'#e040fb', CRV:'#f7b731', XTZ:'#00bfff', NUE:'#ff4dd2' }};
  function _hashCol(s) {{ var h=0; for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))&0xffff; return PALETTE[h%PALETTE.length]; }}
  function symCol(s) {{ var c=s.replace('/USD','').replace('USD',''); return window._TICKER_OVR[c]||_hashCol(c); }}

  // Load persisted colors from Supabase on startup — overwrites defaults
  (function() {{
    fetch(SUPA_URL + '/rest/v1/ticker_colors?select=ticker,color',
      {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
    .then(function(r) {{ return r.ok ? r.json() : null; }})
    .then(function(rows) {{
      if (!Array.isArray(rows)) return;
      rows.forEach(function(row) {{
        if (row.ticker && row.color) window._TICKER_OVR[row.ticker] = row.color;
      }});
      // Re-tint any already-painted canvas tiles
      (window._ET||[]).forEach(function(t) {{
        var c = t.sym.replace('/USD','').replace('USD','');
        if (window._TICKER_OVR[c]) t.col = window._TICKER_OVR[c];
      }});
    }}).catch(function() {{}});
  }})();

  // Persist a single color override to Supabase
  window._saveTickerColor = function(ticker, color) {{
    fetch(SUPA_URL + '/rest/v1/ticker_colors',
      {{
        method: 'POST',
        headers: {{
          'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
          'Content-Type': 'application/json',
          'Prefer': 'resolution=merge-duplicates',
        }},
        body: JSON.stringify({{ ticker: ticker, color: color }}),
      }}
    ).catch(function() {{}});
  }};

  var particles = [];
  var MAX_P = 60;

  function _resize() {{ pc.width = pc.offsetWidth; pc.height = pc.offsetHeight; }}
  _resize();
  window.addEventListener('resize', _resize);

  function _getColors() {{
    var cols = [];
    // Crypto positions
    Object.keys(window._cryptoPositionsMap || {{}}).forEach(function(sym) {{
      cols.push(symCol(sym.replace('/USD','')));
    }});
    // Equity positions
    document.querySelectorAll('#pos-equity-section .pos-card[data-sym]').forEach(function(el) {{
      cols.push(symCol(el.getAttribute('data-sym')));
    }});
    return cols.length ? cols : ['#1a0830']; // near-black when flat
  }}

  function _spawn(cols) {{
    var col = cols[Math.floor(Math.random() * cols.length)];
    particles.push({{
      x: Math.random() * pc.width,
      y: pc.height + 4,
      vy: -(0.25 + Math.random() * 0.55),   // slow upward
      vx: (Math.random() - 0.5) * 0.15,
      r:  0.8 + Math.random() * 1.4,
      alpha: 0,
      fadeIn: 0.015 + Math.random() * 0.01,
      life: 1,
      decay: 0.0008 + Math.random() * 0.0012,
      col: col,
    }});
  }}

  var _spawnTick = 0;
  function _drawParticles() {{
    var W = pc.width, H = pc.height;
    pCtx.clearRect(0, 0, W, H);

    var cols = _getColors();
    var nOpen = cols.length;
    // Spawn rate: 1 particle every N frames, scales with open positions
    _spawnTick++;
    var spawnEvery = nOpen === 1 ? 999 : Math.max(8, 60 - nOpen * 3);
    if (_spawnTick % spawnEvery === 0 && particles.length < MAX_P) _spawn(cols);

    for (var i = particles.length - 1; i >= 0; i--) {{
      var p = particles[i];
      p.x  += p.vx;
      p.y  += p.vy;
      p.alpha = Math.min(p.alpha + p.fadeIn, p.life);
      p.life -= p.decay;
      if (p.life <= 0 || p.y < -8) {{ particles.splice(i, 1); continue; }}

      // Parse hex to rgb for alpha blending
      var hex = p.col.replace('#','');
      var r = parseInt(hex.slice(0,2),16), g = parseInt(hex.slice(2,4),16), b = parseInt(hex.slice(4,6),16);
      var a = Math.min(p.alpha, p.life) * 0.55;

      pCtx.beginPath();
      pCtx.arc(p.x, p.y, p.r, 0, Math.PI*2);
      pCtx.fillStyle = 'rgba('+r+','+g+','+b+','+a+')';
      pCtx.shadowColor = 'rgba('+r+','+g+','+b+','+(a*0.6)+')';
      pCtx.shadowBlur = 4;
      pCtx.fill();
    }}
    pCtx.shadowBlur = 0;
    requestAnimationFrame(_drawParticles);
  }}
  _drawParticles();
}})();

// ── ATH tracking ─────────────────────────────────────────────────────────────
var _athNav = Math.max.apply(null, portValues.length ? portValues : [100000]);
var _athTs  = portDates.length ? portDates[portDates.length - 1] : latestDate;
var _athShapeIdx = _milestoneShapes.length + (latestDate ? 1 : 0); // index in shapes array

function _updateAthShape(nav, ts) {{
  if (nav <= _athNav) return;
  _athNav = nav;
  _athTs  = ts;
  var athShape = {{
    type:'line', xref:'paper', yref:'y',
    x0:0, x1:1, y0:_athNav, y1:_athNav,
    line:{{ color:'rgba(0,255,157,0.35)', width:1, dash:'dash' }},
  }};
  var athAnnot = {{
    xref:'paper', yref:'y',
    x:0.01, y:_athNav,
    text:'▲ ATH',
    showarrow:false,
    font:{{ family:'Consolas', size:7, color:'rgba(0,255,157,0.6)' }},
    xanchor:'left', yanchor:'bottom',
  }};
  // Upsert the ATH shape at a known index
  var newShapes = (gd.layout.shapes || []).slice();
  newShapes[_athShapeIdx] = athShape;
  var newAnnots = (gd.layout.annotations || []).slice();
  // Keep existing annotations (NOW marker), add/replace ATH annotation at index 1
  newAnnots[1] = athAnnot;
  Plotly.relayout(gd, {{ shapes: newShapes, annotations: newAnnots }});
}}

// ── Endpoint dot — SVG pulsing circle at current portfolio position ───────────
function _updateEndpointDot(nav, ts) {{
  var svg = gd && gd.querySelector('svg.main-svg');
  if (!svg || !gd._fullLayout) return;
  var fl = gd._fullLayout;
  var xa = fl.xaxis, ya = fl.yaxis;
  if (!xa || !ya || !xa.range || !ya.range) return;

  var tsMs  = new Date(ts).getTime();
  var xMin  = new Date(xa.range[0]).getTime();
  var xMax  = new Date(xa.range[1]).getTime();
  var xFrac = xMax > xMin ? (tsMs - xMin) / (xMax - xMin) : 1;
  var yFrac = ya.range[1] > ya.range[0] ? (nav - ya.range[0]) / (ya.range[1] - ya.range[0]) : 0.5;
  var ml = fl.margin.l, mt = fl.margin.t;
  var cw = fl.width  - fl.margin.l - fl.margin.r;
  var ch = fl.height - fl.margin.t - fl.margin.b;
  var cx = ml + xFrac * cw;
  var cy = mt + (1 - yFrac) * ch;

  // Above/below baseline determines color
  var aboveBase = nav >= 100000;
  var dotCol  = aboveBase ? '#00ff9d' : '#ff3366';
  var ringCol = aboveBase ? 'rgba(0,255,157,' : 'rgba(255,51,102,';

  var g = svg.querySelector('#ep-g');
  if (!g) {{
    g = document.createElementNS('http://www.w3.org/2000/svg','g');
    g.id = 'ep-g';
    // Outer pulse ring
    var r1 = document.createElementNS('http://www.w3.org/2000/svg','circle');
    r1.id = 'ep-ring1'; r1.setAttribute('fill','none'); r1.setAttribute('stroke-width','1');
    g.appendChild(r1);
    // Inner pulse ring
    var r2 = document.createElementNS('http://www.w3.org/2000/svg','circle');
    r2.id = 'ep-ring2'; r2.setAttribute('fill','none'); r2.setAttribute('stroke-width','1');
    g.appendChild(r2);
    // Core dot
    var dot = document.createElementNS('http://www.w3.org/2000/svg','circle');
    dot.id = 'ep-dot'; dot.setAttribute('r','4');
    g.appendChild(dot);
    // Animation styles
    var st = document.createElementNS('http://www.w3.org/2000/svg','style');
    st.id = 'ep-style';
    st.textContent =
      '@keyframes ep-p1{{0%{{r:5;opacity:.9}}100%{{r:18;opacity:0}}}}' +
      '@keyframes ep-p2{{0%{{r:5;opacity:.6}}100%{{r:12;opacity:0}}}}' +
      '#ep-ring1{{animation:ep-p1 1.8s ease-out infinite}}' +
      '#ep-ring2{{animation:ep-p2 1.8s ease-out .6s infinite}}' +
      '#ep-dot{{filter:drop-shadow(0 0 4px currentColor)}}';
    g.appendChild(st);
    svg.appendChild(g);
  }}

  var ring1 = svg.querySelector('#ep-ring1');
  var ring2 = svg.querySelector('#ep-ring2');
  var edot  = svg.querySelector('#ep-dot');
  [ring1, ring2, edot].forEach(function(el) {{
    if (!el) return;
    el.setAttribute('cx', cx); el.setAttribute('cy', cy);
  }});
  if (ring1) {{ ring1.setAttribute('stroke', ringCol + '0.7)'); }}
  if (ring2) {{ ring2.setAttribute('stroke', ringCol + '0.5)'); }}
  if (edot)  {{ edot.setAttribute('fill', dotCol); edot.style.color = dotCol; }}
}}

function applyPortfolioGlow() {{
  // Portfolio is now trace index 4 (ghost at 3, portfolio at 4)
  var scatters = gd.querySelectorAll('.scatter');
  if (scatters[4]) {{
    var lp = scatters[4].querySelector('path.js-line');
    if (lp) lp.classList.add('portfolio-glow');
  }}
  // Gridline shimmer
  var svg = gd.querySelector('svg.main-svg');
  if (svg && !svg.querySelector('#gl-anim')) {{
    var st = document.createElementNS('http://www.w3.org/2000/svg','style');
    st.id = 'gl-anim';
    st.textContent = '@keyframes gl-sw{{0%,100%{{stroke:rgba(42,0,61,.5)}}50%{{stroke:rgba(190,160,230,.38)}}}}' +
      '.gridlayer .crisp line{{animation:gl-sw 14s ease-in-out infinite}}';
    svg.prepend(st);
  }}
  var lines = gd.querySelectorAll('.gridlayer .crisp line');
  lines.forEach(function(l, i) {{ l.style.animationDelay = -(i * 1.1) % 14 + 's'; }});
  // Update endpoint dot position after replot
  if (window._lastKnownNav && window._lastKnownTs) {{
    _updateEndpointDot(window._lastKnownNav, window._lastKnownTs);
  }}
}}

// Start everything once Plotly has rendered
Plotly.newPlot(gd, traces, layout, config).then(function() {{
  buildTargets();
  applyPortfolioGlow();
  if (rafId) cancelAnimationFrame(rafId);
  drawPulse();
  // Seed endpoint dot — extend portfolio line to "now" so orb lands in intraday window
  if (portDates.length && portValues.length) {{
    var initNav = portValues[portValues.length - 1];
    var nowIso  = new Date().toISOString();
    // Extend the portfolio line (ghost trace 3, main trace 4) to current time
    var extDates  = portDates.concat([nowIso]);
    var extValues = portValues.concat([initNav]);
    Plotly.restyle(gd, {{ x: [extDates, extDates], y: [extValues, extValues] }}, [3, 4]);
    window._lastKnownNav = initNav;
    window._lastKnownTs  = nowIso;
    setTimeout(function() {{ _updateEndpointDot(initNav, nowIso); }}, 200);
    setTimeout(function() {{ _updateAthShape(initNav, nowIso); }}, 250);
  }}
  // Crosshair on load: show → zoom in after crosshair fades
  setTimeout(showCrosshair, 1500);
  // Mark initial layout complete so the pan tracker ignores programmatic events
  setTimeout(function() {{ _initLayoutDone = true; }}, 500);
  // Force intraday zoom — dynamic Y scales to whatever moved in the last 20 min
  setTimeout(function() {{
    _programmaticRelayout = true;
    var _xs = _intradayStart(), _xe = _intradayEnd();
    var _yr = yRange(_xs, new Date().toISOString());
    var _layout = {{ 'xaxis.range': [_xs, _xe] }};
    if (_yr[0] !== null) {{ _layout['yaxis.range'] = _yr; _layout['yaxis.autorange'] = false; }}
    Plotly.relayout(gd, _layout).then(function() {{ _programmaticRelayout = false; }});
  }}, 600);
}});

gd.on('plotly_afterplot', function() {{ buildTargets(); applyPortfolioGlow(); }});

// ── Portfolio canvas chart — sole chart surface, no Plotly ──────────────────
// Robinhood-style: dark bg, glowing trail line, gradient fill, Y labels,
// X time labels, current-value callout, trade markers. Star canvas sits below.
(function() {{
  var _nc = document.getElementById('nav-canvas');
  if (!_nc) return;
  var _dpr = window.devicePixelRatio || 1;

  // Margins — computed dynamically each draw to avoid overlays
  var _ML = 64, _MR = 20, _MT = 28, _MB = 32;

  function _resize() {{
    // offsetWidth/Height are always layout-correct; getBoundingClientRect can
    // return 0 when #chart is display:none and the parent hasn't reflowed yet.
    var cw = _nc.offsetWidth  || (window.innerWidth  - 60)  || 800;
    var ch = _nc.offsetHeight || (window.innerHeight - 140) || 500;
    var pw = Math.round(cw * _dpr), ph = Math.round(ch * _dpr);
    if (_nc.width !== pw || _nc.height !== ph) {{
      _nc.width = pw; _nc.height = ph;
      var ctx = _nc.getContext('2d');
      ctx.setTransform(_dpr, 0, 0, _dpr, 0, 0);
    }}
  }}
  // Delay first resize until layout has settled
  setTimeout(_resize, 100);
  window.addEventListener('resize', _resize);

  // Scroll wheel zooms time window with smooth easing
  window._navWindowMs       = 4 * 3600 * 1000;  // current (lerped)
  window._navTargetWindowMs = 4 * 3600 * 1000;  // target (set by wheel)
  var _WIN_MIN = 5  * 60 * 1000;         //  5 minutes
  var _WIN_MAX = 365 * 86400 * 1000;     //  1 year (full lifetime)
  (function() {{
    var ma = document.getElementById('main-area');
    if (!ma) return;
    ma.addEventListener('wheel', function(e) {{
      e.preventDefault(); e.stopPropagation();
      // Faster zoom: 1.6× per tick in either direction
      var factor = e.deltaY > 0 ? 1.6 : 0.625;
      window._navTargetWindowMs = Math.max(_WIN_MIN,
        Math.min(_WIN_MAX, window._navTargetWindowMs * factor));
    }}, {{ passive: false }});
  }})();

  window._navPush = function(v, isoTs) {{
    // kept for API compatibility — data now comes from _navDbPts
  }};

  window._drawNavCanvas = function() {{
    try {{
    _resize();
    var ctx = _nc.getContext('2d');
    var W = _nc.width / _dpr, H = _nc.height / _dpr;
    ctx.clearRect(0, 0, W, H);

    _ML = 8; _MR = 8; _MT = 28; _MB = 48;

    var liveNav = parseFloat(window._lastKnownNav);
    if (!liveNav || isNaN(liveNav)) {{ window._navOrbFracX=0.5; window._navOrbFracY=0.5; return; }}

    // ── Build point list ───────────────────────────────────────────────────
    var now_ms = Date.now();
    var pts = window._navDbPts || [];
    var allPts = [];
    for (var i = 0; i < pts.length; i++) {{
      var ms = new Date(pts[i].t).getTime();
      if (!isNaN(ms)) allPts.push({{ ms: ms, v: parseFloat(pts[i].v) }});
    }}
    allPts.sort(function(a,b){{return a.ms-b.ms;}});

    // ── Smooth zoom: lerp current window toward target each frame ─────────────
    var _tgt = window._navTargetWindowMs || window._navWindowMs || 4*3600*1000;
    window._navWindowMs += (_tgt - window._navWindowMs) * 0.10;

    // ── Time window — last DB point is pinned to the horizontal center ────────
    var winMs     = window._navWindowMs || 4 * 3600 * 1000;
    var lastPtMs  = allPts.length ? allPts[allPts.length-1].ms : now_ms;
    var dataStart = allPts.length ? allPts[0].ms : now_ms - 30*60000;
    // Half-span = how far back we show; minimum 30 min so line has real width
    var halfSpan  = Math.max(lastPtMs - Math.max(dataStart, lastPtMs - winMs), 30*60000);
    var t0 = lastPtMs - halfSpan;   // left edge = past
    var t1 = lastPtMs + halfSpan;   // right edge = future buffer (last point at center)

    // Filter to window (no synthetic live point — 100% DB-sourced)
    allPts = allPts.filter(function(p) {{ return p.ms >= t0 && p.ms <= t1; }});
    allPts.sort(function(a,b){{return a.ms-b.ms;}});

    // ── Chart area ─────────────────────────────────────────────────────────
    var cx0 = _ML, cx1 = W - _MR, cy0 = _MT, cy1 = H - _MB;
    var cW = cx1 - cx0, cH = cy1 - cy0;

    // ── Y range — tight fit so small moves are visible ─────────────────────
    var lo = liveNav, hi = liveNav;
    for (var vi = 0; vi < allPts.length; vi++) {{
      if (allPts[vi].v < lo) lo = allPts[vi].v;
      if (allPts[vi].v > hi) hi = allPts[vi].v;
    }}
    var spread = hi - lo;
    // Minimum spread: $20 so a flat line sits in a visible band
    if (spread < 20) {{ lo -= (20 - spread) / 2; hi += (20 - spread) / 2; spread = 20; }}
    // 15% padding each side so line doesn't touch edges
    lo -= spread * 0.15; hi += spread * 0.15;

    function tx(ms) {{ return cx0 + (ms - t0) / (t1 - t0) * cW; }}
    function ty(v)  {{ return cy1 - (v - lo) / (hi - lo) * cH; }}

    // ── Grid lines + Y-axis labels (right-anchored, inside chart) ──────────
    var nTicks = 5;
    ctx.font = '10px Consolas,monospace';
    for (var ti = 0; ti <= nTicks; ti++) {{
      var yv = lo + (hi - lo) * ti / nTicks;
      var yy = ty(yv);
      ctx.strokeStyle = 'rgba(140,60,200,0.2)';
      ctx.lineWidth = 1; ctx.setLineDash([3, 6]);
      ctx.beginPath(); ctx.moveTo(cx0, yy); ctx.lineTo(cx1, yy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(190,140,255,0.55)';
      ctx.textAlign = 'left';
      ctx.fillText('$' + Math.round(yv).toLocaleString('en-US'), cx0 + 6, yy - 3);
    }}

    // ── X-axis labels ──────────────────────────────────────────────────────
    var xTickCount = Math.min(8, Math.max(3, Math.floor(cW / 120)));
    ctx.textAlign = 'center';
    for (var xi = 0; xi <= xTickCount; xi++) {{
      var xms = t0 + (t1 - t0) * xi / xTickCount;
      if (xms > now_ms + 60000) continue;  // don't label the future buffer
      var xx  = tx(xms);
      var xd  = new Date(xms);
      var hh  = xd.getHours() % 12 || 12;
      var mm  = ('0' + xd.getMinutes()).slice(-2);
      var ap  = xd.getHours() < 12 ? 'a' : 'p';
      ctx.fillStyle = 'rgba(170,120,255,0.55)';
      ctx.fillText(hh + ':' + mm + ap, xx, cy1 + 18);
    }}

    // ── Map points ─────────────────────────────────────────────────────────
    var m = allPts.map(function(p) {{ return {{ x: tx(p.ms), y: ty(p.v) }}; }});
    var n = m.length;

    // Always draw a line — use flat placeholder if < 2 real points
    if (n < 2) {{
      var midY = ty(liveNav);
      m = [{{ x: cx0, y: midY }}, {{ x: tx(lastPtMs), y: midY }}];
      n = 2;
    }}

    // ── Catmull-Rom path builder with clamped control points (no overshooting) ─
    function _crPath(pts2) {{
      ctx.beginPath();
      ctx.moveTo(pts2[0].x, pts2[0].y);
      for (var ci = 0; ci < pts2.length - 1; ci++) {{
        var p0 = pts2[Math.max(ci-1,0)];
        var p1 = pts2[ci];
        var p2 = pts2[ci+1];
        var p3 = pts2[Math.min(ci+2, pts2.length-1)];
        var cp1x = p1.x + (p2.x - p0.x) / 6;
        var cp1y = p1.y + (p2.y - p0.y) / 6;
        var cp2x = p2.x - (p3.x - p1.x) / 6;
        var cp2y = p2.y - (p3.y - p1.y) / 6;
        // Clamp Y control points so curve can't overshoot segment bounds
        var yLo = Math.min(p1.y, p2.y), yHi = Math.max(p1.y, p2.y);
        cp1y = Math.max(yLo, Math.min(yHi, cp1y));
        cp2y = Math.max(yLo, Math.min(yHi, cp2y));
        ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, p2.x, p2.y);
      }}
    }}

    // ── Pulsing under-fill ────────────────────────────────────────────────────
    var breathe = 0.5 + 0.5 * Math.sin(Date.now() / 1800);
    var fillGrad = ctx.createLinearGradient(0, cy0, 0, cy1);
    fillGrad.addColorStop(0,   'rgba(148,0,255,' + (0.14 + breathe * 0.10) + ')');
    fillGrad.addColorStop(0.5, 'rgba(100,0,200,' + (0.04 + breathe * 0.04) + ')');
    fillGrad.addColorStop(1,   'rgba(148,0,255,0)');
    _crPath(m);
    ctx.lineTo(m[n-1].x, cy1); ctx.lineTo(m[0].x, cy1); ctx.closePath();
    ctx.fillStyle = fillGrad; ctx.fill();

    // ── Glow passes (Catmull-Rom) ─────────────────────────────────────────────
    var passes = [
      {{ w:14, a:0.09, rgb:'120,0,255' }},
      {{ w:5,  a:0.40, rgb:'180,40,255' }},
      {{ w:2,  a:0.80, rgb:'210,80,255' }},
      {{ w:1.5,a:1.00, rgb:'245,190,255' }},
    ];
    passes.forEach(function(pass) {{
      _crPath(m);
      ctx.strokeStyle = 'rgba(' + pass.rgb + ',' + pass.a + ')';
      ctx.lineWidth = pass.w; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
      ctx.stroke();
    }});

    // ── Animated data-packet bead traveling the line ──────────────────────────
    var _packetT = (Date.now() % 4000) / 4000;  // 0→1 every 4 seconds
    var _pidx    = Math.floor(_packetT * (n - 1));
    var _pfrac   = (_packetT * (n - 1)) - _pidx;
    var _pa      = m[Math.min(_pidx,     n-1)];
    var _pb      = m[Math.min(_pidx + 1, n-1)];
    var _px      = _pa.x + (_pb.x - _pa.x) * _pfrac;
    var _py      = _pa.y + (_pb.y - _pa.y) * _pfrac;
    var _pglow   = 0.5 + 0.5 * Math.sin(Date.now() / 120);
    ctx.beginPath(); ctx.arc(_px, _py, 7 + _pglow * 4, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(200,100,255,' + (0.08 + _pglow * 0.10) + ')'; ctx.fill();
    ctx.beginPath(); ctx.arc(_px, _py, 3 + _pglow, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(230,160,255,' + (0.55 + _pglow * 0.30) + ')'; ctx.fill();
    ctx.beginPath(); ctx.arc(_px, _py, 1.5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,0.9)'; ctx.fill();

    // ── Orb tip: last real data point (tx(now_ms) is 90% width due to t1 pad) ──
    var tipX = m[n-1].x;
    var tipY = m[n-1].y;
    var ncRect = _nc.getBoundingClientRect();
    var scrX = ncRect.left + tipX * (ncRect.width  / W);
    var scrY = ncRect.top  + tipY * (ncRect.height / H);
    window._navOrbFracX = Math.max(0.05, Math.min(0.95, scrX / (window.innerWidth  || 1)));
    window._navOrbFracY = Math.max(0.05, Math.min(0.95, scrY / (window.innerHeight || 1)));

    // ── Breathing dot at trail tip ──────────────────────────────────────────
    var pulse = 0.5 + 0.5 * Math.sin(Date.now() / 400);
    // Outer glow
    ctx.beginPath(); ctx.arc(tipX, tipY, 10 + pulse * 8, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(180,0,255,' + (0.12 + pulse * 0.18) + ')'; ctx.fill();
    // Mid ring
    ctx.beginPath(); ctx.arc(tipX, tipY, 5 + pulse * 3, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(220,100,255,' + (0.5 + pulse * 0.3) + ')'; ctx.fill();
    // Core white dot
    ctx.beginPath(); ctx.arc(tipX, tipY, 3, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,0.95)'; ctx.fill();

    // ── Current value callout ───────────────────────────────────────────────
    var valStr = '$' + liveNav.toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}});
    ctx.font = 'bold 13px Consolas,monospace';
    var tw = ctx.measureText(valStr).width;
    // Keep callout inside chart area: prefer right of dot, fall back left
    var lx = tipX + 14;
    if (lx + tw + 4 > cx1) lx = tipX - tw - 18;
    lx = Math.max(cx0 + 2, lx);
    var ly = Math.max(cy0 + 16, Math.min(tipY + 4, cy1 - 6));
    // Pill background (manual rounded rect — roundRect not in all Chrome versions)
    ctx.fillStyle = 'rgba(8,0,18,0.85)';
    ctx.fillRect(lx - 4, ly - 13, tw + 8, 17);
    // Text
    ctx.fillStyle = '#e0c8ff';
    ctx.textAlign = 'left';
    ctx.fillText(valStr, lx, ly);

    // ── ENTER / EXIT trade markers ──────────────────────────────────────────
    var _tradeMarkers = window._navTradeMarkers || [];
    for (var tmi = 0; tmi < _tradeMarkers.length; tmi++) {{
      var tm = _tradeMarkers[tmi];
      var tmMs = new Date(tm.ts).getTime();
      if (tmMs < t0 || tmMs > t1) continue;
      var tmx = tx(tmMs);
      var tmy = tm.nav ? ty(tm.nav) : (tm.side === 'ENTER' ? cy0 + 20 : cy1 - 20);
      var isEnter = tm.side === 'ENTER';
      var tmCol = isEnter ? '#00ff9d' : '#ff3366';
      // Vertical drop line
      ctx.strokeStyle = isEnter ? 'rgba(0,255,157,0.2)' : 'rgba(255,51,102,0.2)';
      ctx.lineWidth = 1; ctx.setLineDash([2,4]);
      ctx.beginPath(); ctx.moveTo(tmx, cy0); ctx.lineTo(tmx, cy1); ctx.stroke();
      ctx.setLineDash([]);
      // Triangle marker
      ctx.fillStyle = tmCol;
      ctx.beginPath();
      if (isEnter) {{
        ctx.moveTo(tmx, tmy - 12); ctx.lineTo(tmx - 6, tmy - 2); ctx.lineTo(tmx + 6, tmy - 2);
      }} else {{
        ctx.moveTo(tmx, tmy + 12); ctx.lineTo(tmx - 6, tmy + 2); ctx.lineTo(tmx + 6, tmy + 2);
      }}
      ctx.closePath(); ctx.fill();
      // Symbol label
      ctx.font = '9px Consolas,monospace';
      ctx.fillStyle = tmCol;
      ctx.textAlign = 'center';
      ctx.fillText(tm.sym || '', tmx, isEnter ? tmy - 15 : tmy + 23);
    }}

    }} catch(e) {{
      console.error('[navChart]', e);
      var _ectx = _nc.getContext('2d');
      _ectx.font = 'bold 11px Consolas'; _ectx.fillStyle = '#ff4400'; _ectx.textAlign = 'center';
      _ectx.fillText('ERR: ' + (e.message || String(e)), (_nc.width/_dpr)/2, (_nc.height/_dpr)/2 + 28);
    }}
  }};

  // ~30fps — enough for a smooth breathing dot without burning GPU
  var _navLastDraw = 0;
  (function _raf(ts) {{
    if (ts - _navLastDraw >= 33) {{ _navLastDraw = ts; window._drawNavCanvas(); }}
    requestAnimationFrame(_raf);
  }})(0);
}})();

// ── Real-time x-axis advance — DISABLED: _recenterOnLatest() handles centering ──
var _userPanned = false;
var _initLayoutDone = false;
var _rtAdvancing = false;
gd.on('plotly_relayout', function(u) {{
  if (!_initLayoutDone || _rtAdvancing) return;
  if (u['xaxis.range[0]'] !== undefined) _userPanned = true;
}});

// ── Trade event markers ───────────────────────────────────────────────────────
var _tradeEventIds = new Set(); // track seen event IDs to avoid re-adding
var _tradeDropLines = []; // shapes for vertical drop lines

function _navAtTime(isoTs) {{
  var tsMs = new Date(isoTs).getTime();
  // Check live intraday pts first (most precise — within seconds)
  if (_intradayPts.length) {{
    var closest = null, closestDiff = Infinity;
    for (var j=0; j<_intradayPts.length; j++) {{
      var diff = Math.abs(new Date(_intradayPts[j].t).getTime() - tsMs);
      if (diff < closestDiff) {{ closestDiff = diff; closest = _intradayPts[j].v; }}
    }}
    if (closest !== null) return closest;
  }}
  // Fall back to daily portfolio snapshots
  if (!portDates.length) return window._lastKnownNav || null;
  var best = null, bestDiff = Infinity;
  for (var i=0; i<portDates.length; i++) {{
    var d = Math.abs(new Date(portDates[i]).getTime() - tsMs);
    if (d < bestDiff) {{ bestDiff = d; best = portValues[i]; }}
  }}
  if (window._lastKnownNav) best = window._lastKnownNav;
  return best;
}}

function _spawnTradeChip(isoTs, sym, isEntry, price) {{
  var fl = gd._fullLayout;
  var gRect = gd.getBoundingClientRect();
  if (!fl || !fl.xaxis || !fl.yaxis) return;

  var navY = _navAtTime(isoTs) || window._lastKnownNav || 100000;
  var col  = isEntry ? [0,255,157] : [255,51,102];
  var rgb  = 'rgb(' + col.join(',') + ')';
  var rgba = function(a) {{ return 'rgba(' + col.join(',') + ',' + a + ')'; }};

  // Pixel position on screen (chart-relative + viewport offset)
  var px = gRect.left, py = gRect.top + gRect.height * 0.5;
  try {{
    px = fl.xaxis.l2p(fl.xaxis.d2l(isoTs)) + fl.margin.l + gRect.left;
    py = fl.yaxis.l2p(fl.yaxis.d2l(navY))  + fl.margin.t + gRect.top;
  }} catch(e) {{}}

  // 1. Expanding ring pulses — 3 rings staggered 160ms apart
  for (var ri = 0; ri < 3; ri++) {{
    (function(delay) {{
      setTimeout(function() {{
        var ring = document.createElement('div');
        ring.style.cssText =
          'position:fixed;pointer-events:none;z-index:283;border-radius:50%;' +
          'border:2px solid ' + rgb + ';' +
          'width:12px;height:12px;' +
          'left:' + (px-6) + 'px;top:' + (py-6) + 'px;' +
          'opacity:.85;transition:transform .75s cubic-bezier(.16,1,.3,1), opacity .75s ease';
        document.body.appendChild(ring);
        requestAnimationFrame(function() {{ requestAnimationFrame(function() {{
          ring.style.transform = 'scale(' + (6 + ri*2) + ')';
          ring.style.opacity = '0';
        }}); }});
        setTimeout(function() {{ ring.remove(); }}, 850);
      }}, delay);
    }})(ri * 160);
  }}

  // 2. Flash dot at marker
  var dot = document.createElement('div');
  dot.style.cssText =
    'position:fixed;pointer-events:none;z-index:290;border-radius:50%;' +
    'width:8px;height:8px;left:' + (px-4) + 'px;top:' + (py-4) + 'px;' +
    'background:' + rgb + ';box-shadow:0 0 24px 8px ' + rgba(.65) + ';' +
    'opacity:1;transition:transform .55s ease, opacity .55s ease';
  document.body.appendChild(dot);
  requestAnimationFrame(function() {{ requestAnimationFrame(function() {{
    dot.style.transform = 'scale(3)';
    dot.style.opacity = '0';
  }}); }});
  setTimeout(function() {{ dot.remove(); }}, 650);

  // 3. Floating label chip — zooms in then drifts and fades
  var label = (isEntry ? '▲ ENTER ' : '&#9660; EXIT ') + sym.replace('/USD','') +
              (price ? '  $' + parseFloat(price||0).toFixed(sym.indexOf('USD')!==-1?4:2) : '');
  var chip = document.createElement('div');
  chip.innerHTML = label;
  chip.style.cssText =
    'position:fixed;pointer-events:none;z-index:296;' +
    'font-family:Consolas,monospace;font-size:9.5px;font-weight:800;letter-spacing:.09em;' +
    'padding:4px 10px 4px 7px;border-radius:2px;white-space:nowrap;' +
    'color:' + rgb + ';background:' + rgba(.07) + ';' +
    'border:1px solid ' + rgba(.45) + ';' +
    'box-shadow:0 0 20px ' + rgba(.35) + ',0 0 50px ' + rgba(.1) + ';' +
    'left:' + (px + 14) + 'px;top:' + (py - 12) + 'px;' +
    'opacity:0;transform:scale(.5) translateY(' + (isEntry ? 10 : -10) + 'px);' +
    'transition:opacity .18s ease, transform .42s cubic-bezier(.22,1,.36,1)';
  document.body.appendChild(chip);
  requestAnimationFrame(function() {{ requestAnimationFrame(function() {{
    chip.style.opacity = '1';
    chip.style.transform = 'scale(1) translateY(0)';
  }}); }});
  setTimeout(function() {{
    chip.style.transition = 'opacity 1.1s ease, transform 3.5s ease';
    chip.style.opacity = '0';
    chip.style.transform = 'scale(.95) translateY(' + (isEntry ? -52 : 52) + 'px)';
    setTimeout(function() {{ chip.remove(); }}, 1200);
  }}, 2600);

  // 4. Spark burst — 8-12 particles radiate outward
  var sparkCount = 8 + Math.floor(Math.random()*5);
  for (var si = 0; si < sparkCount; si++) {{
    (function() {{
      var angle = Math.random() * Math.PI * 2;
      var dist  = 18 + Math.random() * 38;
      var spark = document.createElement('div');
      spark.style.cssText =
        'position:fixed;pointer-events:none;z-index:287;border-radius:50%;' +
        'width:3px;height:3px;' +
        'left:' + (px-1.5) + 'px;top:' + (py-1.5) + 'px;' +
        'background:' + rgb + ';box-shadow:0 0 5px ' + rgb + ';' +
        'opacity:.95;transition:transform .65s cubic-bezier(.22,1,.36,1), opacity .65s ease';
      document.body.appendChild(spark);
      requestAnimationFrame(function() {{ requestAnimationFrame(function() {{
        spark.style.transform =
          'translate(' + (Math.cos(angle)*dist) + 'px,' + (Math.sin(angle)*dist) + 'px) scale(.25)';
        spark.style.opacity = '0';
      }}); }});
      setTimeout(function() {{ spark.remove(); }}, 750);
    }})();
  }}
}}

function _fetchTradeEvents() {{
  var url = SUPA_URL + '/rest/v1/pipeline_events'
    + '?event_type=eq.TRADE'
    + '&order=recorded_at.asc'
    + '&limit=200';
  fetch(url, {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
  .then(function(r) {{ return r.json(); }})
  .then(function(rows) {{
    if (!Array.isArray(rows) || !rows.data) {{
      // rows is the array directly from PostgREST
      if (!Array.isArray(rows)) return;
    }}
    var enterXs=[], enterYs=[], enterTexts=[];
    var exitXs=[],  exitYs=[],  exitTexts=[];
    var newShapes = []; // vertical drop lines

    rows.forEach(function(row) {{
      var id = row.id;
      var msg = row.message || '';
      var ts  = row.recorded_at;
      if (!ts) return;

      var isEntry = msg.indexOf('ENTER') !== -1 || msg.indexOf('enter') !== -1;
      var isExit  = msg.indexOf('EXIT')  !== -1 || msg.indexOf('exit')  !== -1;
      if (!isEntry && !isExit) return;

      // Parse symbol
      var symM = msg.match(/(?:ENTER|EXIT|enter|exit)\s+([A-Z\/]+)/);
      var sym  = symM ? symM[1] : '';
      // Parse price
      var priceM = msg.match(/@\s*\$([\d,.]+)/);
      var price  = priceM ? priceM[1] : '';

      var navY = _navAtTime(ts);
      if (!navY) return;

      var isoTs = new Date(ts).toISOString();

      if (isEntry) {{
        enterXs.push(isoTs); enterYs.push(navY);
        enterTexts.push(sym.replace('/USD',''));
      }} else {{
        exitXs.push(isoTs);  exitYs.push(navY);
        exitTexts.push(sym.replace('/USD',''));
      }}

      // Vertical drop line
      newShapes.push({{
        type:'line', xref:'x', yref:'paper',
        x0:isoTs, x1:isoTs, y0:0, y1:1,
        line:{{ color: isEntry ? 'rgba(0,255,157,.38)' : 'rgba(255,51,102,.38)', width:1.5, dash:'dot' }},
        layer:'below',
      }});

      // Spawn animated chip for NEW events only
      if (id && !_tradeEventIds.has(id)) {{
        _tradeEventIds.add(id);
        // Only animate events from the last 5 minutes (live)
        if (Date.now() - new Date(ts).getTime() < 300000) {{
          _spawnTradeChip(isoTs, sym, isEntry, price);
        }}
      }}
    }});

    // Feed trade markers to canvas chart
    var canvasMarkers = [];
    enterXs.forEach(function(ts, i) {{ canvasMarkers.push({{ ts:ts, nav:enterYs[i], sym:enterTexts[i], side:'ENTER' }}); }});
    exitXs.forEach(function(ts, i)  {{ canvasMarkers.push({{ ts:ts, nav:exitYs[i],  sym:exitTexts[i],  side:'EXIT'  }}); }});
    window._navTradeMarkers = canvasMarkers;
  }})
  .catch(function() {{}});
}}

// Fetch on load + every 10s
setTimeout(_fetchTradeEvents, 2000);
setInterval(_fetchTradeEvents, 10000);

// Also trigger on live TRADE events from feed poller
window._onLiveTrade = function() {{ setTimeout(_fetchTradeEvents, 1500); }};

// ── Intraday "marked the book" trace — live portfolio value within today ──────
function _fetchIntradayMarks() {{
  var today = new Date().toISOString().slice(0,10);
  // Only fetch "marked the book" rows for the chart — filter by message to keep row count small
  var url = SUPA_URL + '/rest/v1/pipeline_events'
    + '?select=message,recorded_at&recorded_at=gte.' + today + 'T00:00:00Z'
    + '&message=ilike.*marked%20the%20book*&order=recorded_at.asc&limit=500';
  fetch(url, {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
  .then(function(r) {{ return r.json(); }})
  .then(function(rows) {{
    if (!Array.isArray(rows)) return;
    var xs = [], ys = [];
    rows.forEach(function(row) {{
      var msg = row.message || '';
      var m = msg.match(/marked the book at \$?([\d,]+)/);
      if (m) {{
        var v = parseFloat(m[1].replace(/,/g,''));
        if (!isNaN(v) && v > 50000 && v < 200000) {{
          xs.push(new Date(row.recorded_at).toISOString());
          ys.push(v);
        }}
      }}
    }});
    // Update intraday trace
    if (xs.length && gd && gd.data && gd.data.length >= 7) {{
      Plotly.restyle(gd, {{ x:[xs], y:[ys] }}, [6]).then(function() {{
        var lastV = ys[ys.length-1], lastT = xs[xs.length-1];
        // Only use pipeline stamp as NAV if no live price has arrived in the last 10s.
        // Prevents the frozen "marked the book" value from oscillating with the live feed.
        if (!window._lastLivePriceMs || (Date.now() - window._lastLivePriceMs) > 10000) {{
          window._lastKnownNav = lastV; window._lastKnownTs = lastT;
        }}
        // Always ingest marks into nav history regardless of which source wins display
        for (var _i=0; _i<xs.length; _i++) {{ if (window._navPush) window._navPush(ys[_i], xs[_i]); }}
        _updateEndpointDot(lastV, lastT);
        buildTargets();
      }});
    }}
    _recenterOnLatest(xs.length > 0 ? xs[xs.length - 1] : null);
  }}).catch(function() {{}});

  // Separate HEAD request for accurate TRADE count (bypasses row limit)
  var urlCount = SUPA_URL + '/rest/v1/pipeline_events'
    + '?select=id&event_type=eq.TRADE&recorded_at=gte.' + today + 'T00:00:00Z&limit=1';
  fetch(urlCount, {{ method:'HEAD', headers: {{
    'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY, 'Prefer': 'count=exact'
  }} }})
  .then(function(r) {{
    var ct = r.headers.get('content-range');
    if (!ct) return;
    var total = parseInt(ct.split('/')[1], 10);
    if (!isNaN(total)) _updateOrbMetrics(total, 0, 0);
  }}).catch(function() {{}});
}}
setTimeout(_fetchIntradayMarks, 3000);
setInterval(_fetchIntradayMarks, 15000);

// ── Live equity tile price updater ────────────────────────────────────────────
(function() {{
  var _eqPrev = {{}};  // sym -> last displayed value

  function _flashVal(el, up) {{
    el.classList.remove('pc-tick-up','pc-tick-down');
    void el.offsetWidth; // reflow
    el.classList.add(up ? 'pc-tick-up' : 'pc-tick-down');
  }}

  function _pollEqPrices() {{
    var liveTiles = (window._ET||[]).filter(function(t) {{
      return !t.isCrypto && (t.phase === 'live' || t.phase === 'entering');
    }});
    if (!liveTiles.length) return;
    var syms = liveTiles.map(function(t) {{ return t.sym; }});

    // Fetch live quotes from Yahoo Finance (same source as yfinance, no auth needed).
    // crumb/cookie not required for the simple quote endpoint.
    var yfUrl = 'https://query1.finance.yahoo.com/v7/finance/quote?symbols='
      + syms.join(',') + '&fields=regularMarketPrice,symbol';
    fetch(yfUrl, {{ headers: {{ 'Accept': 'application/json' }} }})
    .then(function(r) {{ return r.ok ? r.json() : null; }})
    .then(function(data) {{
      var latest = {{}};
      if (data && data.quoteResponse && Array.isArray(data.quoteResponse.result)) {{
        data.quoteResponse.result.forEach(function(q) {{
          if (q.symbol && q.regularMarketPrice) latest[q.symbol] = q.regularMarketPrice;
        }});
      }}
      // Fallback: if Yahoo blocked (CORS on cloud), pull yesterday's close from Supabase
      var missing = syms.filter(function(s) {{ return !latest[s]; }});
      function _applyPrices() {{
        liveTiles.forEach(function(t) {{
          var price = latest[t.sym];
          if (!price) return;
          var val = t.qty * price;
          var pnl = t.entry > 0 ? (price - t.entry) * t.qty : 0;
          var pct = t.entry > 0 ? (price - t.entry) / t.entry * 100 : 0;
          var prev = _eqPrev[t.sym];
          if (prev !== undefined && Math.abs(val - prev) > 0.50) {{
            t._valFlash = val > prev ? 1 : -1;
          }}
          _eqPrev[t.sym] = val;
          t.curPrice = price;
          t.val = val;
          t.pnl = pnl;
          t.pnlPct = pct;
        }});

        // Equity NAV slice
        var _eqLivePnl = 0, _eqCount = 0;
        liveTiles.forEach(function(t) {{
          if (t.qty > 0 && t.entry > 0 && t.curPrice > 0) {{
            _eqLivePnl += t.qty * (t.curPrice - t.entry);
            _eqCount++;
          }}
        }});
        window._livePnlBySource.equity = _eqCount > 0 ? _eqLivePnl : 0;
        if (_eqCount > 0) {{
          var mood = _eqLivePnl > 0 ? 'bs-happy' : _eqLivePnl < 0 ? 'bs-sad' : '';
          var g = document.getElementById('bs-g'), hl = document.getElementById('bs-hl');
          if (g) {{ g.classList.remove('bs-happy','bs-sad'); if (mood) g.classList.add(mood); }}
          if (hl) {{ hl.classList.remove('bs-hl-happy','bs-hl-sad');
            if (mood === 'bs-happy') hl.classList.add('bs-hl-happy');
            else if (mood === 'bs-sad') hl.classList.add('bs-hl-sad'); }}
        }}
      }}

      if (missing.length) {{
        // Yahoo blocked — fallback to Supabase price_bars (yesterday's close)
        var fbUrl = SUPA_URL + '/rest/v1/price_bars'
          + '?select=symbol,close&symbol=in.(' + missing.join(',') + ')'
          + '&order=date.desc&limit=' + (missing.length * 2);
        fetch(fbUrl, {{headers:{{'apikey':SUPA_KEY,'Authorization':'Bearer '+SUPA_KEY}}}})
        .then(function(r) {{ return r.json(); }})
        .then(function(rows) {{
          if (!Array.isArray(rows)) return;
          rows.forEach(function(row) {{ if (!latest[row.symbol]) latest[row.symbol] = row.close; }});
          _applyPrices();
        }}).catch(function() {{}});
      }} else {{
        _applyPrices();
      }}
    }}).catch(function() {{
      // Yahoo fetch failed entirely — fall back to Supabase
      var fbUrl = SUPA_URL + '/rest/v1/price_bars'
        + '?select=symbol,close&symbol=in.(' + syms.join(',') + ')'
        + '&order=date.desc&limit=' + (syms.length * 2);
      fetch(fbUrl, {{headers:{{'apikey':SUPA_KEY,'Authorization':'Bearer '+SUPA_KEY}}}})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        if (!Array.isArray(rows)) return;
        var latest2 = {{}};
        rows.forEach(function(row) {{ if (!latest2[row.symbol]) latest2[row.symbol] = row.close; }});
        liveTiles.forEach(function(t) {{
          var price = latest2[t.sym]; if (!price) return;
          t.curPrice = price;
          t.val = t.qty * price;
          t.pnl = t.entry > 0 ? (price - t.entry) * t.qty : 0;
          t.pnlPct = t.entry > 0 ? (price - t.entry) / t.entry * 100 : 0;
        }});
      }}).catch(function() {{}});
    }});
  }}

  setTimeout(_pollEqPrices, 4000);
  setInterval(_pollEqPrices, 20000);

  // ── Equity tile entry animation (wipe from transparent, bottom→up) ────────────
  (function() {{
    var cards = document.querySelectorAll('.pc-eq');
    cards.forEach(function(el, i) {{
      el.classList.add('pos-card-entering');
      setTimeout(function() {{ el.classList.remove('pos-card-entering'); }}, 600);
    }});
  }})();
}})();

// ── Shared live PnL accumulator — prevents equity+crypto pollers oscillating _lastKnownNav ──
// Each poller writes its slice; both read the combined total so NAV doesn't alternate.
window._livePnlBySource = {{ equity: 0, crypto: 0 }};

// ── Nav chart — 100% DB-sourced, consistent across all machines ──────────────
// _navDbPts seeded from Python at render; refreshed from Supabase every 10s.
// No client-side live point is injected into the draw loop.
// _pushIntradayPoint writes to DB every 10s; the next poll picks it up.

function _fixTs(t) {{
  // Supabase returns naive UTC strings; append Z so JS parses as UTC
  if (t && t[t.length-1] !== 'Z' && t.indexOf('+') === -1) return t + 'Z';
  return t;
}}

function _fetchNavDb() {{
  var since = new Date(Date.now() - 24*3600000).toISOString();
  fetch(SUPA_URL + '/rest/v1/nav_snapshots?select=recorded_at,nav&recorded_at=gte.' + since + '&order=recorded_at.asc&limit=2000',
    {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
  .then(function(r) {{ return r.json(); }})
  .then(function(rows) {{
    if (!Array.isArray(rows)) return;
    window._navDbPts = rows.map(function(r) {{ return {{ t: _fixTs(r.recorded_at), v: r.nav }}; }});
    if (window._redrawNavTraces) window._redrawNavTraces();
  }}).catch(function() {{}});
}}
_fetchNavDb();
setInterval(_fetchNavDb, 10000);  // refresh every 10s

window._forceNavSnapshot = function() {{
  var nav = window._lastKnownNav;
  if (!nav) return;
  var isoTs = new Date().toISOString();
  fetch(SUPA_URL + '/rest/v1/nav_snapshots', {{
    method: 'POST',
    headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
                'Content-Type': 'application/json', 'Prefer': 'return=minimal' }},
    body: JSON.stringify({{ recorded_at: isoTs, nav: nav }})
  }}).catch(function() {{}});
}};

var _lastNavWriteMs = 0;
window._pushIntradayPoint = function(isoTs, val) {{
  var now = Date.now();
  // Always update live nav state for display
  window._lastLivePriceMs = now;
  window._lastKnownNav = val;
  window._lastKnownTs  = isoTs;
  // Write to DB at most every 10s — chart reads from DB, not local array
  if (now - _lastNavWriteMs < 10000) return;
  _lastNavWriteMs = now;
  fetch(SUPA_URL + '/rest/v1/nav_snapshots', {{
    method: 'POST',
    headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
                'Content-Type': 'application/json', 'Prefer': 'return=minimal' }},
    body: JSON.stringify({{ recorded_at: isoTs, nav: val }})
  }}).catch(function(e) {{ console.warn('[nav] snapshot write failed', e); }});
  if (window._navPush) window._navPush(val, isoTs);
  if (gd && gd.data && gd.data.length >= 7) {{
    Plotly.restyle(gd, {{
      x: [_intradayPts.map(function(p) {{ return p.t; }})],
      y: [_intradayPts.map(function(p) {{ return p.v; }})]
    }}, [6]).then(function() {{
      // Move the endpoint dot + orb to the live NAV position
      _updateEndpointDot(val, isoTs);
      buildTargets();
      // Spawn particles if NAV moved
      if (_lastNavForParticles !== null && window._spawnNavParticles) {{
        var _pc = document.getElementById('pulse-canvas');
        var px = (window._navOrbFracX !== undefined ? window._navOrbFracX : 0.5) * (_pc ? _pc.width : 800);
        var py = (window._navOrbFracY !== undefined ? window._navOrbFracY : 0.5) * (_pc ? _pc.height : 500);
        if (true) {{
          try {{
            if (isFinite(px) && isFinite(py)) {{
              window._spawnNavParticles(px, py, val >= _lastNavForParticles);
            }}
          }} catch(e) {{}}
        }}
      }}
      _lastNavForParticles = val;
    }});
  }}
  // Slide the chart window forward with each new point
  _recenterOnLatest(isoTs);
}};

// ── Orb metrics panel updates ─────────────────────────────────────────────────
var _orbTodayTrades = 0, _orbWins = 0, _orbLosses = 0;
function _updateOrbMetrics(todayTrades, wins, losses) {{
  if (todayTrades > 0) _orbTodayTrades = todayTrades;
  if (wins   > 0) _orbWins   = wins;
  if (losses > 0) _orbLosses = losses;
  if (typeof window._updateTradesSlot === 'function') window._updateTradesSlot(_orbTodayTrades);

  // Block 2 exposes these via window.*
  var trTs = window._tradeTs || [];
  var now  = Date.now();
  var cutoff = now - 3600000;
  var tph  = trTs.filter(function(t){{ return t > cutoff; }}).length;
  var el;

  el = document.getElementById('om-tph');
  if (el) el.textContent = tph > 0 ? tph.toFixed(0) : '0';

  el = document.getElementById('om-today');
  if (el) el.textContent = _orbTodayTrades > 0 ? _orbTodayTrades : '0';

  var total = _orbWins + _orbLosses;
  el = document.getElementById('om-winrate');
  if (el) el.textContent = total > 0 ? Math.round(_orbWins/total*100) + '%' : '—';

  el = document.getElementById('om-streak-orb');
  if (el) {{
    var s = window._streak || null;
    if (s && s.count > 0) {{
      var col = s.win ? '#00ff9d' : '#ff3366';
      el.textContent = (s.win ? '+' : '-') + s.count;
      el.style.color = col;
    }} else {{
      el.textContent = '—';
      el.style.color = '';
    }}
  }}

  // Update DAY P&L live from intraday NAV delta
  el = document.getElementById('om-dpnl');
  if (el && window._portfolioBaseline && window._lastKnownNav) {{
    var liveDayPnl = window._lastKnownNav - window._portfolioBaseline;
    el.textContent = (liveDayPnl >= 0 ? '+$' : '-$') + Math.abs(liveDayPnl).toLocaleString('en-US', {{maximumFractionDigits:0}});
    el.style.color = liveDayPnl >= 0 ? '#00ff9d' : '#ff3366';
  }}

  // Update open position count from live card state
  el = document.getElementById('om-openpos');
  if (el) {{
    var cryptoCount = Object.keys(window._cryptoPositionsMap || {{}}).length;
    var equityCount = document.querySelectorAll('#pos-equity-section .pos-card[data-sym]').length;
    el.textContent = (cryptoCount + equityCount) || '0';
  }}
}}
setInterval(function() {{ _updateOrbMetrics(0,0,0); }}, 1000);

var _scrollBusy = false;
var _smoothYMin = null, _smoothYMax = null;

// ── Wallet selector ───────────────────────────────────────────────────────────
var _walletModes = ['PAPER', 'LIVE ●'];
var _walletIdx = 0;
function _cycleWallet() {{
  _walletIdx = (_walletIdx + 1) % _walletModes.length;
  var lbl = document.getElementById('wallet-mode-label');
  var sel = document.getElementById('wallet-selector');
  var ico = document.getElementById('wallet-mode-icon');
  if (!lbl || !sel) return;
  var mode = _walletModes[_walletIdx];
  lbl.textContent = mode;
  if (_walletIdx === 1) {{
    sel.classList.add('live');
    ico.textContent = '◉';
  }} else {{
    sel.classList.remove('live');
    ico.textContent = '◈';
  }}
}}

var _userInteracting = false;
var _programmaticRelayout = false;
gd.on('plotly_relayout', function(ev) {{ buildTargets(); }});

window.addEventListener('resize', function() {{
  resizeCanvas();
  // Re-layout equity columns on viewport resize
  setTimeout(function() {{ if (window._updateOverlayWidth) window._updateOverlayWidth(); }}, 50);
}});
// Initial equity column layout — run after first render
setTimeout(function() {{
  if (typeof _updateOverlayWidth === 'function') _updateOverlayWidth();
}}, 800);
</script>

<!-- Terminal overlay — hidden; kept as DOM container for JS elements -->
<div id="term-overlay">
  <!-- Hidden data sources for JS -->
  <div id="queue-dynamic" style="display:none"></div>
  <div style="display:none">{q_items}</div>
  <!-- HUD overlay (hidden under collapsed parent but DOM-accessible) -->
  <div id="hud-overlay">
    <div id="hud-label">
      <div class="term-dot" style="background:#00e5ff;box-shadow:0 0 8px rgba(0,229,255,.9)"></div>
      <span id="hud-label-text">QUEUED</span>
    </div>
    <div id="hud-items"></div>
  </div>
  <!-- Orphaned wallet elements JS might reference -->
  <div id="wallet-nav" data-val="{last_nav_fmt}" style="display:none">{last_nav_fmt}</div>
  <div id="wallet-pnl" style="display:none">{_pnl_str}</div>
  <div id="wallet-streak" style="display:none"></div>
  <div id="gauge-needle" style="display:none"></div>
  <div id="gauge-arc" style="display:none"></div>
  <div id="gauge-label" style="display:none"></div>
  <div id="wallet-vel-fill" style="display:none"></div>
  <div id="wallet-event-ticker" style="display:none"></div>
  <!-- Feed panel stub (term-body is in overlay above; keep a hidden stub so old JS refs don't break) -->
  <div id="feed-panel" style="display:none"></div>
  <!-- Pos panel stub -->
  <div id="pos-panel" style="display:none"></div>
</div>

<!-- Buy console — inline arcade row -->
<div id="buy-console">
  <span class="bc-lbl">BUY $</span>
  <input id="bc-amt" type="number" placeholder="amt" min="0" step="1" autocomplete="off">
  <span class="bc-lbl">&nbsp;OF&nbsp;</span>
  <input id="bc-sym" type="text" placeholder="ticker" maxlength="12" list="bc-tickers"
         autocomplete="off" spellcheck="false">
  <datalist id="bc-tickers"></datalist>
  <button id="bc-buy" onclick="bcSubmit()">▶ BUY</button>
  <span id="bc-status"></span>
</div>

<script>

  // ── Gauge — avg trades per hour ───────────────────────────────────────────
  var _tradeTs = [];
  window._tradeTs = _tradeTs; // expose to script block 1
  var _GAUGE_MAX = 8;
  var _gaugeRate = 0;

  function _updateGauge(rate) {{
    _gaugeRate = rate;
    var needle = document.getElementById('gauge-needle');
    var label  = document.getElementById('gauge-label');
    if (!needle) return;
    var pct = Math.min(1, rate / _GAUGE_MAX);
    var deg = -90 + pct * 180;
    needle.style.transform = 'rotate(' + deg + 'deg)';
    var col = pct < 0.4 ? '#00ff9d' : pct < 0.75 ? '#ffcc00' : '#ff3366';
    needle.style.stroke = col;
    if (label) {{
      label.style.color = col;
      label.style.textShadow = '0 0 10px ' + col;
      label.innerHTML = rate.toFixed(1) + ' <span style="font-size:7px;opacity:.5">tr/hr</span>';
    }}
  }}

  window._recordTradeForGauge = function() {{
    var now = Date.now();
    _tradeTs.push(now);
    var cutoff = now - 60 * 60 * 1000;
    _tradeTs = _tradeTs.filter(function(t) {{ return t >= cutoff; }});
    _updateGauge(_tradeTs.length);
  }};

  // Decay gauge every 30s when idle
  setInterval(function() {{
    var now = Date.now(), cutoff = now - 60 * 60 * 1000;
    _tradeTs = _tradeTs.filter(function(t) {{ return t >= cutoff; }});
    _updateGauge(_tradeTs.length);
  }}, 30000);

  // ── Streak tracker ────────────────────────────────────────────────────────
  var _streak = {{ count: 0, win: null }};
  window._streak = _streak; // expose to script block 1

  window._recordStreakResult = function(isWin) {{
    if (_streak.win === null || _streak.win === isWin) {{
      _streak.count++; _streak.win = isWin;
    }} else {{
      _streak.count = 1; _streak.win = isWin;
    }}
    var el = document.getElementById('wallet-streak');
    if (el) {{
      var col  = isWin ? '#00ff9d' : '#ff3366';
      var icon = isWin ? '&#9650;' : '&#9660;';
      var n    = _streak.count;
      el.innerHTML = '<span style="color:' + col + ';text-shadow:0 0 8px ' + col + '">' + icon + '&nbsp;' + n + (n === 1 ? ' WIN' : ' STREAK') + '</span>';
    }}
    // Drive combo counter in drawPulse (block 1)
    if (window._orbComboResult) window._orbComboResult(isWin);
  }};

  // ── Wallet NAV animated counter ───────────────────────────────────────────
  var _navAnimRaf = null;
  window._animateWalletNav = function(el, toStr) {{
    if (!el) return;
    var fromNum = parseFloat((el.textContent || '$0').replace(/[^0-9.-]/g,'')) || 0;
    var toNum   = parseFloat(toStr.replace(/[^0-9.-]/g,'')) || 0;
    if (Math.abs(fromNum - toNum) < 1) {{ el.textContent = toStr; el.setAttribute('data-val', toStr); return; }}
    if (_navAnimRaf) cancelAnimationFrame(_navAnimRaf);
    var start = null, dur = 750;
    function step(ts) {{
      if (!start) start = ts;
      var p = Math.min(1, (ts - start) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      var cur = Math.round(fromNum + (toNum - fromNum) * e);
      var s = '$' + cur.toLocaleString('en-US');
      el.textContent = s; el.setAttribute('data-val', s);
      if (p < 1) {{ _navAnimRaf = requestAnimationFrame(step); }}
      else {{ el.textContent = toStr; el.setAttribute('data-val', toStr); _navAnimRaf = null; }}
    }}
    _navAnimRaf = requestAnimationFrame(step);
  }};

  var b = document.getElementById('term-body');
  if (b) {{ b.scrollTop = 0; }}  // newest entries are at top

  // ── Panel resize (horizontal + vertical) ───────────────────────────────
  (function() {{
    // Horizontal column drag
    function makeColDrag(handle, leftPanel, rightPanel, leftHdr, rightHdr) {{
      var dragging = false, startX = 0, startLeft = 0, startRight = 0;
      function begin(clientX) {{
        dragging = true; startX = clientX;
        startLeft = leftPanel.offsetWidth; startRight = rightPanel.offsetWidth;
        handle.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      }}
      function move(clientX) {{
        if (!dragging) return;
        var delta = clientX - startX;
        var nL = Math.max(120, startLeft + delta);
        var nR = Math.max(120, startRight - delta);
        leftPanel.style.width = nL + 'px'; leftPanel.style.flexShrink = '0';
        rightPanel.style.width = nR + 'px'; rightPanel.style.flexShrink = '0';
        if (leftHdr)  {{ leftHdr.style.width = nL + 'px';  leftHdr.style.flex = 'none'; }}
        if (rightHdr) {{ rightHdr.style.width = nR + 'px'; rightHdr.style.flex = 'none'; }}
      }}
      function end() {{
        if (!dragging) return;
        dragging = false; handle.classList.remove('dragging');
        document.body.style.cursor = ''; document.body.style.userSelect = '';
      }}
      handle.addEventListener('mousedown', function(e) {{ begin(e.clientX); e.preventDefault(); }});
      document.addEventListener('mousemove', function(e) {{ move(e.clientX); }});
      document.addEventListener('mouseup', end);
      handle.addEventListener('touchstart', function(e) {{ begin(e.touches[0].clientX); }}, {{passive:true}});
      document.addEventListener('touchmove', function(e) {{ move(e.touches[0].clientX); }}, {{passive:true}});
      document.addEventListener('touchend', end);
    }}

    // Panel drag disabled — panels are now absolute overlays, not flex columns

    // Vertical overlay drag (drag the top edge to resize height)
    var overlay  = document.getElementById('term-overlay');
    var vertDrag = document.getElementById('vert-drag');
    if (overlay && vertDrag) {{
      var vDragging = false, vStartY = 0, vStartH = 0;
      function vBegin(clientY) {{
        vDragging = true; vStartY = clientY; vStartH = overlay.offsetHeight;
        vertDrag.classList.add('dragging');
        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
      }}
      function vMove(clientY) {{
        if (!vDragging) return;
        var delta = vStartY - clientY;   // drag up → taller
        var newH = Math.max(80, Math.min(window.innerHeight * 0.75, vStartH + delta));
        overlay.style.height = newH + 'px';
        overlay.style.maxHeight = 'none';
      }}
      function vEnd() {{
        if (!vDragging) return;
        vDragging = false; vertDrag.classList.remove('dragging');
        document.body.style.cursor = ''; document.body.style.userSelect = '';
      }}
      vertDrag.addEventListener('mousedown', function(e) {{ vBegin(e.clientY); e.preventDefault(); }});
      document.addEventListener('mousemove', function(e) {{ vMove(e.clientY); }});
      document.addEventListener('mouseup', vEnd);
      vertDrag.addEventListener('touchstart', function(e) {{ vBegin(e.touches[0].clientY); }}, {{passive:true}});
      document.addEventListener('touchmove', function(e) {{ vMove(e.touches[0].clientY); }}, {{passive:true}});
      document.addEventListener('touchend', vEnd);
    }}
  }})();
  // ── end resize ──────────────────────────────────────────────────────────

  function fmtCountdown(diff) {{
    if (diff <= 0) return 'now';
    var h = Math.floor(diff / 3600000);
    var m = Math.floor((diff % 3600000) / 60000);
    var s = Math.floor((diff % 60000) / 1000);
    if (h > 0) return h + 'h ' + String(m).padStart(2,'0') + 'm ' + String(s).padStart(2,'0') + 's';
    if (m > 0) return m + 'm ' + String(s).padStart(2,'0') + 's';
    return s + 's';
  }}
  window._fmtCountdown = fmtCountdown;

  // ── Dynamic queue ────────────────────────────────────────────────────────────
  function _nextEquityPipelineMs() {{
    var now = new Date();
    var etOffset = -5 * 60;
    var etNow = new Date(now.getTime() + (now.getTimezoneOffset() + etOffset) * 60000);
    var target = new Date(etNow); target.setHours(16, 5, 0, 0);
    if (etNow >= target) target.setDate(target.getDate() + 1);
    return target - etNow;
  }}

  // HUD open threshold: any action within this many ms shows the HUD
  var HUD_THRESHOLD = 30000;
  var _hudOpen = false;

  function _setHud(open) {{
    var hud = document.getElementById('hud-overlay');
    if (!hud) return;
    if (open === _hudOpen) return;
    _hudOpen = open;
    if (open) {{ hud.classList.add('hud-open'); }}
    else      {{ hud.classList.remove('hud-open'); }}
  }}

  function _updateDynamicQueue() {{
    var now = Date.now();
    var items = [];

    // Crypto scan
    var scanTarget = (window._lastRunAt || now) + 75000;
    var scanDiff   = Math.max(0, scanTarget - now);
    var scanPairs  = window._cryptoPairCount || 15;
    items.push({{
      badge:'SCAN', label:'CRYPTO · ALL PAIRS',
      detail: scanPairs + ' pairs · EMA 3/8 signal',
      color:'#00e5ff', diff: scanDiff,
    }});

    // Equity pipeline
    var eqDiff = _nextEquityPipelineMs();
    items.push({{
      badge:'REBALANCE', label:'EQUITY PIPELINE',
      detail:'momentum · top-5 rebalance',
      color:'#9400ff', diff: eqDiff,
    }});

    // Per-position timeouts (<90s)
    var positions = window._cryptoPositionsMap || {{}};
    Object.values(positions).forEach(function(p) {{
      var exitAt = new Date(p.entered_at).getTime() + 4 * 60 * 1000;
      var diff   = exitAt - now;
      if (diff > 0 && diff < 90000) {{
        items.push({{
          badge:'TIMEOUT', label:p.symbol.replace('/USD','') + ' · MAX HOLD',
          detail:'force evaluation · stop/target check',
          color: diff < 30000 ? '#ff3366' : '#ff9900', diff: diff,
        }});
      }}
    }});

    // Sort most urgent first
    items.sort(function(a, b) {{ return a.diff - b.diff; }});

    // Determine if HUD should open (any item within threshold)
    var anyImminent = items.some(function(it) {{ return it.diff <= HUD_THRESHOLD; }});
    _setHud(anyImminent);

    // Populate HUD items
    var hudItems = document.getElementById('hud-items');
    if (hudItems) {{
      hudItems.innerHTML = items.map(function(it) {{
        var imminent = it.diff < 15000;
        var urgent   = it.diff < 60000;
        var timerTxt = imminent ? 'EXECUTING' : fmtCountdown(it.diff);
        var timerCls = 'hud-timer' + (imminent ? ' hud-imminent' : urgent ? ' hud-urgent' : '');
        var itemCls  = 'hud-item' + (imminent ? ' hud-imminent' : '');
        return '<div class="' + itemCls + '" style="color:' + it.color + '">' +
          '<div class="hud-badge">' + it.badge + '</div>' +
          '<div class="hud-sym">' + it.label + '</div>' +
          '<div class="hud-detail">' + it.detail + '</div>' +
          '<div class="' + timerCls + '">' + timerTxt + '</div>' +
          '</div>';
      }}).join('');
    }}
  }}

  function tick() {{
    var now = Date.now();
    var n = new Date();
    var etParts = n.toLocaleDateString('en-US', {{timeZone:'America/New_York', month:'numeric', day:'numeric', year:'2-digit'}}).split('/');
    var etTime  = n.toLocaleTimeString('en-US', {{timeZone:'America/New_York', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}});
    var el = document.getElementById('live-clock');
    if (el) el.textContent = etParts[0]+'/'+etParts[1]+'/'+etParts[2]+'  '+etTime+'  ';

    document.querySelectorAll('.q-timer').forEach(function(el) {{
      var target = parseInt(el.getAttribute('data-target'), 10);
      var diff = target - now;
      var item = el.closest('.q-item');
      if (diff <= -3000) {{
        /* 3s grace period then slide out and remove */
        if (item && !item.classList.contains('q-dying')) {{
          item.classList.add('q-dying');
          item.style.transition = 'max-height .5s ease, opacity .5s ease, padding .5s ease';
          item.style.maxHeight = item.offsetHeight + 'px';
          requestAnimationFrame(function() {{
            item.style.maxHeight = '0';
            item.style.opacity = '0';
            item.style.paddingTop = '0';
            item.style.paddingBottom = '0';
          }});
          setTimeout(function() {{ if (item.parentNode) item.parentNode.removeChild(item); }}, 520);
        }}
        return;
      }}
      el.textContent = fmtCountdown(diff);
      el.classList.remove('urgent','imminent');
      if (diff <= 0) {{ el.textContent = 'executing...'; el.classList.add('imminent'); }}
      else if (diff < 300000) el.classList.add('imminent');
      else if (diff < 3600000) el.classList.add('urgent');
    }});
  }}
  // Sync HUD to feed overlay bounds
  function _syncHud() {{
    var feed = document.getElementById('feed-overlay');
    var hud  = document.getElementById('hud-overlay');
    if (!feed || !hud) return;
    var r = feed.getBoundingClientRect();
    hud.style.left  = r.left + 'px';
    hud.style.width = r.width + 'px';
    hud.style.right = 'auto';
  }}
  _syncHud();
  window.addEventListener('resize', _syncHud);

  // Position count badge removed (redundant with card count)
  function _updatePosCounts() {{ /* no-op */ }}

  // Last feed event tracker — updated by feed poller when new entry added
  window._lastFeedEventMs = Date.now();
  function _tickFeedAgo() {{
    var ago = document.getElementById('feed-last-ago');
    if (!ago) return;
    var diff = Math.floor((Date.now() - window._lastFeedEventMs) / 1000);
    if (diff < 5)        ago.textContent = 'just now';
    else if (diff < 60)  ago.textContent = diff + 's ago';
    else if (diff < 3600) ago.textContent = Math.floor(diff/60) + 'm ago';
    else                 ago.textContent = Math.floor(diff/3600) + 'h ago';
    // Color: green when fresh, dims over time
    var alpha = Math.max(0.18, 0.7 - diff * 0.008);
    ago.style.color = 'rgba(100,0,160,' + alpha + ')';
    if (diff < 10) ago.style.color = '#00ff9d';
    else if (diff < 30) ago.style.color = '#9400ff';
  }}

  // ── Strategy health indicator ──────────────────────────────────────────────────
  (function() {{
    var _dot   = document.getElementById('strat-health-dot');
    var _label = document.getElementById('strat-health-label');
    var _lastTradeMs = window._lastFeedEventMs || Date.now();
    // Also track only trade events (not all feed events)
    var _origPost = window._postToFeed;
    window._postToFeed = function(plain, ts, html) {{
      if (_origPost) _origPost(plain, ts, html);
      var _h = html || plain;
      if (_h.indexOf('>enter<') !== -1 || _h.indexOf('>exit<') !== -1) {{
        _lastTradeMs = Date.now();
      }}
    }};
    function _tickHealth() {{
      if (!_dot || !_label) return;
      var age = (Date.now() - _lastTradeMs) / 1000;
      var cls, txt;
      if (age < 300) {{        // < 5 min: healthy
        cls = 'green';  txt = 'LIVE';
      }} else if (age < 900) {{ // 5–15 min: warning
        cls = 'yellow'; txt = 'SLOW';
      }} else {{                // > 15 min: stale
        cls = 'red';    txt = 'IDLE';
      }}
      _dot.className = cls;
      _label.textContent = txt;
    }}
    _tickHealth();
    setInterval(_tickHealth, 10000);
  }})();

  // ── Position card scan animation — staggered sweeps across all visible cards ──
  function _scanPositionCards() {{
    var cards = document.querySelectorAll('#pos-overlay .pos-card');
    if (!cards.length) return;
    cards.forEach(function(card, i) {{
      setTimeout(function() {{
        card.classList.remove('pos-card-scanning');
        void card.offsetWidth; // reflow to restart
        card.classList.add('pos-card-scanning');
        setTimeout(function() {{ card.classList.remove('pos-card-scanning'); }}, 1200);
      }}, i * 180); // stagger each card by 180ms
    }});
  }}
  setTimeout(_scanPositionCards, 4000);
  setInterval(_scanPositionCards, 12000); // scan every 12s

  tick();
  setInterval(function() {{ tick(); _tickFeedAgo(); _updateDynamicQueue(); _syncHud(); _updatePosCounts(); }}, 1000);
  _updateDynamicQueue(); // immediate first render

  // ── Terminal feed ─────────────────────────────────────────────────────────────
  (function() {{

    var _feedQueue = [];
    // ── Next-run progress bar ─────────────────────────────────────────────────
    var _RUN_INTERVAL = 75;  // seconds — 60s sleep + ~15s execution = loop cycle
    var _lastRunAt    = Date.now();
    window._lastRunAt = _lastRunAt; // expose for dynamic queue
    var _progTimer    = null;

    function _resetRunTimer() {{
      _lastRunAt = Date.now();
      window._lastRunAt = _lastRunAt;
    }}

    function _tickProgress() {{
      if (_progTimer) clearInterval(_progTimer);
      _progTimer = setInterval(function() {{
        var elapsed   = (Date.now() - _lastRunAt) / 1000;
        var pct       = Math.min(elapsed / _RUN_INTERVAL * 100, 100);
        var fill      = document.getElementById('run-progress-fill');
        var lbl       = document.getElementById('run-progress-label');
        var wrap      = document.getElementById('run-progress-wrap');
        if (fill) {{
          fill.style.width = pct.toFixed(1) + '%';
          fill.classList.toggle('firing', pct >= 95);
        }}
        if (lbl) {{
          var rem = Math.max(0, Math.round(_RUN_INTERVAL - elapsed));
          if (pct >= 100) {{
            lbl.textContent = '▸▸▸';
            lbl.style.color = '#00e5ff';
            lbl.style.textShadow = '0 0 12px rgba(0,229,255,1)';
          }} else {{
            lbl.textContent = String(rem).padStart(3,'0') + 's';
            // cyan → magenta → hot pink in last 15s
            var heat = Math.max(0, (15 - rem) / 15);
            var r = Math.round(204 + heat * 51);
            var g = Math.round(0);
            var b = Math.round(255 - heat * 145);
            lbl.style.color = 'rgb(' + r + ',' + g + ',' + b + ')';
            lbl.style.textShadow = '0 0 ' + (8 + heat * 8) + 'px rgba(' + r + ',0,' + b + ',.9)';
          }}
        }}
        if (wrap) wrap.classList.remove('hidden');
      }}, 1000);
    }}

    // Expose globally so the feed poller (separate IIFE) can reset it
    window._resetRunTimer = _resetRunTimer;

    // ── Equity position hold-timer tick ──────────────────────────────────────
    // `.pc-days` elements have data-days (integer days from Python).
    // This ticks up the displayed seconds within today so it feels live.
    (function() {{
      var _dayStart = new Date(); _dayStart.setHours(0,0,0,0);
      setInterval(function() {{
        var secsToday = Math.floor((Date.now() - _dayStart.getTime()) / 1000);
        document.querySelectorAll('.pc-days[data-days]').forEach(function(el) {{
          var d = parseInt(el.getAttribute('data-days'), 10) || 0;
          var totalSecs = d * 86400 + secsToday;
          var dd = Math.floor(totalSecs / 86400);
          var hh = Math.floor((totalSecs % 86400) / 3600);
          var mm = Math.floor((totalSecs % 3600) / 60);
          var ss = totalSecs % 60;
          el.textContent = '⏱ ' + dd + 'd ' +
            String(hh).padStart(2,'0') + ':' +
            String(mm).padStart(2,'0') + ':' +
            String(ss).padStart(2,'0');
        }});
      }}, 1000);
    }})();

    // Wire the crypto-cycle chip bar to _lastRunAt
    setInterval(function() {{
      var fill  = document.getElementById('crypto-cycle-fill');
      var eta   = document.getElementById('crypto-cycle-eta');
      if (!fill || !eta) return;
      var elapsed = (Date.now() - _lastRunAt) / 1000;
      var pct     = Math.min(elapsed / _RUN_INTERVAL * 100, 100);
      var rem     = Math.max(Math.round(_RUN_INTERVAL - elapsed), 0);
      fill.style.width = pct + '%';
      fill.style.background = pct > 90 ? '#00ff9d' : '#00e5ff';
      eta.textContent = rem + 's';
    }}, 500);

    // ── postToFeed: prepend newest to top, trim from tail ───────────────────
    function postToFeed(plain, timestamp, html) {{
      var _h  = html || plain;
      var tb  = document.getElementById('term-body');
      if (!tb) return;
      var now  = timestamp ? new Date(timestamp) : new Date();
      var hhmm = now.toLocaleTimeString('en-US', {{timeZone:'America/New_York', hour:'2-digit', minute:'2-digit', hour12:false}});
      var row  = document.createElement('div');
      var isTrade = (_h.indexOf('>enter<') !== -1 || _h.indexOf('>exit<') !== -1) && _h.indexOf('@') !== -1;
      var isUser  = plain && plain.indexOf('[USER]') === 0;
      if (isTrade || isUser) {{
        row.className = 'te te-new';
        var _isEntry  = isUser ? (plain.indexOf('BUY') !== -1) : (_h.indexOf('>enter<') !== -1);
        var _isWin    = !_isEntry && (_h.indexOf('color:#00ff9d') !== -1);
        var _flashCol = _isEntry ? '#ffffff' : (_isWin ? '#00ff9d' : '#ff4466');
        var _dimCol   = _isEntry ? 'rgba(200,200,220,.55)' : (_isWin ? 'rgba(0,210,130,.55)' : 'rgba(255,60,80,.55)');
        row.style.color = _flashCol;
        row.style.textShadow = '0 0 10px ' + _flashCol;
        setTimeout(function() {{
          row.style.transition = 'color 2s ease, text-shadow 2s ease';
          row.style.color = _dimCol;
          row.style.textShadow = 'none';
        }}, 1800);
      }} else {{
        row.className = 'te te-new';
        row.style.color = '#4a3060';
        row.style.textShadow = 'none';
      }}
      row.innerHTML = '<span class="te-ts">' + hhmm + '<span style="font-size:7px;opacity:.4;letter-spacing:.08em"> ET</span>&nbsp;&nbsp;</span>' + _h;
      tb.insertBefore(row, tb.firstChild);
      // Keep viewport on newest (top) if user hasn't scrolled down intentionally
      if (tb.scrollTop < 40) tb.scrollTop = 0;
      // Trim oldest entries (now at tail)
      while (tb.children.length > 50) tb.removeChild(tb.lastChild);
      window._lastFeedEventMs = Date.now();
    }}

    // Expose globally
    window._postToFeed = postToFeed;

    // On load: show server-rendered entries
    var tb = document.getElementById('term-body');
    if (tb) {{
      tb.querySelectorAll('.te').forEach(function(el) {{ el.style.opacity = '1'; }});
    }}

    // Live clock at top of terminal
    (function() {{
      var clk = document.getElementById('term-clock');
      var _BLOCKS = 12;
      function _tickClock() {{
        if (!clk) return;
        // Derive clock from DB timestamps so it matches terminal log entries exactly.
        // When a DB anchor is known, extrapolate forward from it. Fall back to new Date().
        var now;
        if (window._lastKnownTs && window._lastLivePriceMs) {{
          var _ts = window._lastKnownTs; _ts = _ts.replace(' ','T'); if (/[+-]\d{{2}}$/.test(_ts)) _ts += ':00'; else if (!/Z|[+-]\d{{2}}:\d{{2}}$/.test(_ts)) _ts += 'Z';
          now = new Date(new Date(_ts).getTime() + (Date.now() - window._lastLivePriceMs));
        }} else {{
          now = new Date();
        }}
        var hhmm  = now.toLocaleTimeString('en-US', {{timeZone:'America/New_York', hour:'2-digit', minute:'2-digit', hour12:false}});
        var elapsed = window._lastRunAt ? (Date.now() - window._lastRunAt) / 1000 : 0;
        var pct     = Math.min(elapsed / (_RUN_INTERVAL || 75), 1);
        var filled  = Math.round(pct * _BLOCKS);
        var bar     = '▓'.repeat(filled) + '░'.repeat(_BLOCKS - filled);
        var rem     = Math.max(0, Math.round((_RUN_INTERVAL || 75) - elapsed));
        var remStr  = pct >= 1 ? '▸▸▸' : String(rem).padStart(3,'0') + 's';
        var filledCol = pct >= 0.9 ? 'rgba(255,120,0,.9)' : '#ffffff';
        var emptyCol  = 'rgba(255,255,255,.18)';
        var filledBar = '<span style="color:' + filledCol + ';font-size:9px;letter-spacing:.04em">' + '▓'.repeat(filled) + '</span>';
        var emptyBar  = '<span style="color:' + emptyCol + ';font-size:9px;letter-spacing:.04em">' + '░'.repeat(_BLOCKS - filled) + '</span>';
        clk.innerHTML = '<span style="color:#fff;font-size:9px;margin-right:3px">' + hhmm + '</span>'
          + '<span style="color:rgba(255,255,255,.28);font-size:7px;letter-spacing:.12em;margin-right:6px">ET</span>'
          + filledBar + emptyBar
          + '<span style="color:rgba(255,255,255,.35);font-size:9px;letter-spacing:.1em;margin-left:5px">' + remStr + '</span>';
      }}
      _tickClock();
      setInterval(_tickClock, 1000);
    }})();

    // ── Event countdown notifications ────────────────────────────────────────
    // Fires a callout card 60s before each scheduled event; card shows a live
    // countdown for the final 10s then flashes "NOW" at execution.
    (function() {{
      var ET = 'America/New_York';
      // Returns ms until next occurrence of hh:mm ET on a weekday
      function _msUntilET(h, m) {{
        var n = new Date();
        // Build a candidate date in ET
        var etStr = n.toLocaleString('en-US', {{timeZone:ET}});
        var etNow = new Date(etStr);
        var t = new Date(etNow); t.setHours(h, m, 0, 0);
        if (t <= etNow) t.setDate(t.getDate() + 1);
        while (t.getDay() === 0 || t.getDay() === 6) t.setDate(t.getDate() + 1);
        // Convert back to wall-clock delta
        return (t - etNow);
      }}

      var _EVENTS = [
        {{ label:'MARKET OPEN',  h:9,  m:30, col:'#00e5ff' }},
        {{ label:'MARKET CLOSE', h:16, m:0,  col:'#9400ff' }},
        {{ label:'PIPELINE RUN', h:16, m:5,  col:'#ff00cc' }},
      ];
      var _fired = {{}}; // key → last fire date string so we don't double-fire

      function _checkEvents() {{
        var today = new Date().toLocaleDateString('en-US', {{timeZone:ET}});
        _EVENTS.forEach(function(ev) {{
          var key = ev.label + ':' + today;
          if (_fired[key]) return;
          var ms = _msUntilET(ev.h, ev.m);
          if (ms <= 60000) {{
            _fired[key] = true;
            if (window._fireEventCallout) window._fireEventCallout(ev.label, ev.col, ms / 1000);
          }}
        }});
      }}

      setInterval(_checkEvents, 1000);
    }})();

    // Kick off the progress bar — inside IIFE where _tickProgress is in scope
    _tickProgress();

  }})();

  // ── Crosshair on portfolio dot ───────────────────────────────────────────────
  function showCrosshair() {{
    var overlay = document.getElementById('crosshair-overlay');
    var xc      = document.getElementById('xhair-canvas');
    var gd2     = document.getElementById('chart');
    if (!overlay || !xc || !gd2 || !gd2._fullLayout) {{
      // Retry up to 3s if layout not ready yet
      if (!showCrosshair._tries) showCrosshair._tries = 0;
      if (++showCrosshair._tries < 6) setTimeout(showCrosshair, 500);
      return;
    }}
    showCrosshair._tries = 0;
    try {{
      var fl  = gd2._fullLayout;
      // Find portfolio trace by name
      var tr = null;
      for (var i = 0; i < gd2.data.length; i++) {{
        if (gd2.data[i].name && gd2.data[i].name.toLowerCase().indexOf('portfolio') >= 0) {{
          tr = gd2.data[i]; break;
        }}
      }}
      if (!tr) tr = gd2.data[0]; // fallback to first trace
      if (!tr || !tr.x || !tr.x.length) return;
      var px = fl.xaxis.l2p(fl.xaxis.d2l(tr.x[tr.x.length-1])) + fl.margin.l;
      var py = fl.yaxis.l2p(fl.yaxis.d2l(tr.y[tr.y.length-1])) + fl.margin.t;

      xc.width  = overlay.offsetWidth;
      xc.height = overlay.offsetHeight;
      var ctx = xc.getContext('2d');
      var Y = '#FFE500';
      ctx.clearRect(0, 0, xc.width, xc.height);

      // Full cross lines
      ctx.strokeStyle = 'rgba(255,229,0,0.35)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 6]);
      ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(xc.width, py); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, xc.height); ctx.stroke();
      ctx.setLineDash([]);

      // Corner brackets (retro radar lock)
      var S = 14, G = 4;
      ctx.strokeStyle = Y; ctx.lineWidth = 2;
      [[px-G-S, py-G-S, 1, 1], [px+G+S, py-G-S, -1, 1],
       [px-G-S, py+G+S, 1, -1], [px+G+S, py+G+S, -1, -1]].forEach(function(c) {{
        ctx.beginPath();
        ctx.moveTo(c[0], c[1]); ctx.lineTo(c[0] + c[2]*S, c[1]);
        ctx.moveTo(c[0], c[1]); ctx.lineTo(c[0], c[1] + c[3]*S);
        ctx.stroke();
      }});

      // Center dot
      ctx.shadowColor = Y; ctx.shadowBlur = 12;
      ctx.fillStyle = Y;
      ctx.beginPath(); ctx.arc(px, py, 3.5, 0, Math.PI*2); ctx.fill();
      ctx.shadowBlur = 0;

      // Label
      ctx.fillStyle = Y; ctx.font = '700 8px Consolas,monospace';
      ctx.letterSpacing = '0.18em';
      ctx.fillText('TARGET ACQUIRED', px + G + S + 6, py + 4);

      // Fade in → hold → fade out → then zoom tightens
      overlay.style.transition = 'opacity 300ms ease';
      overlay.style.opacity = '1';
      setTimeout(function() {{
        overlay.style.transition = 'opacity 400ms ease';
        overlay.style.opacity = '0';
        // Snap to 60-day window
        var yr2 = yRange(xStart, xEnd);
        Plotly.relayout(gd2, {{
          'xaxis.range': [xStart, xEnd],
          'yaxis.range': yr2[0] !== null ? yr2 : undefined
        }});
      }}, 1100);
    }} catch(e) {{}}
  }}

  // ── Buy console ───────────────────────────────────────────────────────────────

  // Populate ticker datalist from Python-seeded universe
  (function() {{
    var dl = document.getElementById('bc-tickers');
    if (!dl || !window._allTickers) return;
    // Only show equity tickers during NYSE hours; crypto is 24/7
    if (_isNYSEOpen()) {{
      (_allTickers.equity || []).forEach(function(s) {{
        var o = document.createElement('option'); o.value = s; dl.appendChild(o);
      }});
    }}
    (_allTickers.crypto || []).forEach(function(s) {{
      var o = document.createElement('option'); o.value = s; dl.appendChild(o);
    }});
  }})();

  function bcStatus(msg, col) {{
    var el = document.getElementById('bc-status');
    if (!el) return;
    el.textContent = msg;
    el.style.color = col || '#0a2a1a';
  }}

  // Route buy/sell through postMessage → parent shim → Alpaca
  function _submitOrder(sym, side, dollarAmt, notional) {{
    window.parent.postMessage({{
      type: 'tnd_order',
      sym: sym,
      side: side,
      notional: notional,  // dollar amount → Alpaca notional order
      strategy: 'user',
    }}, '*');
  }}

  function _isNYSEOpen() {{
    var now = new Date();
    // Convert to ET
    var etStr = now.toLocaleString('en-US', {{timeZone: 'America/New_York'}});
    var et = new Date(etStr);
    var day = et.getDay(); // 0=Sun, 6=Sat
    if (day === 0 || day === 6) return false;
    var h = et.getHours(), m = et.getMinutes();
    var mins = h * 60 + m;
    return mins >= 570 && mins < 960; // 9:30am–4:00pm ET
  }}

  function bcSubmit() {{
    var sym = (document.getElementById('bc-sym').value || '').trim().toUpperCase();
    var amt = parseFloat(document.getElementById('bc-amt').value || 0);
    if (!sym) {{ bcStatus('⚠ enter a ticker', '#ff9900'); return; }}
    if (!amt || amt <= 0) {{ bcStatus('⚠ enter dollar amount', '#ff9900'); return; }}

    // Block NYSE equities outside market hours
    var isCrypto = sym.indexOf('/') !== -1;
    if (!isCrypto && !_isNYSEOpen()) {{
      bcStatus('⚠ NYSE closed · crypto only', '#ff9900');
      return;
    }}

    var btn = document.getElementById('bc-buy');
    if (btn) btn.disabled = true;
    bcStatus('submitting…', '#00e5ff');

    _submitOrder(sym, 'buy', amt, amt);

    // Optimistic tile — only create if tile doesn't already exist (avoid value overwrite)
    var col = _symCol(sym);
    if (window._etUpsert && !(window._etBySym||{{}})[sym]) {{
      window._etUpsert({{
        sym: sym, col: col, val: amt, pnl: 0, pnlPct: 0,
        entry: 0, qty: 0, stop: 0, target: 0, curPrice: 0,
        days: 0, enteredAt: Date.now(), inSignal: true, rank: 0,
        holdText: '0s', strategy: 'user', isCrypto: isCrypto,
      }});
    }}

    var feedMsg = '[USER] BUY $' + amt.toLocaleString('en-US',{{maximumFractionDigits:0}}) + ' ' + sym + ' · market · routed to Alpaca';
    if (window._postToFeed) window._postToFeed(feedMsg);
    if (window._recordTradeForGauge) window._recordTradeForGauge();
    setTimeout(function() {{ if (window._pushIntradayPoint && window._lastKnownNav) window._pushIntradayPoint(new Date().toISOString(), window._lastKnownNav); }}, 5000);

    bcStatus('✓ BUY ' + sym + ' $' + amt.toLocaleString('en-US',{{maximumFractionDigits:0}}), '#00ff9d');
    document.getElementById('bc-amt').value = '';
    document.getElementById('bc-sym').value = '';
    setTimeout(function() {{ bcStatus('dbl-click holding to sell', ''); if (btn) btn.disabled = false; }}, 3000);
  }}

  // ── Double-click tile → sell full position ────────────────────────────────────
  (function() {{
    var _etC = document.getElementById('eq-tiles-canvas');
    if (!_etC) return;
    _etC.addEventListener('dblclick', function(e) {{
      var rect = _etC.getBoundingClientRect();
      var mx = e.clientX - rect.left;
      var my = e.clientY - rect.top;
      // Hit-test against live tiles
      var layout = (typeof _etLayout === 'function') ? _etLayout() : null;
      if (!layout) return;
      var hit = null;
      layout.live.forEach(function(t) {{
        if (t.phase === 'done') return;
        var pos = _etTilePos(t, layout);
        if (mx >= pos.x && mx < pos.x + _EQ_W && my >= pos.y && my < pos.y + _EQ_H) hit = t;
      }});
      if (!hit) return;

      // Show sell flash label
      var hint = document.createElement('div');
      hint.className = 'tc-dblclick-hint';
      hint.textContent = 'SELL ' + hit.sym;
      hint.style.left = (e.clientX - 30) + 'px';
      hint.style.top  = (e.clientY - 20) + 'px';
      document.body.appendChild(hint);
      setTimeout(function() {{ if (hint.parentNode) hint.parentNode.removeChild(hint); }}, 700);

      // Route to Alpaca
      _submitOrder(hit.sym, 'sell', hit.val, hit.val);

      // Feed label
      var feedMsg = '[USER] SELL ' + hit.sym + ' · full position · market · routed to Alpaca';
      if (window._postToFeed) window._postToFeed(feedMsg);
      if (window._recordTradeForGauge) window._recordTradeForGauge();
      setTimeout(function() {{ if (window._pushIntradayPoint && window._lastKnownNav) window._pushIntradayPoint(new Date().toISOString(), window._lastKnownNav); }}, 5000);

      // Trigger exit animation
      if (window._etExit) window._etExit(hit.sym, null, null);
    }});
  }})();

  // Keyboard shortcut: B focuses buy console
  document.addEventListener('keydown', function(e) {{
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'b' || e.key === 'B') document.getElementById('bc-amt').focus();
  }});

  // ── Live feed poller — Supabase REST, no page reload ────────────────────────
  (function() {{
    var SUPA_URL  = 'https://seeevuklabvhkawawtxn.supabase.co';
    var SUPA_KEY  = 'sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY';
    // Server already rendered history; start live polling from newest server event so poller never re-inserts them
    var _lastSeen = '{_newest_ev_ts_js}' || null;

    // Supabase returns "2026-07-12 14:57:23+00" — normalize to proper ISO UTC
    function _parseTs(s) {{
      if (!s) return new Date();
      s = s.replace(' ', 'T');                          // space → T
      if (/[+-]\d{{2}}$/.test(s)) s += ':00';           // +00 → +00:00
      else if (!/Z|[+-]\d{{2}}:\d{{2}}$/.test(s)) s += 'Z'; // bare → UTC
      return new Date(s);
    }}

    function _labelFor(eventType) {{
      var m = {{
        'TRADE':'TRADE','ENTRY':'BUY','EXIT':'SELL','SIGNAL':'SIGNAL',
        'SNAPSHOT':'NAV','START':'RUN','COMPLETE':'RUN','RISK_VETO':'VETO',
        'UPDATE':'UPDATE','INGEST':'DATA'
      }};
      return m[eventType] || eventType;
    }}

    function _poll() {{
      var url = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=event_type,symbol,message,recorded_at'
        + (_lastSeen
            ? '&recorded_at=gt.' + encodeURIComponent(_lastSeen) + '&order=recorded_at.asc&limit=20'
            : '&order=recorded_at.desc&limit=8');
      fetch(url, {{
        headers: {{
          'apikey': SUPA_KEY,
          'Authorization': 'Bearer ' + SUPA_KEY
        }}
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        if (!Array.isArray(rows) || !rows.length) {{ _lastSeen = _lastSeen || new Date().toISOString(); return; }}
        var isHistory = !_lastSeen;
        if (isHistory) rows = rows.slice().reverse(); // DESC → chronological
        if (window._resetRunTimer) window._resetRunTimer();

        // Deduplicate: skip any row we've already rendered (guards WS + poll race)
        if (!window._feedSeenKeys) window._feedSeenKeys = new Set();
        rows = rows.filter(function(row) {{
          var k = (row.recorded_at||'') + '|' + (row.symbol||'') + '|' + (row.message||'').slice(0,80);
          if (window._feedSeenKeys.has(k)) return false;
          window._feedSeenKeys.add(k);
          return true;
        }});
        if (!rows.length) return;

        // ── Batch processing: exits before entries, then batch PnL chip ─────────
        if (!isHistory) {{
          // Sort: exits first, then entries, within this batch
          rows = rows.slice().sort(function(a, b) {{
            var aIsExit  = (a.message||'').indexOf('EXIT')  !== -1;
            var bIsExit  = (b.message||'').indexOf('EXIT')  !== -1;
            var aIsEntry = (a.message||'').indexOf('ENTER') !== -1;
            var bIsEntry = (b.message||'').indexOf('ENTER') !== -1;
            // exits first
            if (aIsExit  && !bIsExit)  return -1;
            if (!aIsExit &&  bIsExit)  return  1;
            // then entries
            if (aIsEntry && !bIsEntry) return -1;
            if (!aIsEntry && bIsEntry) return  1;
            return 0;
          }});

          // Accumulate batch counts before any stagger fires
          var _batchPnl = 0, _exitCount = 0, _entryCount = 0, _tradeCount = 0;
          rows.forEach(function(r) {{
            var _msg = r.message || '';
            if (_msg.indexOf('EXIT') !== -1) {{
              var m = _msg.match(/pnl\s*([+-][\d,.]+)/);
              if (m) {{ _batchPnl += parseFloat(m[1].replace(/,/g,'')); _exitCount++; }}
              _tradeCount++;
            }}
            if (_msg.indexOf('ENTER') !== -1) {{ _entryCount++; _tradeCount++; }}
          }});
          var _batchDur = _tradeCount * 180; // total stagger duration

          // _showChip: shows chip and optionally drives decay on a companion value el
          // valId: id of the main number el; baseVal: real base number; bonusVal: the delta shown in chip
          function _showChip(id, text, col, onFade, valId, baseVal, bonusVal) {{
            var c = document.getElementById(id);
            if (!c) return;
            c.style.color = col;
            c.style.textShadow = '0 0 8px ' + col;
            c.textContent = text;
            c.style.opacity = '1';
            var DECAY_MS = 7000; // slower — 7s visible window
            var startTs = Date.now() + _batchDur;
            // If companion value provided, animate it decaying from base+bonus → base
            if (valId && bonusVal) {{
              var valEl = document.getElementById(valId);
              var decayRaf;
              function _decayStep() {{
                var now = Date.now();
                if (now < startTs) {{ decayRaf = requestAnimationFrame(_decayStep); return; }}
                var t = Math.min(1, (now - startTs) / DECAY_MS); // 0→1 over decay window
                var cur = baseVal + bonusVal * (1 - t); // interpolate bonus → 0
                if (valEl) {{
                  var isInt = (Math.abs(bonusVal) >= 1 && Math.floor(bonusVal) === bonusVal);
                  if (isInt) {{
                    valEl.textContent = Math.round(cur).toLocaleString('en-US');
                  }} else {{
                    var pos = cur >= 0;
                    valEl.textContent = (pos ? '+$' : '-$') + Math.abs(cur).toLocaleString('en-US', {{maximumFractionDigits:0}});
                    valEl.style.color = pos ? '#00c880' : '#e03355';
                  }}
                }}
                if (t < 1) {{ decayRaf = requestAnimationFrame(_decayStep); }}
              }}
              decayRaf = requestAnimationFrame(_decayStep);
            }}
            // Chip fades after decay window
            setTimeout(function() {{
              c.style.transition = 'opacity 1.2s ease';
              c.style.opacity = '0';
              if (onFade) onFade();
            }}, _batchDur + DECAY_MS);
          }}

          // P&L combo chip + sounds
          if (_exitCount > 0) {{
            var _isPos = _batchPnl >= 0;
            var _basePnl = parseFloat((document.getElementById('total-pnl-val') || {{}}).getAttribute('data-raw') || '0');

            // Show batch delta chip — decays companion P&L value from base+bonus → base
            _showChip('batch-pnl-chip',
              (_isPos ? '+' : '') + _batchPnl.toFixed(2),
              _isPos ? '#00c880' : '#e03355', null,
              'total-pnl-val', _basePnl, _batchPnl);

            // Immediately update Portfolio slot with this batch's P&L delta
            if (window._walletCombo) window._walletCombo(_batchPnl);
            // Orb-side popup
            if (window._orbBatchPnl) window._orbBatchPnl(_batchPnl);

            // Sound: one per batch
            if (_isPos && window._soundWin) window._soundWin();
            else if (!_isPos && window._soundLoss) window._soundLoss();

            // After stagger + chip settle: fetch real totals from DB (single source of truth)
            setTimeout(function() {{
              // Total P&L from fills table
              var pnlUrl = SUPA_URL + '/rest/v1/fills'
                + '?select=pnl&strategy=eq.crypto_momentum';
              fetch(pnlUrl, {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
              .then(function(r) {{ return r.json(); }})
              .then(function(rows) {{
                if (!Array.isArray(rows)) return;
                var total = rows.reduce(function(s, r) {{ return s + (parseFloat(r.pnl) || 0); }}, 0);
                var pv = document.getElementById('total-pnl-val');
                if (pv) {{
                  pv.setAttribute('data-raw', total);
                  var pos = total >= 0;
                  pv.style.color = pos ? '#00c880' : '#e03355';
                  pv.textContent = (pos ? '+$' : '-$') + Math.abs(total).toLocaleString('en-US', {{maximumFractionDigits:0}});
                }}
              }}).catch(function() {{}});
            }}, _batchDur + 1000);
          }}

          // Trades combo chip
          if (_tradeCount > 0) {{
            var _baseTrades = parseInt((document.getElementById('om-today') || {{}}).textContent || '0', 10);
            _showChip('trades-combo-chip', '+' + _tradeCount, '#ff9900', null,
              'om-today', _baseTrades, _tradeCount);
            if (window._tradeSlotCombo) window._tradeSlotCombo(_tradeCount);
          }}

          // Open positions delta chip — flash only, _pollPositions owns the persistent count
          var _posDelta = _entryCount - _exitCount;
          if (_posDelta !== 0) {{
            _showChip('pos-combo-chip',
              (_posDelta > 0 ? '+' : '') + _posDelta,
              _posDelta > 0 ? '#00e5ff' : '#ff4466', null);
          }}
        }}

        // Advance _lastSeen synchronously before stagger so concurrent WS polls don't re-fetch
        if (rows.length) _lastSeen = rows[rows.length - 1].recorded_at;

        // Stagger live batches so events drip in one-by-one (history: instant)
        var _staggerMs = isHistory ? 0 : 180;
        rows.forEach(function(row, _ri) {{ setTimeout(function() {{
          var raw = row.message || '';
          var raw = row.message || '';
          var sym = row.symbol || '';
          var display;
          if (row.event_type === 'TRADE' && (raw.indexOf('ENTER') !== -1 || raw.indexOf('EXIT') !== -1)) {{
            var isEntry = raw.indexOf('ENTER') !== -1;
            var verbPlain = isEntry ? 'enter' : 'exit';
            var verbCol   = isEntry ? '#00b4ff' : '#ff9900';
            var verbHtml  = '<span style="color:' + verbCol + '">' + verbPlain + '</span>';
            var symCol    = (function(s) {{
              var _c=sym.replace('/USD','').replace('USD','');
              if(window._TICKER_OVR&&window._TICKER_OVR[_c]) return window._TICKER_OVR[_c];
              var _p=['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
              var h=0; for(var i=0;i<_c.length;i++)h=(h*31+_c.charCodeAt(i))&0xffff; return _p[h%_p.length];
            }})(sym);
            var symHtml   = '<span style="color:' + symCol + ';font-weight:700">' + sym + '</span>';
            var priceM    = raw.match(/@\s*\$([\d,]+(?:\.\d+)?)/);
            var priceS    = priceM ? ' @ <span style="color:rgba(255,255,255,.55)">$' + priceM[1] + '</span>' : '';
            var pnlM      = raw.match(/pnl\s*([+-][\d,.]+)/);
            var pnlCol    = pnlM && pnlM[1][0] === '+' ? '#00c880' : '#e03355';
            var pnlHtml   = pnlM ? ' · <span style="color:' + pnlCol + '">' + pnlM[1] + '</span>' : '';
            var plain     = verbPlain + ' ' + sym;
            var html      = verbHtml + ' ' + symHtml + priceS + pnlHtml;
            if (window._postToFeed) window._postToFeed(plain, _parseTs(row.recorded_at), html);
            // All visual + audio effects fire in one synchronous block — no gaps
            if (!isHistory) {{
              if (window._recordTradeForGauge) window._recordTradeForGauge();
              var _fillPrice = parseFloat((raw.match(/\$([\d,.]+)/) || [])[1] || '0');
              var _qty = parseFloat((raw.match(/x([\d.]+)/) || [])[1] || '1');
              if (window._recordTradeVol && _fillPrice > 0) window._recordTradeVol(_fillPrice * _qty);
              if (!isEntry && pnlM && window._recordStreakResult) {{
                window._recordStreakResult(pnlM[1][0] === '+');
              }}
              if (isEntry) {{
                // ── ENTRY: veil flash + orb bloom + sound + card insert ──
                var _veilE = document.getElementById('trade-veil');
                if (_veilE) {{
                  _veilE.classList.remove('veil-entry','veil-win','veil-loss');
                  void _veilE.offsetWidth;
                  _veilE.classList.add('veil-entry');
                }}
                // No callout for entries — card appearing in positions panel is enough
                if (window._orbTradeFlash) window._orbTradeFlash(true);
                // sound fires from _etUpsert when tile animates in
                // Upsert crypto tile on canvas engine
                (function() {{
                  var _symE = sym.indexOf('/') !== -1 ? sym : sym + '/USD';
                  if (!(window._etBySym||{{}})[_symE]) {{
                    var _priceE = priceM ? parseFloat(priceM[1].replace(/,/g,'')) : 0;
                    var _ep = {{
                      symbol: _symE, direction: 'long', qty: 0,
                      entry_price: _priceE, stop_price: _priceE * 0.997,
                      target_price: _priceE * 1.006, entered_at: new Date().toISOString()
                    }};
                    if (!window._cryptoPositionsMap) window._cryptoPositionsMap = {{}};
                    window._cryptoPositionsMap[_symE] = _ep;
                    _makeCard(_ep); // → _etUpsert, no DOM element
                    // Fetch real qty from DB and backfill tile state
                    (function(_s) {{
                      var _qurl = 'https://seeevuklabvhkawawtxn.supabase.co/rest/v1/crypto_positions'
                        + '?select=qty,stop_price,target_price&symbol=eq.' + encodeURIComponent(_s);
                      fetch(_qurl, {{ headers: {{ 'apikey': 'sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY',
                        'Authorization': 'Bearer sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY' }} }})
                      .then(function(r) {{ return r.json(); }})
                      .then(function(rows) {{
                        if (!Array.isArray(rows) || !rows.length) return;
                        var row = rows[0];
                        var realQty = parseFloat(row.qty || 0);
                        if (window._cryptoPositionsMap[_s]) {{
                          window._cryptoPositionsMap[_s].qty = realQty;
                          window._cryptoPositionsMap[_s].stop_price = parseFloat(row.stop_price || 0);
                          window._cryptoPositionsMap[_s].target_price = parseFloat(row.target_price || 0);
                        }}
                        var t = (window._etBySym||{{}})[_s];
                        if (t) {{
                          t.qty   = realQty;
                          t.stop  = parseFloat(row.stop_price  || 0) || t.stop;
                          t.target= parseFloat(row.target_price|| 0) || t.target;
                          t.val   = realQty * t.curPrice;
                        }}
                        _updateOverlayWidth();
                      }}).catch(function() {{}});
                    }})(_symE);
                    _updateOverlayWidth();
                  }}
                }})();
              }} else {{
                // ── EXIT: ALL effects fire simultaneously — terminal flash + orb bloom +
                //          sound + satellite shoot-out + P&L odometer — one atomic block ──
                var _isWin = pnlM && pnlM[1][0] === '+';
                // 1. Veil flash — full chart area
                var _veilX = document.getElementById('trade-veil');
                if (_veilX) {{
                  _veilX.classList.remove('veil-entry','veil-win','veil-loss');
                  void _veilX.offsetWidth;
                  _veilX.classList.add(_isWin ? 'veil-win' : 'veil-loss');
                }}
                // Stratagem callout drop-in
                if (window._fireCallout) {{
                  var _xPrice = priceM ? parseFloat(priceM[1].replace(/,/g,'')).toFixed(2) : null;
                  var _xPnl   = pnlM ? pnlM[1] : null;
                  window._fireCallout(
                    sym.replace('/USD',''),
                    _xPrice,
                    _xPnl,
                    _isWin ? '#00ff9d' : '#ff3366'
                  );
                }}
                // 2. Orb bloom
                if (window._orbTradeFlash) window._orbTradeFlash(false, _isWin);
                // 3. Sound fires from _etExit when tile animation starts
                // 4. Satellite shoot-out + immediate map removal (1:1 with tile)
                var _exitSymFull = sym.indexOf('/') !== -1 ? sym : sym + '/USD';
                var _satKey = _satAngles[_exitSymFull] !== undefined ? _exitSymFull
                            : _satAngles[sym] !== undefined ? sym : null;
                if (_satKey) {{
                  _satExiting[_satKey] = {{
                    angle: _satAngles[_satKey],
                    orbitR: _smoothOrbitR[_satKey] || 32,
                    age: 0,
                    sr: _isWin ? 0 : 255, sg: _isWin ? 255 : 51, sb: _isWin ? 157 : 102
                  }};
                  delete _satAngles[_satKey];
                  delete _smoothOrbitR[_satKey];
                }}
                // Remove from positions map immediately so count stays 1:1 with tiles
                if (window._cryptoPositionsMap) {{
                  delete window._cryptoPositionsMap[_exitSymFull];
                  delete window._cryptoPositionsMap[sym];
                }}
                // 5. P&L odometer — starts same RAF tick as satellite
                if (pnlM) {{
                  var _pnlEl = document.getElementById('total-pnl-val');
                  var _subEl = document.getElementById('total-pnl-sub');
                  if (_pnlEl) {{
                    var _raw    = parseFloat(_pnlEl.getAttribute('data-raw') || '0') || 0;
                    var _delta  = parseFloat(pnlM[1].replace(/,/g,'')) || 0;
                    var _target = _raw + _delta;
                    _pnlEl.setAttribute('data-raw', _target);
                    var _isPos  = _target >= 0;
                    var _col    = _isPos ? '#00ff9d' : '#ff3366';
                    _pnlEl.style.color = _col;
                    if (_subEl) _subEl.style.color = _col;
                    _pnlEl.classList.remove('pnl-flash-pos','pnl-flash-neg');
                    void _pnlEl.offsetWidth;
                    _pnlEl.classList.add(_isPos ? 'pnl-flash-pos' : 'pnl-flash-neg');
                    var _odoStart = _raw, _odoEnd = _target, _odoT0 = performance.now();
                    function _odoFrame(now) {{
                      var p = Math.min(1, (now - _odoT0) / 600);
                      var ease = 1 - Math.pow(1-p, 3);
                      var v = _odoStart + (_odoEnd - _odoStart) * ease;
                      var sign = v >= 0 ? '+' : '−';
                      _pnlEl.textContent = sign + '$' + Math.abs(Math.round(v)).toLocaleString('en-US');
                      if (_subEl) {{
                        var pct = (v / 100000) * 100;
                        _subEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '% since $100K start';
                      }}
                      if (p < 1) requestAnimationFrame(_odoFrame);
                    }}
                    requestAnimationFrame(_odoFrame);
                  }}
                }}
                // 6. Card exit animation (with sell price)
                if (window._triggerCardExit) {{
                  var _reasonM = raw.match(/·\s*(target|stop|timeout|reversal|signal)\s*$/i);
                  var _exitReason = _reasonM ? _reasonM[1].toLowerCase() : (_isWin ? 'target' : 'stop');
                  var _exitPrice = priceM ? priceM[1] : null;
                  window._triggerCardExit(sym, _exitReason, pnlM ? parseFloat(pnlM[1].replace(/,/g,'')) : null, _exitPrice);
                }}
              }}
            }}
            // Wallet canvas trade burst
            if (!isHistory && window._walletTrade) {{
              var isWinW = isEntry ? true : (pnlM ? pnlM[1][0] === '+' : false);
              var priceW = priceM ? priceM[1] : '';
              window._walletTrade(isEntry, isWinW, sym, priceW);
            }}
            // Trigger chart trade marker refresh
            if (!isHistory && window._onLiveTrade) window._onLiveTrade();
          }} else if (row.event_type === 'UPDATE') {{
            if (!isHistory) {{
              // Parse open symbols
              var symMatch = raw.match(/\(([^)]+)\)/);
              var symList = symMatch
                ? symMatch[1].split(',').map(function(s) {{ return s.trim(); }}).filter(Boolean)
                : [];
              if (window._triggerScan) window._triggerScan(symList);
              if (window._walletScan) window._walletScan();
            }}
          }} else {{
            // Suppress scan messages — handled by VHS bar, not the feed
            if (raw.toLowerCase().indexOf('scan complete') !== -1) return;
            if (raw.toLowerCase().indexOf('scan ') === 0) return;
            var label = _labelFor(row.event_type);
            var txt   = raw || (label + (sym ? ' · ' + sym : ''));
            if (window._postToFeed) window._postToFeed(txt, _parseTs(row.recorded_at));
          }}
        }}, _ri * _staggerMs); }}); // end stagger setTimeout + forEach
      }})
      .catch(function() {{}}); // silent — offline or auth issue
    }}

    // Poll every 3s as fallback — Realtime WebSocket triggers _poll instantly on insert
    setTimeout(function() {{
      _poll();
      setInterval(_poll, 3000);
    }}, 2000);

    // ── Supabase Realtime — instant push on pipeline_events INSERT ──────────────
    // Uses Phoenix channel protocol over WebSocket (no SDK required, free tier)
    (function() {{
      var WS_URL = 'wss://seeevuklabvhkawawtxn.supabase.co/realtime/v1/websocket'
        + '?apikey=sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY&vsn=1.0.0';
      var _ref = 0;
      var _ws, _hbTimer, _reconnTimer;

      function _send(obj) {{
        if (_ws && _ws.readyState === 1) _ws.send(JSON.stringify(obj));
      }}

      function _connect() {{
        try {{ _ws = new WebSocket(WS_URL); }} catch(e) {{ return; }}

        _ws.onopen = function() {{
          // Join postgres_changes channel for pipeline_events INSERTs
          _send({{
            topic: 'realtime:public:pipeline_events',
            event: 'phx_join',
            payload: {{
              config: {{
                broadcast: {{ self: false }},
                postgres_changes: [{{ event: 'INSERT', schema: 'public', table: 'pipeline_events' }}]
              }}
            }},
            ref: String(++_ref)
          }});
          // Heartbeat every 25s to keep connection alive
          clearInterval(_hbTimer);
          _hbTimer = setInterval(function() {{
            _send({{ topic: 'phoenix', event: 'heartbeat', payload: {{}}, ref: String(++_ref) }});
          }}, 25000);
        }};

        _ws.onmessage = function(e) {{
          try {{
            var msg = JSON.parse(e.data);
            // postgres_changes INSERT fires _poll immediately for zero-lag feed update
            if (msg.event === 'postgres_changes' &&
                msg.payload && msg.payload.data &&
                msg.payload.data.type === 'INSERT') {{
              _poll();
            }}
          }} catch(_) {{}}
        }};

        _ws.onclose = function() {{
          clearInterval(_hbTimer);
          // Reconnect after 5s
          clearTimeout(_reconnTimer);
          _reconnTimer = setTimeout(_connect, 5000);
        }};
      }}

      _connect();
    }})();
  }})();

  // ── Live NAV poller — updates chart + all NAV displays in-place ─────────────
  (function() {{
    var SUPA_URL = 'https://seeevuklabvhkawawtxn.supabase.co';
    var SUPA_KEY = 'sb_publishable_UFnDfeRb3XFs2UuT0LPPIg_B7K98OeY';
    var START_NAV = 100000;
    var _lastNavTs = null;

    function _fmt(v) {{
      return '$' + Math.round(v).toLocaleString('en-US');
    }}
    function _fmtRet(v, start) {{
      var pct = ((v - start) / start * 100).toFixed(2);
      return (pct >= 0 ? '+' : '') + pct + '%';
    }}
    function _retColor(v, start) {{
      return v >= start ? '#00ff9d' : '#ff3366';
    }}

    // Rolling nav history — localStorage persists across Streamlit reloads (unlike sessionStorage)
    if (!window._navHistory) {{
      try {{
        var _stored = localStorage.getItem('_navHistory');
        var _cutoffMs = Date.now() - 60*1000;
        window._navHistory = _stored
          ? JSON.parse(_stored).filter(function(p) {{ return new Date(p.x).getTime() > _cutoffMs; }})
          : [];
      }} catch(e) {{ window._navHistory = []; }}
    }}
    function _trackNav(nav, ts) {{
      window._navHistory.push({{ x: new Date(ts).toISOString(), y: parseFloat(nav) }});
      // keep last 200 points (canvas draw uses _navHistory as source of truth)
      if (window._navHistory.length > 200) window._navHistory.shift();
    }}

    function _updateNavDisplays(nav, ts) {{
      window._lastKnownNav = nav;
      if (window._updateWalletSlot) window._updateWalletSlot(nav);
      _trackNav(nav, ts);
      var col = _retColor(nav, START_NAV);
      var ret = _fmtRet(nav, START_NAV);
      var pnl = nav - START_NAV;
      var pnlStr = (pnl >= 0 ? '+' : '') + _fmt(Math.abs(pnl));

      // Topbar NAV stat
      document.querySelectorAll('.tb-stat-val').forEach(function(el, i) {{
        // NAV is first tb-stat-val
        if (i === 0) {{ el.textContent = _fmt(nav); el.style.color = '#ff00cc'; }}
        if (i === 1) {{ el.textContent = ret; el.style.color = col; }}
      }});

      // Wallet panel
      var wNav  = document.getElementById('wallet-nav');
      var wPnl  = document.getElementById('wallet-pnl');
      var wNoise = document.getElementById('wallet-noise');
      if (wNav) {{
        var newVal = _fmt(nav);
        if (wNav.textContent !== newVal) {{
          if (window._animateWalletNav) {{ window._animateWalletNav(wNav, newVal); }}
          else {{ wNav.textContent = newVal; wNav.setAttribute('data-val', newVal); }}
          if (wNoise) {{
            wNoise.classList.remove('sweep'); void wNoise.offsetWidth;
            wNoise.classList.add('sweep');
            setTimeout(function() {{ wNoise.classList.remove('sweep'); }}, 650);
          }}
        }}
      }}
      if (wPnl) {{ wPnl.textContent = (pnl >= 0 ? '+' : '−') + '$' + Math.abs(pnl).toLocaleString('en-US',{{maximumFractionDigits:0}}); wPnl.style.color = pnl >= 0 ? '#00ff9d' : '#ff3366'; }}
      // Feed wallet canvas engine
      if (window._walletNavUpdate) window._walletNavUpdate(nav);

      // nav-card overlay (top-left of chart)
      var nvVal = document.querySelector('.nv-val');
      var nvRet = document.querySelector('.nv-ret');
      var nvDpnl = document.querySelector('.nv-dpnl');
      if (nvVal) nvVal.textContent = _fmt(nav);
      if (nvRet) {{ nvRet.textContent = ret + ' vs $100K start'; nvRet.style.color = col; }}

      // pnl-float — animated counter + physical nudge
      var pnlFloat = document.querySelector('.pnl-float-val');
      var pnlSub   = document.querySelector('.pnl-float-sub');
      var pnlBox   = document.getElementById('pnl-float');
      if (pnlFloat) {{
        var fromVal = parseFloat(pnlFloat.getAttribute('data-raw') || '0');
        var toVal   = pnl;
        var sign    = toVal >= 0 ? '+' : '-';
        var signCol = toVal >= 0 ? '#00ff9d' : '#ff3366';
        pnlFloat.setAttribute('data-raw', toVal);
        pnlFloat.style.color = signCol;
        if (pnlBox) pnlBox.style.borderTopColor = signCol;
        // Animated digit roll
        var startTime = null;
        var dur = 800;
        function animPnl(ts) {{
          if (!startTime) startTime = ts;
          var p = Math.min((ts - startTime) / dur, 1);
          var ease = 1 - Math.pow(1 - p, 3); // ease-out cubic
          var cur = fromVal + (toVal - fromVal) * ease;
          var s = cur >= 0 ? '+' : '-';
          pnlFloat.textContent = s + '$' + Math.round(Math.abs(cur)).toLocaleString('en-US');
          if (p < 1) requestAnimationFrame(animPnl);
        }}
        requestAnimationFrame(animPnl);
        // Physical nudge
        if (pnlBox) {{
          var going = toVal > fromVal ? 'nudge-up' : 'nudge-down';
          pnlBox.classList.remove('nudge-up','nudge-down');
          void pnlBox.offsetWidth;
          pnlBox.classList.add(going);
          setTimeout(function() {{ pnlBox.classList.remove('nudge-up','nudge-down'); }}, 700);
        }}
      }}
      // ── Total P&L odometer — update on every NAV poll ────────────────────
      (function() {{
        var _el  = document.getElementById('total-pnl-val');
        var _sub = document.getElementById('total-pnl-sub');
        if (!_el) return;
        var _prev = parseFloat(_el.getAttribute('data-raw') || '0');
        if (Math.abs(_prev - pnl) < 0.01) return; // no change
        _el.setAttribute('data-raw', pnl);
        var _col = pnl >= 0 ? '#00ff9d' : '#ff3366';
        _el.style.color = _col;
        if (_sub) _sub.style.color = _col;
        var _t0 = performance.now(), _dur = 500, _from = _prev;
        function _roll(now) {{
          var p = Math.min(1, (now - _t0) / _dur);
          var v = _from + (pnl - _from) * (1 - Math.pow(1-p, 3));
          var s = v >= 0 ? '+' : '−';
          _el.textContent = s + '$' + Math.abs(Math.round(v)).toLocaleString('en-US');
          if (_sub) {{
            var pct = (v / 100000) * 100;
            _sub.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '% since $100K start';
          }}
          if (p < 1) requestAnimationFrame(_roll);
        }}
        requestAnimationFrame(_roll);
      }})();

      // ── Recovery meter / profit display ──────────────────────────────────
      var subRoot = document.getElementById('pnl-sub-root');
      if (subRoot) {{
        if (pnl < 0) {{
          var deficit = Math.abs(Math.round(pnl));
          // Track worst deficit for bar scale
          if (!window._worstDeficit || deficit > window._worstDeficit) {{
            window._worstDeficit = deficit;
          }}
          // Compute recovery rate from nav history
          var ratePerMin = null;
          if (window._navHistory && window._navHistory.length >= 2) {{
            var nh = window._navHistory;
            var newest = nh[0], oldest = nh[nh.length - 1];
            var dMin = (newest.ts - oldest.ts) / 60000;
            if (dMin > 0.5) ratePerMin = (newest.nav - oldest.nav) / dMin;
          }}
          var barPct = window._worstDeficit > 0
            ? Math.max(0, Math.round((1 - deficit / window._worstDeficit) * 100))
            : 0;
          var rateHtml = '—';
          var etaHtml  = '—';
          if (ratePerMin !== null && ratePerMin > 0) {{
            var rateHr = Math.round(ratePerMin * 60);
            rateHtml = '+$' + rateHr.toLocaleString('en-US') + '/hr';
            var etaMin = Math.round(deficit / ratePerMin);
            etaHtml = etaMin < 60 ? etaMin + 'min' : Math.round(etaMin/60) + 'h';
          }}
          subRoot.innerHTML =
            '<div id="rc-widget">' +
            '<div id="rc-top">' +
            '<span id="rc-label">DEFICIT</span>' +
            '<span id="rc-amount">-$' + deficit.toLocaleString('en-US') + '</span>' +
            '</div>' +
            '<div id="rc-bar-bg"><div id="rc-bar" style="width:' + barPct + '%"></div></div>' +
            '<div id="rc-stats">' +
            '<span id="rc-rate">' + rateHtml + '</span>' +
            '<span id="rc-eta">eta: ' + etaHtml + '</span>' +
            '</div></div>';
        }} else {{
          window._worstDeficit = 0;
          subRoot.innerHTML = '<span style="font-size:8.5px;color:#00ff9d">' + ret + ' since $100K start</span>';
        }}
      }}

      // Projected annual return (rolling pace from portValues)
      var proj = document.getElementById('nv-proj');
      if (proj && portValues.length >= 2) {{
        var n = Math.min(portValues.length, 30);
        var vS = portValues[portValues.length - n], vE = nav;
        var dS = new Date(portDates[portDates.length - n] + 'T00:00:00Z');
        var days = Math.max(1, (Date.now() - dS) / 86400000);
        var dailyR = Math.pow(vE / vS, 1/days) - 1;
        var dec31 = new Date(new Date().getFullYear(), 11, 31);
        var dLeft = Math.max(0, (dec31 - Date.now()) / 86400000);
        var eoy = vE * Math.pow(1 + dailyR, dLeft);
        var gain = eoy - 100000;
        var gainSign = gain >= 0 ? '+' : '-';
        proj.textContent = 'pace: ' + gainSign + '$' + Math.round(Math.abs(gain)).toLocaleString('en-US') + ' by Dec 31';
        proj.style.color = gain >= 0 ? '#00ff9d' : '#ff3366';
      }}

      // legend-strip PORTFOLIO
      var legVals = document.querySelectorAll('.leg-val');
      var legRets = document.querySelectorAll('.leg-ret');
      if (legVals[0]) legVals[0].textContent = _fmt(nav);
      if (legRets[0]) {{ legRets[0].textContent = ret; legRets[0].style.color = col; }}

      // Push to _navHistory and redraw cleanly — no extendTraces, no type mixing
      var isoTs = ts || new Date().toISOString();
      window._lastKnownTs = isoTs;
      if (!window._navHistory) window._navHistory = [];
      // Deduplicate: don't push same timestamp twice
      var _last = window._navHistory[window._navHistory.length - 1];
      if (!_last || _last.x !== isoTs) {{
        window._navHistory.push({{ x: isoTs, y: nav }});
      }} else {{
        _last.y = nav; // update in place if same tick
      }}
      // Trim to 30 min — matches the visible window, prevents ancient points making laser beams
      var _cutoff = new Date(Date.now() - 30 * 60 * 1000).toISOString();
      while (window._navHistory.length > 0 && window._navHistory[0].x < _cutoff) {{
        window._navHistory.shift();
      }}
      if (window._drawNavCanvas) window._drawNavCanvas();
      _updateEndpointDot(nav, isoTs);
      _updateAthShape(nav, isoTs);
    }}

    // Redraw portfolio trace (index 6) from nav_snapshots DB data + live point.
    // No axis relayout — chart stays wherever the user left it.
    var _navTraceInited = false;
    function _redrawNavTraces() {{
      var _gd = document.getElementById('chart');
      // Retry until Plotly is ready — don't bail out permanently
      if (!_gd || !_gd.data) {{ setTimeout(_redrawNavTraces, 400); return; }}
      var dbPts = window._navDbPts || [];
      var _xs = dbPts.map(function(p) {{ return p.t; }});
      var _ys = dbPts.map(function(p) {{ return p.v; }});
      if (window._lastKnownNav && window._lastKnownTs) {{
        _xs.push(window._lastKnownTs);
        _ys.push(window._lastKnownNav);
      }}
      if (!_xs.length) return;
      // Find the portfolio trace by name rather than hardcoded index
      var traceIdx = 6;
      for (var _ti = 0; _ti < _gd.data.length; _ti++) {{
        if (_gd.data[_ti].name === 'PORTFOLIO') {{ traceIdx = _ti; break; }}
      }}
      // restyle returns a Promise — chain relayout so axes fit AFTER data lands
      Plotly.restyle(_gd, {{ x: [_xs], y: [_ys] }}, [traceIdx]).then(function() {{
        if (!_navTraceInited) {{
          _navTraceInited = true;
          Plotly.relayout(_gd, {{ 'xaxis.autorange': true, 'yaxis.autorange': true }});
        }}
      }});
    }}
    window._redrawNavTraces = _redrawNavTraces;
    _redrawNavTraces();
    setInterval(_redrawNavTraces, 5000);

    function _pollNav() {{
      var url = SUPA_URL + '/rest/v1/portfolio_snapshots'
        + '?select=total_value,recorded_at,strategy'
        + '&strategy=eq.crypto_momentum'
        + '&order=recorded_at.desc&limit=1';
      fetch(url, {{
        headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }}
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        if (!Array.isArray(rows) || !rows.length) return;
        var row = rows[0];
        if (row.recorded_at === _lastNavTs) return; // no change
        _lastNavTs = row.recorded_at;
        // Don't overwrite live crypto price feed with a stale DB snapshot
        if (window._lastLivePriceMs && (Date.now() - window._lastLivePriceMs) < 10000) return;
        _updateNavDisplays(row.total_value, row.recorded_at);
      }})
      .catch(function() {{}});
    }}

    // Seed _navHistory: once the first NAV is known, push a synthetic baseline point
    // at the left edge of the 20-min window so the line appears immediately.
    // crypto_momentum has no portfolio_snapshots rows, so we don't query that table.
    window._navHistory = [];
    window._navBaselineSeeded = false;
    window._seedNavBaseline = function(nav) {{
      if (window._navBaselineSeeded || !nav) return;
      window._navBaselineSeeded = true;
      // Plant baseline 19.5 minutes back — maps to x ≈ 1.25% from left edge
      var baselineTs = new Date(Date.now() - 19.5*60*1000).toISOString();
      window._navHistory.push({{ x: baselineTs, y: nav }});
      if (window._drawNavCanvas) window._drawNavCanvas();
    }};

    setTimeout(function() {{
      _pollNav();
      setInterval(_pollNav, 5000);
    }}, 4000);

    // Heartbeat: stamp current NAV every 5s — fires immediately after first pollNav
    function _navHeartbeat() {{
      var nav = window._lastKnownNav;
      if (!nav) return;
      if (!window._navHistory) window._navHistory = [];
      var isoNow = new Date().toISOString();
      var last = window._navHistory[window._navHistory.length - 1];
      if (last && (new Date(isoNow) - new Date(last.x)) < 4000) return; // dedup <4s
      window._navHistory.push({{ x: isoNow, y: nav }});
      var cutoff = new Date(Date.now() - 60*1000).toISOString();
      while (window._navHistory.length > 0 && window._navHistory[0].x < cutoff) window._navHistory.shift();
      if (window._drawNavCanvas) window._drawNavCanvas();
    }}
    window._navHeartbeat = _navHeartbeat;
    // Fire first heartbeat quickly so baseline seeds as soon as nav is known
    setTimeout(function() {{ _navHeartbeat(); setInterval(_navHeartbeat, 5000); }}, 1500);

    // ── Live positions poller — DOM-diffing with enter/exit animations ───────
    var _TICKER_COLS = ['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
    function _symCol(sym) {{
      var s = sym.replace('/USD','').replace('USD','');
      if (window._TICKER_OVR && window._TICKER_OVR[s]) return window._TICKER_OVR[s];
      var h = 0;
      for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffff;
      return _TICKER_COLS[h % _TICKER_COLS.length];
    }}

    var _cryptoCardEls = {{}}; // symbol → DOM element
    window._cryptoPositionsMap = {{}}; // exposed for dynamic queue
    window._cryptoPairCount    = 15;

    // Scan sweep + popup — expose globally so feed poller can call it
    window._triggerScan = function(symbols) {{
      // symbols: optional array e.g. ['ETH/USD','SOL/USD',...]
      // Panel-level sweep — the whole positions panel gets a scan beam
      var panel = document.getElementById('pos-panel');
      if (panel) {{
        panel.classList.remove('panel-scanning');
        void panel.offsetWidth;
        panel.classList.add('panel-scanning');
        setTimeout(function() {{ panel.classList.remove('panel-scanning'); }}, 1000);
      }}
      // Canvas tiles have built-in scanline effect; legacy DOM equity cards also swept
      Object.values(_equityCardEls).forEach(function(el, i) {{
        setTimeout(function() {{
          el.classList.remove('pos-card-scanning');
          void el.offsetWidth;
          el.classList.add('pos-card-scanning');
          setTimeout(function() {{ el.classList.remove('pos-card-scanning'); }}, 800);
        }}, i * 90);
      }});

    }};

    // ── Video-game card exit ────────────────────────────────────────────────────
    // ── Arcade exit: 3-phase sequence ─────────────────────────────────────────
    // Phase 1 (0–320ms):  Target-lock overlay appears on tile
    // Phase 2 (320–580ms): Hit-flash damage blinks (3 pulses)
    // Phase 3 (580–):     Tile crushes to scanline + P&L ghost spawns left of column
    function _spawnParticles(cx, cy, col) {{
      var N = 10;  // reduced for perf; 8-bit pixel burst feel
      for (var i = 0; i < N; i++) {{
        var angle = (Math.PI * 2 / N) * i;
        var dist  = 24 + Math.floor(Math.random() * 4) * 12;  // quantized distances
        var size  = 2 + (Math.random() > .5 ? 2 : 0);  // 2px or 4px — 8-bit pixels
        var dur   = (.28 + Math.floor(Math.random() * 3) * .08).toFixed(2) + 's';
        var p = document.createElement('div');
        p.className = 'pnl-particle';
        p.style.cssText = [
          'width:' + size + 'px', 'height:' + size + 'px',
          'background:' + col,  // no box-shadow for perf
          'left:' + (cx - size/2) + 'px', 'top:' + (cy - size/2) + 'px',
          '--px:' + Math.round(Math.cos(angle) * dist) + 'px',
          '--py:' + Math.round(Math.sin(angle) * dist) + 'px',
          '--dur:' + dur, 'opacity:1'
        ].join(';');
        document.body.appendChild(p);
        setTimeout(function(pp) {{ if (pp.parentNode) pp.parentNode.removeChild(pp); }}, 700, p);
      }}
    }}

    function _spawnPnlGhost(r, pnl, sym, exitPrice) {{
      var hasPnl = (pnl !== null && pnl !== undefined);
      var isWin  = hasPnl ? pnl >= 0 : true;
      var col    = isWin ? '#00ff9d' : '#ff3366';

      // Position: to the LEFT of the tile column, vertically centered on the card
      var ghostW = 88;
      var gx = r.left - ghostW - 10;
      var gy = r.top + r.height / 2 - 30;

      var g = document.createElement('div');
      g.className = 'pnl-ghost';
      g.style.color = col;
      g.style.left  = gx + 'px';
      g.style.top   = gy + 'px';
      g.style.width = ghostW + 'px';

      var valEl = document.createElement('div');
      valEl.className = 'pg-val';
      if (hasPnl) {{
        var absPnl = Math.abs(pnl);
        valEl.textContent = absPnl >= 1000
          ? (pnl >= 0 ? '+' : '-') + '$' + (absPnl / 1000).toFixed(1) + 'K'
          : (pnl >= 0 ? '+' : '-') + '$' + absPnl.toFixed(2);
      }} else {{
        valEl.textContent = 'CLOSED';
      }}
      g.appendChild(valEl);
      if (exitPrice) {{
        var priceEl = document.createElement('div');
        priceEl.className = 'pg-price';
        var ep = parseFloat(exitPrice.toString().replace(/,/g,''));
        priceEl.textContent = '@ $' + (ep > 1 ? ep.toLocaleString('en-US',{{maximumFractionDigits:2}}) : ep.toFixed(4));
        g.appendChild(priceEl);
      }}
      document.body.appendChild(g);
      setTimeout(function() {{ if (g.parentNode) g.parentNode.removeChild(g); }}, 2800);
    }}

    // ── Equity positions map — server-rendered, for satellite orbs ──────────────
    window._equityPositionsMap = {_eq_pos_js};
    // ── Equity card map — built from SSR DOM on load ────────────────────────────
    var _equityCardEls = {{}};
    function _buildEquityMap() {{
      document.querySelectorAll('#pos-equity-section .pos-card[data-sym]').forEach(function(el) {{
        _equityCardEls[el.getAttribute('data-sym')] = el;
      }});
    }}
    setTimeout(_buildEquityMap, 500);

    // ── Batch ghost collapse — debounced, all exits finish before any reflow ──
    var _ghostsToCollapse = [];
    var _ghostCollapseTimer = null;
    function _queueGhostCollapse(ghost) {{
      _ghostsToCollapse.push(ghost);
      clearTimeout(_ghostCollapseTimer);
      // 1.8s after the LAST exit trigger before any tile reflows
      // 3.2s after LAST exit: covers 2.7s P&L linger + 0.5s arcade exit animation
      _ghostCollapseTimer = setTimeout(function() {{
        var batch = _ghostsToCollapse.splice(0);

        // Step 1: glitch-snap any legacy DOM equity tiles (canvas tiles self-reflow)
        var liveTiles = document.querySelectorAll('#pos-equity-section .pos-card');
        liveTiles.forEach(function(card) {{
          card.classList.remove('pos-card-shuffle-land');
          void card.offsetWidth;  // force reflow so animation restarts
          card.classList.add('pos-card-shuffle-land');
          setTimeout(function() {{ card.classList.remove('pos-card-shuffle-land'); }}, 250);
        }});

        // Step 2: collapse all ghosts simultaneously in quantized steps
        batch.forEach(function(g) {{
          if (!g.parentNode) return;
          var h = g.getBoundingClientRect().height;
          g.style.height = h + 'px';
          requestAnimationFrame(function() {{
            g.classList.add('pos-card-ghost-collapsing');
          }});
        }});

        // Step 3: remove ghost DOM nodes after collapse finishes (7 steps × ~46ms = ~320ms)
        setTimeout(function() {{
          batch.forEach(function(g) {{ if (g.parentNode) g.parentNode.removeChild(g); }});
          _updateOverlayWidth();
        }}, 360);
      }}, 3200);
    }}

    window._triggerCardExit = function(fullSym, reason, pnl, exitPrice) {{
      // All tiles are now on the canvas engine
      var sym1 = fullSym;
      var sym2 = fullSym + '/USD';
      if ((window._etBySym||{{}})[sym1]) {{ window._etExit(sym1, pnl, exitPrice); return; }}
      if ((window._etBySym||{{}})[sym2]) {{ window._etExit(sym2, pnl, exitPrice); return; }}

      // Fallback: legacy DOM path (should not be reached)
      var el = _cryptoCardEls[fullSym] || _cryptoCardEls[fullSym + '/USD'];
      if (!el) return;
      if (_cryptoCardEls[fullSym]) delete _cryptoCardEls[fullSym];
      else if (_cryptoCardEls[fullSym + '/USD']) delete _cryptoCardEls[fullSym + '/USD'];
      var _exitSym = _cryptoCardEls[fullSym + '/USD'] ? fullSym + '/USD' : fullSym;
      if (_satAngles[_exitSym] !== undefined) {{
        _satExiting[_exitSym] = {{
          angle: _satAngles[_exitSym], orbitR: 32, age: 0,
          sr: pnl >= 0 ? 0 : 255, sg: pnl >= 0 ? 255 : 51, sb: pnl >= 0 ? 157 : 102
        }};
        delete _satAngles[_exitSym];
        delete (window._equityPositionsMap || {{}})[_exitSym];
      }}
      el.classList.remove('pos-card-active');
      var col = (pnl !== null && pnl !== undefined) ? (pnl >= 0 ? '#00ff9d' : '#ff3366') : '#fff';

      // ── Snapshot position, swap with ghost placeholder ─────────────────
      var r = el.getBoundingClientRect();
      var ghost = document.createElement('div');
      ghost.className = 'pos-card-ghost-space';
      ghost.style.height = r.height + 'px';
      // In-place P&L result: revealed after destroy animation fires
      var _symClean = fullSym ? fullSym.replace('/USD','').replace('USD','') : '';
      if (pnl !== null && pnl !== undefined) {{
        var _absPnl = Math.abs(pnl);
        var _sign = pnl >= 0 ? '+' : '−';
        var _pnlStr = _sign + '$' + (_absPnl >= 1000 ? (_absPnl/1000).toFixed(1)+'k' : _absPnl.toFixed(2));
        ghost.innerHTML = '<span class="gc-sym">' + _symClean + '</span>'
          + '<span class="gc-pnl" style="color:' + col + '">' + _pnlStr + '</span>';
      }}
      if (el.parentNode) el.parentNode.insertBefore(ghost, el);

      // Detach card and re-pin at exact viewport position — unrestricted by pos-left overflow
      if (el.parentNode) el.parentNode.removeChild(el);
      el.style.cssText += [
        ';position:fixed',
        'top:' + r.top + 'px',
        'left:' + r.left + 'px',
        'width:' + r.width + 'px',
        'height:' + r.height + 'px',
        'z-index:9990',
        'margin:0',
        'box-sizing:border-box',
        'overflow:visible',
        // Restore visual appearance lost when leaving #pos-left scope
        'background:rgba(0,0,10,.92)',
        'border:1px solid rgba(255,255,255,.07)'
      ].join(';');
      document.body.appendChild(el);

      // ── Phase 1: Canvas bitcrusher (0–500ms) ─────────────────────────────
      var bc = document.createElement('canvas');
      bc.width  = Math.round(r.width);
      bc.height = Math.round(r.height);
      bc.style.cssText = 'position:fixed;top:' + r.top + 'px;left:' + r.left + 'px;'
        + 'width:' + r.width + 'px;height:' + r.height + 'px;z-index:9991;pointer-events:none;';
      document.body.appendChild(bc);
      var bCtx = bc.getContext('2d');
      // Snapshot the card into the canvas
      var crushStart = performance.now();
      var crushDur = 500;
      (function _crushFrame(now) {{
        var age = now - crushStart;
        if (age >= crushDur) {{
          if (bc.parentNode) bc.parentNode.removeChild(bc);
          if (el.parentNode) el.parentNode.removeChild(el);
          ghost.classList.add('ghost-pnl-showing');
          ghost.style.opacity = '1';
          return;
        }}
        var crushT = age / crushDur;
        var bSz = Math.max(2, Math.round(2 + crushT * crushT * 12));
        // On first frame, snapshot el appearance via fillRect mimic
        bCtx.clearRect(0, 0, bc.width, bc.height);
        // Draw tile background
        bCtx.fillStyle = 'rgba(0,0,8,0.92)';
        bCtx.fillRect(0, 0, bc.width, bc.height);
        // Left accent stripe
        bCtx.fillStyle = col;
        bCtx.fillRect(0, 0, 3, bc.height);
        // Eat blocks
        for (var by = 0; by < bc.height; by += bSz) {{
          for (var bx = 0; bx < bc.width; bx += bSz) {{
            if (Math.random() < crushT * 1.5) bCtx.clearRect(bx, by, bSz, bSz);
          }}
        }}
        requestAnimationFrame(_crushFrame);
      }})(crushStart);
      el.style.opacity = '0'; // hide original immediately; canvas takes over

      // ── Phase 2: Ghost P&L sticks for 2.5s, then arcade-glitch out ────
      setTimeout(function() {{
        ghost.classList.add('ghost-pnl-exiting');
      }}, 3200);

      // Queue ghost placeholder for batch collapse after exit animation (~400ms after phase 3)
      _queueGhostCollapse(ghost);
    }};

    var _CARD_W = 148; // crypto column width
    var _EQ_W   = 130; // equity column width
    var _EQ_H   = 58;  // tile height px — content ends at y+49 (VU bar), 9px margin

    // ═══════════════════════════════════════════════════════════════════════════
    // CANVAS EQUITY TILE ENGINE
    // All equity holdings rendered on a single canvas — zero DOM, zero layout cost.
    // _ET[] is the single source of truth; draw loop paints it 30fps.
    // ═══════════════════════════════════════════════════════════════════════════
    window._ET = [];          // tile state objects — on window so all scripts share reference
    window._etBySym = {{}};   // sym → tile for O(1) lookup
    var _ET     = window._ET;
    var _etBySym = window._etBySym;

    var _HEADING_H = 16; // px reserved at top of canvas for strategy group labels

    function _etLayout() {{
      var stratBar = document.getElementById('strat-bar');
      var sbH = stratBar ? stratBar.offsetHeight : 46;
      var availH = Math.floor((window.innerHeight - sbH - 4 - _HEADING_H) * 0.67);
      // Cache key: tile count + active tile ids+phases + window height
      var _lk = _ET.length + '|' + window.innerHeight + '|' +
        _ET.map(function(t){{return t.sym+t.phase;}}).join(',');
      if (_etCachedLayout && _lk === _etLayoutKey) return _etCachedLayout;
      _etLayoutKey = _lk;
      var perCol = Math.max(1, Math.floor(availH / _EQ_H));
      // Stable sort: within each group, sort by enteredAt so positions don't
      // shuffle when tiles enter/exit (newest at top, oldest at bottom)
      var crypto = _ET.filter(function(t) {{ return t.phase !== 'done' && t.isCrypto; }})
                      .sort(function(a,b) {{ return (b.enteredAt||0) - (a.enteredAt||0); }});
      var equity = _ET.filter(function(t) {{ return t.phase !== 'done' && !t.isCrypto; }})
                      .sort(function(a,b) {{ return (b.enteredAt||0) - (a.enteredAt||0); }});
      var cryptoCols = Math.max(1, Math.ceil(crypto.length / perCol));
      var equityCols = equity.length > 0 ? Math.max(1, Math.ceil(equity.length / perCol)) : 0;
      var totalCols  = cryptoCols + equityCols;
      _etCachedLayout = {{ perCol: perCol, totalCols: totalCols, cryptoCols: cryptoCols, equityCols: equityCols,
                crypto: crypto, equity: equity, availH: availH,
                live: crypto.concat(equity) }};
      return _etCachedLayout;
    }}

    function _etTilePos(t, layout) {{
      // Equity (NYSE): rightmost columns (col 0 = far right)
      // Crypto: columns just left of equity (separated by 2px gap)
      if (!t.isCrypto) {{
        var ei  = layout.equity.indexOf(t);
        var col = Math.floor(ei / layout.perCol);
        var row = ei % layout.perCol;
        var x   = (layout.totalCols - 1 - col) * _EQ_W;
        return {{ x: x, y: row * _EQ_H }};
      }} else {{
        var ci   = layout.crypto.indexOf(t);
        var col2 = Math.floor(ci / layout.perCol);
        var row2 = ci % layout.perCol;
        // Crypto columns sit to the LEFT of equity columns
        var x2   = (layout.cryptoCols - 1 - col2) * _EQ_W;
        return {{ x: x2, y: row2 * _EQ_H }};
      }}
    }}

    var _etCanvas = null, _etCtx = null;
    var _etLastTileCount = -1; // tracks tile count for overlay-width dirty check
    var _etLastDraw = 0, _etDirty = true;
    var _etCachedLayout = null, _etLayoutKey = '';
    var _etScanT = 0;  // scanline phase

    function _etInitCanvas() {{
      _etCanvas = document.getElementById('eq-tiles-canvas');
      if (!_etCanvas) return;
      _etCtx = _etCanvas.getContext('2d');
      _etCanvas.style.position = 'relative';
      _etCanvas.style.zIndex = '2';
    }}

    var _etDpr = window.devicePixelRatio || 1;
    function _etResize() {{
      if (!_etCanvas) return;
      var layout = _etLayout();
      var cw = _EQ_W * layout.totalCols;
      var ch = layout.availH;
      var pw = Math.round(cw * _etDpr);
      var ph = Math.round(ch * _etDpr);
      if (_etCanvas.width !== pw || _etCanvas.height !== ph) {{
        _etCanvas.width  = pw;
        _etCanvas.height = ph;
        _etCanvas.style.width  = cw + 'px';
        _etCanvas.style.height = ch + 'px';
        _etCtx.setTransform(_etDpr, 0, 0, _etDpr, 0, 0);
        _etDirty = true;
      }}
    }}

    function _etDraw(ts) {{
      if (!_etCtx || !_etCanvas) return;
      _etScanT = ts;

      var layout = _etLayout();
      _etResize();
      var ctx = _etCtx;
      ctx.clearRect(0, 0, _etCanvas.width, _etCanvas.height);

      var now = Date.now();
      var lerpK = 0.03; // lerp speed per frame (~30fps → ~10s to converge; slow = more cinematic)

      // Render order: ghosts first so entering/live tiles paint on top of them
      var _allTiles = layout.crypto.concat(layout.equity);
      var allLive = _allTiles.filter(function(t) {{ return t.phase === 'bit-crush'; }})
                   .concat(_allTiles.filter(function(t) {{ return t.phase !== 'bit-crush'; }}));
      for (var i = 0; i < allLive.length; i++) {{
        var t = allLive[i];
        var pos = _etTilePos(t, layout);
        var x = pos.x, y = pos.y;
        var age = now - t.phaseStart;

        // Lerp display values toward actual values (smooths batch-update flashes)
        if (t._dVal   === undefined) t._dVal   = t.val;
        if (t._dPnl   === undefined) t._dPnl   = t.pnl;
        if (t._dPnlPct=== undefined) t._dPnlPct= t.pnlPct;
        t._dVal    += (t.val    - t._dVal)    * lerpK;
        t._dPnl    += (t.pnl   - t._dPnl)    * lerpK;
        t._dPnlPct += (t.pnlPct- t._dPnlPct) * lerpK;

        if (t.phase === 'entering') {{
          // 8-bit fly-in from canvas center (120ms) + corner sparks (80ms)
          var _flyDur = 120, _sparkDur = 80;
          if (age < _flyDur) {{
            // Cubic-out ease so it snaps in fast then sticks the landing
            var _flyT = age / _flyDur;
            var _flyE = 1 - Math.pow(1 - _flyT, 3);
            // Origin: canvas center minus half tile size
            var _ox = Math.round((_etCanvas.width  * 0.5 - _EQ_W * 0.5) / 8) * 8;
            var _oy = Math.round((_etCanvas.height * 0.5 - _EQ_H * 0.5) / 8) * 8;
            // Quantize current position to 4px grid for 8-bit chunky feel
            var _fx = Math.round((_ox + (x - _ox) * _flyE) / 4) * 4;
            var _fy = Math.round((_oy + (y - _oy) * _flyE) / 4) * 4;
            // Scale from 0.35 at origin to 1.0 at target
            var _fsc = 0.35 + _flyE * 0.65;
            ctx.save();
            ctx.translate(_fx + _EQ_W * 0.5, _fy + _EQ_H * 0.5);
            ctx.scale(_fsc, _fsc);
            ctx.translate(-_EQ_W * 0.5, -_EQ_H * 0.5);
            _etPaintTile(ctx, t, 0, 0, ts);
            ctx.restore();
          }} else {{
            // Tile landed — white corner sparks fade over 80ms
            _etPaintTile(ctx, t, x, y, ts);
            var sparkA = Math.max(0, 1 - (age - _flyDur) / _sparkDur);
            if (sparkA > 0) {{
              ctx.fillStyle = 'rgba(255,255,255,' + sparkA + ')';
              var sp = Math.round(6 * sparkA);
              ctx.fillRect(x,         y,         2, sp); ctx.fillRect(x,         y,         sp, 2);
              ctx.fillRect(x+_EQ_W-2, y,         2, sp); ctx.fillRect(x+_EQ_W-sp,y,         sp, 2);
              ctx.fillRect(x,         y+_EQ_H-sp,2, sp); ctx.fillRect(x,         y+_EQ_H-2, sp, 2);
              ctx.fillRect(x+_EQ_W-2, y+_EQ_H-sp,2, sp); ctx.fillRect(x+_EQ_W-sp,y+_EQ_H-2,sp, 2);
            }}
          }}
          if (age > _flyDur + _sparkDur) {{ t.phase = 'live'; }}

        }} else if (t.phase === 'live') {{
          _etPaintTile(ctx, t, x, y, ts);

        }} else if (t.phase === 'bit-crush') {{
          // Phase 1 (0–500ms): pixel decay → clearRect blocks eat tile to transparent
          // Phase 2 (500–2300ms): P&L ghost in Press Start 2P lingers in cleared space
          var crushDur = 500, ghostDur = 2800;
          if (age < crushDur) {{
            var crushT = age / crushDur; // 0→1
            _etPaintTile(ctx, t, x, y, ts);
            // Quantize: block size grows from 2px → 14px
            var bSz = Math.max(2, Math.round(2 + crushT * crushT * 12));
            for (var by = 0; by < _EQ_H; by += bSz) {{
              for (var bx2 = 0; bx2 < _EQ_W; bx2 += bSz) {{
                if (Math.random() < crushT * 1.5) {{
                  ctx.clearRect(x + bx2, y + by, bSz, bSz);
                }}
              }}
            }}
          }} else {{
            // Tile space cleared — ghost: sym name + P&L in Press Start 2P
            var ghostT = Math.min(1, (age - crushDur) / ghostDur);
            // Fast in (3%), short hold (until 25%), long fade to true zero (25%→100%)
            var ghostA = ghostT < 0.03 ? ghostT / 0.03
                       : ghostT < 0.25 ? 1
                       : Math.max(0, 1 - (ghostT - 0.25) / 0.75);
            if (ghostA > 0.01) {{
              var ec = t.exitPnl >= 0 ? '#00ff9d' : '#ff3366';
              var ep = Math.abs(t.exitPnl);
              var es = (t.exitPnl >= 0 ? '+$' : '-$') + (ep >= 1000 ? (ep/1000).toFixed(1)+'k' : ep.toFixed(2));
              var cx2 = x + _EQ_W/2, cy2 = y + _EQ_H/2;
              ctx.save();
              ctx.globalAlpha = ghostA;
              // Ticker name above
              ctx.shadowColor = 'rgba(255,255,255,0.4)'; ctx.shadowBlur = 6;
              ctx.fillStyle = 'rgba(255,255,255,0.7)';
              ctx.font = '7px Consolas,monospace';
              ctx.textAlign = 'center';
              ctx.fillText(t.sym, cx2, cy2 - 8);
              // P&L value
              ctx.shadowColor = ec; ctx.shadowBlur = 16;
              ctx.fillStyle = ec;
              ctx.font = '8px "Press Start 2P",monospace';
              ctx.fillText(es, cx2, cy2 + 6);
              ctx.textAlign = 'left';
              ctx.restore();
            }}
            if (ghostT >= 1) {{ t.phase = 'done'; _etDirty = true; }}
          }}
        }}
        // 'done' tiles excluded by live filter
      }}

      // Draw equity/crypto separator if both types present
      if (layout.equityCols > 0 && layout.cryptoCols > 0) {{
        var sepX = layout.equityCols * _EQ_W;
        ctx.fillStyle = 'rgba(255,255,255,0.06)';
        ctx.fillRect(sepX, 0, 2, layout.availH);
      }}

      // Only update overlay width when tile count changes — not every frame
      var _nowCount = _ET.filter(function(t){{return t.phase!=='done';}}).length;
      if (_nowCount !== _etLastTileCount) {{
        _etLastTileCount = _nowCount;
        _updateOverlayWidth();
      }}
    }}

    // Strategy badge map — glyph + glow color per strategy key
    var _TILE_BADGES = {{
      'momentum':   {{ g:'▲▲', c:'#00e5ff' }},
      'crypto':     {{ g:'◈',  c:'#e040fb' }},
      'user':       {{ g:'◎',  c:'#00ff9d' }},
      'daytrader':  {{ g:'⊕',  c:'#b2ff59' }},
      'reversion':  {{ g:'⇌',  c:'#ff9900' }},
      'sentiment':  {{ g:'◉',  c:'#ff4081' }},
      'volatility': {{ g:'⚡', c:'#ff6b35' }},
      'factor':     {{ g:'✦',  c:'#ffd740' }},
      'macro':      {{ g:'≋',  c:'#00bcd4' }},
      'ensemble':   {{ g:'❋',  c:'#ffffff' }},
    }};

    var _SCRAMBLE_CHARS = '0123456789';
    function _scrambleDigits(str) {{
      var out = '';
      for (var si = 0; si < str.length; si++) {{
        var c = str[si];
        out += (c >= '0' && c <= '9') ? _SCRAMBLE_CHARS[Math.floor(Math.random()*10)] : c;
      }}
      return out;
    }}

    function _etPaintTile(ctx, t, x, y, ts) {{
      var W = _EQ_W, H = _EQ_H;
      var now = Date.now(); // epoch ms — use for hold timer, NOT rAF ts

      // Hard-reset shadow so exit-ghost glow doesn't leak into live tile text
      ctx.shadowBlur = 0; ctx.shadowColor = 'transparent';

      // Background — transparent
      // Left accent stripe (2px)
      ctx.fillStyle = t.col;
      ctx.fillRect(x, y, 2, H);

      // Bottom separator
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fillRect(x, y + H - 1, W, 1);

      // ── Strategy badge — glowing glyph left of ticker ──
      var _badge = _TILE_BADGES[t.strategy || (t.isCrypto ? 'crypto' : 'momentum')];
      var _badgeOff = 0;
      if (_badge) {{
        ctx.save();
        ctx.font = '7px Consolas,monospace';
        ctx.textAlign = 'left';
        ctx.fillStyle   = _badge.c;
        ctx.globalAlpha = 0.85;
        ctx.fillText(_badge.g, x + 4, y + 14);
        ctx.restore();
        _badgeOff = 14;
      }}
      var lx = x + 4 + _badgeOff;

      // Lerped display values
      var dVal    = t._dVal    !== undefined ? t._dVal    : (t.val    || 0);
      var dPnl    = t._dPnl    !== undefined ? t._dPnl    : (t.pnl    || 0);
      var dPnlPct = t._dPnlPct !== undefined ? t._dPnlPct : (t.pnlPct || 0);
      if (Math.abs(dPnl)    < 0.005) dPnl    = 0;
      if (Math.abs(dPnlPct) < 0.005) dPnlPct = 0;

      var _F1 = '700 16px VT323,monospace'; // ticker sym (bold)
      var _FV = '400 16px VT323,monospace'; // right-side value (not bold)
      var _F2 = '400 14px VT323,monospace'; // entry, pnl, timer

      // ── ROW 1 left: SYM ──
      ctx.font = _F1;
      ctx.fillStyle = t.col;
      ctx.textAlign = 'left';
      ctx.fillText(t.sym, lx, y + 15);

      // ── ROW 1 right: value ──
      if (dVal > 0.5) {{
        if (dPnl > 0.01)       t._valDir = 1;
        else if (dPnl < -0.01) t._valDir = -1;
        var dir = t._valDir || 0;
        var mag = Math.min(Math.abs(dPnlPct) / 5, 1);
        var valCol;
        if (dir > 0)      valCol = 'hsl(140,' + Math.round(mag*75) + '%,' + Math.round(88 - mag*38) + '%)';
        else if (dir < 0) valCol = 'hsl(350,' + Math.round(mag*75) + '%,' + Math.round(88 - mag*44) + '%)';
        else               valCol = '#ffffff';
        var flashAge = t._flashStart ? (ts - t._flashStart) : 9999;
        var isFlashing = flashAge < 180;
        var valStr = '$' + Math.round(dVal).toLocaleString('en-US');
        ctx.font = _FV;
        ctx.fillStyle = isFlashing ? (t._flashDir > 0 ? '#00ff9d' : '#ff3366') : valCol;
        ctx.textAlign = 'right';
        ctx.fillText(isFlashing ? _scrambleDigits(valStr) : valStr, x + W - 5, y + 15);
        ctx.textAlign = 'left';
        if (t._valFlash) {{ t._flashStart = ts; t._flashDir = t._valFlash; t._valFlash = 0; }}
      }}

      // ── ROW 2 left: entry price ──
      if (t.entry > 0) {{
        var entryStr = '@$' + (t.entry < 1 ? t.entry.toFixed(4) : t.entry < 100 ? t.entry.toFixed(2) : Math.round(t.entry).toLocaleString('en-US'));
        ctx.font = _F2;
        ctx.fillStyle = t.col;
        ctx.fillText(entryStr, lx, y + 28);
      }}

      // ── ROW 2 right: P&L with scale-pulse ──
      if (Math.abs(dPnl) >= 0.001) t._lastPnl = dPnl;
      var showPnl = t._lastPnl !== undefined ? t._lastPnl : dPnl;
      if (Math.abs(showPnl) >= 0.001) {{
        var pSign = showPnl >= 0 ? '+' : '-';
        var absPnl = Math.abs(showPnl);
        var pnlDisp = pSign + '$' + (absPnl >= 1000 ? (absPnl/1000).toFixed(1)+'k' : absPnl.toFixed(2));
        var pnlFlashAge = t._flashStart ? (ts - t._flashStart) : 9999;
        var pScale = pnlFlashAge < 260 ? (1 + 0.15 * Math.max(0, 1 - pnlFlashAge/260)) : 1;
        ctx.save();
        if (pScale > 1) {{
          ctx.translate(x + W - 5, y + 28);
          ctx.scale(pScale, pScale);
          ctx.translate(-(x + W - 5), -(y + 28));
        }}
        ctx.font = _F2;
        ctx.fillStyle = showPnl >= 0 ? '#00c87a' : '#e03355';
        ctx.textAlign = 'right';
        ctx.fillText(pnlDisp, x + W - 5, y + 28);
        ctx.textAlign = 'left';
        ctx.restore();
      }}

      // ── ROW 3: hold timer ──
      var holdMs = t.enteredAt ? Math.max(0, now - t.enteredAt) : (t.days||0) * 86400000;
      var holdStr;
      if (holdMs < 60000)         holdStr = Math.floor(holdMs/1000) + 's';
      else if (holdMs < 3600000)  holdStr = Math.floor(holdMs/60000) + 'm';
      else if (holdMs < 86400000) {{ var hH=Math.floor(holdMs/3600000),hM=Math.floor((holdMs%3600000)/60000); holdStr=hH+'h'+(hM?' '+hM+'m':''); }}
      else                        {{ var hD=Math.floor(holdMs/86400000),hHr=Math.floor((holdMs%86400000)/3600000); holdStr=hD+'d'+(hHr?' '+hHr+'h':''); }}
      ctx.font = _F2;
      ctx.fillStyle = 'rgba(255,255,255,0.45)';
      ctx.fillText(holdStr, lx, y + 41);

      // ── VU meter bar + peak hat (y+46) ──
      // Equity: rank-based (rank 1=strong hold→low, rank 5=weak hold→high, EXIT=full)
      // Crypto: P&L% based (loss=low, gain toward 3%=high)
      var vuLevel;
      if (!t.isCrypto) {{
        // Equity — rank drives signal
        if (!t.inSignal && t.inSignal !== undefined) {{
          vuLevel = 1.0;
        }} else {{
          var r = t.rank ? Math.min(t.rank, 5) : 3;
          vuLevel = 0.10 + (r / 5) * 0.72; // rank1→0.24, rank5→0.82
        }}
        // ±5% P&L micro-oscillation
        vuLevel = Math.max(0, Math.min(vuLevel + dPnlPct / 100, 1));
      }} else {{
        // Crypto — stop→target proximity is the sell signal
        var cStop   = t.stop   || 0;
        var cTarget = t.target || 0;
        var cCur    = t.curPrice || t.entry || 0;
        if (cStop > 0 && cTarget > cStop && cCur > 0) {{
          vuLevel = Math.max(0, Math.min((cCur - cStop) / (cTarget - cStop), 1));
        }} else {{
          // Fallback: start at 0, let P&L% drift provide life (no instant baseline)
          vuLevel = Math.max(0, Math.min(dPnlPct / 6, 1));
        }}
      }}

      // Display lerp — bar rises from 0 on spawn, never instantly full
      if (t._dVu === undefined) t._dVu = 0;
      t._dVu += (vuLevel - t._dVu) * 0.012; // ~8s to reach target at 30fps

      // Peak hold tracks _dVu so hat also builds slowly; decays very slowly
      if (t._vuPeak === undefined) {{ t._vuPeak = 0; t._vuPeakTs = ts; }}
      if (t._dVu >= t._vuPeak) {{
        t._vuPeak   = t._dVu;
        t._vuPeakTs = ts;
      }} else {{
        var holdDur = 2000; // 2s hold before decay
        var decayAge = ts - t._vuPeakTs - holdDur;
        if (decayAge > 0) {{
          // very slow fall — ~0.003/s, ~5 min from 1.0 to 0
          t._vuPeak = Math.max(t._dVu, t._vuPeak - decayAge * 0.0001);
          t._vuPeakTs = ts - holdDur;
        }}
      }}

      var xpW = W - 10, xpH = 3, xpX = x + 5, xpY = y + 46;
      ctx.fillStyle = 'rgba(255,255,255,0.09)';
      ctx.fillRect(xpX, xpY, xpW, xpH);
      ctx.fillStyle = 'rgba(255,255,255,0.70)';
      ctx.fillRect(xpX, xpY, Math.round(xpW * t._dVu), xpH);
      var hatX = xpX + Math.round(xpW * t._vuPeak) - 2;
      if (hatX > xpX && hatX + 2 <= xpX + xpW) {{
        ctx.fillStyle = 'rgba(255,255,255,0.95)';
        ctx.fillRect(hatX, xpY - 1, 2, xpH + 2);
      }}
    }}

    var _etInitPhase = true; // suppress entry sound for init seed tiles

    // Add or replace a tile (upsert)
    function _etUpsert(data) {{
      var existing = _etBySym[data.sym];
      if (existing) {{
        // Update live fields only
        existing.val      = data.val      || existing.val;
        existing.pnl      = data.pnl      !== undefined ? data.pnl : existing.pnl;
        existing.pnlPct   = data.pnlPct   !== undefined ? data.pnlPct : existing.pnlPct;
        existing.curPrice = data.curPrice  || existing.curPrice;
        existing.inSignal = data.inSignal  !== undefined ? data.inSignal : existing.inSignal;
        existing.rank     = data.rank      || existing.rank;
        existing.holdText = data.holdText  || existing.holdText;
        // Only accept an enteredAt that is *older* than what we already have —
        // prevents price-poller re-calls from stomping the real DB timestamp with Date.now()
        if (data.enteredAt && (!existing.enteredAt || data.enteredAt < existing.enteredAt)) {{
          existing.enteredAt = data.enteredAt;
        }}
        return existing;
      }}
      var tile = {{
        sym:       data.sym,
        col:       data.col || '#00e5ff',
        val:       data.val || 0,
        pnl:       data.pnl || 0,
        pnlPct:    data.pnlPct || 0,
        entry:     data.entry || 0,
        qty:       data.qty || 0,
        stop:      data.stop || 0,
        target:    data.target || 0,
        curPrice:  data.curPrice || data.entry || 0,
        days:      data.days || 0,
        inSignal:  data.inSignal !== undefined ? data.inSignal : true,
        rank:      data.rank || 0,
        holdText:  data.holdText || '',
        isCrypto:  data.isCrypto || false,
        strategy:  data.strategy || (data.isCrypto ? 'crypto' : 'momentum'),
        direction: data.direction || 'long',
        enteredAt: data.enteredAt || 0,
        exitPnl:   0,
        phase:     'entering',
        phaseStart: Date.now(),
        _valFlash: 0,
      }};
      _ET.push(tile);
      _etBySym[data.sym] = tile;
      _etDirty = true;
      _updateOverlayWidth();
      // Sound fires when tile first appears — skip for page-init seed tiles
      if (!_etInitPhase && window._soundEntry) window._soundEntry();
      return tile;
    }}
    window._etUpsert = _etUpsert;

    // Returns {{ strategy: count }} for all live tiles (used by HUD dropdown)
    window._etStratCounts = function() {{
      var counts = {{}};
      _ET.forEach(function(t) {{
        if (t.phase === 'done') return;
        var s = t.strategy || (t.isCrypto ? 'crypto' : 'momentum');
        counts[s] = (counts[s] || 0) + 1;
      }});
      return counts;
    }};

    // Exit a tile (called by notification handler or poll)
    window._etExit = function(sym, pnl, exitPrice) {{
      var t = _etBySym[sym];
      if (!t || t.phase === 'bit-crush' || t.phase === 'done') return;
      t.exitPnl = (pnl !== null && pnl !== undefined) ? pnl : t.pnl;
      // Sound fires when exit animation starts (on the tile, not the notification)
      if (t.exitPnl >= 0) {{ if (window._soundWin)  window._soundWin();  }}
      else                 {{ if (window._soundLoss) window._soundLoss(); }}
      t.phase = 'bit-crush';
      t.phaseStart = Date.now();
      _etDirty = true;
      // Satellite ejection still uses existing system
      var _exitSym = sym + '/USD';
      if (_satAngles[_exitSym] !== undefined) {{
        var col = t.pnl >= 0 ? '#00ff9d' : '#ff3366';
        _satExiting[_exitSym] = {{ angle:_satAngles[_exitSym], orbitR:32, age:0,
          sr: t.pnl>=0?0:255, sg: t.pnl>=0?255:51, sb: t.pnl>=0?157:102 }};
        delete _satAngles[_exitSym];
      }}
      // Clean up after bit-crush completes (500ms decay + 2800ms ghost + margin)
      setTimeout(function() {{
        delete _etBySym[sym];
        var _rmIdx = _ET.findIndex(function(tile) {{ return tile.sym === sym; }});
        if (_rmIdx !== -1) _ET.splice(_rmIdx, 1);
        _updateOverlayWidth();
      }}, 3500);
    }};

    // Strategy heading data — glyph, color, label per key
    var _HDR_BADGES = {{
      momentum:  {{ g:'▲▲', c:'#00e5ff', n:'MOMENTUM'  }},
      crypto:    {{ g:'◈',  c:'#e040fb', n:'CRYPTO'    }},
      user:      {{ g:'◎',  c:'#00ff9d', n:'MANUAL'    }},
      daytrader: {{ g:'⊕',  c:'#b2ff59', n:'DAYTRADER' }},
      reversion: {{ g:'⇌',  c:'#ff9900', n:'MEAN REV'  }},
      sentiment: {{ g:'◉',  c:'#ff4081', n:'SENTIMENT' }},
      volatility:{{ g:'⚡', c:'#ff6b35', n:'VOLATILITY'}},
      factor:    {{ g:'✦',  c:'#ffd740', n:'FACTOR'    }},
      macro:     {{ g:'≋',  c:'#00bcd4', n:'MACRO'     }},
      ensemble:  {{ g:'❋',  c:'#ffffff', n:'ENSEMBLE'  }},
    }};

    function _updateHeadings(layout) {{
      var hdrEl = document.getElementById('tile-headings');
      if (!hdrEl) return;

      // Collect strategy groups: {{ key, xStart, width, count }}
      var groups = [];
      // Crypto group (left side)
      if (layout.cryptoCols > 0 && layout.crypto.length > 0) {{
        // Identify strategy of first crypto tile (all crypto = same strategy for now)
        var cKey = (layout.crypto[0] && layout.crypto[0].strategy) || 'crypto';
        groups.push({{ key: cKey, x: 0, w: layout.cryptoCols * _EQ_W, n: layout.crypto.length }});
      }}
      // Equity group (right side)
      if (layout.equityCols > 0 && layout.equity.length > 0) {{
        var eKey = (layout.equity[0] && layout.equity[0].strategy) || 'momentum';
        var eX = layout.cryptoCols * _EQ_W + (layout.cryptoCols > 0 && layout.equityCols > 0 ? 2 : 0);
        groups.push({{ key: eKey, x: eX, w: layout.equityCols * _EQ_W, n: layout.equity.length }});
      }}

      // Rebuild heading elements
      hdrEl.innerHTML = '';
      groups.forEach(function(g) {{
        var b = _HDR_BADGES[g.key] || {{ g: '◆', c: '#ffffff', n: g.key.toUpperCase() }};
        var div = document.createElement('div');
        div.className = 'tile-group-hdr';
        div.style.left  = g.x + 'px';
        div.style.width = g.w + 'px';
        div.style.color = b.c;
        div.style.borderBottomColor = b.c.replace(')', ',.15)').replace('rgb','rgba');
        div.style.textShadow = '0 0 8px ' + b.c;
        div.innerHTML = '<span style="font-size:9px;filter:drop-shadow(0 0 4px '+b.c+')">'
          + b.g + '</span><span>' + b.n + '</span>'
          + '<span style="margin-left:auto;opacity:.45;letter-spacing:.05em">'
          + g.n + (g.n === 1 ? ' HOLDING' : ' HOLDINGS') + '</span>';
        hdrEl.appendChild(div);
      }});
    }}

    function _updateOverlayWidth() {{
      var overlay = document.getElementById('pos-overlay');
      if (!overlay) return;
      // All tiles (crypto + equity) are on canvas — no separate left column
      var posLeft = document.getElementById('pos-left');
      if (posLeft) posLeft.style.width = '0';
      var layout = _etLayout();
      var eqW = layout.totalCols * _EQ_W;
      overlay.style.width = eqW + 'px';
      // Resize canvas
      if (_etCanvas) {{
        _etCanvas.style.width  = eqW + 'px';
        _etCanvas.style.height = layout.availH + 'px';
      }}
      // Reposition strategy group headings
      _updateHeadings(layout);
    }}

    window._updateOverlayWidth = _updateOverlayWidth;

    // Seed tiles from Python init data (sounds suppressed during this phase)
    (function() {{
      if (!window._eqCanvasInitData) return;
      _eqCanvasInitData.forEach(function(d) {{ _etUpsert(d); }});
      _etInitPhase = false; // future tile inserts play entry sound
    }})();

    // Wait for ALL fonts (including Orbitron) before starting the draw loop
    var _etRafLast = 0;
    function _etRafLoop(ts) {{
      if (ts - _etRafLast >= 33) {{
        _etRafLast = ts;
        if (!_etCanvas) _etInitCanvas();
        if (_etCanvas) _etDraw(ts);
      }}
      requestAnimationFrame(_etRafLoop);
    }}
    // Force Orbitron to actually render before the RAF loop draws tiles.
    // document.fonts.ready resolves even if the font failed to load;
    // document.fonts.load() triggers a real load, and the warm-up fillText
    // forces the browser to finish rasterizing the glyphs before first draw.
    Promise.all([
      document.fonts.load('700 16px VT323'),
      document.fonts.load('400 14px VT323')
    ]).then(function() {{
      var _tmp = document.createElement('canvas');
      var _tc = _tmp.getContext('2d');
      _tc.font = '700 16px VT323';
      _tc.fillText('BTC', 0, 10);
      _tc.font = '400 14px VT323';
      _tc.fillText('BTC', 0, 10);
      requestAnimationFrame(_etRafLoop);
    }});
    // ── Ticker popup ──────────────────────────────────────────────────────────
    (function() {{
      var _popup = null;
      var _popupSym = null;

      function _openPopup(sym, anchorX, anchorY) {{
        var clean = sym.replace('/USD','').replace('USD','');
        if (_popup && _popupSym === clean) {{ _closePopup(); return; }}
        _closePopup();
        _popupSym = clean;

        var p = document.createElement('div');
        p.id = 'ticker-popup';
        p.style.cssText = [
          'position:fixed;z-index:9999',
          'background:rgba(8,0,18,0.97)',
          'border:1px solid ' + (_symCol(sym)),
          'border-radius:4px',
          'padding:12px 14px',
          'min-width:260px;max-width:320px',
          'font:400 13px VT323,monospace',
          'color:#e0d0ff',
          'box-shadow:0 0 24px rgba(0,0,0,0.8)',
        ].join(';');

        // Position near click, keep on screen
        var W = window.innerWidth, H = window.innerHeight;
        var px = Math.min(anchorX + 12, W - 340);
        var py = Math.min(anchorY + 12, H - 420);
        p.style.left = px + 'px'; p.style.top = py + 'px';

        var col = (window._TICKER_OVR && window._TICKER_OVR[clean]) || _symCol(sym);

        p.innerHTML = [
          '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">',
            '<span id="tp-sym-label" style="font:700 18px VT323,monospace;color:' + col + '">' + clean + '</span>',
            '<div style="display:flex;align-items:center;gap:8px">',
              '<label style="font-size:11px;color:#6a4a8a">COLOR</label>',
              '<input type="color" id="tp-colorpick" value="' + col + '" ',
                'style="width:28px;height:20px;border:none;background:none;cursor:pointer;padding:0">',
            '</div>',
            '<span id="tp-close" style="cursor:pointer;color:#6a4a8a;font-size:16px;padding:0 4px">✕</span>',
          '</div>',
          '<div style="border-top:1px solid rgba(255,255,255,0.07);padding-top:8px;font-size:12px;color:#5a3a7a;margin-bottom:6px">',
            'RECENT TRADES',
          '</div>',
          '<div id="tp-history" style="max-height:280px;overflow-y:auto;font:400 13px VT323,monospace">',
            '<div style="color:#3a1a5a">loading…</div>',
          '</div>',
        ].join('');

        document.body.appendChild(p);
        _popup = p;

        // Color picker — updates tiles, terminal feed spans, popup header, and saves to DB
        p.querySelector('#tp-colorpick').addEventListener('input', function(e) {{
          var newCol = e.target.value;
          if (!window._TICKER_OVR) window._TICKER_OVR = {{}};
          window._TICKER_OVR[clean] = newCol;
          if (window._saveTickerColor) window._saveTickerColor(clean, newCol);
          // Canvas tiles
          (window._ET||[]).forEach(function(t) {{
            if (t.sym.replace('/USD','').replace('USD','') === clean) t.col = newCol;
          }});
          // All terminal feed spans with matching data-sym
          document.querySelectorAll('[data-sym]').forEach(function(s) {{
            if (s.dataset.sym.replace('/USD','').replace('USD','') === clean) s.style.color = newCol;
          }});
          // Popup border + header label
          p.style.borderColor = newCol;
          p.querySelector('#tp-sym-label').style.color = newCol;
        }});

        // Close button
        p.querySelector('#tp-close').addEventListener('click', _closePopup);

        // Click outside to close
        setTimeout(function() {{
          document.addEventListener('click', _outsideClose);
        }}, 50);

        // Fetch fill history
        var histUrl = SUPA_URL + '/rest/v1/fills'
          + '?select=symbol,side,quantity,fill_price,filled_at'
          + '&symbol=eq.' + sym
          + '&order=filled_at.desc&limit=30';
        fetch(histUrl, {{headers:{{'apikey':SUPA_KEY,'Authorization':'Bearer '+SUPA_KEY}}}})
        .then(function(r){{return r.json();}})
        .then(function(rows){{
          var el = document.getElementById('tp-history');
          if (!el) return;
          if (!Array.isArray(rows) || !rows.length) {{
            el.innerHTML = '<div style="color:#3a1a5a">no fills found</div>'; return;
          }}
          el.innerHTML = rows.map(function(f) {{
            var side = (f.side||'').toUpperCase() === 'BUY' ? '<span style="color:#00b4ff">enter</span>' : '<span style="color:#ff9900">exit</span>';
            var price = f.fill_price < 1 ? '$'+parseFloat(f.fill_price).toFixed(4) : '$'+parseFloat(f.fill_price).toLocaleString('en-US',{{maximumFractionDigits:2}});
            var qty   = parseFloat(f.qty || f.quantity || 0);
            var t     = new Date(f.filled_at);
            var ts    = (t.getMonth()+1)+'/'+(t.getDate())+' '+(t.getHours()%12||12)+':'+(('0'+t.getMinutes()).slice(-2))+(t.getHours()<12?'a':'p');
            return '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.04)">'
              +'<span style="color:#3a1a5a;font-size:11px">'+ts+'</span>'
              +side+' '+price
              +'</div>';
          }}).join('');
        }}).catch(function(){{
          var el = document.getElementById('tp-history');
          if (el) el.innerHTML = '<div style="color:#3a1a5a">error fetching fills</div>';
        }});
      }}

      function _closePopup() {{
        if (_popup) {{ _popup.remove(); _popup = null; _popupSym = null; }}
        document.removeEventListener('click', _outsideClose);
      }}

      function _outsideClose(e) {{
        if (_popup && !_popup.contains(e.target)) _closePopup();
      }}

      // Canvas click → hit-test tiles
      document.addEventListener('click', function(e) {{
        var canvas = document.getElementById('eq-tiles-canvas');
        if (!canvas || !window._ET) return;
        var rect = canvas.getBoundingClientRect();
        if (e.clientX < rect.left || e.clientX > rect.right ||
            e.clientY < rect.top  || e.clientY > rect.bottom) return;
        var mx = (e.clientX - rect.left) * (canvas.width / rect.width / _etDpr);
        var my = (e.clientY - rect.top)  * (canvas.height / rect.height / _etDpr);
        var layout = _etLayout();
        var hit = null;
        window._ET.forEach(function(t) {{
          if (t.phase === 'done') return;
          var pos = _etTilePos(t, layout);
          if (mx >= pos.x && mx < pos.x + _EQ_W && my >= pos.y && my < pos.y + _EQ_H) hit = t;
        }});
        if (hit) {{ e.stopPropagation(); _openPopup(hit.sym, e.clientX, e.clientY); }}
      }});

      // Terminal feed click — delegate on the feed container
      document.addEventListener('click', function(e) {{
        var span = e.target;
        if (span.tagName !== 'SPAN' || !span.dataset.sym) return;
        var feedEl = document.getElementById('feed-overlay');
        if (!feedEl || !feedEl.contains(span)) return;
        e.stopPropagation();
        _openPopup(span.dataset.sym, e.clientX, e.clientY);
      }});

      window._openTickerPopup = _openPopup;
    }})();

    window._makeCard = function(p) {{ return _makeCard(p); }};
    function _makeCard(p) {{
      // Route all crypto tiles to the unified canvas engine — no DOM element created
      var col   = _symCol(p.symbol);
      var entry = parseFloat(p.entry_price || 0);
      var stop  = parseFloat(p.stop_price  || 0);
      var tgt   = parseFloat(p.target_price|| 0);
      if ((!tgt || tgt <= 0) && entry > 0) tgt = entry * 1.008;
      var qty   = parseFloat(p.qty || 0);
      var entTs = p.entered_at ? new Date(p.entered_at).getTime() : Date.now();
      _etUpsert({{
        sym: p.symbol, col: col, entry: entry, stop: stop, target: tgt,
        qty: qty, isCrypto: true, direction: p.direction || 'long',
        enteredAt: entTs, curPrice: entry,
        val: qty * entry, pnl: 0, pnlPct: 0,
        inSignal: false, rank: 0, holdText: '',
      }});
      return null; // no DOM element — callers must handle null
    }}
    function _makeCardLEGACY_UNUSED(p) {{
      // Original DOM card builder — kept for reference only, never called
      var col   = _symCol(p.symbol);
      var entry = parseFloat(p.entry_price);
      var stop  = parseFloat(p.stop_price);
      var qty   = parseFloat(p.qty);
      var age   = p.entered_at ? Math.round((Date.now() - new Date(p.entered_at)) / 60000) : 0;
      var stopPct = entry > 0 ? ((stop - entry) / entry * 100).toFixed(1) : '—';
      var qtyStr  = qty > 1000 ? qty.toFixed(0) : qty < 0.001 ? qty.toExponential(2) : qty.toFixed(4);
      var wr = window._winRates && window._winRates[p.symbol];
      var wrHtml = '';
      if (wr && wr.t >= 3) {{
        var wrPct = Math.round(wr.w / wr.t * 100);
        var wrCol = wrPct >= 55 ? '#00ff9d' : wrPct >= 40 ? '#ff9900' : '#ff3366';
        var wrBg  = wrPct >= 55 ? 'rgba(0,255,157,.1)' : wrPct >= 40 ? 'rgba(255,153,0,.1)' : 'rgba(255,51,102,.1)';
        wrHtml = '<span class="win-badge" style="color:' + wrCol + ';background:' + wrBg + '">' + wrPct + '% W</span>';
      }}
      var el = document.createElement('div');
      el.className = 'pos-card';
      el.setAttribute('data-sym', p.symbol);
      el.setAttribute('data-entered', p.entered_at || '');
      el.setAttribute('data-qty', qty || 0);
      el.setAttribute('data-entry', entry || 0);
      el.style.borderLeft = '3px solid ' + col;
      el.style.position = 'relative';
      el.style.overflow = 'hidden';
      el.style.transformOrigin = 'center top';
      var agePct  = Math.min(age / 2 * 100, 100);  // 2-min max hold
      var ageBg   = agePct < 70 ? 'rgba(0,180,140,.55)' : agePct < 90 ? 'rgba(200,140,0,.6)' : 'rgba(200,60,80,.55)';
      // Acquired flash overlay
      var flash = document.createElement('div');
      flash.className = 'pos-acq-flash';
      flash.textContent = 'ACQUIRED';
      flash.style.color = col;
      el.appendChild(flash);
      // Live proximity meter (stop → current → target)
      var tgt = parseFloat(p.target_price || 0);
      // Synthetic target from config (0.8%) if DB value is null/zero
      if ((!tgt || tgt <= 0) && entry > 0) tgt = entry * 1.008;
      var rangeHtml = '';
      if (entry > 0 && stop > 0) {{
        var stopDisp = stop < 1 ? '$' + stop.toFixed(4) : '$' + stop.toFixed(2);
        var tgtDisp  = tgt  < 1 ? '$' + tgt.toFixed(4)  : '$' + tgt.toFixed(2);
        rangeHtml = '<div class="pos-prox-wrap"'
          + ' data-entry="' + entry + '" data-stop="' + stop + '" data-target="' + tgt + '">'
          + '<div class="pos-prox-labels-row">'
          + '<span class="prox-lbl-stop">● ' + stopDisp + '</span>'
          + '<span class="prox-lbl-arrow" id="prox-arrow-' + _symId + '">—</span>'
          + '<span class="prox-lbl-tgt">' + tgtDisp + ' ●</span>'
          + '</div>'
          + '<div class="pos-prox-track">'
          + '<div class="pos-prox-zone-stop" style="width:20%"></div>'
          + '<div class="pos-prox-zone-tgt"  style="width:20%"></div>'
          + '<div class="pos-prox-fill" style="width:50%"></div>'
          + '<div class="pos-prox-cursor" style="left:50%"></div>'
          + '<div class="pos-prox-live" id="prox-live-' + _symId + '" style="left:50%;color:#fff"></div>'
          + '</div>'
          + '</div>';
      }}
      var entryDisp = entry > 0 ? (entry < 0.01 ? '$' + entry.toFixed(6) : entry < 1 ? '$' + entry.toFixed(4) : '$' + entry.toFixed(2)) : '—';
      var _symId = p.symbol.replace(/[^A-Za-z0-9]/g,'_');
      // Age bar: fills left→right over 4h to show how long position has been held
      var ageBarPct = Math.min(agePct / 2 * 100, 100); // agePct is 0-100 over 2min — rescale
      var inner = document.createElement('div');
      inner.innerHTML = '<div class="pos-top">'
        + '<span class="pos-sym" style="color:' + col + '">···</span>'
        + '<span class="pos-hval" id="hval-' + _symId + '">$—</span>'
        + '</div>'
        + '<div class="pos-entry-sub">'
        + '<span class="pos-epx" id="epx-' + _symId + '" style="color:' + col + '">···</span>'
        + '<span class="pos-pnl-live" id="pnl-live-' + _symId + '">——</span>'
        + '</div>'
        + rangeHtml
        + '<div class="pos-age-bar" title="time held"><div class="pos-age-fill" id="age-fill-' + _symId + '" style="width:0%;background:#00c8ff;box-shadow:0 0 7px rgba(0,200,255,.75)"></div></div>';
      el.appendChild(inner);
      // Lock the card at its natural height before entry animation so it never shrinks
      requestAnimationFrame(function() {{
        var h = el.getBoundingClientRect().height;
        if (h > 0) {{ el.style.minHeight = h + 'px'; }}
      }});
      // ── Multi-phase entry animation ────────────────────────────────────────
      var CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#@$%';
      function _scramble(domEl, target, ms, onDone) {{
        var steps = Math.ceil(ms / 28); var f = 0;
        var iv = setInterval(function() {{
          f++;
          var out = '';
          for (var i = 0; i < target.length; i++) {{
            out += (i / target.length < f / steps) ? target[i] : CHARS[Math.floor(Math.random() * CHARS.length)];
          }}
          domEl.textContent = out;
          if (f >= steps) {{ domEl.textContent = target; clearInterval(iv); if (onDone) onDone(); }}
        }}, 28);
      }}
      function _countUp(domEl, start, end, ms, fmt) {{
        var steps = Math.ceil(ms / 20); var f = 0;
        var iv = setInterval(function() {{
          f++;
          var v = start + (end - start) * (f / steps);
          domEl.textContent = fmt(v);
          if (f >= steps) {{ domEl.textContent = fmt(end); clearInterval(iv); }}
        }}, 20);
      }}
      // Phase 1 (180ms): "◈ ACQUIRING" overlay flashes — blue entry theme
      setTimeout(function() {{
        flash.textContent = '◈ ACQUIRING';
        flash.style.color = '#00b4ff';
        flash.style.fontSize = '8px';
        flash.style.letterSpacing = '.22em';
        flash.classList.add('show');
        el.style.boxShadow = '0 0 18px rgba(0,180,255,.45), inset 0 0 12px rgba(0,180,255,.15)';
        el.style.borderLeftColor = '#00b4ff';
      }}, 180);
      // Phase 2 (360ms): sym scrambles in
      setTimeout(function() {{
        var symEl = inner.querySelector('.pos-sym');
        symEl.style.opacity = '1';
        _scramble(symEl, p.symbol.replace('/USD',''), 220);
      }}, 360);
      // Phase 3 (520ms): entry price scrambles into pos-epx in ticker color
      setTimeout(function() {{
        var epxEl = document.getElementById('epx-' + _symId);
        if (epxEl) _scramble(epxEl, entryDisp, 220);
      }}, 520);
      // Phase 4 (720ms): prox bar labels — nothing visible to show, skip
      setTimeout(function() {{ }}, 720);
      // Phase 5 (920ms): proximity bar fills to position, overlay becomes "OPEN" — blue
      setTimeout(function() {{
        flash.textContent = '● OPEN';
        flash.style.color = '#00e5ff';
        flash.style.fontSize = '9px';
        flash.style.letterSpacing = '.3em';
        el.style.boxShadow = '0 0 16px rgba(0,180,255,.3), inset 0 0 6px rgba(0,180,255,.08)';
        el.style.borderLeftColor = col;
        // Fill proximity bar
        var pFill = el.querySelector('.pos-prox-fill');
        var pCursor = el.querySelector('.pos-prox-cursor');
        if (pFill) {{ pFill.style.transition = 'width .4s ease-out'; pFill.style.width = '50%'; }}
        if (pCursor) {{ pCursor.style.transition = 'left .4s ease-out'; pCursor.style.left = '50%'; }}
      }}, 920);
      // Phase 6 (1150ms): overlay fades, glow settles, card goes active
      setTimeout(function() {{
        flash.style.transition = 'opacity .4s ease';
        flash.style.opacity = '0';
        el.classList.add('pos-card-active');
        setTimeout(function() {{
          el.style.boxShadow = '';
          if (flash.parentNode) flash.style.display = 'none';
        }}, 420);
      }}, 1150);
      return el;
    }}   // end _makeCardLEGACY_UNUSED

    function _updateCard(el, p) {{
      var entry   = parseFloat(p.entry_price);
      var ageSec  = p.entered_at ? (Date.now() - new Date(p.entered_at)) / 1000 : 0;
      var ageHrs  = ageSec / 3600;
      var symId   = (p.symbol || el.getAttribute('data-sym') || '').replace(/[^A-Za-z0-9]/g,'_');

      // Entry price in ticker color (pos-epx)
      var epxEl = document.getElementById('epx-' + symId);
      if (epxEl && entry > 0) {{
        epxEl.textContent = entry < 0.01 ? '$' + entry.toFixed(6) : entry < 1 ? '$' + entry.toFixed(4) : '$' + entry.toFixed(2);
      }}

      // Age bar: fills left→right, full at 4 hours — purely visual sense of how long held
      var fill = document.getElementById('age-fill-' + symId) || el.querySelector('.pos-age-fill');
      if (fill) {{
        var pct = Math.min(ageHrs / 4 * 100, 100); // 4h = full bar
        fill.style.width = pct + '%';
        // Color: cyan (fresh) → orange (aging) → red (very long)
        fill.style.background = pct < 33 ? '#00c8ff' : pct < 66 ? '#ffaa00' : '#ff2844';
        fill.style.boxShadow = pct < 33 ? '0 0 7px rgba(0,200,255,.75)' : pct < 66 ? '0 0 7px rgba(255,170,0,.7)' : '0 0 9px rgba(255,40,70,.85)';
      }}
    }}

    function _pollPositions() {{
      var url = SUPA_URL + '/rest/v1/crypto_positions'
        + '?select=symbol,direction,qty,entry_price,stop_price,target_price,entered_at'
        + '&order=entered_at.asc';
      fetch(url, {{
        headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }}
      }})
      .then(function(r) {{ return r.ok ? r.json() : r.json().then(function(e) {{ console.error('[crypto_positions] HTTP', r.status, e); return null; }}); }})
      .then(function(rows) {{
        if (!Array.isArray(rows)) return; // error response — don't touch existing cards
        console.log('[crypto_positions] rows:', rows.length);
        var section = document.getElementById('pos-crypto-section');
        if (!section) return;
        var flat = document.getElementById('pos-crypto-flat');

        // Expose positions map; detect exits to animate satellites out
        var oldMap = window._cryptoPositionsMap || {{}};
        if (Array.isArray(rows) && rows.length) {{
          var newMap = {{}};
          rows.forEach(function(p) {{ newMap[p.symbol] = p; }});
          window._cryptoPositionsMap = newMap;
          window._cryptoPairCount    = 15;
        }} else {{
          window._cryptoPositionsMap = {{}};
        }}
        // Launch exit animation for any symbol no longer in map
        Object.keys(oldMap).forEach(function(sym) {{
          if (!window._cryptoPositionsMap[sym] && _satAngles[sym] !== undefined) {{
            var pos = oldMap[sym]; var entry = parseFloat(pos.entry_price||0);
            var stop = parseFloat(pos.stop_price||0); var tgt = parseFloat(pos.target_price||0)||entry*1.008;
            var range = tgt - stop; var price = (window._liveProxPrices||{{}})[sym] || entry;
            var t2 = range ? Math.max(0,Math.min(1,(price-stop)/range)) : 0.5;
            var orbitR = 20 + t2*24;
            _satExiting[sym] = {{
              angle: _satAngles[sym], orbitR: orbitR, age: 0,
              sr: Math.round(255*Math.max(0,1-t2*1.5)),
              sg: Math.round(255*Math.min(1,t2*1.8)),
              sb: Math.round(102*(1-t2))
            }};
            delete _satAngles[sym];
            delete _smoothOrbitR[sym];
            delete _satEntryAge[sym];
          }}
        }});

        if (!Array.isArray(rows) || !rows.length) {{
          // Exit all open crypto canvas tiles (poll fallback)
          _ET.filter(function(t) {{ return t.isCrypto; }}).forEach(function(t) {{
            if (t.phase === 'live' || t.phase === 'entering') {{
              window._etExit(t.sym, null, null);
            }}
          }});
          _updateOverlayWidth();
          return;
        }}

        var newSyms = {{}};
        rows.forEach(function(p) {{ newSyms[p.symbol] = p; }});

        // Exit crypto canvas tiles no longer in data (poll fallback)
        _ET.filter(function(t) {{ return t.isCrypto; }}).forEach(function(t) {{
          if (!newSyms[t.sym] && (t.phase === 'live' || t.phase === 'entering')) {{
            window._etExit(t.sym, null, null);
          }}
        }});

        // Add or update canvas tiles — _etUpsert handles both
        rows.forEach(function(p) {{
          _makeCard(p);
        }});
        _updateOverlayWidth();

        // Mirror into report panel rp-crypto-section
        var rpSection = document.getElementById('rp-crypto-section');
        if (rpSection) {{
          var PALETTE = ['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
          function _symCol(s) {{ var c=s.replace('/USD','').replace('USD',''); if(window._TICKER_OVR&&window._TICKER_OVR[c])return window._TICKER_OVR[c]; var h=0; for(var i=0;i<c.length;i++)h=(h*31+c.charCodeAt(i))&0xffff; return PALETTE[h%PALETTE.length]; }}
          function _rpPnlStr(p) {{
            if (!p.entry_price) return '—';
            // For crypto we don't have current price in this fetch — show entry info
            return 'entered @ $' + parseFloat(p.entry_price).toFixed(4);
          }}
          // Build desired set of syms
          var desiredSyms = {{}};
          rows.forEach(function(p) {{ desiredSyms[p.symbol] = p; }});
          // Remove stale rp rows
          Array.from(rpSection.querySelectorAll('.rp-pos[data-sym]')).forEach(function(el) {{
            if (!desiredSyms[el.getAttribute('data-sym')]) {{ rpSection.removeChild(el); }}
          }});
          // Add missing rp rows
          rows.forEach(function(p) {{
            if (rpSection.querySelector('.rp-pos[data-sym="'+p.symbol+'"]')) return;
            var tcol = _symCol(p.symbol.replace('/USD',''));
            var baseSym = p.symbol.replace('/USD','');
            var holdMin = Math.floor((Date.now() - new Date(p.entered_at).getTime()) / 60000);
            var holdStr = holdMin < 1 ? '<1m' : holdMin + 'm';
            var subText = (p.qty ? parseFloat(p.qty).toFixed(4) + ' ' + baseSym : '') + (holdMin !== undefined ? '  ·  ' + holdStr : '');
            var el = document.createElement('div');
            el.className = 'rp-pos rp-pos-entering'; el.setAttribute('data-sym', p.symbol);
            el.style.cssText = 'position:relative;overflow:hidden';
            el.innerHTML = '<span class="pos-corner tl" style="border-color:'+tcol+'"></span>' +
              '<span class="pos-corner tr" style="border-color:'+tcol+'"></span>' +
              '<span class="pos-corner bl" style="border-color:'+tcol+'"></span>' +
              '<span class="pos-corner br" style="border-color:'+tcol+'"></span>' +
              '<div class="rp-pos-stripe" style="background:'+tcol+';box-shadow:0 0 8px '+tcol+'55"></div>' +
              '<div class="rp-pos-top"><span class="rp-pos-sym" style="color:'+tcol+'">'+baseSym+'</span>' +
              '<span class="rp-pos-type">CRYPTO</span></div>' +
              '<div class="rp-pos-val">—</div>' +
              '<div class="rp-pos-sub"><span class="rp-pos-qty">'+subText+'</span></div>' +
              '<div class="rp-pos-pnl" style="color:#6a4a8a">'+_rpPnlStr(p)+'</div>';
            rpSection.appendChild(el);
          }});
          if (!rows.length) {{
            if (!rpSection.querySelector('.rp-empty-crypto')) {{
              var emp = document.createElement('div');
              emp.className = 'rp-empty-crypto';
              emp.style.cssText = 'padding:12px 14px;font-size:9px;color:#2a1a3a;letter-spacing:.04em';
              emp.textContent = 'no crypto positions';
              rpSection.appendChild(emp);
            }}
          }} else {{
            var emp2 = rpSection.querySelector('.rp-empty-crypto');
            if (emp2) rpSection.removeChild(emp2);
          }}
        }}
      }})
      .catch(function() {{}});
    }}

    setTimeout(function() {{
      _pollPositions();
      setInterval(_pollPositions, 2000);
    }}, 2000);

    // Tick age bars every 30s (entry price + hold bar — no need for per-second update)
    setInterval(function() {{
      var posMap = window._cryptoPositionsMap || {{}};
      Object.keys(posMap).forEach(function(sym) {{
        var el = (typeof _cryptoCardEls !== 'undefined') ? _cryptoCardEls[sym] : null;
        if (el) _updateCard(el, posMap[sym]);
      }});
    }}, 30000);

    // ── Live crypto price poller — updates proximity meters in real time ──────
    var _CG_SYM_MAP = {{
      'BTC/USD':'bitcoin','ETH/USD':'ethereum','SOL/USD':'solana',
      'AVAX/USD':'avalanche-2','LINK/USD':'chainlink','DOGE/USD':'dogecoin',
      'BCH/USD':'bitcoin-cash','XTZ/USD':'tezos','CRV/USD':'curve-dao-token',
      'UNI/USD':'uniswap','ADA/USD':'cardano','MATIC/USD':'matic-network',
      'DOT/USD':'polkadot',
    }};
    var _CG_ID_TO_SYM = {{}};
    Object.keys(_CG_SYM_MAP).forEach(function(s) {{ _CG_ID_TO_SYM[_CG_SYM_MAP[s]] = s; }});
    function _updateProxMeters(priceMap) {{
      document.querySelectorAll('.pos-prox-wrap[data-entry]').forEach(function(wrap) {{
        var card = wrap.closest('.pos-card[data-sym]');
        if (!card) return;
        var sym = card.getAttribute('data-sym');
        var price = priceMap[sym];
        if (!price) return;
        var entry  = parseFloat(wrap.getAttribute('data-entry'));
        var stop   = parseFloat(wrap.getAttribute('data-stop'));
        var tgt    = parseFloat(wrap.getAttribute('data-target'));
        if (!entry || !stop || !tgt) return;
        // t=0 at stop, t=1 at target (clamped)
        var range = tgt - stop;
        var t = range !== 0 ? Math.max(0, Math.min(1, (price - stop) / range)) : 0.5;
        var pct = (t * 100).toFixed(1);
        var fill   = wrap.querySelector('.pos-prox-fill');
        var cursor = wrap.querySelector('.pos-prox-cursor');
        var live   = wrap.querySelector('.pos-prox-live');
        if (fill)   fill.style.width  = pct + '%';
        if (cursor) cursor.style.left = pct + '%';
        // Cursor zone color
        if (cursor) {{
          cursor.classList.toggle('danger', t < 0.18);
          cursor.classList.toggle('target', t > 0.82);
          if (t >= 0.18 && t <= 0.82) {{
            cursor.style.background = '#ffffff';
            cursor.style.animation  = 'none';
          }}
        }}
        // Floating price label above cursor
        var symId2    = sym.replace(/[^A-Za-z0-9]/g,'_');
        var proxLive  = document.getElementById('prox-live-' + symId2);
        if (proxLive) {{
          var priceDisp = price < 0.01 ? '$' + price.toFixed(6) : price < 1 ? '$' + price.toFixed(4) : '$' + price.toFixed(2);
          var prevPx = parseFloat(proxLive.getAttribute('data-px') || 'NaN');
          var pxDir  = !isNaN(prevPx) ? (price > prevPx ? 'up' : price < prevPx ? 'dn' : '') : '';
          proxLive.setAttribute('data-px', price);
          proxLive.style.left  = pct + '%';
          proxLive.style.color = t < 0.18 ? '#ff3366' : t > 0.82 ? '#00ff9d' : '#ffffff';
          proxLive.textContent = priceDisp;
          if (pxDir) {{
            proxLive.classList.remove('prox-tick-up','prox-tick-dn');
            void proxLive.offsetWidth;
            proxLive.classList.add('prox-tick-' + pxDir);
          }}
        }}
        // Direction arrow between stop/target labels
        var arrowEl = document.getElementById('prox-arrow-' + symId2);
        if (arrowEl) {{
          var prevT = parseFloat(arrowEl.getAttribute('data-t') || 'NaN');
          if (!isNaN(prevT) && t !== prevT) {{
            arrowEl.textContent = t > prevT ? '→' : '←';
            arrowEl.style.color = t > prevT ? '#00ff9d' : '#ff3366';
          }}
          arrowEl.setAttribute('data-t', t);
        }}
        // Live P&L in pos-entry-sub row
        var pnlPct  = entry > 0 ? ((price - entry)/entry*100) : 0;
        var pnlSign = pnlPct >= 0 ? '+' : '';
        var pnlEl   = document.getElementById('pnl-live-' + symId2);
        if (pnlEl) {{
          var prevRaw = parseFloat(pnlEl.getAttribute('data-raw') || 'NaN');
          var arrow = '';
          if (!isNaN(prevRaw) && pnlPct !== prevRaw) {{
            arrow = pnlPct > prevRaw ? '▲ ' : '▼ ';
            var dir = pnlPct > prevRaw ? 'up' : 'dn';
            pnlEl.classList.remove('prox-tick-up', 'prox-tick-dn');
            void pnlEl.offsetWidth;
            pnlEl.classList.add('prox-tick-' + dir);
          }}
          pnlEl.setAttribute('data-raw', pnlPct);
          pnlEl.textContent = arrow + pnlSign + pnlPct.toFixed(2) + '%';
          pnlEl.style.color = pnlPct >= 0 ? '#00ff9d' : '#ff3366';
        }}

      }});
    }}
    function _pollCryptoPrices() {{
      // Collect open crypto tile symbols from canvas engine
      var openSyms = _ET.filter(function(t) {{ return t.isCrypto && t.phase !== 'done'; }})
                        .map(function(t) {{ return t.sym; }});
      if (!openSyms.length) return;
      var cgIds = openSyms.map(function(s) {{ return _CG_SYM_MAP[s]; }}).filter(Boolean);
      if (!cgIds.length) return;
      fetch('https://api.coingecko.com/api/v3/simple/price?ids=' + cgIds.join(',') + '&vs_currencies=usd')
        .then(function(r) {{ return r.ok ? r.json() : null; }})
        .then(function(data) {{
          if (!data) return;
          var priceMap = {{}};
          Object.keys(data).forEach(function(id) {{
            var sym = _CG_ID_TO_SYM[id];
            if (sym && data[id] && data[id].usd) priceMap[sym] = data[id].usd;
          }});
          window._liveProxPrices = priceMap;
          if (window._onPricePoll) window._onPricePoll();
          _updateProxMeters(priceMap);
          // Update canvas tile state (replaces DOM element updates)
          var posMap = window._cryptoPositionsMap || {{}};
          _ET.filter(function(t) {{ return t.isCrypto && t.phase !== 'done'; }}).forEach(function(t) {{
            var price = priceMap[t.sym];
            if (!price) return;
            var posData = posMap[t.sym];
            var qty = t.qty || (posData ? parseFloat(posData.qty || 0) : 0);
            var entry = t.entry || (posData ? parseFloat(posData.entry_price || 0) : 0);
            var prevPrice = t.curPrice;
            t.curPrice = price;
            if (qty > 0) t.val = qty * price;
            if (entry > 0) {{
              t.pnl    = qty * (price - entry);
              t.pnlPct = (price - entry) / entry * 100;
            }}
            if (prevPrice && price !== prevPrice) {{
              t._valFlash = price > prevPrice ? 1 : -1;
            }}
          }});
          // Compute live portfolio NAV and push intraday point
          if (window._pushIntradayPoint) {{
            var baseline = window._portfolioBaseline || 100000;
            var livePnl = 0;
            Object.keys(posMap).forEach(function(sym) {{
              var p = posMap[sym];
              var px = priceMap[sym];
              if (!p || !px) return;
              var entry = parseFloat(p.entry_price || 0);
              var qty   = parseFloat(p.qty || 0);
              if (entry > 0 && qty !== 0) livePnl += qty * (px - entry);
            }});
            // Write crypto slice; combine with equity slice so NAV is consistent across pollers
            window._livePnlBySource.crypto = livePnl;
            var _combinedPnl = window._livePnlBySource.equity + window._livePnlBySource.crypto;
            var nav = baseline + _combinedPnl;
            if (nav > 1000 && nav < 5000000) {{
              window._pushIntradayPoint(new Date().toISOString(), nav);
            }}
          }}
        }}).catch(function() {{}});
    }}
    setTimeout(_pollCryptoPrices, 3500);
    setInterval(_pollCryptoPrices, 4000);

    // ── Canonical NAV from DB — source of truth for displayed Portfolio number ──
    // All tabs read the latest nav_snapshots row so every screen shows the same value.
    function _pollCanonicalNav() {{
      fetch(SUPA_URL + '/rest/v1/nav_snapshots?select=recorded_at,nav&order=recorded_at.desc&limit=1',
        {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        if (!Array.isArray(rows) || !rows.length) return;
        var row = rows[0];
        var age = Date.now() - new Date(row.recorded_at).getTime();
        if (age > 120000) return; // ignore rows older than 2 min — stale
        var nav = parseFloat(row.nav);
        if (!nav || nav < 50000 || nav > 5000000) return;
        // Only update display if DB value differs meaningfully from what's shown
        var shown = window._lastKnownNav || 0;
        if (Math.abs(nav - shown) < 0.01) return;
        window._lastKnownNav = nav;
        if (window._updateNavDisplays_ext) window._updateNavDisplays_ext(nav, row.recorded_at);
      }}).catch(function() {{}});
    }}
    // Expose _updateNavDisplays so canonical poller can call it
    window._updateNavDisplays_ext = function(nav, ts) {{ _updateNavDisplays(nav, ts); }};
    setTimeout(_pollCanonicalNav, 6000); // slight delay so local compute runs first
    setInterval(_pollCanonicalNav, 5000);

    // ── Equity pipeline countdown (daily 4:05pm ET) ───────────────────────────
    (function() {{
      var _PIPELINE_WINDOW = 24 * 60 * 60 * 1000; // 24h in ms
      function _nextPipelineMs() {{
        var now = new Date();
        var etOffset = -5 * 60; // EST minutes offset
        var etNow = new Date(now.getTime() + (now.getTimezoneOffset() + etOffset) * 60000);
        var target = new Date(etNow);
        target.setHours(16, 5, 0, 0);
        if (etNow >= target) target.setDate(target.getDate() + 1);
        return target - etNow;
      }}
      function _updatePipeline() {{
        var fill = document.getElementById('eq-pip-fill');
        var eta  = document.getElementById('eq-pip-eta');
        if (!fill || !eta) return;
        var rem = _nextPipelineMs();
        fill.style.width = Math.max(0, Math.min(100, (1 - rem / _PIPELINE_WINDOW) * 100)) + '%';
        var h = Math.floor(rem / 3600000);
        var m = Math.floor((rem % 3600000) / 60000);
        eta.textContent = h + 'h ' + m + 'm';
      }}
      _updatePipeline();
      setInterval(_updatePipeline, 10000);
    }})();

    // ── Stats poller: streak + daily bar (every 15s) ─────────────────────────
    function _pollStats() {{
      // Fetch last 60 TRADE events that have EXIT to compute streak + per-symbol win rate
      var url = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=symbol,message,recorded_at'
        + '&event_type=eq.TRADE'
        + '&message=like.*EXIT*'
        + '&order=recorded_at.desc&limit=60';
      fetch(url, {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        if (!Array.isArray(rows)) return;
        // Streak: count consecutive ✓ or ✗ from top (most recent)
        var streak = 0, streakSign = null;
        for (var i = 0; i < rows.length; i++) {{
          var m = rows[i].message;
          var isWin = m.indexOf('✓') !== -1;
          var isLoss = m.indexOf('✗') !== -1;
          if (!isWin && !isLoss) continue;
          var s = isWin ? 1 : -1;
          if (streakSign === null) {{ streakSign = s; streak = 1; }}
          else if (s === streakSign) {{ streak++; }}
          else {{ break; }}
        }}
        var sv = document.getElementById('streak-val');
        if (sv) {{
          if (streakSign === null) {{ sv.textContent = '—'; sv.style.color = '#3a1a5a'; }}
          else {{
            var ico = streakSign > 0 ? '🔥' : '☠️';
            sv.innerHTML = ico + ' ' + streak + (streakSign > 0 ? 'W' : 'L');
            sv.style.color = streakSign > 0 ? '#00ff9d' : '#ff3366';
          }}
        }}
        // Sync window._streak so orb tooltip STREAK field stays current
        if (streakSign !== null) {{
          window._streak = {{ count: streak, win: streakSign > 0 }};
        }}
        // Win rate per symbol → store as map for _pollPositions to use
        window._winRates = {{}};
        var _totalW = 0, _totalT = 0;
        rows.forEach(function(row) {{
          var sym = row.symbol || '';
          if (!window._winRates[sym]) window._winRates[sym] = {{w:0,t:0}};
          window._winRates[sym].t++;
          _totalT++;
          if (row.message.indexOf('✓') !== -1) {{ window._winRates[sym].w++; _totalW++; }}
        }});
        // Update header win rate
        var _hwrEl = document.getElementById('hdr-winrate');
        if (_hwrEl) _hwrEl.textContent = _totalT > 0 ? Math.round(_totalW/_totalT*100) + '%' : '—';
      }}).catch(function() {{}});

      // Runner health — fetch most recent UPDATE event (heartbeat) and compute age
      var urlHb = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=recorded_at&event_type=eq.UPDATE&order=recorded_at.desc&limit=1';
      fetch(urlHb, {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        var dot = document.getElementById('runner-dot');
        var age = document.getElementById('runner-age');
        if (!dot || !age || !Array.isArray(rows) || !rows.length) return;
        var mins = (Date.now() - new Date(rows[0].recorded_at)) / 60000;
        var cls  = mins < 6 ? 'ok' : mins < 20 ? 'warn' : 'dead';
        dot.className = cls;
        age.textContent = mins < 1 ? '<1m' : Math.round(mins) + 'm ago';
        age.style.color = cls === 'ok' ? '#00ff9d' : cls === 'warn' ? '#ff9900' : '#ff3366';
      }}).catch(function() {{}});

      // Trade count today — HEAD request with Prefer:count=exact avoids row limit
      var todayStr = new Date().toISOString().split('T')[0];
      var urlTc = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=id&event_type=eq.TRADE&recorded_at=gte.' + todayStr + 'T00:00:00Z&limit=1';
      fetch(urlTc, {{ method:'HEAD', headers: {{
        'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY,
        'Prefer': 'count=exact'
      }} }})
      .then(function(r) {{
        var ct = r.headers.get('content-range'); // e.g. "0-0/1842"
        if (!ct) return;
        var total = ct.split('/')[1];
        var el = document.getElementById('runner-trades');
        if (el && total) el.textContent = total + ' trades today';
      }}).catch(function() {{}});

      // Daily bar: today's fills pnl proxy — compare earliest vs latest portfolio snapshot today
      var today = new Date().toISOString().split('T')[0];
      var urlSnap = SUPA_URL + '/rest/v1/portfolio_snapshots'
        + '?select=total_value,recorded_at&strategy=eq.crypto_momentum'
        + '&recorded_at=gte.' + today + 'T00:00:00Z&order=recorded_at.asc&limit=1';
      fetch(urlSnap, {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        if (!Array.isArray(rows) || !rows.length) return;
        var sodNav = parseFloat(rows[0].total_value);
        var latestNav = parseFloat(document.querySelector('.tb-stat-val')?.textContent?.replace(/[$,]/g,'')) || sodNav;
        // use the nav from the last known update if possible
        if (window._lastKnownNav) latestNav = window._lastKnownNav;
        var dayPnl = latestNav - sodNav;
        var dailyLimit = 10000; // $10K = 10% of $100K
        var pct = Math.min(Math.abs(dayPnl) / dailyLimit, 1);
        var fill = document.getElementById('daily-bar-fill');
        var lbl  = document.getElementById('daily-bar-label');
        if (fill) {{
          fill.style.width = (pct * 100) + '%';
          fill.style.background = dayPnl >= 0
            ? 'linear-gradient(90deg,#00ff9d,#00e5ff)'
            : 'linear-gradient(90deg,#ff3366,#ff9900)';
        }}
        if (lbl) {{
          var sign = dayPnl >= 0 ? '+' : '-';
          lbl.textContent = 'today ' + sign + '$' + Math.round(Math.abs(dayPnl)).toLocaleString('en-US');
          lbl.style.color = dayPnl >= 0 ? '#00ff9d' : '#ff3366';
        }}
      }}).catch(function() {{}});
    }}
    var _runnerCdSecs = 15;
    var _runnerCdEl = document.getElementById('runner-countdown');
    function _resetRunnerCd() {{
      _runnerCdSecs = 15;
      if (_runnerCdEl) _runnerCdEl.textContent = 'next: 15s';
    }}
    setInterval(function() {{
      if (_runnerCdSecs > 0) _runnerCdSecs--;
      if (_runnerCdEl) _runnerCdEl.textContent = 'next: ' + _runnerCdSecs + 's';
    }}, 1000);
    var _origPollStats = _pollStats;
    _pollStats = function() {{ _resetRunnerCd(); _origPollStats(); }};
    setTimeout(function() {{ _pollStats(); setInterval(_pollStats, 15000); }}, 6000);

    // ══════════════════════════════════════════════════════════════
    // STRATAGEM HUD — live slot updates + drop-in callouts
    // ══════════════════════════════════════════════════════════════
    (function() {{
      // ── Slot state helpers ────────────────────────────────────
      function _ssSet(id, stClass, text) {{
        var el = document.getElementById(id);
        if (!el) return;
        el.parentElement.className = 'strat-slot ' + stClass;
        el.textContent = text;
      }}
      function _fmtCountdown(ms) {{
        if (ms <= 0) return 'NOW';
        var s = Math.round(ms / 1000);
        if (s < 60) return s + 's';
        var m = Math.floor(s / 60); s = s % 60;
        if (m < 60) return m + 'm ' + (s < 10 ? '0' : '') + s + 's';
        var h = Math.floor(m / 60); m = m % 60;
        return h + 'h ' + (m < 10 ? '0' : '') + m + 'm';
      }}

      // ── RUNNER slot — reads from runner-dot age ───────────────
      function _updateRunnerSlot() {{
        var dot = document.getElementById('runner-dot');
        if (!dot) return;
        var cls = dot.className; // 'ok', 'warn', 'dead'
        var ageEl = document.getElementById('runner-age');
        var age = ageEl ? ageEl.textContent : '—';
        if (cls === 'ok') {{
          _ssSet('ss-runner-st', 'ss-active', 'ALIVE · ' + age);
        }} else if (cls === 'warn') {{
          _ssSet('ss-runner-st', 'ss-warn', 'STALE · ' + age);
        }} else if (cls === 'dead') {{
          _ssSet('ss-runner-st', 'ss-warn', 'DEAD · ' + age);
        }} else {{
          _ssSet('ss-runner-st', '', '—');
        }}
      }}

      // ── TRADES slot — total trade count (window-exposed for outer scope) ─
      var _hudTradeTotal = 0;
      window._updateTradesSlot = function(count) {{
        if (count !== undefined) _hudTradeTotal = count;
        var el = document.getElementById('ss-pipeline-st');
        if (el) {{ el.textContent = _hudTradeTotal; el.style.color = _hudTradeTotal > 0 ? '#ff9900' : 'rgba(148,0,255,.4)'; el.style.textShadow = _hudTradeTotal > 0 ? '0 0 10px rgba(255,153,0,.6)' : 'none'; }}
      }};
      window._tradeSlotCombo = function(delta) {{
        var chip = document.getElementById('ss-trades-chip');
        if (!chip || delta <= 0) return;
        chip.textContent = '+' + delta;
        chip.style.opacity = '1';
        setTimeout(function() {{ chip.style.opacity = '0'; }}, 4000);
      }};

      // ── WALLET slot — Alpaca NAV with gain/loss color flash (window-exposed) ─
      var _lastWalletVal = null;
      // rAF-animated counter — rolls from current displayed value to target
      var _walletRaf = null;
      var _walletRendered = null;
      function _animateWallet(toVal) {{
        var el = document.getElementById('ss-wallet-val');
        if (!el) return;
        var from = _walletRendered !== null ? _walletRendered : toVal;
        if (_walletRaf) {{ cancelAnimationFrame(_walletRaf); _walletRaf = null; }}
        var startTs = null;
        var DURATION = 700;
        function step(ts) {{
          if (!startTs) startTs = ts;
          var t = Math.min((ts - startTs) / DURATION, 1);
          t = 1 - Math.pow(1 - t, 3); // ease-out cubic
          var cur = from + (toVal - from) * t;
          _walletRendered = cur;
          window._navLiveVal = cur; // feed live interpolated value to canvas each frame
          el.textContent = '$' + cur.toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}});
          if (t < 1) _walletRaf = requestAnimationFrame(step);
          else {{ _walletRendered = toVal; _walletRaf = null; }}
        }}
        _walletRaf = requestAnimationFrame(step);
      }}
      // Quiet sync from NAV polls — color intensity scales with move size vs. recent history
      var _prevWalletNav = null;
      var _recentMagWindow = [];
      var _flashTimeout = null;
      window._updateWalletSlot = function(nav) {{
        if (!nav) return;
        var el = document.getElementById('ss-wallet-val');
        if (el && _prevWalletNav !== null && nav !== _prevWalletNav) {{
          var delta = nav - _prevWalletNav;
          var mag = Math.abs(delta);
          if (mag > 0.01) {{
            _recentMagWindow.push(mag);
            if (_recentMagWindow.length > 30) _recentMagWindow.shift();
          }}
          // Intensity: floor 0.15 so even tiny ticks show faint hue; scales to 1 at median+ moves
          var intensity = 0.15;
          if (_recentMagWindow.length >= 3) {{
            var sorted = _recentMagWindow.slice().sort(function(a,b) {{ return a-b; }});
            var median = sorted[Math.floor(sorted.length / 2)];
            if (median > 0) intensity = Math.min(1, 0.15 + (mag / median) * 0.85);
          }}
          if (mag > 0.01) {{
            var isGain = delta > 0;
            var rgb = isGain ? '0,255,157' : '255,51,102';
            var col = 'rgba(' + rgb + ',' + intensity + ')';
            var glow = 'rgba(' + rgb + ',' + (intensity * 0.7) + ')';
            el.style.color = col;
            el.style.textShadow = '0 0 16px ' + glow + ', 0 0 4px ' + glow;
            if (_flashTimeout) clearTimeout(_flashTimeout);
            _flashTimeout = setTimeout(function() {{
              if (el) {{ el.style.color = ''; el.style.textShadow = ''; }}
            }}, 750); // matches rAF animation duration; combos use class-based color separately
          }}
        }}
        _prevWalletNav = nav;
        _lastWalletVal = nav;
        _animateWallet(nav);
        // Throttle: push at most 1 point per 3s so points are spread across the canvas,
        // not clustered at center (rAF handles visual smoothness; data density doesn't need to match)
        if (!window._navHistory) window._navHistory = [];
        var _nowMs2 = Date.now();
        var _lastH = window._navHistory[window._navHistory.length - 1];
        // Push on every distinct value — no time throttle; rAF smooths visually
        if (!_lastH || _lastH.y !== nav) {{
          window._navHistory.push({{ x: new Date(_nowMs2).toISOString(), y: nav }});
          var _cutoff = new Date(_nowMs2 - 60*1000).toISOString();
          while (window._navHistory.length > 0 && window._navHistory[0].x < _cutoff) window._navHistory.shift();
          try {{ localStorage.setItem('_navHistory', JSON.stringify(window._navHistory)); }} catch(e) {{}}
        }}
      }};
      // Trade event: flash color + chip + animate to new value
      window._walletCombo = function(delta) {{
        var el = document.getElementById('ss-wallet-val');
        var chip = document.getElementById('ss-wallet-chip');
        if (!el) return;
        var newVal = (_lastWalletVal || 0) + delta;
        _lastWalletVal = newVal;
        var isGain = delta >= 0;
        el.classList.remove('gain', 'loss');
        void el.offsetWidth;
        el.classList.add(isGain ? 'gain' : 'loss');
        _animateWallet(newVal);
        if (chip) {{
          chip.textContent = (isGain ? '+$' : '-$') + Math.abs(delta).toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}});
          chip.style.color = isGain ? '#00ff9d' : '#ff3366';
          chip.classList.remove('dmg-active');
          void chip.offsetWidth; // force reflow so re-triggering works
          chip.classList.add('dmg-active');
          setTimeout(function() {{
            chip.classList.remove('dmg-active');
            el.classList.remove('gain','loss');
          }}, 5000);
        }}
      }};

      // ── QUEUED EVENTS slot + dropdown ────────────────────────
      var _lastPriceTs = 0;
      window._onPricePoll = function() {{ _lastPriceTs = Date.now(); }};
      var _queueOpen = false;
      function _fmtMs(ms) {{
        if (ms <= 0) return 'NOW';
        var s = Math.round(ms / 1000);
        if (s < 60) return s + 's';
        var m = Math.floor(s / 60), ss = s % 60;
        if (m < 60) return m + 'm ' + (ss ? ss + 's' : '');
        var h = Math.floor(m / 60), mm = m % 60;
        return h + 'h ' + (mm ? mm + 'm' : '');
      }}
      window._toggleQueueDropdown = function() {{
        _queueOpen = !_queueOpen;
        var dd = document.getElementById('queue-dropdown');
        if (!dd) return;
        if (_queueOpen) {{
          var slot = document.getElementById('ss-queue');
          var r = slot ? slot.getBoundingClientRect() : {{left:0,bottom:0}};
          dd.style.left = r.left + 'px';
          dd.style.top  = (r.bottom + 4) + 'px';
          dd.style.display = 'block';
          _renderQueueItems();
        }} else {{
          dd.style.display = 'none';
        }}
        // Close on outside click
        setTimeout(function() {{
          function _closeOnOut(e) {{
            var dd2 = document.getElementById('queue-dropdown');
            var sl2 = document.getElementById('ss-queue');
            if (dd2 && !dd2.contains(e.target) && sl2 && !sl2.contains(e.target)) {{
              dd2.style.display = 'none'; _queueOpen = false;
              document.removeEventListener('click', _closeOnOut);
            }}
          }}
          document.addEventListener('click', _closeOnOut);
        }}, 10);
      }};
      function _renderQueueItems() {{
        var el = document.getElementById('queue-dropdown-items');
        if (!el) return;
        var now = Date.now();
        var html = '';
        (_queuedActionsData || []).forEach(function(q) {{
          var rem  = (q.target_ms || 0) - now;
          var eta  = _fmtMs(rem);
          var past = rem <= 0;
          var col  = past ? 'rgba(255,255,255,.22)' : q.color;
          html += '<div style="display:flex;align-items:baseline;gap:10px;padding:6px 14px;border-bottom:1px solid rgba(255,255,255,.04)">'
            + '<span style="font-size:8px;font-weight:700;color:'+col+';letter-spacing:.12em;min-width:44px">'+ q.badge +'</span>'
            + '<span style="font-size:10px;color:rgba(220,200,255,.8);flex:1">'+ (q.label||'') +'</span>'
            + '<span style="font-size:8px;color:'+(past?'rgba(255,255,255,.2)':col)+';letter-spacing:.06em;white-space:nowrap">'
            + (past ? 'done' : 'in '+eta) +'</span>'
            + '</div>';
        }});
        if (!html) html = '<div style="padding:8px 14px;font-size:9px;color:rgba(255,255,255,.25)">no events scheduled</div>';
        el.innerHTML = html;
      }}
      function _updateQueueSlot() {{
        var now = Date.now();
        var next = null;
        (_queuedActionsData || []).forEach(function(q) {{
          var rem = (q.target_ms || 0) - now;
          if (rem > 0 && (next === null || rem < next.rem)) next = {{rem:rem, q:q}};
        }});
        if (next) {{
          _ssSet('ss-queue-st', 'ss-active', next.q.badge + ' in ' + _fmtMs(next.rem));
        }} else {{
          _ssSet('ss-queue-st', '', 'all done');
        }}
        if (_queueOpen) _renderQueueItems();  // live-update countdowns while open
      }}

      // ── CURRENT POS slot — open position count ───────────────
      var _prevPosCount = null;
      function _updateNavSlot() {{
        var nav = window._lastKnownNav;
        if (window._updateWalletSlot && nav) window._updateWalletSlot(nav);
        var count = Object.keys(window._cryptoPositionsMap || {{}}).length;
        var eq = document.querySelectorAll('#pos-equity-section .pos-card[data-sym]').length;
        var total = count + eq;
        _ssSet('ss-nav-st', total > 0 ? 'ss-active' : '', total > 0 ? total + ' OPEN' : 'FLAT');
        // Fire combo chip when count changes
        if (_prevPosCount !== null && total !== _prevPosCount) {{
          var diff = total - _prevPosCount;
          var chip = document.getElementById('ss-nav-chip');
          if (chip) {{
            chip.textContent = (diff > 0 ? '+' : '') + diff;
            chip.style.color = diff > 0 ? '#00ff9d' : '#ff3366';
            chip.classList.remove('dmg-active');
            void chip.offsetWidth;
            chip.classList.add('dmg-active');
            setTimeout(function() {{ chip.classList.remove('dmg-active'); }}, 2300);
          }}
        }}
        _prevPosCount = total;
      }}

      // ── Callout system — stackable drop-in notifications ────────
      var _calloutRail = document.getElementById('callout-rail');

      function _symColor(sym) {{
        var s=sym.replace('/USD','').replace('USD','');
        if(window._TICKER_OVR&&window._TICKER_OVR[s])return window._TICKER_OVR[s];
        var _p=['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#ff6b35','#00ffcc','#f7b731','#7c4dff','#18ffff'];
        var h=0; for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))&0xffff; return _p[h%_p.length];
      }}

      function _spawnCallout(cfg) {{
        var rail = document.getElementById('callout-rail');
        if (!rail) return;

        var symClean = (cfg.sym || '').replace('/USD','').replace('USD','');
        var symCol   = _symColor(symClean);
        var pnlVal   = cfg.pnl ? parseFloat(cfg.pnl.replace(/[^0-9.\-]/g,'')) : null;
        var isPos    = pnlVal !== null ? pnlVal >= 0 : null;
        var pnlCol   = isPos === null ? 'rgba(255,255,255,.6)' : (isPos ? '#00ff9d' : '#ff3366');
        var pnlStr   = pnlVal !== null
          ? (isPos ? '+$' : '-$') + Math.abs(pnlVal).toFixed(2)
          : (cfg.pnl || '');

        var isEvent  = cfg.isEvent || false; // true for MARKET OPEN etc.

        var card = document.createElement('div');
        card.className = 'callout-card';
        if (isEvent) {{
          card.innerHTML =
            '<span class="cc-verb" style="color:' + (cfg.col||'#fff') + ';letter-spacing:.2em">' + symClean + '</span>' +
            (cfg.countdown ? '<span class="cc-pnl" style="color:' + (cfg.col||'#fff') + '" id="cc-cd-' + Date.now() + '">' + Math.round(cfg.countdown) + 's</span>' : '');
        }} else {{
          card.innerHTML =
            '<span class="cc-verb" style="color:rgba(180,140,220,.65)">◆</span>' +
            '<span class="cc-sym" style="color:' + symCol + '">' + symClean + '</span>' +
            (pnlStr ? '<span class="cc-pnl" style="color:' + pnlCol + '">' + pnlStr + '</span>' : '');
        }}

        rail.appendChild(card);
        requestAnimationFrame(function() {{
          requestAnimationFrame(function() {{ card.classList.add('cc-show'); }});
        }});

        // Handle countdown for event callouts
        if (isEvent && cfg.countdown > 0) {{
          var cdEl = card.querySelector('[id^="cc-cd-"]');
          var _end = Date.now() + cfg.countdown * 1000;
          (function _tick() {{
            if (!cdEl) return;
            var rem = Math.max(0, Math.round((_end - Date.now()) / 1000));
            cdEl.textContent = rem > 0 ? rem + 's' : 'NOW';
            if (rem > 0) requestAnimationFrame(_tick);
          }})();
        }}

        // Linger then CRT-off exit
        var linger = isEvent ? Math.max(3000, (cfg.countdown||0)*1000 + 1500) : 4500;
        setTimeout(function() {{
          card.classList.remove('cc-show');
          card.classList.add('cc-exit');
          setTimeout(function() {{ if (card.parentNode) card.parentNode.removeChild(card); }}, 600);
        }}, linger);
      }}

      window._fireCallout = function(sym, price, pnl, col, countdown) {{
        _spawnCallout({{ sym:sym, price:price, pnl:pnl, col:col||'#ff3366', countdown:countdown||0 }});
      }};
      window._fireEventCallout = function(label, col, countdown) {{
        _spawnCallout({{ sym:label, col:col, countdown:countdown||0, isEvent:true }});
      }};

      // ── STRATEGIES slot ───────────────────────────────────────
      // Badge definitions — glyph + glow color per strategy archetype
      var _STRAT_BADGES = {{
        'momentum':   {{ glyph:'▲▲', color:'#00e5ff', label:'Momentum',  desc:'JT 12-1 price momentum · NYSE equities' }},
        'crypto':     {{ glyph:'◈',  color:'#e040fb', label:'Crypto',    desc:'Crypto positions pipeline' }},
        'daytrader':  {{ glyph:'⊕',  color:'#b2ff59', label:'Daytrader', desc:'Intraday ORB · VWAP · RVOL' }},
        'reversion':  {{ glyph:'⇌',  color:'#ff9900', label:'Mean Rev',  desc:'Statistical mean reversion' }},
        'sentiment':  {{ glyph:'◉',  color:'#ff4081', label:'Sentiment', desc:'Alt data · earnings · insider flow' }},
        'volatility': {{ glyph:'⚡', color:'#ff6b35', label:'Volatility',desc:'VIX-based dynamic sizing' }},
        'factor':     {{ glyph:'✦',  color:'#ffd740', label:'Factor',    desc:'Fama-French multi-factor' }},
        'macro':      {{ glyph:'≋',  color:'#00bcd4', label:'Macro',     desc:'Regime · sector rotation' }},
        'ensemble':   {{ glyph:'❋',  color:'#ffffff', label:'Ensemble',  desc:'Meta-allocator across strategies' }},
      }};

      var _stratDropOpen = false;
      window._toggleStratDropdown = function() {{
        _stratDropOpen = !_stratDropOpen;
        var dd = document.getElementById('strat-dropdown');
        if (!dd) return;
        if (_stratDropOpen) {{
          _renderStratDropdown();
          var slot = document.getElementById('ss-exposure');
          if (slot) {{
            var r = slot.getBoundingClientRect();
            dd.style.top  = (r.bottom + 4) + 'px';
            dd.style.right = (window.innerWidth - r.right) + 'px';
            dd.style.left = 'auto';
          }}
          dd.style.display = 'block';
          setTimeout(function() {{
            document.addEventListener('click', function _csd(e) {{
              if (!dd.contains(e.target) && e.target.id !== 'ss-exposure') {{
                _stratDropOpen = false; dd.style.display = 'none';
                document.removeEventListener('click', _csd);
              }}
            }});
          }}, 10);
        }} else {{
          dd.style.display = 'none';
        }}
      }};

      function _renderStratDropdown() {{
        var items = document.getElementById('strat-dropdown-items');
        if (!items) return;
        var counts = window._etStratCounts ? window._etStratCounts() : {{}};
        var html = '';
        // Active strategies first, then future ones dimmed
        var allKeys = ['momentum','crypto','daytrader','reversion','sentiment','volatility','factor','macro','ensemble'];
        allKeys.forEach(function(key) {{
          var b = _STRAT_BADGES[key]; if (!b) return;
          var n = counts[key] || 0;
          var active = n > 0;
          var dimAlpha = active ? '1' : '0.28';
          var glowStyle = active ? 'filter:drop-shadow(0 0 6px '+b.color+');' : '';
          html += '<div style="display:flex;align-items:center;gap:10px;padding:7px 14px;border-bottom:1px solid rgba(148,0,255,.08);opacity:'+dimAlpha+'">'
            + '<span style="font-size:14px;'+glowStyle+'color:'+b.color+';flex-shrink:0;width:20px;text-align:center">'+b.glyph+'</span>'
            + '<div style="min-width:0;flex:1">'
            + '<div style="font-size:8px;letter-spacing:.12em;color:'+(active?b.color:'rgba(255,255,255,.5)')+';'+(active?'text-shadow:0 0 8px '+b.color+';':'')+';font-weight:700">'+b.label+'</div>'
            + '<div style="font-size:7px;color:rgba(255,255,255,.35);margin-top:1px">'+b.desc+'</div>'
            + '</div>'
            + '<span style="margin-left:auto;font-size:11px;font-weight:700;color:'+(active?b.color:'rgba(255,255,255,.2)')+';'+(active?'text-shadow:0 0 8px '+b.color:'')+'">'+( active ? n : '—' )+'</span>'
            + '</div>';
        }});
        items.innerHTML = html;
      }}

      function _updateExposureSlot() {{
        var counts = window._etStratCounts ? window._etStratCounts() : {{}};
        var activeStrats = Object.keys(counts).filter(function(k) {{ return counts[k] > 0; }}).length;
        if (activeStrats === 0) {{ _ssSet('ss-exposure-st', '', '—'); return; }}
        _ssSet('ss-exposure-st', 'ss-active', activeStrats + '');
      }}

      // ── $/HR slot — dollar volume traded per hour ─────────────
      var _tradeVolTs = [];   // {{ts, val}} for last-hour fills
      window._recordTradeVol = function(fillAmt) {{
        var now = Date.now();
        _tradeVolTs.push({{ts: now, val: Math.abs(fillAmt)}});
        _tradeVolTs = _tradeVolTs.filter(function(x) {{ return x.ts > now - 3600000; }});
      }};
      function _updateTphSlot() {{
        var now = Date.now();
        _tradeVolTs = _tradeVolTs.filter(function(x) {{ return x.ts > now - 3600000; }});
        var total = _tradeVolTs.reduce(function(s, x) {{ return s + x.val; }}, 0);
        if (total < 1) {{ _ssSet('ss-tph-st', '', '—'); return; }}
        var fmt = total >= 1000 ? '$' + (total/1000).toFixed(1) + 'k' : '$' + Math.round(total);
        _ssSet('ss-tph-st', 'ss-active', fmt + '/hr');
      }}

      // ── Orb-side batch P&L popup ──────────────────────────────
      var _orbPopupTimer = null;
      window._orbBatchPnl = function(pnl) {{
        var popup = document.getElementById('orb-batch-popup');
        var canvas = document.getElementById('pulse-canvas');
        if (!popup || !canvas) return;
        var rect = canvas.getBoundingClientRect();
        var ma = document.getElementById('main-area');
        var maRect = ma ? ma.getBoundingClientRect() : rect;
        var orbX = (window._navOrbFracX || 0.5) * rect.width;
        var orbY = (window._navOrbFracY || 0.5) * rect.height;
        // Place popup left of orb; drift animation carries it further left
        var popX = orbX - 70;
        var popY = orbY;
        popup.style.left      = (rect.left - maRect.left + popX) + 'px';
        popup.style.top       = (rect.top  - maRect.top  + popY) + 'px';
        popup.style.animation = 'none';
        void popup.offsetWidth; // force reflow to restart animation
        popup.style.animation = 'orb-popup-drift 5s ease-in forwards';
        var isPos = pnl >= 0;
        popup.style.color = isPos ? '#00ff9d' : '#ff3366';
        popup.textContent = (isPos ? '+$' : '-$') + Math.abs(pnl).toLocaleString('en-US', {{minimumFractionDigits:2,maximumFractionDigits:2}});
        popup.style.opacity = '1';
        if (_orbPopupTimer) clearTimeout(_orbPopupTimer);
        _orbPopupTimer = setTimeout(function() {{
          popup.style.opacity = '0';
        }}, 4000);
      }};

      // ── System health tracking ────────────────────────────────
      var _apiReqTs = [];
      var _lastFetchLatency = null;
      var _dbOk = true;
      var _origFetch = window.fetch;
      window.fetch = function() {{
        var t0 = Date.now();
        _apiReqTs.push(t0);
        _apiReqTs = _apiReqTs.filter(function(t){{ return t > t0 - 60000; }});
        var p = _origFetch.apply(this, arguments);
        p.then(function() {{
          _lastFetchLatency = Date.now() - t0;
          _dbOk = true;
        }}).catch(function() {{ _dbOk = false; }});
        return p;
      }};

      function _updateSysHealth() {{
        // Market data connected
        var mktAge = window._lastLivePriceMs ? (Date.now() - window._lastLivePriceMs) : Infinity;
        var mdDot = document.getElementById('sysh-mktdata');
        var mdVal = document.getElementById('sysh-mktdata-val');
        if (mdDot) mdDot.className = 'sysh-dot ' + (mktAge < 45000 ? 'ok' : mktAge < 120000 ? 'warn' : 'dead');
        if (mdVal) mdVal.textContent = mktAge < 45000 ? 'LIVE' : mktAge < 120000 ? Math.round(mktAge/1000)+'s ago' : 'LOST';

        // DB connected
        var dbDot = document.getElementById('sysh-db');
        var dbVal = document.getElementById('sysh-db-val');
        if (dbDot) dbDot.className = 'sysh-dot ' + (_dbOk ? 'ok' : 'dead');
        if (dbVal) dbVal.textContent = _dbOk ? 'OK' : 'ERR';

        // Heartbeat (runner age) — reuse runner-age text with conditional color
        var hbEl = document.getElementById('runner-age');
        var syshHb = document.getElementById('sysh-hb');
        if (syshHb && hbEl) {{
          var _hbTxt = hbEl.textContent || '—';
          syshHb.textContent = _hbTxt;
          var _hbMins = _hbTxt === '<1m' ? 0 : parseFloat(_hbTxt);
          syshHb.style.color = isNaN(_hbMins) ? '' : _hbMins < 5 ? '#00ff9d' : _hbMins < 30 ? '#ffaa00' : '#ff3366';
        }}

        // Latency
        var latEl = document.getElementById('sysh-lat');
        if (latEl) {{
          var _lat = _lastFetchLatency;
          latEl.textContent = _lat !== null ? _lat + 'ms' : '—';
          latEl.style.color = _lat === null ? '' : _lat < 200 ? '#00ff9d' : _lat < 600 ? '#ffaa00' : '#ff3366';
        }}

        // API req/min
        var rpmEl = document.getElementById('sysh-rpm');
        if (rpmEl) {{
          var _rpm = _apiReqTs.length;
          rpmEl.textContent = _rpm + '/min';
          rpmEl.style.color = _rpm < 5 ? '#ff3366' : _rpm < 20 ? '#ffaa00' : '#00ff9d';
        }}

        // Clock drift: compare extrapolated DB time to system clock
        var driftEl = document.getElementById('sysh-drift');
        if (driftEl && window._lastKnownTs && window._lastLivePriceMs) {{
          var tsRaw = window._lastKnownTs; tsRaw = tsRaw.replace(' ','T'); if (/[+-]\d{{2}}$/.test(tsRaw)) tsRaw += ':00'; else if (!/Z|[+-]\d{{2}}:\d{{2}}$/.test(tsRaw)) tsRaw += 'Z';
          var dbNow = new Date(new Date(tsRaw).getTime() + (Date.now() - window._lastLivePriceMs));
          var driftMs = Math.abs(Date.now() - dbNow.getTime() - (Date.now() - window._lastLivePriceMs));
          // drift = difference between DB-derived time and real wall clock, ignoring network lag
          var sysMs = Date.now();
          var dbMs  = new Date(tsRaw).getTime();
          var elapsed = sysMs - window._lastLivePriceMs;
          var derived = dbMs + elapsed;
          var drift = Math.abs(sysMs - derived);
          driftEl.textContent = drift < 1000 ? '<1s' : Math.round(drift/1000) + 's';
          driftEl.style.color = drift < 5000 ? 'rgba(255,255,255,.55)' : '#ffaa00';
        }} else {{
          if (driftEl) driftEl.textContent = '—';
        }}
      }}

      // ── Master tick ───────────────────────────────────────────
      function _stratTick() {{
        _updateRunnerSlot();
        // TRADES slot updated via window._updateTradesSlot from _updateOrbMetrics
        // WALLET slot updated via window._updateWalletSlot from _updateNavDisplays
        _updateQueueSlot();
        _updateNavSlot();
        _updateExposureSlot();
        _updateTphSlot();
        _updateSysHealth();
      }}
      _stratTick();
      setInterval(_stratTick, 1000);
    }})();

    // (age bars now updated by _updateCard via _pollPositions every 2s)

  }})();

</script>

</body>
</html>"""


# ── Entry point ────────────────────────────────────────────────────────────────

def render() -> None:
    st.markdown("""
    <style>
    /* Hide Streamlit chrome */
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    [data-testid="stSidebar"],
    [data-testid="collapsedControl"],
    #MainMenu, footer { display: none !important; }

    /* Zero padding on all containers */
    section[data-testid="stMain"],
    section[data-testid="stMain"] > div,
    [data-testid="stMainBlockContainer"],
    div[class*="block-container"] {
        padding: 0 !important;
        margin: 0 !important;
        max-width: 100% !important;
    }
    iframe { display: block !important; border: none !important; }
    </style>
    """, unsafe_allow_html=True)

    try:
        data = _load_chart_data()
    except Exception as e:
        st.error(f"DB connection failed: {e}")
        return

    html = _build_daw_html(data)
    components.html(html, height=900, scrolling=False)

    # 0-height shim: runs in a sibling iframe, finds the main chart iframe in
    # the parent Streamlit page, and sets its height attribute to the true
    # browser window height — same-origin so no cross-origin restriction.
    _resizer = """
    <script>
    (function() {
        function resize() {
            try {
                var p = window.parent;
                var doc = p.document;
                // Bottom: manage-app-button (44px) + generous buffer so nothing clips
                var manageBtn = doc.querySelector('[data-testid="manage-app-button"]');
                var bottomH = manageBtn ? Math.ceil(manageBtn.getBoundingClientRect().height) + 64 : 112;
                // Top: strip Streamlit padding and measure stMain top offset
                var stMain = doc.querySelector('[data-testid="stMain"]');
                if (stMain) {
                    stMain.style.paddingTop    = '0px';
                    stMain.style.paddingBottom = '0px';
                }
                var stBlock = doc.querySelector('[data-testid="stMainBlockContainer"]') || doc.querySelector('.block-container');
                if (stBlock) { stBlock.style.paddingTop = '0px'; stBlock.style.paddingBottom = '0px'; stBlock.style.maxWidth = '100%'; }
                var topH = stMain ? Math.ceil(stMain.getBoundingClientRect().top) : 0;
                if (topH < 0) topH = 0;
                var h = p.innerHeight - topH - bottomH;
                if (h < 300) h = p.innerHeight - 116;
                // Resize the main chart iframe (the biggest one)
                var biggest = null, biggestH = 0;
                doc.querySelectorAll('iframe').forEach(function(f) {
                    if (f !== window.frameElement && f.offsetHeight > biggestH) {
                        biggest = f; biggestH = f.offsetHeight;
                    }
                });
                if (biggest) {
                    biggest.setAttribute('height', h);
                    biggest.style.height = h + 'px';
                }
            } catch(e) {}
        }
        resize();
        [100, 400, 900, 2000].forEach(function(ms) { setTimeout(resize, ms); });
        window.parent.addEventListener('resize', resize);
    })();
    </script>
    """
    components.html(_resizer, height=0, scrolling=False)

    # ── Alpaca order bridge ────────────────────────────────────────────────────
    # A 0-height shim in the parent frame catches postMessage from the main
    # iframe and stores the payload in session_state so Python can act on it.
    _order_shim = """
    <script>
    window.addEventListener('message', function(e) {
        var d = e.data;
        if (!d || d.type !== 'tnd_order') return;
        // Write into a hidden Streamlit number input to trigger a rerun
        var inp = window.parent.document.querySelector('#tnd-order-trigger input');
        if (inp) {
            inp.value = JSON.stringify(d);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
        }
    });
    </script>
    """
    components.html(_order_shim, height=0, scrolling=False)

    # Hidden widget that receives the order payload string
    import json as _json
    order_payload_str = st.text_input("", key="tnd_order_trigger",
                                      label_visibility="collapsed")
    st.markdown('<style>[data-testid="stTextInput"]:has(input[aria-label=""]) { display:none !important; }</style>',
                unsafe_allow_html=True)

    if order_payload_str:
        try:
            _order = _json.loads(order_payload_str)
            _sym      = _order.get("sym", "")
            _side     = _order.get("side", "buy")
            _notional = float(_order.get("notional", 0))
            _strategy = _order.get("strategy", "user")
            if _sym and _notional > 0:
                _submit_alpaca_order(_sym, _side, _notional, _strategy)
        except Exception:
            pass
