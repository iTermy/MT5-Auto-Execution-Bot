import logging
import time
from datetime import datetime

import MetaTrader5 as mt5

from bot.config.constants import MAGIC_NUMBER
from bot.mt5.connection import MT5Connection
from bot.mt5.types import (
    AccountInfo,
    DealInfo,
    OrderInfo,
    OrderRequest,
    OrderResult,
    PositionInfo,
    SymbolInfo,
    TickInfo,
)

logger = logging.getLogger(__name__)

_TRANSIENT_RETCODES = frozenset({
    mt5.TRADE_RETCODE_REQUOTE,
    mt5.TRADE_RETCODE_CONNECTION,
    mt5.TRADE_RETCODE_TIMEOUT,
})

_BULK_CACHE_TTL = 0.5  # seconds — collapses duplicate calls within a single cycle


class MT5Client:
    def __init__(self, connection: MT5Connection) -> None:
        self._conn = connection
        self._symbol_info_cache: dict[str, SymbolInfo] = {}
        self._positions_cache: tuple[float, list[PositionInfo]] | None = None
        self._orders_cache: tuple[float, list[OrderInfo]] | None = None
        self._account_cache: tuple[float, AccountInfo | None] | None = None

    def ensure_connected(self) -> bool:
        return self._conn.ensure_connected()

    def order_send(self, request: OrderRequest) -> OrderResult | None:
        req = {
            "action": request.action,
            "symbol": request.symbol,
            "volume": request.volume,
            "type": request.type,
            "price": request.price,
            "sl": request.sl,
            "tp": request.tp,
            "deviation": request.deviation,
            "magic": request.magic,
            "comment": request.comment,
            "type_time": request.type_time,
            "expiration": request.expiration,
        }
        result = None
        for attempt in range(1, 4):
            result = mt5.order_send(req)
            if result is None:
                logger.error("order_send returned None (attempt %d)", attempt)
                continue
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                break
            if result.retcode in _TRANSIENT_RETCODES:
                logger.warning("Transient retcode %d on attempt %d, retrying", result.retcode, attempt)
                continue
            break
        if result is None:
            return None
        return OrderResult(
            retcode=result.retcode,
            ticket=result.order,
            volume=result.volume,
            price=result.price,
            comment=result.comment,
        )

    def order_get_by_ticket(self, ticket: int) -> OrderInfo | None:
        """Fetch a single pending order by ticket number (bypasses bulk cache)."""
        raw = mt5.orders_get(ticket=ticket)
        if not raw:
            return None
        o = raw[0]
        return OrderInfo(
            ticket=o.ticket,
            symbol=o.symbol,
            volume_current=o.volume_current,
            type=o.type,
            price_open=o.price_open,
            sl=o.sl,
            tp=o.tp,
            magic=o.magic,
            comment=o.comment,
            time_setup=o.time_setup,
        )

    def orders_get(self) -> list[OrderInfo]:
        now = time.monotonic()
        if self._orders_cache and (now - self._orders_cache[0]) < _BULK_CACHE_TTL:
            return self._orders_cache[1]
        raw = mt5.orders_get()
        if raw is None:
            result: list[OrderInfo] = []
        else:
            result = [
                OrderInfo(
                    ticket=o.ticket,
                    symbol=o.symbol,
                    volume_current=o.volume_current,
                    type=o.type,
                    price_open=o.price_open,
                    sl=o.sl,
                    tp=o.tp,
                    magic=o.magic,
                    comment=o.comment,
                    time_setup=o.time_setup,
                )
                for o in raw
                if o.magic == MAGIC_NUMBER
            ]
        self._orders_cache = (now, result)
        return result

    def positions_get(self) -> list[PositionInfo]:
        now = time.monotonic()
        if self._positions_cache and (now - self._positions_cache[0]) < _BULK_CACHE_TTL:
            return self._positions_cache[1]
        raw = mt5.positions_get()
        if raw is None:
            result: list[PositionInfo] = []
        else:
            result = [
                PositionInfo(
                    ticket=o.ticket,
                    symbol=o.symbol,
                    volume=o.volume,
                    type=o.type,
                    price_open=o.price_open,
                    sl=o.sl,
                    tp=o.tp,
                    profit=o.profit,
                    magic=o.magic,
                    comment=o.comment,
                    time=o.time,
                    identifier=o.identifier,
                )
                for o in raw
                if o.magic == MAGIC_NUMBER
            ]
        self._positions_cache = (now, result)
        return result

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        cached = self._symbol_info_cache.get(symbol)
        if cached is not None:
            return cached
        raw = mt5.symbol_info(symbol)
        if raw is None:
            logger.error("symbol_info(%s) failed: %s", symbol, mt5.last_error())
            return None
        info = SymbolInfo(
            name=raw.name,
            digits=raw.digits,
            point=raw.point,
            volume_min=raw.volume_min,
            volume_max=raw.volume_max,
            volume_step=raw.volume_step,
            trade_tick_value=raw.trade_tick_value,
            trade_tick_size=raw.trade_tick_size,
            trade_contract_size=raw.trade_contract_size,
        )
        self._symbol_info_cache[symbol] = info
        return info

    def symbol_info_tick(self, symbol: str) -> TickInfo | None:
        raw = mt5.symbol_info_tick(symbol)
        if raw is None:
            logger.error("symbol_info_tick(%s) failed: %s", symbol, mt5.last_error())
            return None
        return TickInfo(symbol=symbol, bid=raw.bid, ask=raw.ask, time=raw.time)

    def account_info(self) -> AccountInfo | None:
        now = time.monotonic()
        if self._account_cache and (now - self._account_cache[0]) < _BULK_CACHE_TTL:
            return self._account_cache[1]
        raw = mt5.account_info()
        if raw is None:
            logger.error("account_info failed: %s", mt5.last_error())
            self._account_cache = (now, None)
            return None
        result = AccountInfo(
            login=raw.login,
            balance=raw.balance,
            equity=raw.equity,
            margin=raw.margin,
            margin_free=raw.margin_free,
            leverage=raw.leverage,
            currency=raw.currency,
        )
        self._account_cache = (now, result)
        return result

    def cancel_pending_order(self, ticket: int) -> OrderResult | None:
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": ticket,
        })
        if result is None:
            logger.error("cancel_pending_order(%d) returned None", ticket)
            return None
        return OrderResult(
            retcode=result.retcode,
            ticket=ticket,
            volume=0.0,
            price=0.0,
            comment=result.comment,
        )

    def close_position(
        self,
        ticket: int,
        symbol: str,
        volume: float,
        position_type: int,
        comment: str = "",
    ) -> OrderResult | None:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error("close_position: no tick for %s", symbol)
            return None
        if position_type == 0:  # long -> sell to close
            price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        else:  # short -> buy to close
            price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": MAGIC_NUMBER,
            "comment": comment or "tp",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = None
        for attempt in range(1, 4):
            result = mt5.order_send(req)
            if result is None:
                logger.error("close_position(%d) returned None (attempt %d)", ticket, attempt)
                continue
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                break
            if result.retcode in _TRANSIENT_RETCODES:
                logger.warning("Transient retcode %d closing %d attempt %d", result.retcode, ticket, attempt)
                continue
            break
        if result is None:
            return None
        return OrderResult(
            retcode=result.retcode,
            ticket=ticket,
            volume=volume,
            price=result.price,
            comment=result.comment,
        )

    def modify_position_sl(self, ticket: int, symbol: str, new_sl: float) -> OrderResult | None:
        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": new_sl,
            "tp": 0.0,
        })
        if result is None:
            logger.error("modify_position_sl(%d) returned None", ticket)
            return None
        return OrderResult(
            retcode=result.retcode,
            ticket=ticket,
            volume=0.0,
            price=new_sl,
            comment=result.comment,
        )

    def history_deals_get(self, from_time: datetime, to_time: datetime) -> list[DealInfo]:
        raw = mt5.history_deals_get(from_time, to_time)
        if raw is None:
            return []
        return [
            DealInfo(
                ticket=d.ticket,
                order=d.order,
                symbol=d.symbol,
                type=d.type,
                volume=d.volume,
                price=d.price,
                time=d.time,
                comment=d.comment,
            )
            for d in raw
            if d.magic == MAGIC_NUMBER
        ]
