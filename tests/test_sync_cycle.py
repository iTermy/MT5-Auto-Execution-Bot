from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from bot.config.settings import ExcludedChannelAssetConfig
from bot.core.sync_cycle import SyncCycle
from tests.conftest import (
    make_account_info,
    make_order_info,
    make_order_result,
    make_position,
    make_symbol_info,
    make_tick,
)


def _make_supabase_row(
    limit_id=1, signal_id=1, instrument="EURUSD", signal_status="active"
) -> dict:
    return {
        "limit_id": limit_id,
        "signal_id": signal_id,
        "instrument": instrument,
        "direction": "long",
        "stop_loss": 1.08500,
        "price_level": 1.09100,
        "signal_type": "standard",
        "signal_status": signal_status,
        "channel_id": None,
        "sequence_number": 1,
    }


def _mock_supabase(
    signals=None,
    live_prices=None,
    news_mode=None,
    vol_guard=None,
    hit_limit_ids=None,
    profit_limit_ids=None,
):
    sb = AsyncMock()
    sb.fetch_active_signals.return_value = signals or []
    sb.fetch_hit_limit_ids.return_value = set(hit_limit_ids or [])
    sb.fetch_profit_limit_ids.return_value = dict(profit_limit_ids or {})
    sb.fetch_live_prices.return_value = live_prices or {}
    sb.fetch_signal_statuses.return_value = {}
    sb.fetch_mode_gates.return_value = (news_mode, vol_guard)
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
# Re-placement guard: a limit that already filled on our end is never re-placed
# ---------------------------------------------------------------------------


async def test_filled_then_closed_limit_not_replaced(sqlite_db, mock_mt5, sample_config) -> None:
    # Limit filled on our broker, TP'd, and closed → SQLite row is 'closed'. The TM
    # never marked the limit hit, so Supabase still lists it pending. It must NOT be
    # placed a second time (the dangerous loop).
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=9001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(9001, "2026-01-01T00:01:00+00:00")
    await sqlite_db.mark_closed(9001, 12.50)

    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=1)])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    mock_mt5.order_send.assert_not_called()
    assert 1 in cycle._logged_already_filled


async def test_edited_limit_same_price_new_id_not_replaced(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # A TM message edit rebuilds the signal's limit rows with fresh IDENTITY ids. A level
    # we already filled+closed (limit_id=1, price 1.09100) reappears under a new limit_id=2
    # at the same price. The limit_id guard misses it, but the (signal_id, price) guard must
    # still block re-entry.
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=9201,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
        feed_price=1.09100,
    )
    await sqlite_db.mark_filled(9201, "2026-01-01T00:01:00+00:00")
    await sqlite_db.mark_closed(9201, 12.50)

    # New limit_id, same signal + same price_level (1.09100 per _make_supabase_row).
    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=2)])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    mock_mt5.order_send.assert_not_called()
    assert 2 in cycle._logged_already_filled


async def test_cancelled_limit_still_replaceable(sqlite_db, mock_mt5, sample_config) -> None:
    # A never-filled limit that was cancelled (e.g. spread hour / offset drift) must
    # still re-place — the guard only blocks limits that actually filled.
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=9101,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )
    await sqlite_db.mark_cancelled(9101, "2026-01-01T00:01:00+00:00", spread=True)

    mock_mt5.account_info.return_value = make_account_info()
    mock_mt5.order_send.return_value = make_order_result(ticket=9102)
    mock_mt5.order_get_by_ticket.return_value = None
    row = _make_supabase_row(limit_id=1)
    row["price_level"] = 1.09950  # within proximity of mid and below ask → valid buy_limit
    supabase = _mock_supabase(signals=[row])
    supabase.fetch_signal_status.return_value = "active"
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 1
    mock_mt5.order_send.assert_called_once()
    assert 1 not in cycle._logged_already_filled


async def test_replaced_limit_reuses_filled_sibling_lot(sqlite_db, mock_mt5, sample_config) -> None:
    # A signal with a filled sibling re-places its remaining limit using the sibling's
    # stored lot, not a fresh calc: the Supabase fetch drops hit limits (l.status='hit'),
    # so recomputing would split the size across fewer survivors and oversize the order.
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=9101,
        order_type="buy_limit",
        lot_size=0.33,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(9101, "2026-01-01T00:01:00+00:00")

    mock_mt5.account_info.return_value = make_account_info()
    mock_mt5.positions_get.return_value = [make_position(ticket=9101, volume=0.33)]
    mock_mt5.order_send.return_value = make_order_result(ticket=9102)
    mock_mt5.order_get_by_ticket.return_value = None
    row = _make_supabase_row(limit_id=2)  # new pending sibling of the same signal
    row["price_level"] = 1.09950
    supabase = _mock_supabase(signals=[row])
    supabase.fetch_signal_status.return_value = "active"
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 1
    assert mock_mt5.order_send.call_args.args[0].volume == 0.33


