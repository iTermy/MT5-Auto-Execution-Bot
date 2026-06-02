# Project State — 2026-06-02

## Current Status: Pre-Production Hardening In Progress (Phases 1–2 of 7 complete)

**Original 52 steps complete. Post-MVP fixes (31-37). V2 dashboard overhaul (38-46). V3 frontend redesign (47). V4 integration & bug fixes complete (48-57). V5 cross-codebase hardening complete (58-64). V6 MT5 polling reduction complete (65-71). V7 signal_type expansion complete (72). Pre-production hardening (73-82, Phases 1-2 of plan in `C:\Python Stuff\TM Bot\IMPLEMENTATION_PLAN.md`). Owner UX + production log fixes complete (83-88).**

---

## What Exists in Repo

### Documentation
```
CLAUDE.md          — project overview + constraints for Claude Code
ARCHITECTURE.md    — full technical design, all decisions (read first)
STATE.md           — this file
NEXT_STEPS.md      — 52 ordered implementation steps (all 14 phases marked DONE)
CONVENTIONS.md     — coding style, quality rules, API conventions
```

### Scaffolding (Phase 1)
```
.gitignore                                — excludes orders.db, .env, config.json, build artifacts
requirements.txt                          — 14 Python dependencies
config.example.json                       — full config.json template with all defaults
.env.example                              — DSN + license URL template for contributors
bot/__init__.py
bot/config/__init__.py
bot/core/__init__.py
bot/mt5/__init__.py
bot/db/__init__.py
bot/trading/__init__.py
bot/tp/__init__.py
bot/license/__init__.py
bot/api/__init__.py
bot/utils/__init__.py
tests/__init__.py
supabase/functions/validate-license/      — directory only, no files yet
```

### Config + Constants (Phase 2)
```
bot/config/constants.py   — MAGIC_NUMBER, AssetClass enum, OrderStatus enum, DEFAULT_TP_CONFIG
bot/config/settings.py    — Pydantic Settings model, load_config(), load_dsn(), load_license_url()
                            Fields: excluded_symbols, stock_no_suffix (added V2)
```

### MT5 Client (Phase 3)
```
bot/mt5/types.py        — OrderRequest, OrderResult, OrderInfo, PositionInfo, TickInfo,
                          SymbolInfo, AccountInfo, DealInfo
bot/mt5/connection.py   — MT5Connection: initialize(), shutdown(), ensure_connected()
bot/mt5/client.py       — MT5Client: order_send(), orders_get(), positions_get(), symbol_info(),
                          symbol_info_tick(), account_info(), history_deals_get(),
                          cancel_pending_order()  [added during Phase 6]
```

### Database Modules (Phase 4)
```
bot/db/queries.py    — all SQL constants (Supabase + SQLite), clearly separated
                       V2: GET_ORDER_HISTORY, symbol+realized_pnl in INSERT_ORDER/MARK_CLOSED
                       Hardening: INSERT_CLAIMED_ORDER, PROMOTE_CLAIMED_TO_PENDING,
                         DELETE_CLAIMED_ORDER, GET_CLAIMED_ORDERS, GET_CLAIMED_BY_SIGNAL_LIMIT,
                         FETCH_SIGNAL_STATUS; UPDATE_TICKET now has AND status='filled'
bot/db/supabase.py   — SupabaseDB: create_pool(), close(), fetch_active_signals(), fetch_live_prices(),
                       fetch_signal_status() [new — single-row status check for pre-send abort],
                       fetch_signal_statuses(); pool max_size raised to 10
bot/db/sqlite.py     — SQLiteDB: init_schema() (with column migrations), insert_order(+symbol),
                       mark_filled(), mark_cancelled(), mark_closed(+realized_pnl), set_trailing(),
                       get_pending_orders(), get_filled_positions(), get_trailing_positions(),
                       get_all_active(), get_order_history(),
                       update_ticket() [now returns bool, guards AND status='filled'],
                       insert_claimed_order(), promote_claimed_to_pending(),
                       delete_claimed_order(), get_claimed_orders(), get_claimed_by_signal_limit()
```

### Utilities (Phase 5)
```
bot/utils/logging.py    — setup_logging(), SSELogHandler, get_log_queue()
bot/utils/time_utils.py — to_est(), MarketScheduler (is_spread_hour, should_cancel_pending,
                          should_block_placement)
```

### Trading Modules (Phase 6)
```
bot/trading/symbol_mapper.py     — detect_asset_class(), map_symbol(+stock_no_suffix), needs_offset()
bot/trading/lot_calculator.py    — LotCalculator.calculate(stop_loss, limit_prices, mt5_symbol)
bot/trading/offset_calculator.py — OffsetCalculator: get_offset(), apply_offset(), check_drift()
bot/trading/order_placer.py      — OrderPlacer.place_order() [async, passes symbol to SQLite;
                                   comment=s{signal_id}_l{limit_id}, claim-before/promote-after,
                                   pre-send status recheck; accepts supabase parameter]
bot/trading/order_canceller.py   — OrderCanceller.cancel_order() [async]
bot/trading/fill_detector.py     — FillDetector: detect_fills(), detect_partial_close_tickets()
                                   FillEvent, NewTicketEvent dataclasses
```

---

### TP Engine (Phase 7)
```
bot/tp/asset_config.py   — AssetClassConfig dataclass, get_config(asset_class, signal_type, config, instrument)
bot/tp/strategy.py       — TPStrategy Protocol, TPResult dataclass
bot/tp/default_strategy.py — DefaultTPStrategy: should_trigger, execute, update_trailing
bot/tp/trailing.py       — TrailingStopManager.update(): SL ratchet
bot/tp/engine.py         — TPEngine.run_cycle(): groups by signal_id, delegates to strategy
```

### FastAPI Backend (Phase 10)
```
bot/api/sse.py    — SSEBroadcaster: fan-out + 200-msg replay buffer; make_generator() replays on connect
bot/api/routes.py — 11 endpoints: /status, /config (GET/PUT), engine start/stop/shutdown,
                    /dashboard, /history, 2 SSE streams (/logs, /status/stream)
bot/api/app.py    — create_app(engine): lifespan starts broadcasters + sets api_ready, CORS, StaticFiles
```

---

### License (Phase 9)
```
bot/license/models.py    — LicenseStatus enum (VALID/INVALID/EXPIRED/ERROR), LicenseResult dataclass
bot/license/validator.py — LicenseValidator: validate(), heartbeat_loop(); dev-mode bypass when URL empty
```

---

### Core Orchestration (Phase 8)
```
bot/core/scheduler.py       — re-exports MarketScheduler from bot.utils.time_utils
bot/core/sync_cycle.py      — SyncCycle.run(): excluded symbols filter, stock suffix fallback,
                               Supabase diff, placement, fill detection, drift cancel,
                               _check_external_closes() [new — M2 external close detection],
                               _check_forced_exits(), _sync_filled_sls()
bot/core/reconciler.py      — Reconciler.reconcile(): 5 startup reconciliation cases;
                               reconcile_orphans() [new — re-links claimed rows, cleans stale
                               claims, cancels untracked orders; magic-number filtered]
bot/core/engine.py          — Engine: API-first startup, dashboard cache update, shutdown callback,
                               _reconcile_loop() [new — orphan sweep every 60s + full reconcile
                               every 2h]
bot/core/dashboard_cache.py — DashboardCache: caches account/positions/orders (V2)
```

