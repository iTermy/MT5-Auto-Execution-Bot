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
    is_scalp: bool,
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

    if is_scalp and key in tp.scalp_overrides:
        ov = tp.scalp_overrides[key]
        profit_threshold = ov.profit_threshold
        trailing_distance = ov.trailing_distance

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