async def test_tp_fired_signal_limit_not_replaced(sqlite_db, mock_mt5, sample_config) -> None:
    # Our TP engine fired on signal 1 (durably marked). A new limit on that signal still
    # shows active in Supabase (TM/DB lag), but must NOT be re-placed.
    await sqlite_db.mark_signal_tp_fired(1)

    mock_mt5.account_info.return_value = make_account_info()
    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=7, signal_id=1)])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    mock_mt5.order_send.assert_not_called()
    assert 7 in cycle._logged_already_filled


async def test_tp_fired_signal_pending_sibling_cancelled(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # A still-pending sibling on a TP-fired signal (e.g. the TP engine's cancel failed)
    # is cancelled by the sync cycle's safety net, even though Supabase lists it active.
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=4001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )
    await sqlite_db.mark_signal_tp_fired(1)
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=4001)

    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=1, signal_id=1)])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 1
    mock_mt5.cancel_pending_order.assert_called_once_with(4001)
    assert len(await sqlite_db.get_pending_orders()) == 0


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
# Proximity gate uses the feed frame (not the broker frame) for offset symbols
# ---------------------------------------------------------------------------


async def test_proximity_uses_feed_mid_for_offset_symbol(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # SPX500USD limit at the feed price 4590.5; the feed mid is right on it (within the
    # 20-pt index proximity), but the BROKER mid is 4650.5 — 60 pts away. Comparing the
    # feed price to the broker mid (the old bug) would skip this as "outside proximity".
    # With the fix it passes proximity and proceeds to offset (which fails here, with no
    # mocked history → an error, not a proximity skip), proving the gate used the feed mid.
    mock_mt5.symbol_info.return_value = make_symbol_info(name="US500", digits=1, point=0.1)
    mock_mt5.symbol_info_tick.return_value = make_tick(
        bid=4650.0, ask=4651.0, time=int(datetime.now(UTC).timestamp())
    )
    mock_mt5.account_info.return_value = make_account_info()

    row = _make_supabase_row(limit_id=50, instrument="SPX500USD")
    row["stop_loss"] = 4585.0
    row["price_level"] = 4590.5
    supabase = _mock_supabase(
        signals=[row],
        live_prices={"SPX500USD": {"bid": 4590.0, "ask": 4591.0, "updated_at": datetime.now(UTC)}},
    )
    supabase.fetch_signal_status.return_value = "active"
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.skipped == 0  # not proximity-rejected
    assert result.errors == 1  # reached offset compute, which had no broker history
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
        live_prices={"SPX500USD": {"bid": 4590.0, "ask": 4591.0, "updated_at": datetime.now(UTC)}},
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


async def test_placement_skips_limit_past_current_price(sqlite_db, mock_mt5, sample_config) -> None:
    # New EURUSD long limit whose price is at/above current ask — would have to
    # be a buy_stop. Should be skipped, not placed as a stop.
    row = _make_supabase_row(limit_id=50, signal_id=5)
    row["price_level"] = 1.10001  # mid; adj_price = mid + spread > ask
    row["stop_loss"] = 1.09500
    mock_mt5.account_info.return_value = make_account_info()
    supabase = _mock_supabase(signals=[row])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    assert result.skipped == 1
    assert result.errors == 0
    mock_mt5.order_send.assert_not_called()


async def test_offset_drift_skipped_when_signal_marked_hit(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # Same setup as test_offset_drift_cancels_pending, but signal_status='hit'.
    # The remaining pending limit must NOT be cancelled — re-placing it at a
    # fresh offset would leave it inconsistent with the already-hit limit.
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
    mock_mt5.symbol_info.return_value = make_symbol_info(name="US500", digits=1, point=0.1)

    row = _make_supabase_row(limit_id=10, instrument="SPX500USD", signal_status="hit")
    row["stop_loss"] = 4000.0
    row["price_level"] = 4510.0
    supabase = _mock_supabase(
        signals=[row],
        live_prices={"SPX500USD": {"bid": 4590.0, "ask": 4591.0, "updated_at": datetime.now(UTC)}},
    )
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    cycle._offset_calc.get_offset = MagicMock(return_value=90.0)
    cycle._offset_calc.check_drift = MagicMock(return_value=True)

    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 0
    mock_mt5.cancel_pending_order.assert_not_called()

    rows = await sqlite_db.get_pending_orders()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Stale-pending sweep: hit limits are held, genuinely-gone limits are cancelled
# ---------------------------------------------------------------------------


async def test_stale_pending_kept_when_limit_marked_hit(sqlite_db, mock_mt5, sample_config) -> None:
    # The TM marked the limit 'hit', so it drops out of the pending Supabase
    # query — but it's still in hit_limit_ids (signal alive). Our pending order
    # must be held, not stale-cancelled: usually a sub-pip price mismatch.
    await sqlite_db.insert_order(
        limit_id=10,
        signal_id=1,
        mt5_ticket=3001,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
    )
    supabase = _mock_supabase(signals=[], hit_limit_ids={10})
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 0
    mock_mt5.cancel_pending_order.assert_not_called()
    rows = await sqlite_db.get_pending_orders()
    assert len(rows) == 1


async def test_stale_pending_cancelled_when_signal_gone(sqlite_db, mock_mt5, sample_config) -> None:
    # Limit is gone from Supabase and NOT in hit_limit_ids (signal cancelled /
    # closed) → the pending order is still stale-cancelled.
    await sqlite_db.insert_order(
        limit_id=10,
        signal_id=1,
        mt5_ticket=3001,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=3001)
    supabase = _mock_supabase(signals=[], hit_limit_ids=set())
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 1
    mock_mt5.cancel_pending_order.assert_called_once_with(3001)
    rows = await sqlite_db.get_pending_orders()
    assert len(rows) == 0


async def test_stale_pending_kept_when_signal_profit_marked_and_position_held(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # The TM marked the signal 'profit', so its still-pending limit drops out of
    # the active Supabase query. We still hold a filled position for the signal,
    # so the remaining pending limit is held until our own TP engine closes out.
    await sqlite_db.insert_order(
        limit_id=10,
        signal_id=1,
        mt5_ticket=3001,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
    )
    # A second limit on the same signal that already filled (open position).
    await sqlite_db.insert_order(
        limit_id=11,
        signal_id=1,
        mt5_ticket=3002,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
    )
    await sqlite_db.mark_filled(3002, "2026-01-01T00:01:00+00:00")

    supabase = _mock_supabase(signals=[], profit_limit_ids={10: 1})
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 0
    mock_mt5.cancel_pending_order.assert_not_called()
    rows = await sqlite_db.get_pending_orders()
    assert len(rows) == 1


async def test_stale_pending_cancelled_when_profit_signal_has_no_position(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # Signal is 'profit'-marked but we hold no filled position for it — our own TP
    # engine is not running on it, so the leftover pending limit is stale-cancelled.
    await sqlite_db.insert_order(
        limit_id=10,
        signal_id=1,
        mt5_ticket=3001,
        order_type="buy_limit",
        lot_size=0.01,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=4000.0,
        signal_type="standard",
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=3001)
    supabase = _mock_supabase(signals=[], profit_limit_ids={10: 1})
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
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


async def test_spread_hour_24h_stock_exempt_but_normal_stock_cancelled(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # 24h stocks carry the broker -24 suffix → exempt like crypto. A normal stock
    # (listed bare, in stock_no_suffix) is cancelled when the gate fires.
    sample_config.stock_no_suffix = ["AAPL.NAS"]  # AAPL listed bare → non-24h stock
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=5001,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=200.0,
        signal_type="standard",
        symbol="TSLA.NAS-24",
    )
    await sqlite_db.insert_order(
        limit_id=2,
        signal_id=2,
        mt5_ticket=5002,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=150.0,
        signal_type="standard",
        symbol="AAPL.NAS",
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=5002)

    tsla = _make_supabase_row(limit_id=1, signal_id=1, instrument="TSLA.NAS")
    tsla["stop_loss"] = 200.0  # match SQLite to avoid the SL-change cancel path
    aapl = _make_supabase_row(limit_id=2, signal_id=2, instrument="AAPL.NAS")
    aapl["stop_loss"] = 150.0
    supabase = _mock_supabase(signals=[tsla, aapl])
    scheduler = _mock_scheduler(cancel_pending=True)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 1
    mock_mt5.cancel_pending_order.assert_called_once_with(5002)
    pending = await sqlite_db.get_pending_orders()
    assert {r["mt5_ticket"] for r in pending} == {5001}


# ---------------------------------------------------------------------------
# Per-symbol news gate: cancel only pendings whose instrument is under news
# ---------------------------------------------------------------------------


async def test_news_cancels_only_matching_symbol(sqlite_db, mock_mt5, sample_config) -> None:
    # USD news active: EURUSD pending is cancelled, GBPAUD pending survives.
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=7001,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
        symbol="EURUSD",
    )
    await sqlite_db.insert_order(
        limit_id=2,
        signal_id=2,
        mt5_ticket=7002,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
        symbol="GBPAUD",
    )
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=7001)

    eur = _make_supabase_row(limit_id=1, signal_id=1, instrument="EURUSD")
    gbp = _make_supabase_row(limit_id=2, signal_id=2, instrument="GBPAUD")
    supabase = _mock_supabase(signals=[eur, gbp], news_mode="USD")
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 1
    mock_mt5.cancel_pending_order.assert_called_once_with(7001)
    pending = await sqlite_db.get_pending_orders()
    assert {r["mt5_ticket"] for r in pending} == {7002}


async def test_news_all_cancels_every_pending(sqlite_db, mock_mt5, sample_config) -> None:
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=7101,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
        symbol="EURUSD",
    )
    await sqlite_db.insert_order(
        limit_id=2,
        signal_id=2,
        mt5_ticket=7102,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
        symbol="GBPAUD",
    )
    mock_mt5.cancel_pending_order.side_effect = [
        make_order_result(ticket=7101),
        make_order_result(ticket=7102),
    ]

    eur = _make_supabase_row(limit_id=1, signal_id=1, instrument="EURUSD")
    gbp = _make_supabase_row(limit_id=2, signal_id=2, instrument="GBPAUD")
    supabase = _mock_supabase(signals=[eur, gbp], news_mode="ALL")
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 2
    pending = await sqlite_db.get_pending_orders()
    assert pending == []


async def test_news_crypto_pending_exempt(sqlite_db, mock_mt5, sample_config) -> None:
    # BTCUSDT pending survives even under ALL news (crypto is 24/7, exempt).
    await sqlite_db.insert_order(
        limit_id=1,
        signal_id=1,
        mt5_ticket=7201,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=60000.0,
        signal_type="standard",
        symbol="BTCUSD",
    )
    btc = _make_supabase_row(limit_id=1, signal_id=1, instrument="BTCUSDT")
    btc["stop_loss"] = 60000.0
    supabase = _mock_supabase(signals=[btc], news_mode="ALL")
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.cancelled == 0
    mock_mt5.cancel_pending_order.assert_not_called()
    pending = await sqlite_db.get_pending_orders()
    assert {r["mt5_ticket"] for r in pending} == {7201}


# ---------------------------------------------------------------------------
# News force-exit: close filled positions whose instrument is under news
# ---------------------------------------------------------------------------


async def _insert_filled(sqlite_db, *, mt5_ticket, signal_id, symbol, db_stop_loss=1.08500):
    await sqlite_db.insert_order(
        limit_id=mt5_ticket,
        signal_id=signal_id,
        mt5_ticket=mt5_ticket,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=db_stop_loss,
        signal_type="standard",
        symbol=symbol,
    )
    await sqlite_db.mark_filled(mt5_ticket, "2026-01-01T00:01:00+00:00")


async def test_news_force_exits_matching_filled_position(
    sqlite_db, mock_mt5, sample_config
) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=8001, signal_id=1, symbol="EURUSD")
    mock_mt5.positions_get.return_value = [make_position(ticket=8001, symbol="EURUSD")]
    mock_mt5.close_position.return_value = make_order_result(ticket=8001)

    supabase = _mock_supabase(signals=[], news_mode="USD")
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_called_once()
    assert mock_mt5.close_position.call_args.kwargs["comment"] == "force_news"
    assert await sqlite_db.get_filled_positions() == []


