import pytest

import MetaTrader5 as mt5

from bot.tp.asset_config import AssetClassConfig
from bot.tp.default_strategy import DefaultTPStrategy
from tests.conftest import (
    make_order_result, make_position, make_symbol_info, make_tick, make_settings,
)


def _dollars_cfg(threshold=4.0, trail=2.0, pct=50) -> AssetClassConfig:
    return AssetClassConfig(
        profit_threshold=threshold,
        threshold_unit="dollars",
        partial_close_percent=pct,
        trailing_distance=trail,
    )


def _pips_cfg(threshold=7.0, trail=3.0, pct=50) -> AssetClassConfig:
    return AssetClassConfig(
        profit_threshold=threshold,
        threshold_unit="pips",
        partial_close_percent=pct,
        trailing_distance=trail,
    )


# ---------------------------------------------------------------------------
# should_trigger — dollars mode
# ---------------------------------------------------------------------------

def test_trigger_dollars_newest_above_threshold(mock_mt5) -> None:
    # price_open=1.0, bid=5.5, move=4.5 >= threshold=4.0 → True (no others)
    pos = make_position(ticket=1, price_open=1.0, type=0, profit=0.0)
    mock_mt5.symbol_info_tick.return_value = make_tick(bid=5.5, ask=5.502)

    strategy = DefaultTPStrategy()
    assert strategy.should_trigger([pos], _dollars_cfg(threshold=4.0), mock_mt5) is True


def test_trigger_dollars_newest_below_threshold(mock_mt5) -> None:
    pos = make_position(ticket=1, price_open=1.0, type=0, profit=0.0)
    mock_mt5.symbol_info_tick.return_value = make_tick(bid=4.0, ask=4.002)  # move=3.0 < 4.0

    strategy = DefaultTPStrategy()
    assert strategy.should_trigger([pos], _dollars_cfg(threshold=4.0), mock_mt5) is False


def test_trigger_dollars_others_negative_blocks(mock_mt5) -> None:
    # newest (ticket=2, highest) in profit, others (ticket=1) losing → no trigger
    pos1 = make_position(ticket=1, price_open=1.0, type=0, profit=-50.0)
    pos2 = make_position(ticket=2, price_open=1.0, type=0, profit=0.0)
    mock_mt5.symbol_info_tick.return_value = make_tick(bid=6.0, ask=6.002)  # move=5.0 >= 4.0

    strategy = DefaultTPStrategy()
    assert strategy.should_trigger([pos1, pos2], _dollars_cfg(threshold=4.0), mock_mt5) is False


def test_trigger_dollars_others_nonnegative_passes(mock_mt5) -> None:
    pos1 = make_position(ticket=1, price_open=1.0, type=0, profit=0.0)   # others sum = 0
    pos2 = make_position(ticket=2, price_open=1.0, type=0, profit=0.0)
    mock_mt5.symbol_info_tick.return_value = make_tick(bid=6.0, ask=6.002)

    strategy = DefaultTPStrategy()
    assert strategy.should_trigger([pos1, pos2], _dollars_cfg(threshold=4.0), mock_mt5) is True


# ---------------------------------------------------------------------------
# should_trigger — pips mode
# ---------------------------------------------------------------------------

def test_trigger_pips_mode(mock_mt5) -> None:
    # price_open=1.09000, bid=1.09800 → move=0.008, pip_sz=0.0001 → 80 pips >= 7 → True
    pos = make_position(ticket=1, price_open=1.09000, type=0)
    mock_mt5.symbol_info_tick.return_value = make_tick(bid=1.09800, ask=1.09802)
    mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, point=0.00001)

    strategy = DefaultTPStrategy()
    assert strategy.should_trigger([pos], _pips_cfg(threshold=7.0), mock_mt5) is True


def test_trigger_pips_mode_below_threshold(mock_mt5) -> None:
    # move=0.0003 → 3 pips < 7 → False
    pos = make_position(ticket=1, price_open=1.09000, type=0)
    mock_mt5.symbol_info_tick.return_value = make_tick(bid=1.09003, ask=1.09005)
    mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, point=0.00001)

    strategy = DefaultTPStrategy()
    assert strategy.should_trigger([pos], _pips_cfg(threshold=7.0), mock_mt5) is False


