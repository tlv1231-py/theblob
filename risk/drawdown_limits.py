"""Drawdown monitoring utilities."""
import pandas as pd


def compute_drawdown_series(equity_curve: pd.Series) -> pd.Series:
    """Return rolling drawdown from peak as a fraction (negative values)."""
    rolling_max = equity_curve.cummax()
    return (equity_curve - rolling_max) / rolling_max


def max_drawdown(equity_curve: pd.Series) -> float:
    return float(compute_drawdown_series(equity_curve).min())
