from datetime import UTC, datetime, time

import pytz

from bot.config.settings import SpreadHourConfig

_DAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def to_est(dt: datetime) -> datetime:
    est = pytz.timezone("US/Eastern")
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(est)


def _parse_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


class MarketScheduler:
    def __init__(self, config: SpreadHourConfig) -> None:
        self._tz = pytz.timezone(config.timezone)
        self._start = _parse_time(config.daily_start)
        self._end = _parse_time(config.daily_end)
        self._weekend_start = _DAY_MAP[config.weekend_start_day.lower()]
        self._weekend_end = _DAY_MAP[config.weekend_end_day.lower()]

    def is_spread_hour(self, now: datetime | None = None) -> bool:
        now_local = (now or datetime.now(UTC)).astimezone(self._tz)
        t = now_local.time()
        day = now_local.weekday()  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun

        # Weekend closure: Fri 16:45 through Sun 18:00 (continuous)
        if day == self._weekend_start and t >= self._start:
            return True
        if self._weekend_start < day < self._weekend_end:  # all day Saturday
            return True
        if day == self._weekend_end and t < self._end:
            return True

        # Daily spread hour Mon–Thu
        if day < self._weekend_start and self._start <= t < self._end:
            return True

        return False

    def should_cancel_pending(self, now: datetime | None = None) -> bool:
        return self.is_spread_hour(now)

    def should_block_placement(self, now: datetime | None = None) -> bool:
        return self.is_spread_hour(now)

    def is_weekend_window(self, now: datetime | None = None) -> bool:
        """Forex weekend window: Friday >=16:45 EST through Sunday <18:00 EST.

        Independent of is_spread_hour because the spread-hour daily window
        (e.g. Mon-Thu 16:45-18:00) is not a 'weekend' for signal-expiry purposes.
        """
        now_local = (now or datetime.now(UTC)).astimezone(self._tz)
        t = now_local.time()
        day = now_local.weekday()
        fri_cutoff = time(16, 45)
        sun_open = time(18, 0)
        if day == 4 and t >= fri_cutoff:
            return True
        if day == 5:
            return True
        if day == 6 and t < sun_open:
            return True
        return False
