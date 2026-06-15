from bot.config.constants import AssetClass
from bot.config.settings import Settings

_METALS = frozenset({"XAUUSD", "XAGUSD", "GOLD", "SILVER"})
_OIL_KEYWORDS = ("OIL", "WTI", "BRENT")
_INDEX_KEYWORDS = ("SPX", "NAS", "DAX", "DE30", "DE40", "JP225", "UK100", "US500", "USTEC")


def detect_asset_class(db_symbol: str) -> AssetClass:
    s = db_symbol.upper()

    if s in _METALS:
        return AssetClass.METALS
    if any(k in s for k in _OIL_KEYWORDS):
        return AssetClass.OIL
    # Stocks MUST be checked before indices (e.g. "AMD.NAS" contains "NAS")
    if s.endswith(".NAS") or s.endswith(".NYSE"):
        return AssetClass.STOCKS
    # Gold and micro-gold futures (e.g. MGCQ6, GCZ6) — must precede the index check
    if s.startswith("MGC") or s.startswith("GC"):
        return AssetClass.METALS
    if any(k in s for k in _INDEX_KEYWORDS):
        return AssetClass.INDICES
    if (s.endswith("USD") or s.endswith("USDT")) and len(s) > 6:
        return AssetClass.CRYPTO
    if "JPY" in s:
        return AssetClass.FOREX_JPY
    return AssetClass.FOREX


def _suffix_for(db_symbol: str, config: Settings) -> str:
    asset = detect_asset_class(db_symbol).value
    for rule in config.symbol_suffixes:
        if asset in rule.asset_classes:
            return rule.suffix
    return ""


def map_symbol(db_symbol: str, config: Settings) -> str:
    if db_symbol in config.symbol_map:
        mt5_symbol = config.symbol_map[db_symbol]
    elif db_symbol.upper().endswith((".NAS", ".NYSE")) and db_symbol not in config.stock_no_suffix:
        mt5_symbol = db_symbol + config.stock_suffix
    else:
        mt5_symbol = db_symbol
    # Don't double up when an explicit symbol_map target already carries the suffix
    # (e.g. mapping SPX500USD -> "SPX500m" while indices also has an "m" rule).
    suffix = _suffix_for(db_symbol, config)
    if suffix and not mt5_symbol.endswith(suffix):
        mt5_symbol += suffix
    return mt5_symbol


def needs_offset(db_symbol: str, config: Settings) -> bool:
    return db_symbol in config.offset_instruments


def _strip_to_base(mt5_symbol: str, config: Settings) -> str:
    for db_sym, mapped in config.symbol_map.items():
        if mapped == mt5_symbol:
            return db_sym
    if config.stock_suffix and mt5_symbol.endswith(config.stock_suffix):
        return mt5_symbol[: -len(config.stock_suffix)]
    return mt5_symbol


def db_symbol_from_mt5(mt5_symbol: str, config: Settings) -> str:
    """Reverse-map an MT5 symbol back to its DB symbol for asset-class detection.
    The broker suffix depends on the (unknown) asset class, so try each configured
    suffix (longest first) and keep the candidate that round-trips through
    map_symbol; fall back to a plain strip when none match."""
    for suffix in sorted(
        {r.suffix for r in config.symbol_suffixes if r.suffix}, key=len, reverse=True
    ):
        if mt5_symbol.endswith(suffix):
            db_sym = _strip_to_base(mt5_symbol[: -len(suffix)], config)
            if map_symbol(db_sym, config) == mt5_symbol:
                return db_sym
    return _strip_to_base(mt5_symbol, config)
