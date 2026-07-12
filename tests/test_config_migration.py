import json

from bot.config.settings import (
    _CRYPTO_PROXIMITY_OVERRIDES,
    _MIGRATION_CRYPTO_PROXIMITY,
    _MIGRATION_INDEX_F40,
    _MIGRATION_LIVE_PRICE_INTERVAL,
    _MIGRATION_OFFSET_BACKFILL,
    _MIGRATION_PROFIT_DEFAULTS,
    _MIGRATION_PROXIMITY_BUMP,
    _MIGRATION_RISKY_GOLD_DISABLED,
    _MIGRATION_SPREAD_HOUR_LATE,
    _MIGRATION_STOCK_PROXIMITY,
    _MIGRATION_STOCK_SPREAD_EARLY,
    _MIGRATION_SYMBOL_MAP_BACKFILL,
    _OFFSET_BACKFILL_SYMBOLS,
    _RISKY_GOLD_CHANNEL_ID,
    _STOCK_PROXIMITY_OVERRIDES,
    migrate_config,
)


def _write(path, data: dict) -> None:
    path.write_text(json.dumps(data))


def _read(path) -> dict:
    return json.loads(path.read_text())


def test_backfill_adds_missing_offset_symbols(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"offset_instruments": ["SPX500USD"]})

    migrate_config(cfg)

    data = _read(cfg)
    for sym in _OFFSET_BACKFILL_SYMBOLS:
        assert sym in data["offset_instruments"]
    assert "SPX500USD" in data["offset_instruments"]  # existing entries preserved
    assert _MIGRATION_OFFSET_BACKFILL in data["config_migrations"]


def test_backfill_is_idempotent_and_respects_removal(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"offset_instruments": ["SPX500USD"]})
    migrate_config(cfg)

    # User removes a backfilled symbol after the one-time migration.
    data = _read(cfg)
    data["offset_instruments"].remove("USOILSPOT")
    _write(cfg, data)

    # Re-running must NOT re-add it — the marker records the migration already ran.
    migrate_config(cfg)
    assert "USOILSPOT" not in _read(cfg)["offset_instruments"]


def test_backfill_no_duplicate_when_already_present(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"offset_instruments": list(_OFFSET_BACKFILL_SYMBOLS)})

    migrate_config(cfg)

    offset = _read(cfg)["offset_instruments"]
    for sym in _OFFSET_BACKFILL_SYMBOLS:
        assert offset.count(sym) == 1


def test_backfill_seeds_offset_when_key_absent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {})

    migrate_config(cfg)

    offset = _read(cfg)["offset_instruments"]
    for sym in _OFFSET_BACKFILL_SYMBOLS:
        assert sym in offset


def test_proximity_bump_sets_forex_metals_and_doubles_indices(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(
        cfg,
        {
            "proximity": {
                "forex_pips": 10.0,
                "forex_jpy_pips": 10.0,
                "metals": 15.0,
                "indices": {"SPX": 20.0, "NAS": 50.0, "CUSTOM": 7.0},
            }
        },
    )

    migrate_config(cfg)

    prox = _read(cfg)["proximity"]
    assert prox["forex_pips"] == 15.0
    assert prox["forex_jpy_pips"] == 15.0
    assert prox["metals"] == 25.0
    # F40 is also backfilled (its migration runs in the same pass).
    assert prox["indices"] == {"SPX": 40.0, "NAS": 100.0, "CUSTOM": 14.0, "F40": 40.0}
    assert _MIGRATION_PROXIMITY_BUMP in _read(cfg)["config_migrations"]


def test_proximity_bump_is_idempotent_and_respects_retuning(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"proximity": {"forex_pips": 10.0, "indices": {"SPX": 20.0}}})
    migrate_config(cfg)

    # User re-tunes after the one-time migration.
    data = _read(cfg)
    data["proximity"]["forex_pips"] = 8.0
    data["proximity"]["indices"]["SPX"] = 12.0
    _write(cfg, data)

    migrate_config(cfg)
    prox = _read(cfg)["proximity"]
    assert prox["forex_pips"] == 8.0  # not re-applied
    assert prox["indices"]["SPX"] == 12.0  # not re-doubled


