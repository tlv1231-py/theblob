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

    _term_evs  = data.get("term_events", [])
    _last_ev_i = len(_term_evs) - 1

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
        pnl_line = (
            f'<div class="pos-pnl-line" style="color:{pnl_col}">'
            f'{pnl_sign}${abs(epnl):,.0f} &nbsp;<span style="color:{pnl_col};opacity:.7">({epct:+.1f}%)</span>'
            f'</div>'
        ) if ep else ""
        pos_cards += (
            f'<div class="pos-card pos-card-active pos-card-entering" data-sym="{p["sym"]}"'
            f' style="border-left:3px solid {tcol};position:relative;overflow:hidden;transform-origin:center top">'
            f'<span class="pos-corner tl" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner tr" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner bl" style="border-color:{tcol}"></span>'
            f'<span class="pos-corner br" style="border-color:{tcol}"></span>'
            f'<div class="pos-top">'
            f'<span class="pos-sym" style="color:{tcol}">{p["sym"]}</span>'
            f'<span class="pos-qty">{p["qty"]} sh</span>'
            f'<span class="pos-val">${p["value"]:,.0f}</span>'
            f'</div>'
            f'{pnl_line}'
            f'<div class="pos-hold {hold_cls}">{p["hold_text"]}</div>'
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
  -webkit-mask-image:linear-gradient(to bottom,transparent 0%,black 16%,black 100%);
  mask-image:linear-gradient(to bottom,transparent 0%,black 16%,black 100%);
}}
#feed-overlay .panel-hdr {{ pointer-events:auto; flex-shrink:0; padding:6px 8px 5px; border-bottom:1px solid #1a0022; }}
#feed-overlay #term-body {{ flex:1; overflow-y:auto; display:flex; flex-direction:column; padding:2px 0 4px; scrollbar-width:none; background:transparent; }}
#feed-overlay #term-body::-webkit-scrollbar {{ display:none; }}
#feed-overlay .te {{ padding:2px 6px; font-size:10px; }}
#feed-bottom-bar {{ flex-shrink:0; padding:4px 8px; pointer-events:auto; display:flex; align-items:center; }}
#mute-btn {{ background:none; border:none; cursor:pointer; font-size:12px; opacity:.45; padding:2px 4px; transition:opacity .2s; }}
#mute-btn:hover {{ opacity:.9; }}

/* ── Right positions overlay ── */
#pos-overlay {{
  position:absolute; right:0; top:0; bottom:0; width:260px; z-index:15;
  display:flex; flex-direction:column;
  background:linear-gradient(270deg,rgba(1,0,8,.88) 0%,rgba(1,0,8,.6) 80%,transparent 100%);
  -webkit-mask-image:linear-gradient(to bottom,transparent 0%,black 12%,black 88%,transparent 100%);
  mask-image:linear-gradient(to bottom,transparent 0%,black 12%,black 88%,transparent 100%);
}}
#pos-overlay .panel-hdr {{ flex-shrink:0; padding:6px 12px 5px; border-bottom:1px solid #1a0022; }}
#pos-overlay #pos-body {{ flex:1; overflow:hidden; display:flex; flex-direction:row; gap:0; }}
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
@keyframes trade-entry-flash {{
  0%   {{ box-shadow:inset 0 0 0 2px rgba(0,255,157,0), border-color:#00ff41; }}
  15%  {{ box-shadow:inset 0 0 40px 6px rgba(0,255,157,.45); border-color:#00ff9d; }}
  100% {{ box-shadow:inset 0 0 0 2px rgba(0,255,157,0); border-color:#00ff41; }}
}}
@keyframes trade-exit-flash {{
  0%   {{ box-shadow:inset 0 0 0 2px rgba(255,153,0,0); border-color:#00ff41; }}
  15%  {{ box-shadow:inset 0 0 40px 6px rgba(255,153,0,.45); border-color:#ff9900; }}
  100% {{ box-shadow:inset 0 0 0 2px rgba(255,153,0,0); border-color:#00ff41; }}
}}
#term-overlay.flash-entry {{ animation:trade-entry-flash 1.2s ease-out forwards; }}
#term-overlay.flash-exit  {{ animation:trade-exit-flash  1.2s ease-out forwards; }}
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
#tracker-bar {{
  flex-shrink:0;
  background:rgba(8,3,0,.95);
  border-top:1px solid #2a1000;
  border-bottom:1px solid #ff6600;
  padding:0 16px;
  height:24px;
  display:flex;
  align-items:center;
  gap:20px;
  z-index:5;
}}
/* CYCLE block */
#run-progress-wrap {{
  display:inline-flex; align-items:center; gap:7px;
  flex-shrink:0; transition:opacity .3s;
}}
#run-progress-wrap.hidden {{ opacity:0; pointer-events:none; }}
#run-progress-track {{
  width:140px; height:6px; background:#0a0500;
  border:1px solid #3a1800;
  overflow:hidden; position:relative;
  /* vertical scanlines — the grid */
  background-image:repeating-linear-gradient(
    90deg,
    transparent 0px, transparent 7px,
    rgba(255,102,0,.08) 7px, rgba(255,102,0,.08) 8px
  );
}}
#run-progress-fill {{
  height:100%; width:0%;
  background:linear-gradient(90deg, #ff3300 0%, #ff6600 55%, #ffaa00 100%);
  box-shadow:0 0 10px rgba(255,102,0,.8), 0 0 3px rgba(255,180,0,.5);
  transition:width .9s linear;
  position:relative;
}}
/* scanline shimmer over the fill */
#run-progress-fill::after {{
  content:'';
  position:absolute; inset:0;
  background:repeating-linear-gradient(
    0deg,
    transparent 0px, transparent 1px,
    rgba(0,0,0,.35) 1px, rgba(0,0,0,.35) 2px
  );
  animation:vp-shimmer 1.8s linear infinite;
}}
@keyframes vp-shimmer {{
  from {{ background-position:0 0; }}
  to   {{ background-position:0 8px; }}
}}
@keyframes fill-fire {{
  0%,100% {{ box-shadow:0 0 10px rgba(255,102,0,.8),0 0 3px rgba(255,180,0,.5); }}
  50%      {{ box-shadow:0 0 22px rgba(255,60,0,1),0 0 8px rgba(255,200,0,.9); }}
}}
#run-progress-fill.firing {{ animation:fill-fire .4s ease-in-out infinite; }}
#run-progress-label {{
  font-size:9px; letter-spacing:.18em; white-space:nowrap;
  font-family:Consolas,monospace;
  color:#ff6600;
  text-shadow:0 0 8px rgba(255,102,0,.8);
  min-width:28px; text-align:right;
}}
/* ── Status bar (clock / cursor only) ── */
#status-bar {{
  position:fixed; bottom:0; left:0; right:0; z-index:200;
  background:#060010;
  border-top:1px solid #0d001e;
  padding:5px 16px;
  font-size:10px;
  line-height:1.4;
}}
#live-clock {{ display:inline; color:#006622; font-size:8.5px; letter-spacing:.04em; }}
#prompt-sym {{ display:inline; color:#004d18; font-size:10px; user-select:none; margin:0 2px; }}
#type-preview {{
  display:inline; color:#00ff41; font-size:10px; letter-spacing:.04em;
  text-shadow:0 0 8px rgba(0,255,65,.9);
  white-space:normal; word-break:break-word;
}}
#blink-cur {{
  display:inline; color:#00ff41;
  text-shadow:0 0 8px rgba(0,255,65,.9);
  animation:blink-c 1s step-start infinite;
}}
@keyframes blink-c {{ 0%,100%{{opacity:1}} 50%{{opacity:0}} }}
@keyframes enter-flash {{
  0%   {{ background:rgba(0,255,65,.15); }}
  100% {{ background:transparent; }}
}}
.enter-flash {{ animation:enter-flash 220ms ease-out forwards; }}
/* ── VHS trade flash on enter/exit feed lines ── */
@keyframes vhs-trade-in {{
  0%   {{ opacity:0; transform:translateX(-4px); filter:brightness(6) saturate(0); }}
  8%   {{ opacity:1; filter:brightness(3) saturate(1.5);
          text-shadow:-3px 0 rgba(255,0,204,.7),3px 0 rgba(0,229,255,.7),0 0 20px rgba(0,255,65,.9); }}
  30%  {{ filter:brightness(1.4) saturate(1.2);
          text-shadow:-1px 0 rgba(255,0,204,.4),1px 0 rgba(0,229,255,.4),0 0 10px rgba(0,255,65,.6); }}
  100% {{ opacity:1; transform:none; filter:brightness(1) saturate(1); text-shadow:none; }}
}}
@keyframes vhs-trade-aberr {{
  0%,100% {{ text-shadow:0 0 6px rgba(0,255,65,.4); }}
  20%      {{ text-shadow:-2px 0 rgba(255,0,204,.5),2px 0 rgba(0,229,255,.5),0 0 14px rgba(0,255,65,.7); }}
  40%      {{ text-shadow:0 0 6px rgba(0,255,65,.3); }}
  60%      {{ text-shadow:1px 0 rgba(255,0,204,.3),-1px 0 rgba(0,229,255,.3),0 0 8px rgba(0,255,65,.4); }}
}}
.te-trade {{
  animation:vhs-trade-in .45s cubic-bezier(.22,1,.36,1) forwards, vhs-trade-aberr 1.8s ease-out 0.45s 1 forwards;
}}

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
  padding:2px 0 4px;
  scrollbar-width:none; background:#010006;
}}
#term-body::-webkit-scrollbar {{ display:none; }}
.te {{ padding:2px 12px; flex-shrink:0;
       font-size:10px; line-height:1.6; color:#9060b8;
       white-space:normal; word-break:break-word; }}
