import logging
import math

from bot.config.settings import LotExceptionConfig, Settings
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


def price_distance_to_money(info: SymbolInfo, distance: float, volume: float) -> float | None:
    """Convert a price distance into account-currency money for `volume` lots.
    Returns None when the symbol's tick metadata is unusable."""
    if info.trade_tick_size <= 0:
        return None
    return abs(distance) * (info.trade_tick_value / info.trade_tick_size) * volume


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

    def _get_fixed_lot(self, mt5_symbol: str) -> float:
        fl = self._config.lot_sizing.fixed_lot
        if isinstance(fl, dict):
            return fl.get(mt5_symbol) or fl.get("default") or 0.01
        return float(fl)

    def _get_risk_percent(self, mt5_symbol: str) -> float:
        rp = self._config.lot_sizing.risk_percent
        if isinstance(rp, dict):
            return rp.get(mt5_symbol) or rp.get("default") or 1.0
        return float(rp)

    def _resolve_exception(self, mt5_symbol: str, signal_type: str) -> LotExceptionConfig | None:
        # A signal-type-specific exception beats an "all" one for the same symbol.
        exact: LotExceptionConfig | None = None
        fallback: LotExceptionConfig | None = None
        for ex in self._config.lot_sizing.exceptions:
            if ex.symbol != mt5_symbol:
                continue
            if ex.signal_type == signal_type:
                exact = ex
            elif ex.signal_type == "all":
                fallback = ex
        return exact or fallback

    def calculate(
        self,
        stop_loss: float,
        limit_prices: list[float],
        mt5_symbol: str,
        signal_type: str = "all",
    ) -> float:
        info = self._client.symbol_info(mt5_symbol)
        if info is None:
            logger.error("symbol_info unavailable for %s, using fixed_lot fallback", mt5_symbol)
            return self._get_fixed_lot(mt5_symbol)

        # Per-symbol exception takes precedence over the global mode.
        exception = self._resolve_exception(mt5_symbol, signal_type)
        if exception is not None:
            if exception.mode == "fixed":
                return _clamp(exception.value, info)
            return self._calc_risk_lot(exception.value, info, stop_loss, limit_prices, mt5_symbol)

        if self._config.lot_sizing.mode != "risk_percent":
            return _clamp(self._get_fixed_lot(mt5_symbol), info)

        return self._calc_risk_lot(
            self._get_risk_percent(mt5_symbol), info, stop_loss, limit_prices, mt5_symbol
        )

    def _calc_risk_lot(
        self,
        risk_percent: float,
        info: SymbolInfo,
        stop_loss: float,
        limit_prices: list[float],
        mt5_symbol: str,
    ) -> float:
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

        raw = (account.balance * risk_percent / 100) / (len(limit_prices) * avg_sl_pips * pip_val)
        capped = min(raw, self._config.lot_sizing.max_lot_per_order)
        return _clamp(capped, info)
