import logging

import asyncpg

from bot.db.queries import FETCH_ACTIVE_SIGNALS_WITH_LIMITS, FETCH_LIVE_PRICES, FETCH_SIGNAL_STATUSES

logger = logging.getLogger(__name__)


class SupabaseDB:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def create_pool(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=3, command_timeout=10
        )
        logger.info("Supabase pool created")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("Supabase pool closed")

    async def fetch_active_signals(self) -> list[asyncpg.Record]:
        try:
            async with self._pool.acquire() as conn:
                return await conn.fetch(FETCH_ACTIVE_SIGNALS_WITH_LIMITS)
        except asyncpg.PostgresError as e:
            logger.error("fetch_active_signals failed: %s", e)
            return []

    async def fetch_live_prices(self, symbols: list[str]) -> dict[str, asyncpg.Record]:
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(FETCH_LIVE_PRICES, symbols)
            return {row["symbol"]: row for row in rows}
        except asyncpg.PostgresError as e:
            logger.error("fetch_live_prices failed: %s", e)
            return {}

    async def fetch_signal_statuses(self, signal_ids: list[int]) -> dict[int, str]:
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(FETCH_SIGNAL_STATUSES, signal_ids)
            return {row["id"]: row["status"] for row in rows}
        except asyncpg.PostgresError as e:
            logger.error("fetch_signal_statuses failed: %s", e)
            return {}
