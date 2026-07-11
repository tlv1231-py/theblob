"""Daytrader — MFIM live session monitor."""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import datetime as _dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import text

_ROOT = Path(__file__).resolve().parent.parent.parent
_ET   = ZoneInfo("America/New_York")

_BG   = "#06070a"
_BG2  = "#0b0d12"
_GRID = "#161924"
_TEXT = "#7a8499"
_GRN  = "#00ff9d"
_CYN  = "#00b4d8"
_RED  = "#ff4560"
_ORG  = "#ffb340"


def _dark_layout(**kw) -> dict:
    base = dict(
        paper_bgcolor=_BG, plot_bgcolor=_BG2,
        font=dict(family="Consolas,'Courier New',monospace", color=_TEXT, size=11),
        xaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID, tickfont=dict(size=10)),
        yaxis=dict(gridcolor=_GRID, zerolinecolor=_GRID, tickfont=dict(size=10)),
        margin=dict(l=40, r=16, t=24, b=24),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=10)),
    )
    base.update(kw)
    return base


# ── DB ────────────────────────────────────────────────────────────────────────

def _session():
    try:
        from data.database import get_session
        return get_session()
    except ImportError:
        from dashboard.db import get_session
        return get_session()


def _today_fills() -> pd.DataFrame:
    today = _dt.datetime.now(_ET).date().isoformat()
    try:
        with _session() as s:
            rows = s.execute(text("""
                SELECT f.fill_id, f.symbol, f.side, f.quantity,
                       f.fill_price, f.filled_at
                FROM fills f
                JOIN orders o ON f.order_id = o.order_id
                WHERE o.strategy = 'daytrader'
                  AND DATE(f.filled_at AT TIME ZONE 'America/New_York') = :today
                ORDER BY f.filled_at
            """), {"today": today}).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["fill_id","symbol","side","qty","fill_price","filled_at"])
        df["filled_at"] = pd.to_datetime(df["filled_at"]).dt.tz_convert("America/New_York")
        return df
    except Exception:
        return pd.DataFrame()


def _all_fills() -> pd.DataFrame:
    try:
        with _session() as s:
            rows = s.execute(text("""
                SELECT f.symbol, f.side, f.quantity, f.fill_price, f.filled_at
                FROM fills f JOIN orders o ON f.order_id = o.order_id
                WHERE o.strategy = 'daytrader'
                ORDER BY f.filled_at
            """)).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["symbol","side","qty","fill_price","filled_at"])
        df["filled_at"] = pd.to_datetime(df["filled_at"]).dt.tz_convert("America/New_York")
        return df
    except Exception:
        return pd.DataFrame()


def _calc_pnl(fills: pd.DataFrame) -> tuple[float, int, int]:
    """Returns (total_pnl, trades, wins)."""
    if fills.empty:
        return 0.0, 0, 0
    buys  = fills[fills["side"] == "buy"]
    sells = fills[fills["side"] == "sell"]
    pnl, trades, wins = 0.0, 0, 0
    for sym in sells["symbol"].unique():
        sb = buys[buys["symbol"] == sym]
        ss = sells[sells["symbol"] == sym]
        if sb.empty:
            continue
        avg_e = (sb["fill_price"] * sb["qty"]).sum() / sb["qty"].sum()
        for _, row in ss.iterrows():
            p = (row["fill_price"] - avg_e) * row["qty"]
            pnl += p; trades += 1
            if p > 0: wins += 1
    return pnl, trades, wins


def _open_positions(fills: pd.DataFrame) -> pd.DataFrame:
    if fills.empty:
        return pd.DataFrame()
    pos: dict = {}
    for _, r in fills.iterrows():
        sym = r["symbol"]
        if r["side"] == "buy":
            if sym not in pos:
                pos[sym] = {"symbol": sym, "shares": 0, "entry": 0.0, "entered_at": r["filled_at"]}
            pos[sym]["shares"] += r["qty"]
            pos[sym]["entry"]   = r["fill_price"]
        elif r["side"] == "sell" and sym in pos:
            pos[sym]["shares"] -= r["qty"]
            if pos[sym]["shares"] <= 0:
                del pos[sym]
    return pd.DataFrame(list(pos.values())) if pos else pd.DataFrame()


