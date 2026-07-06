import asyncio
import logging

import asyncpg

from bot.db.queries import (
    FETCH_FEED_HEALTH,
    FETCH_LIVE_PRICES,
    FETCH_MODE_GATES,
    FETCH_SIGNAL_SETS,
    FETCH_SIGNAL_STATUS,
    FETCH_SIGNAL_STATUSES,
    UPSERT_USER_SNAPSHOT,
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
                    # statement_cache_size=0 disables client-side prepared statements
                    # so the same code works with Supabase's transaction-mode pooler
                    # (port 6543), which doesn't keep server-side state between calls.
                    # Cost in session mode is negligible (sub-ms per query).
                    statement_cache_size=0,
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

    async def fetch_signal_sets(
        self,
    ) -> tuple[list[asyncpg.Record], set[int], dict[int, int]]:
        """The three active-signal sets in one round-trip (egress guard): the
        active+pending rows to place, the TM-marked 'hit' limit ids to spare from
        stale-cancel, and the {limit_id: signal_id} map for 'profit'-marked signals."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(FETCH_SIGNAL_SETS)
        active = [
            r
            for r in rows
            if r["signal_status"] in ("active", "hit") and r["limit_status"] == "pending"
        ]
        hit_limit_ids = {
            r["limit_id"]
            for r in rows
            if r["signal_status"] in ("active", "hit") and r["limit_status"] == "hit"
        }
        profit_limit_signal = {
            r["limit_id"]: r["signal_id"] for r in rows if r["signal_status"] == "profit"
        }
        return active, hit_limit_ids, profit_limit_signal

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

    async def fetch_mode_gates(self) -> tuple[str | None, str | None]:
        """Return (news_mode, vol_guard) from the single bot_mode_status row. Both are
        comma-separated token lists (or 'ALL'), NULL when the respective mode is off."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(FETCH_MODE_GATES)
        if row is None:
            return None, None
        return row["news_mode"], row["vol_guard"]

    async def fetch_feed_health(self) -> dict[str, str]:
        """Return {feed_name: status} from the feed_health table."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(FETCH_FEED_HEALTH)
        return {row["feed"]: row["status"] for row in rows}

    async def upsert_user_snapshot(
        self,
        license_key: str,
        mt5_account: int,
        balance: float,
        equity: float,
        currency: str,
        leverage: int,
        open_positions_count: int,
        total_realized_pnl: float,
        total_trades: int,
        wins: int,
        losses: int,
        win_rate: float,
        bot_version: str,
    ) -> None:
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    UPSERT_USER_SNAPSHOT,
                    license_key,
                    mt5_account,
                    balance,
                    equity,
                    currency,
                    leverage,
                    open_positions_count,
                    total_realized_pnl,
                    total_trades,
                    wins,
                    losses,
                    win_rate,
                    bot_version,
                )
        except Exception:
            logger.error("User snapshot upsert failed account=%d", mt5_account, exc_info=True)
