from types import SimpleNamespace

import pytest

from bot.config.constants import MAGIC_NUMBER
from bot.core.history_import import history_rows


def deal(**kwargs):
    return SimpleNamespace(
        **{
            "position_id": 100,
            "entry": 0,
            "type": 0,
            "magic": MAGIC_NUMBER,
            "volume": 1.0,
            "time": 1700000000,
            "comment": "s12_l34",
            "symbol": "EURUSD",
            "profit": 0,
            "commission": -1,
            "swap": 0,
            "fee": -0.5,
            **kwargs,
        }
    )


def test_partial_exits_include_broker_magic_and_all_costs():
    rows, skipped = history_rows(
        [
            deal(),
            deal(entry=1, magic=0, volume=0.4, profit=10, time=1700000010),
            deal(entry=3, magic=0, volume=0.6, profit=20, swap=-2, time=1700000020),
            deal(position_id=200, magic=9),
            deal(position_id=200, entry=1, magic=9),
        ]
    )
    assert skipped == 0
    assert len(rows) == 1
    assert rows[0][:3] == (100, 34, 12)
    assert rows[0][-1] == 23.5


@pytest.mark.parametrize("exits", [[], [deal(entry=1, volume=0.5)], [deal(entry=2)]])
def test_skip_open_incomplete_and_reversed(exits):
    assert history_rows([deal(), *exits]) == ([], 1)


async def test_import_is_idempotent_and_separate_from_trading(sqlite_db):
    rows, _ = history_rows([deal(comment=""), deal(entry=1, profit=10)])
    assert await sqlite_db.import_history(rows) == 1
    assert await sqlite_db.import_history(rows) == 0
    history = await sqlite_db.get_order_history("1970", "2099")
    assert history[0]["signal_id"] == -100
    assert history[0]["signal_type"] == "unknown"
    assert history[0]["total_pnl"] == 7
    assert (await sqlite_db.get_user_stats())["total_pnl"] == 7
    assert await sqlite_db.get_signals_with_fills() == set()
    await sqlite_db.clear_history()
    assert await sqlite_db.get_order_history("1970", "2099") == []


async def test_existing_local_position_is_not_double_counted(sqlite_db):
    await sqlite_db.insert_order(
        limit_id=34,
        signal_id=12,
        mt5_ticket=101,
        order_type="buy",
        lot_size=1,
        placed_at="2023-01-01",
        db_stop_loss=1,
        signal_type="scalp",
    )
    await sqlite_db.mark_filled(101, "2023-01-01")
    await sqlite_db.mark_closed(101, 20)
    rows, _ = history_rows([deal(), deal(entry=1, profit=10)])
    assert await sqlite_db.import_history(rows) == 0
    assert (await sqlite_db.get_user_stats())["total_pnl"] == 20
