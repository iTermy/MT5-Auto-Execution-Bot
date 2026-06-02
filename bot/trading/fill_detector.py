import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite

from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client
from bot.mt5.types import OrderInfo, PositionInfo

logger = logging.getLogger(__name__)


@dataclass
class FillEvent:
    mt5_ticket: int  # original order ticket stored in SQLite
    position_ticket: int  # actual MT5 position ticket (may differ in hedging mode)
    filled_at: str  # ISO UTC timestamp


@dataclass
class NewTicketEvent:
    original_ticket: int  # SQLite row being replaced
    new_ticket: int  # new position ticket from partial close
    signal_id: int
    signal_type: str


class FillDetector:
    def detect_fills(
        self,
        mt5_orders: list[OrderInfo],
        mt5_positions: list[PositionInfo],
        pending_rows: list[aiosqlite.Row],
    ) -> list[FillEvent]:
        active_order_tickets = {o.ticket for o in mt5_orders}
        # In MT5 hedging mode, position.identifier == the originating order ticket
        position_by_identifier = {p.identifier: p for p in mt5_positions}

        fills: list[FillEvent] = []
        filled_at = datetime.now(UTC).isoformat()

        for row in pending_rows:
            ticket = row["mt5_ticket"]
            if ticket in active_order_tickets:
                continue  # Still pending
            pos = position_by_identifier.get(ticket)
            if pos is None:
                continue  # Gone from MT5 entirely — reconciler handles this
            fills.append(
                FillEvent(
                    mt5_ticket=ticket,
                    position_ticket=pos.ticket,
                    filled_at=filled_at,
                )
            )

        return fills

    async def detect_partial_close_tickets(
        self,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
        positions: list[PositionInfo] | None = None,
    ) -> list[NewTicketEvent]:
        trailing_rows = await sqlite.get_trailing_positions()
        all_active = await sqlite.get_all_active()
        known_tickets = {row["mt5_ticket"] for row in all_active}

        if positions is None:
            positions = mt5_client.positions_get()
        active_tickets = {p.ticket for p in positions}

        results: list[NewTicketEvent] = []
        for row in trailing_rows:
            original_ticket = row["mt5_ticket"]
            if original_ticket in active_tickets:
                continue  # Position still open, no partial close yet

            # Original position is gone — find the new remainder position
            signal_id = row["signal_id"]
            expected_comment = f"s{signal_id}"
            for pos in positions:
                if pos.comment == expected_comment and pos.ticket not in known_tickets:
                    results.append(
                        NewTicketEvent(
                            original_ticket=original_ticket,
                            new_ticket=pos.ticket,
                            signal_id=signal_id,
                            signal_type=row["signal_type"],
                        )
                    )
                    logger.info(
                        "Partial close detected: signal=%d old_ticket=%d new_ticket=%d",
                        signal_id,
                        original_ticket,
                        pos.ticket,
                    )
                    break

        return results
