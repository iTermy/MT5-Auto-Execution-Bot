import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from bot.config.constants import _PRODUCTION_DSN, _PRODUCTION_LICENSE_URL

load_dotenv()

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path("config.json")


class LotSizingConfig(BaseModel):
    mode: str = "risk_percent"
    risk_percent: float = 1.0
    fixed_lot: float = 0.01
    max_lot_per_order: float = 5.0


class PollingConfig(BaseModel):
    supabase_interval_seconds: int = 30
    tp_active_interval_seconds: int = 1
    license_heartbeat_seconds: int = 900


class SpreadHourConfig(BaseModel):
    daily_start: str = "16:45"
    daily_end: str = "18:00"
    timezone: str = "US/Eastern"
    weekend_start_day: str = "Friday"
    weekend_end_day: str = "Sunday"


class AssetTPConfig(BaseModel):
    profit_threshold: float
    threshold_unit: str
    trailing_distance: float


class ScalpOverrideConfig(BaseModel):
    profit_threshold: float
    trailing_distance: float


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
    instrument_overrides: dict[str, dict] = {}


class Settings(BaseModel):
    license_key: str = ""
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
    return os.getenv("SUPABASE_DSN") or _PRODUCTION_DSN


def load_license_url() -> str:
    return os.getenv("LICENSE_API_URL") or _PRODUCTION_LICENSE_URL
