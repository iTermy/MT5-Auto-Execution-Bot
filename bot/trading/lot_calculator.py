import logging
import math

from bot.config.settings import Settings
from bot.mt5.client import MT5Client
from bot.mt5.types import SymbolInfo

logger = logging.getLogger(__name__)


def _pip_size(info: SymbolInfo) -> float:
    # 5-digit and 3-digit instruments: 1 pip = 10 points (e.g. EURUSD, USDJPY)
    # All others: 1 pip = 1 point (metals, indices, crypto)
    return info.point * (10 if info.digits in (3, 5) else 1)


def _pip_value_per_lot(info: SymbolInfo) -> float:
    pip_sz = _pip_size(info)
    return info.trade_tick_value * (pip_sz / info.trade_tick_size)


def _clamp(lot: float, info: SymbolInfo) -> float:
    step = info.volume_step
    # Floor to nearest step (conservative — never over-leverage)
    lot = math.floor(lot / step) * step
    lot = round(lot, 8)
    return min(max(lot, info.volume_min), info.volume_max)


class LotCalculator:
    def __init__(self, mt5_client: MT5Client, config: Settings) -> None:
        self._client = mt5_client
        self._config = config

    def calculate(self, stop_loss: float, limit_prices: list[float], mt5_symbol: str) -> float:
        info = self._client.symbol_info(mt5_symbol)
        if info is None:
            logger.error("symbol_info unavailable for %s, using fixed_lot fallback", mt5_symbol)
            return self._config.lot_sizing.fixed_lot

        if self._config.lot_sizing.mode != "risk_percent":
            return _clamp(self._config.lot_sizing.fixed_lot, info)

        account = self._client.account_info()
        if account is None:
            logger.error("account_info unavailable, using volume_min for %s", mt5_symbol)
            return _clamp(info.volume_min, info)

        pip_sz = _pip_size(info)
        pip_val = _pip_value_per_lot(info)

        if pip_sz <= 0 or pip_val <= 0:
            logger.error("Invalid pip metrics for %s (size=%s val=%s)", mt5_symbol, pip_sz, pip_val)
            return _clamp(info.volume_min, info)

        sl_pips = [abs(price - stop_loss) / pip_sz for price in limit_prices]
        avg_sl_pips = sum(sl_pips) / len(sl_pips)

        if avg_sl_pips <= 0:
            logger.warning("Zero SL distance for %s, using volume_min", mt5_symbol)
            return _clamp(info.volume_min, info)

        raw = (account.balance * self._config.lot_sizing.risk_percent / 100) / (
            len(limit_prices) * avg_sl_pips * pip_val
        )
        capped = min(raw, self._config.lot_sizing.max_lot_per_order)
        return _clamp(capped, info)
