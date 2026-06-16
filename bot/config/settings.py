import json
import logging
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from bot.config.constants import _PRODUCTION_DSN, _PRODUCTION_LICENSE_URL, AssetClass

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config.json")

_VALID_ASSET_CLASSES = frozenset(a.value for a in AssetClass)


class SymbolSuffixRule(BaseModel):
    suffix: str
    asset_classes: list[str]  # AssetClass values this suffix applies to

    @field_validator("asset_classes")
    @classmethod
    def _validate_classes(cls, v: list[str]) -> list[str]:
        unknown = [c for c in v if c not in _VALID_ASSET_CLASSES]
        if unknown:
            raise ValueError(f"unknown asset class(es): {', '.join(unknown)}")
        return v


class LotExceptionConfig(BaseModel):
    symbol: str
    signal_type: str = "all"  # "all" applies to every signal type
    mode: str  # "risk_percent" | "fixed"
    value: float  # percent for risk_percent, lots for fixed


class ExcludedTradeConfig(BaseModel):
    symbol: str
    signal_type: str = "all"  # "all" excludes every signal type for this symbol


class LotSizingConfig(BaseModel):
    mode: str = "risk_percent"
    risk_percent: float | dict[str, float] = 1.0
    fixed_lot: float | dict[str, float] = 0.01
    max_lot_per_order: float = 5.0
    exceptions: list[LotExceptionConfig] = []

    @field_validator("exceptions", mode="before")
    @classmethod
    def _coerce_exceptions(cls, v: object) -> object:
        # Back-compat: legacy `{symbol: {mode, value}}` dict → list of entries.
        if isinstance(v, dict):
            return [{"symbol": sym, **ex} for sym, ex in v.items()]
        return v


class PollingConfig(BaseModel):
    supabase_interval_seconds: int = 30
    tp_active_interval_seconds: int = 1
    tp_trailing_interval_seconds: int = 2
    license_heartbeat_seconds: int = 900


class SpreadHourConfig(BaseModel):
    daily_start: str = "16:45"
    stock_daily_start: str = "15:45"  # stocks close at 16:00 — cancel 15 min before
    daily_end: str = "18:00"
    # Filled positions have their SL stripped from here to daily_end so a spread spike
    # can't stop them out, then it's restored. Starts ~5 min before the spread spike
    # (forex 17:00, stocks' 16:00 close).
    sl_strip_start: str = "16:55"
    sl_strip_stock_start: str = "15:55"
    timezone: str = "US/Eastern"
    weekend_start_day: str = "Friday"
    weekend_end_day: str = "Sunday"


class ProximityConfig(BaseModel):
    forex_pips: float = 10.0
    forex_jpy_pips: float = 10.0
    metals: float = 15.0
    crypto: float = 1000.0
    stocks: float = 5.0
    indices: dict[str, float] = {
        "SPX": 20.0,
        "US500": 20.0,
        "NAS": 50.0,
        "USTEC": 50.0,
        "DAX": 50.0,
        "DE30": 50.0,
        "US30": 50.0,
        "US2000": 10.0,
        "JP225": 100.0,
    }
    stock_overrides: dict[str, float] = {}


class AssetTPConfig(BaseModel):
    profit_threshold: float
    threshold_unit: str
    trailing_distance: float
    partial_close_percent: int = 50


class ScalpOverrideConfig(BaseModel):
    profit_threshold: float
    trailing_distance: float
    partial_close_percent: int | None = None


class OneToOneConfig(BaseModel):
    profit_threshold: float = 10.0  # global default in account dollars
    overrides: dict[str, float] = {}  # per asset_class override (dollars)


class TPConfig(BaseModel):
    partial_close_percent: int = 50
    forex: AssetTPConfig
    forex_jpy: AssetTPConfig
    metals: AssetTPConfig
    indices: AssetTPConfig
    stocks: AssetTPConfig
    crypto: AssetTPConfig
    oil: AssetTPConfig
    scalp_overrides: dict[str, ScalpOverrideConfig] = {}
    toll_overrides: dict[str, ScalpOverrideConfig] = {}
    swing_overrides: dict[str, ScalpOverrideConfig] = {}
    pa_overrides: dict[str, ScalpOverrideConfig] = {}
    one_to_one: OneToOneConfig = OneToOneConfig()
    instrument_overrides: dict[str, dict] = {}


