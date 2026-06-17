# CLAUDE.md — MT5 Auto-Execution Bot

Python Windows desktop app that reads trading signals from Supabase PostgreSQL and places/manages pending orders on MetaTrader 5 via ICMarkets. FastAPI backend + React frontend at `localhost:8501`, system tray via pystray.

For users and a quick-start, see [README.md](README.md). For the full system design, see [ARCHITECTURE.md](ARCHITECTURE.md). For contributor setup and the production build workflow, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Build & Run

### Development

```bash
pip install -r requirements.txt
python main.py
```

The bot opens `http://localhost:8501` automatically. For frontend live-reload:

```bash
cd frontend && npm install && npm run dev   # Vite at :5173, proxies /api/* to :8501
```

Tests and formatters:

```bash
pytest                              # backend tests
ruff check bot tests main.py        # lint
ruff format bot tests main.py       # format
cd frontend && npm run format       # prettier
cd frontend && npx tsc --noEmit     # type-check
```

### Production exe (owner only)

1. Bump `BOT_VERSION` in `bot/config/constants.py` and set the real values for `_PRODUCTION_DSN`, `_PRODUCTION_LICENSE_URL`, and `_PRODUCTION_UPDATE_MANIFEST_URL`.
2. Build the frontend: `cd frontend && npm install && npm run build && cd ..` — produces `frontend/dist/`.
3. Build the binary: `pyinstaller bot.spec` — output is `dist/MT5Bot.exe` (single-file Windows executable, frontend bundled).
4. Revert constants before committing: `git checkout bot/config/constants.py`. **Never commit the filled DSN, license URL, or manifest URL.**

### Release an auto-update (owner only)

The running bot polls `_PRODUCTION_UPDATE_MANIFEST_URL` hourly; when it points at a newer `version` than the running `BOT_VERSION`, the dashboard surfaces an "Update and restart" prompt that downloads, verifies SHA-256, self-replaces, and relaunches (`bot/update/`). To ship a build:

1. Build `dist/MT5Bot.exe` as above (with `BOT_VERSION` bumped).
2. Hash it: `CertUtil -hashfile dist/MT5Bot.exe SHA256` (or `sha256sum`).
3. Upload the exe as `MT5Bot-<version>.exe` to the public Supabase Storage `releases` bucket.
4. **Last**, update `releases/latest.json` so users never pull a manifest pointing at a not-yet-uploaded binary:
   ```json
   { "version": "1.3.0", "url": "https://<proj>.supabase.co/storage/v1/object/public/releases/MT5Bot-1.3.0.exe", "sha256": "<hex>", "notes": "...", "min_supported": "1.0.0" }
   ```

Test against a scratch bucket without rebuilding the constant via the `MT5BOT_UPDATE_URL` env override (`bot/config/settings.py:load_update_manifest_url`). The updater is frozen-only — in dev (`python main.py`) the install path raises a clear "packaged build only" error.

### Edge Function deploy (owner only)

```bash
npm install -g supabase
supabase login
supabase link --project-ref <your-project-ref>
supabase functions deploy validate-license
```

The Edge Function reads `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from the project environment automatically. `licenses` table schema:

```sql
CREATE TABLE licenses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    license_key TEXT NOT NULL UNIQUE,
    mt5_account BIGINT NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT true,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`users` table (one row per license, UPSERTed by the bot every 5 min for leaderboard / TP optimization). `license_id` matches the `licenses.id` column type — change it if your `licenses.id` is something other than `BIGINT`:

