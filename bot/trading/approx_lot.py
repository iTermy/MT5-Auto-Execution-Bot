from dataclasses import dataclass

from bot.config.settings import Settings
from bot.mt5.types import SymbolInfo
from bot.trading.lot_calculator import _clamp, _pip_value_per_lot, price_distance_to_money
from bot.trading.symbol_mapper import map_symbol

# Target average risk per signal as a percent of account balance. The approximation
# sizes each instrument so a median-shaped signal risks roughly this much; signals
# with more limits or wider stops risk more, fewer/tighter risk less.
_TARGET_RISK_PCT = 3.0

# Median cumulative stop-loss distance per instrument, in the instrument's own price
# units (sum of |limit - SL| across a signal's limits). From signal-history analysis.
# Keyed by DB instrument; mapped to the broker symbol at compute time.
_INSTRUMENT_MEDIANS: dict[str, float] = {
    "XAUUSD": 25.00,
    "SPX500USD": 52.50,
    "NAS100USD": 826.00,
    "USOILSPOT": 3.47,
    "BTCUSDT": 4485.00,
    "JP225": 1565.00,
    "GCQ26": 59.00,
    "DE30EUR": 1058.50,
    "US30USD": 431.00,
}

# Forex is aggregated across all pairs as a single median cumulative SL in pips; it's
# applied per common pair using that pair's own pip value, so each pair lands near the
# same money risk despite differing pip values (JPY/cross pairs included).
_FOREX_MEDIAN_PIPS = 90.20
_FOREX_PAIRS = [
    "EURUSD",
    "GBPUSD",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    "USDCHF",
    "USDJPY",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
    "CADJPY",
    "CHFJPY",
    "NZDJPY",
    "EURGBP",
    "EURAUD",
    "EURCAD",
    "EURCHF",
    "GBPAUD",
    "GBPCAD",
    "AUDCAD",
    "AUDNZD",
]


@dataclass
class LotRecommendation:
    symbol: str  # broker (MT5) symbol
    signal_type: str
    mode: str
    value: float


def target_db_symbols() -> list[str]:
    """DB instruments the approximation needs broker specs for, so the engine can
    pre-cache their SymbolInfo off the request path."""
    return list(_INSTRUMENT_MEDIANS) + _FOREX_PAIRS


def compute_recommendations(
    config: Settings,
    balance: float,
    specs: dict[str, SymbolInfo],
    max_lot: float,
) -> list[LotRecommendation]:
    """Fixed-lot-per-limit values that put a median-shaped signal at ~3% account risk.
    `specs` maps broker symbol -> SymbolInfo; symbols the broker doesn't carry are
    skipped. Lots are floored to the broker volume step and capped at max_lot."""
    risk_money = balance * _TARGET_RISK_PCT / 100
    out: list[LotRecommendation] = []

    for db, median in _INSTRUMENT_MEDIANS.items():
        mt5_sym = map_symbol(db, config)
        info = specs.get(mt5_sym)
        if info is None:
            continue
        # Money risked per lot for this signal = money-per-price-unit * cumulative SL.
        money_per_unit = price_distance_to_money(info, 1.0, 1.0)
        if not money_per_unit or median <= 0:
            continue
        lot = _clamp(min(risk_money / (money_per_unit * median), max_lot), info)
        if lot > 0:
            out.append(LotRecommendation(mt5_sym, "all", "fixed", lot))

    for db in _FOREX_PAIRS:
        mt5_sym = map_symbol(db, config)
        info = specs.get(mt5_sym)
        if info is None:
            continue
        pip_val = _pip_value_per_lot(info)
        if pip_val <= 0:
            continue
        lot = _clamp(min(risk_money / (pip_val * _FOREX_MEDIAN_PIPS), max_lot), info)
        if lot > 0:
            out.append(LotRecommendation(mt5_sym, "all", "fixed", lot))

    return out