class Settings(BaseModel):
    license_key: str = ""
    mt5_terminal_path: str = ""
    lot_sizing: LotSizingConfig = LotSizingConfig()
    polling: PollingConfig = PollingConfig()
    magic_number: int = 20250001
    symbol_map: dict[str, str] = {
        "SPX500USD": "US500",
        "NAS100USD": "USTEC",
        "BTCUSDT": "BTCUSD",
        "ETHUSDT": "ETHUSD",
        "US30USD": "US30",
        "US2000USD": "US2000",
    }
    stock_suffix: str = "-24"
    # Per-asset-class broker suffix rules. Each rule appends `suffix` to every MT5
    # symbol whose detected asset class is listed in `asset_classes` (e.g. Exness
    # "m" on forex/metals/crypto: EURUSD -> EURUSDm). An asset class may appear in
    # at most one rule.
    symbol_suffixes: list[SymbolSuffixRule] = []
    stock_no_suffix: list[str] = []
    excluded_symbols: list[str] = []
    # Per-(symbol, signal_type) exclusions. signal_type "all" drops every type.
    excluded_trades: list[ExcludedTradeConfig] = []
    # Signal types and channel ids that are skipped wholesale (empty = none skipped).
    disabled_signal_types: list[str] = []
    disabled_channels: list[str] = []
    offset_instruments: list[str] = [
        "SPX500USD",
        "NAS100USD",
        "BTCUSDT",
        "ETHUSDT",
        "US30USD",
        "US2000USD",
        "JP225",
    ]
    offset_drift_threshold_pips: float = 5.0
    offset_drift_check_interval_seconds: int = 1800
    # Offset is a slow-moving broker-vs-feed property — recompute at most this often
    # per symbol and serve the cached value in between (the feed itself refreshes ~5s).
    offset_recompute_interval_seconds: int = 300
    # Dead-feed bound: while a signal is active the feed refreshes ~5s, so a stale
    # updated_at means the feed updater has stalled — skip placement past this age.
    feed_max_staleness_seconds: int = 120
    spread_hour: SpreadHourConfig = SpreadHourConfig()
    proximity: ProximityConfig = ProximityConfig()
    tp_config: TPConfig

    @model_validator(mode="before")
    @classmethod
    def _migrate_universal_suffix(cls, data: object) -> object:
        # Back-compat: a legacy flat `universal_suffix` becomes one rule covering
        # every asset class (its original all-symbols behaviour).
        if (
            isinstance(data, dict)
            and "symbol_suffixes" not in data
            and data.get("universal_suffix")
        ):
            data["symbol_suffixes"] = [
                {"suffix": data["universal_suffix"], "asset_classes": sorted(_VALID_ASSET_CLASSES)}
            ]
        return data

    @field_validator("symbol_suffixes")
    @classmethod
    def _no_class_conflicts(cls, v: list[SymbolSuffixRule]) -> list[SymbolSuffixRule]:
        seen: set[str] = set()
        for rule in v:
            for ac in rule.asset_classes:
                if ac in seen:
                    raise ValueError(f"asset class '{ac}' assigned to multiple suffix rules")
                seen.add(ac)
        return v


def load_config(path: Path = _CONFIG_PATH) -> Settings | None:
    try:
        data = json.loads(path.read_text())
        return Settings.model_validate(data)
    except FileNotFoundError:
        logger.error("config.json not found at %s", path.resolve())
        return None
    except json.JSONDecodeError as e:
        logger.error("config.json parse error: %s", e)
        return None
    except ValidationError as e:
        logger.error("config.json validation error: %s", e)
        return None


def load_dsn() -> str:
    return _PRODUCTION_DSN


def load_license_url() -> str:
    return _PRODUCTION_LICENSE_URL