# ---------------------------------------------------------------------------
# execute — partial_close_percent variants
# ---------------------------------------------------------------------------

async def test_execute_pct_zero_sets_trailing(sqlite_db, mock_mt5) -> None:
    # pct=0 → set_trailing, no close
    pos = make_position(ticket=1001)
    await sqlite_db.insert_order(
        limit_id=1, signal_id=1, mt5_ticket=1001,
        order_type="buy_limit", lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500, signal_type="standard",
    )
    await sqlite_db.mark_filled(1001, "2026-01-01T00:01:00+00:00")

    strategy = DefaultTPStrategy()
    result = await strategy.execute(1, [pos], _dollars_cfg(pct=0), mock_mt5, sqlite_db)

    assert 1001 in result.trailed_tickets
    assert result.closed_tickets == []
    mock_mt5.close_position.assert_not_called()

    rows = await sqlite_db.get_trailing_positions()
    assert any(r["mt5_ticket"] == 1001 for r in rows)


async def test_execute_pct_100_closes_all(sqlite_db, mock_mt5) -> None:
    # pct=100 → close newest fully, no trailing
    pos = make_position(ticket=1001)
    await sqlite_db.insert_order(
        limit_id=1, signal_id=1, mt5_ticket=1001,
        order_type="buy_limit", lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500, signal_type="standard",
    )
    await sqlite_db.mark_filled(1001, "2026-01-01T00:01:00+00:00")
    mock_mt5.close_position.return_value = make_order_result(ticket=1001)

    strategy = DefaultTPStrategy()
    result = await strategy.execute(1, [pos], _dollars_cfg(pct=100), mock_mt5, sqlite_db)

    assert 1001 in result.closed_tickets
    assert result.trailed_tickets == []

    rows = await sqlite_db.get_all_active()
    assert all(r["status"] != "filled" for r in rows)


async def test_execute_pct_50_partial_close(sqlite_db, mock_mt5) -> None:
    # pct=50 → partial close (close vol = volume * 0.5)
    pos = make_position(ticket=1001, volume=0.2)
    await sqlite_db.insert_order(
        limit_id=1, signal_id=1, mt5_ticket=1001,
        order_type="buy_limit", lot_size=0.2,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500, signal_type="standard",
    )
    await sqlite_db.mark_filled(1001, "2026-01-01T00:01:00+00:00")
    mock_mt5.close_position.return_value = make_order_result(ticket=1001)

    strategy = DefaultTPStrategy()
    result = await strategy.execute(1, [pos], _dollars_cfg(pct=50), mock_mt5, sqlite_db)

    assert 1001 in result.closed_tickets
    call_args = mock_mt5.close_position.call_args
    assert call_args.kwargs["volume"] == pytest.approx(0.1, abs=1e-6)  # 50% of 0.2


async def test_execute_closes_earlier_positions_first(sqlite_db, mock_mt5) -> None:
    # Two positions: ticket=1001 (older) and ticket=1002 (newest)
    # Earlier (1001) should be fully closed; newest (1002) is partial-closed or trailing
    pos1 = make_position(ticket=1001, volume=0.1)
    pos2 = make_position(ticket=1002, volume=0.1)
    for ticket, lid in [(1001, 1), (1002, 2)]:
        await sqlite_db.insert_order(
            limit_id=lid, signal_id=1, mt5_ticket=ticket,
            order_type="buy_limit", lot_size=0.1,
            placed_at="2026-01-01T00:00:00+00:00",
            db_stop_loss=1.08500, signal_type="standard",
        )
        await sqlite_db.mark_filled(ticket, "2026-01-01T00:01:00+00:00")
    mock_mt5.close_position.return_value = make_order_result()

    strategy = DefaultTPStrategy()
    result = await strategy.execute(1, [pos1, pos2], _dollars_cfg(pct=50), mock_mt5, sqlite_db)

    # Earlier position (1001) closed; newest (1002) partial-closed
    assert 1001 in result.closed_tickets
    assert 1002 in result.closed_tickets
    assert mock_mt5.close_position.call_count == 2
