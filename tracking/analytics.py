"""Performance analytics: Sharpe, Sortino, CAGR, drawdown."""
import numpy as np
import pandas as pd


TRADING_DAYS = 252


def cagr(equity_curve: pd.Series) -> float:
    if len(equity_curve) < 2:
        return 0.0
    years = len(equity_curve) / TRADING_DAYS
    return float((equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / years) - 1)


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.05) -> float:
    daily_rf = risk_free_rate / TRADING_DAYS
    excess = returns - daily_rf
    if excess.std() == 0:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(TRADING_DAYS))


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.05) -> float:
    daily_rf = risk_free_rate / TRADING_DAYS
    excess = returns - daily_rf
    downside = excess[excess < 0].std()
    if downside == 0:
        return 0.0
    return float(excess.mean() / downside * np.sqrt(TRADING_DAYS))


def max_drawdown(equity_curve: pd.Series) -> float:
    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    return float(drawdown.min())


def summary(equity_curve: pd.Series) -> dict:
    returns = equity_curve.pct_change().dropna()
    return {
        "cagr": cagr(equity_curve),
        "sharpe": sharpe_ratio(returns),
        "sortino": sortino_ratio(returns),
        "max_drawdown": max_drawdown(equity_curve),
        "volatility_annualized": float(returns.std() * np.sqrt(TRADING_DAYS)),
        "total_return": float(
            (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1
        ) if len(equity_curve) > 1 else 0.0,
    }