async def test_news_does_not_exit_unrelated_filled_position(
    sqlite_db, mock_mt5, sample_config
) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=8101, signal_id=1, symbol="GBPAUD")
    mock_mt5.positions_get.return_value = [make_position(ticket=8101, symbol="GBPAUD")]

    supabase = _mock_supabase(signals=[], news_mode="USD")
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_not_called()
    assert {r["mt5_ticket"] for r in await sqlite_db.get_filled_positions()} == {8101}


async def test_news_does_not_exit_crypto_position(sqlite_db, mock_mt5, sample_config) -> None:
    # Crypto stays live through news, mirroring the placement-gate exemption.
    sample_config.symbol_map = {"BTCUSDT": "BTCUSD"}  # reverse-maps for asset-class detection
    await _insert_filled(
        sqlite_db, mt5_ticket=8201, signal_id=1, symbol="BTCUSD", db_stop_loss=60000.0
    )
    mock_mt5.positions_get.return_value = [make_position(ticket=8201, symbol="BTCUSD")]

    supabase = _mock_supabase(signals=[], news_mode="ALL")
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_not_called()
    assert {r["mt5_ticket"] for r in await sqlite_db.get_filled_positions()} == {8201}


# ---------------------------------------------------------------------------
# Volatility guard: vol_guard tokens gate trades exactly like news, but only
# when the user has enabled the feature (config.volatility_guard).
# ---------------------------------------------------------------------------


