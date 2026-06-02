import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import MetaTrader5 as mt5

from bot.config.constants import MAGIC_NUMBER
from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client

logger = logging.getLogger(__name__)


def _parse_comment(comment: str) -> tuple[int, int] | None:
    """Parse 's{signal_id}_l{limit_id}' → (signal_id, limit_id) or None."""
    try:
        if not comment or not comment.startswith("s") or "_l" not in comment:
            return None
        parts = comment.split("_l", 1)
        if len(parts) != 2:
            return None
        return int(parts[0][1:]), int(parts[1])
    except (ValueError, IndexError):
        return None


@dataclass
class ReconciliationResult:
    filled: int = 0
    cancelled: int = 0
    closed: int = 0
    trailing_resumed: int = 0
    orphans: int = 0


class Reconciler:
    async def reconcile(self, mt5_client: MT5Client, sqlite: SQLiteDB) -> ReconciliationResult:
        result = ReconciliationResult()

        mt5_orders = mt5_client.orders_get()
        mt5_positions = mt5_client.positions_get()

        mt5_order_tickets = {o.ticket for o in mt5_orders}
        # In hedging mode, position.identifier == originating order ticket
        position_by_identifier = {p.identifier: p for p in mt5_positions}
        position_by_ticket = {p.ticket: p for p in mt5_positions}

        pending_rows = await sqlite.get_pending_orders()
        filled_rows = await sqlite.get_filled_positions()

        now_iso = datetime.now(UTC).isoformat()

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

        result.orphans = await self.reconcile_orphans(mt5_client, sqlite, mt5_orders=mt5_orders)

        logger.info(
            "Reconciliation: filled=%d cancelled=%d closed=%d trailing=%d orphans=%d",
            result.filled,
            result.cancelled,
            result.closed,
            result.trailing_resumed,
            result.orphans,
        )
        return result

    async def reconcile_orphans(
        self,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
        mt5_orders: list | None = None,
    ) -> int:
        """
        Orphan sweep (C2): re-link claimed rows whose order_send completed but
        the SQLite commit was lost, and cancel truly untracked orders.
        Also cleans stale claimed rows that have no corresponding MT5 order.
        """
        if mt5_orders is None:
            mt5_orders = mt5_client.orders_get()

        pending_rows = await sqlite.get_pending_orders()
        claimed_rows = await sqlite.get_claimed_orders()

        sqlite_pending_tickets = {r["mt5_ticket"] for r in pending_rows}

        count = 0

        # Clean up stale claim rows that have no matching MT5 order (order_send
        # never ran or failed, then the bot crashed before delete_claimed_order).
        for row in claimed_rows:
            matched = any(
                _parse_comment(o.comment) == (row["signal_id"], row["limit_id"]) for o in mt5_orders
            )
            if not matched:
                await sqlite.delete_claimed_order(row["limit_id"])
                logger.info(
                    "Stale claim removed: limit=%d signal=%d",
                    row["limit_id"],
                    row["signal_id"],
                )
                count += 1

        # Re-link or cancel MT5 orders with our magic number not in SQLite pending.
        for order in mt5_orders:
            if order.magic != MAGIC_NUMBER:
                continue
            if order.ticket in sqlite_pending_tickets:
                continue

            parsed = _parse_comment(order.comment)
            if parsed:
                sig_id, lim_id = parsed
                claimed = await sqlite.get_claimed_by_signal_limit(sig_id, lim_id)
                if claimed:
                    # C2 crash-recovery: promote the claim to pending with the real ticket
                    await sqlite.promote_claimed_to_pending(lim_id, order.ticket)
                    logger.info(
                        "Orphan re-linked: ticket=%d signal=%d limit=%d",
                        order.ticket,
                        sig_id,
                        lim_id,
                    )
                    count += 1
                    continue

            # Re-check SQLite right before cancelling — order_canceller may have
            # already cancelled this ticket in the same cycle, in which case the
            # snapshot above is stale and the cancel would noisily fail.
            fresh = await sqlite.get_order_by_ticket(order.ticket)
            if fresh and fresh["status"] in ("cancelled", "spread_cancelled", "filled", "closed"):
                continue

            res = mt5_client.cancel_pending_order(order.ticket)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info("Orphan cancelled: ticket=%d symbol=%s", order.ticket, order.symbol)
            else:
                retcode = res.retcode if res else "None"
                logger.warning(
                    "Orphan cancel failed: ticket=%d symbol=%s comment=%s retcode=%s",
                    order.ticket,
                    order.symbol,
                    order.comment,
                    retcode,
                )
            count += 1

        return count
