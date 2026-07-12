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

def _fetch_bars(timeframe: str, limit: int) -> dict[str, list]:
    """Fetch latest bars for all universe symbols in one request."""
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    tf = TimeFrame.Minute if timeframe == "1Min" else TimeFrame.Hour
    client = _data_client()
    req = CryptoBarsRequest(
        symbol_or_symbols = _UNIVERSE,
        timeframe         = tf,
        limit             = limit,
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
            s.add(FillRecord(
                id        = str(uuid.uuid4()),
                order_id  = order_id,
                strategy  = "crypto_momentum",
                symbol    = symbol,
                side      = side,
                qty       = qty,
                price     = price,
                pnl       = pnl or 0.0,
                filled_at = datetime.now(timezone.utc),
                note      = reason,
            ))
            s.commit()
    except Exception as e:
        logger.warning(f"Fill log failed: {e}")


# ── Order execution ───────────────────────────────────────────────────────────

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

def _compute_signal(min_bars: list[dict], hour_bars: list[dict]) -> str | None:
    """Returns 'long', 'short', or None."""
    if len(min_bars) < _SIG["breakout_bars"] + 21:
        return None

    closes  = [b["close"]  for b in min_bars]
    volumes = [b["volume"] for b in min_bars]
    highs   = [b["high"]   for b in min_bars]
    lows    = [b["low"]    for b in min_bars]

    close   = closes[-1]
    vol     = volumes[-1]
    avg_vol = sum(volumes[-21:-1]) / 20
    rvol    = (vol / avg_vol) if avg_vol > 0 else 0.0
    if rvol < _SIG["rvol_min"]:
        return None

    # VWAP from hourly bars (24h window)
    if hour_bars:
        tp_vol  = sum(((b["high"]+b["low"]+b["close"])/3) * b["volume"] for b in hour_bars)
        tot_vol = sum(b["volume"] for b in hour_bars)
        vwap    = tp_vol / tot_vol if tot_vol > 0 else close
    else:
        vwap = close

    n = _SIG["breakout_bars"]
    prior_highs = highs[-(n+1):-1]
    prior_lows  = lows[ -(n+1):-1]

    if close > max(prior_highs) and close > vwap:
        return "long"
    if close < min(prior_lows) and close < vwap:
        return "short"
    return None


# ── Main run ──────────────────────────────────────────────────────────────────

def run() -> None:
    now     = datetime.now(timezone.utc)
    nav     = _account_value()
    risk_pc = _POS["risk_pct"] / 100.0
    stop_pc = _POS["stop_pct"]
    tgt_pc  = _POS["target_pct"]
    max_pos = _POS["max_positions"]
    max_hold= _POS["max_hold_minutes"]

    logger.info(f"[crypto] run @ {now.isoformat()} | NAV=${nav:,.2f}")

    # Fetch bars (2 API calls, all symbols batched)
    try:
        min_bars  = _fetch_bars("1Min", 32)
        hour_bars = _fetch_bars("1Hour", 24)
    except Exception as e:
        logger.error(f"[crypto] Bar fetch failed: {e}")
        return

    logger.info(f"[crypto] bars received: {len(min_bars)} syms (1min) · {len(hour_bars)} syms (1hr)")
    for sym in list(min_bars.keys())[:3]:
        logger.info(f"  {sym}: {len(min_bars[sym])} 1min bars · {len(hour_bars.get(sym,[]))} 1hr bars")

    positions = _load_positions()
    daily_pnl = 0.0

    # ── Manage open positions ─────────────────────────────────────────────────
    for sym, pos in list(positions.items()):
        bars = min_bars.get(sym, [])
        if not bars:
            continue
        close = bars[-1]["close"]
        age   = (now - pos["entered_at"].replace(tzinfo=timezone.utc)).total_seconds() / 60
        d     = pos["direction"]
        reason= None

        if d == "long":
            if close <= pos["stop_price"]:    reason = "stop"
            elif close >= pos["target_price"]: reason = "target"
        else:
            if close >= pos["stop_price"]:    reason = "stop"
            elif close <= pos["target_price"]: reason = "target"

        if reason is None and age >= max_hold:
            reason = "max_hold"

        if reason:
            exit_price = close * (1 - _SLIPPAGE) if d == "long" else close * (1 + _SLIPPAGE)
            pnl = (exit_price - pos["entry_price"]) * pos["qty"] * (1 if d == "long" else -1)
            daily_pnl += pnl

            side = "sell" if d == "long" else "buy"
            _submit_order(sym, side, pos["qty"])
            _log_fill(sym, pos["order_id"] or "", "exit", pos["qty"], exit_price, pnl, reason)
            _delete_position(sym)

            emoji = "✓" if pnl >= 0 else "✗"
            _post_event("TRADE", sym,
                f"{emoji} EXIT {d.upper()} {sym} @ ${exit_price:,.4f} · pnl {pnl:+,.4f} · {reason}",
                f"age={age:.0f}m daily_pnl={daily_pnl:+,.2f}")
            logger.info(f"[exit] {sym} {reason} pnl={pnl:+,.4f}")

    # ── Check for new entries ─────────────────────────────────────────────────
    if len(positions) < max_pos:
        for sym in _UNIVERSE:
            if sym in positions:
                continue
            if len(positions) >= max_pos:
                break

            m_bars = min_bars.get(sym, [])
            h_bars = hour_bars.get(sym, [])
            signal = _compute_signal(m_bars, h_bars)
            if not signal:
                continue

            price  = m_bars[-1]["close"] if m_bars else 0
            if price <= 0:
                continue

            qty    = round((nav * risk_pc) / price, 8)
            filled = price * (1 + _SLIPPAGE) if signal == "long" else price * (1 - _SLIPPAGE)
            stop   = filled * (1 - stop_pc)  if signal == "long" else filled * (1 + stop_pc)
            target = filled * (1 + tgt_pc)   if signal == "long" else filled * (1 - tgt_pc)

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
                f"qty={qty:.6f} target=${target:,.4f}")
            logger.info(f"[entry] {signal.upper()} {sym} @ {filled:.4f} qty={qty:.6f}")


if __name__ == "__main__":
    run()