.te-ts  {{ color:#6a5a7a; font-size:9px; }}
.te-date {{ padding:5px 12px 1px; flex-shrink:0;
            font-size:7.5px; font-weight:700; letter-spacing:.28em;
            color:#1a0028; text-transform:uppercase; }}
/* clock line hidden — status bar handles cursor */
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
#pos-left {{ border-right:1px solid #0d0020; }}
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
/* ── Orb metrics panel — replaces old P&L tooltip ── */
#pnl-float {{
  position:absolute; pointer-events:none;
  background:rgba(4,0,10,.88); border:1px solid #2a003d; border-top:2px solid #ff00cc;
  backdrop-filter:blur(8px);
  padding:8px 12px; min-width:130px;
  transform:translate(-50%, -100%) translateY(-18px);
  opacity:0;
  transition:opacity .4s ease, transform .6s cubic-bezier(.22,1,.36,1);
}}
#pnl-float.visible {{ opacity:1; }}
#pnl-float.nudge-up   {{ transform:translate(-50%, -100%) translateY(-28px); }}
#pnl-float.nudge-down {{ transform:translate(-50%, -100%) translateY(-10px); }}
.om-row {{
  display:flex; align-items:baseline; justify-content:space-between; gap:10px;
  padding:1.5px 0;
}}
.om-label {{
  font-size:7px; letter-spacing:.18em; color:#4a2a6a; white-space:nowrap;
  font-family:Consolas,monospace; text-transform:uppercase;
}}
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
.pos-section-label {{
  font-size:7px; letter-spacing:.22em; color:#2a1a3a;
  padding:4px 12px 2px; text-transform:uppercase; border-bottom:1px solid #0d0020;
}}
#pos-equity-section .pos-section-label {{ border-top:1px solid #0d0020; margin-top:2px; }}
.pos-card {{ padding:6px 12px 7px; cursor:default; position:relative; overflow:hidden;
             background:rgba(6,0,8,.72); backdrop-filter:blur(6px); border-bottom:1px solid #0d0020; }}
/* scan sweep */
@keyframes card-scan-sweep {{
  0%   {{ top:-3px; opacity:0; }}
  8%   {{ opacity:1; }}
  92%  {{ opacity:1; }}
  100% {{ top:calc(100% + 3px); opacity:0; }}
}}
.pos-card-scanning::after {{
  content:''; position:absolute; pointer-events:none; z-index:20;
  left:-5%; right:-5%; height:2px; top:-3px;
  background:linear-gradient(90deg,transparent 0%,rgba(0,255,157,.65) 20%,#00e5ff 50%,rgba(0,255,157,.65) 80%,transparent 100%);
  box-shadow:0 0 6px #00ff9d,0 0 16px rgba(0,229,255,.7);
  animation:card-scan-sweep .65s ease-in-out forwards;
}}
.pos-top {{ display:flex; align-items:baseline; gap:6px; line-height:1.3; }}
.pos-sym {{ font-weight:700; font-size:15px; }}
.pos-qty {{ color:#3a1a5a; font-size:10px; }}
.pos-val {{ color:#9060b8; font-size:12px; font-weight:700; margin-left:auto; }}
.pos-pnl-line {{ font-size:10px; margin-top:1px; }}
.pos-hold {{ font-size:8.5px; color:#4a2a6a; margin-top:2px; letter-spacing:.02em; }}
.pos-hold.active  {{ color:#1a6a2a; }}
.pos-hold.exiting {{ color:#7a3a0a; }}
/* ── VHS Scan bar ── */
#vhs-scan-bar {{
  display:inline-flex; align-items:center; gap:9px;
  flex-shrink:0; opacity:0; pointer-events:none;
  transition:opacity .15s;
}}
#vhs-scan-bar.active {{ opacity:1; pointer-events:auto; }}
#vhs-scan-label {{
  font-size:11px; font-weight:900; letter-spacing:.32em;
  font-stretch:condensed;
  color:#00e5ff;
  text-shadow:0 0 6px rgba(0,229,255,.9), 2px 0 0 rgba(255,0,204,.35), -1px 0 0 rgba(255,0,204,.2);
  white-space:nowrap;
  /* VHS horizontal smear */
  transform:scaleX(1.08) scaleY(.94);
  transform-origin:left center;
}}
#vhs-track {{
  width:220px; height:10px;
  background:#000;
  border:1px solid rgba(255,255,255,.55);
  overflow:hidden; position:relative;
  /* vertical stripe grid mimicking VHS tape */
  background-image:repeating-linear-gradient(
    90deg,
    transparent 0px, transparent 5px,
    rgba(0,229,255,.04) 5px, rgba(0,229,255,.04) 6px
  );
}}
#vhs-fill {{
  height:100%; width:0%;
  background:linear-gradient(90deg, rgba(0,229,255,.9) 0%, #00ff9d 70%, #fff 100%);
  box-shadow:0 0 8px rgba(0,229,255,.8), 0 0 2px #fff;
  position:relative;
}}
/* Horizontal scanline shimmer over fill */
#vhs-fill::after {{
  content:'';
  position:absolute; inset:0;
  background:repeating-linear-gradient(
    0deg,
    transparent 0px, transparent 1px,
    rgba(0,0,0,.45) 1px, rgba(0,0,0,.45) 2px
  );
  animation:vhs-lines 1.2s linear infinite;
}}
@keyframes vhs-lines {{
  from {{ background-position:0 0; }}
  to   {{ background-position:0 8px; }}
}}
/* Leading edge noise blip */
#vhs-fill::before {{
  content:'';
  position:absolute; right:-1px; top:0; bottom:0; width:3px;
  background:rgba(255,255,255,.85);
  box-shadow:0 0 4px #fff, 0 0 8px rgba(0,229,255,.9);
  animation:vhs-blip .08s steps(1) infinite;
}}
@keyframes vhs-blip {{
  0%,100% {{ opacity:1; height:100%; top:0; }}
  50%      {{ opacity:.7; height:60%; top:20%; }}
}}
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
.pos-age-bar {{ height:2px; margin-top:4px; border-radius:1px; overflow:hidden; background:#0d0020; }}
.pos-age-fill {{
  height:100%; border-radius:1px;
  transition:width .8s linear, background .8s;
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
.pos-card-entering {{ animation:card-enter .45s cubic-bezier(.22,1,.36,1) forwards; transform-origin:center top; }}
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
  <div id="vhs-scan-bar">
    <span id="vhs-scan-label">SCAN:</span>
    <div id="vhs-track"><div id="vhs-fill"></div></div>
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
  <div id="crosshair-overlay"><canvas id="xhair-canvas"></canvas></div>
  <div id="pnl-float">
    <div class="om-row">
      <span class="om-label">DAY P&amp;L</span>
      <span class="om-val" id="om-dpnl" style="color:{_pnl_col}">{dpnl_str}</span>
    </div>
    <div class="om-divider"></div>
    <div class="om-row">
      <span class="om-label">TRADES/HR</span>
      <span class="om-val" id="om-tph">—</span>
    </div>
    <div class="om-row">
      <span class="om-label">TODAY</span>
      <span class="om-val" id="om-today">0</span>
    </div>
    <div class="om-divider"></div>
    <div class="om-row">
      <span class="om-label">WIN RATE</span>
      <span class="om-val" id="om-winrate">—</span>
    </div>
    <div class="om-row">
      <span class="om-label">STREAK</span>
      <span class="om-val" id="om-streak-orb">—</span>
    </div>
    <div class="om-divider"></div>
    <div class="om-row">
      <span class="om-label">OPEN POS</span>
      <span class="om-val" id="om-openpos">{n_positions}</span>
    </div>
    <div class="om-row">
      <span class="om-label">TOTAL P&amp;L</span>
      <span class="om-val" style="color:{_pnl_col}">{_pnl_str}</span>
    </div>
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
    <div id="term-body">
      {term_rows}
    </div>
    <div id="feed-bottom-bar">
      <span id="feed-last-ago" style="font:700 7px Consolas,monospace;letter-spacing:.14em;color:#3a1a5a;flex:1">—</span>
      <button id="mute-btn" onclick="_toggleMute()" title="Toggle sound">&#128266;</button>
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
// Center the current-position dot: equal padding left and right of latest data
var _CENTER_DAYS = 4;  // tight zoom — 4 days each side so movements look dramatic
var xEnd   = latestPortDate ? _datePlus_from(latestPortDate, _CENTER_DAYS) : _datePlus(14);
var xStart = latestPortDate ? _dateMinus(latestPortDate, _CENTER_DAYS) : _datePlus(-30);

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
    line:{{ color:'rgba(255,0,204,0.06)', width:14 }},
    fill:'tozeroy', fillcolor:'rgba(255,0,204,0.04)',
    name:'ghost', hoverinfo:'skip', showlegend:false,
  }},
  // PORTFOLIO — main line (trace index 4)
  {{
    x: portDates, y: portValues,
    type:'scatter', mode:'lines',
    line:{{ color:'#ff00cc', width:2.5 }},
    fill:'tozeroy', fillcolor:'rgba(255,0,204,0.07)',
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
    autorange:true,
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

// ── Ambient canvas — drifting cyberpunk blobs ─────────
var ambCanvas = document.getElementById('ambient-canvas');
(function() {{
  function resizeAmb() {{ ambCanvas.width=window.innerWidth; ambCanvas.height=window.innerHeight; }}
  resizeAmb();
  window.addEventListener('resize', resizeAmb);
  var t = 0;
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

// ── Orb trade flash — animated color burst on entry/exit ─────────────────────
var _orbFlash = {{ active: false, isEntry: true, t: 0, dur: 2200 }};
window._orbTradeFlash = function(isEntry) {{
  _orbFlash.active = true;
  _orbFlash.isEntry = isEntry;
  _orbFlash.t = Date.now();
  // Burst: extra rings, held briefly
  _orbBurstCount = isEntry ? 6 : 5;
}};
var _orbBurstCount = 0;
var _liveTip = {{ pts: [] }}; // brownian extension from latest portfolio point

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
  var fl = gd._fullLayout;
  var tr = gd.data[3]; // PORTFOLIO trace
  var pf = document.getElementById('pnl-float');
  if (!fl || !tr || !tr.x || !tr.x.length || !pf) return;
  try {{
    var cx = fl.xaxis.l2p(fl.xaxis.d2l(tr.x[tr.x.length-1])) + fl.margin.l;
    var cy = fl.yaxis.l2p(fl.yaxis.d2l(tr.y[tr.y.length-1])) + fl.margin.t;
    if (!isFinite(cx) || !isFinite(cy)) return;
    pf.style.left = cx + 'px';
    pf.style.top  = cy + 'px';
    pf.classList.add('visible');
  }} catch(e) {{}}
}}

var phase = 0;
var rafId = null;
function drawPulse() {{
  var ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  phase += 0.03;

  // Compute flash blend for portfolio orb
  var flashAlpha = 0;
  var flashRgb = [255, 0, 204]; // default pink
  if (_orbFlash.active) {{
    var elapsed = Date.now() - _orbFlash.t;
    flashAlpha = Math.max(0, 1 - elapsed / _orbFlash.dur);
    if (flashAlpha <= 0) {{ _orbFlash.active = false; _orbBurstCount = 0; }}
    else flashRgb = _orbFlash.isEntry ? [0,255,157] : [255,51,102];
  }}

  pulseTargets.forEach(function(t) {{
    try {{
      var fl = gd._fullLayout;
      if (!fl || !fl.xaxis || !fl.yaxis) return;
      var cx = fl.xaxis.l2p(fl.xaxis.d2l(t.x)) + fl.margin.l;
      var cy = fl.yaxis.l2p(fl.yaxis.d2l(t.y)) + fl.margin.t;
      if (!isFinite(cx) || !isFinite(cy)) return;

      // Portfolio orb: blend between flash color and base pink
      var isPortfolio = t.rgb[0]===255 && t.rgb[2]===204;
      var r, g, b;
      if (isPortfolio && flashAlpha > 0) {{
        r = Math.round(t.rgb[0]*(1-flashAlpha) + flashRgb[0]*flashAlpha);
        g = Math.round(t.rgb[1]*(1-flashAlpha) + flashRgb[1]*flashAlpha);
        b = Math.round(t.rgb[2]*(1-flashAlpha) + flashRgb[2]*flashAlpha);
      }} else {{
        r=t.rgb[0]; g=t.rgb[1]; b=t.rgb[2];
      }}

      // Rings — extra burst count on trade flash
      var ringCount = (isPortfolio && _orbBurstCount > 0) ? _orbBurstCount : 3;
      if (isPortfolio && _orbBurstCount > 0) _orbBurstCount = Math.max(0, _orbBurstCount - 0.04);
      for (var k = 0; k < Math.ceil(ringCount); k++) {{
        var p = (Math.sin(phase - k * 0.9) + 1) / 2;
        var maxR = isPortfolio && flashAlpha > 0 ? 40 + flashAlpha*20 : 26;
        ctx.beginPath();
        ctx.arc(cx, cy, 5 + p * maxR, 0, Math.PI*2);
        ctx.strokeStyle = 'rgba('+r+','+g+','+b+','+(0.7*(1-p))+')';
        ctx.lineWidth = 2 - k*0.3;
        ctx.stroke();
      }}

      // Core glow — brighter during flash
      var coreSize = isPortfolio && flashAlpha > 0 ? 6 + flashAlpha*4 : 6;
      ctx.shadowColor = 'rgba('+r+','+g+','+b+',1)';
      ctx.shadowBlur = isPortfolio && flashAlpha > 0 ? 35 + flashAlpha*20 : 22;
      ctx.beginPath();
      ctx.arc(cx, cy, coreSize, 0, Math.PI*2);
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

  // ── Live-tip: brownian extension from latest portfolio point ─────────────
  (function() {{
    var portT = pulseTargets.find(function(t) {{ return t.rgb[0]===255 && t.rgb[2]===204; }});
    if (!portT) return;
    try {{
      var fl = gd._fullLayout;
      if (!fl || !fl.xaxis || !fl.yaxis) return;
      var cx = fl.xaxis.l2p(fl.xaxis.d2l(portT.x)) + fl.margin.l;
      var cy = fl.yaxis.l2p(fl.yaxis.d2l(portT.y)) + fl.margin.t;
      if (!isFinite(cx) || !isFinite(cy)) return;
      // Brownian motion state (persisted across frames via closure on module scope)
      if (!_liveTip.pts.length) _liveTip.pts.push({{dx:0,dy:0}});
      var last = _liveTip.pts[_liveTip.pts.length-1];
      var ndx = last.dx + (Math.random()-0.48)*1.1; // slight rightward drift
      var ndy = last.dy * 0.93 + (Math.random()-0.5)*1.4; // mean-reverting
      ndx = Math.min(ndx, 52); // cap extension width
      _liveTip.pts.push({{dx:ndx, dy:ndy}});
      if (_liveTip.pts.length > 80) _liveTip.pts.shift();
      // Fade alpha along the path
      var n = _liveTip.pts.length;
      ctx.save();
      for (var i = 1; i < n; i++) {{
        var a = (i/n) * 0.55;
        var p0 = _liveTip.pts[i-1], p1 = _liveTip.pts[i];
        ctx.beginPath();
        ctx.moveTo(cx + p0.dx, cy + p0.dy);
        ctx.lineTo(cx + p1.dx, cy + p1.dy);
        ctx.strokeStyle = 'rgba(255,0,204,' + a + ')';
        ctx.lineWidth   = 1.1;
        ctx.shadowColor = 'rgba(255,0,204,' + (a*0.8) + ')';
        ctx.shadowBlur  = 5;
        ctx.stroke();
      }}
      ctx.restore();
    }} catch(e) {{}}
  }})();

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
  var btn = document.getElementById('mute-btn');
  if (btn) btn.innerHTML = _audioMuted ? '&#128263;' : '&#128266;';
  if (!_audioMuted) _unlockAudio();
}}
function _playTones(freqs, dur, type) {{
  if (_audioMuted || !_audioReady || !_audioCtx) return;
  try {{
    if (_audioCtx.state === 'suspended') {{ _audioCtx.resume(); return; }}
    freqs.forEach(function(f, i) {{
      var osc = _audioCtx.createOscillator(), g = _audioCtx.createGain();
      osc.connect(g); g.connect(_audioCtx.destination);
      osc.type = type || 'sine';
      osc.frequency.value = f;
      var t0 = _audioCtx.currentTime + i * 0.09;
      g.gain.setValueAtTime(0, t0);
      g.gain.linearRampToValueAtTime(0.12, t0 + 0.01);
      g.gain.linearRampToValueAtTime(0, t0 + dur);
      osc.start(t0); osc.stop(t0 + dur + 0.05);
    }});
  }} catch(e) {{}}
}}
window._soundEntry = function() {{ _playTones([440, 660], 0.12); }};
window._soundWin   = function() {{ _playTones([523, 659, 784], 0.18); }};
window._soundLoss  = function() {{ _playTones([330, 247], 0.22, 'triangle'); }};

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
  // Seed endpoint dot from server-rendered data
  if (portDates.length && portValues.length) {{
    var initNav = portValues[portValues.length - 1];
    var initTs  = portDates[portDates.length - 1];
    window._lastKnownNav = initNav;
    window._lastKnownTs  = initTs;
    var initAbove = initNav >= 100000;
    Plotly.restyle(gd, {{ fillcolor: initAbove ? 'rgba(0,255,157,0.09)' : 'rgba(255,51,102,0.09)' }}, [4]);
    Plotly.restyle(gd, {{ fillcolor: initAbove ? 'rgba(0,255,157,0.04)' : 'rgba(255,51,102,0.04)' }}, [3]);
    setTimeout(function() {{ _updateEndpointDot(initNav, initTs); }}, 200);
    setTimeout(function() {{ _updateAthShape(initNav, initTs); }}, 250);
  }}
  // Crosshair on load: show → zoom in after crosshair fades
  setTimeout(showCrosshair, 1500);
  // Mark initial layout complete so the pan tracker ignores programmatic events
  setTimeout(function() {{ _initLayoutDone = true; }}, 500);
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
  // Find the closest portfolio value by date
  if (!portDates.length) return null;
  var d = isoTs.slice(0,10);
  var best = null, bestDiff = Infinity;
  for (var i=0; i<portDates.length; i++) {{
    var diff = Math.abs(new Date(portDates[i]).getTime() - new Date(d).getTime());
    if (diff < bestDiff) {{ bestDiff = diff; best = portValues[i]; }}
  }}
  // If we have a live NAV that's more recent, prefer it for today
  if (window._lastKnownNav && d >= (portDates[portDates.length-1]||'')) best = window._lastKnownNav;
  return best;
}}

function _spawnTradeChip(isoTs, sym, isEntry, price) {{
  // Floating animated chip on the chart area
  var gRect = gd.getBoundingClientRect();
  var xaxis = gd._fullLayout.xaxis;
  var yaxis = gd._fullLayout.yaxis;
  if (!xaxis || !yaxis) return;

  var chip = document.createElement('div');
  chip.style.cssText = [
    'position:fixed',
    'pointer-events:none',
    'z-index:290',
    'font-family:Consolas,monospace',
    'font-size:9px',
    'font-weight:700',
    'letter-spacing:.08em',
    'padding:3px 7px 3px 5px',
    'border-radius:2px',
    'white-space:nowrap',
    isEntry
      ? 'color:#00ff9d;background:rgba(0,255,157,.1);border:1px solid rgba(0,255,157,.3);box-shadow:0 0 12px rgba(0,255,157,.25)'
      : 'color:#ff3366;background:rgba(255,51,102,.1);border:1px solid rgba(255,51,102,.3);box-shadow:0 0 12px rgba(255,51,102,.25)',
    'opacity:0',
    'transform:translateY(0px)',
    'transition:opacity .25s ease, transform 1.4s cubic-bezier(.22,1,.36,1)',
  ].join(';');
  chip.textContent = (isEntry ? '▲ ' : '▼ ') + sym.replace('/USD','') + '  $' + parseFloat(price||0).toFixed(sym.indexOf('USD')!==-1?4:2);
  document.body.appendChild(chip);

  // Position near chart right edge / current time
  var pxX = gRect.left + gRect.width * 0.78;
  var pxY = gRect.top  + gRect.height * (isEntry ? 0.45 : 0.55);
  chip.style.left = pxX + 'px';
  chip.style.top  = pxY + 'px';

  requestAnimationFrame(function() {{
    requestAnimationFrame(function() {{
      chip.style.opacity = '1';
      chip.style.transform = 'translateY(' + (isEntry ? -28 : 28) + 'px)';
    }});
  }});

  setTimeout(function() {{
    chip.style.transition = 'opacity .6s ease';
    chip.style.opacity = '0';
    setTimeout(function() {{ if (chip.parentNode) chip.parentNode.removeChild(chip); }}, 700);
  }}, 3500);
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
var _SUPA_URL_REF = SUPA_URL, _SUPA_KEY_REF = SUPA_KEY;
function _fetchIntradayMarks() {{
  var today = new Date().toISOString().slice(0,10);
  var url = _SUPA_URL_REF + '/rest/v1/pipeline_events'
    + '?run_date=eq.' + today
    + '&order=recorded_at.asc&limit=2000';
  fetch(url, {{ headers: {{ 'apikey': _SUPA_KEY_REF, 'Authorization': 'Bearer ' + _SUPA_KEY_REF }} }})
  .then(function(r) {{ return r.json(); }})
  .then(function(rows) {{
    if (!Array.isArray(rows)) return;
    var xs = [], ys = [];
    var tradeCountToday = 0, wins = 0, losses = 0;
    rows.forEach(function(row) {{
      var msg = row.message || '';
      // Intraday portfolio value
      var m = msg.match(/marked the book at \$?([\d,]+)/);
      if (m) {{
        var v = parseFloat(m[1].replace(/,/g,''));
        if (!isNaN(v) && v > 50000 && v < 200000) {{
          xs.push(new Date(row.recorded_at).toISOString());
          ys.push(v);
        }}
      }}
      // Count trades for metrics panel
      if (msg.match(/ENTER|enter/)) tradeCountToday++;
      if (msg.match(/EXIT|exit/)) {{
        tradeCountToday++;
        var pnlM = msg.match(/pnl\s*([+-][\d.]+)/);
        if (pnlM) {{ if (parseFloat(pnlM[1]) >= 0) wins++; else losses++; }}
      }}
    }});
    // Update intraday trace (index 6)
    if (gd && gd.data && gd.data.length >= 7) {{
      Plotly.restyle(gd, {{ x:[xs], y:[ys] }}, [6]);
    }}
    // Recenter chart on actual latest point (intraday or daily snapshot)
    _recenterOnLatest(xs.length > 0 ? xs[xs.length - 1] : null);
    // Update metrics panel
    _updateOrbMetrics(tradeCountToday, wins, losses);
  }}).catch(function() {{}});
}}
setTimeout(_fetchIntradayMarks, 3000);
setInterval(_fetchIntradayMarks, 15000);

// ── Orb metrics panel updates ─────────────────────────────────────────────────
var _orbTodayTrades = 0, _orbWins = 0, _orbLosses = 0;
function _updateOrbMetrics(todayTrades, wins, losses) {{
  if (todayTrades > 0) _orbTodayTrades = todayTrades;
  if (wins   > 0) _orbWins   = wins;
  if (losses > 0) _orbLosses = losses;

  // _tradeTs is defined in script block 2 — access via window or direct (same scope)
  var tph = (typeof _tradeTs !== 'undefined') ? _tradeTs.length : 0;
  var el;

  el = document.getElementById('om-tph');
  if (el) el.textContent = tph.toFixed(1);

  el = document.getElementById('om-today');
  if (el) el.textContent = _orbTodayTrades + ' trades';

  var total = _orbWins + _orbLosses;
  el = document.getElementById('om-winrate');
  if (el) el.textContent = total > 0 ? Math.round(_orbWins/total*100) + '%' : '—';

  el = document.getElementById('om-streak-orb');
  if (el) {{
    var s = (typeof _streak !== 'undefined') ? _streak : null;
    if (s && s.count > 0) {{
      var col = s.win ? '#00ff9d' : '#ff3366';
      el.textContent = (s.win ? '+' : '-') + s.count;
      el.style.color = col;
    }} else {{
      el.textContent = '—';
    }}
  }}
}}
setInterval(function() {{ _updateOrbMetrics(0,0,0); }}, 5000);

// ── Chart re-center on latest point ──────────────────────────────────────────
function _recenterOnLatest(latestIsoTs) {{
  if (_userInteracting) return;
  // Use provided timestamp or fall back to latest portfolio date
  var anchor = latestIsoTs ? latestIsoTs.slice(0,10) : (portDates.length ? portDates[portDates.length-1] : null);
  if (!anchor) return;
  var newStart = _dateMinus(anchor, _CENTER_DAYS);
  var newEnd   = _datePlus_from(anchor, _CENTER_DAYS);
  // Only update if range actually changed by more than 1 day
  if (newEnd !== _defaultXRange[1]) {{
    _defaultXRange = [newStart, newEnd];
    _programmaticRelayout = true;
    Plotly.relayout(gd, {{ 'xaxis.range': [newStart, newEnd] }}).then(function() {{
      _programmaticRelayout = false;
    }});
  }}
}}

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

<!-- Status bar — clock / cursor only (fixed) -->
<div id="status-bar">
  <span id="live-clock"></span>
  <span id="prompt-sym">&gt;</span>
  <span id="type-preview"></span>
  <span id="blink-cur">█</span>
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
    if (!el) return;
    var col  = isWin ? '#00ff9d' : '#ff3366';
    var icon = isWin ? '▲' : '▼';
    var n    = _streak.count;
    el.innerHTML = '<span style="color:' + col + ';text-shadow:0 0 8px ' + col + '">' + icon + '&nbsp;' + n + (n === 1 ? ' WIN' : n < 3 ? ' STREAK' : ' STREAK 🔥') + '</span>';
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
  if (b) {{ b.scrollTop = b.scrollHeight; }}

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

  // ── Terminal typewriter ──────────────────────────────────────────────────────
  (function() {{

    // Machine-types text at the > prompt, then Enter: flash + post to feed.
    // Used on load for the latest entry; reusable for live events later.
    function typeAtCursor(text, onDone) {{
      var preview    = document.getElementById('type-preview');
      var blinkCur   = document.getElementById('blink-cur');
      var clockLine  = document.getElementById('status-bar'); // flash status bar on Enter
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

    var _busy      = false;
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
        // hide bar while a message is typing through status
        if (wrap) wrap.classList.toggle('hidden', _busy);
      }}, 1000);
    }}

    // Expose globally so the feed poller (separate IIFE) can reset it
    window._resetRunTimer = _resetRunTimer;

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

    function startIdle() {{
      // no-op — progress bar replaced idle phrases
    }}

    // ── postToFeed: THE single gateway for all System Feed entries ────────────
    // Every trade, fill, deposit, withdraw, pipeline event goes through here.
    // Text types through Status first, Enter commits it as a new feed row.
    // postToFeed(plain, timestamp, html)
    // plain = what types through the status bar cursor (no HTML tags)
    // html  = what appears in the feed row (may contain spans for color)
    function postToFeed(plain, timestamp, html) {{
      _feedQueue.push({{plain: plain, html: html || plain, ts: timestamp || null}});
      _drainQueue();
    }}

    function _drainQueue() {{
      if (_busy || !_feedQueue.length) return;
      _busy = true;
      var item = _feedQueue.shift();
      typeAtCursor(item.plain, function() {{
        // Append new row to System Feed
        var tb   = document.getElementById('term-body');
        var now  = item.ts ? new Date(item.ts) : new Date();
        var hhmm = now.toLocaleTimeString('en-US', {{timeZone:'America/New_York', hour:'2-digit', minute:'2-digit', hour12:false}});
        var row  = document.createElement('div');
        var _h = item.html;
        // Only flag as trade if it has the colored enter/exit spans (not just the word)
        var isTrade = (_h.indexOf('>enter<') !== -1 || _h.indexOf('>exit<') !== -1 ||
                       _h.indexOf('ENTER') !== -1 || _h.indexOf('EXIT') !== -1) &&
                      (_h.indexOf('@') !== -1); // must have a price
        if (isTrade) {{
          row.className = 'te te-trade';
          // Trade entries: flash bright, then dim to readable green after 3s
          row.style.color = '#00ff9d';
          setTimeout(function() {{
            row.style.transition = 'color 1.5s ease, text-shadow 1.5s ease';
            row.style.color = 'rgba(0,200,120,.45)';
            row.style.textShadow = 'none';
          }}, 3200);
        }} else {{
          row.className = 'te';
          row.style.color = '#00ff41';
          row.style.textShadow = '0 0 6px rgba(0,255,65,.5)';
          row.style.transition = 'color 1200ms ease, text-shadow 1200ms ease';
          // Fade to dim purple after flash
          requestAnimationFrame(function() {{
            requestAnimationFrame(function() {{
              row.style.color = '#6a4a8a';
              row.style.textShadow = 'none';
            }});
          }});
        }}
        row.innerHTML = '<span class="te-ts">' + hhmm + '&nbsp;&nbsp;</span>' + _h;
        if (tb) {{ tb.appendChild(row); tb.scrollTop = tb.scrollHeight; }}
        // Update "Xs ago" ticker on every new feed entry
        window._lastFeedEventMs = Date.now();
        _busy = false;
        if (_feedQueue.length) {{
          setTimeout(_drainQueue, 400);
        }} else {{
          startIdle();
        }}
      }});
    }}

    // Expose globally — trades, fills, deposits, pipeline events all call this
    window._postToFeed   = postToFeed;
    window._typeAtCursor = typeAtCursor;  // raw cursor typing (no feed append)

    // ── On load: type the latest System Feed entry through Status ─────────────
    var tb      = document.getElementById('term-body');
    var newest  = document.getElementById('te-newest');
    if (newest && tb) {{
      _busy = true;
      tb.scrollTop = tb.scrollHeight;
      var plainText = newest.textContent.replace(/\s+/g, ' ').trim();
      typeAtCursor(plainText, function() {{
        newest.style.transition = 'opacity 80ms ease, color 1400ms ease, text-shadow 1400ms ease';
        newest.style.opacity = '1';
        tb.scrollTop = tb.scrollHeight;
        requestAnimationFrame(function() {{
          requestAnimationFrame(function() {{
            newest.style.color = '#9060b8';
            newest.style.textShadow = 'none';
          }});
        }});
        _busy = false;
        startIdle();
      }});
    }} else {{
      startIdle();
    }}

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
    var _lastSeen = null;   // null = load history first, then switch to live

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
        rows.forEach(function(row) {{
          _lastSeen = row.recorded_at;
          var raw = row.message || '';
          var sym = row.symbol || '';
          var display;
          if (row.event_type === 'TRADE' && (raw.indexOf('ENTER') !== -1 || raw.indexOf('EXIT') !== -1)) {{
            var isEntry = raw.indexOf('ENTER') !== -1;
            // Sound — only on live events (not history replay)
            if (!isHistory) {{
              if (isEntry) {{ if (window._soundEntry) window._soundEntry(); }}
              else {{
                var pnlMsnd = raw.match(/pnl\s*([+-][\d,.]+)/);
                if (pnlMsnd && pnlMsnd[1][0] === '+') {{ if (window._soundWin) window._soundWin(); }}
                else {{ if (window._soundLoss) window._soundLoss(); }}
              }}
            }}
            // Flash the terminal border — live events only
            var ovl = !isHistory && document.getElementById('term-overlay');
            if (ovl) {{
              ovl.classList.remove('flash-entry','flash-exit');
              void ovl.offsetWidth; // force reflow to restart animation
              ovl.classList.add(isEntry ? 'flash-entry' : 'flash-exit');
              setTimeout(function() {{ ovl.classList.remove('flash-entry','flash-exit'); }}, 1300);
            }}
            var verbPlain = isEntry ? 'enter' : 'exit';
            var verbHtml  = isEntry ? '<span style="color:#00ff9d">enter</span>' : '<span style="color:#ff9900">exit</span>';
            var priceM    = raw.match(/@\s*\$([\d,]+(?:\.\d+)?)/);
            var priceS    = priceM ? ' @ $' + priceM[1] : '';
            var pnlM      = raw.match(/pnl\s*([+-][\d,.]+)/);
            var pnlCol    = pnlM && pnlM[1][0] === '+' ? '#00ff9d' : '#ff4444';
            var pnlHtml   = pnlM ? ' · pnl <span style="color:' + pnlCol + '">' + pnlM[1] + '</span>' : '';
            var plain     = verbPlain + ' ' + sym;
            var html      = verbHtml + ' ' + sym + priceS + pnlHtml;
            if (window._postToFeed) window._postToFeed(plain, _parseTs(row.recorded_at), html);
            // Trigger reason-aware exit animation on live events
            if (!isHistory && !isEntry && window._triggerCardExit) {{
              var reasonM = raw.match(/·\s*(target|stop|timeout|reversal|signal)\s*$/i);
              var exitReason = reasonM ? reasonM[1].toLowerCase() : (pnlM && pnlM[1][0] === '+' ? 'target' : 'stop');
              var pnlVal = pnlM ? parseFloat(pnlM[1].replace(/,/g,'')) : null;
              window._triggerCardExit(sym, exitReason, pnlVal);
            }}
            // Heartbeat spike on live trades
            if (!isHistory && window._triggerHeartbeat) {{
              var isWinTrade = isEntry ? true : (pnlM ? pnlM[1][0] === '+' : true);
              window._triggerHeartbeat(isWinTrade);
            }}
            // Gauge + streak + orb flash on live trades
            if (!isHistory) {{
              if (window._recordTradeForGauge) window._recordTradeForGauge();
              if (!isEntry && pnlM && window._recordStreakResult) {{
                window._recordStreakResult(pnlM[1][0] === '+');
              }}
              if (window._orbTradeFlash) window._orbTradeFlash(isEntry);
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
        }});
      }})
      .catch(function() {{}}); // silent — offline or auth issue
    }}

    // Wait for feed to initialise then start polling every 5s
    setTimeout(function() {{
      _poll();
      setInterval(_poll, 5000);
    }}, 3000);
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
        // Conditional fill only — portfolio line stays magenta always
        var aboveBase = nav >= 100000;
        Plotly.restyle(gd, {{ fillcolor: aboveBase ? 'rgba(0,255,157,0.09)' : 'rgba(255,51,102,0.09)' }}, [4]);
        Plotly.restyle(gd, {{ fillcolor: aboveBase ? 'rgba(0,255,157,0.04)' : 'rgba(255,51,102,0.04)' }}, [3]);
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

      // ── VHS tracking bar ──────────────────────────────────────────────────────
      var vhsBar  = document.getElementById('vhs-scan-bar');
      var vhsFill = document.getElementById('vhs-fill');
      if (!vhsBar || !vhsFill) return;

      // Show, reset, fill, hide
      vhsBar.classList.add('active');
      vhsFill.style.transition = 'none';
      vhsFill.style.width = '0%';

      requestAnimationFrame(function() {{
        requestAnimationFrame(function() {{
          vhsFill.style.transition = 'width 1.35s cubic-bezier(.15,.8,.35,1)';
          vhsFill.style.width = '100%';
        }});
      }});

      setTimeout(function() {{
        vhsFill.style.transition = 'width .22s ease-in';
        vhsFill.style.width = '0%';
        setTimeout(function() {{ vhsBar.classList.remove('active'); }}, 240);
      }}, 1650);
    }};

    // ── Video-game card exit ────────────────────────────────────────────────────
    function _spawnPnlGhost(el, pnl, sym) {{
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

      g.appendChild(symEl); g.appendChild(valEl); g.appendChild(lbl);
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
    // ── Equity card map — built from SSR DOM on load ────────────────────────────
    var _equityCardEls = {{}};
    function _buildEquityMap() {{
      document.querySelectorAll('#pos-equity-section .pos-card[data-sym]').forEach(function(el) {{
        _equityCardEls[el.getAttribute('data-sym')] = el;
      }});
    }}
    setTimeout(_buildEquityMap, 500);

    window._triggerCardExit = function(fullSym, reason, pnl) {{
      // Check crypto map first (fullSym may be "BTC/USD" or just "BTC"), then equity map
      var el = _cryptoCardEls[fullSym] || _cryptoCardEls[fullSym + '/USD']
             || _equityCardEls[fullSym];
      if (!el) return;
      // Remove from whichever map owns it
      if (_cryptoCardEls[fullSym]) delete _cryptoCardEls[fullSym];
      else if (_cryptoCardEls[fullSym + '/USD']) delete _cryptoCardEls[fullSym + '/USD'];
      else if (_equityCardEls[fullSym]) delete _equityCardEls[fullSym];
      el.classList.remove('pos-card-active');
      // Spawn ghost + particles immediately; collapse card after flash plays (280ms)
      _spawnPnlGhost(el, pnl, fullSym);
      var cls = _EXIT_CLASS[reason] || 'pos-card-exit-stop';
      var dur = _EXIT_DUR[reason] || 500;
      setTimeout(function() {{
        el.style.animation = '';  // clear flash so exit CSS can take over
        el.classList.add(cls);
        setTimeout(function() {{ if (el.parentNode) el.parentNode.removeChild(el); }}, dur);
      }}, 260);
    }};

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
      el.style.borderLeft = '3px solid ' + col;
      el.style.position = 'relative';
      el.style.overflow = 'hidden';
      el.style.transformOrigin = 'center top';
      var agePct  = Math.min(age / 12 * 100, 100);
      var ageBg   = agePct < 60 ? '#00ff9d' : agePct < 85 ? '#ff9900' : '#ff3366';
      // Corner brackets
      ['tl','tr','bl','br'].forEach(function(pos) {{
        var c = document.createElement('span');
        c.className = 'pos-corner ' + pos;
        c.style.borderColor = col;
        el.appendChild(c);
      }});
      // Acquired flash overlay
      var flash = document.createElement('div');
      flash.className = 'pos-acq-flash';
      flash.textContent = '⌐ ACQUIRED ¬';
      flash.style.color = col;
      el.appendChild(flash);
      // Live proximity meter (stop → current → target)
      var tgt = parseFloat(p.target_price || 0);
      var rangeHtml = '';
      if (tgt > 0 && entry > 0 && stop > 0) {{
        var tgtPct = ((tgt - entry)/entry*100).toFixed(1);
        rangeHtml = '<div class="pos-prox-wrap"'
          + ' data-entry="' + entry + '" data-stop="' + stop + '" data-target="' + tgt + '">'
          + '<div class="pos-prox-track">'
          + '<div class="pos-prox-fill" style="width:50%"></div>'
          + '<div class="pos-prox-cursor" style="left:50%"></div>'
          + '</div>'
          + '<div class="pos-prox-labels">'
          + '<span style="color:#ff3366">&#x25B6; stop ' + stopPct + '%</span>'
          + '<span class="pos-prox-live" id="prox-live-' + p.symbol.replace(/\//g,'-') + '">——</span>'
          + '<span style="color:#00ff9d">tgt +' + tgtPct + '% &#x25C0;</span>'
          + '</div>'
          + '</div>';
      }}
      var inner = document.createElement('div');
      inner.innerHTML = '<div class="pos-top">'
        + '<span class="pos-sym" style="color:' + col + '">···</span>'
        + '<span class="pos-qty">' + qtyStr + '</span>'
        + '<span class="pos-val" style="color:#cc00ff;font-size:10px">▲ LONG</span>'
        + wrHtml
        + '</div>'
        + '<div class="pos-hold active">··········</div>'
        + rangeHtml
        + '<div class="pos-age-bar"><div class="pos-age-fill" style="width:' + agePct + '%;background:' + ageBg + '"></div></div>';
      el.appendChild(inner);
      // Orchestrate entry: flash → scramble sym → resolve price
      var CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#@$%';
      function _scramble(domEl, target, ms) {{
        var steps = Math.ceil(ms/30); var f = 0;
        var iv = setInterval(function() {{
          f++;
          var out = '';
          for (var i = 0; i < target.length; i++) {{
            out += i / target.length < f / steps ? target[i] : CHARS[Math.floor(Math.random()*CHARS.length)];
          }}
          domEl.textContent = out;
          if (f >= steps) {{ domEl.textContent = target; clearInterval(iv); }}
        }}, 30);
      }}
      setTimeout(function() {{
        flash.classList.add('show');
        el.classList.add('pos-card-active');
        var symEl = inner.querySelector('.pos-sym');
        _scramble(symEl, p.symbol.replace('/USD',''), 280);
        var holdEl = inner.querySelector('.pos-hold');
        var holdTarget = '$' + entry.toFixed(entry < 0.01 ? 6 : 4) + ' · stop ' + stopPct + '%';
        setTimeout(function() {{ _scramble(holdEl, holdTarget, 220); }}, 150);
      }}, 90);
      return el;
    }}

    function _updateCard(el, p) {{
      var entry   = parseFloat(p.entry_price);
      var stop    = parseFloat(p.stop_price);
      var age     = p.entered_at ? (Date.now() - new Date(p.entered_at)) / 60000 : 0;
      var stopPct = entry > 0 ? ((stop - entry) / entry * 100).toFixed(1) : '—';
      var hold = el.querySelector('.pos-hold');
      if (hold) hold.textContent = '$' + entry.toFixed(entry < 0.01 ? 6 : 4) + ' · stop ' + stopPct + '%';
      var fill = el.querySelector('.pos-age-fill');
      if (fill) {{
        var agePct = Math.min(age / 12 * 100, 100);
        fill.style.width  = agePct + '%';
        fill.style.background = agePct < 60 ? '#00ff9d' : agePct < 85 ? '#ff9900' : '#ff3366';
      }}
    }}

    function _pollPositions() {{
      var url = SUPA_URL + '/rest/v1/crypto_positions'
        + '?select=symbol,direction,qty,entry_price,stop_price,target_price,entered_at'
        + '&order=entered_at.asc';
      fetch(url, {{
        headers: {{ 'apikey': SUPA_KEY, 'Authorization': 'Bearer ' + SUPA_KEY }}
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(rows) {{
        var section = document.getElementById('pos-crypto-section');
        if (!section) return;
        var flat = document.getElementById('pos-crypto-flat');

        // Expose positions map for dynamic queue timeout countdowns
        if (Array.isArray(rows) && rows.length) {{
          var newMap = {{}};
          rows.forEach(function(p) {{ newMap[p.symbol] = p; }});
          window._cryptoPositionsMap = newMap;
          window._cryptoPairCount    = 15; // universe size
        }} else {{
          window._cryptoPositionsMap = {{}};
        }}

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
            el.classList.add('pos-card-entering');
            section.appendChild(el);
            _cryptoCardEls[p.symbol] = el;
          }}
        }});

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
      setInterval(_pollPositions, 5000);
    }}, 2000);

    // ── Live crypto price poller — updates proximity meters in real time ──────
    var _BINANCE_SYM_MAP = {{
      'BTC/USD':'BTCUSDT','ETH/USD':'ETHUSDT','SOL/USD':'SOLUSDT',
      'AVAX/USD':'AVAXUSDT','LINK/USD':'LINKUSDT','DOGE/USD':'DOGEUSDT',
      'BCH/USD':'BCHUSDT','UNI/USD':'UNIUSDT','CRV/USD':'CRVUSDT',
      'ADA/USD':'ADAUSDT','MATIC/USD':'MATICUSDT','DOT/USD':'DOTUSDT',
    }};
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
      var openSyms = Object.keys(window._cryptoPositionsMap || {{}});
      if (!openSyms.length) return;
      var bSyms = openSyms.map(function(s) {{ return _BINANCE_SYM_MAP[s] || s.replace('/',''); }})
                          .filter(Boolean);
      if (!bSyms.length) return;
      var encoded = encodeURIComponent('["' + bSyms.join('","') + '"]');
      fetch('https://api.binance.com/api/v3/ticker/price?symbols=' + encoded)
        .then(function(r) {{ return r.json(); }})
        .then(function(rows) {{
          if (!Array.isArray(rows)) return;
          var priceMap = {{}};
          rows.forEach(function(r) {{
            var rev = Object.entries(_BINANCE_SYM_MAP).find(function(kv) {{ return kv[1] === r.symbol; }});
            if (rev) priceMap[rev[0]] = parseFloat(r.price);
          }});
          _updateProxMeters(priceMap);
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
            var ico = streakSign > 0 ? '🔥' : '☠';
            sv.textContent = ico + ' ' + streak + (streakSign > 0 ? 'W' : 'L');
            sv.style.color = streakSign > 0 ? '#00ff9d' : '#ff3366';
          }}
        }}
        // Win rate per symbol → store as map for _pollPositions to use
        window._winRates = {{}};
        rows.forEach(function(row) {{
          var sym = row.symbol || '';
          if (!window._winRates[sym]) window._winRates[sym] = {{w:0,t:0}};
          window._winRates[sym].t++;
          if (row.message.indexOf('✓') !== -1) window._winRates[sym].w++;
        }});
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
        var el = document.getElementById('runner-trades');
        if (el && Array.isArray(rows)) el.textContent = rows.length + ' trades today';
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
          var agePct = Math.min(age / 12 * 100, 100);
          fill.style.width = agePct + '%';
          fill.style.background = agePct < 60 ? '#00ff9d' : agePct < 85 ? '#ff9900' : '#ff3366';
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
