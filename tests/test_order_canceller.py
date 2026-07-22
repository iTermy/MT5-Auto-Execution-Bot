import MetaTrader5 as mt5

from bot.trading.order_canceller import OrderCanceller
from tests.conftest import make_order_info, make_order_result, make_position


async def _insert_pending(sqlite_db, ticket: int) -> None:
    await sqlite_db.insert_order(
        limit_id=ticket,
        signal_id=1,
        mt5_ticket=ticket,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )


async def _is_pending(sqlite_db, ticket: int) -> bool:
    rows = await sqlite_db.get_pending_orders()
    return any(r["mt5_ticket"] == ticket for r in rows)


async def test_successful_cancel_marks_cancelled(sqlite_db, mock_mt5) -> None:
    await _insert_pending(sqlite_db, ticket=1001)
    mock_mt5.cancel_pending_order.return_value = make_order_result(
        retcode=mt5.TRADE_RETCODE_DONE, ticket=1001
    )

    ok = await OrderCanceller().cancel_order(1001, mock_mt5, sqlite_db)

    assert ok is True
    assert not await _is_pending(sqlite_db, 1001)


async def test_invalid_but_order_gone_resolves_as_cancelled(sqlite_db, mock_mt5) -> None:
    # retcode 10013 while the order is absent from both books → stale pending row,
    # resolve immediately instead of retrying until the periodic reconcile.
    await _insert_pending(sqlite_db, ticket=1001)
    mock_mt5.cancel_pending_order.return_value = make_order_result(
        retcode=mt5.TRADE_RETCODE_INVALID, ticket=1001
    )
    mock_mt5.orders_get.return_value = []
    mock_mt5.positions_get.return_value = []

    ok = await OrderCanceller().cancel_order(1001, mock_mt5, sqlite_db)

    assert ok is True
    assert not await _is_pending(sqlite_db, 1001)


async def test_invalid_but_order_still_pending_is_a_failure(sqlite_db, mock_mt5) -> None:
    # Genuine cancel failure: the order is still a live pending order. Retry next cycle.
    await _insert_pending(sqlite_db, ticket=1001)
    mock_mt5.cancel_pending_order.return_value = make_order_result(
        retcode=mt5.TRADE_RETCODE_INVALID, ticket=1001
    )
    mock_mt5.orders_get.return_value = [make_order_info(ticket=1001)]

    ok = await OrderCanceller().cancel_order(1001, mock_mt5, sqlite_db)

    assert ok is False
    assert await _is_pending(sqlite_db, 1001)


async def test_invalid_but_order_filled_not_marked_cancelled(sqlite_db, mock_mt5) -> None:
    # The order left the pending book because it filled — never record a live
    # position as cancelled; leave it for fill detection / reconcile.
    await _insert_pending(sqlite_db, ticket=1001)
    mock_mt5.cancel_pending_order.return_value = make_order_result(
        retcode=mt5.TRADE_RETCODE_INVALID, ticket=1001
    )
    mock_mt5.orders_get.return_value = []
    mock_mt5.positions_get.return_value = [make_position(ticket=2001, identifier=1001)]

    ok = await OrderCanceller().cancel_order(1001, mock_mt5, sqlite_db)

    assert ok is False
    assert await _is_pending(sqlite_db, 1001)


async def test_market_closed_defers_without_resolving(sqlite_db, mock_mt5) -> None:
    await _insert_pending(sqlite_db, ticket=1001)
    mock_mt5.cancel_pending_order.return_value = make_order_result(
        retcode=mt5.TRADE_RETCODE_MARKET_CLOSED, ticket=1001
    )
    # Even though the books are empty, a closed market must not resolve the row.
    mock_mt5.orders_get.return_value = []
    mock_mt5.positions_get.return_value = []

    ok = await OrderCanceller().cancel_order(1001, mock_mt5, sqlite_db)

    assert ok is False
    assert await _is_pending(sqlite_db, 1001)