async def test_vol_guard_gates_like_news_when_enabled(sqlite_db, mock_mt5, sample_config) -> None:
    sample_config.volatility_guard = True
    await _insert_filled(sqlite_db, mt5_ticket=8301, signal_id=1, symbol="EURUSD")
    mock_mt5.positions_get.return_value = [make_position(ticket=8301, symbol="EURUSD")]
    mock_mt5.close_position.return_value = make_order_result(ticket=8301)

    supabase = _mock_supabase(signals=[], news_mode=None, vol_guard="USD")
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_called_once()
    assert await sqlite_db.get_filled_positions() == []


async def test_vol_guard_ignored_when_disabled(sqlite_db, mock_mt5, sample_config) -> None:
    # Default off: the vol_guard column is read but never acted on.
    assert sample_config.volatility_guard is False
    await _insert_filled(sqlite_db, mt5_ticket=8401, signal_id=1, symbol="EURUSD")
    mock_mt5.positions_get.return_value = [make_position(ticket=8401, symbol="EURUSD")]

    supabase = _mock_supabase(signals=[], news_mode=None, vol_guard="ALL")
    scheduler = _mock_scheduler(cancel_pending=False)

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_not_called()
    assert {r["mt5_ticket"] for r in await sqlite_db.get_filled_positions()} == {8401}


