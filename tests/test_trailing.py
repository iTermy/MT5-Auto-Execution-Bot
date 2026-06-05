import pytest

from bot.tp.asset_config import AssetClassConfig
from bot.tp.trailing import TrailingStopManager
from tests.conftest import make_order_result, make_position, make_symbol_info, make_tick


def _cfg(trail=0.0020) -> AssetClassConfig:
    return AssetClassConfig(
        profit_threshold=4.0,
        threshold_unit="dollars",
        partial_close_percent=50,
        trailing_distance=trail,
    )


def _pips_cfg(trail_pips=20.0) -> AssetClassConfig:
    return AssetClassConfig(
        profit_threshold=7.0,
        threshold_unit="pips",
        partial_close_percent=50,
        trailing_distance=trail_pips,
    )


# ---------------------------------------------------------------------------
# Long positions — SL ratchets up
# ---------------------------------------------------------------------------


async def test_long_initial_sl_set_when_zero(sqlite_db, mock_mt5) -> None:
    # sl=0 → initial set always happens regardless of guard
    pos = make_position(ticket=1001, type=0, sl=0.0)
    tick = make_tick(bid=1.12000, ask=1.12002)
    sym = make_symbol_info(digits=5, point=0.00001)
    mock_mt5.symbol_info.return_value = sym
    mock_mt5.modify_position_sl.return_value = make_order_result(ticket=1001)

    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=1001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(1001, "2026-01-01T00:01:00+00:00")
    await sqlite_db.set_trailing(1001)

    mgr = TrailingStopManager()
    updated = await mgr.update(pos, tick, _cfg(trail=0.0020), mock_mt5, sqlite_db)

    assert updated is True
    mock_mt5.modify_position_sl.assert_called_once()
    # new_sl = bid - trail = 1.12000 - 0.0020 = 1.11800
    call_sl = mock_mt5.modify_position_sl.call_args.args[2]
    assert call_sl == pytest.approx(1.11800, abs=1e-5)


async def test_long_sl_ratchets_up(sqlite_db, mock_mt5) -> None:
    # sl=1.10000; new_sl = 1.12000 - 0.002 = 1.11800 > 1.10000 → moves
    pos = make_position(ticket=1001, type=0, sl=1.10000)
    tick = make_tick(bid=1.12000, ask=1.12002)
    mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, point=0.00001)
    mock_mt5.modify_position_sl.return_value = make_order_result(ticket=1001)

    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=1001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.09000,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(1001, "2026-01-01T00:01:00+00:00")
    await sqlite_db.set_trailing(1001)

    mgr = TrailingStopManager()
    updated = await mgr.update(pos, tick, _cfg(trail=0.0020), mock_mt5, sqlite_db)

    assert updated is True


async def test_long_sl_never_retreats(sqlite_db, mock_mt5) -> None:
    # sl=1.11900; new_sl = 1.12000 - 0.002 = 1.11800 <= 1.11900 → no move
    pos = make_position(ticket=1001, type=0, sl=1.11900)
    tick = make_tick(bid=1.12000, ask=1.12002)
    mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, point=0.00001)

    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=1001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.09000,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(1001, "2026-01-01T00:01:00+00:00")

    mgr = TrailingStopManager()
    updated = await mgr.update(pos, tick, _cfg(trail=0.0020), mock_mt5, sqlite_db)

    assert updated is False
    mock_mt5.modify_position_sl.assert_not_called()


# ---------------------------------------------------------------------------
# Short positions — SL ratchets down
# ---------------------------------------------------------------------------


async def test_short_sl_ratchets_down(sqlite_db, mock_mt5) -> None:
    # sl=1.15000; new_sl = ask + trail = 1.10002 + 0.002 = 1.10202 < 1.15000 → moves
    pos = make_position(ticket=1002, type=1, sl=1.15000)
    tick = make_tick(bid=1.10000, ask=1.10002)
    mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, point=0.00001)
    mock_mt5.modify_position_sl.return_value = make_order_result(ticket=1002)

    await sqlite_db.insert_order(
        limit_id=2,
        signal_id=2,
        mt5_ticket=1002,
        order_type="sell_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.15500,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(1002, "2026-01-01T00:01:00+00:00")
    await sqlite_db.set_trailing(1002)

    mgr = TrailingStopManager()
    updated = await mgr.update(pos, tick, _cfg(trail=0.0020), mock_mt5, sqlite_db)

    assert updated is True


async def test_short_sl_never_retreats(sqlite_db, mock_mt5) -> None:
    # sl=1.10500; new_sl = 1.10002 + 0.002 = 1.10202 < 1.10500 — retreat for short (moving up) → no move
    # Wait: for short, favorable SL movement is DOWNWARD. If new_sl >= old_sl → no move.
    # sl=1.10500, new_sl=1.10202 < 1.10500 → moves (favorable)
    # For no-move: sl=1.10100, new_sl=1.10202 >= 1.10100 → no move
    pos = make_position(ticket=1002, type=1, sl=1.10100)
    tick = make_tick(bid=1.10000, ask=1.10002)
    mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, point=0.00001)

    await sqlite_db.insert_order(
        limit_id=2,
        signal_id=2,
        mt5_ticket=1002,
        order_type="sell_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.15500,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(1002, "2026-01-01T00:01:00+00:00")

    mgr = TrailingStopManager()
    updated = await mgr.update(pos, tick, _cfg(trail=0.0020), mock_mt5, sqlite_db)

    assert updated is False
    mock_mt5.modify_position_sl.assert_not_called()


# ---------------------------------------------------------------------------
# Pips mode — trail_dist converted to price
# ---------------------------------------------------------------------------


async def test_retcode_no_changes_treated_as_no_op(sqlite_db, mock_mt5) -> None:
    """TRADE_RETCODE_NO_CHANGES (10025) means the requested SL is already at the
    target — must not be logged as an error and must not retry. Return False so
    the caller knows no update happened, but without surfacing a failure."""
    import MetaTrader5 as mt5

    pos = make_position(ticket=1003, type=0, sl=0.0)
    tick = make_tick(bid=1.12000, ask=1.12002)
    mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, point=0.00001)
    mock_mt5.modify_position_sl.return_value = make_order_result(
        retcode=mt5.TRADE_RETCODE_NO_CHANGES, ticket=1003
    )

    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=1003,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(1003, "2026-01-01T00:01:00+00:00")
    await sqlite_db.set_trailing(1003)

    mgr = TrailingStopManager()
    updated = await mgr.update(pos, tick, _cfg(trail=0.0020), mock_mt5, sqlite_db)

    assert updated is False


async def test_trailing_pips_mode_converts_to_price(sqlite_db, mock_mt5) -> None:
    # digits=5, point=0.00001 → pip_sz=0.0001
    # trail_pips=20 → trail_dist=0.0020 (same as dollars test above, but via pips mode)
    pos = make_position(ticket=1001, type=0, sl=0.0)
    tick = make_tick(bid=1.12000, ask=1.12002)
    mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, point=0.00001)
    mock_mt5.modify_position_sl.return_value = make_order_result(ticket=1001)

    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=1001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(1001, "2026-01-01T00:01:00+00:00")
    await sqlite_db.set_trailing(1001)

    mgr = TrailingStopManager()
    updated = await mgr.update(pos, tick, _pips_cfg(trail_pips=20.0), mock_mt5, sqlite_db)

    assert updated is True
    call_sl = mock_mt5.modify_position_sl.call_args.args[2]
    assert call_sl == pytest.approx(1.12000 - 20 * 0.0001, abs=1e-5)
