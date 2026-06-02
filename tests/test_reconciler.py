from bot.core.reconciler import Reconciler
from tests.conftest import make_order_info, make_position


async def _insert_pending(sqlite_db, ticket: int, limit_id: int = None, signal_id: int = 1) -> None:
    await sqlite_db.insert_order(
        limit_id=limit_id or ticket,
        signal_id=signal_id,
        mt5_ticket=ticket,
        order_type="buy_limit",
        lot_size=0.1,
        placed_at="2026-01-01T00:00:00+00:00",
        db_stop_loss=1.08500,
        signal_type="standard",
    )


async def _insert_filled(
    sqlite_db, ticket: int, limit_id: int = None, trailing: bool = False
) -> None:
    await _insert_pending(sqlite_db, ticket, limit_id)
    await sqlite_db.mark_filled(ticket, "2026-01-01T00:01:00+00:00")
    if trailing:
        await sqlite_db.set_trailing(ticket)


# ---------------------------------------------------------------------------
# Case 1: pending + in MT5 orders → no state change
# ---------------------------------------------------------------------------


async def test_pending_in_mt5_orders_no_change(sqlite_db, mock_mt5) -> None:
    await _insert_pending(sqlite_db, ticket=1001)
    mock_mt5.orders_get.return_value = [make_order_info(ticket=1001)]
    mock_mt5.positions_get.return_value = []

    result = await Reconciler().reconcile(mock_mt5, sqlite_db)

    assert result.filled == 0
    assert result.cancelled == 0
    rows = await sqlite_db.get_pending_orders()
    assert any(r["mt5_ticket"] == 1001 for r in rows)


# ---------------------------------------------------------------------------
# Case 2: pending + filled position exists → mark_filled (update_ticket if needed)
# ---------------------------------------------------------------------------


async def test_pending_found_as_position_marks_filled(sqlite_db, mock_mt5) -> None:
    await _insert_pending(sqlite_db, ticket=1001)
    # In hedging mode: position.identifier == order ticket, position.ticket may differ
    pos = make_position(ticket=2001, identifier=1001)
    mock_mt5.orders_get.return_value = []
    mock_mt5.positions_get.return_value = [pos]

    result = await Reconciler().reconcile(mock_mt5, sqlite_db)

    assert result.filled == 1
    filled = await sqlite_db.get_filled_positions()
    assert len(filled) == 1
    # Ticket should have been updated to position ticket (2001)
    assert filled[0]["mt5_ticket"] == 2001


async def test_pending_filled_same_ticket_no_update_ticket(sqlite_db, mock_mt5) -> None:
    # When position.ticket == position.identifier, no update_ticket call needed
    await _insert_pending(sqlite_db, ticket=1001)
    pos = make_position(ticket=1001, identifier=1001)
    mock_mt5.orders_get.return_value = []
    mock_mt5.positions_get.return_value = [pos]

    result = await Reconciler().reconcile(mock_mt5, sqlite_db)

    assert result.filled == 1
    filled = await sqlite_db.get_filled_positions()
    assert filled[0]["mt5_ticket"] == 1001


# ---------------------------------------------------------------------------
# Case 3: pending + gone from MT5 → mark_cancelled
# ---------------------------------------------------------------------------


async def test_pending_gone_from_mt5_marks_cancelled(sqlite_db, mock_mt5) -> None:
    await _insert_pending(sqlite_db, ticket=1001)
    mock_mt5.orders_get.return_value = []
    mock_mt5.positions_get.return_value = []

    result = await Reconciler().reconcile(mock_mt5, sqlite_db)

    assert result.cancelled == 1
    pending = await sqlite_db.get_pending_orders()
    assert len(pending) == 0


# ---------------------------------------------------------------------------
# Case 4: filled + gone from MT5 → mark_closed
# ---------------------------------------------------------------------------


async def test_filled_gone_from_mt5_marks_closed(sqlite_db, mock_mt5) -> None:
    await _insert_filled(sqlite_db, ticket=1001)
    mock_mt5.orders_get.return_value = []
    mock_mt5.positions_get.return_value = []  # position disappeared

    result = await Reconciler().reconcile(mock_mt5, sqlite_db)

    assert result.closed == 1
    # Closed rows excluded from get_filled_positions
    filled = await sqlite_db.get_filled_positions()
    assert len(filled) == 0


# ---------------------------------------------------------------------------
# Case 5: filled + is_trailing=1 + still in MT5 → resume trailing (counted only)
# ---------------------------------------------------------------------------


async def test_filled_trailing_in_mt5_resumes(sqlite_db, mock_mt5) -> None:
    await _insert_filled(sqlite_db, ticket=1001, trailing=True)
    pos = make_position(ticket=1001)
    mock_mt5.orders_get.return_value = []
    mock_mt5.positions_get.return_value = [pos]

    result = await Reconciler().reconcile(mock_mt5, sqlite_db)

    assert result.trailing_resumed == 1
    assert result.closed == 0


# ---------------------------------------------------------------------------
# Orphan: MT5 order not in SQLite → cancel and count
# ---------------------------------------------------------------------------


async def test_orphan_mt5_order_not_in_sqlite(sqlite_db, mock_mt5) -> None:
    # Order exists in MT5 but is not in SQLite
    mock_mt5.orders_get.return_value = [make_order_info(ticket=9999)]
    mock_mt5.positions_get.return_value = []

    result = await Reconciler().reconcile(mock_mt5, sqlite_db)

    assert result.orphans == 1
    mock_mt5.cancel_pending_order.assert_called_once_with(9999)


# ---------------------------------------------------------------------------
# Multiple cases in one reconciliation run
# ---------------------------------------------------------------------------


async def test_mixed_reconciliation(sqlite_db, mock_mt5) -> None:
    # Case 1: ticket=1001 — still pending in MT5
    await _insert_pending(sqlite_db, ticket=1001, limit_id=101)
    # Case 3: ticket=1002 — gone from MT5
    await _insert_pending(sqlite_db, ticket=1002, limit_id=102)
    # Case 4: ticket=1003 — filled but position gone
    await _insert_filled(sqlite_db, ticket=1003, limit_id=103)

    mock_mt5.orders_get.return_value = [make_order_info(ticket=1001)]
    mock_mt5.positions_get.return_value = []

    result = await Reconciler().reconcile(mock_mt5, sqlite_db)

    assert result.cancelled == 1  # ticket 1002
    assert result.closed == 1  # ticket 1003
    assert result.filled == 0
    assert result.orphans == 0
