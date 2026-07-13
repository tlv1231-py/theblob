"""Command Center — full-screen DAW-style scrubbing timeline.

Three live tracks: portfolio value / SPY / QQQ.
Playhead at current date. Scroll to zoom, drag to pan.
Floating metric strip + terminal feed overlaid.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
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
#body{{flex:1;overflow:hidden;display:flex;flex-direction:column;padding:4px 0}}
.bt-e{{padding:4px 18px 3px;border-top:1px solid rgba(42,0,61,.3);flex-shrink:0}}
.bt-m{{font-size:13px;font-weight:600;line-height:1.4;
       white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.bt-s{{font-size:9px;color:#3a1a4a;margin-top:1px;letter-spacing:.04em}}
.ev-fill{{color:#ff00cc}}.ev-signal{{color:#00e5ff}}.ev-snapshot{{color:#9400ff}}
#cur{{padding:4px 18px;flex-shrink:0;color:#ff00cc;animation:bl 1s step-start infinite}}
@keyframes bl{{0%,100%{{opacity:1}}50%{{opacity:0}}}}
</style></head><body>
<div id="wrap">
  <div id="hdr"><div class="dot"></div>SYSTEM FEED</div>
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
            for r in pipe_rows:
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

                # Entry fills — earliest BUY per symbol
                entry_rows = s.execute(text("""
                    SELECT DISTINCT ON (symbol) symbol, fill_price, filled_at::date as entry_date
                    FROM fills WHERE side = 'BUY' AND symbol = ANY(:syms)
                    ORDER BY symbol, filled_at ASC
                """), {"syms": syms}).fetchall()
                entry_map = {
                    r.symbol: {"price": float(r.fill_price), "date": str(r.entry_date)}
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
    port  = data["portfolio"]
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

    _TICKER_PALETTE = ["#00e5ff","#9400ff","#ff9900","#e040fb","#40c4ff","#b2ff59","#ff6b35","#00ffcc"]
    _SYSTEM_SYMS = {"PIPELINE", "PORTFOLIO", "RUN", "INGEST", "SIGNAL", "HOLD",
                    "SNAPSHOT", "PNL", "NAV", "UPDATE", "DATA", "START", "COMPLETE", "VETO"}

    def _tc(sym: str) -> str:
        if not sym or sym.upper() in _SYSTEM_SYMS:
            return "#f0e0ff"
        return _TICKER_PALETTE[hash(sym) % len(_TICKER_PALETTE)]

    def _ts(sym: str) -> str:
        """Wrap a ticker symbol in its color span."""
        return f'<span style="color:{_tc(sym)};font-weight:700">{sym}</span>'

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

        # Convert UTC → NYC (ET = UTC-5 standard, UTC-4 daylight)
        if len(ts_raw) >= 16:
            try:
                from datetime import timezone as _tz, timedelta as _tdd
                _utc_dt = _dt.fromisoformat(ts_raw.replace("Z","").split(".")[0])
                import time as _time_mod
                _is_dst = bool(_time_mod.daylight) and bool(_time_mod.localtime().tm_isdst)
                _et_offset = -4 if True else -5  # EDT (summer) always for NYC
                _et_dt = _utc_dt + _tdd(hours=_et_offset)
                hhmm = _et_dt.strftime("%H:%M")
            except Exception:
                hhmm = ts_raw[11:16]
        else:
            hhmm = ""

        tag = ev.get("tag", "")
        nav_col = None
        if tag in ("NAV", "UPDATE", "SNAPSHOT"):
            curr = _snap_vals[_snap_idx] if _snap_idx < len(_snap_vals) else None
            prev = _snap_vals[_snap_idx - 1] if 0 < _snap_idx <= len(_snap_vals) else None
            nav_col = "#00ff9d" if (prev is None or curr is None or curr >= prev) else "#ff3366"
            if _snap_idx < len(_snap_vals):
                _snap_idx += 1

        prose = _humanize(ev, nav_col)

        is_newest = (_ev_i == _last_ev_i)
        tw = ' id="te-newest" style="opacity:0;color:#00ff41;text-shadow:0 0 8px rgba(0,255,65,.6)"' if is_newest else ''
        term_rows += (
            f'<div class="te"{tw}>'
            f'<span class="te-ts">{hhmm}&nbsp;&nbsp;</span>'
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

    # Build equity positions map for JS satellites
    import json as _json
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

    pos_cards = ""
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

        pos_cards += (
            f'<div class="pos-card pc-eq pos-card-active" data-sym="{p["sym"]}"'
            f' style="border-left:3px solid {tcol}">'
            f'<span class="pos-corner tl" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner tr" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner bl" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner br" style="border-color:{tcol}"></span>'
            # Row 1: sym + badge + value
            f'<div class="pc-row1">'
            f'  <span class="pc-sym" style="color:{tcol}">{p["sym"]}</span>'
            f'  {badge_html}'
            f'  <span class="pc-val">${p["value"]:,.0f}</span>'
            f'</div>'
            # Row 2: P&L
            f'<div class="pc-pnl" style="color:{pnl_col}">'
            f'  {pnl_arrow} {pnl_sign}${abs(epnl):,.0f}'
            f'  <span class="pc-pnl-pct">({epct:+.1f}%)</span>'
            f'</div>'
            # Proximity bar
            f'{prox_bar}'
            # Row 3: hold timer + entry info
            f'<div class="pc-meta">'
            f'  <span class="pc-days" data-days="{days}">⏱ {days} {day_lbl}</span>'
            f'  <span class="pc-entry">entered {entry_fmt} · {edate_fmt}</span>'
            f'</div>'
            f'<div class="pc-status {"pc-status-hold" if p["in_signal"] else "pc-status-sell"}">'
            f'  {p["hold_text"]}'
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
    spy_dates_j   = json.dumps(spy["dates"])
    spy_norm_j    = json.dumps(spy_norm)
    qqq_dates_j   = json.dumps(qqq["dates"])
    qqq_norm_j    = json.dumps(qqq_norm)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{
  background:#060008; overflow:hidden;
  font-family:Consolas,'Courier New',monospace;
  color:#f0e0ff; height:100vh; width:100vw;
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
#chart {{ position:absolute; inset:0; width:100%; height:100%; }}
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
  background:linear-gradient(270deg,rgba(1,0,8,.88) 0%,rgba(1,0,8,.6) 80%,transparent 100%);
  -webkit-mask-image:linear-gradient(to bottom,transparent 0%,black 12%,black 88%,transparent 100%);
  mask-image:linear-gradient(to bottom,transparent 0%,black 12%,black 88%,transparent 100%);
}}
#pos-left {{ flex:0 0 auto !important; overflow:hidden; width:0; transition:width .4s cubic-bezier(.22,1,.36,1); }}
#pos-left .pos-section-label {{ display:none; }}
#pos-overlay #particle-canvas {{ position:absolute; inset:0; pointer-events:none; z-index:1; width:100%; height:100%; }}

/* ── Top bar ── */
.topbar {{
  height:44px; flex-shrink:0;
  background:rgba(6,0,8,.9); border-bottom:1px solid #2a003d;
  backdrop-filter:blur(12px);
  display:flex; align-items:center; padding:0 20px; gap:14px; z-index:10;
  overflow:hidden;
}}
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
  0%   {{ opacity:.22; background:radial-gradient(ellipse at 50% 50%, rgba(0,255,157,.35) 0%, rgba(0,255,157,0) 70%); }}
  100% {{ opacity:0; }}
}}
@keyframes veil-win {{
  0%   {{ opacity:.28; background:radial-gradient(ellipse at 50% 50%, rgba(0,255,157,.4) 0%, rgba(0,255,157,0) 70%); }}
  100% {{ opacity:0; }}
}}
@keyframes veil-loss {{
  0%   {{ opacity:.28; background:radial-gradient(ellipse at 50% 50%, rgba(255,51,102,.4) 0%, rgba(255,51,102,0) 70%); }}
  100% {{ opacity:0; }}
}}
#trade-veil.veil-entry {{ animation:veil-entry .5s ease-out forwards; }}
#trade-veil.veil-win   {{ animation:veil-win   .5s ease-out forwards; }}
#trade-veil.veil-loss  {{ animation:veil-loss  .5s ease-out forwards; }}
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
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap');
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
#pos-left {{ border-right:none; }}
/* Crypto cards — transparent column, left accent stripe only */
#pos-left .pos-card {{
  border-left:3px solid; border-right:none; border-top:none; border-bottom:1px solid rgba(13,0,32,.4);
  background:transparent !important; backdrop-filter:none !important;
}}
#pos-overlay {{ transition:width .4s cubic-bezier(.22,1,.36,1); }}
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
/* ── Orb metrics panel — anchored center, dot is always centered ── */
#pnl-float {{
  position:absolute; pointer-events:none;
  left:50%; top:42%; transform:translate(-50%,-50%);
  background:rgba(4,0,10,.82); border:1px solid #2a003d; border-top:2px solid #ff00cc;
  backdrop-filter:blur(12px);
  padding:10px 18px 12px;
  opacity:0; transition:opacity .4s ease;
}}
#pnl-float.visible {{ opacity:1; }}
/* three-column metric layout */
#pnl-float-cols {{
  display:flex; align-items:flex-start; gap:20px;
}}
.pnl-col {{
  display:flex; flex-direction:column; align-items:center; gap:2px; min-width:64px;
}}
.pnl-col-center {{ min-width:120px; }}
.pnl-col-label {{
  font-family:Consolas,monospace; font-size:6.5px; letter-spacing:.22em;
  color:rgba(190,150,255,.6); text-transform:uppercase; white-space:nowrap;
}}
.pnl-col-val {{
  font-family:Consolas,monospace; font-size:16px; font-weight:700;
  color:#ff00cc; letter-spacing:.02em; white-space:nowrap;
}}
.pnl-col-center .pnl-col-val {{ font-size:26px; }}
.pnl-combo-chip {{
  font-family:Consolas,monospace; font-size:11px; font-weight:700;
  opacity:0; transition:opacity .15s; min-height:14px;
  text-shadow:0 0 8px currentColor;
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
.pos-card {{ padding:6px 12px 7px; cursor:default; position:relative; overflow:hidden;
             background:rgba(6,0,8,.38); backdrop-filter:blur(2px); border-bottom:1px solid #0d0020; }}

/* ── Equity position cards (right panel) ── */
.pc-eq {{
  padding:11px 12px 10px 14px !important;
  background:rgba(6,0,18,.62) !important;
  backdrop-filter:blur(6px) !important;
  border-bottom:1px solid rgba(255,255,255,.03) !important;
  border-left-width:2px !important;
  transition:background .4s ease;
}}
.pc-eq:hover {{ background:rgba(10,0,28,.72) !important; }}
.pc-eq .pos-corner {{ display:none; }}
.pc-row1 {{
  display:flex; align-items:baseline; gap:6px; margin-bottom:5px;
}}
.pc-sym {{
  font-family:Consolas,monospace; font-size:14px; font-weight:800;
  letter-spacing:.06em; flex-shrink:0;
}}
.pc-badge {{
  font-size:6px; font-weight:700; letter-spacing:.18em; padding:2px 6px 1px;
  border-radius:1px; flex-shrink:0; font-family:Consolas,monospace;
  text-transform:uppercase;
}}
.pc-badge-hold {{
  background:transparent; color:rgba(0,180,110,.55);
  border:1px solid rgba(0,180,110,.2);
}}
.pc-badge-sell {{
  background:transparent; color:rgba(220,160,0,.6);
  border:1px solid rgba(220,160,0,.25);
}}
.pc-val {{
  margin-left:auto; font-family:Consolas,monospace; font-size:13px;
  font-weight:700; color:rgba(230,220,255,.9); letter-spacing:.01em;
  font-variant-numeric:tabular-nums;
}}
.pc-pnl {{
  font-family:Consolas,monospace; font-size:11px; font-weight:600;
  letter-spacing:.02em; margin-bottom:7px; font-variant-numeric:tabular-nums;
  opacity:.9;
}}
.pc-pnl-pct {{
  font-size:9.5px; opacity:.65; margin-left:5px; font-weight:400;
}}
/* Proximity bar — range navigator, not danger meter */
.pc-prox-wrap {{
  position:relative; margin-bottom:6px;
}}
.pc-prox-labels {{
  display:flex; justify-content:space-between; align-items:center;
  position:relative; height:11px; margin-bottom:3px;
}}
.pc-prox-stop,.pc-prox-tgt {{
  font-family:Consolas,monospace; font-size:6.5px; color:rgba(140,110,170,.5);
  letter-spacing:.04em;
}}
.pc-prox-cur {{
  position:absolute; transform:translateX(-50%);
  font-family:Consolas,monospace; font-size:7px; font-weight:700;
  color:rgba(255,255,255,.65); white-space:nowrap;
}}
.pc-prox-track {{
  position:relative; height:2px; background:rgba(255,255,255,.05);
  border-radius:1px; overflow:visible;
}}
.pc-prox-fill {{
  height:100%; border-radius:1px; transition:width 1.2s ease; opacity:.7;
}}
.pc-prox-dot {{
  position:absolute; top:50%; transform:translate(-50%,-50%);
  width:6px; height:6px; border-radius:50%;
  border:1px solid rgba(0,0,0,.5);
  transition:left 1.2s ease;
}}
/* Meta row */
.pc-meta {{
  display:flex; justify-content:space-between; align-items:center;
  margin-top:5px; margin-bottom:4px;
}}
.pc-days {{
  font-family:Consolas,monospace; font-size:8.5px; color:rgba(0,200,220,.55);
  letter-spacing:.04em;
}}
.pc-entry {{
  font-family:Consolas,monospace; font-size:7px; color:rgba(140,110,170,.45);
  letter-spacing:.02em;
}}
/* Status line */
.pc-status {{
  font-size:7px; letter-spacing:.06em; padding-top:4px;
  border-top:1px solid rgba(255,255,255,.04);
  font-family:Consolas,monospace; line-height:1.5; text-transform:uppercase;
}}
.pc-status-hold {{ color:rgba(0,170,100,.4); }}
.pc-status-sell {{ color:rgba(210,160,0,.45); }}

/* ── Crypto cards — calm, data-dense ── */
#pos-left .pos-card {{
  padding:7px 10px 6px 11px;
  background:rgba(6,0,18,.5) !important; backdrop-filter:blur(4px) !important;
  border-left:2px solid; border-right:none; border-top:none;
  border-bottom:1px solid rgba(255,255,255,.03);
  transition:background .3s ease;
}}
#pos-left .pos-card:hover {{ background:rgba(10,0,28,.65) !important; }}
#pos-left .pos-corner {{ display:none; }}
#pos-left .pos-acq-flash {{ font-size:7px; letter-spacing:.18em; }}
#pos-left .pos-top {{
  display:flex; justify-content:space-between; align-items:baseline; gap:4px; line-height:1.3;
}}
#pos-left .pos-sym {{ font-size:11px; font-weight:800; letter-spacing:.05em; }}
#pos-left .pos-qty {{ display:none; }}
#pos-left .pos-val {{
  font-size:8px; font-weight:600; font-variant-numeric:tabular-nums;
  color:rgba(255,255,255,.38); margin-left:auto;
}}
#pos-left .pos-hold {{
  font-size:7px; color:rgba(200,180,255,.22); margin-top:2px; letter-spacing:.02em;
}}
#pos-left .pos-prox-wrap {{ margin-top:4px; padding:0; }}
#pos-left .pos-prox-track {{ height:2px; background:rgba(255,255,255,.06); }}
#pos-left .pos-prox-fill {{
  transition:width .8s cubic-bezier(.22,1,.36,1), background .8s;
}}
#pos-left .pos-prox-cursor {{ width:5px; height:5px; }}
#pos-left .pos-prox-labels {{ display:none; }}
#pos-left .pos-age-bar {{ margin-top:3px; }}

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
/* ── Capital floating popup ── */
#capital-fab {{
  position:fixed; bottom:52px; right:16px; z-index:300;
  background:rgba(6,0,8,.92); border:1px solid #2a003d; border-top:2px solid #ff00cc;
  color:#ff00cc; font:700 8px Consolas,monospace; letter-spacing:.2em;
  padding:6px 10px; cursor:pointer;
  text-shadow:0 0 8px rgba(255,0,204,.5);
  transition:all .2s; user-select:none;
}}
#capital-fab:hover {{ background:rgba(255,0,204,.1); box-shadow:0 0 16px rgba(255,0,204,.25); }}
#capital-popup {{
  position:fixed; bottom:84px; right:16px; z-index:299;
  width:240px; background:#00000a; border:1px solid #1a0028; border-top:2px solid #ff00cc;
  display:flex; flex-direction:column; overflow:hidden;
  transform:translateY(20px); opacity:0; pointer-events:none;
  transition:transform .35s cubic-bezier(.22,1,.36,1), opacity .25s ease;
  box-shadow:0 -8px 40px rgba(255,0,204,.15);
}}
#capital-popup.open {{ transform:translateY(0); opacity:1; pointer-events:all; }}
#dep-body {{ flex:1; overflow-y:auto; scrollbar-width:none; padding:8px 12px; display:flex; flex-direction:column; gap:8px; }}
#dep-body::-webkit-scrollbar {{ display:none; }}
.dep-tabs {{ display:flex; gap:0; }}
.dep-tab {{
  flex:1; padding:5px 0; font-size:9px; letter-spacing:.16em; text-align:center;
  cursor:pointer; border:1px solid #1a0028; color:#4a2a6a;
  background:#000; transition:all .15s;
}}
.dep-tab.active {{ color:#ff00cc; border-color:#ff00cc; background:rgba(255,0,204,.06);
  text-shadow:0 0 8px rgba(255,0,204,.5); }}
.dep-amt-row {{ display:flex; gap:6px; align-items:center; }}
.dep-input {{
  flex:1; background:#000; border:1px solid #1a0028; color:#f0e0ff;
  font-family:Consolas,monospace; font-size:13px; padding:5px 8px;
  outline:none; letter-spacing:.02em;
}}
.dep-input:focus {{ border-color:#ff00cc; box-shadow:0 0 8px rgba(255,0,204,.2); }}
.dep-btn {{
  padding:5px 12px; background:transparent; border:1px solid #ff00cc;
  color:#ff00cc; font-family:Consolas,monospace; font-size:9px; letter-spacing:.18em;
  cursor:pointer; transition:all .15s;
  text-shadow:0 0 6px rgba(255,0,204,.4);
}}
.dep-btn:hover {{ background:rgba(255,0,204,.1); }}
.dep-note {{ font-size:8px; color:#2a0040; letter-spacing:.04em; line-height:1.5; }}
.dep-hist-hdr {{ font-size:7px; letter-spacing:.28em; color:#2a0040; text-transform:uppercase; border-top:1px solid #0a0018; padding-top:8px; }}
.dep-hist-item {{ font-size:10px; color:#4a2a6a; display:flex; gap:6px; }}
.dep-hist-amt {{ font-weight:700; }}
.dep-hist-date {{ color:#1a0028; font-size:9px; margin-left:auto; }}
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
/* ── Live proximity meter ── */
.pos-prox-wrap {{
  margin-top:5px; padding:0 0 2px;
}}
.pos-prox-track {{
  position:relative; height:4px; border-radius:2px; overflow:visible;
  background:rgba(255,255,255,.06);
}}
.pos-prox-fill {{
  position:absolute; left:0; top:0; height:100%; border-radius:2px;
  transition:width .6s cubic-bezier(.22,1,.36,1), background .6s;
  background:linear-gradient(90deg,rgba(255,51,102,.6) 0%,rgba(255,153,0,.7) 50%,rgba(0,255,157,.8) 100%);
  background-size:200% 100%;
}}
.pos-prox-cursor {{
  position:absolute; top:50%; transform:translate(-50%,-50%);
  width:6px; height:6px; border-radius:50%;
  transition:left .6s cubic-bezier(.22,1,.36,1), background .6s, box-shadow .6s;
  background:#fff; box-shadow:0 0 6px #fff;
}}
@keyframes prox-danger {{
  0%,100%{{box-shadow:0 0 4px #ff3366,0 0 10px rgba(255,51,102,.5)}}
  50%{{box-shadow:0 0 8px #ff3366,0 0 20px rgba(255,51,102,.8)}}
}}
@keyframes prox-target {{
  0%,100%{{box-shadow:0 0 4px #00ff9d,0 0 10px rgba(0,255,157,.5)}}
  50%{{box-shadow:0 0 8px #00ff9d,0 0 20px rgba(0,255,157,.8)}}
}}
.pos-prox-cursor.danger {{ background:#ff3366; animation:prox-danger .8s ease-in-out infinite; }}
.pos-prox-cursor.target {{ background:#00ff9d; animation:prox-target .8s ease-in-out infinite; }}
.pos-prox-labels {{
  display:flex; justify-content:space-between; align-items:center;
  margin-top:2px; font-size:6px; letter-spacing:.05em; color:#2a1a4a;
}}
.pos-prox-live {{
  text-align:center; font-size:7px; font-weight:700; letter-spacing:.04em;
  font-family:Consolas,monospace; transition:color .4s;
}}
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
@keyframes card-enter {{
  0%   {{ opacity:0; transform:scaleY(0); filter:brightness(5) saturate(0); }}
  20%  {{ opacity:1; transform:scaleY(1); filter:brightness(3) saturate(0); }}
  60%  {{ filter:brightness(2) saturate(2); }}
  100% {{ filter:brightness(1) saturate(1); }}
}}
@keyframes card-exit-target {{
  0%   {{ transform:translateX(0); filter:brightness(1); background:transparent; }}
  20%  {{ filter:brightness(4); background:rgba(0,255,157,.1); }}
  100% {{ transform:translateX(110%); opacity:0; filter:brightness(2); }}
}}
@keyframes card-exit-stop {{
  0%   {{ transform:scale(1); filter:brightness(1); }}
  20%  {{ filter:brightness(5); background:rgba(255,51,102,.15); }}
  100% {{ transform:scale(0); opacity:0; max-height:0; padding:0; }}
}}
@keyframes card-exit-timeout {{
  0%   {{ transform:translateY(0); opacity:1; }}
  20%  {{ background:rgba(255,153,0,.08); filter:brightness(2); }}
  100% {{ transform:translateY(-28px); opacity:0; max-height:0; padding:0; }}
}}
@keyframes card-exit-rev {{
  0%   {{ opacity:1; filter:brightness(1); }}
  30%  {{ filter:brightness(3) hue-rotate(180deg); background:rgba(0,229,255,.08); }}
  100% {{ opacity:0; max-height:0; padding:0; }}
}}
/* card-entering — JS orchestrates phases; CSS provides initial clip */
.pos-card-entering {{
  clip-path:inset(0 0 100% 0);
  animation:card-clip-reveal .32s cubic-bezier(.22,1,.36,1) forwards;
  transform-origin:top;
  box-shadow:0 0 0 1px rgba(0,180,255,0);
}}
@keyframes card-clip-reveal {{
  0%   {{ clip-path:inset(0 0 100% 0); box-shadow:0 0 0 1px rgba(0,180,255,0); filter:brightness(2.5) saturate(0); }}
  30%  {{ box-shadow:0 0 20px 2px rgba(0,180,255,.55), inset 0 0 12px rgba(0,180,255,.15); filter:brightness(1.8) saturate(1.5); }}
  70%  {{ clip-path:inset(0 0 0% 0); box-shadow:0 0 12px 1px rgba(0,180,255,.3); filter:brightness(1.2) saturate(1.2); }}
  100% {{ clip-path:inset(0 0 0% 0); box-shadow:none; filter:brightness(1) saturate(1); }}
}}
.pos-card-exiting  {{ animation:card-exit-stop .42s ease-in forwards; overflow:hidden; }}
.pos-card-exit-target  {{ animation:card-exit-target  .52s cubic-bezier(.55,0,1,.45) forwards; overflow:hidden; }}
.pos-card-exit-stop    {{ animation:card-exit-stop    .42s ease-in forwards; overflow:hidden; }}
.pos-card-exit-timeout {{ animation:card-exit-timeout .48s ease-in forwards; overflow:hidden; }}
.pos-card-exit-rev     {{ animation:card-exit-rev     .48s ease-out forwards; overflow:hidden; }}
/* ── PnL ghost — video-game exit ── */
@keyframes pnl-ghost-pop {{
  0%   {{ transform:scale(.3) translateY(0);    opacity:0; filter:brightness(3); }}
  18%  {{ transform:scale(1.4) translateY(-12px); opacity:1; filter:brightness(1.8); }}
  38%  {{ transform:scale(.88) translateY(-22px); opacity:1; filter:brightness(1.2); }}
  55%  {{ transform:scale(1.06) translateY(-34px); opacity:1; filter:brightness(1); }}
  80%  {{ transform:scale(1.0) translateY(-70px); opacity:.85; }}
  100% {{ transform:scale(.9) translateY(-115px); opacity:0; }}
}}
@keyframes pnl-particle {{
  0%   {{ transform:translate(0,0) scale(1); opacity:1; }}
  100% {{ transform:translate(var(--px),var(--py)) scale(0); opacity:0; }}
}}
@keyframes card-flash-exit {{
  0%   {{ box-shadow:inset 0 0 0 1px transparent; }}
  15%  {{ box-shadow:inset 0 0 0 2px var(--flash-col,#fff), 0 0 24px 4px var(--flash-col,#fff); filter:brightness(2.2); }}
  100% {{ box-shadow:inset 0 0 0 1px transparent; filter:brightness(1); }}
}}
.pnl-ghost {{
  position:fixed; pointer-events:none; z-index:9999;
  display:flex; flex-direction:column; align-items:center; gap:2px;
  animation:pnl-ghost-pop 1.1s cubic-bezier(.22,1,.36,1) forwards;
}}
.pnl-ghost .pg-sym {{
  font:600 8px Consolas,monospace; letter-spacing:.18em; opacity:.7; text-transform:uppercase;
}}
.pnl-ghost .pg-val {{
  font:800 28px/1 Consolas,monospace; letter-spacing:.04em;
  text-shadow:0 0 18px currentColor, 0 0 36px currentColor;
}}
.pnl-ghost .pg-label {{
  font:600 7px Consolas,monospace; letter-spacing:.3em; opacity:.55;
  text-transform:uppercase; margin-top:1px;
}}
.pnl-ghost .pg-price {{
  font:600 9px Consolas,monospace; letter-spacing:.08em; opacity:.75;
  margin-top:3px;
}}
.pnl-particle {{
  position:fixed; pointer-events:none; z-index:9998; border-radius:50%;
  animation:pnl-particle var(--dur,.6s) ease-out forwards;
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
</style>
</head>
<body>

<!-- flex child 1: topbar -->
<div class="topbar">
  <span class="wordmark">THE BLOB</span>
  <div class="pulse-dot"></div>
  <div id="wallet-selector" onclick="_cycleWallet()" title="Switch portfolio">
    <span id="wallet-mode-icon">◈</span>
    <span id="wallet-mode-label">PAPER</span>
    <span id="wallet-mode-chevron">▾</span>
  </div>
  <div id="strat-health" title="Strategy health">
    <div id="strat-health-dot"></div>
    <span id="strat-health-label">—</span>
  </div>
  <div class="spacer"></div>
  <div class="tb-stat">
    <span class="tb-stat-label">NAV</span>
    <span class="tb-stat-val" style="color:#ff00cc">{nav_str}</span>
  </div>
  <div class="tb-sep"></div>
  <div class="tb-stat">
    <span class="tb-stat-label">return</span>
    <span class="tb-stat-val" style="color:{ret_color}">{ret_str}</span>
  </div>
  <div class="tb-sep"></div>
  <div class="tb-stat">
    <span class="tb-stat-label">day P&amp;L</span>
    <span class="tb-stat-val" style="color:{'#00ff9d' if day_pnl >= 0 else '#ff3366'}">{dpnl_str}</span>
  </div>
  <div class="tb-sep"></div>
  <div class="tb-stat">
    <span class="tb-stat-label">sharpe</span>
    <span class="tb-stat-val" style="color:#00e5ff">{sharpe}</span>
  </div>
  <div class="tb-sep"></div>
  <div class="tb-stat">
    <span class="tb-stat-label">SPY</span>
    <span class="tb-stat-val" style="color:#00e5ff">{spy_latest}</span>
  </div>
  <div class="tb-sep"></div>
  <div class="tb-stat">
    <span class="tb-stat-label">QQQ</span>
    <span class="tb-stat-val" style="color:#9400ff">{qqq_latest}</span>
  </div>
  <div class="tb-sep"></div>
  <div class="tb-stat">
    <span class="tb-stat-label">win rate</span>
    <span class="tb-stat-val" id="hdr-winrate" style="color:#00e5ff">—</span>
  </div>
  <div class="tb-sep"></div>
  <div id="streak-chip">
    <span class="streak-label">streak</span>
    <span id="streak-val" class="streak-val" style="color:#3a1a5a">—</span>
  </div>
  <div class="tb-sep"></div>
  <div id="runner-health">
    <div id="runner-dot" class="warn"></div>
    <div>
      <div id="runner-age" style="color:#3a1a5a">—</div>
      <div id="runner-trades" class="runner-trades">0 trades today</div>
    </div>
  </div>
</div>
<!-- Cyberpunk cycle bar — orange, sits between header and chart -->
<div id="tracker-bar">
  <div id="run-progress-wrap">
    <span style="font:700 7px Consolas,monospace;letter-spacing:.22em;color:#ff6600;text-transform:uppercase;text-shadow:0 0 6px rgba(255,102,0,.6)">CYCLE</span>
    <div id="run-progress-track"><div id="run-progress-fill"></div></div>
    <span id="run-progress-label">—</span>
  </div>
</div>

<div id="daily-bar" style="display:none">
  <div id="daily-bar-fill" style="width:0%"></div>
  <span id="daily-bar-label"></span>
</div>

<!-- flex child 2: chart + floating overlays -->
<div id="main-area">
  <div id="chart"></div>
  <canvas id="ambient-canvas"></canvas>
  <canvas id="pulse-canvas"></canvas>
  <div id="trade-veil"></div>
  <div id="crosshair-overlay"><canvas id="xhair-canvas"></canvas></div>
  <div id="pnl-float">
    <div id="pnl-float-cols">
      <!-- TRADES -->
      <div class="pnl-col">
        <div class="pnl-col-label">TRADES</div>
        <div class="pnl-col-val" id="om-today">0</div>
        <div class="pnl-combo-chip" id="trades-combo-chip"></div>
      </div>
      <!-- TOTAL P&L (center, largest) -->
      <div class="pnl-col pnl-col-center">
        <div class="pnl-col-label">TOTAL P&amp;L</div>
        <div style="display:flex;align-items:baseline;gap:6px">
          <div id="total-pnl-val" class="pnl-col-val" data-raw="{_total_pnl}" style="color:{_pnl_col}">{_pnl_str}</div>
          <div id="batch-pnl-chip" class="pnl-combo-chip"></div>
        </div>
      </div>
      <!-- OPEN POS -->
      <div class="pnl-col">
        <div class="pnl-col-label">OPEN POS</div>
        <div class="pnl-col-val" id="om-openpos" style="color:#00e5ff">{n_positions}</div>
        <div class="pnl-combo-chip" id="pos-combo-chip"></div>
      </div>
    </div>
    <!-- hidden compat elements so existing JS refs don't break -->
    <span id="om-dpnl" style="display:none">{dpnl_str}</span>
    <span id="om-tph" style="display:none">—</span>
    <span id="om-winrate" style="display:none">—</span>
    <span id="om-streak-orb" style="display:none">—</span>
    <span id="total-pnl-sub" style="display:none">{_pnl_pct_str}</span>
  </div>
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
    <div class="panel-hdr"><div class="term-dot"></div>SYSTEM FEED</div>
    <div id="term-clock" class="te" style="flex-shrink:0;border-bottom:1px solid rgba(255,255,255,.06);padding-bottom:5px;margin-bottom:2px"></div>
    <div id="term-body">
      {term_rows}
    </div>
    <div id="feed-bottom-bar">
      <span id="feed-last-ago" style="font:700 7px Consolas,monospace;letter-spacing:.14em;color:#3a1a5a;flex:1">—</span>
      <button id="mute-btn" onclick="_toggleMute()" title="Toggle sound">
        <span id="mute-icon">♪</span>
        <span id="mute-label">ON</span>
      </button>
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
        <div class="pos-section-label">equity</div>
        <div id="pos-equity-section">{pos_cards}</div>
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

var portDates  = {port_dates_j};
var portValues = {port_values_j};
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
// Intraday sliding window — "now" always at center
var _CENTER_DAYS = 1;
var _HALF_WIN_MS = 45 * 60 * 1000;  // 45 min each side
function _intradayStart() {{ return new Date(Date.now() - _HALF_WIN_MS).toISOString(); }}
function _intradayEnd()   {{ return new Date(Date.now() + _HALF_WIN_MS).toISOString(); }}
var xStart = _intradayStart();
var xEnd   = _intradayEnd();

// Tight Y range for the visible window
function yRange(x0, x1) {{
  var minV = Infinity, maxV = -Infinity;
  var series = [
    [portDates, portValues],
    [spyDates,  spyNorm],
    [qqqDates,  qqqNorm],
  ];
  series.forEach(function(s) {{
    var dates = s[0], vals = s[1];
    for (var i=0; i<dates.length; i++) {{
      if ((!x0 || dates[i] >= x0) && (!x1 || dates[i] <= x1)) {{
        if (vals[i] < minV) minV = vals[i];
        if (vals[i] > maxV) maxV = vals[i];
      }}
    }}
  }});
  if (minV === Infinity) return [null, null];
  var pad = (maxV - minV) * 0.18 || 2000;
  return [minV - pad, maxV + pad];
}}

var yr = yRange(xStart, xEnd);

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
  // 20% annual target trajectory — replaces flat baseline (trace index 0)
  {{
    x: _tgt20Dates, y: _tgt20Vals,
    type:'scatter', mode:'lines',
    line:{{ color:'rgba(0,229,100,0.4)', width:1, dash:'dashdot' }},
    name:'20% TARGET',
    hovertemplate:'<b style="color:#00e564">TARGET $%{{y:,.0f}}</b><extra></extra>',
  }},
  {{
    x: spyDates, y: spyNorm,
    type:'scatter', mode:'lines',
    line:{{ color:'#00e5ff', width:1.5, dash:'dot' }},
    name:'SPY (norm)',
    hovertemplate:'<b style="color:#00e5ff">SPY $%{{y:,.0f}}</b><extra></extra>',
  }},
  {{
    x: qqqDates, y: qqqNorm,
    type:'scatter', mode:'lines',
    line:{{ color:'#9400ff', width:1.5, dash:'dot' }},
    name:'QQQ (norm)',
    hovertemplate:'<b style="color:#9400ff">QQQ $%{{y:,.0f}}</b><extra></extra>',
  }},
  // Portfolio on top — solid, brightest
  // Ghost glow — wide blurred trace drawn BELOW portfolio for depth
  {{
    x: portDates, y: portValues,
    type:'scatter', mode:'lines',
    line:{{ color:'rgba(255,0,204,0.18)', width:20 }},
    fill:'none',
    name:'ghost', hoverinfo:'skip', showlegend:false,
  }},
  // PORTFOLIO — main line with area fill (trace index 4)
  {{
    x: portDates, y: portValues,
    type:'scatter', mode:'lines',
    line:{{ color:'#ff00cc', width:3 }},
    fill:'tozeroy',
    fillcolor:'rgba(255,0,204,0.07)',
    name:'PORTFOLIO',
    hovertemplate:'<b style="color:#ff00cc">PORTFOLIO $%{{y:,.0f}}</b><extra></extra>',
  }},
  // HYSA 4.8% benchmark (trace index 5)
  {{
    x: _hysaDates, y: _hysaVals,
    type:'scatter', mode:'lines',
    line:{{ color:'rgba(255,200,0,0.3)', width:1, dash:'dash' }},
    name:'HYSA 4.8%',
    hovertemplate:'<b style="color:#ffc800">HYSA $%{{y:,.0f}}</b><extra></extra>',
  }},
  // Intraday "marked the book" values — live portfolio value within the day (index 6)
  {{
    x:[], y:[], name:'INTRADAY',
    type:'scatter', mode:'lines',
    line:{{ color:'rgba(255,0,204,.55)', width:1.5 }},
    hoverinfo:'skip', showlegend:false,
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
    range: xStart ? [xStart, xEnd] : undefined,
    showgrid:true, gridcolor:'rgba(42,0,61,0.5)', gridwidth:1,
    tickfont:{{ family:'Consolas', size:8, color:'#3a1a4a' }},
    tickformat:'%b %d', zeroline:false, showline:false, type:'date', fixedrange:false,
  }},
  yaxis:{{
    autorange:false,
    range: (function() {{
      var _v = {port_values_j};
      var _clean = _v.filter(function(x){{ return x > 0; }});
      if (!_clean.length) return [90000, 110000];
      var _lo = Math.min.apply(null, _clean), _hi = Math.max.apply(null, _clean);
      var _spread = Math.max(_hi - _lo, _lo * 0.004, 200);
      var _c = (_lo + _hi) / 2;
      return [_c - _spread * 0.7, _c + _spread * 0.7];
    }})(),
    showgrid:true, gridcolor:'rgba(42,0,61,0.5)', gridwidth:1,
    tickfont:{{ family:'Consolas', size:8, color:'#3a1a4a' }},
    tickformat:'$,.0f',
    zeroline:false, showline:false, fixedrange:true,
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

function toggleCapital() {{
  document.getElementById('capital-popup').classList.toggle('open');
}}

// ── Pulsing canvas dots ────────────────────────────────
var canvas = document.getElementById('pulse-canvas');
function resizeCanvas() {{ canvas.width=window.innerWidth; canvas.height=window.innerHeight; }}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

var pulseTargets = [];

// ── Orb state ─────────────────────────────────────────────────────────────────
var _orbFlash = {{ active: false, isEntry: true, t: 0, dur: 900 }};
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

window._orbTradeFlash = function(isEntry) {{
  _orbFlash.active = true;
  _orbFlash.isEntry = isEntry;
  _orbFlash.t = Date.now();
  _orbBurstCount = isEntry ? 6 : 5;
  // Spawn 5 shockwave rings staggered
  var portT = pulseTargets.find(function(t) {{ return t.rgb[0]===255 && t.rgb[2]===204; }});
  if (portT) {{
    try {{
      var fl = gd._fullLayout;
      var scx = fl.xaxis.l2p(fl.xaxis.d2l(portT.x)) + fl.margin.l;
      var scy = fl.yaxis.l2p(fl.yaxis.d2l(portT.y)) + fl.margin.t;
      if (isFinite(scx) && isFinite(scy)) {{
        var scol = isEntry ? [0,255,157] : [255,51,102];
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
    else flashRgb = _orbFlash.isEntry ? [0,255,157] : [255,51,102];
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
      var fl = gd._fullLayout;
      if (!fl || !fl.xaxis || !fl.yaxis) throw '';
      var _rawPcx = fl.xaxis.l2p(fl.xaxis.d2l(portT.x)) + fl.margin.l;
      var _rawPcy = fl.yaxis.l2p(fl.yaxis.d2l(portT.y)) + fl.margin.t;
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

      // ── Combo streak text above orb ───────────────────────────────────────
      if (_comboCount > 0) {{
        var comboCol = _comboCount>=10 ? '0,229,255' : _comboCount>=5 ? '255,170,0' : '255,0,204';
        var bounce   = Math.sin(phase*6)*2;
        var comboSize= Math.min(9 + _comboCount*0.8, 18);
        ctx.save();
        ctx.font = 'bold '+Math.round(comboSize)+'px Consolas';
        ctx.fillStyle   = 'rgba('+comboCol+',.9)';
        ctx.shadowColor = 'rgba('+comboCol+',1)';
        ctx.shadowBlur  = 10+_comboCount*1.2;
        ctx.textAlign   = 'center';
        ctx.fillText('\xd7'+_comboCount+' COMBO', pcx, pcy-32+bounce);
        ctx.restore();
      }}
      if (_comboFlash) {{
        _comboFlash.age += 0.018;
        var fa = Math.max(0, 1-_comboFlash.age*1.4);
        ctx.save();
        ctx.font='bold 8px Consolas';
        ctx.fillStyle='rgba('+_comboFlash.col[0]+','+_comboFlash.col[1]+','+_comboFlash.col[2]+','+fa+')';
        ctx.shadowColor='rgba('+_comboFlash.col[0]+','+_comboFlash.col[1]+','+_comboFlash.col[2]+','+fa+')';
        ctx.shadowBlur=12;
        ctx.textAlign='center';
        ctx.fillText(_comboFlash.text, pcx, pcy-50-_comboFlash.age*20);
        ctx.restore();
        if (_comboFlash.age >= 1) _comboFlash = null;
      }}

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
      var fl2 = gd._fullLayout;
      var tcx  = fl2.xaxis.l2p(fl2.xaxis.d2l(portT.x)) + fl2.margin.l;
      var tcy  = fl2.yaxis.l2p(fl2.yaxis.d2l(portT.y)) + fl2.margin.t;
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
// Entry: single clean tick
window._soundEntry = function() {{ _playTones([880], 0.07, 'sine', 0, 0.10); }};
// Win exit: ascending arpeggio — G4 C5 E5 A5
window._soundWin   = function() {{ _playTones([392, 523, 659, 880], 0.18, 'sine', 0.10, 0.13); }};
// Loss exit: descending drop — G4 Eb4 B3 G3
window._soundLoss  = function() {{ _playTones([392, 311, 247, 196], 0.22, 'triangle', 0.10, 0.11); }};

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

  // palette pulled from open positions' accent colors
  var PALETTE = ['#00e5ff','#9400ff','#ff9900','#e040fb','#40c4ff','#b2ff59','#ff6b35','#00ffcc'];
  function symCol(s) {{ var h=0; for(var c of s)h=(h*31+c.charCodeAt(0))&0xffff; return PALETTE[h%PALETTE.length]; }}

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
  // Force intraday zoom + tight y-axis centered on current NAV
  setTimeout(function() {{
    _programmaticRelayout = true;
    var centerNav = window._lastKnownNav || {last_nav};
    // Use actual data spread to set zoom — tight like a Bloomberg intraday chart
    var _vals = portValues.filter(function(v) {{ return v > 0; }});
    var _dataSpread = _vals.length > 1
      ? Math.max.apply(null, _vals) - Math.min.apply(null, _vals)
      : 0;
    // Show at most 2× the actual data range, or at minimum ±0.4% of NAV
    var pad = Math.max(_dataSpread * 0.6, centerNav * 0.004, 200);
    Plotly.relayout(gd, {{
      'xaxis.range': [_intradayStart(), _intradayEnd()],
      'yaxis.range': [centerNav - pad, centerNav + pad]
    }}).then(function() {{
      _programmaticRelayout = false;
    }});
  }}, 600);
}});

gd.on('plotly_afterplot', function() {{ buildTargets(); applyPortfolioGlow(); }});

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

    // Rebuild traces 7 + 8 (entry/exit markers; 6 = intraday line)
    if (gd && gd.data && gd.data.length >= 9) {{
      Plotly.restyle(gd, {{ x:[enterXs], y:[enterYs], text:[enterTexts] }}, [7]);
      Plotly.restyle(gd, {{ x:[exitXs],  y:[exitYs],  text:[exitTexts]  }}, [8]);
      // Merge drop lines with current layout shapes (preserves ATH shape etc.)
      var curShapes = (gd.layout && gd.layout.shapes) ? gd.layout.shapes.slice() : shapes.slice();
      var baseShapes = curShapes.filter(function(s) {{ return !s._trade; }});
      newShapes.forEach(function(s) {{ s._trade = true; }});
      Plotly.relayout(gd, {{ shapes: baseShapes.concat(newShapes) }});
    }}
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
  var url = SUPA_URL + '/rest/v1/pipeline_events'
    + '?run_date=eq.' + today
    + '&order=recorded_at.asc&limit=2000';
  fetch(url, {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
  .then(function(r) {{ return r.json(); }})
  .then(function(rows) {{
    if (!Array.isArray(rows)) return;
    var xs = [], ys = [];
    var tradeCountToday = 0, wins = 0, losses = 0;
    var tradeTs = [];
    rows.forEach(function(row) {{
      var msg = row.message || '';
      var ts  = row.recorded_at ? new Date(row.recorded_at).getTime() : 0;
      // Intraday portfolio value
      var m = msg.match(/marked the book at \$?([\d,]+)/);
      if (m) {{
        var v = parseFloat(m[1].replace(/,/g,''));
        if (!isNaN(v) && v > 50000 && v < 200000) {{
          xs.push(new Date(row.recorded_at).toISOString());
          ys.push(v);
        }}
      }}
      // Count trades for metrics panel + collect trade timestamps for TRADES/HR
      if (msg.match(/ENTER|enter/)) {{
        tradeCountToday++;
        if (ts) tradeTs.push(ts);
      }}
      if (msg.match(/EXIT|exit/)) {{
        tradeCountToday++;
        if (ts) tradeTs.push(ts);
        var pnlM = msg.match(/pnl\s*([+-][\d.]+)/);
        if (pnlM) {{ if (parseFloat(pnlM[1]) >= 0) wins++; else losses++; }}
      }}
    }});
    // Expose trade timestamps so TRADES/HR works across blocks
    window._tradeTs = tradeTs;
    // Update intraday trace (index 6) from DB marks only — live prices extend it via _pushIntradayPoint
    if (xs.length && gd && gd.data && gd.data.length >= 7) {{
      Plotly.restyle(gd, {{ x:[xs], y:[ys] }}, [6]).then(function() {{
        var lastV = ys[ys.length-1], lastT = xs[xs.length-1];
        window._lastKnownNav = lastV; window._lastKnownTs = lastT;
        _updateEndpointDot(lastV, lastT);
        buildTargets();
      }});
    }}
    // Recenter chart on today (intraday default) unless user has panned
    _recenterOnLatest(xs.length > 0 ? xs[xs.length - 1] : null);
    // Update metrics panel
    _updateOrbMetrics(tradeCountToday, wins, losses);
  }}).catch(function() {{}});
}}
setTimeout(_fetchIntradayMarks, 3000);
setInterval(_fetchIntradayMarks, 15000);

// ── Live intraday NAV accumulator — fed by Binance price poll every 4s ────────
var _intradayPts = [];  // {{t: isoStr, v: number}}
window._pushIntradayPoint = function(isoTs, val) {{
  var now = Date.now();
  var cutoff = now - 10 * 3600000;  // keep 10h of points
  _intradayPts = _intradayPts.filter(function(p) {{ return new Date(p.t).getTime() > cutoff; }});
  // Overwrite last point if less than 30s old (smooth, not spiky)
  if (_intradayPts.length) {{
    var last = _intradayPts[_intradayPts.length - 1];
    if (now - new Date(last.t).getTime() < 30000) {{
      last.t = isoTs; last.v = val;
    }} else {{
      _intradayPts.push({{ t: isoTs, v: val }});
    }}
  }} else {{
    _intradayPts.push({{ t: isoTs, v: val }});
  }}
  window._lastKnownNav = val;
  window._lastKnownTs  = isoTs;
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
        var pt = pulseTargets.find(function(t) {{ return t.rgb[0]===255 && t.rgb[2]===204; }});
        if (pt) {{
          try {{
            var fl = gd._fullLayout;
            var px = fl.xaxis.l2p(fl.xaxis.d2l(pt.x)) + fl.margin.l;
            var py = fl.yaxis.l2p(fl.yaxis.d2l(pt.y)) + fl.margin.t;
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

// ── Smooth ticker-tape scroll — keeps "now" always centered ────────────────────
var _scrollBusy = false;
function _recenterOnLatest(_ignored) {{
  if (_scrollBusy || _userInteracting) return;  // don't snap back if user has panned
  var nowIso   = new Date().toISOString();
  var newStart = _intradayStart();
  var newEnd   = _intradayEnd();
  _defaultXRange = [newStart, newEnd];

  // Keep portfolio line endpoint at current time so it stays connected to the orb
  var _nav = window._lastKnownNav;
  if (_nav && gd && gd.data && gd.data.length >= 5) {{
    var _portX = (gd.data[3].x || []).slice();
    var _portY = (gd.data[3].y || []).slice();
    if (_portX.length > 0) {{
      _portX[_portX.length - 1] = nowIso;
      _portY[_portY.length - 1] = _nav;
      Plotly.restyle(gd, {{ x: [_portX, _portX], y: [_portY, _portY] }}, [3, 4]);
      _updateEndpointDot(_nav, nowIso);
    }}
  }}

  _scrollBusy = true;
  _programmaticRelayout = true;
  Plotly.relayout(gd, {{ 'xaxis.range': [newStart, newEnd] }}).then(function() {{
    _scrollBusy = false;
    setTimeout(function() {{ _programmaticRelayout = false; }}, 80);
  }}).catch(function() {{ _scrollBusy = false; _programmaticRelayout = false; }});
}}
// Advance every 10s — smooth enough, no animation overhead
setInterval(function() {{ _recenterOnLatest(null); }}, 10000);

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

// ── Auto-reset chart to default view after 10s idle ──────────────────────────
var _defaultXRange = [xStart, xEnd];
var _resetTimer = null;
var _userInteracting = false;
gd.on('plotly_relayout', function(ev) {{
  buildTargets();
  // Detect user pan/zoom (not our programmatic relayouts)
  if (ev['xaxis.range[0]'] !== undefined || ev['xaxis.autorange'] !== undefined) {{
    if (!_programmaticRelayout) {{
      _userInteracting = true;
      clearTimeout(_resetTimer);
      _resetTimer = setTimeout(function() {{
        _programmaticRelayout = true;
        Plotly.relayout(gd, {{ 'xaxis.range': _defaultXRange }}).then(function() {{
          _programmaticRelayout = false;
          _userInteracting = false;
        }});
      }}, 10000);
    }}
  }}
}});
var _programmaticRelayout = false;

window.addEventListener('resize', function() {{
  resizeCanvas();
}});
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

<!-- Capital FAB + popup (fixed position, outside term-overlay) -->
<div id="capital-fab" onclick="toggleCapital()">◈ CAPITAL</div>
<div id="capital-popup">
  <div class="panel-hdr" style="cursor:pointer" onclick="toggleCapital()"><div class="term-dot"></div>CAPITAL <span style="margin-left:auto;font-size:8px;opacity:.5">✕</span></div>
  <div id="dep-body">
    <div class="dep-tabs">
      <div class="dep-tab active" id="tab-dep" onclick="setDepMode('deposit')">DEPOSIT</div>
      <div class="dep-tab" id="tab-wdw" onclick="setDepMode('withdraw')">WITHDRAW</div>
    </div>
    <div class="dep-amt-row">
      <input class="dep-input" id="dep-amount" type="number" placeholder="0.00" min="0" step="100">
      <button class="dep-btn" onclick="submitTransfer()">TRANSFER</button>
    </div>
    <div class="dep-note" id="dep-note">ACH · free · 1-3 business days to settle</div>
    <div class="dep-hist-hdr">history</div>
    <div id="dep-hist">
      <div class="dep-hist-item" style="color:#1a0028;font-size:9px">no transfers yet</div>
    </div>
  </div>
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
      if (isTrade) {{
        row.className = 'te te-new';
        var _isEntry  = _h.indexOf('>enter<') !== -1;
        var _isWin    = !_isEntry && (_h.indexOf('color:#00ff9d') !== -1);
        var _flashCol = _isEntry ? '#00e5ff' : (_isWin ? '#00ff9d' : '#ff4466');
        var _dimCol   = _isEntry ? 'rgba(0,180,220,.55)' : (_isWin ? 'rgba(0,210,130,.55)' : 'rgba(255,60,80,.55)');
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
      row.innerHTML = '<span class="te-ts">' + hhmm + '</span>' + _h;
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
        var now   = new Date();
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
        clk.innerHTML = '<span style="color:#fff;font-size:9px;margin-right:6px">' + hhmm + '</span>'
          + filledBar + emptyBar
          + '<span style="color:rgba(255,255,255,.35);font-size:9px;letter-spacing:.1em;margin-left:5px">' + remStr + '</span>';
      }}
      _tickClock();
      setInterval(_tickClock, 1000);
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

  // ── Deposit / Withdraw panel ──────────────────────────────────────────────────
  var _depMode = 'deposit';
  function setDepMode(m) {{
    _depMode = m;
    document.getElementById('tab-dep').classList.toggle('active', m==='deposit');
    document.getElementById('tab-wdw').classList.toggle('active', m==='withdraw');
    var note = document.getElementById('dep-note');
    if (note) note.textContent = m === 'deposit'
      ? 'ACH · free · 1-3 business days to settle'
      : 'ACH · free · available in 1-3 business days';
  }}
  function submitTransfer() {{
    var amt = parseFloat(document.getElementById('dep-amount').value);
    if (!amt || amt <= 0) return;
    var sign    = _depMode === 'deposit' ? '+' : '-';
    var col     = _depMode === 'deposit' ? '#00ff9d' : '#ff9900';
    var now     = new Date();
    var label   = (now.getMonth()+1)+'/'+now.getDate()+'/'+String(now.getFullYear()).slice(2);
    var amtStr  = amt.toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}});

    // Log to capital history panel
    var hist = document.getElementById('dep-hist');
    var row  = document.createElement('div');
    row.className = 'dep-hist-item';
    row.innerHTML = '<span class="dep-hist-amt" style="color:'+col+'">'+sign+'$'+amtStr+'</span>'
      + '<span style="color:#3a2a5a">'+_depMode+'</span>'
      + '<span class="dep-hist-date">'+label+'</span>';
    var noTx = hist.querySelector('div');
    if (noTx && noTx.textContent.includes('no transfers')) noTx.remove();
    hist.insertBefore(row, hist.firstChild);
    document.getElementById('dep-amount').value = '';

    // Route through Status → System Feed like every other event
    var feedMsg = _depMode === 'deposit'
      ? 'ACH deposit initiated · $' + amtStr + ' · pending 1-3 business days'
      : 'ACH withdrawal initiated · $' + amtStr + ' · pending 1-3 business days';
    if (window._postToFeed) window._postToFeed(feedMsg);
  }}

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

          function _showChip(id, text, col) {{
            var c = document.getElementById(id);
            if (!c) return;
            c.style.color = col;
            c.style.textShadow = '0 0 8px ' + col;
            c.textContent = text;
            c.style.opacity = '1';
            setTimeout(function() {{ c.style.opacity = '0'; }}, _batchDur + 900);
          }}

          // P&L combo chip (exits)
          if (_exitCount > 0) {{
            var _isPos = _batchPnl >= 0;
            _showChip('batch-pnl-chip',
              (_isPos ? '+' : '') + _batchPnl.toFixed(2),
              _isPos ? '#00c880' : '#e03355');

            // Trades combo chip
            _showChip('trades-combo-chip', '+' + _tradeCount, '#ff9900');

            // Open positions delta chip (entries minus exits = net change)
            var _posDelta = _entryCount - _exitCount;
            if (_posDelta !== 0) {{
              _showChip('pos-combo-chip',
                (_posDelta > 0 ? '+' : '') + _posDelta,
                _posDelta > 0 ? '#00e5ff' : '#ff4466');
            }}

            // Alpaca NAV verification after batch settles
            setTimeout(function() {{
              var url = SUPA_URL + '/rest/v1/portfolio_snapshots'
                + '?strategy=eq.crypto_momentum&order=recorded_at.desc&limit=1'
                + '&select=total_value,recorded_at';
              fetch(url, {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
              .then(function(r) {{ return r.json(); }})
              .then(function(snaps) {{
                if (!Array.isArray(snaps) || !snaps.length) return;
                var _alpacaNav = parseFloat(snaps[0].total_value);
                if (isNaN(_alpacaNav)) return;
                // Update wallet display if differs by more than $1
                var _walEl = document.querySelector('[data-val]');
                var _dispEl = document.getElementById('wallet-val');
                if (_dispEl) {{
                  var _cur = parseFloat((_dispEl.getAttribute('data-val') || '').replace(/[^0-9.-]/g,''));
                  if (Math.abs(_alpacaNav - _cur) > 1) {{
                    _dispEl.setAttribute('data-val', '$' + _alpacaNav.toLocaleString('en-US', {{minimumFractionDigits:2}}));
                    _dispEl.textContent  = '$' + Math.round(_alpacaNav).toLocaleString('en-US');
                  }}
                }}
              }}).catch(function() {{}});
            }}, _exitCount * 180 + 1200);
          }}
        }}

        // Stagger live batches so events drip in one-by-one (history: instant)
        var _staggerMs = isHistory ? 0 : 180;
        rows.forEach(function(row, _ri) {{ setTimeout(function() {{
          _lastSeen = row.recorded_at;
          var raw = row.message || '';
          var sym = row.symbol || '';
          var display;
          if (row.event_type === 'TRADE' && (raw.indexOf('ENTER') !== -1 || raw.indexOf('EXIT') !== -1)) {{
            var isEntry = raw.indexOf('ENTER') !== -1;
            var verbPlain = isEntry ? 'enter' : 'exit';
            var verbCol   = isEntry ? '#00b4ff' : '#ff9900';
            var verbHtml  = '<span style="color:' + verbCol + '">' + verbPlain + '</span>';
            var symCol    = (function(s) {{
              var h = 0; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffffff;
              var hue = (h % 360 + 360) % 360; return 'hsl(' + hue + ',70%,62%)';
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
                if (window._orbTradeFlash) window._orbTradeFlash(true);
                if (window._soundEntry) window._soundEntry();
                if (window._makeCard) {{
                  var _sec = document.getElementById('pos-crypto-section');
                  var _symE = sym.indexOf('/') !== -1 ? sym : sym + '/USD';
                  if (_sec && !_cryptoCardEls[_symE]) {{
                    var _priceE = priceM ? parseFloat(priceM[1].replace(/,/g,'')) : 0;
                    var _ep = {{
                      symbol: _symE, direction: 'long', qty: 0,
                      entry_price: _priceE, stop_price: _priceE * 0.997,
                      target_price: _priceE * 1.006, entered_at: new Date().toISOString()
                    }};
                    // Inject into positions map immediately — satellite spawns next animation frame
                    if (!window._cryptoPositionsMap) window._cryptoPositionsMap = {{}};
                    window._cryptoPositionsMap[_symE] = _ep;
                    var _el = window._makeCard(_ep);
                    _sec.appendChild(_el);
                    void _el.offsetWidth;
                    _el.classList.add('pos-card-entering');
                    setTimeout(function() {{ _el.classList.remove('pos-card-entering'); }}, 220);
                    _cryptoCardEls[_symE] = _el;
                    var _flat = document.getElementById('pos-crypto-flat');
                    if (_flat) _flat.style.display = 'none';
                  }}
                }}
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
                // 2. Orb bloom
                if (window._orbTradeFlash) window._orbTradeFlash(false);
                // 3. Sound
                if (pnlM) {{
                  if (_isWin) {{ if (window._soundWin) window._soundWin(); }}
                  else {{ if (window._soundLoss) window._soundLoss(); }}
                }}
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

    // Poll every 2s — smaller batches = more live, less bulk-load feel
    setTimeout(function() {{
      _poll();
      setInterval(_poll, 2000);
    }}, 2000);
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

    // Rolling nav history for velocity computation
    if (!window._navHistory) window._navHistory = [];
    function _trackNav(nav, ts) {{
      window._navHistory.unshift({{ nav: nav, ts: new Date(ts).getTime() }});
      if (window._navHistory.length > 20) window._navHistory.pop();
    }}

    function _updateNavDisplays(nav, ts) {{
      window._lastKnownNav = nav;
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

      // Extend the Plotly chart with this new data point
      var gd = document.getElementById('chart');
      if (gd && gd.data && gd.data.length > 0) {{
        var isoTs = ts || new Date().toISOString();
        window._lastKnownTs = isoTs;
        // Extend ghost (3) + portfolio (4) simultaneously
        Plotly.extendTraces(gd, {{x:[[isoTs],[isoTs]], y:[[nav],[nav]]}}, [3,4]);
        // Re-center y-axis on current NAV
        if (!_userPanned) {{
          var _yPad = Math.max(nav * 0.04, 800);
          Plotly.relayout(gd, {{ 'yaxis.range': [nav - _yPad, nav + _yPad] }});
        }}
        // Endpoint dot
        _updateEndpointDot(nav, isoTs);
        // ATH check
        _updateAthShape(nav, isoTs);
      }}
    }}

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
        _updateNavDisplays(row.total_value, row.recorded_at);
      }})
      .catch(function() {{}});
    }}

    setTimeout(function() {{
      _pollNav();
      setInterval(_pollNav, 5000);
    }}, 4000);

    // ── Live positions poller — DOM-diffing with enter/exit animations ───────
    var _TICKER_COLS = ['#00e5ff','#cc00ff','#ff9900','#e040fb','#40c4ff','#b2ff59','#ff6b35','#00ffcc'];
    function _symCol(sym) {{
      var h = 0;
      for (var i = 0; i < sym.length; i++) h = (h * 31 + sym.charCodeAt(i)) & 0xffff;
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
      // Card sweep animations — crypto + equity
      var cardEls = Object.values(_cryptoCardEls).concat(Object.values(_equityCardEls));
      cardEls.forEach(function(el, i) {{
        setTimeout(function() {{
          el.classList.remove('pos-card-scanning');
          void el.offsetWidth;
          el.classList.add('pos-card-scanning');
          setTimeout(function() {{ el.classList.remove('pos-card-scanning'); }}, 800);
        }}, i * 90);
      }});

    }};

    // ── Video-game card exit ────────────────────────────────────────────────────
    function _spawnPnlGhost(el, pnl, sym, exitPrice) {{
      if (!el) return;
      var hasPnl = (pnl !== null && pnl !== undefined);
      var r    = el.getBoundingClientRect();
      var cx   = r.left + r.width  / 2;
      var cy   = r.top  + r.height / 2;
      var isWin = hasPnl ? pnl >= 0 : true;
      var col  = isWin ? '#00ff9d' : '#ff3366';

      // ── 1. Card flash ──────────────────────────────────────────────────────
      el.style.setProperty('--flash-col', col);
      el.style.animation = 'card-flash-exit .28s ease-out forwards';

      // ── 2. Particle burst ──────────────────────────────────────────────────
      var N = 14;
      for (var i = 0; i < N; i++) {{
        var angle = (Math.PI * 2 / N) * i + (Math.random() - .5) * .6;
        var dist  = 55 + Math.random() * 60;
        var size  = 3 + Math.random() * 5;
        var dur   = (.45 + Math.random() * .35).toFixed(2) + 's';
        var p = document.createElement('div');
        p.className = 'pnl-particle';
        p.style.cssText = [
          'width:' + size + 'px', 'height:' + size + 'px',
          'background:' + col,
          'box-shadow:0 0 6px ' + col,
          'left:' + (cx - size/2) + 'px',
          'top:'  + (cy - size/2) + 'px',
          '--px:' + Math.round(Math.cos(angle) * dist) + 'px',
          '--py:' + Math.round(Math.sin(angle) * dist) + 'px',
          '--dur:' + dur,
          'opacity:1'
        ].join(';');
        document.body.appendChild(p);
        setTimeout(function(pp) {{ if (pp.parentNode) pp.parentNode.removeChild(pp); }}, 900, p);
      }}

      // ── 3. Large P&L ghost number ──────────────────────────────────────────
      var g = document.createElement('div');
      g.className = 'pnl-ghost';
      g.style.color = col;
      g.style.left  = (cx - 52) + 'px';
      g.style.top   = (cy - 28) + 'px';

      var symEl = document.createElement('div');
      symEl.className = 'pg-sym';
      symEl.textContent = (sym || '').replace('/USD','');

      var valEl = document.createElement('div');
      valEl.className = 'pg-val';
      if (hasPnl) {{
        var absPnl = Math.abs(pnl);
        valEl.textContent = absPnl >= 1000
          ? (pnl >= 0 ? '+' : '-') + '$' + (absPnl / 1000).toFixed(1) + 'K'
          : (pnl >= 0 ? '+' : '-') + '$' + absPnl.toFixed(2);
      }} else {{
        valEl.textContent = 'CLOSED';
        valEl.style.fontSize = '18px';
        valEl.style.letterSpacing = '.15em';
      }}

      var lbl = document.createElement('div');
      lbl.className = 'pg-label';
      lbl.textContent = hasPnl ? (isWin ? 'PROFIT' : 'LOSS') : 'EXIT';

      var priceEl = document.createElement('div');
      priceEl.className = 'pg-price';
      if (exitPrice) {{
        var ep = parseFloat(exitPrice.toString().replace(/,/g,''));
        priceEl.textContent = '@ $' + (ep > 1 ? ep.toLocaleString('en-US',{{maximumFractionDigits:2}}) : ep.toFixed(4));
      }}

      g.appendChild(symEl); g.appendChild(valEl); g.appendChild(lbl);
      if (exitPrice) g.appendChild(priceEl);
      document.body.appendChild(g);
      setTimeout(function() {{ if (g.parentNode) g.parentNode.removeChild(g); }}, 1200);
    }}
    var _EXIT_CLASS = {{
      'target':   'pos-card-exit-target',
      'stop':     'pos-card-exit-stop',
      'timeout':  'pos-card-exit-timeout',
      'reversal': 'pos-card-exit-rev',
      'signal':   'pos-card-exit-rev'
    }};
    var _EXIT_DUR = {{ 'target':540, 'stop':430, 'timeout':500, 'reversal':510, 'signal':510 }};
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

    window._triggerCardExit = function(fullSym, reason, pnl, exitPrice) {{
      // Check crypto map first (fullSym may be "BTC/USD" or just "BTC"), then equity map
      var el = _cryptoCardEls[fullSym] || _cryptoCardEls[fullSym + '/USD']
             || _equityCardEls[fullSym];
      if (!el) return;
      // Remove from whichever map owns it; launch satellite exit animation
      if (_cryptoCardEls[fullSym]) delete _cryptoCardEls[fullSym];
      else if (_cryptoCardEls[fullSym + '/USD']) delete _cryptoCardEls[fullSym + '/USD'];
      else if (_equityCardEls[fullSym]) delete _equityCardEls[fullSym];
      // Satellite exit for both crypto and equity
      var _exitSym = _cryptoCardEls[fullSym + '/USD'] ? fullSym + '/USD' : fullSym;
      if (_satAngles[_exitSym] !== undefined) {{
        var _ep = (window._equityPositionsMap || {{}})[_exitSym] || {{}};
        _satExiting[_exitSym] = {{
          angle: _satAngles[_exitSym], orbitR: 32, age: 0,
          sr: pnl >= 0 ? 0 : 255, sg: pnl >= 0 ? 255 : 51, sb: pnl >= 0 ? 157 : 102
        }};
        delete _satAngles[_exitSym];
        delete (window._equityPositionsMap || {{}})[_exitSym];
      }}
      el.classList.remove('pos-card-active');
      // Spawn ghost + particles immediately; collapse card after flash plays (280ms)
      _spawnPnlGhost(el, pnl, fullSym, exitPrice);
      var cls = _EXIT_CLASS[reason] || 'pos-card-exit-stop';
      var dur = _EXIT_DUR[reason] || 500;
      setTimeout(function() {{
        el.style.animation = '';  // clear flash so exit CSS can take over
        el.classList.add(cls);
        setTimeout(function() {{ if (el.parentNode) el.parentNode.removeChild(el); _updateOverlayWidth(); }}, dur);
      }}, 260);
    }};

    var _CARD_W = 118; // crypto column width
    var _EQ_W   = 130; // equity column width
    function _updateOverlayWidth() {{
      var overlay = document.getElementById('pos-overlay');
      var posLeft = document.getElementById('pos-left');
      if (!overlay || !posLeft) return;
      var count = Object.keys(_cryptoCardEls).length;
      var leftW = count > 0 ? _CARD_W : 0;  // single column regardless of count
      posLeft.style.width = leftW + 'px';
      overlay.style.width = (leftW + _EQ_W) + 'px';
    }}

    window._makeCard = function(p) {{ return _makeCard(p); }};
    function _makeCard(p) {{
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
      el.style.borderLeft = '2px solid ' + col;
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
        var tgtPct = ((tgt - entry)/entry*100).toFixed(1);
        var proxId = 'prox-live-' + p.symbol.replace(/[^A-Za-z0-9]/g,'_');
        rangeHtml = '<div class="pos-prox-wrap"'
          + ' data-entry="' + entry + '" data-stop="' + stop + '" data-target="' + tgt + '">'
          + '<div class="pos-prox-track">'
          + '<div class="pos-prox-fill" style="width:50%"></div>'
          + '<div class="pos-prox-cursor" style="left:50%"></div>'
          + '</div>'
          + '<div class="pos-prox-labels">'
          + '<span style="color:#ff3366">S ' + stopPct + '%</span>'
          + '<span class="pos-prox-live" id="' + proxId + '">——</span>'
          + '<span style="color:#00ff9d">T +' + tgtPct + '%</span>'
          + '</div>'
          + '</div>';
      }}
      var entryDisp = entry > 0 ? (entry < 0.01 ? '$' + entry.toFixed(6) : entry < 1 ? '$' + entry.toFixed(4) : '$' + entry.toFixed(2)) : '—';
      var inner = document.createElement('div');
      inner.innerHTML = '<div class="pos-top">'
        + '<span class="pos-sym" style="color:' + col + '">···</span>'
        + '<span class="pos-val">··········</span>'
        + '</div>'
        + '<div class="pos-hold active">··········</div>'
        + rangeHtml
        + '<div class="pos-age-bar" title="cooldown"><span class="pos-age-sell">SELL</span><div class="pos-age-fill" style="width:' + (100 - agePct) + '%;background:#00c8ff;box-shadow:0 0 7px rgba(0,200,255,.75)"></div></div>';
      el.appendChild(inner);
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
      // Phase 3 (520ms): entry price counts up
      setTimeout(function() {{
        var valEl = inner.querySelector('.pos-val');
        valEl.style.opacity = '1';
        var endVal = entry > 0 ? entry : 0;
        _countUp(valEl, 0, endVal, 280, function(v) {{
          return v < 0.01 ? '$' + v.toFixed(6) : v < 1 ? '$' + v.toFixed(4) : '$' + entry.toLocaleString('en-US', {{maximumFractionDigits:2}});
        }});
      }}, 520);
      // Phase 4 (720ms): stop/target line resolves
      setTimeout(function() {{
        var holdEl = inner.querySelector('.pos-hold');
        if (holdEl) {{
          holdEl.style.opacity = '1';
          var tgtPct = tgt > 0 ? ((tgt - entry) / entry * 100).toFixed(1) : '—';
          _scramble(holdEl, 'STP ' + stopPct + '%   TGT +' + tgtPct + '%', 180);
        }}
      }}, 720);
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
    }}

    function _updateCard(el, p) {{
      var entry   = parseFloat(p.entry_price);
      var stop    = parseFloat(p.stop_price);
      var age     = p.entered_at ? (Date.now() - new Date(p.entered_at)) / 60000 : 0;
      var stopPct = entry > 0 ? ((stop - entry) / entry * 100).toFixed(1) : '—';
      var hold = el.querySelector('.pos-hold');
      if (hold) hold.textContent = stopPct + '% stop · ' + Math.floor(age) + 'm';
      var valEl = el.querySelector('.pos-val');
      if (valEl && entry > 0) {{
        valEl.textContent = entry < 0.01 ? '$' + entry.toFixed(6) : entry < 1 ? '$' + entry.toFixed(4) : '$' + entry.toFixed(2);
      }}
      var fill = el.querySelector('.pos-age-fill');
      if (fill) {{
        var agePct = Math.min(age / 90 * 100, 100);
        var rem = 100 - agePct;
        fill.style.width = rem + '%';
        fill.style.background = rem > 40 ? '#00c8ff' : rem > 15 ? '#ffaa00' : '#ff2844';
          fill.style.boxShadow = rem > 40 ? '0 0 7px rgba(0,200,255,.75)' : rem > 15 ? '0 0 7px rgba(255,170,0,.7)' : '0 0 9px rgba(255,40,70,.85)';
        var sellLbl = el.querySelector('.pos-age-sell');
        if (sellLbl) sellLbl.classList.toggle('show', rem <= 15);
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
          // Exit all existing cards (poll fallback — event-driven already fired for live exits)
          Object.keys(_cryptoCardEls).forEach(function(sym) {{
            var el = _cryptoCardEls[sym];
            if (!el.classList.contains('pos-card-exit-target') &&
                !el.classList.contains('pos-card-exit-stop') &&
                !el.classList.contains('pos-card-exit-timeout') &&
                !el.classList.contains('pos-card-exit-rev')) {{
              el.classList.add('pos-card-exit-stop');
            }}
            setTimeout(function() {{ if (el.parentNode) el.parentNode.removeChild(el); }}, 450);
          }});
          _cryptoCardEls = {{}};
          _updateOverlayWidth();
          if (!flat) {{
            var f = document.createElement('div');
            f.id = 'pos-crypto-flat'; f.className = 'pos-hold';
            f.style.padding = '4px 14px 6px'; f.textContent = 'flat';
            section.appendChild(f);
          }}
          return;
        }}

        // Remove "flat" placeholder
        if (flat) flat.parentNode.removeChild(flat);

        var newSyms = {{}};
        rows.forEach(function(p) {{ newSyms[p.symbol] = p; }});

        // Exit cards no longer in data (poll fallback — event-driven already fired for live exits)
        Object.keys(_cryptoCardEls).forEach(function(sym) {{
          if (!newSyms[sym]) {{
            var el = _cryptoCardEls[sym];
            if (!el.classList.contains('pos-card-exit-target') &&
                !el.classList.contains('pos-card-exit-stop') &&
                !el.classList.contains('pos-card-exit-timeout') &&
                !el.classList.contains('pos-card-exit-rev')) {{
              el.classList.add('pos-card-exit-stop'); // fallback
            }}
            setTimeout(function() {{ if (el.parentNode) el.parentNode.removeChild(el); }}, 450);
            delete _cryptoCardEls[sym];
          }}
        }});

        // Add or update small cards
        rows.forEach(function(p) {{
          if (_cryptoCardEls[p.symbol]) {{
            _updateCard(_cryptoCardEls[p.symbol], p);
          }} else {{
            var el = _makeCard(p);
            section.appendChild(el);
            void el.offsetWidth;
            el.classList.add('pos-card-entering');
            setTimeout(function() {{ el.classList.remove('pos-card-entering'); }}, 220);
            _cryptoCardEls[p.symbol] = el;
          }}
        }});
        _updateOverlayWidth();

        // Mirror into report panel rp-crypto-section
        var rpSection = document.getElementById('rp-crypto-section');
        if (rpSection) {{
          var PALETTE = ['#00e5ff','#9400ff','#ff9900','#e040fb','#40c4ff','#b2ff59','#ff6b35','#00ffcc'];
          function _symCol(s) {{ var h=0; for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))&0xffff; return PALETTE[h%PALETTE.length]; }}
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
        if (fill)   fill.style.width   = pct + '%';
        if (cursor) cursor.style.left  = pct + '%';
        // Color the cursor: danger zone <15%, target zone >85%
        if (cursor) {{
          cursor.classList.toggle('danger', t < 0.15);
          cursor.classList.toggle('target', t > 0.85);
          if (t >= 0.15 && t <= 0.85) {{
            cursor.style.background = '#ffffff';
            cursor.style.animation  = 'none';
          }}
        }}
        // Live P&L
        if (live) {{
          var pnlPct = entry > 0 ? ((price - entry)/entry*100) : 0;
          var sign   = pnlPct >= 0 ? '+' : '';
          live.textContent = sign + pnlPct.toFixed(2) + '%';
          live.style.color = pnlPct >= 0 ? '#00ff9d' : '#ff3366';
        }}
      }});
    }}
    function _pollCryptoPrices() {{
      // Collect open symbols from DOM (works even if _cryptoPositionsMap not yet populated)
      var openSyms = [];
      document.querySelectorAll('.pos-prox-wrap[data-entry]').forEach(function(w) {{
        var card = w.closest('.pos-card[data-sym]');
        if (card) openSyms.push(card.getAttribute('data-sym'));
      }});
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
          window._liveProxPrices = priceMap; // expose for satellite dots in drawPulse
          _updateProxMeters(priceMap);
          // Compute live portfolio NAV and push intraday point
          if (window._pushIntradayPoint) {{
            var posMap = window._cryptoPositionsMap || {{}};
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
            var nav = baseline + livePnl;
            if (nav > 50000 && nav < 5000000) {{
              window._pushIntradayPoint(new Date().toISOString(), nav);
            }}
          }}
        }}).catch(function() {{}});
    }}
    setTimeout(_pollCryptoPrices, 3500);
    setInterval(_pollCryptoPrices, 4000);

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
            var ico = streakSign > 0 ? '&#128293;' : '&#9760;';
            sv.textContent = ico + ' ' + streak + (streakSign > 0 ? 'W' : 'L');
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

      // Trade count today
      var todayStr = new Date().toISOString().split('T')[0];
      var urlTc = SUPA_URL + '/rest/v1/pipeline_events'
        + '?select=id&event_type=eq.TRADE&recorded_at=gte.' + todayStr + 'T00:00:00Z';
      fetch(urlTc + '&limit=500', {{ headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }} }})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        if (!Array.isArray(rows)) return;
        var el = document.getElementById('runner-trades');
        if (el) el.textContent = rows.length + ' trades today';
        var omEl = document.getElementById('om-today');
        if (omEl) omEl.textContent = rows.length;
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
    setTimeout(function() {{ _pollStats(); setInterval(_pollStats, 15000); }}, 6000);

    // Tick age bars every 30s without a network call
    setInterval(function() {{
      Object.keys(_cryptoCardEls).forEach(function(sym) {{
        var el = _cryptoCardEls[sym];
        if (!el) return;
        var enteredAt = el.getAttribute('data-entered');
        if (!enteredAt) return;
        var age = (Date.now() - new Date(enteredAt)) / 60000;
        var fill = el.querySelector('.pos-age-fill');
        if (fill) {{
          var agePct = Math.min(age / 2 * 100, 100);
          var rem = 100 - agePct;
          fill.style.width = rem + '%';
          fill.style.background = rem > 40 ? '#00c8ff' : rem > 15 ? '#ffaa00' : '#ff2844';
          fill.style.boxShadow = rem > 40 ? '0 0 7px rgba(0,200,255,.75)' : rem > 15 ? '0 0 7px rgba(255,170,0,.7)' : '0 0 9px rgba(255,40,70,.85)';
          var sellLbl = el.querySelector('.pos-age-sell');
          if (sellLbl) sellLbl.classList.toggle('show', rem <= 15);
        }}
      }});
    }}, 30000);

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
                // Top: stHeader is hidden so topH=0; stMain may add a few px of padding
                var stMain = doc.querySelector('[data-testid="stMain"]');
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
