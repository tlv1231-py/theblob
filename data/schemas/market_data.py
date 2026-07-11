from datetime import date, datetime
from pydantic import BaseModel, Field, model_validator


class OHLCV(BaseModel):
    symbol: str
    date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)
    adj_close: float = Field(gt=0)
    ingested_at: datetime | None = None

    @model_validator(mode="after")
    def high_gte_low(self) -> "OHLCV":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) must be >= low ({self.low})")
        return self


class Quote(BaseModel):
    symbol: str
    timestamp: datetime
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    last: float = Field(gt=0)
    volume: int = Field(ge=0)

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2
