import logging
import time
from datetime import UTC, datetime, timedelta

import asyncpg
import MetaTrader5 as mt5

from bot.mt5.client import MT5Client
from bot.mt5.types import TickInfo

logger = logging.getLogger(__name__)

# Offset = broker_mid − feed_mid, both taken at the feed's exact updated_at. The
# broker price comes from tick history matched to that timestamp to the millisecond
# (time_msc), so the gap between the feed's updated_at and "now" never leaks into the
# offset. Recompute is throttled (offset is slow-moving) to spare MT5/DB calls.
_TICK_MATCH_HALFWIDTH = 5  # seconds — tick-history search window around updated_at
_M1_HALFWIDTH = 60  # seconds — M1-bar fallback search window


def _closest_tick_mid(ticks: list[TickInfo], target_msc: int) -> float | None:
    if not ticks:
        return None
    best = min(ticks, key=lambda t: abs(t.time_msc - target_msc))
    return (best.bid + best.ask) / 2


class OffsetCalculator:
    def __init__(self) -> None:
        # mt5_symbol -> (monotonic compute time, offset). Recompute is throttled to
        # the recompute interval; the cached value is served in between.
        self._cache: dict[str, tuple[float, float]] = {}
        self._no_history_logged: set[str] = set()

    def get_offset(
        self,
        mt5_symbol: str,
        live_price_row: asyncpg.Record,
        mt5_client: MT5Client,
        max_staleness_seconds: int,
        recompute_interval_seconds: int,
    ) -> float | None:
        # asyncpg returns tz-aware UTC. While a signal is active the feed refreshes
        # every ~5s; a stale updated_at means the feed updater stalled — skip then.
        updated_at: datetime = live_price_row["updated_at"]
        age = (datetime.now(UTC) - updated_at).total_seconds()
        if age > max_staleness_seconds:
            logger.warning(
                "Live price for %s is %.0fs old (> %ds bound), skipping offset",
                mt5_symbol,
                age,
                max_staleness_seconds,
            )
            return None

        cached = self._cache.get(mt5_symbol)
        now_mono = time.monotonic()
        if cached is not None and (now_mono - cached[0]) < recompute_interval_seconds:
            return cached[1]

        feed_mid = (float(live_price_row["bid"]) + float(live_price_row["ask"])) / 2
        broker_mid = self._broker_mid_at(mt5_symbol, updated_at, mt5_client)
        if broker_mid is None:
            # Transient history gap — keep serving the last good offset rather than
            # blocking placement; offset drifts slowly, so a recent value is safe.
            return cached[1] if cached is not None else None

        offset = broker_mid - feed_mid
        self._cache[mt5_symbol] = (now_mono, offset)
        self._no_history_logged.discard(mt5_symbol)
        return offset

    def _broker_mid_at(
        self, mt5_symbol: str, updated_at: datetime, mt5_client: MT5Client
    ) -> float | None:
        # MT5 history is keyed in the broker server frame; derive the whole-hour
        # server offset from a live tick's server epoch (no extra dedicated call).
        ref = mt5_client.symbol_info_tick(mt5_symbol)
        if ref is None:
            return None
        server_offset = round((ref.time - time.time()) / 3600.0) * 3600
        target_epoch = updated_at.timestamp() + server_offset
        server_dt = datetime.fromtimestamp(target_epoch, UTC)

        ticks = mt5_client.copy_ticks_range(
            mt5_symbol,
            server_dt - timedelta(seconds=_TICK_MATCH_HALFWIDTH),
            server_dt + timedelta(seconds=_TICK_MATCH_HALFWIDTH),
        )
        mid = _closest_tick_mid(ticks, int(target_epoch * 1000))
        if mid is not None:
            return mid

        rates = mt5_client.copy_rates_range(
            mt5_symbol,
            mt5.TIMEFRAME_M1,
            server_dt - timedelta(seconds=_M1_HALFWIDTH),
            server_dt + timedelta(seconds=_M1_HALFWIDTH),
        )
        if rates:
            bar = min(rates, key=lambda r: abs(r.time - target_epoch))
            return (bar.open + bar.close) / 2

        if mt5_symbol not in self._no_history_logged:
            logger.warning(
                "No broker history for %s at %s — skipping offset",
                mt5_symbol,
                updated_at.isoformat(),
            )
            self._no_history_logged.add(mt5_symbol)
        return None

    def check_drift(self, current_offset: float, stored_offset: float, threshold: float) -> bool:
        return abs(current_offset - stored_offset) > threshold
