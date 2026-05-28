# Coding Conventions

## Code Quality (Non-Negotiable)

- Production-grade code only. No placeholder implementations, no TODO-driven development.
- Minimal, concise implementations. If it can be done in 10 lines, don't write 30.
- No AI-generated filler. No emoji in code or docs. No motivational comments.
- No overengineering or speculative abstraction. Don't build a framework before you need one.
- No defensive programming unless justified by a real, documented failure case. Trust internal code.
- Prefer simple, explicit control flow over clever patterns.
- Avoid unnecessary comments — only explain WHY, never WHAT. Well-named code is self-documenting.
- Avoid verbose or redundant structure. Three similar lines beat a premature abstraction.
- No "just in case" error handling. Validate at system boundaries (user input, MT5 responses, DB results), not between internal functions.
- Don't add features, helpers, or abstractions beyond what the current task requires.

## Python

### Style
- Python 3.13, modern type hints (`list[str]` not `List[str]`, `X | None` not `Optional[X]`)
- No docstrings except on Protocol methods
- Flat imports, no relative imports across packages
- No `from __future__ import annotations` — use runtime type hints

### Naming
- Classes: `PascalCase` — `MT5Client`, `SyncCycle`, `TPEngine`
- Functions/methods: `snake_case` — `place_order()`, `detect_fills()`
- Constants: `UPPER_SNAKE` — `MAGIC_NUMBER`, `DEFAULT_TP_CONFIG`
- Enums: `PascalCase` class, `UPPER_SNAKE` members — `AssetClass.FOREX_JPY`
- Private: single underscore — `_calc_move()`, `_clamp()`
- Files: `snake_case.py` — `sync_cycle.py`, `lot_calculator.py`

### Async Patterns
- Supabase: `async` via asyncpg
- SQLite: `async` via aiosqlite
- MT5: synchronous, called directly in async context (<50ms, acceptable)
- Never use `loop.run_in_executor()` for MT5 — they must run on the engine thread
- Use `asyncio.sleep()` for loop intervals, never `time.sleep()` in async code

### Error Handling
- Trading operations: catch, log, continue (never crash the loop)
- DB: catch `asyncpg.PostgresError` and `aiosqlite.Error` separately
- MT5: check `result.retcode == mt5.TRADE_RETCODE_DONE`, retry up to 3x on transient errors
- Never bare `except:` — at least `except Exception:`
- `logger.error(..., exc_info=True)` for unexpected exceptions

### Dependency Injection
- All classes take dependencies via constructor. No globals, no singletons.
- `Engine` wires everything together, passes instances down.
- For testing: pass mock MT5Client, in-memory SQLite.

### Config Access
- Read `config.json` once per sync cycle (hot-reload)
- Pass config snapshot as parameter, don't re-read mid-cycle
- Pydantic validates on load — if invalid, use previous valid config

## asyncpg
```python
# Correct: positional params unpacked
row = await conn.fetchrow("SELECT * FROM signals WHERE id = $1", signal_id)

# WRONG: list of params
row = await conn.fetchrow("SELECT * FROM signals WHERE id = $1", [signal_id])

# ROUND requires CAST
await conn.fetch("SELECT ROUND(CAST(price AS NUMERIC), 2) FROM ...")

# Timestamps are native datetime objects — DO NOT parse
created_at = row['created_at']  # already datetime
# WRONG: datetime.fromisoformat(str(row['created_at']))
```

## aiosqlite
```python
# Use ? placeholders (not $1)
await db.execute("INSERT INTO order_mappings (limit_id, signal_id) VALUES (?, ?)",
                 (limit_id, signal_id))

# INSERT OR IGNORE for idempotency
await db.execute("INSERT OR IGNORE INTO order_mappings ...")

# Always commit after writes
await db.commit()
```

## MT5
```python
# Always filter by magic number
orders = mt5.orders_get()
bot_orders = [o for o in (orders or []) if o.magic == MAGIC_NUMBER]

# Check retcode on every order_send
result = mt5.order_send(request)
if result.retcode != mt5.TRADE_RETCODE_DONE:
    logger.error(f"Order failed: {result.retcode} - {result.comment}")

# Signal ID in comment field (max 31 chars)
request = {"comment": f"s{signal_id}", ...}

# Never pass credentials to initialize
mt5.initialize()  # attaches to already-running terminal
```

## FastAPI
```python
# SSE via sse-starlette
from sse_starlette.sse import EventSourceResponse

# Config updates validate with Pydantic before writing
@router.put("/api/config")
async def update_config(update: ConfigUpdate):
    ...
```

## React/TypeScript
- Functional components only
- Custom hooks in `src/hooks/`
- API calls in `src/api.ts` (centralized)
- No state management library — useState + useEffect is sufficient
- SSE via native `EventSource` API in custom hook
- Vite proxy to FastAPI in dev: `vite.config.ts` -> `server.proxy`

## File Organization
- One class per file when the class is the primary export
- Related small types can share a file (e.g., `types.py`, `models.py`)
- Tests mirror source: `bot/trading/lot_calculator.py` -> `tests/test_lot_calculator.py`
- SQL constants in `bot/db/queries.py`, not inline

## Git
- Imperative commit messages ("Add TP engine" not "Added TP engine")
- One logical change per commit
- Never commit: `.env`, `config.json`, `orders.db`, `node_modules/`, `dist/`, `build/`
