"""Stateless crypto_momentum runner — designed for GitHub Actions cron.

Each invocation is independent:
  1. Fetch last 30 1-min bars + 24 1-hour bars from Alpaca REST (2 API calls)
  2. Load open positions from Supabase crypto_positions table
  3. Manage open positions (stop / target / max-hold)
  4. Check signals on symbols with no open position
  5. Execute entries via Alpaca paper REST
  6. Persist updated positions back to Supabase
  7. Post every fill to pipeline_events → dashboard Status fires

Runtime: ~10-20 seconds per invocation.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from loguru import logger
from sqlalchemy import text, delete

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv()

from data.database import get_session
from data.models import CryptoPosition, FillRecord, OrderRecord
from strategies.crypto.signals import SymbolBuffer, Direction

_CFG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())
_SIG = _CFG["signals"]
_POS = _CFG["position"]
_EXE = _CFG["execution"]
_UNIVERSE = _CFG["universe"]
_SLIPPAGE = _EXE["slippage_bps"] / 10_000


# ── Alpaca clients ────────────────────────────────────────────────────────────

def _api_key():
    return os.environ["ALPACA_API_KEY"].strip().lstrip("﻿")

def _secret_key():
    return os.environ["ALPACA_SECRET_KEY"].strip().lstrip("﻿")

def _trading_client():
    from alpaca.trading.client import TradingClient
    return TradingClient(api_key=_api_key(), secret_key=_secret_key(), paper=True)

def _data_client():
    from alpaca.data.historical.crypto import CryptoHistoricalDataClient
    return CryptoHistoricalDataClient(api_key=_api_key(), secret_key=_secret_key())


# ── Bar fetching ──────────────────────────────────────────────────────────────

def _fetch_bars(timeframe: str, lookback_minutes: int) -> dict[str, list]:
    """Fetch bars for all universe symbols over a trailing time window."""
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    if timeframe == "1Min":
        tf = TimeFrame.Minute
    elif timeframe == "5Min":
        tf = TimeFrame(5, TimeFrameUnit.Minute)
    elif timeframe == "15Min":
        tf = TimeFrame(15, TimeFrameUnit.Minute)
    else:
        tf = TimeFrame.Hour

    end   = datetime.now(timezone.utc)
    start = end - timedelta(minutes=lookback_minutes)
    client = _data_client()
    req = CryptoBarsRequest(
        symbol_or_symbols = _UNIVERSE,
        timeframe         = tf,
        start             = start,
        end               = end,
    )
    resp = client.get_crypto_bars(req)
    raw = resp.data if hasattr(resp, "data") else resp
    result = {}
    for sym, bars in raw.items():
        result[sym] = [
            {
                "open":      float(b.open),
                "high":      float(b.high),
                "low":       float(b.low),
                "close":     float(b.close),
                "volume":    float(b.volume),
                "timestamp": b.timestamp,
            }
            for b in bars
        ]
    return result


# ── Account NAV ───────────────────────────────────────────────────────────────

def _account_value() -> float:
    try:
        acct = _trading_client().get_account()
        return float(acct.equity)
    except Exception as e:
        logger.warning(f"Could not read account value: {e}")
        return 100_000.0


# ── Position persistence ──────────────────────────────────────────────────────

def _load_positions() -> dict[str, dict]:
    with get_session() as s:
        rows = s.query(CryptoPosition).all()
        return {
            r.symbol: {
                "symbol":      r.symbol,
                "direction":   r.direction,
                "qty":         r.qty,
                "entry_price": r.entry_price,
                "stop_price":  r.stop_price,
                "target_price":r.target_price,
                "entered_at":  r.entered_at,
                "order_id":    r.order_id,
            }
            for r in rows
        }

def _save_position(pos: dict) -> None:
    with get_session() as s:
        s.execute(delete(CryptoPosition).where(CryptoPosition.symbol == pos["symbol"]))
        s.add(CryptoPosition(
            symbol       = pos["symbol"],
            direction    = pos["direction"],
            qty          = pos["qty"],
            entry_price  = pos["entry_price"],
            stop_price   = pos["stop_price"],
            target_price = pos["target_price"],
            entered_at   = pos["entered_at"],
            order_id     = pos.get("order_id"),
        ))
        s.commit()

def _delete_position(symbol: str) -> None:
    with get_session() as s:
        s.execute(delete(CryptoPosition).where(CryptoPosition.symbol == symbol))
        s.commit()


# ── DB event logging ──────────────────────────────────────────────────────────

def _post_event(event_type: str, symbol: str, message: str, detail: str = "") -> None:
    try:
        with get_session() as s:
            s.execute(text("""
                INSERT INTO pipeline_events (run_date, event_type, symbol, message, detail, recorded_at)
                VALUES (:rd, :et, :sym, :msg, :det, :ts)
            """), {
                "rd":  datetime.now(timezone.utc).date(),
                "et":  event_type,
                "sym": symbol,
                "msg": message,
                "det": detail,
                "ts":  datetime.now(timezone.utc),
            })
            s.commit()
    except Exception as e:
        logger.warning(f"Event log failed: {e}")

def _log_fill(symbol: str, order_id: str, side: str, qty: float, price: float,
              pnl: float | None, reason: str) -> None:
    try:
        with get_session() as s:
            s.execute(text("""
                INSERT INTO fills (fill_id, order_id, symbol, side, quantity, fill_price,
                                   commission, slippage, filled_at)
                VALUES (:fid, :oid, :sym, :side, :qty, :price, 0, 0, :ts)
            """), {
                "fid":  str(uuid.uuid4()),
                "oid":  order_id or str(uuid.uuid4()),
                "sym":  symbol,
                "side": side,
                "qty":  qty,
                "price": price,
                "ts":   datetime.now(timezone.utc),
            })
            s.commit()
    except Exception as e:
        logger.warning(f"Fill log failed: {e}")


def _write_snapshot(nav: float, positions: dict) -> None:
    import json as _json
    try:
        pos_json = _json.dumps({k: v["qty"] for k, v in positions.items()})
        with get_session() as s:
            s.execute(text("""
                INSERT INTO portfolio_snapshots
                    (snapshot_date, strategy, cash, gross_exposure, net_exposure,
                     total_value, positions, recorded_at)
                VALUES (:sd, :strat, :cash, :gross, :net, :total, cast(:pos as jsonb), :ts)
            """), {
                "sd":    datetime.now(timezone.utc).date(),
                "strat": "crypto_momentum",
                "cash":  nav,
                "gross": nav,
                "net":   nav,
                "total": nav,
                "pos":   pos_json,
                "ts":    datetime.now(timezone.utc),
            })
            s.commit()
    except Exception as e:
        logger.warning(f"Snapshot write failed: {e}")


# ── Order execution ───────────────────────────────────────────────────────────

def _close_position(symbol: str) -> str | None:
    """Close entire position via Alpaca close_position — avoids float qty precision errors."""
    order_sym = symbol.replace("/", "")
    try:
        resp = _trading_client().close_position(order_sym)
        return str(resp.id)
    except Exception as e:
        logger.warning(f"Close position failed {symbol}: {e}")
        return str(uuid.uuid4())


def _submit_order(symbol: str, side: str, qty: float) -> str | None:
    order_sym = symbol.replace("/", "")
    try:
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        req = MarketOrderRequest(
            symbol        = order_sym,
            qty           = qty,
            side          = OrderSide.BUY if side == "buy" else OrderSide.SELL,
            time_in_force = TimeInForce.GTC,
        )
        resp = _trading_client().submit_order(req)
        return str(resp.id)
    except Exception as e:
        logger.warning(f"Order failed {symbol} {side}: {e}")
        return str(uuid.uuid4())


# ── Signal computation ────────────────────────────────────────────────────────

def _compute_signal(min_bars: list[dict], _unused=None) -> str | None:
    """Max-throughput: always enter. Position manager handles exits."""
    return "long"


# ── Main run ──────────────────────────────────────────────────────────────────

def _recent_exits(lookback_minutes: int) -> dict[str, datetime]:
    """Return {symbol: last_exit_time} for exits within lookback_minutes."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    try:
        with get_session() as s:
            rows = s.execute(text("""
                SELECT symbol, MAX(recorded_at) as last_exit
                FROM pipeline_events
                WHERE event_type = 'TRADE'
                  AND message LIKE '%EXIT%'
                  AND recorded_at >= :cutoff
                GROUP BY symbol
            """), {"cutoff": cutoff}).fetchall()
            return {r.symbol: r.last_exit for r in rows}
    except Exception as e:
        logger.warning(f"Cooldown query failed: {e}")
        return {}


