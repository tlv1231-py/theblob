"""Central risk gate. All signals pass through here before reaching the executor."""
from loguru import logger

from config.risk_limits import (
    MAX_DAILY_DRAWDOWN,
    MAX_GROSS_EXPOSURE,
    MAX_NET_EXPOSURE,
    MAX_POSITION_SIZE,
    MAX_RISK_PER_TRADE,
    MAX_SECTOR_EXPOSURE,
    MAX_TOTAL_DRAWDOWN,
)
from data.schemas import Signal


class RiskVeto(Exception):
    pass


class RiskEngine:
    def __init__(
        self,
        portfolio_value: float,
        current_drawdown: float = 0.0,
        daily_drawdown: float = 0.0,
        gross_exposure: float = 0.0,
        net_exposure: float = 0.0,
    ) -> None:
        self.portfolio_value = portfolio_value
        self.current_drawdown = current_drawdown
        self.daily_drawdown = daily_drawdown
        self.gross_exposure = gross_exposure
        self.net_exposure = net_exposure

    def check_portfolio_limits(self) -> None:
        if self.current_drawdown >= MAX_TOTAL_DRAWDOWN:
            raise RiskVeto(
                f"Total drawdown {self.current_drawdown:.1%} exceeds limit "
                f"{MAX_TOTAL_DRAWDOWN:.1%}. System halted."
            )
        if self.daily_drawdown >= MAX_DAILY_DRAWDOWN:
            raise RiskVeto(
                f"Daily drawdown {self.daily_drawdown:.1%} exceeds limit "
                f"{MAX_DAILY_DRAWDOWN:.1%}. Pausing trading."
            )

    def size_position(self, signal: Signal, price: float) -> int:
        """Return share quantity for a signal, respecting all risk limits.

        Uses fixed fractional sizing: risk 1% of portfolio per trade,
        with a 5% stop loss → position = (portfolio * 0.01) / (price * 0.05).
        """
        stop_loss_pct = 0.05
        dollar_risk = self.portfolio_value * MAX_RISK_PER_TRADE
        position_dollars = dollar_risk / stop_loss_pct

        # Cap at max position size
        max_dollars = self.portfolio_value * MAX_POSITION_SIZE
        position_dollars = min(position_dollars, max_dollars)

        shares = int(position_dollars / price)
        logger.debug(
            f"[risk] {signal.symbol}: ${position_dollars:,.0f} → {shares} shares @ ${price:.2f}"
        )
        return max(shares, 0)

    def approve_signal(self, signal: Signal, price: float) -> int:
        """Full risk gate. Returns approved share qty or raises RiskVeto."""
        self.check_portfolio_limits()

        if self.gross_exposure >= MAX_GROSS_EXPOSURE:
            raise RiskVeto(
                f"Gross exposure {self.gross_exposure:.1%} at limit. Cannot add {signal.symbol}."
            )

        qty = self.size_position(signal, price)
        if qty == 0:
            raise RiskVeto(f"Sized position in {signal.symbol} to 0 shares — skipping.")

        return qty
