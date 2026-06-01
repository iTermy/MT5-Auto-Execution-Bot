# CLAUDE.md — Auto-Execution Bot V2

## Current Implementation Status
**All 14 phases complete (52/52 steps) + post-MVP fixes (decisions 31-37) + V2 dashboard overhaul (decisions 38-46) + V3 frontend redesign (decision 47) + V4 integration & bug fixes complete (decisions 48-57) + V5 cross-codebase hardening complete (decisions 58-64) + V6 MT5 polling reduction complete (decisions 65-71) + V7 signal_type expansion complete (decision 72).**
Read STATE.md immediately — it lists all implementation decisions made during build that are not
in the original ARCHITECTURE.md.

## What To Do Now
All planned work is complete. NEXT_STEPS.md is fully executed. See STATE.md decision 72 for the
V7 expansion that replaced the `is_scalp` boolean with a six-value `signal_type` (standard / scalp
/ swing / toll / pa / 1-1) and added per-type TP overrides + the 1-1 fixed-TP path.

## What This Is
Python Windows desktop app that reads trading signals from Supabase PostgreSQL and places/manages pending orders on MetaTrader 5 (MT5) via ICMarkets. FastAPI backend + React/TypeScript frontend served at `localhost:8501`, system tray icon via pystray.

## How To Work In This Repo
All decisions and context live in these repo files. Do not rely on chat history or memory.

- **Commit by default** — after completing changes, commit and push to `main` without asking. Only ask before committing if the change is destructive or you are unsure about correctness.
- **Commit style** — one short line, plain English, no version labels ("V5", "V6"), no decision refs ("decisions 65-71"), no parenthetical explanations. State *what* changed in as few words as possible. Good: `"Fix SL offset on offset instruments"`. Bad: `"V5 fix: SL offset at placement (decision 58) — adj_sl now includes offset for SPX/NAS/BTC/ETH"`.
- **ARCHITECTURE.md** — system design, schemas, all technical decisions, config.json structure
- **STATE.md** — what exists, what doesn't, all owner-approved decisions, known risks
- **NEXT_STEPS.md** — V5 cross-codebase review (7 steps, 4 phases). Fully executed.
- **CONVENTIONS.md** — code quality rules, naming, async patterns, API-specific conventions

Read STATE.md first. It lists every owner decision and every known risk.

## Build & Run

### Development
```bash
# Backend (uses .env for DSN, empty license URL bypasses validation)
pip install -r requirements.txt
python main.py

# Frontend (dev)
cd frontend && npm install && npm run dev

# Frontend (production build)
cd frontend && npm run build

# Tests
pytest tests/
```

### Production Build (.exe)
The production exe has DSN and license URL baked into the binary. No .env file needed at runtime.

1. **Set credentials** in `bot/config/constants.py`:
   ```python
   _PRODUCTION_DSN: str = "postgresql://execution_bot_ro.cqogevbfbrfzgbuxbhmn:oS%2495chu86HanS@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
   _PRODUCTION_LICENSE_URL: str = "https://cqogevbfbrfzgbuxbhmn.supabase.co/functions/v1/validate-license"
   ```
   **DSN must use the Supabase session pooler** (`aws-1-us-east-2.pooler.supabase.com:5432`), not the direct connection (`db.xxx.supabase.co`). Direct connections resolve to IPv6 which fails on IPv4-only hosts. URL-encode `$` as `%24` in the password.

2. **Build frontend** (if changed):
   ```bash
   cd frontend && npm run build
   ```

3. **Build exe**:
   ```bash
   pyinstaller bot.spec
   ```
   Output: `dist/MT5Bot.exe`

4. **Revert credentials** — do not commit them:
   ```python
   _PRODUCTION_DSN: str = ""
   _PRODUCTION_LICENSE_URL: str = ""
   ```

5. **Deploy** — copy to the production folder:
   - `MT5Bot.exe`
   - `config.json` (if not already present)

   The exe serves the frontend from the bundled `frontend/dist/` — no separate files needed. `orders.db` and `bot.log` are created at runtime next to the exe.

