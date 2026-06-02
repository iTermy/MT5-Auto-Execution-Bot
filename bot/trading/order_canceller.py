import logging
from datetime import UTC, datetime

import MetaTrader5 as mt5

from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client

logger = logging.getLogger(__name__)


class OrderCanceller:
    async def cancel_order(
        self,
        mt5_ticket: int,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
        spread: bool = False,
    ) -> bool:
        result = mt5_client.cancel_pending_order(mt5_ticket)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else "None"
            logger.error("Cancel failed: ticket=%d retcode=%s", mt5_ticket, retcode)
            return False

        cancelled_at = datetime.now(UTC).isoformat()
        await sqlite.mark_cancelled(mt5_ticket, cancelled_at, spread=spread)
        label = "spread_cancelled" if spread else "cancelled"
        logger.info("Order %s: ticket=%d", label, mt5_ticket)
        return True
