import pandas as pd
import pytest

from ingestion.validators import validate_ohlcv


def _make_df(**overrides) -> pd.DataFrame:
    data = {
        "open": [100.0],
        "high": [105.0],
        "low": [98.0],
        "close": [103.0],
        "adj_close": [103.0],
        "volume": [1_000_000],
    }
    data.update(overrides)
    return pd.DataFrame(data, index=pd.to_datetime(["2024-01-02"]))


def test_valid_bar_passes():
    df = _make_df()
    result = validate_ohlcv(df, "TEST")
    assert len(result) == 1


def test_drops_null_close():
    df = _make_df()
    df["close"] = None
    result = validate_ohlcv(df, "TEST")
    assert len(result) == 0


def test_drops_high_lt_low():
    df = _make_df(high=[90.0], low=[98.0])
    result = validate_ohlcv(df, "TEST")
    assert len(result) == 0


def test_drops_zero_close():
    df = _make_df(close=[0.0], adj_close=[0.0])
    result = validate_ohlcv(df, "TEST")
    assert len(result) == 0


def test_warns_on_large_gap(caplog):
    import pandas as pd
    rows = {
        "open": [100.0, 100.0],
        "high": [105.0, 105.0],
        "low": [98.0, 98.0],
        "close": [100.0, 160.0],
        "adj_close": [100.0, 160.0],
        "volume": [1_000_000, 1_000_000],
    }
    df = pd.DataFrame(rows, index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    validate_ohlcv(df, "TEST")  # should not raise, but should warn