## Key Constraints (Non-Negotiable)
- Supabase tables are **read-only** — no INSERT/UPDATE/DELETE on signals, limits, live_prices, feed_health, licenses
- All mutable bot state lives in **local SQLite** (`orders.db`)
- No MT5 credentials in code or UI — always `mt5.initialize()` with no arguments
- All MT5 orders use magic number `20250001`
- `signal_type` captured from signal at placement time (Supabase `signals.type`), stored in SQLite as `signal_type TEXT`, never re-read from DB. Values: `standard`, `scalp`, `swing`, `toll`, `pa`, `1-1`.
- Idempotent sync — running a cycle twice must have no additional effect
- TP engine must never crash the main loop — log errors and continue
- Spread adjustment applied to every order placement (see ARCHITECTURE.md)
- `lot_sizing.risk_percent` accepts either a flat `float` (e.g. `1.0`) or a per-instrument dict (e.g. `{"XAUUSD": 0.3, "default": 1.0}`). Resolution order: exact MT5 symbol → `"default"` key → `1.0`. Same shape as `fixed_lot`.

## Concurrency (Critical)
- Main thread: pystray (system tray icon, Windows message pump)
- Engine thread: asyncio event loop + MT5 (bound to this thread)
- MT5 calls are synchronous but <50ms, called directly in async loop
- FastAPI runs as an async task in the engine thread's event loop
- **Never call MT5 from a FastAPI request handler** — use `DashboardCache` (populated each sync cycle) instead
- Shutdown from UI triggers `engine.shutdown()` → cancels async tasks → calls `tray.stop()` via callback

## Critical Implementation Decisions (Phases 7–10)
These are not in ARCHITECTURE.md — they were decided during build:

- **ICMarkets hedging**: filled position ticket ≠ order ticket. After fill, call `sqlite.update_ticket(order_ticket, position_ticket)` so all downstream code (TP engine, trailing) can look up by `position.ticket`. See STATE.md decision #19.
- **Partial close remainder**: synthetic `limit_id = -new_ticket` (negative integer). fill_detector detects it and insert_order is called with order_type="remainder". status is immediately set to filled+trailing.
- **TP trigger metric**: compares **price movement** (not account P&L) to `profit_threshold`. Dollar threshold = raw price distance. Pip threshold = price_distance / pip_size. Only "others P&L >= 0" uses `position.profit` (account currency).
- **db_symbol_from_mt5()** in `symbol_mapper.py`: reverse-maps MT5 symbol to DB symbol for asset-class detection. Needed because "BTCUSD" (len 6) fails the crypto rule without mapping back to "BTCUSDT".
- **Adaptive sleep**: sync_loop sleeps 1s when active, tp_loop sleeps 2s when active (`tp_trailing_interval_seconds`), both 30s when idle. During spread hours/weekends: 30s (active) or 60s (idle).
- **Engine.app is set externally**: main.py calls `create_app(engine)` and assigns to `engine.app`. `run_forever()` starts uvicorn only if `engine.app is not None`.
- **LicenseValidator dev bypass**: empty URL → returns VALID immediately, no HTTP call.
- **SSEBroadcaster.last_msg + replay buffer**: GET /api/status reads cached last status. SSE generators replay up to 200 buffered messages for late-connecting clients (init logs).
- **API-first startup**: `run_forever()` starts the API server task and waits for `api_ready` event before DB/license init, so the frontend can connect before init logs fire.
- **DashboardCache**: Engine updates `dashboard_cache` each sync cycle with account info, positions, orders, summary. API endpoints read from cache — no MT5 calls in handlers.

