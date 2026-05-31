from dataclasses import dataclass

from bot.config.constants import AssetClass
from bot.config.settings import Settings


@dataclass
class AssetClassConfig:
    profit_threshold: float
    threshold_unit: str  # "pips" or "dollars"
    partial_close_percent: int
    trailing_distance: float


def get_config(
    asset_class: AssetClass,
    signal_type: str,
    config: Settings,
    instrument: str | None = None,
) -> AssetClassConfig:
    tp = config.tp_config
    key = asset_class.value
    base = getattr(tp, key)

    profit_threshold = base.profit_threshold
    trailing_distance = base.trailing_distance
    threshold_unit = base.threshold_unit
    partial_close_percent = tp.partial_close_percent

    if signal_type == "1-1":
        # Fixed dollar TP, full close, no trailing
        profit_threshold = tp.one_to_one.overrides.get(key, tp.one_to_one.profit_threshold)
        threshold_unit = "dollars"
        partial_close_percent = 100
        trailing_distance = 0.0
    else:
        override_map = {
            "scalp": tp.scalp_overrides,
            "toll":  tp.toll_overrides,
            "swing": tp.swing_overrides,
            "pa":    tp.pa_overrides,
        }.get(signal_type)
        if override_map and key in override_map:
            ov = override_map[key]
            profit_threshold = ov.profit_threshold
            trailing_distance = ov.trailing_distance
        elif signal_type == "swing":
            # No swing override configured — default to 3× the standard threshold
            profit_threshold = base.profit_threshold * 3
        # scalp/toll/pa with no override fall through to base asset-class config

    if instrument and instrument in tp.instrument_overrides:
        inst = tp.instrument_overrides[instrument]
        profit_threshold = inst.get("profit_threshold", profit_threshold)
        trailing_distance = inst.get("trailing_distance", trailing_distance)
        threshold_unit = inst.get("threshold_unit", threshold_unit)
        partial_close_percent = inst.get("partial_close_percent", partial_close_percent)

    return AssetClassConfig(
        profit_threshold=profit_threshold,
        threshold_unit=threshold_unit,
        partial_close_percent=partial_close_percent,
        trailing_distance=trailing_distance,
    )
