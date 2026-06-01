import json
import logging
from pathlib import Path

from pydantic import BaseModel, ValidationError

from bot.config.constants import _PRODUCTION_DSN, _PRODUCTION_LICENSE_URL

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config.json")


class LotSizingConfig(BaseModel):
    mode: str = "risk_percent"
    risk_percent: float | dict[str, float] = 1.0
    fixed_lot: float | dict[str, float] = 0.01
    max_lot_per_order: float = 5.0


class PollingConfig(BaseModel):
    supabase_interval_seconds: int = 30
    tp_active_interval_seconds: int = 1
    tp_trailing_interval_seconds: int = 2
    license_heartbeat_seconds: int = 900


class SpreadHourConfig(BaseModel):
    daily_start: str = "16:45"
    daily_end: str = "18:00"
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
        "JP225": 100.0,
    }
    stock_overrides: dict[str, float] = {}


class AssetTPConfig(BaseModel):
    profit_threshold: float
    threshold_unit: str
    trailing_distance: float


class ScalpOverrideConfig(BaseModel):
    profit_threshold: float
    trailing_distance: float


class OneToOneConfig(BaseModel):
    profit_threshold: float = 10.0          # global default in account dollars
    overrides: dict[str, float] = {}        # per asset_class override (dollars)


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
    }
    stock_suffix: str = "-24"
    stock_no_suffix: list[str] = []
    excluded_symbols: list[str] = []
    offset_instruments: list[str] = ["SPX500USD", "NAS100USD", "BTCUSDT", "ETHUSDT"]
    offset_drift_threshold_pips: float = 5.0
    feed_max_staleness_seconds: int = 30
    spread_hour: SpreadHourConfig = SpreadHourConfig()
    proximity: ProximityConfig = ProximityConfig()
    tp_config: TPConfig


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