# ── Terminal ──────────────────────────────────────────────────────────────────

def _classify(line: str) -> str:
    l = line.lower()
    if any(k in l for k in ("entry", "buy", "long", "short", "fill")):   return "grn"
    if any(k in l for k in ("t1 hit", "t2 hit", "exit", "p&l", "profit")): return "cyn"
    if any(k in l for k in ("stop hit", "loss", "halt", "block", "error", "traceback")): return "red"
    if any(k in l for k in ("warn", "skip", "rvol", "vwap", "retry", "cooldown")): return "org"
    if any(k in l for k in ("debug",)):                                    return "dim"
    return "mid"


def _render_terminal(lines: list[str], finished: bool) -> None:
    color_map = {
        "grn": _GRN, "cyn": _CYN, "red": _RED,
        "org": _ORG, "dim": "#323849", "mid": _TEXT,
    }
    rows = []
    for raw in lines[-300:]:
        clean = raw.strip()
        if " | " in clean:
            parts = clean.split(" | ")
            clean = parts[-1] if len(parts) >= 3 else clean
        if not clean:
            continue
        col = color_map.get(_classify(clean), _TEXT)
        import html as _h
        rows.append(f'<span style="color:{col}">{_h.escape(clean)}</span>')

    body   = "<br>".join(rows) or '<span style="color:#323849">waiting for output…</span>'
    cursor = "" if finished else '<span style="color:#00ff9d;animation:blink 1s step-end infinite">_</span>'

    st.markdown(f"""
    <style>
    @keyframes blink {{ 50% {{ opacity:0; }} }}
    .blob-term {{
        background:#040508;
        border:1px solid #161924;
        padding:16px 18px;
        font-family:Consolas,'Courier New',monospace;
        font-size:0.72rem;
        line-height:1.65;
        max-height:480px;
        overflow-y:auto;
        color:{_TEXT};
        scrollbar-width:thin;
    }}
    </style>
    <div class="blob-term" id="blob-term">{body}{cursor}</div>
    <script>
    (function(){{
        var el = document.getElementById("blob-term");
        if (el) el.scrollTop = el.scrollHeight;
    }})();
    </script>
    """, unsafe_allow_html=True)


# ── Subprocess management ─────────────────────────────────────────────────────

def _reader_thread(stdout, q: queue.SimpleQueue) -> None:
    try:
        for line in stdout:
            q.put(line)
    finally:
        q.put(None)


def _start_session() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-u", str(_ROOT / "run_daytrader.py"), "--mode", "live"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=str(_ROOT),
    )
    q: queue.SimpleQueue = queue.SimpleQueue()
    threading.Thread(target=_reader_thread, args=(proc.stdout, q), daemon=True).start()
    st.session_state.update(dt_proc=proc, dt_queue=q, dt_lines=[], dt_running=True)


def _stop_session() -> None:
    proc = st.session_state.get("dt_proc")
    if proc and proc.poll() is None:
        proc.terminate()
    st.session_state.update(dt_running=False, dt_proc=None, dt_stopped_at=time.time())


def _poll() -> None:
    q: queue.SimpleQueue | None = st.session_state.get("dt_queue")
    if not q:
        return
    lines = st.session_state.setdefault("dt_lines", [])
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if item is None:
            st.session_state["dt_running"] = False
            break
        lines.append(item)


# ── Session window helpers ────────────────────────────────────────────────────

def _next_open(now: _dt.datetime) -> _dt.datetime:
    candidate = now.replace(hour=9, minute=30, second=0, microsecond=0)
    if now >= candidate:
        candidate += _dt.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += _dt.timedelta(days=1)
    return candidate


def _fmt_countdown(secs: float) -> str:
    s = int(secs)
    h, rem = divmod(s, 3600)
    m, s   = divmod(rem, 60)
    if h:    return f"{h}h {m}m"
    if m:    return f"{m}m {s}s"
    return f"{s}s"


# ── Trade event feed ──────────────────────────────────────────────────────────

