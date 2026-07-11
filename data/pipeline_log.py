"""Thin helper for writing structured pipeline events to the DB terminal feed."""
from datetime import date, datetime

from data.database import get_session
from data.models import PipelineEvent


def log_event(
    run_date: date,
    event_type: str,
    message: str,
    detail: str | None = None,
    symbol: str | None = None,
) -> None:
    with get_session() as s:
        s.add(PipelineEvent(
            run_date=run_date,
            event_type=event_type,
            symbol=symbol,
            message=message,
            detail=detail,
            recorded_at=datetime.utcnow(),
        ))
        s.commit()