```sql
CREATE TABLE users (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    license_id            BIGINT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    license_key           TEXT NOT NULL UNIQUE,
    mt5_account           BIGINT NOT NULL,
    balance               NUMERIC(14,2),
    equity                NUMERIC(14,2),
    currency              TEXT,
    leverage              INTEGER,
    open_positions_count  INTEGER NOT NULL DEFAULT 0,
    total_realized_pnl    NUMERIC(14,2) NOT NULL DEFAULT 0,
    total_trades          INTEGER NOT NULL DEFAULT 0,
    wins                  INTEGER NOT NULL DEFAULT 0,
    losses                INTEGER NOT NULL DEFAULT 0,
    win_rate              NUMERIC(5,2) NOT NULL DEFAULT 0,
    bot_version           TEXT,
    last_update_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Production role (used by the shipped .exe; DSN role is `execution_bot_ro`):
GRANT SELECT ON licenses TO execution_bot_ro;
GRANT SELECT, INSERT, UPDATE ON users TO execution_bot_ro;

-- Contributor role (used by `.env` setups in dev):
GRANT SELECT ON licenses TO contributor_bot;
GRANT SELECT, INSERT, UPDATE ON users TO contributor_bot;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_insert_exec ON users FOR INSERT TO execution_bot_ro WITH CHECK (true);
CREATE POLICY users_update_exec ON users FOR UPDATE TO execution_bot_ro USING (true) WITH CHECK (true);
CREATE POLICY users_insert      ON users FOR INSERT TO contributor_bot   WITH CHECK (true);
CREATE POLICY users_update      ON users FOR UPDATE TO contributor_bot   USING (true) WITH CHECK (true);
```

The bot's UPSERT pulls `license_id` from `licenses` via the `license_key`, so each role needs SELECT on `licenses`. If the configured `license_key` isn't in `licenses`, the INSERT silently inserts zero rows. Policy names must be unique per table — that's why the production and contributor policies have distinct names even though they apply the same predicate.

## Key Constraints (Non-Negotiable)

