from dataclasses import dataclass

from bot.config.constants import AssetClass
from bot.config.settings import Settings

_OVERRIDE_FIELDS = frozenset(
    {"profit_threshold", "trailing_distance", "threshold_unit", "partial_close_percent"}
)


@dataclass
class AssetClassConfig:
    profit_threshold: float
    threshold_unit: str  # "pips" or "dollars"
    partial_close_percent: int
    trailing_distance: float


def _resolve_instrument_override(inst: dict, signal_type: str) -> dict | None:
    """Pick the right override dict for this signal_type from an instrument entry.

    Flat form (all signal types):  {"profit_threshold": ..., "trailing_distance": ...}
    Nested form (per signal_type): {"scalp": {...}, "swing": {...}, "default": {...}}

    Detection: if any override field key (profit_threshold etc.) sits at the top
    level, it's flat. Otherwise nested — try the signal_type key first, then "default".
    """
    if not inst:
        return None
    if any(k in inst for k in _OVERRIDE_FIELDS):
        return inst
    if signal_type in inst and isinstance(inst[signal_type], dict):
        return inst[signal_type]
    if "default" in inst and isinstance(inst["default"], dict):
        return inst["default"]
    return None


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
    # Per-asset partial close, falling back to the top-level default
    partial_close_percent = getattr(base, "partial_close_percent", None)
    if partial_close_percent is None:
        partial_close_percent = tp.partial_close_percent

    if signal_type == "1-1":
        # Fixed dollar TP, full close, no trailing
        profit_threshold = tp.one_to_one.overrides.get(key, tp.one_to_one.profit_threshold)
        threshold_unit = "dollars"
        partial_close_percent = 100
        trailing_distance = 0.0
    elif signal_type == "risky":
        # Dedicated config: dollar threshold with normal trailing/partial close. Its own
        # base (not the asset-class base) so gold risky defaults to $4, and an optional
        # per-asset-class override.
        risky = tp.risky
        profit_threshold = risky.profit_threshold
        threshold_unit = risky.threshold_unit
        trailing_distance = risky.trailing_distance
        partial_close_percent = risky.partial_close_percent
        ov = risky.overrides.get(key)
        if ov is not None:
            profit_threshold = ov.profit_threshold
            trailing_distance = ov.trailing_distance
            if ov.partial_close_percent is not None:
                partial_close_percent = ov.partial_close_percent
    else:
        override_map = {
            "scalp": tp.scalp_overrides,
            "toll": tp.toll_overrides,
            "swing": tp.swing_overrides,
            "pa": tp.pa_overrides,
        }.get(signal_type)
        if override_map and key in override_map:
            ov = override_map[key]
            profit_threshold = ov.profit_threshold
            trailing_distance = ov.trailing_distance
            if ov.partial_close_percent is not None:
                partial_close_percent = ov.partial_close_percent
        elif signal_type == "swing":
            # No swing override configured — default to 3× the standard threshold
            profit_threshold = base.profit_threshold * 3
        # scalp/toll/pa with no override fall through to base asset-class config

    if instrument and instrument in tp.instrument_overrides:
        inst_override = _resolve_instrument_override(
            tp.instrument_overrides[instrument], signal_type
        )
        if inst_override:
            profit_threshold = inst_override.get("profit_threshold", profit_threshold)
            trailing_distance = inst_override.get("trailing_distance", trailing_distance)
            threshold_unit = inst_override.get("threshold_unit", threshold_unit)
            partial_close_percent = inst_override.get(
                "partial_close_percent", partial_close_percent
            )

    return AssetClassConfig(
        profit_threshold=profit_threshold,
        threshold_unit=threshold_unit,
        partial_close_percent=partial_close_percent,
        trailing_distance=trailing_distance,
    )
