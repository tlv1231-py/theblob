"""Pydantic schemas for sector-diversified portfolio construction."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# GICS sector names used in this project
GICSector = Literal[
    "Technology",
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Financials",
    "Health Care",
    "Industrials",
    "Energy",
    "Materials",
    "Real Estate",
    "Utilities",
]


class SectorAllocation(BaseModel):
    """One slot in a sector-capped portfolio."""

    symbol: str = Field(description="Ticker symbol selected for this slot")
    sector: GICSector = Field(description="GICS sector of this symbol")
    rank: int = Field(ge=1, description="Momentum rank before sector cap (1 = strongest)")
    score: float = Field(description="Raw momentum score")
    displaced: bool = Field(
        default=False,
        description="True if this symbol was promoted due to a higher-ranked same-sector stock",
    )


class SectorCapResult(BaseModel):
    """Output of the sector cap filter for one rebalance date."""

    selected: list[SectorAllocation] = Field(
        description="Final portfolio after 1-stock-per-sector enforcement"
    )
    dropped: list[SectorAllocation] = Field(
        default_factory=list,
        description="Stocks excluded due to sector collision",
    )
    cap_applied: bool = Field(
        description="True if any stock was replaced due to sector cap"
    )

    @model_validator(mode="after")
    def no_duplicate_sectors(self) -> "SectorCapResult":
        sectors_seen = [s.sector for s in self.selected]
        if len(sectors_seen) != len(set(sectors_seen)):
            dupes = [s for s in sectors_seen if sectors_seen.count(s) > 1]
            raise ValueError(f"Duplicate sectors in selected portfolio: {dupes}")
        return self