# ---------------------------------------------------------------------------
# Profit-weekend force-exit: flatten profit-marked signals before the weekend
# ---------------------------------------------------------------------------


async def test_profit_marked_position_closed_in_weekend_window(
    sqlite_db, mock_mt5, sample_config
) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=9001, signal_id=1, symbol="USDCAD")
    mock_mt5.positions_get.return_value = [make_position(ticket=9001, symbol="USDCAD")]
    mock_mt5.close_position.return_value = make_order_result(ticket=9001)

    supabase = _mock_supabase(signals=[])
    supabase.fetch_signal_statuses.return_value = {1: {"status": "profit"}}
    scheduler = _mock_scheduler(cancel_pending=False)
    scheduler.is_weekend_window.return_value = True

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_called_once()
    assert mock_mt5.close_position.call_args.kwargs["comment"] == "force_profit_weekend"
    assert await sqlite_db.get_filled_positions() == []


async def test_profit_marked_position_kept_open_on_weekday(
    sqlite_db, mock_mt5, sample_config
) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=9101, signal_id=1, symbol="USDCAD")
    mock_mt5.positions_get.return_value = [make_position(ticket=9101, symbol="USDCAD")]

    supabase = _mock_supabase(signals=[])
    supabase.fetch_signal_statuses.return_value = {1: {"status": "profit"}}
    scheduler = _mock_scheduler(cancel_pending=False)
    scheduler.is_weekend_window.return_value = False

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_not_called()
    assert {r["mt5_ticket"] for r in await sqlite_db.get_filled_positions()} == {9101}


