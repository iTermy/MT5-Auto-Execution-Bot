import logging
from datetime import datetime, timezone

import MetaTrader5 as mt5

from bot.config.constants import MAGIC_NUMBER
from bot.db.sqlite import SQLiteDB
from bot.db.supabase import SupabaseDB
from bot.mt5.client import MT5Client
from bot.mt5.types import OrderRequest

logger = logging.getLogger(__name__)

_ACTIVE_SIGNAL_STATUSES = frozenset({"active", "hit"})


class OrderPlacer:
    async def place_order(
        self,
        signal_id: int,
        limit_id: int,
        direction: str,
        db_stop_loss: float,
        db_price: float,
        signal_type: str,
        mt5_symbol: str,
        lot: float,
        offset: float | None,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
        supabase: SupabaseDB,
        channel_id: int | None = None,
    ) -> bool:
        tick = mt5_client.symbol_info_tick(mt5_symbol)
        if tick is None:
            logger.error("No tick for %s (signal=%d limit=%d)", mt5_symbol, signal_id, limit_id)
            return False

        info = mt5_client.symbol_info(mt5_symbol)
        if info is None:
            logger.error("No symbol_info for %s", mt5_symbol)
            return False

        spread = tick.ask - tick.bid
        base_price = db_price + (offset or 0.0)

        if direction == "long":
            adj_price = round(base_price + spread, info.digits)
            adj_sl = round(db_stop_loss + (offset or 0.0) - spread, info.digits)
            if adj_price < tick.ask:
                order_type = mt5.ORDER_TYPE_BUY_LIMIT
                order_type_str = "buy_limit"
            else:
                order_type = mt5.ORDER_TYPE_BUY_STOP
                order_type_str = "buy_stop"
        else:
            adj_price = round(base_price - spread, info.digits)
            adj_sl = round(db_stop_loss + (offset or 0.0) + spread, info.digits)
            if adj_price > tick.bid:
                order_type = mt5.ORDER_TYPE_SELL_LIMIT
                order_type_str = "sell_limit"
            else:
                order_type = mt5.ORDER_TYPE_SELL_STOP
                order_type_str = "sell_stop"

        comment = f"s{signal_id}_l{limit_id}"[:32]
        placed_at = datetime.now(timezone.utc).isoformat()

        # C2: pre-write claim so a crash between order_send and SQLite commit is recoverable
        await sqlite.insert_claimed_order(
            limit_id=limit_id,
            signal_id=signal_id,
            order_type=order_type_str,
            lot_size=lot,
            placed_at=placed_at,
            db_stop_loss=db_stop_loss,
            signal_type=signal_type,
            feed_price=db_price,
            mt5_price=adj_price,
            offset=offset,
            symbol=mt5_symbol,
            channel_id=channel_id,
        )

        # C3: pre-send status recheck — abort if signal was cancelled since this cycle began
        status = await supabase.fetch_signal_status(signal_id)
        if status not in _ACTIVE_SIGNAL_STATUSES:
            logger.warning(
                "Pre-send abort: signal=%d status=%r — placement cancelled", signal_id, status
            )
            await sqlite.delete_claimed_order(limit_id)
            return False

        request = OrderRequest(
            action=mt5.TRADE_ACTION_PENDING,
            symbol=mt5_symbol,
            volume=lot,
            type=order_type,
            price=adj_price,
            sl=adj_sl,
            magic=MAGIC_NUMBER,
            comment=comment,
        )

        result = mt5_client.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else "None"
            logger.error(
                "Placement failed: signal=%d limit=%d retcode=%s", signal_id, limit_id, retcode
            )
            await sqlite.delete_claimed_order(limit_id)
            return False

        await sqlite.promote_claimed_to_pending(limit_id, result.ticket)

        # H8: Verify broker accepted the exact SL/price (silent broker adjustments surface here)
        placed = mt5_client.order_get_by_ticket(result.ticket)
        if placed is not None:
            if abs(placed.sl - adj_sl) > info.point:
                logger.warning(
                    "Placement SL mismatch: ticket=%d requested=%.5f broker=%.5f",
                    result.ticket, adj_sl, placed.sl,
                )
            if abs(placed.price_open - adj_price) > info.point:
                logger.warning(
                    "Placement price mismatch: ticket=%d requested=%.5f broker=%.5f",
                    result.ticket, adj_price, placed.price_open,
                )
        else:
            logger.warning("Placement readback: order ticket=%d not found", result.ticket)

        logger.info(
            "Placed %s ticket=%d signal=%d limit=%d price=%.5f lot=%.2f",
            order_type_str, result.ticket, signal_id, limit_id, adj_price, lot,
        )
        return True