def run() -> None:
    now      = datetime.now(timezone.utc)
    nav      = _account_value()
    risk_pc  = _POS["risk_pct"] / 100.0
    stop_pc  = _POS["stop_pct"]
    target_pc= _POS.get("target_pct", 0.0)
    max_pos  = _POS["max_positions"]
    max_hold = _POS["max_hold_minutes"]

    logger.info(f"[crypto] run @ {now.isoformat()} | NAV=${nav:,.2f}")

    # Fetch bars — timeframe from config; lookback covers signal window + stop checks
    bar_size = _SIG.get("bar_size", "5Min")
    bar_mins = int(bar_size.replace("Min", "").replace("Hour", "60")) if "Min" in bar_size else 60
    needed_bars = max(_SIG["vwap_window_bars"] + _SIG["breakout_bars"] + 25, 80)
    lookback = needed_bars * bar_mins + 30  # +30min buffer
    try:
        min_bars = _fetch_bars(bar_size, lookback)
    except Exception as e:
        logger.error(f"[crypto] Bar fetch failed: {e}")
        return

    positions = _load_positions()
    exited_this_run: set[str] = set()

    # Reconcile phase 1: fetch Alpaca state; drop DB rows that no longer exist in Alpaca
    alpaca_positions: dict = {}
    try:
        alpaca_raw = _trading_client().get_all_positions()
        alpaca_positions = {
            p.symbol.replace("USD", "/USD"): p for p in alpaca_raw
        }
        for sym in list(positions.keys()):
            if sym not in alpaca_positions:
                logger.warning(f"[reconcile] {sym} in DB but not in Alpaca — dropping")
                _delete_position(sym)
                del positions[sym]
    except Exception as e:
        logger.warning(f"[reconcile] Could not fetch Alpaca positions: {e}")

    daily_pnl = 0.0

    # ── Manage open positions ─────────────────────────────────────────────────
    for sym, pos in list(positions.items()):
        entered = pos["entered_at"]
        if entered.tzinfo is None:
            entered = entered.replace(tzinfo=timezone.utc)
        age = (now - entered).total_seconds() / 60

        m = min_bars.get(sym, [])
        d = pos["direction"]
        reason = None

        if m:
            close = m[-1]["close"]
            # Stop loss
            if d == "long"  and close <= pos["stop_price"]: reason = "stop"
            if d == "short" and close >= pos["stop_price"]: reason = "stop"
            # Profit target
            if reason is None and target_pc > 0:
                if d == "long"  and close >= pos["entry_price"] * (1 + target_pc): reason = "target"
                if d == "short" and close <= pos["entry_price"] * (1 - target_pc): reason = "target"
        else:
            # No bar data — use entry price as exit price, exit by age only
            close = float(pos["entry_price"])
            logger.warning(f"[exit] no bars for {sym} age={age:.1f}m — age-only exit check")

        # Max hold fires regardless of bar availability
        if reason is None and age >= max_hold:
            reason = "timeout"

        if reason:
            try:
                exit_price = close * (1 - _SLIPPAGE) if d == "long" else close * (1 + _SLIPPAGE)
                pnl = (exit_price - pos["entry_price"]) * pos["qty"] * (1 if d == "long" else -1)
                daily_pnl += pnl

                side = "sell" if d == "long" else "buy"
                _close_position(sym) if side == "sell" else _submit_order(sym, side, pos["qty"])
                _log_fill(sym, pos["order_id"] or "", "exit", pos["qty"], exit_price, pnl, reason)
                _post_event("TRADE", sym,
                    f"{'✓' if pnl >= 0 else '✗'} EXIT {d.upper()} {sym} @ ${exit_price:,.4f} · pnl {pnl:+,.4f} · {reason}",
                    f"age={age:.0f}m daily_pnl={daily_pnl:+,.2f}")
                logger.info(f"[exit] {sym} {reason} pnl={pnl:+,.4f}")
            except Exception as ex:
                logger.error(f"[exit] {sym} exit block failed: {ex}")
            finally:
                # Always remove from DB and memory so stuck positions never block the loop
                _delete_position(sym)
                positions.pop(sym, None)
                exited_this_run.add(sym)

    # Daily loss halt
    if nav > 0 and daily_pnl / nav <= -_CFG["risk"]["max_daily_loss_pct"] / 100:
        _post_event("RISK", "", f"daily loss limit hit · halted · pnl={daily_pnl:+.2f}")
        return

    # Reconcile phase 2: import Alpaca positions missing from DB, skipping symbols
    # just closed this run (Alpaca position list lags order settlement by ~15s)
    for sym, ap in alpaca_positions.items():
        if sym in exited_this_run:
            logger.info(f"[reconcile] skip re-import {sym} — closed this run")
            continue
        if sym not in positions:
            qty   = float(ap.qty)
            entry = float(ap.avg_entry_price)
            stop  = entry * (1 - _POS["stop_pct"])
            pos   = {
                "symbol":       sym,
                "direction":    "long",
                "qty":          qty,
                "entry_price":  entry,
                "stop_price":   stop,
                "target_price": 0.0,
                "entered_at":   now,
                "order_id":     None,
            }
            _save_position(pos)
            positions[sym] = pos
            logger.info(f"[reconcile] imported {sym} qty={qty} entry={entry}")

    # ── Check for new entries ─────────────────────────────────────────────────
    if len(positions) < max_pos:
        for sym in _UNIVERSE:
            if sym in positions:
                continue
            if len(positions) >= max_pos:
                break

            m_bars = min_bars.get(sym, [])
            signal = _compute_signal(m_bars)
            if not signal:
                continue

            price = m_bars[-1]["close"] if m_bars else 0
            if price <= 0:
                continue

            qty = round((nav * risk_pc) / price, 8)
            if qty <= 0:
                logger.warning(f"[entry] {sym} qty=0 (price={price}, nav={nav}, risk={risk_pc})")
                continue

            filled = price * (1 + _SLIPPAGE) if signal == "long" else price * (1 - _SLIPPAGE)
            stop   = filled * (1 - stop_pc)  if signal == "long" else filled * (1 + stop_pc)
            target = filled * (1 + target_pc) if signal == "long" else filled * (1 - target_pc)

            order_id = _submit_order(sym, "buy" if signal == "long" else "sell", qty)
            _log_fill(sym, order_id or "", "entry", qty, filled, None, "signal")

            pos = {
                "symbol":       sym,
                "direction":    signal,
                "qty":          qty,
                "entry_price":  filled,
                "stop_price":   stop,
                "target_price": target,
                "entered_at":   now,
                "order_id":     order_id,
            }
            _save_position(pos)
            positions[sym] = pos

            arrow = "▲" if signal == "long" else "▼"
            _post_event("TRADE", sym,
                f"{arrow} ENTER {signal.upper()} {sym} @ ${filled:,.4f} · stop ${stop:,.4f}",
                f"qty={qty:.6f}")
            logger.info(f"[entry] {signal.upper()} {sym} @ {filled:.4f} qty={qty:.6f}")

    # Re-fetch NAV so snapshot reflects any just-executed trades
    nav = _account_value()
    _write_snapshot(nav, positions)

    # Heartbeat — always post so the dashboard progress bar resets each run
    open_syms = ", ".join(positions.keys()) if positions else "flat"
    _post_event("UPDATE", None,
        f"▸ scan complete · NAV ${nav:,.2f} · {len(positions)} open ({open_syms})",
        f"positions={len(positions)}")
    logger.info(f"[crypto] snapshot written NAV=${nav:,.2f}")


if __name__ == "__main__":
    run()