def test_proximity_bump_noop_when_key_absent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {})

    migrate_config(cfg)

    # No proximity block to migrate — new defaults apply at load — but the marker is
    # still recorded so it never runs against a later-added custom block.
    data = _read(cfg)
    assert "proximity" not in data
    assert _MIGRATION_PROXIMITY_BUMP in data["config_migrations"]


def test_spread_hour_late_moves_daily_start(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"spread_hour": {"daily_start": "16:45", "daily_end": "18:00"}})

    migrate_config(cfg)

    sh = _read(cfg)["spread_hour"]
    assert sh["daily_start"] == "15:55"
    assert sh["daily_end"] == "18:00"  # other keys untouched
    assert _MIGRATION_SPREAD_HOUR_LATE in _read(cfg)["config_migrations"]


def test_spread_hour_late_is_idempotent_and_respects_retuning(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"spread_hour": {"daily_start": "16:45"}})
    migrate_config(cfg)

    # User re-tunes after the one-time migration.
    data = _read(cfg)
    data["spread_hour"]["daily_start"] = "16:30"
    _write(cfg, data)

    migrate_config(cfg)
    assert _read(cfg)["spread_hour"]["daily_start"] == "16:30"  # not re-applied


def test_spread_hour_late_noop_when_key_absent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {})

    migrate_config(cfg)

    data = _read(cfg)
    assert "spread_hour" not in data  # new default (15:55) applies at load
    assert _MIGRATION_SPREAD_HOUR_LATE in data["config_migrations"]


def test_stock_spread_hour_early_moves_both_stock_starts(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(
        cfg,
        {"spread_hour": {"stock_daily_start": "15:45", "sl_strip_stock_start": "15:55"}},
    )

    migrate_config(cfg)

    sh = _read(cfg)["spread_hour"]
    assert sh["stock_daily_start"] == "15:40"
    assert sh["sl_strip_stock_start"] == "15:40"
    assert _MIGRATION_STOCK_SPREAD_EARLY in _read(cfg)["config_migrations"]


def test_stock_spread_hour_early_is_idempotent_and_respects_retuning(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"spread_hour": {"sl_strip_stock_start": "15:55"}})
    migrate_config(cfg)

    # User re-tunes after the one-time migration.
    data = _read(cfg)
    data["spread_hour"]["sl_strip_stock_start"] = "15:50"
    _write(cfg, data)

    migrate_config(cfg)
    assert _read(cfg)["spread_hour"]["sl_strip_stock_start"] == "15:50"  # not re-applied


def test_symbol_map_backfill_adds_uk100_offset_and_default_maps(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"offset_instruments": ["SPX500USD"], "symbol_map": {"SPX500USD": "US500"}})

    migrate_config(cfg)

    data = _read(cfg)
    assert "UK100USD" in data["offset_instruments"]
    # Every missing default map is backfilled, not just the indices.
    assert data["symbol_map"]["UK100USD"] == "UK100"
    assert data["symbol_map"]["DE30EUR"] == "DE40"
    assert data["symbol_map"]["USOILSPOT"] == "XTIUSD"
    assert data["symbol_map"]["BTCUSDT"] == "BTCUSD"
    assert _MIGRATION_SYMBOL_MAP_BACKFILL in data["config_migrations"]


def test_symbol_map_backfill_preserves_existing_maps(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    # User already re-mapped some symbols to their broker's names.
    _write(
        cfg,
        {"offset_instruments": ["DE30EUR"], "symbol_map": {"DE30EUR": "GER40", "UK100USD": "FTSE"}},
    )

    migrate_config(cfg)

    smap = _read(cfg)["symbol_map"]
    assert smap["DE30EUR"] == "GER40"  # custom map not forced to DE40
    assert smap["UK100USD"] == "FTSE"  # custom map not forced to UK100
    assert smap["USOILSPOT"] == "XTIUSD"  # absent one still backfilled


def test_symbol_map_backfill_is_idempotent_and_respects_removal(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"offset_instruments": ["SPX500USD"], "symbol_map": {}})
    migrate_config(cfg)

    # User removes the UK100 offset row after the one-time migration.
    data = _read(cfg)
    data["offset_instruments"].remove("UK100USD")
    _write(cfg, data)

    migrate_config(cfg)
    assert "UK100USD" not in _read(cfg)["offset_instruments"]  # not re-added


