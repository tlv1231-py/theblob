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
#body{{flex:1;overflow:hidden;display:flex;flex-direction:column-reverse;padding:4px 0}}
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

        port_dates  = [r.d for r in port_rows]
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
        }
        try:
            pipe_rows = s.execute(text("""
                SELECT event_type, symbol, message, detail, recorded_at as ts
                FROM pipeline_events
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

    term_events.sort(key=lambda e: e["ts"] if e["ts"] else "")  # oldest first → newest at bottom
    term_events = term_events[-200:]

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

                    if sig:
                        rank = sig["rank"]
                        hold_text = f"ranked #{rank} · stays in until it drops out of top 5"
                    else:
                        hold_text = f"fell out of top 5 · the blob sells this at {_next_td_str} close"

                    positions_data.append({
                        "sym": sym, "qty": qty, "price": price,
                        "value": value, "hold_text": hold_text,
                        "in_signal": bool(sig),
                        "entry_price": entry_price,
                        "entry_date": entry_date,
                        "entry_cost": entry_cost,
                        "entry_pnl": entry_pnl,
                        "entry_pnl_pct": entry_pnl_pct,
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
    day_pnl    = data["day_pnl"]
    dpnl_str   = f'{day_pnl:+,.0f}'

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
            verb = "bought" if "bought" in msg else "sold"
            verb_col = "#00ff9d" if verb == "bought" else "#ff9900"
            qty_m = _re.search(r'(\d+)\s+shares', msg)
            qty = qty_m.group(1) if qty_m else "?"
            return f'<span style="color:{verb_col}">{verb}</span> {qty} shares {_ts(sym)}'

        # fallback
        return f'<span style="color:#5a3a7a">{msg}</span>'

    # Collect NAV values oldest-first for up/down coloring
    _snap_vals: list[float] = []
    for _ev_i, ev in enumerate(_term_evs):
        if ev["tag"] in ("NAV", "UPDATE", "SNAPSHOT"):
            _m = _re.search(r'\$([\d,]+)', ev.get("line1",""))
            if _m:
                _snap_vals.append(float(_m.group(1).replace(",","")))

    term_rows = ""
    _last_date = None
    _snap_idx  = 0
    _term_evs  = data.get("term_events", [])
    _last_ev_i = len(_term_evs) - 1

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

        hhmm = ts_raw[11:16] if len(ts_raw) >= 16 else ""

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
        tw = ' id="te-newest" style="opacity:0"' if is_newest else ''
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

    pos_cards = ""
    _TICKER_PAL = ["#00e5ff","#9400ff","#ff9900","#e040fb","#40c4ff","#b2ff59","#ff6b35","#00ffcc"]
    for p in data.get("positions_data", []):
        tcol = _TICKER_PAL[hash(p["sym"]) % len(_TICKER_PAL)]
        hold_cls = "active" if p["in_signal"] else "exiting"
        ep = p["entry_price"]
        ec = p["entry_cost"]
        epnl = p["entry_pnl"]
        epct = p["entry_pnl_pct"]
        pnl_col = "#00ff9d" if epnl >= 0 else "#ff3366"
        pnl_sign = "+" if epnl >= 0 else "−"
        tip = (
            f'<div class="pos-tip">'
            f'<div>entered {p["entry_date"]} &nbsp;·&nbsp; {p["qty"]} sh @ ${ep:.2f}</div>'
            f'<div>cost basis &nbsp;${ec:,.0f} &nbsp;→&nbsp; now ${p["value"]:,.0f}</div>'
            f'<div style="color:{pnl_col}">{pnl_sign}${abs(epnl):,.0f} &nbsp;({epct:+.1f}% lifetime)</div>'
            f'</div>'
        ) if ep else ""
        pos_cards += (
            f'<div class="pos-card">'
            f'{tip}'
            f'<div class="pos-top">'
            f'<span class="pos-sym" style="color:{tcol}">{p["sym"]}</span>'
            f'<span class="pos-qty">{p["qty"]} sh</span>'
            f'<span class="pos-val">${p["value"]:,.0f}</span>'
            f'</div>'
            f'<div class="pos-hold {hold_cls}">{p["hold_text"]}</div>'
            f'</div>'
        )
    if not pos_cards:
        pos_cards = '<div class="pos-hold" style="padding:8px 14px">no open positions</div>'

    # Normalize SPY and QQQ to $100K at portfolio start date
    # so all 3 lines are directly comparable on one axis
    spy_norm: list[float] = []
    if spy["prices"] and port["values"]:
        spy_base = spy["prices"][0]
        spy_norm = [p / spy_base * _STARTING_CAPITAL for p in spy["prices"]]

    qqq_norm: list[float] = []
    if qqq["prices"] and port["values"]:
        qqq_base = qqq["prices"][0]
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
#chart {{ position:absolute; inset:0; }}
#pulse-canvas {{ position:absolute; inset:0; pointer-events:none; z-index:8; }}

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

/* ── Legend chips (top-right of main-area) ── */
.legend-strip {{
  position:absolute; top:10px; right:16px;
  display:flex; flex-direction:column; gap:6px; z-index:10;
}}
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

/* ── Terminal overlay — CRT retrowave ── */
#term-overlay {{
  height:38%; flex-shrink:0; min-height:160px; width:100%;
  border-bottom:2px solid #ff00cc;
  background:#03000a;
  border-top:2px solid #ff00cc;
  box-shadow:0 0 32px rgba(255,0,204,.18), inset 0 0 60px rgba(0,0,0,.6);
  display:flex; flex-direction:column;
  z-index:20; pointer-events:auto;
  overflow:hidden;
}}
/* CRT scanlines inside terminal */
#term-overlay::before {{
  content:'';
  position:absolute; inset:0;
  background:repeating-linear-gradient(
    0deg, transparent, transparent 2px,
    rgba(0,0,0,.18) 2px, rgba(0,0,0,.18) 3px
  );
  pointer-events:none; z-index:100;
}}
/* vertical resize handle at top of overlay */
#vert-drag {{
  height:6px; flex-shrink:0; cursor:ns-resize;
  background:transparent; transition:background .15s; z-index:10;
}}
#vert-drag:hover, #vert-drag.dragging {{
  background:rgba(255,0,204,.22);
}}
#term-hdr {{
  flex-shrink:0; padding:0;
  border-bottom:1px solid #1a0028;
  font-size:8px; letter-spacing:.28em; color:#ff00cc;
  text-shadow:0 0 12px rgba(255,0,204,.9), 0 0 30px rgba(255,0,204,.4);
  display:flex; align-items:center; gap:0;
  background:#02000a;
}}
.hdr-col {{
  display:flex; align-items:center; gap:8px;
  padding:5px 14px; overflow:hidden; flex-shrink:0;
}}
#hdr-feed {{ flex:1; flex-shrink:1; }}
.hdr-drag-ph {{ width:5px; flex-shrink:0; }}
.term-dot {{
  width:5px; height:5px; border-radius:50%;
  background:#ff00cc;
  box-shadow:0 0 8px #ff00cc, 0 0 20px rgba(255,0,204,.5);
  animation:shimmer 2s ease-in-out infinite;
}}
/* two-column body */
#term-cols {{
  flex:1; display:flex; overflow:hidden;
}}
#term-body {{
  flex:1; overflow-y:auto;
  display:flex; flex-direction:column;
  padding:4px 0 2px;
  scrollbar-width:none;
}}
#term-body::-webkit-scrollbar {{ display:none; }}
.te {{ padding:0 16px; flex-shrink:0;
       font-size:11px; line-height:1.75; color:#9060b8;
       white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
       position:relative; }}
.te-ts  {{ color:#2e1448; font-size:10px; }}
/* typewriter curtain */
.tw-curtain {{
  position:absolute; top:0; right:0; bottom:0;
  background:#060008; pointer-events:none; z-index:4;
  display:flex; align-items:stretch;
}}
.tw-cur {{
  width:2px; flex-shrink:0; align-self:stretch;
  background:#ff00cc;
  box-shadow:0 0 6px rgba(255,0,204,.9), 0 0 14px rgba(255,0,204,.4);
}}
/* queue items need relative + clip for curtain */
.q-item {{ position:relative; overflow:hidden; }}
.te-date {{ padding:10px 16px 1px; flex-shrink:0;
            font-size:9px; font-weight:700; letter-spacing:.3em;
            color:#4a2a6a; text-transform:uppercase; }}
/* clock line */
#clock-line {{
  flex-shrink:0; padding:2px 16px 4px;
  font-size:11.5px; color:#ff00cc;
  text-shadow:0 0 10px rgba(255,0,204,.8), 0 0 24px rgba(255,0,204,.3);
  letter-spacing:.04em;
  display:flex; align-items:center; gap:0;
}}
#live-clock {{ margin-right:8px; color:#3a1a5a; font-size:10px; letter-spacing:.06em; }}
#prompt-sym {{
  color:#4a1a6a; margin-right:5px; font-size:12px; flex-shrink:0;
  text-shadow:none; user-select:none;
}}
#type-preview {{
  color:#ff00cc; font-size:11px; letter-spacing:.04em;
  text-shadow:0 0 8px rgba(255,0,204,.8), 0 0 20px rgba(255,0,204,.3);
  white-space:nowrap; flex:1; overflow:hidden;
}}
#blink-cur {{
  display:inline-block; color:#ff00cc; flex-shrink:0;
  text-shadow:0 0 10px rgba(255,0,204,.9);
  animation:blink-c 1s step-start infinite;
}}
@keyframes blink-c {{ 0%,100%{{opacity:1}} 50%{{opacity:0}} }}
@keyframes enter-flash {{
  0%   {{ background:rgba(255,0,204,.18); }}
  100% {{ background:transparent; }}
}}
.enter-flash {{ animation:enter-flash 220ms ease-out forwards; }}
/* positions panel */
#pos-panel {{
  flex:1; min-width:180px;
  border-left:none;
  overflow-y:auto; padding:6px 0;
  scrollbar-width:none;
  background:#020008;
}}
#pos-panel::-webkit-scrollbar {{ display:none; }}
#pos-panel .pos-hdr {{
  font-size:7.5px; letter-spacing:.28em; color:#2e1448;
  padding:0 14px 6px; text-transform:uppercase;
}}
.pos-card {{ padding:5px 14px 8px; position:relative; cursor:default; }}
.pos-top {{
  display:flex; align-items:baseline; gap:6px;
  font-size:12px; line-height:1.3;
}}
.pos-sym {{ font-weight:700; font-size:13px; }}
.pos-qty {{ color:#4a2a6a; font-size:10.5px; }}
.pos-val {{ color:#9060b8; font-size:11px; margin-left:auto; }}
.pos-hold {{
  font-size:9px; color:#6a4a8a;
  margin-top:2px; letter-spacing:.02em;
}}
.pos-hold.active  {{ color:#3a7a4a; }}
.pos-hold.exiting {{ color:#a05020; }}
/* ── Drag handles ── */
.col-drag {{
  width:5px; flex-shrink:0; cursor:col-resize;
  background:transparent;
  transition:background .15s;
  position:relative; z-index:10;
}}
.col-drag:hover, .col-drag.dragging {{
  background:rgba(255,0,204,.25);
}}
/* ── Queue panel ── */
#queue-panel {{
  flex:1; min-width:180px;
  border-left:none;
  overflow-y:auto; padding:4px 0;
  scrollbar-width:none;
  background:#010006;
}}
#queue-panel::-webkit-scrollbar {{ display:none; }}
.q-hdr {{
  font-size:7.5px; letter-spacing:.28em; color:#2e1448;
  padding:2px 14px 6px; text-transform:uppercase;
}}
.q-item {{
  padding:7px 14px 9px;
  border-top:1px solid rgba(26,0,40,.4);
  overflow:hidden;
}}
.q-badge {{
  font-size:7px; letter-spacing:.2em; font-weight:700;
  margin-bottom:3px;
}}
.q-label {{
  font-size:11px; font-weight:700;
  line-height:1.3; word-break:break-all;
}}
.q-detail {{
  font-size:8.5px; color:#3a2a5a;
  margin-top:1px; letter-spacing:.02em;
}}
.q-timer {{
  font-size:12px; font-weight:700; letter-spacing:.04em;
  margin-top:5px; color:#6a4a8a;
  font-variant-numeric:tabular-nums;
}}
.q-timer.urgent {{ color:#ff9900; }}
@keyframes q-pulse {{
  0%,100% {{ opacity:1; }} 50% {{ opacity:.5; }}
}}
.q-timer.imminent {{ color:#ff3366; animation:q-pulse .6s ease-in-out infinite; }}
.pos-tip {{
  display:none;
  position:absolute; left:0; bottom:100%;
  background:#0a0015; border:1px solid #3a1a4a;
  border-top:1px solid #ff00cc;
  padding:7px 12px; font-size:9.5px; line-height:1.75;
  z-index:999; white-space:nowrap; color:#6a4a8a;
  pointer-events:none;
  box-shadow:0 -4px 20px rgba(255,0,204,.1);
}}
.pos-card:hover .pos-tip {{ display:block; }}
</style>
</head>
<body>

<!-- flex child 1: topbar -->
<div class="topbar">
  <span class="wordmark">THE BLOB</span>
  <div class="pulse-dot"></div>
  <span class="pill pill-m">MOMENTUM · {status}</span>
  <span class="pill pill-c">▸ DAY {mon}/{_MONITOR_TARGET}</span>
  <span class="pill pill-d">LAST RUN {last_run}</span>
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
</div>

<!-- flex child 2: chart + floating overlays -->
<div id="main-area">
  <div id="chart"></div>
  <canvas id="pulse-canvas"></canvas>
  <div class="nav-card">
    <span class="nv-val">{nav_str}</span>
    <span class="nv-ret" style="color:{ret_color}">{ret_str} vs $100K start</span>
    <span class="nv-dpnl">today  {dpnl_str}</span>
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
</div>


<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script>
var portDates  = {port_dates_j};
var portValues = {port_values_j};
var spyDates   = {spy_dates_j};
var spyNorm    = {spy_norm_j};
var qqqDates   = {qqq_dates_j};
var qqqNorm    = {qqq_norm_j};

var latestDate = portDates.length ? portDates[portDates.length-1] : null;

// Right edge: latest data + 3-day buffer so the pulsing dot isn't pinned to the wall
var xEndDate = latestDate
  ? new Date(new Date(latestDate).getTime() + 3*24*3600*1000).toISOString().split('T')[0]
  : null;

// Default left edge: 60 days back, but never before first data point
var firstDate = portDates.length ? portDates[0] : null;
var xStartDefault = latestDate
  ? new Date(new Date(latestDate).getTime() - 60*24*3600*1000).toISOString().split('T')[0]
  : null;
if (firstDate && xStartDefault && xStartDefault < firstDate) xStartDefault = firstDate;

var xEnd   = xEndDate;
var xStart = xStartDefault;

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

var traces = [
  // $100K baseline reference
  {{
    x: [portDates[0]||xStart, latestDate],
    y: [100000, 100000],
    type:'scatter', mode:'lines',
    line:{{ color:'rgba(58,26,74,0.6)', width:1, dash:'dot' }},
    name:'$100K baseline',
    hoverinfo:'skip',
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
  {{
    x: portDates, y: portValues,
    type:'scatter', mode:'lines',
    line:{{ color:'#ff00cc', width:2.5 }},
    name:'PORTFOLIO',
    hovertemplate:'<b style="color:#ff00cc">PORTFOLIO $%{{y:,.0f}}</b><extra></extra>',
  }},
];

var shapes = latestDate ? [{{
  type:'line', xref:'x', yref:'paper',
  x0:latestDate, x1:latestDate, y0:0, y1:1,
  line:{{ color:'rgba(255,255,255,0.15)', width:1, dash:'dot' }},
}}] : [];

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
  margin:{{ t:44, b:310, l:72, r:16 }},
  width: window.innerWidth,
  height: window.innerHeight,

  xaxis:{{
    range: xStart ? [xStart, xEnd] : undefined,
    showgrid:true, gridcolor:'rgba(42,0,61,0.5)', gridwidth:1,
    tickfont:{{ family:'Consolas', size:8, color:'#3a1a4a' }},
    tickformat:'%b %d', zeroline:false, showline:false, type:'date', fixedrange:false,
  }},
  yaxis:{{
    range: yr[0] !== null ? yr : undefined,
    showgrid:true, gridcolor:'rgba(42,0,61,0.35)',
    tickfont:{{ family:'Consolas', size:8, color:'#3a1a4a' }},
    tickformat:'$,.0f',
    zeroline:false, showline:false, fixedrange:true,
    tickprefix:'',
  }},

  shapes, annotations,
  showlegend:false,
  dragmode:'pan',
  hoverlabel:{{ bgcolor:'#0d0010', bordercolor:'#2a003d', font:{{ family:'Consolas', size:9, color:'#f0e0ff' }} }},
  hovermode:'x unified',
}};

var config = {{ scrollZoom:true, displayModeBar:false, responsive:true }};
var gd = document.getElementById('chart');

// ── Pulsing canvas dots ────────────────────────────────
var canvas = document.getElementById('pulse-canvas');
function resizeCanvas() {{ canvas.width=window.innerWidth; canvas.height=window.innerHeight; }}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

var pulseTargets = [];
function buildTargets() {{
  pulseTargets = [];
  // trace order: 0=baseline(skip), 1=SPY, 2=QQQ, 3=PORTFOLIO
  [[1,[0,229,255]], [2,[148,0,255]], [3,[255,0,204]]].forEach(function(ic) {{
    var tr = gd.data[ic[0]];
    if (tr && tr.x && tr.x.length) {{
      var pt = {{ x: tr.x[tr.x.length-1], y: tr.y[tr.y.length-1], rgb: ic[1] }};
      pulseTargets.push(pt);
      console.log('pulse target', pt.x, pt.y);
    }}
  }});
  console.log('canvas size', canvas.width, canvas.height, 'targets', pulseTargets.length);
}}

var phase = 0;
var rafId = null;
function drawPulse() {{
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  phase += 0.03;

  pulseTargets.forEach(function(t) {{
    try {{
      var fl = gd._fullLayout;
      if (!fl || !fl.xaxis || !fl.yaxis) return;
      // d2l converts data value → linearized internal value; l2p converts that → pixels
      var cx = fl.xaxis.l2p(fl.xaxis.d2l(t.x)) + fl.margin.l;
      var cy = fl.yaxis.l2p(fl.yaxis.d2l(t.y)) + fl.margin.t;
      if (!isFinite(cx) || !isFinite(cy)) return;
      var r=t.rgb[0], g=t.rgb[1], b=t.rgb[2];

      // 3 staggered expanding rings
      for (var k = 0; k < 3; k++) {{
        var p = (Math.sin(phase - k * 1.1) + 1) / 2;
        ctx.beginPath();
        ctx.arc(cx, cy, 5 + p * 26, 0, Math.PI*2);
        ctx.strokeStyle = 'rgba('+r+','+g+','+b+','+(0.7*(1-p))+')';
        ctx.lineWidth = 2 - k*0.4;
        ctx.stroke();
      }}

      // Bright core with glow
      ctx.shadowColor = 'rgba('+r+','+g+','+b+',1)';
      ctx.shadowBlur = 22;
      ctx.beginPath();
      ctx.arc(cx, cy, 6, 0, Math.PI*2);
      ctx.fillStyle = 'rgba('+r+','+g+','+b+',1)';
      ctx.fill();

      // White hot center
      ctx.shadowBlur = 0;
      ctx.beginPath();
      ctx.arc(cx, cy, 2.5, 0, Math.PI*2);
      ctx.fillStyle = 'rgba(255,255,255,0.95)';
      ctx.fill();
    }} catch(e) {{ console.error('pulse err', e, t); }}
  }});
  rafId = requestAnimationFrame(drawPulse);
}}

// Start everything once Plotly has rendered
Plotly.newPlot(gd, traces, layout, config).then(function() {{
  buildTargets();
  if (rafId) cancelAnimationFrame(rafId);
  drawPulse();
}});

gd.on('plotly_afterplot', buildTargets);

// Dynamically tighten Y as user pans/zooms
gd.on('plotly_relayout', function(update) {{
  if (update['xaxis.range[0]'] !== undefined) {{
    var x0 = (update['xaxis.range[0]']||'').split('T')[0];
    var x1 = (update['xaxis.range[1]']||'').split('T')[0];
    var r = yRange(x0||null, x1||null);
    if (r[0] !== null) Plotly.relayout(gd, {{'yaxis.range': r}});
  }}
  buildTargets();
}});

window.addEventListener('load', function() {{
  Plotly.relayout(gd, {{ width:window.innerWidth, height:window.innerHeight }});
}});
window.addEventListener('resize', function() {{
  Plotly.relayout(gd, {{ width:window.innerWidth, height:window.innerHeight }});
  resizeCanvas();
}});
</script>

<!-- Terminal overlay — bottom third of chart -->
<div id="term-overlay">
  <div id="vert-drag"></div>
  <div id="term-hdr">
    <div class="hdr-col" id="hdr-feed">
      <div class="term-dot"></div><span style="font-size:13px;letter-spacing:.18em;color:#ff00cc">SYSTEM FEED</span>
    </div>
    <div class="hdr-drag-ph"></div>
    <div class="hdr-col" id="hdr-queue" style="flex:1;min-width:180px">
      <div class="term-dot"></div><span style="font-size:13px;letter-spacing:.18em;color:#ff00cc">QUEUED ACTIONS</span>
    </div>
    <div class="hdr-drag-ph"></div>
    <div class="hdr-col" id="hdr-pos" style="flex:1;min-width:180px">
      <div class="term-dot"></div><span style="font-size:13px;letter-spacing:.18em;color:#ff00cc">POSITIONS</span>
    </div>
  </div>
  <div id="term-cols">
    <div id="term-body">
      {term_rows}
      <div id="clock-line"><span id="live-clock"></span><span id="prompt-sym">&gt;</span><span id="type-preview"></span><span id="blink-cur">█</span></div>
    </div>
    <div class="col-drag" id="drag-q" title="drag to resize"></div>
    <div id="queue-panel">
      {q_items}
    </div>
    <div class="col-drag" id="drag-p" title="drag to resize"></div>
    <div id="pos-panel">
      {pos_cards}
    </div>
  </div>
</div>
<script>

  var b = document.getElementById('term-body');
  if (b) b.scrollTop = b.scrollHeight;

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

    var feedPanel = document.getElementById('term-body');
    var qPanel    = document.getElementById('queue-panel');
    var posPanel  = document.getElementById('pos-panel');
    var hdrFeed   = document.getElementById('hdr-feed');
    var hdrQueue  = document.getElementById('hdr-queue');
    var hdrPos    = document.getElementById('hdr-pos');

    makeColDrag(document.getElementById('drag-q'), feedPanel, qPanel,  hdrFeed, hdrQueue);
    makeColDrag(document.getElementById('drag-p'), qPanel,   posPanel, hdrQueue, hdrPos);

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

  function tick() {{
    var now = Date.now();
    var n = new Date();
    var mo = n.getMonth()+1, d = n.getDate(), y = String(n.getFullYear()).slice(2);
    var hh = String(n.getHours()).padStart(2,'0');
    var mm = String(n.getMinutes()).padStart(2,'0');
    var ss = String(n.getSeconds()).padStart(2,'0');
    var el = document.getElementById('live-clock');
    if (el) el.textContent = mo+'/'+d+'/'+y+'  '+hh+':'+mm+':'+ss+'  ';

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
  tick();
  setInterval(tick, 1000);

  // ── Terminal typewriter ──────────────────────────────────────────────────────
  (function() {{

    // Machine-types text at the > prompt, then Enter: flash + post to feed.
    // Used on load for the latest entry; reusable for live events later.
    function typeAtCursor(text, onDone) {{
      var preview   = document.getElementById('type-preview');
      var blinkCur  = document.getElementById('blink-cur');
      var clockLine = document.getElementById('clock-line');
      if (!preview) {{ if (onDone) onDone(); return; }}

      // Kill the cursor blink while typing — it trails the text naturally
      if (blinkCur) blinkCur.style.animation = 'none';
      preview.textContent = '';
      var i = 0;

      function tick() {{
        if (i < text.length) {{
          preview.textContent += text[i++];
          // Machine speed: 12 ms/char, rare 55 ms micro-stall (~6% of chars)
          setTimeout(tick, 12 + (Math.random() < 0.06 ? 55 : 0));
        }} else {{
          // Brief hover before Enter
          setTimeout(function() {{
            // ENTER — flash the clock-line, clear preview, reveal feed entry
            if (clockLine) {{
              clockLine.classList.add('enter-flash');
              setTimeout(function() {{ clockLine.classList.remove('enter-flash'); }}, 220);
            }}
            preview.textContent = '';
            if (blinkCur) blinkCur.style.animation = '';
            if (onDone) onDone();
          }}, 160);
        }}
      }}
      tick();
    }}

    // Expose globally so live-polling code can call it later
    window._typeAtCursor = typeAtCursor;

    // ── On load: type the latest System Feed entry ────────────────────────────
    var tb      = document.getElementById('term-body');
    var newest  = document.getElementById('te-newest');
    if (newest && tb) {{
      tb.scrollTop = tb.scrollHeight;
      var plainText = newest.textContent.replace(/\s+/g, ' ').trim();
      typeAtCursor(plainText, function() {{
        // Post: make the .te entry visible, scroll to it
        newest.style.opacity = '1';
        newest.style.transition = 'opacity 80ms ease';
        tb.scrollTop = tb.scrollHeight;
      }});
    }}

  }})();

  // ── Page reload every 90s (data freshness) ─────────────────────────────────
  setTimeout(function() {{ window.parent.location.reload(); }}, 90000);

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