## Post-MVP Fixes (decisions 31-37 in STATE.md)
- **Partial close sets is_trailing immediately** — execute() calls set_trailing after partial close so remainder is tracked. Original decision #16 was buggy.
- **Cancel pending on TP fire** — TPEngine cancels remaining pending orders for a signal after TP executes.
- **SL sync for filled positions** — sync_cycle updates MT5 position SL when signal stop_loss changes in Supabase. Skips trailing positions.
- **Forced exit on signal cancellation** — sync_cycle closes all positions when signal status transitions to 'cancelled'/'breakeven' from 'hit'.
- **Orphan sweep cancels** — Reconciler cancels orphan orders instead of just logging.
- **Pending SL change detection** — sync_cycle cancels pending orders with stale SL for re-placement.

## V2 Dashboard Overhaul (decisions 38-46 in STATE.md)
- **SSE replay buffer** — SSEBroadcaster keeps a 200-message deque; new SSE clients receive buffered messages on connect.
- **API-first engine startup** — API server starts before DB/license init so the browser can connect first and see all init logs.
- **Shutdown from UI** — `POST /api/engine/shutdown` triggers full process exit (engine + tray icon). Tray icon `stop()` wired as shutdown callback.
- **Excluded symbols** — `excluded_symbols` list in config.json. Sync cycle filters these out before any MT5 calls. Currently: `["USOILSPOT"]`.
- **Stock suffix fallback** — When a `.NAS-24`/`.NYSE-24` symbol fails MT5 lookup, tries without suffix. On success, auto-persists to `stock_no_suffix` in config.json.
- **Dashboard cache** — `DashboardCache` (new file) holds account, positions, orders, summary; updated each sync cycle. `GET /api/dashboard` reads from cache.
- **Trade history with P&L** — `realized_pnl` and `symbol` columns added to `order_mappings`. `mark_closed()` accepts P&L. `GET /api/history` returns trades + win/loss stats.