- Supabase tables (`signals`, `limits`, `live_prices`) are **read-only** from the bot. `licenses` is read-only via SELECT (used by `users` UPSERT to resolve `license_id`); writes still go through the Edge Function. `tp_outcomes` is write-only (append-only analytics log; INSERT granted to `contributor_bot` plus a row-level-security INSERT policy on the same role, applied via DDL run in the Supabase SQL editor). `users` is upsert-only (one row per license, refreshed every 5 min; INSERT + UPDATE granted to `contributor_bot` with matching RLS policies).
- **`tp_outcomes` is two-staged per trade** (`stage` column): a `"trigger"` row when TP fires (partial/closed-portion `realized_pnl` + money-based `r_multiple`, MFE/MAE so far, `level_sequence`, `seconds_to_trigger`) and a `"final"` row written by `TPFinalizer.sweep` once the signal's last position goes flat (full-trade `realized_pnl`, final `r_multiple`, aggregate MFE/MAE, `hold_seconds`, `exit_reason`). The `final` write is idempotent via the local SQLite `signal_finalized` guard table. `r_multiple` is money-based: `realized_pnl / risk_money`, where `risk_money = price_distance_to_money(symbol_info, |avg_entry − stop_loss|, total_volume)` (`bot/trading/lot_calculator.py`); shared-SL multi-limit signals make `|avg_entry − stop_loss| · total_vol` the exact signal risk. Adding columns to `tp_outcomes` requires an `ALTER TABLE … ADD COLUMN IF NOT EXISTS` run by the owner in the Supabase SQL editor (the bot only INSERTs); the current extra columns are `stage, mfe_price, mfe_r, mae_price, mae_r, level_sequence, total_levels, seconds_to_trigger, hold_seconds, exit_reason` (plus the pre-existing `r_multiple`).
- All mutable transactional state lives in local SQLite (`orders.db`).
- No MT5 credentials in code or UI — always `mt5.initialize()` with no arguments.
- All MT5 orders use magic number `20250001`.
- `signal_type` (`standard`, `scalp`, `swing`, `toll`, `pa`, `1-1`) is captured at placement time from Supabase `signals.type` and stored in SQLite; never re-read from Supabase.
- Idempotent sync — running a cycle twice must have no additional effect.
- TP engine must never crash the main loop — log errors and continue. TP outcome writes are also non-fatal (Supabase failure is logged, sync continues).
- Spread adjustment applied to every order placement (see ARCHITECTURE.md).
- `lot_sizing.risk_percent` and `lot_sizing.fixed_lot` accept either a flat `float` or a per-instrument dict (`{"XAUUSD": 0.3, "default": 1.0}`). Resolution order: exact MT5 symbol → `"default"` key → `1.0`.
- `lot_sizing.exceptions` is a **list** of `{symbol, signal_type, mode, value}` entries keyed by **MT5 symbol**, each optionally scoped to one `signal_type` (`"all"` = every type). An exception overrides the global lot mode. Resolution per `(mt5_symbol, signal_type)`: a `signal_type`-specific match beats an `"all"` match for the same symbol; no match falls through to the global mode. The legacy `{symbol: {mode, value}}` dict form is still accepted on load (coerced to a list with `signal_type="all"` via a `field_validator`).
- **Crypto symbols (BTCUSDT, ETHUSDT, anything `detect_asset_class()` classifies as `CRYPTO`) are exempt from spread-hour and news-mode gates** — they keep placing and stay live through those windows because the 24/7 crypto market doesn't have the same liquidity events.
- **Weekend force-close window**: when a signal's status flips to `cancelled`, the bot only force-closes filled positions if `MarketScheduler.is_weekend_window()` is True (Fri ≥16:45 EST through Sun <18:00 EST) **or** the position is on BTCUSD/crypto. Weekday cancellations on signals with fills are expected (Supabase extends expiry) so positions stay open. `breakeven` status closes unconditionally.
- **Spread-hour SL strip**: `SyncCycle._manage_spread_hour_sls` clears the broker-side stop-loss off every filled position (trailing included) during `MarketScheduler.is_sl_strip_window()` — opens ~5 min before the spread spike (`sl_strip_start` 16:55 forex / `sl_strip_stock_start` 15:55 stocks, before their 16:00 close) and closes at `daily_end` — so a spread-driven spike can't stop it out. When the window ends the SL is restored to the persisted `last_known_mt5_sl`; if price has genuinely moved past that level the position is closed at market instead (a bigger but rare loss). State lives in the SQLite `sl_stripped` flag (restart-safe); while set, both the TP loop and `_sync_filled_sls` skip the position so neither re-arms the stop. Crypto and `-24` 24h stocks are exempt (`_gate_exempt`).
- **Offset-drift throttle**: drift checks are gated per-order by `last_offset_check` and `config.offset_drift_check_interval_seconds` (default 1800s = 30 min). Prevents feed-mid jitter from churning the same order every sync cycle.
- **Auto-update** (`bot/update/`): owner-driven and manual-confirm only — the bot detects a newer release from the HTTPS manifest and flags availability, but installs solely on explicit user click. Integrity is the mandatory SHA-256 from the manifest (we don't code-sign); a mismatch aborts and the old exe keeps running. Self-replace works only in the frozen build and needs write access to the exe's own folder (fine for a user-owned folder; Program Files would need elevation, out of scope). `_update_loop` and `_run_update` are catch-and-log — they never crash the main loop. The Supabase `releases` bucket is read over plain HTTPS, not the asyncpg pool.
- **TP `instrument_overrides`** key by **DB symbol** (e.g. `SPX500USD`, `NAS100USD`, `BTCUSDT`), not MT5 symbol. Note this differs from `lot_sizing.*` per-instrument dicts which key by MT5 symbol (e.g. `US500`). Each entry can be either flat (applies to all signal types) or nested per-signal-type:
  ```json
  "instrument_overrides": {
    "SPX500USD": { "profit_threshold": 15.0, "trailing_distance": 4.0 },
    "NAS100USD": {
      "default": { "profit_threshold": 50.0, "trailing_distance": 15.0 },
      "scalp":   { "profit_threshold": 30.0, "trailing_distance": 8.0 },
      "swing":   { "profit_threshold": 150.0, "trailing_distance": 40.0 }
    }
  }
  ```
  Detection rule: if any of `profit_threshold`/`trailing_distance`/`threshold_unit`/`partial_close_percent` sits at the top level, the entry is flat. Otherwise nested — lookup order is `signal_type` key → `"default"` key → no override (asset-class value stands). Each block may set any subset of fields; unspecified fields keep the value resolved earlier in the chain.

## Concurrency (Critical)

- **Main thread**: pystray (system tray icon, Windows message pump).
- **Engine thread**: asyncio event loop + MT5 (bound to this thread).
- MT5 calls are synchronous but <50ms, called directly in the async loop.
- FastAPI runs as an async task in the engine thread's event loop.
- **Never call MT5 from a FastAPI request handler** — use `DashboardCache` (populated each sync cycle) instead.
- Shutdown from UI triggers `engine.shutdown()` → cancels async tasks → calls `tray.stop()` via callback.

## Code Conventions

### Quality (non-negotiable)
- Production-grade code only. No placeholder implementations, no TODO-driven development.
- Minimal, concise implementations. If it can be done in 10 lines, don't write 30.
- No defensive programming unless justified by a real, documented failure case. Trust internal code.
- No "just in case" error handling. Validate at system boundaries (user input, MT5 responses, DB results), not between internal functions.
- Avoid unnecessary comments — only explain WHY, never WHAT. Well-named code is self-documenting.
- Don't add features, helpers, or abstractions beyond what the current task requires.

### Python (3.13)
- Modern type hints: `list[str]` not `List[str]`, `X | None` not `Optional[X]`.
- No docstrings except on Protocol methods.
- No `from __future__ import annotations` — use runtime type hints.
- Naming: `PascalCase` classes, `snake_case` functions, `UPPER_SNAKE` constants, `_private` with single underscore.
- Files: `snake_case.py`.
- Format with `ruff format`; lint with `ruff check`. Config in `pyproject.toml`.

### Async
- Supabase: asyncpg. SQLite: aiosqlite. MT5: synchronous, called directly in async context.
- Never use `loop.run_in_executor()` for MT5 — must run on the engine thread.
- Use `asyncio.sleep()`, never `time.sleep()` in async code.

### Error handling
- Trading operations: catch, log, continue (never crash the loop).
- DB: catch `asyncpg.PostgresError` and `aiosqlite.Error` separately.
- MT5: check `result.retcode == mt5.TRADE_RETCODE_DONE`, retry up to 3x on transient errors.
- Never bare `except:` — at least `except Exception:`.
- `logger.error(..., exc_info=True)` for unexpected exceptions.

### Dependency injection
- All classes take dependencies via constructor. No globals, no singletons.
- `Engine` wires everything together, passes instances down.
- For testing: pass mock `MT5Client`, in-memory SQLite.

### Config access
- Read `config.json` once per sync cycle (hot-reload).
- Pass the config snapshot as a parameter; don't re-read mid-cycle.
- Pydantic validates on load — if invalid, the previous valid config is kept.

### React / TypeScript
- Functional components only; custom hooks in `src/hooks/`.
- API calls centralised in `src/api.ts`.
- No state-management library — `useState` + `useEffect` is sufficient.
- SSE via native `EventSource` in a custom hook.
- Format with `npm run format` (Prettier). Config in `frontend/.prettierrc`.

### File organisation
- One class per file when the class is the primary export.
- Related small types may share a file (`types.py`, `models.py`).
- Tests mirror source: `bot/trading/lot_calculator.py` → `tests/test_lot_calculator.py`.
- SQL constants in `bot/db/queries.py`, never inline.

### Git
- Imperative commit messages (`Add TP engine`, not `Added TP engine`).
- One logical change per commit.
- Never commit: `.env`, `config.json`, `orders.db`, `node_modules/`, `dist/`, `build/`.

## Database Access

```python
# asyncpg: positional params, NOT a list
row = await conn.fetchrow("SELECT * FROM signals WHERE id = $1", signal_id)
# Timestamps are native datetime — DO NOT parse
created_at = row["created_at"]
# ROUND requires CAST
await conn.fetch("SELECT ROUND(CAST(price AS NUMERIC), 2) FROM ...")
```

```python
# aiosqlite: ? placeholders, tuple params, always commit
await db.execute(
    "INSERT INTO order_mappings (limit_id, signal_id) VALUES (?, ?)",
    (limit_id, signal_id),
)
await db.commit()
```

```python
# MT5: always filter by magic, always check retcode
orders = mt5.orders_get()
bot_orders = [o for o in (orders or []) if o.magic == MAGIC_NUMBER]
result = mt5.order_send(request)
if result.retcode != mt5.TRADE_RETCODE_DONE:
    logger.error("Order failed: %s - %s", result.retcode, result.comment)
mt5.initialize()  # attaches to already-running terminal — never pass credentials
```
