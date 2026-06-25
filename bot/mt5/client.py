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
    RateInfo,
    SymbolInfo,
    TickInfo,
)

logger = logging.getLogger(__name__)

_TRANSIENT_RETCODES = frozenset(
    {
        mt5.TRADE_RETCODE_REQUOTE,
        mt5.TRADE_RETCODE_CONNECTION,
        mt5.TRADE_RETCODE_TIMEOUT,
    }
)

_BULK_CACHE_TTL = 0.5  # seconds — collapses duplicate calls within a single cycle
_TICK_FAIL_COOLDOWN = 60.0  # seconds — silence repeat errors for a missing symbol
_SYMBOLS_CACHE_TTL = 300.0  # seconds — broker symbol list is near-static
# trade_tick_value is live for cross pairs (EURGBP, EURCAD, …): it's the quote/profit
# currency tick value converted to the account currency at the current rate, so it
# drifts as that rate moves. Risk sizing depends entirely on it, so the cache must
# expire — a permanent cache freezes a stale (or bad first-read) conversion rate and
# mis-sizes lots. Static fields (digits, volumes, contract size) tolerate the refetch.
_SYMBOL_INFO_TTL = 30.0  # seconds

# symbol_info.filling_mode bitmask values (the MetaTrader5 package exposes the
# ORDER_FILLING_* enum but not these SYMBOL_FILLING_* bits).
_SYMBOL_FILLING_FOK = 1
_SYMBOL_FILLING_IOC = 2