Additions to existing modules during Phase 8:
- `bot/db/queries.py`: UPDATE_TICKET query
- `bot/db/sqlite.py`: update_ticket(old, new) — reassigns mt5_ticket after hedging fill

---

Additions to existing modules during Phase 7:
- `bot/db/queries.py`: UPDATE_SL query
- `bot/db/sqlite.py`: update_sl(mt5_ticket, sl) method
- `bot/mt5/client.py`: close_position(), modify_position_sl()
- `bot/trading/symbol_mapper.py`: db_symbol_from_mt5(mt5_symbol, config)

---

## What Does NOT Exist Yet

### Phase 14: Tests
```
pytest.ini                   — asyncio_mode=auto, testpaths=tests
tests/conftest.py            — sqlite_db fixture (in-memory), mock_mt5, sample_config,
                               factory helpers: make_settings, make_symbol_info, make_tick,
                               make_position, make_order_info, make_order_result, make_account_info
tests/test_symbol_mapper.py  — 21 parametrized cases + edge cases; map_symbol; db_symbol_from_mt5
tests/test_lot_calculator.py — risk% basic/multi-limit, fixed mode, floor-not-round, clamp min/max,
                               fallback when symbol_info=None
tests/test_tp_engine.py      — should_trigger (dollars/pips mode, others neg/pos), execute
                               pct=0/50/100, multiple positions (earlier closed first)
tests/test_trailing.py       — long ratchet up, never retreats, initial sl=0 set; short ratchet down,
                               never retreats; pips mode converts to price
tests/test_sync_cycle.py     — idempotency (known limit not re-placed, second run is noop),
                               spread hour (cancels pending, skips new placement),
                               offset drift (cancels for re-placement)
tests/test_reconciler.py     — all 5 cases (pending/in-orders, pending/in-positions, pending/gone,
                               filled/gone, filled+trailing/in-MT5), orphan detection,
                               mixed multi-case run
```

### Phase 13: Edge Function + Docs + Build
```
supabase/functions/validate-license/index.ts  — Deno edge function: POST {license_key, mt5_account},
    queries licenses table (active, not expired, account matches), returns {status, expires_at, message}
CONTRIBUTING.md   — .env setup, contributor_bot SQL, monthly rotation, prod build workflow, deploy
bot.spec          — PyInstaller onefile/windowed; bundles frontend/dist; hiddenimports for
                    asyncpg, pystray._win32, uvicorn submodules
```

### Core Python (main.py) — Phase 12
```
main.py   — entry point: setup_logging, create all deps, create tray icon, wire shutdown callback,
             engine.app = create_app(engine), start engine thread, poll :8501, open browser, tray.run()
```

Additions to existing modules during Phase 12:
- `bot/core/engine.py`: `self._loop`, `self._tasks`, `shutdown()`, `_cancel_tasks()`
  Engine now stores its event loop and task list for clean cross-thread cancellation.

---

### V2 Dashboard Overhaul (decisions 38-46) — backend
```
bot/core/dashboard_cache.py       — DashboardCache + DashboardData dataclass
bot/api/sse.py                    — 200-message replay buffer (deque)
bot/api/routes.py                 — /api/dashboard, /api/history, /api/engine/shutdown
```

### V3 Frontend Redesign (decision 47)
```
frontend/src/index.css                — full theme: light/dark CSS vars, all component classes
frontend/src/App.tsx                  — app shell: top bar, sidebar rail, page routing, log drawer
frontend/src/pages/DashboardPage.tsx  — hero P&L curve + donut, closest signals, positions, recent trades, daily bars
frontend/src/pages/HistoryPage.tsx    — filters, 12-stat performance grid, sortable trades
frontend/src/pages/SettingsPage.tsx   — engine controls, license, lot sizing, TP config, symbol mapping, save bar
frontend/src/components/Icon.tsx      — SVG icon paths (stroke-based)
frontend/src/components/NavSidebar.tsx — 72px icon sidebar rail with tooltips
frontend/src/components/TopBar.tsx    — comfy-black bar: account figs, connection dots, engine toggle
frontend/src/components/LogDrawer.tsx — slide-up log panel
frontend/src/components/Seg.tsx       — segmented control
frontend/src/components/ProxMeter.tsx — proximity bar for signal cards
frontend/src/charts/EquityCurve.tsx   — hoverable SVG area chart
frontend/src/charts/Donut.tsx         — animated win-rate donut
frontend/src/charts/Bars.tsx          — hoverable daily P&L bars
frontend/src/charts/smoothPath.ts     — Catmull-Rom path utility
frontend/src/hooks/useSort.tsx        — generic sortable-table hook
frontend/src/utils/money.ts           — money() and fmtBalance() formatters
frontend/src/utils/stats.ts           — compute stats, daily bars, cumulative P&L from trades
frontend/src/hooks/useSSE.ts          — SSE for logs + status (unchanged from V2)
frontend/src/hooks/useDashboard.ts    — polling hook (unchanged from V2)
frontend/src/api.ts                   — fetch wrappers (unchanged from V2)
frontend/src/types.ts                 — TypeScript interfaces (unchanged from V2)
```

Deleted V2 frontend components (replaced by redesign):
- AccountMetrics.tsx, PositionsTable.tsx, PendingOrdersTable.tsx, StatsCards.tsx, TradesTable.tsx

Deleted V1 frontend components (in V2):
- StatusBar.tsx, ControlPanel.tsx, LicensePanel.tsx, LogPanel.tsx

---

## Implementation Decisions Made During Build

These were clarified or resolved during implementation. Future Claude should treat them as final.

1. **OrderStatus.CLOSED added** — reconciler step 5 ("mark closed") requires a distinct status for
   positions that were filled and later closed in MT5. Added `CLOSED = "closed"` to the enum in
   `bot/config/constants.py`. The SQLite schema's `status` column supports it as a valid value.

2. **cancel_pending_order added to MT5Client** — not in the original Phase 3 spec but required by
   order_canceller.py. Uses `TRADE_ACTION_REMOVE`. Located at `bot/mt5/client.py`.

3. **Partial close detection via comment matching** — `detect_partial_close_tickets()` in
   `fill_detector.py` finds new remainder positions by matching `position.comment == "s{signal_id}"`
   against positions whose ticket is not yet in SQLite. Avoids complex deal history parsing.
   This overrides the note in the Known Risks section below ("track via history_deals_get") —
   the comment-based approach is simpler and sufficient for ICMarkets.

