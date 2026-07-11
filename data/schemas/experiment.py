from datetime import date, datetime
from pydantic import BaseModel, Field


class ExperimentLog(BaseModel):
    experiment_id: str
    strategy: str
    hypothesis: str = Field(description="What you were testing and why")
    params: dict = Field(description="Key parameters used in this run")
    result_summary: str = Field(description="What happened — quantitative and qualitative")
    start_date: date
    end_date: date
    sharpe: float | None = None
    cagr: float | None = None
    max_drawdown: float | None = None
    notes: str = ""
    logged_at: datetime
