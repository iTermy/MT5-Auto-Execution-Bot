import json

from bot.config.settings import (
    _MIGRATION_OFFSET_BACKFILL,
    _MIGRATION_PROXIMITY_BUMP,
    _MIGRATION_SPREAD_HOUR_LATE,
    _MIGRATION_SYMBOL_MAP_BACKFILL,
    _OFFSET_BACKFILL_SYMBOLS,
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
    assert prox["indices"] == {"SPX": 40.0, "NAS": 100.0, "CUSTOM": 14.0}
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


def test_missing_file_is_noop(tmp_path) -> None:
    cfg = tmp_path / "does_not_exist.json"
    migrate_config(cfg)  # must not raise
    assert not cfg.exists()