def _trade_feed(fills: pd.DataFrame) -> None:
    """Render a vertical feed of trade events, newest first."""
    if fills.empty:
        st.markdown(
            f'<p style="color:{_TEXT};font-size:0.75rem;padding:12px 0;">No trades today.</p>',
            unsafe_allow_html=True,
        )
        return

    events = []
    buys  = fills[fills["side"] == "buy"].copy()
    sells = fills[fills["side"] == "sell"].copy()

    for _, r in fills.iterrows():
        sym   = r["symbol"]
        side  = r["side"]
        price = r["fill_price"]
        t     = r["filled_at"].strftime("%H:%M:%S")
        qty   = int(r["qty"])

        if side == "buy":
            sb = buys[buys["symbol"] == sym]
            avg_e = (sb["fill_price"] * sb["qty"]).sum() / sb["qty"].sum() if not sb.empty else price
            events.append({
                "time": t, "sym": sym, "label": "ENTRY LONG",
                "detail": f"{qty} shares @ ${price:.2f}",
                "color": _GRN, "pnl": None,
            })
        else:
            sb = buys[buys["symbol"] == sym]
            avg_e = (sb["fill_price"] * sb["qty"]).sum() / sb["qty"].sum() if not sb.empty else price
            pnl = (price - avg_e) * qty
            color = _GRN if pnl >= 0 else _RED
            sign  = "+" if pnl >= 0 else ""
            events.append({
                "time": t, "sym": sym, "label": "EXIT",
                "detail": f"{qty} shares @ ${price:.2f}",
                "color": color, "pnl": f"{sign}${pnl:,.2f}",
            })

    html = []
    for ev in reversed(events):
        pnl_html = (
            f'<span style="color:{ev["color"]};font-weight:700;margin-left:auto;">{ev["pnl"]}</span>'
            if ev["pnl"] else ""
        )
        html.append(f"""
        <div style="display:flex;align-items:center;gap:12px;padding:10px 14px;
                    border-left:2px solid {ev["color"]};background:{_BG2};
                    margin-bottom:4px;">
            <span style="color:{_TEXT};font-size:0.65rem;min-width:60px;">{ev["time"]}</span>
            <span style="color:{ev["color"]};font-size:0.68rem;font-weight:700;
                         letter-spacing:0.08em;min-width:90px;">{ev["label"]}</span>
            <span style="color:#eceef4;font-size:0.78rem;font-weight:700;min-width:50px;">{ev["sym"]}</span>
            <span style="color:{_TEXT};font-size:0.72rem;">{ev["detail"]}</span>
            {pnl_html}
        </div>""")

    st.markdown(
        f'<div style="max-height:320px;overflow-y:auto;">{"".join(html)}</div>',
        unsafe_allow_html=True,
    )


# ── Replay subprocess ─────────────────────────────────────────────────────────

_SCENARIOS = {
    "Custom":            (None, None),
    "2024 Bull Run":     ("2024-01-01", "2024-12-31"),
    "2023 Recovery":     ("2023-01-01", "2023-12-31"),
    "2022 Bear Market":  ("2022-01-01", "2022-12-31"),
    "2020 COVID Crash":  ("2020-01-15", "2020-06-30"),
    "2018 Q4 Selloff":   ("2018-09-01", "2018-12-31"),
}

_ALL_SYMBOLS = [
    "SPY","QQQ","IWM","AAPL","MSFT","NVDA","AMZN","META","GOOGL",
    "TSLA","AMD","AVGO","JPM","GS","XLE","GLD","TLT",
]

def _start_replay(start: str, end: str, symbols: list[str]) -> None:
    sym_arg = ",".join(symbols)
    proc = subprocess.Popen(
        [sys.executable, "-u", str(_ROOT / "run_daytrader.py"),
         "--mode", "backtest", "--start", start, "--end", end,
         "--symbols", sym_arg],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, cwd=str(_ROOT),
    )
    q: queue.SimpleQueue = queue.SimpleQueue()
    threading.Thread(target=_reader_thread, args=(proc.stdout, q), daemon=True).start()
    st.session_state.update(
        rp_proc=proc, rp_queue=q, rp_lines=[], rp_running=True,
        rp_start=start, rp_end=end,
    )


def _stop_replay() -> None:
    proc = st.session_state.get("rp_proc")
    if proc and proc.poll() is None:
        proc.terminate()
    st.session_state.update(rp_running=False, rp_proc=None)


