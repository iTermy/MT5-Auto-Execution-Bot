import logging

import asyncpg

from bot.db.queries import (
    FETCH_ACTIVE_SIGNALS_WITH_LIMITS,
    FETCH_FEED_HEALTH,
    FETCH_LIVE_PRICES,
    FETCH_NEWS_MODE,
    FETCH_SIGNAL_STATUS,
    FETCH_SIGNAL_STATUSES,
)

logger = logging.getLogger(__name__)


class SupabaseDB:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def create_pool(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=10, command_timeout=10
        )
        logger.info("Supabase pool created")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("Supabase pool closed")

    async def fetch_active_signals(self) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(FETCH_ACTIVE_SIGNALS_WITH_LIMITS)

    async def fetch_live_prices(self, symbols: list[str]) -> dict[str, asyncpg.Record]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(FETCH_LIVE_PRICES, symbols)
        return {row["symbol"]: row for row in rows}

    async def fetch_signal_status(self, signal_id: int) -> str | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(FETCH_SIGNAL_STATUS, signal_id)

    async def fetch_signal_statuses(self, signal_ids: list[int]) -> dict[int, str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(FETCH_SIGNAL_STATUSES, signal_ids)
        return {row["id"]: row["status"] for row in rows}

    async def fetch_news_mode(self) -> bool:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(FETCH_NEWS_MODE) or False

    async def fetch_feed_health(self) -> dict[str, str]:
        """Return {feed_name: status} from the feed_health table."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(FETCH_FEED_HEALTH)
        return {row["feed"]: row["status"] for row in rows}
