from unittest.mock import AsyncMock

import pytest

from bot.tp.finalizer import TPFinalizer
from tests.conftest import make_account_info, make_settings, make_symbol_info


async def _seed_closed_signal(
    db, signal_id=1, ticket=1001, pnl=11.4, entry=4459.0, sl=4440.0, vol=0.3, trailing=False
) -> None:
    await db.insert_order(
        limit_id=ticket,
        signal_id=signal_id,
        mt5_ticket=ticket,
        order_type="buy_limit",
        lot_size=vol,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=sl,
        signal_type="standard",
        mt5_price=entry,
        symbol="XAUUSD",
        sequence_number=2,
    )
    await db.mark_filled(ticket, "2026-01-01T00:01:00+00:00")
    await db.update_excursion(ticket, 8.0, 3.0)
    if trailing:
        await db.set_trailing(ticket)
    await db.mark_closed(ticket, pnl)


def _finalizer(mock_mt5):
    # tick_value/tick_size = 1.0 → risk_money = |entry-sl| * volume
    mock_mt5.symbol_info.return_value = make_symbol_info(
        name="XAUUSD", trade_tick_value=1.0, trade_tick_size=1.0
    )
    mock_mt5.account_info.return_value = make_account_info()
    writer = AsyncMock()
    return TPFinalizer(writer), writer


@pytest.mark.asyncio
async def test_sweep_writes_one_final_row(sqlite_db, mock_mt5) -> None:
    await _seed_closed_signal(sqlite_db)
    fin, writer = _finalizer(mock_mt5)

    await fin.sweep(mock_mt5, sqlite_db, make_settings())

    writer.record.assert_awaited_once()
    outcome = writer.record.await_args.args[0]
    assert outcome.stage == "final"
    assert outcome.realized_pnl == pytest.approx(11.4)
    # risk_money = |4459-4440| * 0.3 = 5.7 → r = 11.4 / 5.7 = 2.0
    assert outcome.r_multiple == pytest.approx(2.0)
    assert outcome.mfe_price == pytest.approx(8.0)
    assert outcome.mfe_r == pytest.approx(8.0 / 19.0)
    assert outcome.mae_r == pytest.approx(3.0 / 19.0)
    assert outcome.level_sequence == 2
    assert outcome.exit_reason == "tp_full"
    assert outcome.hold_seconds is not None and outcome.hold_seconds > 0


@pytest.mark.asyncio
async def test_sweep_is_idempotent(sqlite_db, mock_mt5) -> None:
    await _seed_closed_signal(sqlite_db)
    fin, writer = _finalizer(mock_mt5)

    await fin.sweep(mock_mt5, sqlite_db, make_settings())
    await fin.sweep(mock_mt5, sqlite_db, make_settings())

    writer.record.assert_awaited_once()  # second sweep writes nothing


@pytest.mark.asyncio
async def test_trailing_exit_reason(sqlite_db, mock_mt5) -> None:
    await _seed_closed_signal(sqlite_db, trailing=True)
    fin, writer = _finalizer(mock_mt5)

    await fin.sweep(mock_mt5, sqlite_db, make_settings())

    assert writer.record.await_args.args[0].exit_reason == "trailing_stop"


@pytest.mark.asyncio
async def test_loss_exit_reason(sqlite_db, mock_mt5) -> None:
    await _seed_closed_signal(sqlite_db, pnl=-30.0)
    fin, writer = _finalizer(mock_mt5)

    await fin.sweep(mock_mt5, sqlite_db, make_settings())

    assert writer.record.await_args.args[0].exit_reason == "stop_loss"


@pytest.mark.asyncio
async def test_sweep_skips_open_position(sqlite_db, mock_mt5) -> None:
    # filled but not closed → not settled
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=1001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4440.0,
        signal_type="standard",
        symbol="XAUUSD",
    )
    await sqlite_db.mark_filled(1001, "2026-01-01T00:01:00+00:00")
    fin, writer = _finalizer(mock_mt5)

    await fin.sweep(mock_mt5, sqlite_db, make_settings())

    writer.record.assert_not_awaited()