4. **Pip size formula** — `point * 10` for instruments with `digits in (3, 5)` (standard FX and JPY);
   `point` for all others (metals, indices, crypto with 2 or 1 digits). Used in both
   `lot_calculator.py` and will be needed in TP engine pip-based threshold comparisons.

5. **LotCalculator floors to volume_step** — not rounds — to avoid over-leveraging. If the raw lot
   is below `volume_min` after flooring, the result is clamped up to `volume_min`.

6. **SQLiteDB holds a persistent connection** — opened in `init_schema()`, closed in `close()`.
   `init_schema()` MUST be called before any SQLiteDB method. WAL mode and busy_timeout=5000 are
   set once at connection open, not per query.

7. **LotCalculator.calculate() takes primitives** — signature is
   `calculate(stop_loss: float, limit_prices: list[float], mt5_symbol: str) -> float`.
   The caller (sync_cycle) extracts values from asyncpg.Record before calling.

8. **detect_fills() takes pre-fetched rows** — signature is
   `detect_fills(mt5_orders, mt5_positions, pending_rows: list[aiosqlite.Row])`.
   Caller fetches pending rows from SQLite and passes them in; FillDetector does not query SQLite
   directly in this method.

9. **detect_partial_close_tickets() queries SQLite directly** — takes `(mt5_client, sqlite)` as
   instances and fetches trailing + all_active rows internally.

10. **OffsetCalculator.check_drift() takes absolute price threshold** — not pips. The caller
    (sync_cycle) must convert `offset_drift_threshold_pips * pip_size` to a price value before
    calling `check_drift(current, stored, threshold_in_price)`.

11. **MarketScheduler lives in time_utils.py** — `bot/core/scheduler.py` (Phase 8, step 28) will
    import it directly rather than duplicating logic.

12. **fetch_live_prices returns dict[str, asyncpg.Record]** — keyed by symbol string.
    Caller passes `list[str]` of symbols; asyncpg passes it as a PostgreSQL array to `= ANY($1)`.

13. **TP trigger uses price movement, not account P&L** — `profit_threshold` compares the
    price distance moved in the favorable direction (pips for forex/JPY, raw price units for metals/
    indices/crypto/oil). The "others >= 0" check uses `position.profit` (account currency P&L).
    These are intentionally different metrics: threshold is lot-size-independent.

14. **db_symbol_from_mt5() in symbol_mapper.py** — Added for TP engine to reverse-map MT5 symbols
    (e.g., "BTCUSD", "AMD.NAS-24") back to DB symbols (e.g., "BTCUSDT", "AMD.NAS") for correct
    asset-class detection. Without this, BTCUSD (len 6) fails the crypto detection rule.

15. **close_position() and modify_position_sl() added to MT5Client** — Required by DefaultTPStrategy
    and TrailingStopManager. close_position() retries up to 3x on transient retcodes.

16. **~~Partial close does NOT set is_trailing in execute()~~** — **SUPERSEDED by decision #31.**
    Original design was broken: remainder positions were never tracked because
    detect_partial_close_tickets() only searches is_trailing=1 rows. See decision #31.

17. **Trailing SL initial set when position.sl == 0** — TrailingStopManager checks `position.sl > 0`
    before the "don't retreat" guard, so positions with sl=0 always get the initial trailing SL set.

18. **TPEngine constructs DefaultTPStrategy internally** — Constructor accepts an optional
    `strategy: TPStrategy` for testing; defaults to `DefaultTPStrategy()`. DefaultTPStrategy
    owns its TrailingStopManager internally.

19. **update_ticket() added to SQLiteDB** — In ICMarkets hedging mode, the filled position's
    ticket (position.ticket) differs from the originating order ticket. After mark_filled(),
    update_ticket(order_ticket, position_ticket) is called so downstream code (TP engine, trailing)
    can look up positions by their actual MT5 ticket.

20. **Partial close remainder uses synthetic limit_id = -new_ticket** — The remainder position
    from a partial close has no Supabase limit row. A negative ticket value is used as limit_id to
    satisfy the UNIQUE constraint while ensuring it never collides with real Supabase IDs (positive).

21. **SyncCycle.run() takes placement_active: bool** — When False (engine stopped or license
    invalid), skips placement and cancellation but still runs fill detection and partial close
    detection. This keeps position state current even when trading is paused.

22. **Adaptive sleep in sync_loop and tp_loop** — Both loops sleep 1s when SQLite has any active
    rows (pending or filled); sleep 30s when idle. This gives 1s fill-detection latency for scalp
    strategy without hammering Supabase when idle.

23. **Offset drift cancel-and-re-place** — When drift exceeds threshold, the pending order is
    cancelled (status='cancelled'). On the next cycle, the limit_id is absent from sqlite_active,
    so it appears in new_limit_ids and is re-placed with the current offset.

24. **Engine.app set externally** — main.py calls create_app(engine) (Phase 10) and assigns the
    result to engine.app before starting the engine thread. run_forever() starts uvicorn only if
    app is not None.

25. **LicenseValidator dev-mode bypass** — If the license URL is empty (contributor .env without
    LICENSE_API_URL, or production constants.py placeholder not filled), validate() returns VALID
    immediately without any HTTP call. This lets contributors run and test without a live Edge Function.

26. **LicenseValidator.validate() stores last key+account** — heartbeat_loop() calls validate()
    with the stored values so it can re-validate without external parameters. If config hot-reload
    changes the license_key, the new key takes effect on the next explicit validate() call (startup
    or manual); the heartbeat uses whatever was last validated.

27. **SSEBroadcaster.last_msg** — caches the most recent status broadcast so GET /api/status can
    return current state without an MT5 call. Returns _STATUS_DEFAULTS dict if no broadcast yet.

28. **SSE heartbeat every 15s** — make_generator() uses asyncio.wait_for with timeout=15 and yields
    an empty "heartbeat" event to keep HTTP connections alive through proxies/load balancers.

