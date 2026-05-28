import logging
from datetime import datetime, timezone

import asyncpg

from bot.mt5.client import MT5Client

logger = logging.getLogger(__name__)


class OffsetCalculator:
    def get_offset(
        self,
        mt5_symbol: str,
        live_price_row: asyncpg.Record,
        mt5_client: MT5Client,
        max_staleness_seconds: int,
    ) -> float | None:
        # Freshness check — asyncpg returns tz-aware datetime
        updated_at: datetime = live_price_row["updated_at"]
        age = datetime.now(timezone.utc) - updated_at
        if age.total_seconds() > max_staleness_seconds:
            logger.warning(
                "Live price for %s is stale (%.0fs old), skipping offset",
                mt5_symbol, age.total_seconds(),
            )
            return None

        feed_mid = (float(live_price_row["bid"]) + float(live_price_row["ask"])) / 2

        tick = mt5_client.symbol_info_tick(mt5_symbol)
        if tick is None:
            logger.error("Cannot get MT5 tick for %s to compute offset", mt5_symbol)
            return None

        mt5_mid = (tick.bid + tick.ask) / 2
        return mt5_mid - feed_mid

    def apply_offset(self, db_price: float, offset: float) -> float:
        return db_price + offset

    def check_drift(
        self, current_offset: float, stored_offset: float, threshold: float
    ) -> bool:
        return abs(current_offset - stored_offset) > threshold