## V3 Frontend Redesign (decision 47 in STATE.md)
- **Design source** — Claude Design handoff bundle; Layout A (Command Strip) chosen by owner, iterated to light theme with comfy-black top bar.
- **Theme** — Warm light paper surfaces (#F7F4EE bg, #FFFFFF panels), comfy-black top bar (#262320), orange accent (#E8824A). Dark theme preserved in CSS vars but light is default (`data-theme="light"` on `<html>`).
- **Typography** — Schibsted Grotesk (body) + JetBrains Mono (numbers/code), loaded via Google Fonts in index.html.
- **Layout** — Full-width dark top bar → grid below: 72px icon sidebar rail | main content. Log drawer slides up from bottom of main column.
- **Custom SVG charts** — EquityCurve (hoverable Catmull-Rom area chart), Donut (animated win/loss), Bars (hoverable daily P&L). No chart library — `recharts` removed.
- **Dashboard page** — Hero row (cumulative P&L curve + win/loss donut with Day/Week/All toggles), Closest Signals cards with proximity meters, sortable positions table, recent trades + daily P&L bars.
- **History page** — Date/status/type filters, 12-cell performance stats grid (computed client-side from trade data), sortable trades table.
- **Settings page** — Engine controls + connection status, license key, lot sizing (Risk%/Fixed toggle), TP config table, symbol mapping table, floating save bar + toast.
- **Computed stats** — `utils/stats.ts` computes detailed stats (profit factor, expectancy, avg win/loss, streaks, hold time, scalp share) client-side from trade history.

## Database Access
- **asyncpg** for Supabase: positional params unpacked (`$1, $2` as separate args, not a list)
- **aiosqlite** for SQLite: `?` placeholders, tuple params, commit after writes
- Supabase timestamps are native `datetime` — never pass to `datetime.fromisoformat()`
- `ROUND(x, 2)` in Postgres requires `CAST(... AS NUMERIC)`

## DSN Loading
`_PRODUCTION_DSN` constant in `bot/config/constants.py` — placeholder `""` in the repo, set before building the production exe. No `.env` file or environment variables needed.

## Target File Layout
```
main.py                        — entry point (tray + thread launch, shutdown callback)
bot/config/constants.py        — magic number, enums, production DSN placeholder
bot/config/settings.py         — Pydantic config model (incl excluded_symbols, stock_no_suffix)
bot/core/engine.py             — orchestrator (API-first startup, dashboard cache, shutdown)
bot/core/dashboard_cache.py    — DashboardCache: caches account/positions/orders for API
bot/core/sync_cycle.py         — idempotent sync (excluded symbols filter, stock suffix fallback)
bot/core/reconciler.py         — startup reconciliation
bot/core/scheduler.py          — spread hour gating
bot/mt5/client.py              — all MT5 API calls
bot/mt5/connection.py          — init/shutdown/reconnect
bot/mt5/types.py               — dataclasses for MT5 return types
bot/db/supabase.py             — asyncpg pool + queries
bot/db/sqlite.py               — aiosqlite CRUD (incl realized_pnl, symbol columns, history query)
bot/db/queries.py              — SQL constants
bot/trading/order_placer.py    — place orders (with spread adjustment)
bot/trading/order_canceller.py — cancel orders
bot/trading/fill_detector.py   — detect fills + partial close tickets
bot/trading/lot_calculator.py  — risk % and fixed lot modes
bot/trading/offset_calculator.py — feed offset for indices/crypto
bot/trading/symbol_mapper.py   — DB->MT5 mapping + asset class detection + stock_no_suffix
bot/tp/engine.py               — TP monitor loop
bot/tp/strategy.py             — TPStrategy Protocol
bot/tp/default_strategy.py     — trigger, partial close, trailing handoff
bot/tp/trailing.py             — trailing stop SL ratchet
bot/tp/asset_config.py         — per-asset-class TP thresholds
bot/license/validator.py       — HTTP validation via Edge Function
bot/license/models.py          — license status types
bot/api/app.py                 — FastAPI app (lifespan sets api_ready), static serving
bot/api/routes.py              — REST endpoints (incl /dashboard, /history, /engine/shutdown)
bot/api/sse.py                 — SSE streaming with 200-message replay buffer
bot/utils/logging.py           — structured logging + SSE broadcast hook
bot/utils/time_utils.py        — EST conversion, market hours
frontend/src/index.css         — full theme: CSS vars, light/dark, all component styles
frontend/src/App.tsx           — root: app shell, top bar, sidebar, page routing, log drawer
frontend/src/pages/DashboardPage.tsx  — hero P&L chart + donut, closest signals, positions, recent trades, daily bars
frontend/src/pages/HistoryPage.tsx    — filters, 12-stat performance grid, sortable trades table
frontend/src/pages/SettingsPage.tsx   — engine controls, license, lot sizing, TP config, symbol mapping, save bar
frontend/src/components/Icon.tsx      — SVG icon paths (stroke-based, 24x24 viewBox)
frontend/src/components/NavSidebar.tsx — icon sidebar rail (brand, 3 pages, logs toggle)
frontend/src/components/TopBar.tsx    — comfy-black bar: account figs, connection dots, engine toggle
frontend/src/components/LogDrawer.tsx — slide-up log panel with header + close
frontend/src/components/Seg.tsx       — segmented control (Day/Week/All, filter toggles)
frontend/src/components/ProxMeter.tsx — proximity bar for closest-signal cards
frontend/src/charts/EquityCurve.tsx   — hoverable SVG area chart (Catmull-Rom smoothing)
frontend/src/charts/Donut.tsx         — animated win-rate donut
frontend/src/charts/Bars.tsx          — hoverable daily P&L bar chart
frontend/src/charts/smoothPath.ts     — Catmull-Rom → cubic bezier path utility
frontend/src/hooks/useSSE.ts          — SSE for logs + status
frontend/src/hooks/useDashboard.ts    — polling hook (2s interval)
frontend/src/hooks/useSort.tsx        — generic sortable-table hook with sort indicators
frontend/src/utils/money.ts           — money() and fmtBalance() formatters
frontend/src/utils/stats.ts           — compute detailed stats, daily bars, cumulative P&L from trades
frontend/src/utils/channels.ts — channel ID → name/type mapping
supabase/functions/            — Edge Function for license validation
tests/                         — pytest suite
```

## V4 Completed Fixes

All V4 bugs have been resolved. See STATE.md decisions 48–57 for full details.

- **MARK_CLOSED bug fixed** — `cancelled_at = datetime('now')` now set on close; charts work.
- **channel_id pipeline** — Supabase → SQLite → API → frontend; serialised as string to preserve 64-bit Discord snowflake precision. `frontend/src/utils/channels.ts` maps IDs to names/types.
- **Timestamp fallbacks** — `t.closed_at || t.filled_at || t.placed_at` used throughout `stats.ts`.
- **Period filtering wired** — `filterTradesByPeriod()` drives Day/Week/All toggles on dashboard.
- **Signal grouping** — `groupBySignalId()` used in Dashboard (Closest Signals + Recent Trades) and History table.
- **Dashboard section order** — Positions before Closest Signals.
- **History filters** — Instrument dropdown, expanded Type Seg (Standard/Scalp/Swing/Tolls), Sort by dropdown added.
- **Settings: TP config** — reads object keyed by asset class; fully editable with controlled inputs; oil preserved on save.
- **Settings: symbol map** — reads `config.symbol_map`; add/remove rows; stock suffix field.
- **Settings: handleSave** — saves all fields (tp_config, symbol_map, stock_suffix, full lot_sizing).
- **Settings: Validate button** — wired to save license_key via PUT /api/config.
- **Fixed lot per instrument** — `LotSizingConfig.fixed_lot: float | dict[str, float]`; UI table with Default + per-instrument rows; `LotCalculator._get_fixed_lot()` handles both shapes.
- **Select element CSS** — `select.inp` styled with `appearance: none` + custom SVG chevron arrow.

## V5 Completed Fixes

All V5 bugs have been resolved. See STATE.md decisions 58–64 for full details.

- **SL offset at placement** — `order_placer.py`: both `adj_sl` calculations now include `+ (offset or 0.0)`. Before this fix, MT5 SL on offset instruments (SPX, NAS, BTC, ETH) was placed in DB price space, not MT5 price space — off by the entire offset.
- **Partial close volume floor** — `default_strategy.py`: `math.floor(raw / volume_step) * volume_step` + `volume_min` clamp. Added `close_vol <= 0` guard that trails full position. Prevents `TRADE_RETCODE_INVALID_VOLUME` on instruments with `volume_step=0.1`.
- **Supabase outage guard** — `supabase.py`: errors now propagate from all three fetch methods. `sync_cycle.run()`: `fetch_active_signals` wrapped in try/except; entire placement/cancellation block gated on result. Fill detection always runs.
- **Force exit after cold restart** — `_check_forced_exits`: removed `previous != "hit"` guard. On restart `_last_signal_status` is empty; the old guard skipped every signal. `filled_sids` gate prevents false positives.
- **Force exit retry on partial failure** — `_check_forced_exits`: `_last_signal_status` updated only when `all_closed=True`; failed positions are retried next cycle.
- **SL sync uses current offset** — `_sync_filled_sls`: uses `live_prices` (passed from `run()`) to compute current offset; falls back to `offset_at_placement` when live price unavailable.

## V6 Polling Reduction (decisions 65-71 in STATE.md)
- **symbol_info() permanent cache** — `MT5Client` caches `SymbolInfo` per symbol in a dict. Static metadata never changes during a session. Eliminates ~500K-1M calls/day when active.
- **Bulk query TTL cache** — `positions_get()`, `orders_get()`, `account_info()` cached with 500ms TTL. Collapses 4x `positions_get()` and 2x `orders_get()` duplicates per cycle into 1 each.
- **Pass positions to fill_detector** — `detect_partial_close_tickets()` accepts optional `positions` param; sync_cycle passes its already-fetched list.
- **Spread-hour deep sleep** — `_active_interval()` returns 30s/60s during spread hours and weekends instead of 1s.
- **TP loop crypto-only during spread hours** — `TPEngine.run_cycle(crypto_only=True)` during spread hours; non-crypto trailing stops not adjusted during high-spread periods.
- **Separate TP loop interval** — `tp_trailing_interval_seconds` (default 2s) in `PollingConfig`. TP loop polls at 2s, sync loop at 1s.
- **Dashboard tick deduplication** — `DashboardCache.update()` fetches `symbol_info_tick()` once per unique symbol, not per position/order.

## Pre-Production Hardening (Phases 2–4 from TM IMPLEMENTATION_PLAN.md)

These changes landed after V7 as part of a joint TM+EX hardening pass before live forward-testing. They are not in STATE.md.

### Phase 2 — Placement integrity
- **C2 orphan window:** MT5 order comment changed to `s{signal_id}_l{limit_id}`[:32]. Before `order_send()`, a `status='claimed'` row is written to SQLite; on success it is promoted to `pending`; on failure it is deleted. `reconciler.py` re-links claimed rows on startup, cleans stale claims, and cancels truly untracked orders. Orphan sweep runs every 60s, full reconcile every 2h.
- **C3 cancel race:** `place_order()` calls `supabase.fetch_signal_status()` immediately before `order_send()` and aborts (deletes claim) if status is not `active` or `hit`. On the TM side, all cancel paths update `limits.status='cancelled'` **before** `signals.status='cancelled'` so EX's pending-limit query stops seeing the limits first.
- **M1/M2:** Full reconcile every 2h via `_reconcile_loop`; `_check_external_closes()` marks positions closed if they disappear from MT5 every cycle (even when Supabase is down).
- **M14:** `UPDATE_TICKET` query adds `AND status='filled'` guard; `update_ticket()` returns `bool`.

### Phase 4 — Price / state sync
- **H1 offset (no drift):** `FETCH_LIVE_PRICES` now selects `ic_bid, ic_ask`. `OffsetCalculator.get_offset()` prefers `ic_mid − feed_mid` from the same row (both written at the same flush time by TM). Falls back to a live MT5 tick with a one-time per-symbol WARNING if `ic_bid`/`ic_ask` are NULL (rolling-deploy gap). `OffsetCalculator` now has `__init__` with `_ic_fallback_logged: set[str]`.
- **M6 news_mode:** `supabase.fetch_news_mode()` called once per cycle after the spread-hour gate. When `True`: all pending orders cancelled (same path as spread hour), `placement_active = False`, logged as `reason=news_mode`.
- **M5 feed_health:** `supabase.fetch_feed_health()` returns `{feed: status}`. Feeds with `status IN ('degraded', 'down')` collected into `stale_feeds`. `_feed_for_symbol(db_sym, config)` determines whether a symbol is served by `icmarkets` / `oanda` / `binance`. Signals on stale feeds are skipped in the approval loop with `reason=feed_stale`.
- **M11 excluded logging:** `_logged_excluded: set[int]` in `SyncCycle.__init__`. Each excluded-symbol limit is logged exactly once per bot lifetime with `signal_id`, `limit_id`, `symbol`.

## Pre-Production Hardening (Phases 5–7 from TM IMPLEMENTATION_PLAN.md)

### Phase 5 — SL & TP hygiene
- **C5 trailing stop on forced exit:** `_FORCE_EXIT_STATUSES` now includes `profit` (was `cancelled`, `breakeven`). Before closing positions, `set_trailing(ticket, 0)` is called for all rows of the signal so the TP loop cannot ratchet the SL while force-exit is in progress.
- **C8 SL failure alert:** `_sl_fail_count / _sl_fail_target` per-ticket dicts in `SyncCycle`. After 5 consecutive failures on the same target SL, logs at ERROR once. Resets on success or target change.
- **H9 partial close floor:** In `DefaultTPStrategy`, if `raw_vol < volume_step`, closes `max(volume_step, volume_min)` rather than falling through to `volume_min` (prevents closes well below the broker step).
- **M13 force-exit attempt counter:** `_force_exit_fail_count` per-ticket, `_last_force_exit_status` per-signal in `SyncCycle`. After 5 consecutive close failures on a ticket, logs ERROR and treats it as "handled" (stops retrying). Counts reset when the signal's force-exit status changes.
- **H7 atomic fill+ticket:** `SQLiteDB.mark_filled_and_set_position_ticket()` wraps both updates in `async with self._db:` (single transaction). Fill detection call site uses this helper unconditionally.
- **H8 placement readback:** After `order_send` succeeds, `MT5Client.order_get_by_ticket()` fetches the placed order; mismatches in `sl` or `price_open` vs. requested values log WARNING immediately.

### Phase 6 — Lifecycle correctness (EX side)
- **M10 `closed_reason`:** `FETCH_SIGNAL_STATUSES` now selects `closed_reason`. `fetch_signal_statuses()` returns `dict[int, dict]` with `status` and `closed_reason`. `_check_forced_exits` logs `closed_reason=` in the forced-exit warning so operators can distinguish `manual` / `automatic` / `expiry` closures.

### Phase 7 — License teardown + per-instrument risk %
- **L5 license teardown:** `Engine` tracks `_license_expired`, `shutdown_reason`, `_last_license_valid`. When `_sync_loop` detects `license_valid` flipping `True → False`, it calls `_license_teardown()`: cancels all SQLite-pending MT5 orders, market-closes all filled positions, sets `shutdown_reason = "license_expired"`, and returns (loop exits). **Re-activation requires a bot restart.** `_last_license_valid` is synced after the initial `validate()` in `run_forever()` so a failing startup validation does not trigger teardown.
- **Per-instrument `risk_percent`:** `LotSizingConfig.risk_percent` is now `float | dict[str, float]` (same shape as `fixed_lot`). `LotCalculator._get_risk_percent(mt5_symbol)` resolves: exact symbol key → `"default"` key → `1.0`. Plain `float` still works unchanged.

## V7 signal_type Expansion (decision 72 in STATE.md)
- **Schema change** — Supabase dropped `signals.scalp BOOLEAN`, added `signals.type TEXT` with six values: `standard`, `scalp`, `swing`, `toll`, `pa`, `1-1`. SQLite `order_mappings.is_scalp` → `signal_type TEXT DEFAULT 'standard'`; one-shot migration in `SQLiteDB.init_schema()` backfills `is_scalp=1 → 'scalp'` and drops the old column.
- **TP routing per type** — `asset_config.get_config(asset_class, signal_type, config, instrument)` dispatches: `standard` uses base; `scalp/toll/pa` use their own override map (fall back to base if unconfigured); `swing` falls back to **3× the base threshold** when unconfigured; `1-1` forces `threshold_unit='dollars'`, `partial_close_percent=100`, `trailing_distance=0`.
- **1-1 trailing lockout** — `TPEngine._process_group` skips the trailing branch when `signal_type == '1-1'`, even if a stale `is_trailing=1` row exists. Belt-and-suspenders alongside the `partial_close_percent=100` config force.
- **Config additions** — `TPConfig` gained `toll_overrides`, `swing_overrides`, `pa_overrides` (same shape as `scalp_overrides`) and `one_to_one: OneToOneConfig` (`profit_threshold: float = 10.0` + `overrides: dict[str, float]`). All new override maps default to `{}`.
- **Frontend** — `TradeData.signal_type`, `PositionData.signal_type`, `PendingOrderData.signal_type` (replaces `is_scalp`); History page Type filter expanded to all six types and reads `signal_type` from DB; Settings TP table now has `Standard | Scalp | Toll | Swing | PA` tabs over the per-asset grid plus a separate 1-1 fixed-TP card. `channels.ts` keeps `getChannelName()` only — `getSignalType()`/`CHANNEL_TYPES` removed (replaced by authoritative DB field). New `frontend/src/utils/signalType.ts` holds the type list, display labels, and badge classes.
