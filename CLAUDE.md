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

1. Edit `bot/config/constants.py` and set the real values for `_PRODUCTION_DSN` and `_PRODUCTION_LICENSE_URL`.
2. Build the frontend: `cd frontend && npm install && npm run build && cd ..` — produces `frontend/dist/`.
3. Build the binary: `pyinstaller bot.spec` — output is `dist/MT5Bot.exe` (single-file Windows executable, frontend bundled).
4. Revert constants before committing: `git checkout bot/config/constants.py`. **Never commit the filled DSN or license URL.**

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

## Key Constraints (Non-Negotiable)

- Supabase tables (`signals`, `limits`, `live_prices`, `licenses`) are **read-only** from the bot.
- All mutable state lives in local SQLite (`orders.db`).
- No MT5 credentials in code or UI — always `mt5.initialize()` with no arguments.
- All MT5 orders use magic number `20250001`.
- `signal_type` (`standard`, `scalp`, `swing`, `toll`, `pa`, `1-1`) is captured at placement time from Supabase `signals.type` and stored in SQLite; never re-read from Supabase.
- Idempotent sync — running a cycle twice must have no additional effect.
- TP engine must never crash the main loop — log errors and continue.
- Spread adjustment applied to every order placement (see ARCHITECTURE.md).
- `lot_sizing.risk_percent` and `lot_sizing.fixed_lot` accept either a flat `float` or a per-instrument dict (`{"XAUUSD": 0.3, "default": 1.0}`). Resolution order: exact MT5 symbol → `"default"` key → `1.0`.

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