29. **StaticFiles mount is conditional** — app.py checks if frontend/dist/ exists before mounting.
    In dev, Vite runs on :5173 and proxies /api/* to :8501. In production, dist/ is present and
    FastAPI serves the SPA directly.

30. **PUT /api/config accepts full Settings** — the endpoint receives the complete Settings model.
    Frontend pattern: GET config, modify fields, PUT full config back. No partial-update mechanism.

31. **Partial close NOW sets is_trailing in execute()** — Supersedes decision #16. After a successful
    partial close (0 < pct < 100), execute() calls `sqlite.set_trailing(newest.ticket)`. This marks
    the original as is_trailing=1 so detect_partial_close_tickets() finds the remainder on the next
    sync cycle. Without this, the remainder was never tracked and trailing never started.

32. **Original ticket marked closed when remainder found** — sync_cycle calls
    `sqlite.mark_closed(evt.original_ticket)` after inserting the remainder row. Cleans up the stale
    original entry so it doesn't appear in future queries.

33. **Cancel pending orders when TP fires** — After execute() completes, TPEngine cancels all remaining
    pending orders for that signal via `_cancel_pending_for_signal()`. Prevents additional fills after
    the trade is concluded. Ported from V1.

34. **SL sync for filled positions** — sync_cycle._sync_filled_sls() updates MT5 position SL when the
    signal's stop_loss changes in Supabase. Skips is_trailing=1 positions (trail owns SL). Compares
    stored db_stop_loss against current signal SL, only acts when drift exceeds 1 pip. Ported from V1.

35. **Forced exit on signal cancellation** — sync_cycle._check_forced_exits() monitors filled signals
    for status transitions to 'cancelled' or 'breakeven' (from 'hit' only). Closes all positions at
    market via mt5_client.close_position(). Uses transition detection to avoid re-firing. Ported from V1.

36. **Orphan sweep cancels orders** — Reconciler now cancels orphan MT5 orders (our magic number, not
    tracked in SQLite) instead of just logging a warning. Matches V1 behavior.

37. **Pending SL change detection** — sync_cycle cancels pending orders whose db_stop_loss differs from
    the current signal stop_loss by >= 1 pip. The order is re-placed with the new SL on the next cycle.
    Ported from V1.

38. **SSE replay buffer** — SSEBroadcaster keeps a `deque(maxlen=200)` of recent broadcasts. When a
    new SSE client connects via `make_generator()`, all buffered messages are yielded first (replay),
    then live messages from the per-client queue. Solves the problem of init logs being lost before
    the browser connects.

39. **API-first engine startup** — `run_forever()` now starts the API server task FIRST and awaits
    `self.api_ready` (an `asyncio.Event` set in the FastAPI lifespan). Only then does it proceed with
    `init_schema()`, `create_pool()`, `reconcile()`, `validate()`. This ensures the frontend can
    connect and SSE broadcasters are running before init logs start firing.

40. **Shutdown from UI** — New `POST /api/engine/shutdown` endpoint calls `engine.shutdown()`.
    `shutdown()` now also invokes `_shutdown_callback` (set to `tray.stop()` in main.py). This causes
    `tray.run()` to return, leading to normal process exit. Main.py reordered: tray icon created before
    engine thread starts, callback wired before `engine_thread.start()`.

41. **Excluded symbols** — `excluded_symbols: list[str]` added to Settings. Sync cycle filters
    `supabase_rows` early (before any MT5 calls) by removing rows whose `instrument` is in the list.
    Currently configured: `["USOILSPOT"]` (oil not supported via live_prices yet).

42. **Stock suffix fallback** — `stock_no_suffix: list[str]` added to Settings. `map_symbol()` checks
    this list before appending `stock_suffix`. In sync_cycle pre-check phase: when a `.NAS-24`/`.NYSE-24`
    symbol fails `symbol_info_tick()`, tries the base symbol (without suffix). On success, auto-persists
    `db_symbol` to `stock_no_suffix` in config.json via `_persist_stock_no_suffix()`. First cycle with
    a new stock fails (one-time); next cycle uses the cached no-suffix mapping.

43. **DashboardCache** — New file `bot/core/dashboard_cache.py`. `DashboardCache` class holds
    `DashboardData` (account, positions, pending_orders, summary). Engine calls
    `dashboard_cache.update()` at end of each sync cycle with MT5 + SQLite data. `GET /api/dashboard`
    reads from cache — no MT5 calls in the handler.

44. **realized_pnl column** — Added `realized_pnl REAL` column to `order_mappings`. `mark_closed()`
    now accepts `realized_pnl: float | None = None`. Callers updated: TP close passes `pos.profit`,
    forced exit passes `pos.profit`, reconciler/partial-close pass `None`. Migration in `init_schema()`.

45. **symbol column** — Added `symbol TEXT` column to `order_mappings`. `insert_order()` now accepts
    `symbol: str | None = None`. `order_placer.py` passes `mt5_symbol`. Partial close remainder passes
    symbol from the MT5 position. Migration in `init_schema()`. History endpoint uses this for display.

46. **Frontend V2 redesign** — Professional dark trading dashboard replacing the minimal 4-component
    layout. Three-page navigation (Dashboard, History, Settings) via state-based routing. Dashboard
    shows account metrics, sortable positions/orders tables. History shows date-filtered trades with
    stats cards and recharts P&L bar chart. Settings consolidates connection status, license, lot sizing,
    engine controls + shutdown button with confirmation. Toggleable log drawer at bottom. recharts added
    as dependency. Old components (StatusBar, ControlPanel, LicensePanel, LogPanel) deleted.

47. **Frontend V3 redesign** — Complete visual overhaul from Claude Design handoff.

48. **MARK_CLOSED timestamp fix** — `MARK_CLOSED` in `queries.py` now sets
    `cancelled_at = datetime('now')`. SQLite has no separate `closed_at` column; `cancelled_at`
    doubles as the close timestamp. Frontend's `closed_at` field (mapped from `cancelled_at` in
    the history route) was always empty before this fix, breaking all chart computations.

49. **channel_id data pipeline** — `s.channel_id` added to `FETCH_ACTIVE_SIGNALS_WITH_LIMITS`.
    `channel_id INTEGER` column added to `order_mappings` (with migration). `insert_order()`
    accepts `channel_id: int | None`; `order_placer.py` passes it through from the Supabase row.
    Dashboard cache and history route serialise as `str(channel_id)` to avoid 64-bit Discord
    snowflake precision loss in JavaScript JSON parsing. TypeScript types use `string | null`.

50. **channels.ts — channel ID mapping** — New file `frontend/src/utils/channels.ts`. 18-channel
    ID→name mapping (hardcoded). `getChannelName()` returns the channel display name.
    **Superseded in V7 (decision 72)**: `getSignalType()` and the `CHANNEL_TYPES` map were removed;
    the History page Type filter and Dashboard signal cards now read the authoritative
    `signal_type` field that flows through Supabase → SQLite → API → frontend.

51. **Timestamp fallback chain** — All three compute functions in `stats.ts` now use
    `t.closed_at || t.filled_at || t.placed_at` as the effective timestamp for closed trades.
    Handles existing SQLite rows that have NULL `cancelled_at` (before fix 48 was deployed).

52. **filterTradesByPeriod / groupBySignalId** — Two new exports in `stats.ts`.
    `filterTradesByPeriod(trades, 'daily'|'weekly'|'all')` cuts by 24h or 7d window.
    `groupBySignalId<T extends { signal_id: number }>(items)` returns a `Map<number, T[]>`.
    Used by dashboard (period toggles, signal grouping) and history (signal grouping).

53. **Dashboard: period filtering wired** — `pnlP` toggle filters trades before computing
    equity curve, daily bars, and pnlValue. `wlP` toggle independently filters for win/loss
    donut. Previously the toggles only changed the label text.

54. **Dashboard: signal grouping** — Closest Signals groups `pending_orders` by `signal_id`;
    each card shows limit count, channel name, signal type. Recent Trades groups closed trades
    by `signal_id`; each row shows aggregate P&L and limit count. Section order changed:
    Positions before Closest Signals.

55. **History: signal grouping + new filters** — History table now shows one row per signal
    group (aggregated P&L, total lots, limit count). New filter controls: Instrument `<select>`,
    Sort by `<select>` (Newest/Oldest/P&L High→Low/P&L Low→High/Symbol A→Z), Type Seg expanded
    to All/Standard/Scalp/Swing/Tolls. `useSort` removed; `buildGroups()` + `sortGroups()`
    handle grouping and ordering. Stats grid remains trade-level.

56. **Settings: full rewrite** — All four bugs fixed in one pass:
    (a) TP config reads `tp_config` as object keyed by asset class (not array); oil preserved on
        save via `...config.tp_config` spread. `partial_close_percent` read from
        `tp_config.partial_close_percent`.
    (b) Symbol mapping reads `config.symbol_map` (not non-existent `symbol_overrides`); always
        shown (no visibility guard); feed indicator derived from `offset_instruments`.
    (c) `handleSave` now saves all fields: full `lot_sizing`, `tp_config`, `symbol_map`,
        `stock_suffix`. Uses `...config` spread to preserve fields not in UI.
    (d) Validate button calls `handleValidate()` which PUTs config with updated `license_key`.
    All inputs converted from `defaultValue` (uncontrolled) to `value` + `onChange` (controlled).
    `initFromConfig()` drives both initial load and Discard reset.

57. **Fixed lot per instrument** — `LotSizingConfig.fixed_lot` changed from `float` to
    `float | dict[str, float]` in `settings.py`. `LotCalculator._get_fixed_lot(mt5_symbol)`
    looks up by symbol then `default` key when `fixed_lot` is a dict. Settings UI shows a table
    with a locked Default row + editable per-instrument rows when mode=`fixed`. Saves as float
    when only the default row exists, dict otherwise. `select.inp` in `index.css` adds
    `appearance: none` + SVG chevron arrow (theme-aware) for consistent styling. Layout A (Command
    Strip) chosen. Theme: warm light paper surfaces (#F7F4EE), comfy-black top bar (#262320), orange
    accent (#E8824A). Typography: Schibsted Grotesk + JetBrains Mono via Google Fonts. Full-width top
    bar spans above sidebar. 72px icon sidebar rail with hover tooltips. Custom SVG charts replace
    recharts (removed as dependency): hoverable equity curve (Catmull-Rom smoothing), animated win/loss
    donut, hoverable daily P&L bars. Dashboard hero row has cumulative P&L + win/loss with Day/Week/All
    period toggles. Closest Signals section with proximity meter cards replaces flat pending orders table.
    History page computes 12 detailed stats client-side (profit factor, expectancy, avg win/loss, streaks,
    hold time, scalp share). Settings adds TP config table and symbol mapping table (shown when config
    provides them). Floating unsaved-changes save bar + toast notification. Dark theme preserved in CSS
    vars but not exposed in UI (no Tweaks panel — that was design-tool-only). V2 table components
    (AccountMetrics, PositionsTable, PendingOrdersTable, StatsCards, TradesTable) deleted.

---

### V4 Integration & Bug Fixes (COMPLETE)
```
NEXT_STEPS.md — 19 steps, 5 phases. All implemented. See decisions 48–57 below.
```

**Bugs discovered during V3 verification:**

48. **MARK_CLOSED timestamp bug** — `MARK_CLOSED` query in `queries.py` never sets `cancelled_at`
    for closed trades. SQLite uses `cancelled_at` as the close timestamp (no separate closed_at
    column). Result: `/api/history` returns `closed_at: ""` for all closed trades. This breaks
    equity curve, daily P&L bars, recent trades, and hold time stats (all filter on `closed_at`
    being truthy, which it never is). Fix: add `cancelled_at = datetime('now')` to MARK_CLOSED.

49. **SettingsPage TP config invisible** — `SettingsPage.tsx` reads `config.tp_config` as array
    (`Array.isArray(tp)`) but the backend sends it as an object with named asset class keys.
    Check always fails, TP section never renders.

50. **SettingsPage symbol mapping invisible** — Code reads `config.symbol_overrides` which doesn't
    exist in the Settings model. Correct field is `config.symbol_map`. Section never renders.

51. **SettingsPage handleSave incomplete** — Only saves `license_key` and `lot_sizing`. TP config,
    symbol map, partial close %, and all other settings are silently dropped. Must save full config.

52. **Signal grouping** — Frontend treats individual limits as separate entries. Signals consist of
    groups of limits sharing a `signal_id`. Owner wants Closest Signals, Recent Trades, and History
    to group by signal and show aggregate P&L. `signal_id` is available on all data points.

53. **Channel ID for signal types** — Supabase `signals` table has `channel_id` (Discord channel ID).
    Not currently piped through SQLite/API. Channel IDs map to signal types: scalps→Scalp,
    swing-trades→Swing, *tolls*→Tolls, others→Standard. V4 adds channel_id to the data pipeline
    and creates a frontend mapping utility.

54. **Dashboard section order** — Closest Signals appears before Open Positions. Owner wants
    Open Positions first, then Closest Signals.

55. **P&L period filtering broken** — Day/Week/All toggles change the label but don't filter data.
    Must filter trades by period before computing curve/bars/win-loss stats.

56. **History missing filters** — Design specifies Instrument dropdown, Sort by dropdown, and
    expanded Type filter (Tolls/Swings/1-1). Current implementation only has Status and basic Type.

57. **Fixed lot per instrument** — Design shows per-instrument fixed lot table when Fixed lot mode
    selected. Current implementation shows single input. Requires `LotSizingConfig.fixed_lot` to
    accept `float | dict[str, float]`.

---

### V5 Cross-Codebase Review (COMPLETE)
```
NEXT_STEPS.md — 7 steps, 4 phases. All implemented. See decisions 58–64 below.
```

58. **SL offset at placement fixed** — `order_placer.py` lines 45/54: both `adj_sl` calculations
    now include `+ (offset or 0.0)`. Before this fix, the MT5 SL on offset instruments (SPX, NAS,
    BTC, ETH) was off by the entire offset amount — SL placed in DB price space, not MT5 price space.

59. **Partial close volume floored to volume_step** — `bot/tp/default_strategy.py`: replaced
    `round(raw_vol, 2)` with `math.floor(raw_vol / volume_step) * volume_step` + `volume_min` clamp.
    Added `close_vol <= 0` guard that trails the full position instead of attempting a zero-volume
    close. Prevents `TRADE_RETCODE_INVALID_VOLUME` on instruments with `volume_step=0.1`.

60. **Supabase outage no longer mass-cancels orders** — `bot/db/supabase.py`: removed try/except
    from `fetch_active_signals`, `fetch_live_prices`, `fetch_signal_statuses` — errors now propagate.
    `bot/core/sync_cycle.py` `run()`: `fetch_active_signals` wrapped in try/except that sets
    `supabase_rows = None` on failure; entire placement/cancellation block gated on
    `if supabase_rows is not None:`. Fill detection always runs. SL sync and forced exits also
    gated on `supabase_rows is not None` (second guard after fill detection).

61. **Force exit fires after cold restart** — `_check_forced_exits`: removed `if previous != "hit":
    continue` guard. On restart `_last_signal_status` is empty so `previous` is None; the old guard
    always skipped force exit for signals that transitioned during the restart window. Now force exit
    fires on first observation of a cancelled/breakeven signal that has filled positions in SQLite.
    The `filled_sids` gate already prevents false positives on never-filled signals.

62. **Force exit retries on partial close failure** — `_check_forced_exits`: `_last_signal_status`
    is now updated only after all positions for a signal are successfully closed (`all_closed=True`).
    If any `close_position` call fails, the status entry stays at its previous value so the next
    cycle retries the remaining unclosed positions.

63. **SL sync uses current offset** — `_sync_filled_sls` now accepts `live_prices` dict (passed from
    `run()`). For offset instruments, tries `self._offset_calc.get_offset()` from current live price
    first; falls back to `offset_at_placement` if live price unavailable or stale. `live_prices`
    initialized at the outer `if supabase_rows is not None:` scope so it is always defined at the
    call site regardless of whether `placement_active` was True.

64. **MAGIC_NUMBER doc corrected** — CLAUDE.md said `20260001`; corrected to `20250001` to match
    `bot/config/constants.py` and `bot/config/settings.py`.

65. **symbol_info() permanent cache** — `MT5Client` caches `SymbolInfo` per symbol in a dict. Static
    instrument metadata (digits, point, volume_min, volume_step) never changes during a session.
    Eliminates ~500K–1M redundant MT5 calls/day when active positions exist.

66. **Bulk query TTL cache** — `positions_get()`, `orders_get()`, `account_info()` cached with a
    500ms TTL on `MT5Client`. Collapses 4 duplicate `positions_get()` and 2 duplicate `orders_get()`
    per cycle into 1 each. Independent consumers (sync, TP, dashboard, fill_detector) all share the
    cached result within the same cycle window.

67. **Pass positions to detect_partial_close_tickets()** — `fill_detector.detect_partial_close_tickets()`
    now accepts an optional `positions` parameter. `sync_cycle.run()` passes the `mt5_positions` list
    it already fetched, avoiding a redundant `positions_get()` call.

68. **Spread-hour deep sleep** — `_active_interval()` returns 30s (active orders) or 60s (idle)
    during spread hours and weekends, instead of 1s. No fills can occur during these periods for
    non-crypto instruments.

69. **TP loop skipped during spread hours** — `TPEngine.run_cycle()` accepts `crypto_only=True`.
    During spread hours, TP engine only monitors crypto positions (which trade 24/7). Non-crypto
    trailing stops are not adjusted during high-spread periods to avoid harmful SL changes.

70. **Separate TP loop interval** — New `tp_trailing_interval_seconds` config (default 2s). TP loop
    uses `_tp_interval()` instead of `_active_interval()`, polling at 2s instead of 1s. Trailing SL
    does not need sub-second precision. Fill detection (sync loop) remains at 1s.

71. **Dashboard tick deduplication** — `DashboardCache.update()` fetches `symbol_info_tick()` once
    per unique symbol, not once per position/order. With 5 positions + 3 orders across 4 symbols,
    this reduces 8 tick calls to 4.

72. **signal_type replaces is_scalp (V7)** — Supabase `signals` table dropped `scalp BOOLEAN` and
    added `type TEXT` with six values: `standard`, `scalp`, `swing`, `toll`, `pa`, `1-1`. The bot
    now propagates `signal_type` end-to-end:
    - **Supabase query** (`bot/db/queries.py`): `s.type AS signal_type` (aliased; `type` is a Python
      builtin, alias keeps Python access ergonomic and matches the SQLite column name).
    - **SQLite schema**: `order_mappings.is_scalp INTEGER` → `signal_type TEXT NOT NULL DEFAULT 'standard'`.
      One-shot migration in `SQLiteDB.init_schema()`: PRAGMA-detects the old column, ALTERs to add
      `signal_type`, backfills `is_scalp=1 → 'scalp'`, then DROPs `is_scalp`. DROP wrapped in
      try/except — if SQLite is too old, the column is left in place (code stops reading it either way).
    - **Pipeline propagation**: `OrderPlacer.place_order()`, `SQLiteDB.insert_order()`,
      `FillDetector.NewTicketEvent`, and `DashboardCache` all carry `signal_type: str` instead of
      `is_scalp: int`. The remainder-insert path in `sync_cycle.py` forwards the same string.
    - **TP routing** (`bot/tp/asset_config.py`): `get_config(asset_class, signal_type, config, instrument)`.
      Override dispatch table covers `scalp/toll/pa` (fall back to base if unset) and `swing` (falls
      back to `3 × base.profit_threshold` when no override is configured — `swing` default lives in
      code, not config, per owner spec "for now, make it 3x"). `1-1` forces `threshold_unit='dollars'`,
      `partial_close_percent=100`, `trailing_distance=0`.
    - **1-1 trailing lockout**: `TPEngine._process_group` explicitly skips the `trailing_rows` branch
      when `signal_type == '1-1'`, even if a stale `is_trailing=1` row exists. Belt-and-suspenders
      alongside the `partial_close_percent=100` config force so manual DB edits or future config
      changes cannot accidentally enable trailing for 1-1 trades.
    - **Config additions** (`bot/config/settings.py`): `TPConfig` gained `toll_overrides`,
      `swing_overrides`, `pa_overrides` (each `dict[str, ScalpOverrideConfig]`) and `one_to_one:
      OneToOneConfig` (`profit_threshold: float = 10.0` + `overrides: dict[str, float]`). All new
      override maps default to `{}`. `config.json` updated with empty stubs.
    - **API serialization** (`bot/api/routes.py /api/history`): emits `signal_type: str` instead of
      `is_scalp: bool`. `DashboardCache` also adds `signal_type` to positions and pending orders.
    - **Frontend** (`frontend/src/types.ts`): `TradeData.signal_type`, `PositionData.signal_type`,
      `PendingOrderData.signal_type`, plus the new `SignalType` union. New
      `frontend/src/utils/signalType.ts` holds the type list, display labels (`Standard`, `Scalp`,
      `Swing`, `Toll`, `PA`, `1-1`), and badge classes. History page Type filter expanded to all six
      types and reads `signal_type` from DB; Settings TP table now has a `Standard | Scalp | Toll |
      Swing | PA` tab strip over the per-asset grid plus a separate "1-1 fixed TP" card with global
      default + per-asset overrides table. New CSS badge classes in `frontend/src/index.css`:
      `.tag.swing`, `.tag.toll`, `.tag.pa`, `.tag.one-to-one`.
    - **Tests**: all `is_scalp=0` fixture references in `tests/test_*.py` updated to
      `signal_type="standard"`. `_make_supabase_row` returns `signal_type` and `channel_id`.

---

### Pre-Production Hardening — Phases 1–2 (decisions 73–82)

73. **Supabase pool max_size raised to 10 (M3)** — `bot/db/supabase.py`. Previous limit of 3 was
    too low for concurrent placement + SL sync + forced exit + fill detection calls within a single
    cycle. No config knob added; 10 is hardcoded alongside min_size=1.

74. **feed_health Supabase table (M5 writer)** — New table in TM: `feed_health (feed TEXT PRIMARY KEY,
    status TEXT, stale_seconds INTEGER, last_seen TIMESTAMPTZ, updated_at TIMESTAMPTZ)`. Written by
    TM's `FeedHealthMonitor` via `_write_feed_health()` on each health check (idle / healthy /
    degraded / down). The `FeedHealthMonitor` constructor now accepts an optional `db` parameter.
    EX reader side deferred to Phase 4.4 of the hardening plan.

75. **ic_bid / ic_ask columns on live_prices (H1 schema)** — TM's `live_prices` table gained two
    nullable `DOUBLE PRECISION` columns. TM writer and EX reader changes deferred to Phase 4.1.
    The schema migration is idempotent (ADD COLUMN IF NOT EXISTS).

76. **Limit skip logging in sync_cycle (L6)** — `sync_cycle.py` approval loop now populates
    `rejection_reason: dict[int, str]` (reasons: "symbol not in terminal" / "live price stale" /
    "outside proximity"). Placement loop logs INFO with `limit_id`, `signal_id`, `instrument`,
    `reason` for every skipped limit. Proximity filter upgraded from DEBUG → INFO. The tick/info-None
    case (previously silent) now logs a WARNING.

77. **C2: order-placement orphan window closed** — Three-part fix:
    (a) MT5 order comment changed from `s{signal_id}` to `s{signal_id}_l{limit_id}`[:32] so
        any orphan can be matched back to a claim row.
    (b) `place_order()` pre-writes a "claimed" row (`status='claimed'`, `mt5_ticket=-limit_id` as
        unique placeholder) before calling `order_send()`. On success, promotes claim to `pending`
        with the real ticket. On MT5 failure, deletes the claim. Crash between `order_send` and the
        promote → stale claim row detected by reconciler.
    (c) `reconcile_orphans()` extracted from `reconcile()`: parses comments, matches orphan MT5
        orders to claimed rows and promotes them; cleans stale claims that have no MT5 order; cancels
        truly untracked orders (magic-number filter added). Called every 60s by `_reconcile_loop`.

78. **C2: periodic reconciliation loop (M1 + orphan sweep)** — New `_reconcile_loop` task in
    `engine.py`. Runs `reconcile_orphans()` every 60 seconds (catches crash-window orphans without
    requiring a restart). Runs full `reconcile()` every 2 hours (M1 — detects position drift,
    missed fills, etc. that accumulate over time). Orphan sweep and full reconcile share the same
    task to avoid task proliferation.

79. **C3: cancel ordering — limits before signal (TM)** — All three TM cancel paths now update
    `limits.status = 'cancelled'` **before** `signals.status = 'cancelled'` within the same
    transaction. Affected functions: `cancel_signal_by_message`, `manually_set_signal_status`
    (final-status branch), `expire_old_signals`. Invariant documented inline in each function.
    Rationale: EX's Supabase query filters `WHERE l.status='pending'`, so EX stops seeing these
    limits as soon as they are cancelled — before the signal row transitions, preventing a placement
    window during the TM cancel.

80. **C3: pre-send status recheck (EX)** — `place_order()` now calls `supabase.fetch_signal_status(
    signal_id)` immediately before `order_send()`. If status is not in `{active, hit}`, the claim
    row is deleted and placement is aborted with a WARNING log. `SupabaseDB.fetch_signal_status()`
    added (`FETCH_SIGNAL_STATUS` query). `supabase` parameter added to `place_order()` signature
    and threaded from `sync_cycle.run()`.

81. **M2: external close detection** — New `_check_external_closes()` method in `SyncCycle`. Runs
    every cycle (outside the Supabase gate). For each SQLite `filled` row whose ticket is absent
    from the current `mt5_positions` list, calls `mark_closed()` and logs at INFO. Catches manual
    position closures in MT5 (by the user or broker) and keeps SQLite consistent. Runs before
    `_sync_filled_sls` and `_check_forced_exits` so those methods do not see stale filled rows.

82. **M14: idempotent update_ticket** — `UPDATE_TICKET` query now includes `AND status = 'filled'`
    (not `'pending'` — both call sites call `mark_filled` before `update_ticket`, so the row is
    already filled when the ticket update runs). `update_ticket()` returns `bool` indicating whether
    a row was actually updated. A second call with the same arguments is a no-op because the first
    call changes `mt5_ticket` to the new value, so `WHERE mt5_ticket = old_ticket` no longer matches.

### Owner UX + Production Log Fixes (decisions 83–88)

83. **Lot-sizing per-symbol exceptions** — `LotSizingConfig` gained an `exceptions: dict[str,
    LotExceptionConfig]` field where each entry has `{mode: "risk_percent" | "fixed", value:
    float}`. `LotCalculator.calculate()` checks `exceptions[mt5_symbol]` first; if present, the
    exception's mode and value override the global mode entirely. The pre-existing `risk_percent:
    float | dict` and `fixed_lot: float | dict` shapes are still honored for back-compat (legacy
    dict keys are migrated into the new Exceptions UI on load). The Settings page replaces the old
    fixed-lot per-instrument table with a unified Exceptions panel: each row has a symbol, a
    Risk%/Fixed toggle, and a value. Top-level `risk_percent` / `fixed_lot` save as flat floats
    (the global default for non-exception symbols).

84. **`profit` removed from `_FORCE_EXIT_STATUSES`** — `sync_cycle.py:74` now only force-closes on
    `cancelled` and `breakeven`. When TM clicks "profit" on a signal, EX keeps the position open
    and the TP engine continues to manage it (the engine has no awareness of Supabase signal
    status — it iterates SQLite filled positions). One INFO log fires on the `profit` transition
    so the carve-out is visible in `bot.log`. `is_trailing` is no longer flipped to 0 on `profit`,
    so trailing continues uninterrupted.

85. **`symbol_info_tick` failure cooldown (60s/symbol)** — `MT5Client.__init__` adds
    `_tick_unavailable_until: dict[str, float]`. After a failed `symbol_info_tick(symbol)` (None
    return), the next call for the same symbol is silently short-circuited for 60 seconds. Caps
    repeat ERROR spam at ~1/min/symbol for missing instruments (e.g. when a DB symbol is not in
    the broker's terminal) — previously the overnight production log accumulated thousands of
    `symbol_info_tick(US30USD) failed: Terminal: Not found` lines because `DashboardCache`
    bypassed `SyncCycle`'s 300s placement cooldown. Successful calls clear the cooldown entry.

86. **Default `symbol_map` + `offset_instruments` expanded** — `bot/config/settings.py` defaults
    now include `"US30USD": "US30"` in `symbol_map` and add `"US30USD"` + `"JP225"` to
    `offset_instruments`. Rationale: the production log showed `US30USD` symbol lookup errors
    (DB symbol, no MT5 mapping) and JP225 signal 2041 placed orders at `~67,000` (TM/OANDA feed
    space) while IC's JP225 trades far below that — limits expired without ever filling. With
    these instruments in `offset_instruments`, `OffsetCalculator` will compute `ic_mid − feed_mid`
    from `live_prices.ic_bid/ic_ask` (or fall back to live MT5 tick with a one-time WARNING per
    symbol if those columns are NULL).

87. **Reconciler orphan-cancel race fix** — `bot/core/reconciler.py:reconcile_orphans()` now
    re-checks SQLite via `get_order_by_ticket(ticket)` immediately before calling
    `cancel_pending_order()`. If the row is already `cancelled` / `spread_cancelled` / `filled` /
    `closed`, the orphan path is skipped (`continue`). Avoids the benign-but-noisy WARNING that
    fired when `order_canceller` and the orphan sweep ran in the same second on the same ticket
    (witnessed for JP225 ticket 1680604972). The WARNING for genuine failures now includes the
    MT5 retcode. New helper: `SQLiteDB.get_order_by_ticket()` + `GET_ORDER_BY_TICKET` SQL.

88. **Settings UI — "Trailing %" + per-symbol TP overrides** — UI-only changes; storage shape
    unchanged.
    (a) `Partial close` slider relabeled to `Trailing %`. Displayed value is `100 −
        partial_close_percent`; slider input is converted back on save. Helpers
        `partialToTrailing` / `trailingToPartial` at the top of `SettingsPage.tsx`. Applied
        across the Standard tab and every override tab (Scalp/Toll/Swing/PA).
    (b) Each asset-class row on the Standard tab gained a `+` button that expands an inline
        per-symbol overrides table (Symbol / Threshold / Trail dist. / Trailing %). Backed by
        the pre-existing `tp_config.instrument_overrides: dict[str, dict]` field; routing was
        already wired in `asset_config.get_config()`. Symbols are entered as DB-form (e.g.
        `SPX500USD`, `JP225`, `AMD.NAS`) — stock suffix mapping is handled internally. New
        utility `frontend/src/utils/assetClass.ts` ports `detect_asset_class` for grouping rows
        by asset class on load. Note in the UI: per-symbol overrides apply across all
        signal-type tabs (they layer on after signal-type routing).

---

## All Owner-Approved Decisions

These are final. Do not revisit or propose alternatives.

1. **UI stack**: FastAPI backend + React/TypeScript frontend (Vite), served at `localhost:8501`
2. **App shell**: System tray icon (pystray + Pillow) + auto-open browser on startup
3. **License validation**: Supabase Edge Function (Deno/TypeScript), not direct DB query or JWT
4. **Multiple signals per instrument**: Yes. MT5 order comment encodes both IDs: `"s{signal_id}_l{limit_id}"` (truncated to 32 chars). This allows orphan re-linking on restart (see decision 77).
5. **Signal expiry**: Handled by Supabase backend (bot reacts to status change in sync cycle, does NOT independently check expiry_time)
6. **TP threshold values**: From original spec — forex 7 pip/3 pip trail, metals $4/$2, indices $20/$5, stocks $1/$0.50, crypto $300/$50, oil $0.50/$0.20. Scalp values roughly halved.
7. **Partial close behavior**: ICMarkets hedging mode creates a NEW ticket for the remainder. Original ticket is fully closed. Fill detector tracks via comment matching (see decision #3 above).
8. **Stock suffix**: "-24" is permanent (means 24-hour trading, not the year). Still configurable in config.json.
9. **Config reload**: Hot-reload for ALL settings including TP thresholds. Re-read config.json each sync cycle.
10. **Spread adjustment**: On every order placement, adjust limit price and SL for current MT5 spread. Long: price+spread, SL-spread. Short: price-spread, SL+spread.
11. **Polling cadence**: Sync loop 1s when active, TP loop 2s when active (trailing doesn't need sub-second precision). 30s idle. 30-60s during spread hours/weekends. `symbol_info()` cached permanently; `positions_get()`/`orders_get()`/`account_info()` cached with 500ms TTL to collapse duplicate calls within a cycle.

---

## Known Risks and Fragile Areas

- **MT5 thread binding**: `mt5.initialize()` binds to the calling thread. ALL subsequent MT5 calls must happen on that same thread. FastAPI request handlers must NEVER call MT5Client methods.
- **asyncpg positional params**: Must be `conn.execute(q, val1, val2)` NOT `conn.execute(q, [val1, val2])`. Produces cryptic errors.
- **Supabase timestamps**: asyncpg returns native Python datetime objects. Do not pass to `datetime.fromisoformat()`.
- **Spread hour + startup**: Reconciler must run BEFORE spread-hour cancellation logic. Sequence: reconcile first, then check spread hour gate.
- **Config hot-reload race**: Read config once at cycle start, pass snapshot to all sub-calls within that cycle.
- **Feed offset + freshness**: Check freshness immediately before using the price, not at cycle start.
- **Asset class detection order**: Stocks (`.NAS`, `.NYSE`) checked before indices — enforced in `symbol_mapper.py`.
- **Partial close new ticket**: `detect_partial_close_tickets()` matches remainder positions by comment `s{signal_id}_l{limit_id}` against positions not yet in SQLite. If a comment is truncated or malformed, the remainder becomes an unmanaged orphan. The periodic `reconcile_orphans()` (every 60s) will catch and cancel it; monitor for orphan warnings in logs.
- **Claimed rows on Supabase outage**: If Supabase is unreachable during `fetch_signal_status()` in `place_order()`, the pre-send check raises and the placement is aborted (claim row is deleted). The limit will be retried next cycle when Supabase recovers.
- **SQLiteDB init_schema** must be called before any other SQLiteDB method or it will raise (connection is None).

---

## Intentionally Avoided Complexity
- No ORM — raw SQL for both asyncpg and aiosqlite
- No dependency injection framework — manual constructor injection
- No message queue — asyncio.Queue for internal log/status broadcasting
- No migration framework — inline ALTER TABLE ADD COLUMN in init_schema() with try/except
- No WebSocket — SSE is simpler and sufficient for one-way server-to-client streaming
- No React router — state-based page switching (`useState<Page>`) is sufficient for 3 pages
- No state management library — useState/useEffect + polling hook for dashboard data

### Frontend Dependencies (V3)
- `react` + `react-dom` 18.x
- `vite` 5.x + TypeScript — build tooling
- No chart library — custom SVG charts in `frontend/src/charts/` (recharts removed in V3)
- Google Fonts: Schibsted Grotesk + JetBrains Mono (loaded in index.html, no npm dep)