async def test_profit_marked_crypto_kept_open_in_weekend_window(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # Crypto trades 24/7 through the weekend, mirroring the gate exemptions.
    sample_config.symbol_map = {"BTCUSDT": "BTCUSD"}  # reverse-maps for asset-class detection
    await _insert_filled(
        sqlite_db, mt5_ticket=9201, signal_id=1, symbol="BTCUSD", db_stop_loss=60000.0
    )
    mock_mt5.positions_get.return_value = [make_position(ticket=9201, symbol="BTCUSD")]

    supabase = _mock_supabase(signals=[])
    supabase.fetch_signal_statuses.return_value = {1: {"status": "profit"}}
    scheduler = _mock_scheduler(cancel_pending=False)
    scheduler.is_weekend_window.return_value = True

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_not_called()
    assert {r["mt5_ticket"] for r in await sqlite_db.get_filled_positions()} == {9201}


# ---------------------------------------------------------------------------
# Manual profit force-exit: a TM-marked manual 'profit' closes immediately
# (like breakeven), while an auto-TP 'profit' stays open for our TP engine.
# ---------------------------------------------------------------------------


async def test_manual_profit_position_closed_on_weekday(sqlite_db, mock_mt5, sample_config) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=9301, signal_id=1, symbol="USDCAD")
    mock_mt5.positions_get.return_value = [make_position(ticket=9301, symbol="USDCAD")]
    mock_mt5.close_position.return_value = make_order_result(ticket=9301)

    supabase = _mock_supabase(signals=[])
    supabase.fetch_signal_statuses.return_value = {
        1: {"status": "profit", "closed_reason": "manual"}
    }
    scheduler = _mock_scheduler(cancel_pending=False)
    scheduler.is_weekend_window.return_value = False

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_called_once()
    assert mock_mt5.close_position.call_args.kwargs["comment"] == "force_profit"
    assert await sqlite_db.get_filled_positions() == []


async def test_auto_tp_profit_position_kept_open_on_weekday(
    sqlite_db, mock_mt5, sample_config
) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=9401, signal_id=1, symbol="USDCAD")
    mock_mt5.positions_get.return_value = [make_position(ticket=9401, symbol="USDCAD")]

    supabase = _mock_supabase(signals=[])
    supabase.fetch_signal_statuses.return_value = {
        1: {"status": "profit", "closed_reason": "automatic"}
    }
    scheduler = _mock_scheduler(cancel_pending=False)
    scheduler.is_weekend_window.return_value = False

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.close_position.assert_not_called()
    assert {r["mt5_ticket"] for r in await sqlite_db.get_filled_positions()} == {9401}


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
        live_prices={"SPX500USD": {"bid": 4590.0, "ask": 4591.0, "updated_at": datetime.now(UTC)}},
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
        live_prices={"SPX500USD": {"bid": 4590.0, "ask": 4591.0, "updated_at": datetime.now(UTC)}},
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


# ---------------------------------------------------------------------------
# Multi-broker symbol availability: catalogue-based skip + symbol_select
# ---------------------------------------------------------------------------


async def test_unmapped_symbol_skipped_and_logged_once(sqlite_db, mock_mt5, sample_config) -> None:
    # GCQ26 isn't in the broker catalogue → skip cleanly, no order, no select call,
    # and the skip is logged exactly once across cycles.
    mock_mt5.symbols_get.return_value = frozenset({"EURUSD", "US500"})

    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=70, instrument="GCQ26")])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    r1 = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)
    r2 = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert r1.placed == 0 and r2.placed == 0
    mock_mt5.order_send.assert_not_called()
    assert "GCQ26" in cycle._logged_unmapped
    # Never selected (it doesn't exist on the broker)
    for call in mock_mt5.symbol_select.call_args_list:
        assert call.args[0] != "GCQ26"


async def test_catalogued_symbol_is_selected(sqlite_db, mock_mt5, sample_config) -> None:
    # EURUSD is in the catalogue → it gets selected into MarketWatch before use.
    mock_mt5.symbols_get.return_value = frozenset({"EURUSD"})

    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=71, instrument="EURUSD")])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.symbol_select.assert_any_call("EURUSD")
    assert "EURUSD" not in cycle._logged_unmapped


# ---------------------------------------------------------------------------
# Spread-hour SL strip / restore
# ---------------------------------------------------------------------------


def _strip_scheduler(in_window: bool) -> MagicMock:
    sched = MagicMock()
    sched.is_sl_strip_window.return_value = in_window
    return sched


async def test_sl_strip_removes_sl_in_window(sqlite_db, mock_mt5, sample_config) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=3001, signal_id=1, symbol="EURUSD")
    pos = make_position(ticket=3001, sl=1.08500)
    mock_mt5.modify_position_sl.return_value = make_order_result(ticket=3001)

    cycle = SyncCycle()
    await cycle._manage_spread_hour_sls(
        sqlite_db, mock_mt5, [pos], _strip_scheduler(True), sample_config, set()
    )

    mock_mt5.modify_position_sl.assert_called_once_with(3001, "EURUSD", 0.0)
    row = await sqlite_db.get_order_by_ticket(3001)
    assert row["sl_stripped"] == 1
    assert row["last_known_mt5_sl"] == 1.08500  # pre-strip SL persisted for restore


