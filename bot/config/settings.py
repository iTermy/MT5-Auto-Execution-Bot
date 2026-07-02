import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from bot.config.constants import (
    _PRODUCTION_DSN,
    _PRODUCTION_LICENSE_URL,
    _PRODUCTION_UPDATE_MANIFEST_URL,
    AssetClass,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config.json")

_VALID_ASSET_CLASSES = frozenset(a.value for a in AssetClass)

# Feed-offset instruments: DB symbols whose Supabase price comes from an external
# feed (OANDA indices/oil, Binance crypto), so the bot derives a broker-vs-feed
# offset before placing. Forex and gold are direct-feed (broker price) and absent.
DEFAULT_OFFSET_INSTRUMENTS = [
    "SPX500USD",
    "NAS100USD",
    "BTCUSDT",
    "ETHUSDT",
    "US30USD",
    "US2000USD",
    "USOILSPOT",
    "DE30EUR",
    "UK100USD",
    "JP225",
]

# Default DB→broker symbol map (DB symbol → MT5/broker symbol). Single source for both
# the Settings.symbol_map default and the symbol-map backfill migration, so an install
# missing an entry gets the default without overriding any the user has customised.
_DEFAULT_SYMBOL_MAP = {
    "SPX500USD": "US500",
    "NAS100USD": "USTEC",
    "BTCUSDT": "BTCUSD",
    "ETHUSDT": "ETHUSD",
    "USOILSPOT": "XTIUSD",
    "US30USD": "US30",
    "US2000USD": "US2000",
    "DE30EUR": "DE40",
    "UK100USD": "UK100",
}

# Symbols every existing install should carry as offset-feed after updating. Applied
# once per install via `migrate_config` (tracked in `config_migrations`), so a user
# may still remove them afterwards without the migration re-adding them.
_OFFSET_BACKFILL_SYMBOLS = ("USOILSPOT", "DE30EUR", "US2000USD")
_MIGRATION_OFFSET_BACKFILL = "offset_feed_backfill_v1"

# Wider placement proximity for existing installs: forex/JPY → 15 pips, metals →
# $25, indices doubled. Applied once per install via `migrate_config`, so a user may
# still re-tune any value afterwards without the migration re-applying.
_MIGRATION_PROXIMITY_BUMP = "proximity_bump_v1"

# Move the forex pending-cancel/placement-block start earlier (16:45 → 15:55) so
# late-market signals stop activating well before the spread spike. SL stripping is
# unchanged (sl_strip_start 16:55). Applied once per install via `migrate_config`, so
# a user may still re-tune daily_start afterwards without the migration re-applying.
_MIGRATION_SPREAD_HOUR_LATE = "spread_hour_late_market_v1"

# Backfill any missing _DEFAULT_SYMBOL_MAP entry for installs that predate it: without
# the DB→broker map the offset can't resolve to the broker symbol. Applied via
# setdefault, so a user who already re-mapped an entry keeps their own choice. UK100 is
# also added to offset_instruments (it postdates the earlier offset backfill).
_MIGRATION_SYMBOL_MAP_BACKFILL = "symbol_map_backfill_v1"


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
    symbol: str = ""  # "" or "all" applies to every symbol
    channel: str = ""  # "" or "all" applies to every channel (stores channel_id)
    signal_type: str = "all"  # "all" applies to every signal type
    mode: str  # "risk_percent" | "fixed" | "total_lot"
    value: float  # percent for risk_percent, lots for fixed/total_lot


class ExcludedTradeConfig(BaseModel):
    symbol: str
    signal_type: str = "all"  # "all" excludes every signal type for this symbol


class ExcludedChannelAssetConfig(BaseModel):
    channel: str = ""  # "" or "all" = every channel (stores channel_id)
    asset_class: str = ""  # "" or "all" = every asset class


class LotSizingConfig(BaseModel):
    mode: str = "risk_percent"
    risk_percent: float | dict[str, float] = 1.0
    fixed_lot: float | dict[str, float] = 0.01
    # Total lots for a signal, split evenly across its limits (more limits = less per
    # limit = lower risk). Same per-instrument dict form as fixed_lot.
    total_lot: float | dict[str, float] = 0.1
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
    daily_start: str = "15:55"  # cancel pending / block placement 15 min ahead of the SL-strip window
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
    forex_pips: float = 15.0
    forex_jpy_pips: float = 15.0
    metals: float = 25.0
    crypto: float = 1000.0
    oil: float = 1.0
    stocks: float = 5.0
    indices: dict[str, float] = {
        "SPX": 40.0,
        "US500": 40.0,
        "NAS": 100.0,
        "USTEC": 100.0,
        "DAX": 100.0,
        "DE30": 100.0,
        "DE40": 100.0,
        "US30": 100.0,
        "US2000": 20.0,
        "UK100": 50.0,
        "JP225": 200.0,
    }
    stock_overrides: dict[str, float] = {}


class OffsetDriftConfig(BaseModel):
    """Drift thresholds in the instrument's own price units (dollars/points), never
    pips. A still-pending offset order is cancelled for re-placement when its
    broker-vs-feed offset has drifted beyond this since placement. Offset
    instruments are all non-forex, so a pip has no meaning here."""

    indices: dict[str, float] = {
        "SPX": 3.0,
        "US500": 3.0,
        "NAS": 8.0,
        "USTEC": 8.0,
        "DAX": 8.0,
        "DE30": 8.0,
        "US30": 5.0,
        "US2000": 2.0,
        "JP225": 15.0,
    }
    crypto: float = 25.0
    oil: float = 0.15
    metals: float = 2.0
    default: float = 5.0


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
    # Which copy of the bot this is when running several side by side on one machine.
    # Left at 1 (or absent) it behaves exactly like a lone install: single-instance
    # lock "mt5bot.lock" and UI port 8501. Give a *separate* install folder — with its
    # own config.json, orders.db, and mt5_terminal_path — instance_id 2, 3, ... to run
    # concurrently: each instance N takes lock "mt5bot-N.lock" and port 8500+N. Two
    # folders sharing an instance_id still exclude each other (same lock), so the
    # double-open guard holds per instance.
    instance_id: int = 1
    lot_sizing: LotSizingConfig = LotSizingConfig()
    polling: PollingConfig = PollingConfig()
    magic_number: int = 20250001
    symbol_map: dict[str, str] = dict(_DEFAULT_SYMBOL_MAP)
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
    # Per-(channel, asset_class) exclusions. A blank/"all" dimension is a wildcard;
    # a signal is dropped if any rule matches both its channel and its asset class.
    excluded_channel_assets: list[ExcludedChannelAssetConfig] = []
    # Signal types and channel ids that are skipped wholesale (empty = none skipped).
    disabled_signal_types: list[str] = []
    disabled_channels: list[str] = []
    offset_instruments: list[str] = list(DEFAULT_OFFSET_INSTRUMENTS)
    offset_drift: OffsetDriftConfig = OffsetDriftConfig()
    offset_drift_check_interval_seconds: int = 1800
    # Offset is a slow-moving broker-vs-feed property — recompute at most this often
    # per symbol and serve the cached value in between (the feed itself refreshes ~5s).
    offset_recompute_interval_seconds: int = 300
    # Dead-feed bound: while a signal is active the feed refreshes every few seconds,
    # so a stale updated_at means the feed updater has stalled — skip placement past
    # this age.
    feed_max_staleness_seconds: int = 120
    spread_hour: SpreadHourConfig = SpreadHourConfig()
    proximity: ProximityConfig = ProximityConfig()
    # One-time config migrations already applied to this install (see migrate_config).
    config_migrations: list[str] = []
    # Set true once the user accepts the in-app risk disclaimer. Default false (and
    # absent in existing installs' config.json) means the disclaimer still shows, so
    # existing users see it once and acceptance is backfilled by /api/disclaimer/accept.
    disclaimer_accepted: bool = False
    # When true the TP engine never trails or closes — the user owns every exit. The
    # bot still places, cancels, and updates limits, and cancels a signal's remaining
    # pending limits once its filled positions are all closed.
    disable_auto_tp: bool = False
    # When true the bot also reads bot_mode_status.vol_guard (the TM volatility guard,
    # same token format as news_mode) and gates on it exactly like news mode — cancelling
    # matching pending orders and force-closing matching filled positions. Off by default.
    volatility_guard: bool = False
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

    @field_validator("instance_id")
    @classmethod
    def _positive_instance_id(cls, v: int) -> int:
        if v < 1:
            raise ValueError("instance_id must be >= 1")
        return v

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


def migrate_config(path: Path = _CONFIG_PATH) -> None:
    """Apply one-time, idempotent config rewrites that must survive an update. Each
    migration is recorded in `config_migrations` so it runs at most once per install
    — a user who later removes a backfilled symbol keeps it removed. Runs before
    load_config at startup; silently no-ops if config.json is missing or unparseable
    (load_config surfaces those)."""
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return

    applied = data.get("config_migrations")
    if not isinstance(applied, list):
        applied = []

    changed = False
    if _MIGRATION_OFFSET_BACKFILL not in applied:
        offset = data.get("offset_instruments")
        if not isinstance(offset, list):
            offset = list(DEFAULT_OFFSET_INSTRUMENTS)
        for sym in _OFFSET_BACKFILL_SYMBOLS:
            if sym not in offset:
                offset.append(sym)
        data["offset_instruments"] = offset
        applied.append(_MIGRATION_OFFSET_BACKFILL)
        data["config_migrations"] = applied
        changed = True

    if _MIGRATION_PROXIMITY_BUMP not in applied:
        prox = data.get("proximity")
        if isinstance(prox, dict):
            prox["forex_pips"] = 15.0
            prox["forex_jpy_pips"] = 15.0
            prox["metals"] = 25.0
            indices = prox.get("indices")
            if isinstance(indices, dict):
                for sym, value in indices.items():
                    if isinstance(value, (int, float)):
                        indices[sym] = value * 2
            data["proximity"] = prox
        applied.append(_MIGRATION_PROXIMITY_BUMP)
        data["config_migrations"] = applied
        changed = True

    if _MIGRATION_SPREAD_HOUR_LATE not in applied:
        sh = data.get("spread_hour")
        if isinstance(sh, dict):
            sh["daily_start"] = "15:55"
            data["spread_hour"] = sh
        applied.append(_MIGRATION_SPREAD_HOUR_LATE)
        data["config_migrations"] = applied
        changed = True

    if _MIGRATION_SYMBOL_MAP_BACKFILL not in applied:
        offset = data.get("offset_instruments")
        if isinstance(offset, list) and "UK100USD" not in offset:
            offset.append("UK100USD")
            data["offset_instruments"] = offset
        smap = data.get("symbol_map")
        if isinstance(smap, dict):
            for db_sym, mt5_sym in _DEFAULT_SYMBOL_MAP.items():
                smap.setdefault(db_sym, mt5_sym)
            data["symbol_map"] = smap
        applied.append(_MIGRATION_SYMBOL_MAP_BACKFILL)
        data["config_migrations"] = applied
        changed = True

    if changed:
        path.write_text(json.dumps(data, indent=2))
        logger.info("Applied config migration(s): %s", ", ".join(applied))


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


def load_update_manifest_url() -> str:
    # Env override eases testing against a scratch bucket without rebuilding the constant.
    return os.environ.get("MT5BOT_UPDATE_URL") or _PRODUCTION_UPDATE_MANIFEST_URL
