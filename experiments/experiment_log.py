"""Log experiments to DB. All backtests must be logged before results are considered valid."""
import uuid
from datetime import date, datetime

from loguru import logger

from data.database import get_session
from data.models import ExperimentRecord
from data.schemas import ExperimentLog


def log_experiment(
    strategy: str,
    hypothesis: str,
    params: dict,
    result_summary: str,
    start_date: date,
    end_date: date,
    sharpe: float | None = None,
    cagr: float | None = None,
    max_drawdown: float | None = None,
    notes: str = "",
) -> str:
    """Log an experiment and return its experiment_id."""
    experiment_id = str(uuid.uuid4())[:8]
    exp = ExperimentLog(
        experiment_id=experiment_id,
        strategy=strategy,
        hypothesis=hypothesis,
        params=params,
        result_summary=result_summary,
        start_date=start_date,
        end_date=end_date,
        sharpe=sharpe,
        cagr=cagr,
        max_drawdown=max_drawdown,
        notes=notes,
        logged_at=datetime.utcnow(),
    )

    with get_session() as session:
        rec = ExperimentRecord(**exp.model_dump())
        session.add(rec)
        session.commit()

    logger.info(f"[experiment] Logged '{experiment_id}': {strategy} | {hypothesis[:60]}")
    return experiment_id
