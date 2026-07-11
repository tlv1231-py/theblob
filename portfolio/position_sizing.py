"""Volatility-adjusted position sizing utilities."""
import numpy as np
import pandas as pd


def volatility_adjusted_size(
    portfolio_value: float,
    price: float,
    returns: pd.Series,
    target_vol: float = 0.01,
    lookback: int = 21,
) -> int:
    """Size position so that its contribution to portfolio vol equals target_vol.

    target_vol is daily portfolio vol target (e.g. 0.01 = 1% per day).
    """
    recent = returns.tail(lookback)
    asset_vol = float(recent.std())
    if asset_vol == 0:
        return 0
    dollar_alloc = (portfolio_value * target_vol) / asset_vol
    return max(int(dollar_alloc / price), 0)
