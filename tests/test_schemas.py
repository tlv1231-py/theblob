from datetime import date, datetime

import pytest
from pydantic import ValidationError

from data.schemas import OHLCV, Signal, SignalDirection, Order, OrderSide


def test_ohlcv_valid():
    bar = OHLCV(
        symbol="SPY",
        date=date(2024, 1, 2),
        open=476.0, high=477.5, low=474.0, close=476.8, adj_close=476.8,
        volume=50_000_000,
    )
    assert bar.symbol == "SPY"


def test_ohlcv_high_lt_low_raises():
    with pytest.raises(ValidationError):
        OHLCV(
            symbol="SPY",
            date=date(2024, 1, 2),
            open=476.0, high=470.0, low=474.0, close=476.8, adj_close=476.8,
            volume=50_000_000,
        )


def test_signal_valid():
    sig = Signal(
        strategy="momentum",
        symbol="AAPL",
        direction=SignalDirection.LONG,
        score=0.85,
        confidence=0.9,
        generated_at=datetime.utcnow(),
        as_of_date="2024-01-02",
    )
    assert sig.direction == SignalDirection.LONG


def test_signal_confidence_out_of_range():
    with pytest.raises(ValidationError):
        Signal(
            strategy="momentum",
            symbol="AAPL",
            direction=SignalDirection.LONG,
            score=0.85,
            confidence=1.5,  # > 1.0
            generated_at=datetime.utcnow(),
            as_of_date="2024-01-02",
        )
