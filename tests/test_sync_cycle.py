import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.core.sync_cycle import SyncCycle
from tests.conftest import make_order_result, make_settings, make_symbol_info


def _make_supabase_row(limit_id=1, signal_id=1, instrument="EURUSD") -> dict:
    return {
        "limit_id": limit_id,
        "signal_id": signal_id,
        "instrument": instrument,
        "direction": "long",
        "stop_loss": 1.08500,
        "price_level": 1.09100,
        "signal_type": "standard",
        "channel_id": None,
    }


def _mock_supabase(signals=None, live_prices=None):
    sb = AsyncMock()
    sb.fetch_active_signals.return_value = signals or []
    sb.fetch_live_prices.return_value = live_prices or {}
    sb.fetch_signal_statuses.return_value = {}
    return sb


def _mock_scheduler(cancel_pending=False):
    sched = MagicMock()
    sched.should_cancel_pending.return_value = cancel_pending
    sched.should_block_placement.return_value = False
    return sched


# ---------------------------------------------------------------------------
# Idempotency: already-tracked limits are not re-placed
# ---------------------------------------------------------------------------

async def test_idempotency_known_limit_not_replaced(sqlite_db, mock_mt5, sample_config) -> None:
    # Pre-populate SQLite with limit_id=1
    await sqlite_db.insert_order(
        limit_id=1, signal_id=1, mt5_ticket=1001,
        order_type="buy_limit", lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500, signal_type="standard",
    )

    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=1)])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    mock_mt5.order_send.assert_not_called()


async def test_idempotency_second_run_is_noop(sqlite_db, mock_mt5, sample_config) -> None:
    # Two consecutive runs with the same single known limit → placed=0 both times
    await sqlite_db.insert_order(
        limit_id=2, signal_id=1, mt5_ticket=1002,
        order_type="buy_limit", lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500, signal_type="standard",
    )
    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=2)])
    scheduler = _mock_scheduler()
    cycle = SyncCycle()

    r1 = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)
    r2 = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert r1.placed == 0
    assert r2.placed == 0


# ---------------------------------------------------------------------------
# Spread hour: pending orders are cancelled, placement is skipped
# ---------------------------------------------------------------------------

async def test_spread_hour_cancels_pending(sqlite_db, mock_mt5, sample_config) -> None:
    await sqlite_db.insert_order(
        limit_id=1, signal_id=1, mt5_ticket=2001,
        order_type="buy_limit", lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500, signal_type="standard",
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=2001)

    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=1)])
    scheduler = _mock_scheduler(cancel_pending=True)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 1
    mock_mt5.cancel_pending_order.assert_called_once_with(2001)

    # Verify SQLite row is now spread_cancelled
    rows = await sqlite_db.get_pending_orders()
    assert len(rows) == 0


async def test_spread_hour_skips_new_placements(sqlite_db, mock_mt5, sample_config) -> None:
    # No pending in SQLite, one new limit from Supabase, but spread hour active → no placement
    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=99)])
    scheduler = _mock_scheduler(cancel_pending=True)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    mock_mt5.order_send.assert_not_called()


# ---------------------------------------------------------------------------
# Offset drift: drifted pending orders are cancelled for re-placement
# ---------------------------------------------------------------------------

async def test_offset_drift_cancels_pending(sqlite_db, mock_mt5, sample_config) -> None:
    # Insert pending order for SPX500USD with offset_at_placement=10.0
    await sqlite_db.insert_order(
        limit_id=10, signal_id=1, mt5_ticket=3001,
        order_type="buy_limit", lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0, signal_type="standard",
        feed_price=4500.0, mt5_price=4510.0, offset=10.0,
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=3001)
    # US500 symbol info (mapped from SPX500USD)
    mock_mt5.symbol_info.return_value = make_symbol_info(
        name="US500", digits=1, point=0.1
    )

    row = _make_supabase_row(limit_id=10, instrument="SPX500USD")
    row["stop_loss"] = 4000.0
    row["price_level"] = 4510.0
    supabase = _mock_supabase(
        signals=[row],
        live_prices={"SPX500USD": {"bid": 4590.0, "ask": 4591.0, "updated_at": None}},
    )
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    # Patch OffsetCalculator on this instance to simulate large drift
    cycle._offset_calc.get_offset = MagicMock(return_value=90.0)
    cycle._offset_calc.check_drift = MagicMock(return_value=True)

    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 1
    mock_mt5.cancel_pending_order.assert_called_once_with(3001)

    rows = await sqlite_db.get_pending_orders()
    assert len(rows) == 0
