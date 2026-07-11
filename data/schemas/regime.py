"""Pydantic schemas for market regime signals."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# String alias kept for import compatibility
RegimeState = Literal["bull", "bear"]


class RegimeSignal(BaseModel):
    """A single daily regime observation for one benchmark symbol."""

    symbol: str = Field(description="Benchmark symbol used (e.g. 'SPY')")
    as_of_date: date = Field(description="Trading date this regime applies to")
    regime: Literal["bull", "bear"] = Field(
        description="'bull' when price > MA, 'bear' when price < MA"
    )
    price: float = Field(gt=0, description="Closing price on this date")
    ma_value: float = Field(gt=0, description="Moving-average value on this date")
    ma_window: int = Field(gt=0, description="Moving-average lookback in days")
    distance_pct: float = Field(
        description="(price - ma) / ma — positive in bull, negative in bear"
    )

    @model_validator(mode="after")
    def regime_consistent_with_price(self) -> "RegimeSignal":
        if self.regime == "bull" and self.price <= self.ma_value:
            raise ValueError(
                f"regime='bull' but price ({self.price:.2f}) <= MA ({self.ma_value:.2f})"
            )
        if self.regime == "bear" and self.price >= self.ma_value:
            raise ValueError(
                f"regime='bear' but price ({self.price:.2f}) >= MA ({self.ma_value:.2f})"
            )
        return self
