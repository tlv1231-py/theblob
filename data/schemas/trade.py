from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order(BaseModel):
    order_id: str
    strategy: str
    symbol: str
    side: OrderSide
    quantity: int = Field(gt=0)
    limit_price: float | None = None
    created_at: datetime
    status: OrderStatus = OrderStatus.PENDING
    signal_id: str | None = None


class Fill(BaseModel):
    fill_id: str
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int = Field(gt=0)
    fill_price: float = Field(gt=0)
    commission: float = Field(ge=0, default=0.0)
    slippage: float = Field(default=0.0)
    filled_at: datetime

    @property
    def gross_value(self) -> float:
        return self.fill_price * self.quantity

    @property
    def net_cost(self) -> float:
        return self.gross_value + self.commission
