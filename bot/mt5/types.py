from dataclasses import dataclass


@dataclass
class OrderRequest:
    action: int
    symbol: str
    volume: float
    type: int
    price: float
    sl: float
    magic: int
    comment: str
    tp: float = 0.0
    deviation: int = 20
    type_time: int = 0  # ORDER_TIME_GTC
    expiration: int = 0
    type_filling: int | None = None  # None → omit, let the terminal pick its default


@dataclass
class OrderResult:
    retcode: int
    ticket: int
    volume: float
    price: float
    comment: str


@dataclass
class OrderInfo:
    ticket: int
    symbol: str
    volume_current: float
    type: int
    price_open: float
    sl: float
    tp: float
    magic: int
    comment: str
    time_setup: int


@dataclass
class PositionInfo:
    ticket: int
    symbol: str
    volume: float
    type: int  # 0=buy, 1=sell
    price_open: float
    sl: float
    tp: float
    profit: float
    magic: int
    comment: str
    time: int
    identifier: int


@dataclass
class TickInfo:
    symbol: str
    bid: float
    ask: float
    time: int
    time_msc: int = 0  # broker-server epoch milliseconds (sub-second tick precision)


@dataclass
class SymbolInfo:
    name: str
    digits: int
    point: float
    volume_min: float
    volume_max: float
    volume_step: float
    trade_tick_value: float
    trade_tick_size: float
    trade_contract_size: float
    filling_mode: int = 0  # SYMBOL_FILLING_* bitmask of modes the broker allows


@dataclass
class RateInfo:
    time: int  # bar open time, broker-server epoch seconds
    open: float
    close: float


@dataclass
class AccountInfo:
    login: int
    balance: float
    equity: float
    margin: float
    margin_free: float
    leverage: int
    currency: str
    margin_mode: int = 0  # ACCOUNT_MARGIN_MODE_* (RETAIL_HEDGING expected)
    server: str = ""
    company: str = ""


@dataclass
class DealInfo:
    ticket: int
    order: int  # originating order ticket
    position_id: int
    symbol: str
    type: int
    entry: int  # 0=in, 1=out, 2=inout, 3=out_by
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    time: int
    comment: str