def _poll_replay() -> None:
    q = st.session_state.get("rp_queue")
    if not q:
        return
    lines = st.session_state.setdefault("rp_lines", [])
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if item is None:
            st.session_state["rp_running"] = False
            break
        lines.append(item)


def _parse_replay_results(lines: list[str]) -> dict | None:
    """Extract final metrics from backtest terminal output."""
    for line in reversed(lines):
        if "Trades:" in line and "Win rate:" in line:
            import re
            m = re.search(
                r"Trades:\s*(\d+).*?Win rate:\s*([\d.]+)%.*?"
                r"Total P&L:\s*\$([+\-\d,.]+).*?CAGR:\s*([+\-\d.]+)%.*?"
                r"Sharpe:\s*([+\-\d.nan]+).*?Max DD:\s*([+\-\d.]+)%",
                line,
            )
            if m:
                return {
                    "trades":   int(m.group(1)),
                    "win_rate": float(m.group(2)) / 100,
                    "pnl":      float(m.group(3).replace(",", "")),
                    "cagr":     float(m.group(4)) / 100,
                    "sharpe":   float(m.group(5)) if m.group(5) != "nan" else float("nan"),
                    "max_dd":   float(m.group(6)) / 100,
                }
    return None


# ── Main render ───────────────────────────────────────────────────────────────

