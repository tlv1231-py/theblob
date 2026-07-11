"""Shared market calendar utility. All trading-hours/holiday logic lives here."""
from datetime import date

import pandas as pd
import pandas_market_calendars as mcal
from loguru import logger


_NYSE = mcal.get_calendar("NYSE")


def is_trading_day(dt: date) -> bool:
    schedule = _NYSE.schedule(
        start_date=dt.strftime("%Y-%m-%d"),
        end_date=dt.strftime("%Y-%m-%d"),
    )
    return not schedule.empty


def get_trading_days(start: date, end: date) -> list[date]:
    schedule = _NYSE.schedule(
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
    )
    return [d.date() for d in schedule.index]


def previous_trading_day(dt: date) -> date:
    days = get_trading_days(
        date(dt.year - 1, dt.month, dt.day),  # look back up to a year
        dt,
    )
    # last entry <= dt
    past = [d for d in days if d < dt]
    if not past:
        raise ValueError(f"No prior trading day found before {dt}")
    return past[-1]


def next_trading_day(dt: date) -> date:
    days = get_trading_days(dt, date(dt.year + 1, dt.month, dt.day))
    future = [d for d in days if d > dt]
    if not future:
        raise ValueError(f"No next trading day found after {dt}")
    return future[0]


def market_open_close(dt: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    schedule = _NYSE.schedule(
        start_date=dt.strftime("%Y-%m-%d"),
        end_date=dt.strftime("%Y-%m-%d"),
    )
    if schedule.empty:
        raise ValueError(f"{dt} is not a trading day.")
    row = schedule.iloc[0]
    return row["market_open"], row["market_close"]
