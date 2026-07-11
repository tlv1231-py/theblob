from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml
from loguru import logger
from sqlalchemy import select

from data.database import get_session
from data.models import PriceBar
from data.schemas import Signal, SignalDirection
from features.momentum.price_momentum import compute_momentum_score, rank_cross_sectional
from signals.base_signal import BaseSignalGenerator

_PARAMS_PATH = Path(__file__).parent.parent / "config" / "strategy_params" / "momentum.yaml"


def _load_params() -> dict:
    with _PARAMS_PATH.open() as f:
        return yaml.safe_load(f)


class MomentumSignalGenerator(BaseSignalGenerator):
    strategy = "momentum"

    def __init__(
        self,
        lookback_days: int | None = None,
        skip_last_days: int | None = None,
        top_n: int | None = None,
        min_score_threshold: float | None = None,
    ) -> None:
        """Load params from momentum.yaml by default; kwargs override."""
        params = _load_params()
        self.lookback_days = lookback_days if lookback_days is not None else params.get("lookback_days", 252)
        self.skip_last_days = skip_last_days if skip_last_days is not None else params.get("short_lookback_days", 21)
        self.top_n = top_n if top_n is not None else params.get("top_n_stocks", 5)
        self.min_score_threshold = (
            min_score_threshold if min_score_threshold is not None
            else params.get("signal", {}).get("min_score_threshold", 0.05)
        )
        logger.debug(
            f"[momentum] Loaded params: lookback={self.lookback_days}, "
            f"skip={self.skip_last_days}, top_n={self.top_n}, "
            f"min_score={self.min_score_threshold}"
        )

    def generate(self, as_of_date: date) -> list[Signal]:
        """Generate momentum signals using only data available at as_of_date."""
        prices = self._load_prices(as_of_date)
        if prices.empty:
            logger.warning(f"[momentum] No price data available for {as_of_date}.")
            return []

        scores = prices.apply(
            lambda col: compute_momentum_score(
                col.dropna(), self.lookback_days, self.skip_last_days
            ).iloc[-1] if len(col.dropna()) > self.lookback_days + self.skip_last_days else None
        )
        scores = scores.dropna()

        if scores.empty:
            logger.warning(f"[momentum] No valid scores for {as_of_date}.")
            return []

        ranks = rank_cross_sectional(scores)
        qualified = scores[scores >= self.min_score_threshold]
        top = qualified.nlargest(self.top_n)

        signals: list[Signal] = []
        for symbol, raw_score in top.items():
            rank = float(ranks[symbol])
            signals.append(
                Signal(
                    strategy=self.strategy,
                    symbol=str(symbol),
                    direction=SignalDirection.LONG,
                    score=rank,
                    confidence=min(rank, 1.0),
                    expected_return=float(raw_score),
                    rationale=(
                        f"12-1 momentum score {raw_score:.1%}, "
                        f"cross-sectional rank {rank:.2f}"
                    ),
                    generated_at=datetime.utcnow(),
                    as_of_date=as_of_date.strftime("%Y-%m-%d"),
                )
            )

        logger.info(f"[momentum] Generated {len(signals)} signals for {as_of_date}.")
        return signals

    def _load_prices(self, as_of_date: date) -> pd.DataFrame:
        """Load adj_close prices up to (and including) as_of_date from DB.

        Limits rows to exactly what the score computation needs:
        lookback + skip + buffer trading days. This prevents fetching
        unbounded history as the dataset grows.
        """
        rows_needed = self.lookback_days + self.skip_last_days + 30
        with get_session() as session:
            # Subquery: get the last `rows_needed` distinct dates <= as_of_date
            from sqlalchemy import func
            date_subq = (
                select(PriceBar.date)
                .where(PriceBar.date <= as_of_date)
                .distinct()
                .order_by(PriceBar.date.desc())
                .limit(rows_needed)
                .subquery()
            )
            rows = session.execute(
                select(PriceBar.symbol, PriceBar.date, PriceBar.adj_close)
                .where(PriceBar.date.in_(select(date_subq.c.date)))
                .order_by(PriceBar.date)
            ).fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["symbol", "date", "adj_close"])
        df["date"] = pd.to_datetime(df["date"])
        pivot = df.pivot(index="date", columns="symbol", values="adj_close")
        return pivot
