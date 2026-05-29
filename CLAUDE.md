# CLAUDE.md — Auto-Execution Bot V2

## Current Implementation Status
**All 14 phases complete (52/52 steps) + post-MVP fixes (decisions 31-37) + V2 dashboard overhaul (decisions 38-46) + V3 frontend redesign (decision 47). V4 integration & bug fix plan in NEXT_STEPS.md (19 steps, 5 phases).**
Read STATE.md immediately — it lists all implementation decisions made during build that are not
in the original ARCHITECTURE.md.

## What To Do Now
**Execute NEXT_STEPS.md** — V4 integration & bug fix plan. 19 steps across 5 phases.
Phase 1 (backend fixes) must be done first — it unblocks broken charts and enables signal
grouping with channel/type data. See NEXT_STEPS.md for full details and implementation order.

## What This Is
Python Windows desktop app that reads trading signals from Supabase PostgreSQL and places/manages pending orders on MetaTrader 5 (MT5) via ICMarkets. FastAPI backend + React/TypeScript frontend served at `localhost:8501`, system tray icon via pystray.

## How To Work In This Repo
All decisions and context live in these repo files. Do not rely on chat history or memory.

- **ARCHITECTURE.md** — system design, schemas, all technical decisions, config.json structure
- **STATE.md** — what exists, what doesn't, all owner-approved decisions, known risks
- **NEXT_STEPS.md** — V4 integration & bug fix plan (19 steps, 5 phases). Execute in order.
- **CONVENTIONS.md** — code quality rules, naming, async patterns, API-specific conventions

Read STATE.md first. It lists every owner decision and every known risk.

## Build & Run
```bash
# Backend
pip install -r requirements.txt
python main.py

# Frontend (dev)
cd frontend && npm install && npm run dev

# Frontend (production build)
cd frontend && npm run build

# PyInstaller
pyinstaller bot.spec

# Tests
pytest tests/
```

## Key Constraints (Non-Negotiable)
- Supabase tables are **read-only** — no INSERT/UPDATE/DELETE on signals, limits, live_prices, licenses
- All mutable bot state lives in **local SQLite** (`orders.db`)
- No MT5 credentials in code or UI — always `mt5.initialize()` with no arguments
- All MT5 orders use magic number `20260001`
- `is_scalp` captured from signal at placement time, stored in SQLite, never re-read from DB
- Idempotent sync — running a cycle twice must have no additional effect
- TP engine must never crash the main loop — log errors and continue
- Spread adjustment applied to every order placement (see ARCHITECTURE.md)

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
- **Adaptive sleep**: both sync_loop and tp_loop sleep 1s when `sqlite.get_all_active()` is non-empty, 30s when idle.
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
1. `.env` file with `SUPABASE_DSN` (contributor path)
2. `_PRODUCTION_DSN` constant in `bot/config/constants.py` (production build, placeholder in repo)

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
frontend/src/utils/channels.ts — channel ID → name/type mapping (TO BE CREATED in V4)
supabase/functions/            — Edge Function for license validation
tests/                         — pytest suite
```

## V4 Known Bugs (to be fixed by NEXT_STEPS.md)

### Critical: MARK_CLOSED timestamp bug
`MARK_CLOSED` in `queries.py` never sets `cancelled_at` for closed trades. The SQLite schema
uses `cancelled_at` as the close timestamp (no separate `closed_at` column). Result: `/api/history`
returns `closed_at: ""` for every closed trade. This breaks:
- `computeCumulativePnl()` — filters out ALL closed trades (empty string is falsy)
- `computeDailyBars()` — same issue, daily P&L bars are empty
- Recent trades on dashboard — no time displayed
- Hold time calculation in stats — always 0

### Settings: TP Config invisible
`SettingsPage.tsx` reads `config.tp_config` as an array (`Array.isArray(tp)`) — it's actually an
object with named asset keys (forex, metals, etc.). Check always fails, section never renders.

### Settings: Symbol Mapping invisible
Code reads `config.symbol_overrides` — field doesn't exist. Correct field is `config.symbol_map`.

### Settings: handleSave incomplete
`handleSave` only saves `license_key` and `lot_sizing`. TP config, symbol map, and all other
settings are silently dropped on save.

### Dashboard: signals not grouped
Individual limits are shown separately. Signals consist of groups of limits (sharing `signal_id`)
and should be displayed as signal groups in Closest Signals and Recent Trades.

### History: missing filters
Design specifies Instrument dropdown, Sort by dropdown, and Type filters (Tolls/Swings/1-1).
Current implementation only has Status and Type (All/Standard/Scalp).

### Channel ID availability
Supabase `signals` table has `channel_id` (Discord channel ID number). Not currently piped
through to SQLite/API/frontend. V4 Step 2 adds this. Channel IDs map to signal types:
scalps channel → Scalp, swing-trades → Swing, *tolls* channels → Tolls, others → Standard.
