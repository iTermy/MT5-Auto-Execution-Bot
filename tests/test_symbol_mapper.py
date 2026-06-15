import pytest
from pydantic import ValidationError

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


def test_map_symbol_appends_broker_suffix() -> None:
    cfg = make_settings(
        symbol_suffixes=[{"suffix": "m", "asset_classes": ["forex", "crypto", "stocks"]}]
    )
    # Plain passthrough, symbol-map target, and stock suffix all get the broker suffix.
    assert map_symbol("EURUSD", cfg) == "EURUSDm"
    assert map_symbol("BTCUSDT", cfg) == "BTCUSDm"
    assert map_symbol("AMD.NAS", cfg) == "AMD.NAS-24m"


def test_map_symbol_suffix_scoped_to_asset_class() -> None:
    # "m" only on forex/metals/crypto — indices and stocks stay bare.
    cfg = make_settings(
        symbol_suffixes=[
            {"suffix": "m", "asset_classes": ["forex", "forex_jpy", "metals", "crypto"]}
        ]
    )
    assert map_symbol("EURUSD", cfg) == "EURUSDm"
    assert map_symbol("XAUUSD", cfg) == "XAUUSDm"
    assert map_symbol("SPX500USD", cfg) == "US500"
    assert map_symbol("AMD.NAS", cfg) == "AMD.NAS-24"


def test_map_symbol_multiple_suffix_rules() -> None:
    cfg = make_settings(
        symbol_suffixes=[
            {"suffix": "m", "asset_classes": ["forex", "forex_jpy"]},
            {"suffix": ".r", "asset_classes": ["crypto"]},
        ]
    )
    assert map_symbol("EURUSD", cfg) == "EURUSDm"
    assert map_symbol("BTCUSDT", cfg) == "BTCUSD.r"


def test_map_symbol_does_not_double_suffix_explicit_mapping() -> None:
    # Mapping straight to "SPX500m" while indices also carries an "m" rule must not
    # produce "SPX500mm".
    cfg = make_settings(
        symbol_map={"SPX500USD": "SPX500m"},
        symbol_suffixes=[{"suffix": "m", "asset_classes": ["indices"]}],
    )
    assert map_symbol("SPX500USD", cfg) == "SPX500m"


def test_symbol_suffix_class_conflict_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(
            symbol_suffixes=[
                {"suffix": "m", "asset_classes": ["forex"]},
                {"suffix": "s", "asset_classes": ["forex"]},
            ]
        )


def test_symbol_suffix_unknown_class_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(symbol_suffixes=[{"suffix": "m", "asset_classes": ["stonks"]}])


def test_legacy_universal_suffix_migrated_to_all_classes() -> None:
    cfg = make_settings(universal_suffix="m")
    assert map_symbol("EURUSD", cfg) == "EURUSDm"
    assert map_symbol("SPX500USD", cfg) == "US500m"
    assert map_symbol("AMD.NAS", cfg) == "AMD.NAS-24m"


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


def test_db_symbol_from_mt5_strips_broker_suffix() -> None:
    cfg = make_settings(
        symbol_suffixes=[{"suffix": "m", "asset_classes": ["forex", "crypto", "stocks"]}]
    )
    assert db_symbol_from_mt5("EURUSDm", cfg) == "EURUSD"
    assert db_symbol_from_mt5("BTCUSDm", cfg) == "BTCUSDT"  # reverse symbol_map after strip
    assert db_symbol_from_mt5("AMD.NAS-24m", cfg) == "AMD.NAS"  # strip broker then stock


def test_db_symbol_from_mt5_no_suffix_for_unscoped_class() -> None:
    # "m" only covers forex, so an indices symbol carries no suffix to strip.
    cfg = make_settings(symbol_suffixes=[{"suffix": "m", "asset_classes": ["forex"]}])
    assert db_symbol_from_mt5("US500", cfg) == "SPX500USD"
    assert db_symbol_from_mt5("EURUSDm", cfg) == "EURUSD"
