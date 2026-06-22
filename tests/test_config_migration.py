import json

from bot.config.settings import (
    _MIGRATION_OFFSET_BACKFILL,
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


def test_missing_file_is_noop(tmp_path) -> None:
    cfg = tmp_path / "does_not_exist.json"
    migrate_config(cfg)  # must not raise
    assert not cfg.exists()
