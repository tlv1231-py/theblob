"""Paper trading executor. Simulates fills and logs everything to DB."""
import uuid
from datetime import datetime

from loguru import logger

from data.database import get_session
from data.models import FillRecord, OrderRecord, SignalRecord
from data.schemas import Fill, Order, OrderSide, OrderStatus, Signal, SignalDirection
from execution.broker_adapter import BrokerAdapter

# Simulated slippage: 5bps per side
SLIPPAGE_BPS = 5


class PaperBrokerAdapter(BrokerAdapter):
    """Simulates market fills with slippage. All state stored in DB."""

    def submit_order(self, order: Order) -> Fill:
        price = order.limit_price
        if price is None:
            raise ValueError("PaperBrokerAdapter requires a limit_price (last close).")

        slippage_pct = SLIPPAGE_BPS / 10_000
        if order.side == OrderSide.BUY:
            fill_price = price * (1 + slippage_pct)
        else:
            fill_price = price * (1 - slippage_pct)

        fill = Fill(
            fill_id=str(uuid.uuid4()),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=round(fill_price, 4),
            commission=0.0,
            slippage=round(abs(fill_price - price) * order.quantity, 2),
            filled_at=datetime.utcnow(),
        )
        self._persist_fill(fill, order)
        logger.info(
            f"[paper] FILL {order.side.value.upper()} {order.quantity} {order.symbol} "
            f"@ ${fill_price:.4f} (slippage ${fill.slippage:.2f})"
        )
        return fill

    def cancel_order(self, order_id: str) -> bool:
        with get_session() as session:
            rec = session.query(OrderRecord).filter_by(order_id=order_id).first()
            if rec:
                rec.status = OrderStatus.CANCELLED.value
                session.commit()
                return True
        return False

    def get_position(self, symbol: str) -> int:
        with get_session() as session:
            fills = session.query(FillRecord).filter_by(symbol=symbol).all()
        net = 0
        for f in fills:
            net += f.quantity if f.side == "buy" else -f.quantity
        return net

    def get_all_positions(self) -> dict[str, int]:
        """Return net long share count for every symbol currently held (qty > 0)."""
        with get_session() as session:
            fills = session.query(FillRecord).all()
        positions: dict[str, int] = {}
        for f in fills:
            delta = f.quantity if f.side == "buy" else -f.quantity
            positions[f.symbol] = positions.get(f.symbol, 0) + delta
        return {sym: qty for sym, qty in positions.items() if qty > 0}

    def _persist_fill(self, fill: Fill, order: Order) -> None:
        with get_session() as session:
            order_rec = OrderRecord(
                order_id=order.order_id,
                strategy=order.strategy,
                symbol=order.symbol,
                side=order.side.value,
                quantity=order.quantity,
                limit_price=order.limit_price,
                status=OrderStatus.FILLED.value,
                signal_id=order.signal_id,
                created_at=order.created_at,
            )
            fill_rec = FillRecord(
                fill_id=fill.fill_id,
                order_id=fill.order_id,
                symbol=fill.symbol,
                side=fill.side.value,
                quantity=fill.quantity,
                fill_price=fill.fill_price,
                commission=fill.commission,
                slippage=fill.slippage,
                filled_at=fill.filled_at,
            )
            session.add(order_rec)
            session.add(fill_rec)
            session.commit()


class PaperExecutor:
    """Converts signals → orders → fills via PaperBrokerAdapter."""

    def __init__(self, portfolio_value: float) -> None:
        self.broker = PaperBrokerAdapter()
        self.portfolio_value = portfolio_value

    def execute_sell(self, symbol: str, qty: int, price: float, strategy: str) -> Fill | None:
        """Exit a full position — sell all held shares of symbol."""
        if qty <= 0:
            logger.warning(f"[paper] Skipping sell {symbol} — qty={qty}")
            return None
        order = Order(
            order_id=str(uuid.uuid4()),
            strategy=strategy,
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=qty,
            limit_price=price,
            created_at=datetime.utcnow(),
            signal_id=None,
        )
        fill = self.broker.submit_order(order)
        logger.info(f"[paper] EXIT {symbol} — sold {qty} shares @ ${price:.4f}")
        return fill

    def execute_signal(self, signal: Signal, price: float, quantity: int) -> Fill | None:
        if quantity <= 0:
            logger.warning(f"[paper] Skipping {signal.symbol} — quantity={quantity}")
            return None

        # Skip if a long position is already held — prevents re-buying unchanged
        # positions on every pipeline run. The strategy only enters; exits are
        # handled when a symbol drops out of the top-N (not yet implemented).
        if signal.direction == SignalDirection.LONG:
            current_qty = self.broker.get_position(signal.symbol)
            if current_qty > 0:
                logger.info(
                    f"[paper] Skipping {signal.symbol} — already holding {current_qty} shares"
                )
                return None

        signal_id = self._persist_signal(signal)

        order = Order(
            order_id=str(uuid.uuid4()),
            strategy=signal.strategy,
            symbol=signal.symbol,
            side=OrderSide.BUY if signal.direction == SignalDirection.LONG else OrderSide.SELL,
            quantity=quantity,
            limit_price=price,
            created_at=datetime.utcnow(),
            signal_id=signal_id,
        )
        return self.broker.submit_order(order)

    def _persist_signal(self, signal: Signal) -> str:
        with get_session() as session:
            rec = SignalRecord(
                strategy=signal.strategy,
                symbol=signal.symbol,
                direction=signal.direction.value,
                score=signal.score,
                confidence=signal.confidence,
                expected_return=signal.expected_return,
                rationale=signal.rationale,
                as_of_date=signal.as_of_date,
                generated_at=signal.generated_at,
                params_version=signal.params_version,
            )
            session.add(rec)
            session.commit()
            session.refresh(rec)
            return str(rec.id)
