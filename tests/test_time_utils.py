from datetime import datetime

import pytz

from bot.config.settings import SpreadHourConfig
from bot.utils.time_utils import MarketScheduler


def _est(year, month, day, hour, minute) -> datetime:
    tz = pytz.timezone("US/Eastern")
    return tz.localize(datetime(year, month, day, hour, minute))


def _scheduler() -> MarketScheduler:
    return MarketScheduler(SpreadHourConfig())


def test_is_weekend_window_friday_before_cutoff() -> None:
    # Friday Mar 6, 2026 at 16:44 EST — just before the cutoff
    assert _scheduler().is_weekend_window(_est(2026, 3, 6, 16, 44)) is False


def test_is_weekend_window_friday_at_cutoff() -> None:
    assert _scheduler().is_weekend_window(_est(2026, 3, 6, 16, 45)) is True


def test_is_weekend_window_friday_evening() -> None:
    assert _scheduler().is_weekend_window(_est(2026, 3, 6, 22, 0)) is True


def test_is_weekend_window_saturday_noon() -> None:
    assert _scheduler().is_weekend_window(_est(2026, 3, 7, 12, 0)) is True


def test_is_weekend_window_sunday_before_open() -> None:
    assert _scheduler().is_weekend_window(_est(2026, 3, 8, 17, 59)) is True


def test_is_weekend_window_sunday_at_open() -> None:
    assert _scheduler().is_weekend_window(_est(2026, 3, 8, 18, 0)) is False


def test_is_weekend_window_monday_morning() -> None:
    assert _scheduler().is_weekend_window(_est(2026, 3, 9, 9, 0)) is False


def test_is_weekend_window_thursday() -> None:
    # Thursday is never a weekend window even at 17:00 (which IS spread-hour)
    assert _scheduler().is_weekend_window(_est(2026, 3, 5, 17, 0)) is False
