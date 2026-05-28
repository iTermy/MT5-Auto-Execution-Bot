from bot.config.constants import AssetClass
from bot.config.settings import Settings

_METALS = frozenset({"XAUUSD", "XAGUSD", "GOLD", "SILVER"})
_OIL_KEYWORDS = ("OIL", "WTI", "BRENT")
_INDEX_KEYWORDS = ("SPX", "NAS", "DAX", "JP225", "UK100", "US500", "USTEC")


def detect_asset_class(db_symbol: str) -> AssetClass:
    s = db_symbol.upper()

    if s in _METALS:
        return AssetClass.METALS
    if any(k in s for k in _OIL_KEYWORDS):
        return AssetClass.OIL
    # Stocks MUST be checked before indices (e.g. "AMD.NAS" contains "NAS")
    if s.endswith(".NAS") or s.endswith(".NYSE"):
        return AssetClass.STOCKS
    if any(k in s for k in _INDEX_KEYWORDS):
        return AssetClass.INDICES
    if (s.endswith("USD") or s.endswith("USDT")) and len(s) > 6:
        return AssetClass.CRYPTO
    if "JPY" in s:
        return AssetClass.FOREX_JPY
    return AssetClass.FOREX


def map_symbol(db_symbol: str, config: Settings) -> str:
    if db_symbol in config.symbol_map:
        return config.symbol_map[db_symbol]
    if db_symbol.upper().endswith((".NAS", ".NYSE")):
        return db_symbol + config.stock_suffix
    return db_symbol


def needs_offset(db_symbol: str, config: Settings) -> bool:
    return db_symbol in config.offset_instruments


def db_symbol_from_mt5(mt5_symbol: str, config: Settings) -> str:
    """Reverse-map MT5 symbol to DB symbol for asset-class detection."""
    for db_sym, mapped in config.symbol_map.items():
        if mapped == mt5_symbol:
            return db_sym
    if config.stock_suffix and mt5_symbol.endswith(config.stock_suffix):
        return mt5_symbol[: -len(config.stock_suffix)]
    return mt5_symbol
