import numpy as np
import pandas as pd
import pytest

from tracking.analytics import cagr, sharpe_ratio, sortino_ratio, max_drawdown, summary


def _flat_equity(start: float = 100_000, n: int = 252) -> pd.Series:
    return pd.Series([start] * n)


def _growing_equity(start: float = 100_000, annual_return: float = 0.10, n: int = 252) -> pd.Series:
    daily = (1 + annual_return) ** (1 / 252)
    return pd.Series([start * daily**i for i in range(n)])


def test_cagr_roughly_correct():
    eq = _growing_equity(annual_return=0.10)
    assert abs(cagr(eq) - 0.10) < 0.01


def test_sharpe_positive_for_growing():
    eq = _growing_equity(annual_return=0.20)
    returns = eq.pct_change().dropna()
    assert sharpe_ratio(returns) > 0


def test_max_drawdown_flat_is_zero():
    eq = _flat_equity()
    assert max_drawdown(eq) == 0.0


def test_max_drawdown_negative():
    eq = pd.Series([100, 110, 90, 95, 100])
    dd = max_drawdown(eq)
    assert dd < 0


def test_summary_keys():
    eq = _growing_equity()
    result = summary(eq)
    expected_keys = {"cagr", "sharpe", "sortino", "max_drawdown", "volatility_annualized", "total_return"}
    assert expected_keys == set(result.keys())
