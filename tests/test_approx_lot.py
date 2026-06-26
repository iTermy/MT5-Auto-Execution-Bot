import pytest

from bot.trading.approx_lot import compute_recommendations
from tests.conftest import make_settings, make_symbol_info


def _gold_info(**overrides):
    # XAUUSD: money-per-$1-move-per-lot = tick_value/tick_size = 1.0/0.01 = 100
    defaults = dict(
        name="XAUUSD",
        digits=2,
        point=0.01,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_tick_value=1.0,
        trade_tick_size=0.01,
        trade_contract_size=100.0,
    )
    defaults.update(overrides)
    return make_symbol_info(**defaults)


# make_settings() has no symbol_map/suffix rules, so map_symbol is identity here —
# spec keys are the DB symbols themselves.


def test_gold_sized_to_target_risk() -> None:
    # balance=10000 → 3% = 300 risk. Gold median cumulative SL = 25 price units.
    # lot = 300 / (100 * 25) = 0.12 → exactly 3% per a median signal.
    cfg = make_settings()
    recs = compute_recommendations(cfg, 10000.0, {"XAUUSD": _gold_info()}, max_lot=5.0)

    gold = next(r for r in recs if r.symbol == "XAUUSD")
    assert gold.mode == "fixed"
    assert gold.signal_type == "all"
    assert gold.value == pytest.approx(0.12, abs=1e-9)


def test_forex_uses_pip_value_and_pip_median() -> None:
    # EURUSD default: pip_val=10. Forex median = 90.2 pips.
    # lot = 300 / (10 * 90.2) = 0.3326 → floored to step 0.01 → 0.33.
    cfg = make_settings()
    recs = compute_recommendations(cfg, 10000.0, {"EURUSD": make_symbol_info()}, max_lot=5.0)

    eur = next(r for r in recs if r.symbol == "EURUSD")
    assert eur.value == pytest.approx(0.33, abs=1e-9)


def test_symbols_without_specs_are_skipped() -> None:
    # Only Gold + EURUSD specs provided → only those two come back.
    cfg = make_settings()
    specs = {"XAUUSD": _gold_info(), "EURUSD": make_symbol_info()}
    recs = compute_recommendations(cfg, 10000.0, specs, max_lot=5.0)

    assert {r.symbol for r in recs} == {"XAUUSD", "EURUSD"}


def test_max_lot_caps_the_value() -> None:
    cfg = make_settings()
    recs = compute_recommendations(cfg, 10000.0, {"XAUUSD": _gold_info()}, max_lot=0.1)

    gold = next(r for r in recs if r.symbol == "XAUUSD")
    assert gold.value == pytest.approx(0.1, abs=1e-9)


def test_tiny_target_clamps_up_to_volume_min() -> None:
    # balance=100 → 3% = 3. lot = 3 / (100*25) = 0.0012 → floors below step, clamps to min.
    cfg = make_settings()
    recs = compute_recommendations(cfg, 100.0, {"XAUUSD": _gold_info()}, max_lot=5.0)

    gold = next(r for r in recs if r.symbol == "XAUUSD")
    assert gold.value == pytest.approx(0.01, abs=1e-9)


def test_unusable_tick_metadata_is_skipped() -> None:
    cfg = make_settings()
    recs = compute_recommendations(
        cfg, 10000.0, {"XAUUSD": _gold_info(trade_tick_size=0.0)}, max_lot=5.0
    )

    assert recs == []
