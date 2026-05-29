import logging

import aiosqlite

from bot.db.queries import (
    CREATE_ORDER_MAPPINGS,
    GET_ALL_ACTIVE,
    GET_FILLED_POSITIONS,
    GET_FILLED_SIGNAL_IDS,
    GET_ORDER_HISTORY,
    GET_PENDING_BY_SIGNAL,
    GET_PENDING_ORDERS,
    GET_TRAILING_POSITIONS,
    INSERT_ORDER,
    MARK_CANCELLED,
    MARK_CLOSED,
    MARK_FILLED,
    SET_TRAILING,
    UPDATE_DB_STOP_LOSS,
    UPDATE_SL,
    UPDATE_TICKET,
)

logger = logging.getLogger(__name__)


class SQLiteDB:
    def __init__(self, path: str = "orders.db") -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def init_schema(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute(CREATE_ORDER_MAPPINGS)
        await self._db.commit()
        # Migrations for existing databases
        for col in ("symbol TEXT", "realized_pnl REAL", "channel_id INTEGER"):
            name = col.split()[0]
            try:
                await self._db.execute(f"SELECT {name} FROM order_mappings LIMIT 0")
            except Exception:
                await self._db.execute(f"ALTER TABLE order_mappings ADD COLUMN {col}")
                await self._db.commit()
                logger.info("Migration: added %s column", name)
        logger.info("SQLite schema ready: %s", self._path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def insert_order(
        self,
        limit_id: int,
        signal_id: int,
        mt5_ticket: int,
        order_type: str,
        lot_size: float,
        placed_at: str,
        db_stop_loss: float,
        is_scalp: int,
        feed_price: float | None = None,
        mt5_price: float | None = None,
        offset: float | None = None,
        symbol: str | None = None,
        channel_id: int | None = None,
    ) -> None:
        await self._db.execute(
            "DELETE FROM order_mappings WHERE limit_id = ? AND status NOT IN ('pending', 'filled')",
            (limit_id,),
        )
        await self._db.execute(
            INSERT_ORDER,
            (limit_id, signal_id, mt5_ticket, order_type, lot_size, placed_at,
             db_stop_loss, is_scalp, feed_price, mt5_price, offset, symbol, channel_id),
        )
        await self._db.commit()

    async def mark_filled(self, mt5_ticket: int, filled_at: str) -> None:
        await self._db.execute(MARK_FILLED, (filled_at, mt5_ticket))
        await self._db.commit()

    async def mark_cancelled(
        self, mt5_ticket: int, cancelled_at: str, spread: bool = False
    ) -> None:
        status = "spread_cancelled" if spread else "cancelled"
        await self._db.execute(MARK_CANCELLED, (status, cancelled_at, mt5_ticket))
        await self._db.commit()

    async def mark_closed(self, mt5_ticket: int, realized_pnl: float | None = None) -> None:
        await self._db.execute(MARK_CLOSED, (realized_pnl, mt5_ticket))
        await self._db.commit()

    async def set_trailing(self, mt5_ticket: int, is_trailing: int = 1) -> None:
        await self._db.execute(SET_TRAILING, (is_trailing, mt5_ticket))
        await self._db.commit()

    async def get_pending_orders(self) -> list[aiosqlite.Row]:
        async with self._db.execute(GET_PENDING_ORDERS) as cursor:
            return await cursor.fetchall()

    async def get_filled_positions(self) -> list[aiosqlite.Row]:
        async with self._db.execute(GET_FILLED_POSITIONS) as cursor:
            return await cursor.fetchall()

    async def get_trailing_positions(self) -> list[aiosqlite.Row]:
        async with self._db.execute(GET_TRAILING_POSITIONS) as cursor:
            return await cursor.fetchall()

    async def get_all_active(self) -> list[aiosqlite.Row]:
        async with self._db.execute(GET_ALL_ACTIVE) as cursor:
            return await cursor.fetchall()

    async def update_sl(self, mt5_ticket: int, sl: float) -> None:
        await self._db.execute(UPDATE_SL, (sl, mt5_ticket))
        await self._db.commit()

    async def update_ticket(self, old_ticket: int, new_ticket: int) -> None:
        await self._db.execute(UPDATE_TICKET, (new_ticket, old_ticket))
        await self._db.commit()

    async def get_pending_by_signal(self, signal_id: int) -> list[aiosqlite.Row]:
        async with self._db.execute(GET_PENDING_BY_SIGNAL, (signal_id,)) as cursor:
            return await cursor.fetchall()

    async def get_filled_signal_ids(self) -> set[int]:
        async with self._db.execute(GET_FILLED_SIGNAL_IDS) as cursor:
            rows = await cursor.fetchall()
        return {row["signal_id"] for row in rows}

    async def get_order_history(self, from_date: str, to_date: str) -> list[aiosqlite.Row]:
        async with self._db.execute(GET_ORDER_HISTORY, (from_date, to_date)) as cursor:
            return await cursor.fetchall()

    async def update_db_stop_loss(self, mt5_ticket: int, new_db_sl: float, new_mt5_sl: float) -> None:
        await self._db.execute(UPDATE_DB_STOP_LOSS, (new_db_sl, new_mt5_sl, mt5_ticket))
        await self._db.commit()
