from datetime import date

from ingestion.calendar import is_trading_day, get_trading_days, previous_trading_day


def test_known_trading_day():
    assert is_trading_day(date(2024, 1, 2)) is True


def test_known_holiday():
    # New Year's Day 2024
    assert is_trading_day(date(2024, 1, 1)) is False


def test_weekend():
    # Saturday
    assert is_trading_day(date(2024, 1, 6)) is False


def test_get_trading_days_range():
    days = get_trading_days(date(2024, 1, 2), date(2024, 1, 5))
    assert date(2024, 1, 2) in days
    assert date(2024, 1, 3) in days
    assert date(2024, 1, 4) in days
    assert date(2024, 1, 1) not in days  # holiday


def test_previous_trading_day():
    # Monday Jan 8 → prev is Friday Jan 5
    prev = previous_trading_day(date(2024, 1, 8))
    assert prev == date(2024, 1, 5)