class MT5Client:
    def __init__(self, connection: MT5Connection) -> None:
        self._conn = connection
        self._symbol_info_cache: dict[str, tuple[float, SymbolInfo]] = {}
        self._positions_cache: tuple[float, list[PositionInfo]] | None = None
        self._orders_cache: tuple[float, list[OrderInfo]] | None = None
        self._account_cache: tuple[float, AccountInfo | None] | None = None
        self._tick_unavailable_until: dict[str, float] = {}
        self._symbols_cache: tuple[float, frozenset[str]] | None = None
        self._selected: set[str] = set()

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
        if request.type_filling is not None:
            req["type_filling"] = request.type_filling
        result = None
        for attempt in range(1, 4):
            result = mt5.order_send(req)
            if result is None:
                logger.error("order_send returned None (attempt %d)", attempt)
                continue
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                break
            if result.retcode in _TRANSIENT_RETCODES:
                logger.warning(
                    "Transient retcode %d on attempt %d, retrying", result.retcode, attempt
                )
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
        now = time.monotonic()
        cached = self._symbol_info_cache.get(symbol)
        if cached is not None and (now - cached[0]) < _SYMBOL_INFO_TTL:
            return cached[1]
        raw = mt5.symbol_info(symbol)
        if raw is None:
            logger.error("symbol_info(%s) failed: %s", symbol, mt5.last_error())
            return cached[1] if cached is not None else None
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
            filling_mode=raw.filling_mode,
        )
        self._symbol_info_cache[symbol] = (now, info)
        return info

    def symbol_info_tick(self, symbol: str) -> TickInfo | None:
        now = time.monotonic()
        if now < self._tick_unavailable_until.get(symbol, 0.0):
            return None
        raw = mt5.symbol_info_tick(symbol)
        if raw is None:
            logger.error("symbol_info_tick(%s) failed: %s", symbol, mt5.last_error())
            self._tick_unavailable_until[symbol] = now + _TICK_FAIL_COOLDOWN
            return None
        self._tick_unavailable_until.pop(symbol, None)
        return TickInfo(
            symbol=symbol, bid=raw.bid, ask=raw.ask, time=raw.time, time_msc=raw.time_msc
        )

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
            margin_mode=raw.margin_mode,
            server=raw.server,
            company=raw.company,
        )
        self._account_cache = (now, result)
        return result

    def symbols_get(self) -> frozenset[str]:
        """All symbol names the broker exposes (visible or not). Cached — the list
        is near-static and symbols_get() returns thousands of rows."""
        now = time.monotonic()
        if self._symbols_cache and (now - self._symbols_cache[0]) < _SYMBOLS_CACHE_TTL:
            return self._symbols_cache[1]
        raw = mt5.symbols_get()
        names = frozenset(s.name for s in raw) if raw else frozenset()
        self._symbols_cache = (now, names)
        return names

    def symbol_select(self, symbol: str) -> bool:
        """Load a symbol into MarketWatch so ticks/history become available. Called
        once per symbol — brokers hide most of their catalogue by default."""
        if symbol in self._selected:
            return True
        if mt5.symbol_select(symbol, True):
            self._selected.add(symbol)
            return True
        return False

    def resolve_filling(self, symbol: str) -> int:
        """Pick a market-order filling mode the symbol actually allows. Prefer IOC
        (the prior hardcoded choice — keeps ICMarkets behavior), then FOK, then
        RETURN, so brokers that reject IOC don't fail closes."""
        info = self.symbol_info(symbol)
        mode = info.filling_mode if info else 0
        if mode & _SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        if mode & _SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def copy_ticks_range(
        self, symbol: str, date_from: datetime, date_to: datetime
    ) -> list[TickInfo]:
        """Historical ticks in [date_from, date_to]. Datetimes must already be in
        the broker server frame (see OffsetCalculator). Returns [] when none."""
        raw = mt5.copy_ticks_range(symbol, date_from, date_to, mt5.COPY_TICKS_ALL)
        if raw is None or len(raw) == 0:
            return []
        return [
            TickInfo(
                symbol=symbol,
                bid=float(t["bid"]),
                ask=float(t["ask"]),
                time=int(t["time"]),
                time_msc=int(t["time_msc"]),
            )
            for t in raw
        ]

    def copy_rates_range(
        self, symbol: str, timeframe: int, date_from: datetime, date_to: datetime
    ) -> list[RateInfo]:
        """Historical bars in [date_from, date_to] — M1 fallback for offset lookups
        when tick history isn't available that far back. Returns [] when none."""
        raw = mt5.copy_rates_range(symbol, timeframe, date_from, date_to)
        if raw is None or len(raw) == 0:
            return []
        return [
            RateInfo(time=int(r["time"]), open=float(r["open"]), close=float(r["close"]))
            for r in raw
        ]

    def cancel_pending_order(self, ticket: int) -> OrderResult | None:
        result = mt5.order_send(
            {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": ticket,
            }
        )
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
            "type_filling": self.resolve_filling(symbol),
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
                logger.warning(
                    "Transient retcode %d closing %d attempt %d", result.retcode, ticket, attempt
                )
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
        result = mt5.order_send(
            {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": symbol,
                "sl": new_sl,
                "tp": 0.0,
            }
        )
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

    def history_deals_get(
        self, from_time: datetime, to_time: datetime, position_id: int | None = None
    ) -> list[DealInfo]:
        # SL/TP-triggered close deals are issued by the broker and may not carry our
        # magic, so don't filter by magic here — callers filter by position_id instead.
        if position_id is not None:
            raw = mt5.history_deals_get(position=position_id)
        else:
            raw = mt5.history_deals_get(from_time, to_time)
        if raw is None:
            return []
        return [
            DealInfo(
                ticket=d.ticket,
                order=d.order,
                position_id=d.position_id,
                symbol=d.symbol,
                type=d.type,
                entry=d.entry,
                volume=d.volume,
                price=d.price,
                profit=d.profit,
                commission=d.commission,
                swap=d.swap,
                time=d.time,
                comment=d.comment,
            )
            for d in raw
        ]

    def get_position_realized_pnl(self, position_ticket: int) -> float | None:
        """Sum of profit + swap + commission across all deals for this position.
        Returns None if MT5 history is unavailable. Returns 0.0 if no deals match
        (e.g. position just opened with no closing deal yet)."""
        deals = self.history_deals_get(
            datetime.fromtimestamp(0), datetime.now(), position_id=position_ticket
        )
        if not deals:
            return None
        return sum(d.profit + d.swap + d.commission for d in deals)
