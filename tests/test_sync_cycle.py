from unittest.mock import AsyncMock, MagicMock

from bot.core.sync_cycle import SyncCycle
from tests.conftest import make_order_result, make_symbol_info


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


def _mock_supabase(signals=None, live_prices=None, news_mode=False):
    sb = AsyncMock()
    sb.fetch_active_signals.return_value = signals or []
    sb.fetch_live_prices.return_value = live_prices or {}
    sb.fetch_signal_statuses.return_value = {}
    sb.fetch_news_mode.return_value = news_mode
    sb.fetch_feed_health.return_value = {}
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
        limit_id=1,
        signal_id=1,
        mt5_ticket=1001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
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
        limit_id=2,
        signal_id=1,
        mt5_ticket=1002,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
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
        limit_id=1,
        signal_id=1,
        mt5_ticket=2001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
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
        limit_id=10,
        signal_id=1,
        mt5_ticket=3001,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
        feed_price=4500.0,
        mt5_price=4510.0,
        offset=10.0,
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=3001)
    # US500 symbol info (mapped from SPX500USD)
    mock_mt5.symbol_info.return_value = make_symbol_info(name="US500", digits=1, point=0.1)

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


# ---------------------------------------------------------------------------
# Crypto exemption from spread-hour and news-mode gates
# ---------------------------------------------------------------------------


async def test_spread_hour_skips_crypto_cancellation(sqlite_db, mock_mt5, sample_config) -> None:
    # Two pendings: one BTCUSDT (crypto) and one EURUSD. Spread hour fires.
    # Only the EURUSD order should be cancelled; BTCUSDT survives.
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=4001,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08,
        signal_type="standard",
        symbol="EURUSD",
    )
    await sqlite_db.insert_order(
        limit_id=2,
        signal_id=2,
        mt5_ticket=4002,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=60000.0,
        signal_type="standard",
        symbol="BTCUSD",  # MT5 symbol; maps from BTCUSDT
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=4001)

    eur_row = _make_supabase_row(limit_id=1, signal_id=1, instrument="EURUSD")
    btc_row = _make_supabase_row(limit_id=2, signal_id=2, instrument="BTCUSDT")
    btc_row["stop_loss"] = 60000.0  # match SQLite to avoid the SL-change cancel path
    supabase = _mock_supabase(signals=[eur_row, btc_row])
    scheduler = _mock_scheduler(cancel_pending=True)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 1
    mock_mt5.cancel_pending_order.assert_called_once_with(4001)
    pending = await sqlite_db.get_pending_orders()
    assert {r["mt5_ticket"] for r in pending} == {4002}


# ---------------------------------------------------------------------------
# Offset drift interval throttle: skip re-evaluation within 30 min window
# ---------------------------------------------------------------------------


async def test_drift_skipped_when_sibling_already_filled(
    sqlite_db, mock_mt5, sample_config
) -> None:
    """A pending limit on a signal whose sibling already filled must not be cancelled
    by offset drift — once a limit has hit, the remaining pendings should hold their
    placement instead of being yanked further from the existing entry."""
    # Sibling limit on the same signal — already filled into a position
    await sqlite_db.insert_order(
        limit_id=20,
        signal_id=7,
        mt5_ticket=6000,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
        feed_price=4500.0,
        mt5_price=4510.0,
        offset=10.0,
    )
    await sqlite_db.mark_filled(6000, "2026-01-01T00:01:00+00:00")

    # The pending limit we want to keep
    await sqlite_db.insert_order(
        limit_id=21,
        signal_id=7,
        mt5_ticket=6001,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
        feed_price=4500.0,
        mt5_price=4510.0,
        offset=10.0,
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=6001)
    mock_mt5.symbol_info.return_value = make_symbol_info(name="US500", digits=1, point=0.1)

    pending_row = _make_supabase_row(limit_id=21, signal_id=7, instrument="SPX500USD")
    pending_row["stop_loss"] = 4000.0
    pending_row["price_level"] = 4510.0
    filled_row = _make_supabase_row(limit_id=20, signal_id=7, instrument="SPX500USD")
    filled_row["stop_loss"] = 4000.0
    filled_row["price_level"] = 4510.0
    supabase = _mock_supabase(
        signals=[filled_row, pending_row],
        live_prices={"SPX500USD": {"bid": 4590.0, "ask": 4591.0, "updated_at": None}},
    )
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    cycle._offset_calc.get_offset = MagicMock(return_value=90.0)
    cycle._offset_calc.check_drift = MagicMock(return_value=True)

    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 0
    # Drift check should be skipped entirely — get_offset should not even be invoked
    # on a signal that has fills, regardless of throttle state.
    cycle._offset_calc.get_offset.assert_not_called()
    pending = await sqlite_db.get_pending_orders()
    assert {r["mt5_ticket"] for r in pending} == {6001}


async def test_drift_check_skipped_within_interval(sqlite_db, mock_mt5, sample_config) -> None:
    from datetime import UTC, datetime, timedelta

    await sqlite_db.insert_order(
        limit_id=10,
        signal_id=1,
        mt5_ticket=5001,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
        feed_price=4500.0,
        mt5_price=4510.0,
        offset=10.0,
    )
    # Mark a recent offset check (5 minutes ago), within the default 30-min throttle
    recent = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    await sqlite_db.update_last_offset_check(5001, recent)

    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=5001)
    mock_mt5.symbol_info.return_value = make_symbol_info(name="US500", digits=1, point=0.1)

    row = _make_supabase_row(limit_id=10, instrument="SPX500USD")
    row["stop_loss"] = 4000.0
    row["price_level"] = 4510.0
    supabase = _mock_supabase(
        signals=[row],
        live_prices={"SPX500USD": {"bid": 4590.0, "ask": 4591.0, "updated_at": None}},
    )
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    # Even with large drift configured, the throttle should prevent cancellation
    cycle._offset_calc.get_offset = MagicMock(return_value=90.0)
    cycle._offset_calc.check_drift = MagicMock(return_value=True)

    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 0
    cycle._offset_calc.get_offset.assert_not_called()
    rows = await sqlite_db.get_pending_orders()
    assert len(rows) == 1
