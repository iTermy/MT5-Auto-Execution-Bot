import json

from bot.config.settings import (
    _MIGRATION_OFFSET_BACKFILL,
    _MIGRATION_PROXIMITY_BUMP,
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


def test_missing_file_is_noop(tmp_path) -> None:
    cfg = tmp_path / "does_not_exist.json"
    migrate_config(cfg)  # must not raise
    assert not cfg.exists()
