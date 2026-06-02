import pytest

from bot.config.constants import AssetClass
from bot.trading.symbol_mapper import db_symbol_from_mt5, detect_asset_class, map_symbol
from tests.conftest import make_settings

# ---------------------------------------------------------------------------
# detect_asset_class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol,expected",
    [
        # Metals
        ("XAUUSD", AssetClass.METALS),
        ("XAGUSD", AssetClass.METALS),
        ("GOLD", AssetClass.METALS),
        ("SILVER", AssetClass.METALS),
        # Gold futures contracts (e.g. MGCQ6, GCZ6) — also metals
        ("MGCQ6", AssetClass.METALS),
        ("MGCZ6", AssetClass.METALS),
        ("GCG7", AssetClass.METALS),
        # Oil
        ("WTI", AssetClass.OIL),
        ("BRENTUSD", AssetClass.OIL),
        ("USOIL", AssetClass.OIL),
        # Stocks — must beat indices (AMD.NAS contains "NAS")
        ("AMD.NAS", AssetClass.STOCKS),
        ("MSFT.NYSE", AssetClass.STOCKS),
        # Indices
        ("US500", AssetClass.INDICES),
        ("USTEC", AssetClass.INDICES),
        (
            "NAS100USD",
            AssetClass.INDICES,
        ),  # contains NAS keyword; NOT crypto (len>6 check comes after)
        ("DAX40", AssetClass.INDICES),
        ("JP225", AssetClass.INDICES),
        # Crypto — ends USD/USDT and len > 6
        ("BTCUSDT", AssetClass.CRYPTO),  # len 7
        ("ETHUSDT", AssetClass.CRYPTO),  # len 7
        ("BTCUSD", AssetClass.FOREX),  # len 6 — falls through to FOREX
        # Forex JPY
        ("USDJPY", AssetClass.FOREX_JPY),
        ("EURJPY", AssetClass.FOREX_JPY),
        # Forex default
        ("EURUSD", AssetClass.FOREX),
        ("GBPUSD", AssetClass.FOREX),
    ],
)
def test_detect_asset_class(symbol: str, expected: AssetClass) -> None:
    assert detect_asset_class(symbol) == expected


def test_stocks_beats_indices_for_nas_suffix() -> None:
    # AMD.NAS contains "NAS" which is in _INDEX_KEYWORDS, but .NAS suffix check comes first
    assert detect_asset_class("AMD.NAS") == AssetClass.STOCKS
    assert detect_asset_class("MSFT.NYSE") == AssetClass.STOCKS


def test_btcusd_is_forex_not_crypto() -> None:
    # BTCUSD has len==6 so the crypto rule (len > 6) does not match
    assert detect_asset_class("BTCUSD") == AssetClass.FOREX


# ---------------------------------------------------------------------------
# map_symbol
# ---------------------------------------------------------------------------


def test_map_symbol_uses_symbol_map() -> None:
    cfg = make_settings()
    assert map_symbol("BTCUSDT", cfg) == "BTCUSD"
    assert map_symbol("SPX500USD", cfg) == "US500"


def test_map_symbol_appends_stock_suffix() -> None:
    cfg = make_settings()
    assert map_symbol("AMD.NAS", cfg) == "AMD.NAS-24"
    assert map_symbol("MSFT.NYSE", cfg) == "MSFT.NYSE-24"


def test_map_symbol_passthrough() -> None:
    cfg = make_settings()
    assert map_symbol("EURUSD", cfg) == "EURUSD"
    assert map_symbol("XAUUSD", cfg) == "XAUUSD"


# ---------------------------------------------------------------------------
# db_symbol_from_mt5 (reverse mapping)
# ---------------------------------------------------------------------------


def test_db_symbol_from_mt5_reverses_symbol_map() -> None:
    cfg = make_settings()
    assert db_symbol_from_mt5("BTCUSD", cfg) == "BTCUSDT"
    assert db_symbol_from_mt5("US500", cfg) == "SPX500USD"


def test_db_symbol_from_mt5_strips_stock_suffix() -> None:
    cfg = make_settings()
    assert db_symbol_from_mt5("AMD.NAS-24", cfg) == "AMD.NAS"
    assert db_symbol_from_mt5("MSFT.NYSE-24", cfg) == "MSFT.NYSE"


def test_db_symbol_from_mt5_passthrough_unknown() -> None:
    cfg = make_settings()
    assert db_symbol_from_mt5("EURUSD", cfg) == "EURUSD"
