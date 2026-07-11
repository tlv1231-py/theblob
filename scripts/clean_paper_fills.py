"""scripts/clean_paper_fills.py

Reconstructs a clean paper trading fill history by:

  1. Deleting ALL existing fills and orders
  2. Re-inserting the correct set:

     2026-05-29  BUY  GOOGL 51 @ $390.3251   (Run 2 — correct top-5 sizing)
     2026-05-29  BUY  AVGO  46 @ $426.7933
     2026-05-29  BUY  NVDA  93 @ $214.3571
     2026-05-29  BUY  JNJ   86 @ $230.9154
     2026-05-29  BUY  XOM  136 @ $147.0335

     2026-06-02  SELL NVDA  93 @ $222.82     (exit — dropped out of top-5)
     2026-06-02  SELL JNJ   86 @ $222.89
     2026-06-02  SELL XOM  136 @ $149.56
     2026-06-02  BUY  INTC 165 @ $120.9504   (entry — new to top-5)
     2026-06-02  BUY  AMD   38 @ $518.3491
     2026-06-02  BUY  CAT   22 @ $888.1138

     2026-06-04  SELL AVGO  46 @ $479.23     (exit — dropped out of top-5)
     2026-06-04  BUY  VLO   81 @ $244.9724   (entry — new to top-5)

Usage:
    python scripts/clean_paper_fills.py            # dry run — preview only
    python scripts/clean_paper_fills.py --confirm  # apply changes
"""
import sys
import uuid
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data.database import get_session
from data.models import FillRecord, OrderRecord

SLIPPAGE_BPS = 5
STRATEGY = "momentum"

# ── Clean fill specification ──────────────────────────────────────────────────
# (date_str, side, symbol, qty, raw_price)
# raw_price = close price; slippage applied automatically
CLEAN_FILLS = [
    # 2026-05-29 — initial top-5 buys
    ("2026-05-29 15:07:56", "buy",  "GOOGL",  51, 390.3251),
    ("2026-05-29 15:07:56", "buy",  "AVGO",   46, 426.7933),
    ("2026-05-29 15:07:56", "buy",  "NVDA",   93, 214.3571),
    ("2026-05-29 15:07:56", "buy",  "JNJ",    86, 230.9154),
    ("2026-05-29 15:07:56", "buy",  "XOM",   136, 147.0335),

    # 2026-06-02 — rebalance: sell exits, buy new entries
    ("2026-06-02 14:25:00", "sell", "NVDA",   93, 222.8200),
    ("2026-06-02 14:25:00", "sell", "JNJ",    86, 222.8900),
    ("2026-06-02 14:25:00", "sell", "XOM",   136, 149.5600),
    ("2026-06-02 14:25:00", "buy",  "INTC",  165, 120.9504),
    ("2026-06-02 14:25:00", "buy",  "AMD",    38, 518.3491),
    ("2026-06-02 14:25:00", "buy",  "CAT",    22, 888.1138),

    # 2026-06-04 — rebalance: AVGO exits, VLO enters
    ("2026-06-04 19:23:44", "sell", "AVGO",   46, 479.2300),
    ("2026-06-04 19:23:44", "buy",  "VLO",    81, 244.9724),
]


def _apply_slippage(side: str, price: float) -> float:
    pct = SLIPPAGE_BPS / 10_000
    return round(price * (1 + pct) if side == "buy" else price * (1 - pct), 4)


def _preview() -> None:
    print("\n=== CLEAN FILL HISTORY (DRY RUN) ===\n")
    running_positions: dict[str, int] = {}
    for ts, side, symbol, qty, price in CLEAN_FILLS:
        fill_price = _apply_slippage(side, price)
        if side == "buy":
            running_positions[symbol] = running_positions.get(symbol, 0) + qty
        else:
            running_positions[symbol] = running_positions.get(symbol, 0) - qty
            if running_positions[symbol] == 0:
                del running_positions[symbol]
        print(f"  {ts}  {side.upper():4}  {symbol:5}  {qty:4} shares @ ${fill_price:.4f}")

    print(f"\n  Total fills: {len(CLEAN_FILLS)}")
    print(f"\n  Final portfolio positions:")
    for sym, qty in sorted(running_positions.items()):
        print(f"    {sym:5}  {qty} shares")

    print("\nRun with --confirm to apply.\n")


def _apply() -> None:
    print("\n=== APPLYING CLEAN FILL HISTORY ===\n")

    with get_session() as session:
        # Count what we're deleting
        fill_count = session.query(FillRecord).count()
        order_count = session.query(OrderRecord).count()
        print(f"  Deleting {fill_count} existing fills and {order_count} orders...")

        session.query(FillRecord).delete()
        session.query(OrderRecord).delete()
        session.commit()
        print("  Deleted.")

        # Insert clean records
        print(f"\n  Inserting {len(CLEAN_FILLS)} clean fills...\n")
        for ts, side, symbol, qty, price in CLEAN_FILLS:
            fill_price = _apply_slippage(side, price)
            slippage = round(abs(fill_price - price) * qty, 2)
            filled_at = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")

            order_id = str(uuid.uuid4())
            fill_id  = str(uuid.uuid4())

            order_rec = OrderRecord(
                order_id=order_id,
                strategy=STRATEGY,
                symbol=symbol,
                side=side,
                quantity=qty,
                limit_price=price,
                status="filled",
                signal_id=None,
                created_at=filled_at,
            )
            fill_rec = FillRecord(
                fill_id=fill_id,
                order_id=order_id,
                symbol=symbol,
                side=side,
                quantity=qty,
                fill_price=fill_price,
                commission=0.0,
                slippage=slippage,
                filled_at=filled_at,
            )
            session.add(order_rec)
            session.add(fill_rec)
            print(f"  {side.upper():4}  {symbol:5}  {qty:4} shares @ ${fill_price:.4f}"
                  f"  (slippage ${slippage:.2f})")

        session.commit()

    print("\n  Done. Run python run_pipeline.py to regenerate today's snapshot and PnL.\n")


if __name__ == "__main__":
    confirm = "--confirm" in sys.argv
    if confirm:
        _apply()
    else:
        _preview()
