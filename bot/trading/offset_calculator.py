import logging
from datetime import UTC, datetime

import asyncpg

from bot.mt5.client import MT5Client

logger = logging.getLogger(__name__)


class OffsetCalculator:
    def __init__(self) -> None:
        # Track symbols for which we have already logged the ic fallback warning,
        # so we log at most once per symbol over the bot's lifetime.
        self._ic_fallback_logged: set[str] = set()

    def get_offset(
        self,
        mt5_symbol: str,
        live_price_row: asyncpg.Record,
        mt5_client: MT5Client,
        max_staleness_seconds: int,
    ) -> float | None:
        # Freshness check — asyncpg returns tz-aware datetime
        updated_at: datetime = live_price_row["updated_at"]
        age = datetime.now(UTC) - updated_at
        if age.total_seconds() > max_staleness_seconds:
            logger.warning(
                "Live price for %s is stale (%.0fs old), skipping offset",
                mt5_symbol,
                age.total_seconds(),
            )
            return None

        feed_mid = (float(live_price_row["bid"]) + float(live_price_row["ask"])) / 2

        # Prefer ic_bid/ic_ask: both OANDA/Binance and ICMarkets prices are written
        # to the same row at the same flush time — no inter-fetch drift.
        try:
            ic_bid = live_price_row["ic_bid"]
            ic_ask = live_price_row["ic_ask"]
        except (KeyError, IndexError):
            ic_bid = None
            ic_ask = None

        if ic_bid is not None and ic_ask is not None:
            ic_mid = (float(ic_bid) + float(ic_ask)) / 2
            return ic_mid - feed_mid

        # Fallback: live MT5 tick (ic columns not yet populated — rolling-deploy gap).
        if mt5_symbol not in self._ic_fallback_logged:
            logger.warning(
                "ic_bid/ic_ask NULL for %s — falling back to live MT5 tick (rolling-deploy gap?)",
                mt5_symbol,
            )
            self._ic_fallback_logged.add(mt5_symbol)

        tick = mt5_client.symbol_info_tick(mt5_symbol)
        if tick is None:
            logger.error("Cannot get MT5 tick for %s to compute offset", mt5_symbol)
            return None

        mt5_mid = (tick.bid + tick.ask) / 2
        return mt5_mid - feed_mid

    def check_drift(self, current_offset: float, stored_offset: float, threshold: float) -> bool:
        return abs(current_offset - stored_offset) > threshold
