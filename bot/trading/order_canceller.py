import logging
import time
from datetime import UTC, datetime

import MetaTrader5 as mt5

from bot.db.sqlite import SQLiteDB
from bot.mt5.client import MT5Client

logger = logging.getLogger(__name__)

# Throttle repeated "market closed" notices so leftover orders on a closed session
# (e.g. weekend) don't spam the log every sync cycle. Per-ticket, monotonic seconds.
_MARKET_CLOSED_LOG_INTERVAL = 300.0


class OrderCanceller:
    def __init__(self) -> None:
        self._market_closed_log_ts: dict[int, float] = {}

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
            if result is not None and result.retcode == mt5.TRADE_RETCODE_MARKET_CLOSED:
                # Can't cancel while the market is closed; it clears when the session
                # reopens. Expected and self-resolving — log at most once per interval.
                now = time.monotonic()
                if (
                    now - self._market_closed_log_ts.get(mt5_ticket, 0.0)
                    >= _MARKET_CLOSED_LOG_INTERVAL
                ):
                    self._market_closed_log_ts[mt5_ticket] = now
                    logger.warning("Cancel deferred (market closed): ticket=%d", mt5_ticket)
            else:
                logger.error("Cancel failed: ticket=%d retcode=%s", mt5_ticket, retcode)
            return False

        cancelled_at = datetime.now(UTC).isoformat()
        await sqlite.mark_cancelled(mt5_ticket, cancelled_at, spread=spread)
        self._market_closed_log_ts.pop(mt5_ticket, None)
        label = "spread_cancelled" if spread else "cancelled"
        logger.info("Order %s: ticket=%d", label, mt5_ticket)
        return True
