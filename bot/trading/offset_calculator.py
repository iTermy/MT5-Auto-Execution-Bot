import logging
import time
from datetime import UTC, datetime, timedelta

import asyncpg
import MetaTrader5 as mt5

from bot.mt5.client import MT5Client
from bot.mt5.types import TickInfo

logger = logging.getLogger(__name__)

# Feed prices are written infrequently (every ~15 min, and only when a signal on
# that feed is close), so `updated_at` is the anchor — we compare the feed mid to
# the broker's price AT THAT instant, not "now". When the feed was written within
# this window the current tick is still time-aligned, so we skip the history call.
_FRESH_TICK_WINDOW = 15.0  # seconds
_TICK_MATCH_HALFWIDTH = 5  # seconds — search window around the feed timestamp
_M1_HALFWIDTH = 60  # seconds — M1-bar fallback search window


def _closest_tick_mid(ticks: list[TickInfo], target_epoch: float) -> float | None:
    if not ticks:
        return None
    best = min(ticks, key=lambda t: abs(t.time - target_epoch))
    return (best.bid + best.ask) / 2


class OffsetCalculator:
    def __init__(self) -> None:
        # mt5_symbol -> (feed updated_at, offset). One history lookup per feed row;
        # an idle feed (frozen updated_at) is served from here with no MT5 call.
        self._cache: dict[str, tuple[datetime, float]] = {}
        self._no_history_logged: set[str] = set()

    def get_offset(
        self,
        mt5_symbol: str,
        live_price_row: asyncpg.Record,
        mt5_client: MT5Client,
        max_staleness_seconds: int,
    ) -> float | None:
        # asyncpg returns tz-aware UTC. An old updated_at is expected (idle feed);
        # only reject a feed that has gone fully dark (dead-feed bound).
        updated_at: datetime = live_price_row["updated_at"]
        age = (datetime.now(UTC) - updated_at).total_seconds()
        if age > max_staleness_seconds:
            logger.warning(
                "Live price for %s is %.0fs old (> %ds dead-feed bound), skipping offset",
                mt5_symbol,
                age,
                max_staleness_seconds,
            )
            return None

        cached = self._cache.get(mt5_symbol)
        if cached is not None and cached[0] == updated_at:
            return cached[1]

        feed_mid = (float(live_price_row["bid"]) + float(live_price_row["ask"])) / 2
        broker_mid = self._broker_mid_at(mt5_symbol, updated_at, age, mt5_client)
        if broker_mid is None:
            return None

        offset = broker_mid - feed_mid
        self._cache[mt5_symbol] = (updated_at, offset)
        self._no_history_logged.discard(mt5_symbol)
        return offset

    def _broker_mid_at(
        self, mt5_symbol: str, updated_at: datetime, age: float, mt5_client: MT5Client
    ) -> float | None:
        # Fast path: feed just written → the current tick is time-aligned, no history.
        if age <= _FRESH_TICK_WINDOW:
            tick = mt5_client.symbol_info_tick(mt5_symbol)
            if tick is not None:
                return (tick.bid + tick.ask) / 2

        # History path: the broker's price at the feed's timestamp. MT5 history APIs
        # work in the broker server frame, so shift the UTC timestamp by the server
        # offset (derived from a live tick's server epoch — no extra dedicated call).
        ref = mt5_client.symbol_info_tick(mt5_symbol)
        if ref is None:
            return None
        server_offset = round((ref.time - time.time()) / 3600.0) * 3600
        target_epoch = updated_at.timestamp() + server_offset
        # MT5 history is keyed in the broker server frame; build a datetime whose
        # epoch is the server-time instant so the query window lines up with it.
        server_dt = datetime.fromtimestamp(target_epoch, UTC)

        ticks = mt5_client.copy_ticks_range(
            mt5_symbol,
            server_dt - timedelta(seconds=_TICK_MATCH_HALFWIDTH),
            server_dt + timedelta(seconds=_TICK_MATCH_HALFWIDTH),
        )
        mid = _closest_tick_mid(ticks, target_epoch)
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