def test_risky_gold_channel_disabled_by_default(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"disabled_channels": ["1512881096650391582"]})

    migrate_config(cfg)

    data = _read(cfg)
    assert _RISKY_GOLD_CHANNEL_ID in data["disabled_channels"]
    assert "1512881096650391582" in data["disabled_channels"]  # existing entries preserved
    assert _MIGRATION_RISKY_GOLD_DISABLED in data["config_migrations"]


def test_risky_gold_disable_seeds_list_when_key_absent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {})

    migrate_config(cfg)

    assert _read(cfg)["disabled_channels"] == [_RISKY_GOLD_CHANNEL_ID]


def test_risky_gold_disable_is_idempotent_and_respects_reenable(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {})
    migrate_config(cfg)

    # User re-enables the channel after the one-time migration.
    data = _read(cfg)
    data["disabled_channels"].remove(_RISKY_GOLD_CHANNEL_ID)
    _write(cfg, data)

    migrate_config(cfg)
    assert _RISKY_GOLD_CHANNEL_ID not in _read(cfg)["disabled_channels"]  # not re-added


def test_stock_proximity_replaces_bare_keys_with_canonical(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    # Old shipped set: sparse bare tickers that would shadow full-symbol keys.
    _write(cfg, {"proximity": {"stocks": 5.0, "stock_overrides": {"AAPL": 0.64, "MU": 1.0}}})

    migrate_config(cfg)

    overrides = _read(cfg)["proximity"]["stock_overrides"]
    assert overrides == _STOCK_PROXIMITY_OVERRIDES  # bare keys dropped, canonical applied
    assert "AAPL" not in overrides  # old bare key gone (would shadow "AAPL.NAS")
    assert overrides["AAPL.NAS"] == 2.0
    assert overrides["GOOGL.NAS"] == 5.0  # real traded symbol covered alongside GOOG.NAS
    assert _MIGRATION_STOCK_PROXIMITY in _read(cfg)["config_migrations"]


def test_stock_proximity_preserves_custom_full_symbol_keys(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"proximity": {"stock_overrides": {"AAPL": 0.64, "SMCI.NAS": 3.3}}})

    migrate_config(cfg)

    overrides = _read(cfg)["proximity"]["stock_overrides"]
    assert overrides["SMCI.NAS"] == 3.3  # user's custom full-symbol override kept
    assert "AAPL" not in overrides  # bare key still dropped


def test_stock_proximity_is_idempotent_and_respects_retuning(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"proximity": {"stock_overrides": {"AAPL": 0.64}}})
    migrate_config(cfg)

    # User re-tunes after the one-time migration.
    data = _read(cfg)
    data["proximity"]["stock_overrides"]["AAPL.NAS"] = 3.5
    _write(cfg, data)

    migrate_config(cfg)
    assert _read(cfg)["proximity"]["stock_overrides"]["AAPL.NAS"] == 3.5  # not re-applied


def test_stock_proximity_noop_when_proximity_absent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {})

    migrate_config(cfg)

    data = _read(cfg)
    assert "proximity" not in data  # new default applies at load
    assert _MIGRATION_STOCK_PROXIMITY in data["config_migrations"]


def test_index_f40_backfilled_when_absent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    # Pre-apply the index-doubling bump so it doesn't skew this migration's assertions.
    _write(
        cfg,
        {"config_migrations": [_MIGRATION_PROXIMITY_BUMP], "proximity": {"indices": {"SPX": 40.0}}},
    )

    migrate_config(cfg)

    indices = _read(cfg)["proximity"]["indices"]
    assert indices["F40"] == 40.0
    assert indices["SPX"] == 40.0  # existing entries preserved
    assert _MIGRATION_INDEX_F40 in _read(cfg)["config_migrations"]


def test_index_f40_respects_existing_value(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(
        cfg,
        {"config_migrations": [_MIGRATION_PROXIMITY_BUMP], "proximity": {"indices": {"F40": 60.0}}},
    )

    migrate_config(cfg)

    assert _read(cfg)["proximity"]["indices"]["F40"] == 60.0  # user's value not overwritten


def test_live_price_interval_bumped_from_pinned_default(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"polling": {"live_price_interval_seconds": 2}})

    migrate_config(cfg)

    assert _read(cfg)["polling"]["live_price_interval_seconds"] == 5
    assert _MIGRATION_LIVE_PRICE_INTERVAL in _read(cfg)["config_migrations"]


