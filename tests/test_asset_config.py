from bot.config.constants import AssetClass
from bot.tp.asset_config import get_config
from tests.conftest import make_settings


def _settings_with_overrides(instrument_overrides: dict):
    return make_settings(
        tp_config=make_settings().tp_config.model_copy(
            update={"instrument_overrides": instrument_overrides}
        )
    )


def test_no_instrument_override_uses_asset_class_default() -> None:
    cfg = _settings_with_overrides({})
    out = get_config(AssetClass.INDICES, "standard", cfg, instrument="SPX500USD")
    assert out.profit_threshold == 20.0  # indices default
    assert out.trailing_distance == 5.0


def test_flat_override_applies_to_all_signal_types() -> None:
    cfg = _settings_with_overrides(
        {"SPX500USD": {"profit_threshold": 15.0, "trailing_distance": 4.0}}
    )
    # Standard uses the override
    std = get_config(AssetClass.INDICES, "standard", cfg, instrument="SPX500USD")
    assert std.profit_threshold == 15.0
    assert std.trailing_distance == 4.0
    # Scalp inherits the same flat override (no per-type breakout)
    sc = get_config(AssetClass.INDICES, "scalp", cfg, instrument="SPX500USD")
    assert sc.profit_threshold == 15.0
    assert sc.trailing_distance == 4.0


def test_nested_override_picks_signal_type_block() -> None:
    cfg = _settings_with_overrides(
        {
            "NAS100USD": {
                "default": {"profit_threshold": 50.0, "trailing_distance": 15.0},
                "scalp": {"profit_threshold": 30.0, "trailing_distance": 8.0},
                "swing": {"profit_threshold": 150.0, "trailing_distance": 40.0},
            }
        }
    )
    std = get_config(AssetClass.INDICES, "standard", cfg, instrument="NAS100USD")
    assert std.profit_threshold == 50.0  # default block
    assert std.trailing_distance == 15.0

    sc = get_config(AssetClass.INDICES, "scalp", cfg, instrument="NAS100USD")
    assert sc.profit_threshold == 30.0  # scalp block
    assert sc.trailing_distance == 8.0

    sw = get_config(AssetClass.INDICES, "swing", cfg, instrument="NAS100USD")
    assert sw.profit_threshold == 150.0
    assert sw.trailing_distance == 40.0


def test_nested_override_falls_back_to_default_for_missing_type() -> None:
    cfg = _settings_with_overrides(
        {"NAS100USD": {"default": {"profit_threshold": 50.0}, "scalp": {"profit_threshold": 30.0}}}
    )
    # toll not listed — falls back to "default" block
    toll = get_config(AssetClass.INDICES, "toll", cfg, instrument="NAS100USD")
    assert toll.profit_threshold == 50.0


def test_nested_override_no_default_and_no_match_leaves_asset_class_value() -> None:
    cfg = _settings_with_overrides(
        {"NAS100USD": {"scalp": {"profit_threshold": 30.0}}}  # no "default", no "standard"
    )
    std = get_config(AssetClass.INDICES, "standard", cfg, instrument="NAS100USD")
    # No applicable override — falls through to indices default
    assert std.profit_threshold == 20.0


def test_nested_override_supports_partial_field_overrides() -> None:
    # Per-type block can override just profit_threshold; trailing_distance keeps
    # the value resolved earlier in the chain (asset-class default).
    cfg = _settings_with_overrides({"NAS100USD": {"scalp": {"profit_threshold": 30.0}}})
    sc = get_config(AssetClass.INDICES, "scalp", cfg, instrument="NAS100USD")
    assert sc.profit_threshold == 30.0
    assert sc.trailing_distance == 5.0  # indices default, not overridden
