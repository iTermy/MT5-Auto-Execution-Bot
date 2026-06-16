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


# ---------------------------------------------------------------------------
# Per-asset spread-hour cutoff: stocks cancel earlier (15:45) than the default (16:45)
# ---------------------------------------------------------------------------


def test_stock_spread_hour_starts_at_stock_cutoff() -> None:
    # Monday 15:45 EST — stocks are in their window; everything else isn't yet
    s = _scheduler()
    assert s.is_spread_hour(_est(2026, 3, 9, 15, 45), stock=True) is True
    assert s.is_spread_hour(_est(2026, 3, 9, 15, 45), stock=False) is False


def test_stock_spread_hour_before_cutoff() -> None:
    assert _scheduler().is_spread_hour(_est(2026, 3, 9, 15, 44), stock=True) is False


def test_default_spread_hour_at_default_cutoff() -> None:
    # 16:45 EST — default window opens; stocks have already been in theirs since 15:45
    s = _scheduler()
    assert s.is_spread_hour(_est(2026, 3, 9, 16, 45), stock=False) is True
    assert s.is_spread_hour(_est(2026, 3, 9, 16, 45), stock=True) is True


def test_stock_friday_weekend_starts_at_stock_cutoff() -> None:
    # Friday 15:45 EST — the stock weekend closure opens early; default waits for 16:45
    s = _scheduler()
    assert s.is_spread_hour(_est(2026, 3, 6, 15, 45), stock=True) is True
    assert s.is_spread_hour(_est(2026, 3, 6, 15, 45), stock=False) is False