def test_live_price_interval_respects_custom_value(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"polling": {"live_price_interval_seconds": 10}})

    migrate_config(cfg)

    assert _read(cfg)["polling"]["live_price_interval_seconds"] == 10  # user's value untouched


def test_live_price_interval_is_idempotent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"polling": {"live_price_interval_seconds": 2}})
    migrate_config(cfg)

    # User later drops back to 2 after the one-time migration — must not be re-bumped.
    data = _read(cfg)
    data["polling"]["live_price_interval_seconds"] = 2
    _write(cfg, data)
    migrate_config(cfg)
    assert _read(cfg)["polling"]["live_price_interval_seconds"] == 2


def test_crypto_proximity_seeds_eth_when_absent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"proximity": {"crypto": 1000.0}})

    migrate_config(cfg)

    overrides = _read(cfg)["proximity"]["crypto_overrides"]
    assert overrides["ETHUSDT"] == _CRYPTO_PROXIMITY_OVERRIDES["ETHUSDT"]
    assert _MIGRATION_CRYPTO_PROXIMITY in _read(cfg)["config_migrations"]


def test_crypto_proximity_respects_existing_value(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"proximity": {"crypto_overrides": {"ETHUSDT": 25.0}}})

    migrate_config(cfg)

    assert _read(cfg)["proximity"]["crypto_overrides"]["ETHUSDT"] == 25.0  # not overwritten


def test_crypto_proximity_is_idempotent_and_respects_removal(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"proximity": {"crypto": 1000.0}})
    migrate_config(cfg)

    # User removes the seeded ETH override after the one-time migration.
    data = _read(cfg)
    del data["proximity"]["crypto_overrides"]["ETHUSDT"]
    _write(cfg, data)

    migrate_config(cfg)
    assert "ETHUSDT" not in _read(cfg)["proximity"]["crypto_overrides"]  # not re-seeded


def test_missing_file_is_noop(tmp_path) -> None:
    cfg = tmp_path / "does_not_exist.json"
    migrate_config(cfg)  # must not raise
    assert not cfg.exists()


def test_profit_defaults_adds_skip_limits_and_flips_default_partials(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(
        cfg,
        {
            "lot_sizing": {"mode": "risk_percent", "risk_percent": 5.0},
            "tp_config": {
                "partial_close_percent": 50,
                "metals": {
                    "profit_threshold": 5.0,
                    "threshold_unit": "dollars",
                    "trailing_distance": 3.0,
                    "partial_close_percent": 75,
                },
                "forex": {
                    "profit_threshold": 10.0,
                    "threshold_unit": "pips",
                    "trailing_distance": 7.0,
                    "partial_close_percent": 33,
                },
                "toll_overrides": {
                    "metals": {
                        "profit_threshold": 5.0,
                        "trailing_distance": 3.0,
                        "partial_close_percent": 75,
                    }
                },
            },
        },
    )

    migrate_config(cfg)

    data = _read(cfg)
    assert data["lot_sizing"]["skip_limits_at"] == 6
    tp = data["tp_config"]
    assert tp["partial_close_percent"] == 0  # old default 50 flipped
    assert tp["metals"]["partial_close_percent"] == 0  # old default 75 flipped
    assert tp["forex"]["partial_close_percent"] == 33  # user-customized value preserved
    assert tp["toll_overrides"]["metals"]["partial_close_percent"] == 0  # nested flip
    assert _MIGRATION_PROFIT_DEFAULTS in data["config_migrations"]


def test_profit_defaults_respects_explicit_skip_limits(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"lot_sizing": {"mode": "fixed", "skip_limits_at": 0}})

    migrate_config(cfg)

    data = _read(cfg)
    assert data["lot_sizing"]["skip_limits_at"] == 0  # user's explicit off is kept
    assert data["lot_sizing"]["mode"] == "fixed"  # mode never touched


def test_profit_defaults_is_idempotent(tmp_path) -> None:
    cfg = tmp_path / "config.json"
    _write(cfg, {"lot_sizing": {"mode": "risk_percent"}})
    migrate_config(cfg)

    # User flips a partial back to 50 after the one-time migration.
    data = _read(cfg)
    data["lot_sizing"]["skip_limits_at"] = 9
    _write(cfg, data)

    migrate_config(cfg)
    assert _read(cfg)["lot_sizing"]["skip_limits_at"] == 9  # not re-applied
