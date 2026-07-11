from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class Signal(BaseModel):
    strategy: str
    symbol: str
    direction: SignalDirection
    score: float = Field(description="Normalized signal strength, e.g. momentum percentile rank")
    confidence: float = Field(ge=0.0, le=1.0)
    expected_return: float | None = None
    rationale: str = ""
    generated_at: datetime
    as_of_date: str = Field(description="Market date this signal is valid for (YYYY-MM-DD)")
    params_version: str = ""