async def test_sl_strip_exempts_crypto(sqlite_db, mock_mt5, sample_config) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=3002, signal_id=1, symbol="BTCUSD")
    pos = make_position(ticket=3002, symbol="BTCUSD", sl=60000.0)

    cycle = SyncCycle()
    await cycle._manage_spread_hour_sls(
        sqlite_db, mock_mt5, [pos], _strip_scheduler(True), sample_config, set()
    )

    mock_mt5.modify_position_sl.assert_not_called()
    row = await sqlite_db.get_order_by_ticket(3002)
    assert row["sl_stripped"] == 0


async def test_sl_strip_idempotent_when_already_stripped(
    sqlite_db, mock_mt5, sample_config
) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=3005, signal_id=1, symbol="EURUSD")
    await sqlite_db.set_sl_stripped(3005, 1)
    pos = make_position(ticket=3005, sl=0.0)

    cycle = SyncCycle()
    await cycle._manage_spread_hour_sls(
        sqlite_db, mock_mt5, [pos], _strip_scheduler(True), sample_config, set()
    )

    mock_mt5.modify_position_sl.assert_not_called()


async def test_sl_restore_resets_sl_after_window(sqlite_db, mock_mt5, sample_config) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=3003, signal_id=1, symbol="EURUSD")
    await sqlite_db.update_sl(3003, 1.08500)  # pre-strip SL in last_known_mt5_sl
    await sqlite_db.set_sl_stripped(3003, 1)
    pos = make_position(ticket=3003, sl=0.0)
    mock_mt5.symbol_info_tick.return_value = make_tick(bid=1.10000, ask=1.10002)
    mock_mt5.modify_position_sl.return_value = make_order_result(ticket=3003)

    cycle = SyncCycle()
    await cycle._manage_spread_hour_sls(
        sqlite_db, mock_mt5, [pos], _strip_scheduler(False), sample_config, set()
    )

    mock_mt5.modify_position_sl.assert_called_once_with(3003, "EURUSD", 1.08500)
    mock_mt5.close_position.assert_not_called()
    row = await sqlite_db.get_order_by_ticket(3003)
    assert row["sl_stripped"] == 0


async def test_sl_restore_closes_when_price_past_stop(sqlite_db, mock_mt5, sample_config) -> None:
    await _insert_filled(sqlite_db, mt5_ticket=3004, signal_id=1, symbol="EURUSD")
    await sqlite_db.update_sl(3004, 1.08500)
    await sqlite_db.set_sl_stripped(3004, 1)
    pos = make_position(ticket=3004, sl=0.0, profit=-50.0)
    # bid below the stored stop → price moved past it while unprotected
    mock_mt5.symbol_info_tick.return_value = make_tick(bid=1.08000, ask=1.08002)
    mock_mt5.close_position.return_value = make_order_result(ticket=3004)

    cycle = SyncCycle()
    await cycle._manage_spread_hour_sls(
        sqlite_db, mock_mt5, [pos], _strip_scheduler(False), sample_config, set()
    )

    mock_mt5.close_position.assert_called_once()
    mock_mt5.modify_position_sl.assert_not_called()
    row = await sqlite_db.get_order_by_ticket(3004)
    assert row["status"] == "closed"


# ---------------------------------------------------------------------------
# Per-signal user overrides: skip (pull + never place) and manual (orphan)
# ---------------------------------------------------------------------------


async def test_skip_cancels_pending_and_closes_fills(sqlite_db, mock_mt5, sample_config) -> None:
    # Skipped signal with one pending order and one filled position: pull both.
    await sqlite_db.insert_order(
        limit_id=5001,
        signal_id=1,
        mt5_ticket=5001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
        symbol="EURUSD",
    )
    await _insert_filled(sqlite_db, mt5_ticket=5002, signal_id=1, symbol="EURUSD")
    await sqlite_db.set_signal_action(1, "skip")

    mock_mt5.orders_get.return_value = [make_order_info(ticket=5001)]
    mock_mt5.positions_get.return_value = [make_position(ticket=5002, symbol="EURUSD")]
    mock_mt5.cancel_pending_order.return_value = make_order_result(ticket=5001)
    mock_mt5.close_position.return_value = make_order_result(ticket=5002)

    supabase = _mock_supabase(signals=[])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.cancel_pending_order.assert_called_once_with(5001)
    mock_mt5.close_position.assert_called_once()
    assert mock_mt5.close_position.call_args.kwargs["comment"] == "skip"
    assert await sqlite_db.get_pending_orders() == []
    assert await sqlite_db.get_filled_positions() == []


