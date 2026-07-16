"""Create all DB tables. Run once to initialize schema."""
from loguru import logger

from data.database import Base, engine
from data.models import (  # noqa: F401 — imports needed to register models
    CapitalEvent,
    ChartAnnotation,
    ExperimentRecord,
    FillRecord,
    OrderRecord,
    PipelineEvent,
    PnLRecord,
    PortfolioSnapshot,
    PriceBar,
    SignalRecord,
    StreamEvent,
    StreamHealth,
)


def create_tables() -> None:
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully.")


if __name__ == "__main__":
    create_tables()
