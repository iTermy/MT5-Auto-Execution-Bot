import asyncpg

from bot.db.supabase import SupabaseDB


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    """fetchrow raises UndefinedColumnError for the signals_rev query (legacy DB)
    and answers the legacy query with a plain dict row."""

    def __init__(self):
        self.queries: list[str] = []

    async def fetchrow(self, query):
        self.queries.append(query)
        if "signals_rev" in query:
            raise asyncpg.exceptions.UndefinedColumnError("column does not exist")
        return {"news_mode": "EUR", "vol_guard": None}


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self, timeout=None):
        return _FakeAcquire(self._conn)


async def test_fetch_sync_state_legacy_fallback() -> None:
    db = SupabaseDB("postgresql://unused")
    conn = _FakeConn()
    db._pool = _FakePool(conn)

    assert await db.fetch_sync_state() == ("EUR", None, None)
    # The missing column is not retried: subsequent polls go straight to legacy.
    assert await db.fetch_sync_state() == ("EUR", None, None)
    assert sum("signals_rev" in q for q in conn.queries) == 1