async def test_skip_blocks_new_placement(sqlite_db, mock_mt5, sample_config) -> None:
    # A live signal the user skipped must never place, even with a fresh limit.
    await sqlite_db.set_signal_action(1, "skip")

    supabase = _mock_supabase(signals=[_make_supabase_row(limit_id=1, signal_id=1)])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    mock_mt5.order_send.assert_not_called()
    assert await sqlite_db.get_pending_orders() == []


async def test_manual_orphans_pending_and_skips_management(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # Manually-handled signal: pending stays put, fills are not force-exited even
    # under news that would otherwise close the position.
    await sqlite_db.insert_order(
        limit_id=6001,
        signal_id=1,
        mt5_ticket=6001,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
        symbol="EURUSD",
    )
    await _insert_filled(sqlite_db, mt5_ticket=6002, signal_id=1, symbol="EURUSD")
    await sqlite_db.set_signal_action(1, "manual")

    mock_mt5.orders_get.return_value = [make_order_info(ticket=6001)]
    mock_mt5.positions_get.return_value = [make_position(ticket=6002, symbol="EURUSD")]

    supabase = _mock_supabase(signals=[], news_mode="USD")
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    mock_mt5.cancel_pending_order.assert_not_called()
    mock_mt5.close_position.assert_not_called()
    assert {r["mt5_ticket"] for r in await sqlite_db.get_pending_orders()} == {6001}
    assert {r["mt5_ticket"] for r in await sqlite_db.get_filled_positions()} == {6002}


async def test_clear_signal_action_resumes_management(sqlite_db) -> None:
    await sqlite_db.set_signal_action(1, "manual")
    assert await sqlite_db.get_signal_actions() == {1: "manual"}
    await sqlite_db.clear_signal_action(1)
    assert await sqlite_db.get_signal_actions() == {}


# ---------------------------------------------------------------------------
# Channel + asset-class exclusions: drop signals before placement
# ---------------------------------------------------------------------------


async def test_excluded_channel_asset_blocks_placement(sqlite_db, mock_mt5, sample_config) -> None:
    # Exclude forex signals from channel 123 → a EURUSD limit on that channel never places.
    sample_config.excluded_channel_assets = [
        ExcludedChannelAssetConfig(channel="123", asset_class="forex")
    ]
    mock_mt5.account_info.return_value = make_account_info()
    row = _make_supabase_row(limit_id=1, instrument="EURUSD")
    row["channel_id"] = 123
    row["price_level"] = 1.09950
    supabase = _mock_supabase(signals=[row])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    mock_mt5.order_send.assert_not_called()
    assert 1 in cycle._logged_excluded


async def test_excluded_channel_asset_ignores_other_asset(
    sqlite_db, mock_mt5, sample_config
) -> None:
    # The same channel rule targets indices; a forex EURUSD limit is unaffected and places.
    sample_config.excluded_channel_assets = [
        ExcludedChannelAssetConfig(channel="123", asset_class="indices")
    ]
    mock_mt5.account_info.return_value = make_account_info()
    mock_mt5.order_send.return_value = make_order_result(ticket=2002)
    mock_mt5.order_get_by_ticket.return_value = None
    row = _make_supabase_row(limit_id=1, instrument="EURUSD")
    row["channel_id"] = 123
    row["price_level"] = 1.09950
    supabase = _mock_supabase(signals=[row])
    supabase.fetch_signal_status.return_value = "active"
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 1
    mock_mt5.order_send.assert_called_once()


async def test_excluded_asset_wildcard_channel(sqlite_db, mock_mt5, sample_config) -> None:
    # Channel left as "all": every forex signal is excluded regardless of channel.
    sample_config.excluded_channel_assets = [ExcludedChannelAssetConfig(asset_class="forex")]
    mock_mt5.account_info.return_value = make_account_info()
    row = _make_supabase_row(limit_id=1, instrument="EURUSD")
    row["channel_id"] = 999
    row["price_level"] = 1.09950
    supabase = _mock_supabase(signals=[row])
    scheduler = _mock_scheduler()

    cycle = SyncCycle()
    result = await cycle.run(supabase, sqlite_db, mock_mt5, sample_config, scheduler)

    assert result.placed == 0
    mock_mt5.order_send.assert_not_called()
