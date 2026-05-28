import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    filled: int = 0
    cancelled: int = 0
    closed: int = 0
    trailing_resumed: int = 0
    orphans: int = 0


class Reconciler:
    async def reconcile(
        self, mt5_client: MT5Client, sqlite: SQLiteDB
    ) -> ReconciliationResult:
        result = ReconciliationResult()

        mt5_orders = mt5_client.orders_get()
        mt5_positions = mt5_client.positions_get()

        mt5_order_tickets = {o.ticket for o in mt5_orders}
        # In hedging mode, position.identifier == originating order ticket
        position_by_identifier = {p.identifier: p for p in mt5_positions}
        position_by_ticket = {p.ticket: p for p in mt5_positions}

        pending_rows = await sqlite.get_pending_orders()
        filled_rows = await sqlite.get_filled_positions()
        sqlite_tickets = {r["mt5_ticket"] for r in pending_rows} | {r["mt5_ticket"] for r in filled_rows}

        now_iso = datetime.now(timezone.utc).isoformat()

        for row in pending_rows:
            ticket = row["mt5_ticket"]
            if ticket in mt5_order_tickets:
                # Case 1: still a pending MT5 order — no change needed
                pass
            elif ticket in position_by_identifier:
                # Case 2: order filled, position exists (identifier == order ticket)
                pos = position_by_identifier[ticket]
                await sqlite.mark_filled(ticket, now_iso)
                if pos.ticket != ticket:
                    await sqlite.update_ticket(ticket, pos.ticket)
                result.filled += 1
                logger.info("Reconcile filled: order=%d pos=%d", ticket, pos.ticket)
            else:
                # Case 3: gone from MT5 entirely — treat as cancelled
                await sqlite.mark_cancelled(ticket, now_iso, spread=False)
                result.cancelled += 1
                logger.info("Reconcile cancelled: ticket=%d", ticket)

        for row in filled_rows:
            ticket = row["mt5_ticket"]
            if ticket not in position_by_ticket:
                # Case 4: position gone from MT5 — mark closed
                await sqlite.mark_closed(ticket)
                result.closed += 1
                logger.info("Reconcile closed: ticket=%d", ticket)
            elif row["is_trailing"]:
                # Case 5: trailing position still alive — resume trailing
                result.trailing_resumed += 1
                logger.info("Reconcile trailing resumed: ticket=%d", ticket)

        # Orphan check: MT5 orders with our magic number not tracked in SQLite
        for order in mt5_orders:
            if order.ticket not in sqlite_tickets:
                logger.warning(
                    "Reconcile orphan: ticket=%d symbol=%s comment=%s",
                    order.ticket, order.symbol, order.comment,
                )
                result.orphans += 1

        logger.info(
            "Reconciliation: filled=%d cancelled=%d closed=%d trailing=%d orphans=%d",
            result.filled, result.cancelled, result.closed,
            result.trailing_resumed, result.orphans,
        )
        return result
