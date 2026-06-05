import asyncio
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

# Supabase session-mode poolers have a tight per-tenant connection limit
# (typically 15). Keep our pool small so a quick bot restart doesn't trip
# EMAXCONNSESSION while the pooler is still recycling stale sessions.
_POOL_MIN_SIZE = 1
_POOL_MAX_SIZE = 3
_POOL_RETRY_ATTEMPTS = 4
_POOL_RETRY_DELAY = 8.0


class SupabaseDB:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def create_pool(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, _POOL_RETRY_ATTEMPTS + 1):
            try:
                self._pool = await asyncpg.create_pool(
                    self._dsn,
                    min_size=_POOL_MIN_SIZE,
                    max_size=_POOL_MAX_SIZE,
                    command_timeout=10,
                    ssl="require",
                )
                logger.info("Supabase pool created")
                return
            except asyncpg.exceptions.InternalServerError as e:
                # Pooler is over its session limit — old connections from a previous
                # bot run will be reaped within ~30s, so back off and try again.
                if "EMAXCONNSESSION" not in str(e):
                    raise
                last_error = e
                if attempt < _POOL_RETRY_ATTEMPTS:
                    logger.warning(
                        "Supabase pooler at capacity (attempt %d/%d) — retrying in %.0fs",
                        attempt,
                        _POOL_RETRY_ATTEMPTS,
                        _POOL_RETRY_DELAY,
                    )
                    await asyncio.sleep(_POOL_RETRY_DELAY)
        assert last_error is not None
        raise last_error

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

    async def fetch_signal_statuses(self, signal_ids: list[int]) -> dict[int, dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(FETCH_SIGNAL_STATUSES, signal_ids)
        return {
            row["id"]: {"status": row["status"], "closed_reason": row["closed_reason"]}
            for row in rows
        }

    async def fetch_news_mode(self) -> bool:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(FETCH_NEWS_MODE) or False

    async def fetch_feed_health(self) -> dict[str, str]:
        """Return {feed_name: status} from the feed_health table."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(FETCH_FEED_HEALTH)
        return {row["feed"]: row["status"] for row in rows}