def render() -> None:

    # Init live state
    for k, v in [("dt_running",False),("dt_proc",None),
                  ("dt_queue",None),("dt_lines",[]),("dt_stopped_at",None)]:
        st.session_state.setdefault(k, v)

    # Init replay state
    for k, v in [("rp_running",False),("rp_proc",None),
                  ("rp_queue",None),("rp_lines",[]),
                  ("rp_start",None),("rp_end",None)]:
        st.session_state.setdefault(k, v)

    _poll()
    _poll_replay()

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown(
        '<h1 style="margin-bottom:4px;">MFIM Daytrader</h1>',
        unsafe_allow_html=True,
    )

    tab_live, tab_replay = st.tabs(["Live Session", "Historical Replay"])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — LIVE
    # ══════════════════════════════════════════════════════════════════════════
    with tab_live:
        running    = st.session_state["dt_running"]
        lines      = st.session_state["dt_lines"]
        now        = _dt.datetime.now(_ET)
        is_weekday = now.weekday() < 5

        range_start  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
        range_cutoff = now.replace(hour=9,  minute=45, second=0, microsecond=0)
        window_open  = is_weekday and range_start <= now <= range_cutoff
        after_cutoff = is_weekday and now > range_cutoff
        before_open  = is_weekday and now < range_start

        _COOLDOWN    = 180
        stopped_at   = st.session_state.get("dt_stopped_at")
        cooldown_rem = max(0, int(_COOLDOWN - (time.time() - stopped_at))) if stopped_at and not running else 0
        secs_to_open = max(0, (_next_open(now) - now).total_seconds())

        # Status + controls
        if running:
            status_html = f'<span class="live-dot"></span><span style="color:{_GRN};font-size:0.68rem;font-weight:700;letter-spacing:0.12em;">LIVE</span>'
        elif window_open:
            status_html = f'<span style="color:{_CYN};font-size:0.68rem;font-weight:700;letter-spacing:0.12em;">WINDOW OPEN</span>'
        elif after_cutoff:
            status_html = f'<span style="color:{_TEXT};font-size:0.68rem;letter-spacing:0.1em;">MARKET CLOSED</span>'
        else:
            status_html = f'<span style="color:{_TEXT};font-size:0.68rem;letter-spacing:0.1em;">PRE-MARKET</span>'

        h1, h2, h3 = st.columns([3, 1, 1])
        with h1:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:16px;padding:6px 0 14px;">'
                f'<span style="display:flex;align-items:center;gap:6px;">{status_html}</span>'
                f'<span style="color:{_TEXT};font-size:0.68rem;">{now.strftime("%Y-%m-%d  %H:%M:%S ET")}</span>'
                f'</div>', unsafe_allow_html=True,
            )
        with h2:
            if running:
                if st.button("Stop Session", use_container_width=True):
                    _stop_session(); st.rerun()
            elif cooldown_rem > 0:
                st.button(f"Cooldown {cooldown_rem}s", disabled=True, use_container_width=True)
            elif after_cutoff or not is_weekday:
                st.button(f"Opens in {_fmt_countdown(secs_to_open)}", disabled=True, use_container_width=True)
            elif before_open:
                st.button(f"Opens in {_fmt_countdown(secs_to_open)}", disabled=True, use_container_width=True)
            else:
                if st.button("Start Live Session", type="primary", use_container_width=True):
                    _start_session(); st.rerun()
        with h3:
            if st.button("Refresh", use_container_width=True):
                st.rerun()

        # KPIs
        today_fills = _today_fills()
        open_pos    = _open_positions(today_fills)
        today_pnl, trades, wins = _calc_pnl(today_fills)
        all_f       = _all_fills()
        total_pnl, _, _ = _calc_pnl(all_f)
        win_rate    = wins / trades if trades else 0.0

        k1,k2,k3,k4,k5 = st.columns(5)
        with k1: st.metric("Today P&L",     f'{"+" if today_pnl>=0 else ""}${today_pnl:,.2f}')
        with k2: st.metric("Trades",         str(trades))
        with k3: st.metric("Win Rate",        f"{win_rate:.0%}" if trades else "—")
        with k4: st.metric("Open Positions",  str(len(open_pos) if not open_pos.empty else 0))
        with k5: st.metric("All-Time P&L",   f'{"+" if total_pnl>=0 else ""}${total_pnl:,.2f}')

        st.divider()

        left, right = st.columns([1, 1], gap="large")
        with left:
            st.markdown("### Open Positions")
            if open_pos.empty:
                st.markdown(f'<p style="color:{_TEXT};font-size:0.75rem;padding:8px 0 0;">Flat — no open positions.</p>', unsafe_allow_html=True)
            else:
                for _, row in open_pos.iterrows():
                    st.markdown(f"""
                    <div style="background:{_BG2};border:1px solid {_GRID};border-left:2px solid {_GRN};
                                padding:12px 16px;margin-bottom:6px;display:flex;align-items:center;gap:16px;">
                        <span style="color:{_GRN};font-size:0.9rem;font-weight:700;">{row['symbol']}</span>
                        <span style="color:{_TEXT};font-size:0.7rem;">LONG</span>
                        <span style="color:#eceef4;font-size:0.8rem;">{int(row['shares'])} shares</span>
                        <span style="color:{_TEXT};font-size:0.72rem;">@ ${row['entry']:.2f}</span>
                        <span style="color:{_TEXT};font-size:0.65rem;margin-left:auto;">{row['entered_at'].strftime('%H:%M:%S')}</span>
                    </div>""", unsafe_allow_html=True)
        with right:
            st.markdown("### Trade Feed")
            _trade_feed(today_fills)

        st.divider()

        # Intraday curve
        sells = today_fills[today_fills["side"]=="sell"] if not today_fills.empty else pd.DataFrame()
        if not sells.empty:
            st.markdown("### Intraday P&L")
            buys = today_fills[today_fills["side"]=="buy"]
            rows = []
            for sym in sells["symbol"].unique():
                sb = buys[buys["symbol"]==sym]; ss = sells[sells["symbol"]==sym]
                if sb.empty: continue
                avg_e = (sb["fill_price"]*sb["qty"]).sum() / sb["qty"].sum()
                for _, r in ss.iterrows():
                    rows.append({"time": r["filled_at"], "pnl": (r["fill_price"]-avg_e)*r["qty"]})
            if rows:
                curve = pd.DataFrame(rows).sort_values("time")
                curve["cum"] = curve["pnl"].cumsum()
                last = curve["cum"].iloc[-1]
                lc = _GRN if last >= 0 else _RED
                fc = "rgba(0,255,157,0.06)" if last >= 0 else "rgba(255,69,96,0.06)"
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=curve["time"], y=curve["cum"], mode="lines+markers",
                    line=dict(color=lc, width=2),
                    marker=dict(color=[_GRN if v>=0 else _RED for v in curve["cum"]], size=7),
                    fill="tozeroy", fillcolor=fc,
                ))
                fig.add_hline(y=0, line_color=_GRID, line_width=1)
                fig.update_layout(**_dark_layout(height=180))
                st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Live Terminal")
        _render_terminal(lines, finished=not running)

        if running or cooldown_rem > 0 or before_open:
            time.sleep(3); st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — HISTORICAL REPLAY
    # ══════════════════════════════════════════════════════════════════════════
    with tab_replay:
        rp_running = st.session_state["rp_running"]
        rp_lines   = st.session_state["rp_lines"]

        st.markdown(
            f'<p style="color:{_TEXT};font-size:0.75rem;margin-bottom:16px;">'
            f'Replay historical minute bars through the MFIM strategy. '
            f'Bars are fetched from Alpaca and cached locally — first run per date range downloads data, '
            f'subsequent runs are instant.</p>',
            unsafe_allow_html=True,
        )

        # ── Controls ──────────────────────────────────────────────────────────
        c1, c2 = st.columns([1, 2])

        with c1:
            scenario = st.selectbox("Scenario", list(_SCENARIOS.keys()), disabled=rp_running)
            preset_start, preset_end = _SCENARIOS[scenario]

        with c2:
            d1, d2 = st.columns(2)
            default_start = _dt.date.fromisoformat(preset_start) if preset_start else _dt.date(2024, 1, 1)
            default_end   = _dt.date.fromisoformat(preset_end)   if preset_end   else _dt.date(2024, 12, 31)
            with d1:
                start_date = st.date_input("Start", value=default_start, disabled=rp_running)
            with d2:
                end_date   = st.date_input("End",   value=default_end,   disabled=rp_running)

        symbols = st.multiselect(
            "Symbols",
            options=_ALL_SYMBOLS,
            default=["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA"],
            disabled=rp_running,
        )

        r1, r2, _ = st.columns([1, 1, 3])
        with r1:
            if not rp_running:
                can_run = bool(symbols) and start_date < end_date
                if st.button("Run Replay", type="primary", use_container_width=True, disabled=not can_run):
                    _start_replay(str(start_date), str(end_date), symbols)
                    st.rerun()
            else:
                if st.button("Stop", use_container_width=True):
                    _stop_replay(); st.rerun()
        with r2:
            if rp_lines:
                if st.button("Clear", use_container_width=True):
                    st.session_state["rp_lines"] = []; st.rerun()

        st.divider()

        # ── Results summary (shown when complete) ──────────────────────────────
        if rp_lines and not rp_running:
            results = _parse_replay_results(rp_lines)
            if results:
                st.markdown("### Results")
                r1,r2,r3,r4,r5,r6 = st.columns(6)
                pnl_sign = "+" if results["pnl"] >= 0 else ""
                with r1: st.metric("Total P&L",  f'{pnl_sign}${results["pnl"]:,.0f}')
                with r2: st.metric("CAGR",        f'{results["cagr"]:+.1%}')
                with r3: st.metric("Sharpe",      f'{results["sharpe"]:.2f}' if results["sharpe"]==results["sharpe"] else "—")
                with r4: st.metric("Max DD",      f'{results["max_dd"]:.1%}')
                with r5: st.metric("Win Rate",    f'{results["win_rate"]:.0%}')
                with r6: st.metric("Trades",      str(results["trades"]))
                st.divider()

        # ── Replay terminal ────────────────────────────────────────────────────
        if rp_lines or rp_running:
            label = "Replay Running..." if rp_running else f"Replay Complete — {st.session_state.get('rp_start')} to {st.session_state.get('rp_end')}"
            st.markdown(
                f'<p style="color:{_GRN if rp_running else _TEXT};font-size:0.65rem;'
                f'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px;">{label}</p>',
                unsafe_allow_html=True,
            )
            _render_terminal(rp_lines, finished=not rp_running)
        else:
            st.markdown(
                f'<div style="background:{_BG2};border:1px solid {_GRID};padding:32px;'
                f'text-align:center;color:{_TEXT};font-size:0.78rem;">'
                f'Select a scenario or date range and hit Run Replay.</div>',
                unsafe_allow_html=True,
            )

        if rp_running:
            time.sleep(2); st.rerun()
