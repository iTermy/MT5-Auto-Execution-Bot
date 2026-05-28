# Implementation Order — Exact Next Steps

Each phase is testable independently. Do not skip ahead.

**RESUME FROM: Phase 11, Step 37 — React frontend scaffold**
Phases 1–10 (steps 1–36) are complete. See STATE.md for implementation decisions made during build.

---

## [DONE] Phase 1: Project Scaffolding
```
1.  Directory tree created
2.  __init__.py in every bot/ subdirectory + tests/
3.  .gitignore
4.  requirements.txt
5.  config.example.json
6.  .env.example
```

## [DONE] Phase 2: Config + Constants
```
7.  bot/config/constants.py — MAGIC_NUMBER, AssetClass, OrderStatus (incl. CLOSED), DEFAULT_TP_CONFIG
8.  bot/config/settings.py  — Pydantic models, load_config(), load_dsn(), load_license_url()
```

## [DONE] Phase 3: MT5 Client
```
9.  bot/mt5/types.py       — 8 dataclasses incl. OrderInfo, DealInfo
10. bot/mt5/connection.py  — MT5Connection
11. bot/mt5/client.py      — MT5Client + cancel_pending_order() [added during Phase 6]
```

## [DONE] Phase 4: Database Modules
```
12. bot/db/queries.py   — all SQL constants (Supabase + SQLite)
13. bot/db/supabase.py  — SupabaseDB with persistent pool
14. bot/db/sqlite.py    — SQLiteDB with persistent connection, WAL mode
```

## [DONE] Phase 5: Utilities
```
15. bot/utils/logging.py    — setup_logging(), SSELogHandler, get_log_queue()
16. bot/utils/time_utils.py — to_est(), MarketScheduler (full spread-hour logic)
```

## [DONE] Phase 6: Trading Modules
```
17. bot/trading/symbol_mapper.py     — detect_asset_class(), map_symbol(), needs_offset()
18. bot/trading/lot_calculator.py    — LotCalculator.calculate(stop_loss, limit_prices, mt5_symbol)
19. bot/trading/offset_calculator.py — OffsetCalculator: get_offset(), apply_offset(), check_drift()
20. bot/trading/order_placer.py      — OrderPlacer.place_order() [async]
21. bot/trading/order_canceller.py   — OrderCanceller.cancel_order() [async]
22. bot/trading/fill_detector.py     — FillDetector, FillEvent, NewTicketEvent
```

---

## [DONE] Phase 7: TP Engine
```
23. bot/tp/asset_config.py
    - AssetClassConfig dataclass: profit_threshold, threshold_unit, partial_close_percent,
      trailing_distance
    - get_config(asset_class, is_scalp, config) -> AssetClassConfig
    - Merge order: base defaults < scalp_overrides < instrument_overrides

24. bot/tp/strategy.py
    - TPStrategy Protocol with should_trigger(), execute(), update_trailing()
    - TPResult dataclass: closed_tickets, trailed_tickets, errors

25. bot/tp/default_strategy.py
    - DefaultTPStrategy implementing TPStrategy
    - should_trigger: newest pos P&L >= threshold AND sum(others P&L) >= 0
    - execute: close earlier positions, partial-close newest, trail remainder
    - update_trailing: ratchet SL in favorable direction only

26. bot/tp/trailing.py
    - TrailingStopManager class
    - update(position, tick, asset_config, mt5_client, sqlite)
    - SL ratchet: long -> SL = bid - trail_distance; short -> SL = ask + trail_distance
    - SL only moves favorably, never retreats

27. bot/tp/engine.py
    - TPEngine class
    - run_cycle(mt5_client, sqlite, config): groups positions by signal_id,
      delegates to strategy, manages trailing
    - Must never crash the main loop — catch, log, continue per group
```

## [DONE] Phase 8: Core Orchestration
```
28. bot/core/scheduler.py
    - Import MarketScheduler from bot.utils.time_utils (no logic duplication)
    - Re-export or thin wrapper only

29. bot/core/sync_cycle.py
    - SyncCycle class
    - run(supabase, sqlite, mt5_client, config, scheduler) -> SyncResult
    - Full idempotent iteration: fetch signals, diff vs SQLite, place new orders,
      cancel stale orders, detect fills, adjust offset drift
    - Read config snapshot ONCE at start, use for entire cycle

30. bot/core/reconciler.py
    - Reconciler class
    - reconcile(mt5_client, sqlite) -> ReconciliationResult
    - Five cases (see ARCHITECTURE.md Startup Reconciliation):
      pending+in MT5 orders -> no change
      pending+in MT5 positions -> mark filled
      pending+gone from MT5 -> mark cancelled
      filled+gone from MT5 -> mark closed
      filled+is_trailing=1+in MT5 -> resume trailing
    - MT5 orders with our magic but not in SQLite -> log warning only, do NOT cancel

31. bot/core/engine.py
    - Engine class: the main orchestrator
    - run_forever(): starts async tasks (sync loop, tp loop, license heartbeat, FastAPI)
    - start() / stop() called from FastAPI routes
    - Holds all dependencies: mt5_client, supabase, sqlite, config, scheduler, tp_engine,
      license_validator
    - Broadcasts status updates to SSE queue after each sync cycle
```

## [DONE] Phase 9: License
```
32. bot/license/models.py
    - LicenseStatus enum: VALID, INVALID, EXPIRED, ERROR
    - LicenseResult dataclass: status, expires_at, message

33. bot/license/validator.py
    - LicenseValidator class
    - validate(license_key, mt5_account) -> LicenseResult (HTTP POST via httpx to Edge Function)
    - heartbeat_loop(interval_seconds): re-validates on schedule
    - On failure: flag license_valid=False; engine skips new placements but keeps managing positions
```

## [DONE] Phase 10: FastAPI Backend
```
34. bot/api/sse.py
    - SSEBroadcaster class: add_client(), remove_client(), broadcast()
    - Consumes from log queue (bot/utils/logging.py get_log_queue()) and status queue
    - Formats as SSE with event types: "log", "status"

35. bot/api/routes.py
    - GET /api/status         — {engine_running, license_valid, mt5_connected, supabase_connected,
                                  pending_count, open_count, trailing_count}
    - GET /api/config         — current config.json as JSON
    - PUT /api/config         — Pydantic validates, writes file, hot-reload takes effect next cycle
    - POST /api/engine/start
    - POST /api/engine/stop
    - GET /api/logs           — SSE stream
    - GET /api/status/stream  — SSE stream
    - IMPORTANT: no MT5 calls in any handler — MT5 is engine-thread only

36. bot/api/app.py
    - create_app(engine) -> FastAPI
    - Mount StaticFiles from frontend/dist/ at "/"
    - CORS middleware for dev only (allow origin :5173)
```

## [DONE] Phase 11: React Frontend
```
37. Scaffolded manually: frontend/package.json, tsconfig.json, tsconfig.node.json,
    vite.config.ts, index.html, src/main.tsx, src/index.css, src/types.ts

38. frontend/src/api.ts
    - fetchStatus(), fetchConfig(), updateConfig(), startEngine(), stopEngine()
    - Base URL "" in production; vite.config.ts proxy /api -> :8501 in dev

39. frontend/src/hooks/useSSE.ts
    - Connects to /api/logs and /api/status/stream
    - Auto-reconnect on error (3s delay), alive flag prevents reconnect after unmount
    - Returns { logs: LogEntry[], status: StatusData | null, connected: bool }

40. frontend/src/components/:
    - LicensePanel.tsx  — text input, Save button, green/red status dot from SSE status
    - ControlPanel.tsx  — start/stop toggle, lot mode radio (Risk % / Fixed) with
                          contextual number inputs, MT5 dot, Supabase dot
    - LogPanel.tsx      — auto-scrolling div, entries colored by level
                          (DEBUG=gray, INFO=slate, WARNING=amber, ERROR=red)
    - StatusBar.tsx     — pending / open / trailing counts + UI connected dot

41. frontend/src/App.tsx — single-page layout composing all 4 components
```

## [DONE] Phase 12: Entry Point + Tray
```
42. main.py
    - setup_logging(), load_config() (exits if missing), load_dsn/license_url
    - Wires: MT5Connection -> MT5Client, SupabaseDB, SQLiteDB, TPEngine, LicenseValidator, Engine
    - engine.app = create_app(engine)
    - engine_thread: _run_engine(conn, engine) = conn.initialize() + asyncio.run(run_forever()) + conn.shutdown()
    - Polls /api/status with urllib (30s timeout), opens browser when ready
    - pystray tray: "Open UI" (webbrowser.open) / "Exit" (engine.shutdown() + icon.stop())
    - After icon.run() returns: engine_thread.join(10) + sys.exit(0)

    Engine.shutdown() added: cancels all asyncio tasks via loop.call_soon_threadsafe()
    Engine._loop and Engine._tasks stored in run_forever() for cross-thread access
```

## [DONE] Phase 13: Edge Function + Docs
```
43. supabase/functions/validate-license/index.ts
    - Deno.serve handler; POST {license_key, mt5_account}
    - Uses @supabase/supabase-js with SUPABASE_SERVICE_ROLE_KEY
    - Checks: row exists, active=true, mt5_account matches, not expired
    - Returns {status: valid|invalid|expired|error, expires_at, message}

44. CONTRIBUTING.md
    - Dev setup: pip install, .env, config.json copy, python main.py / npm run dev
    - contributor_bot SQL (CREATE ROLE + GRANT SELECT) + monthly rotation
    - Owner prod build: fill constants.py, npm run build, pyinstaller bot.spec, revert
    - Edge Function deploy via supabase CLI
    - licenses table schema

45. bot.spec
    - datas: frontend/dist -> frontend/dist
    - hiddenimports: asyncpg + asyncpg.protocol.protocol, aiosqlite, MetaTrader5,
      pystray + pystray._win32, PIL + PIL.Image,
      uvicorn.loops.none, uvicorn.protocols.http.auto,
      uvicorn.protocols.websockets.auto, uvicorn.lifespan.on
    - onefile=True, console=False, name=MT5Bot
```

## [DONE] Phase 14: Tests
```
46. pytest.ini + tests/conftest.py
    - asyncio_mode=auto; fixtures: sqlite_db (:memory:), mock_mt5, sample_config
    - Factories: make_settings, make_symbol_info, make_tick, make_position,
      make_order_info, make_order_result, make_account_info

47. tests/test_symbol_mapper.py
    - 21 parametrized detect_asset_class cases covering all 7 classes
    - Explicit edge cases: BTCUSD(len=6)=FOREX, AMD.NAS=STOCKS not INDICES
    - map_symbol: symbol_map lookup, stock suffix append, passthrough
    - db_symbol_from_mt5: reverse symbol_map, strip suffix, passthrough

48. tests/test_lot_calculator.py
    - risk% basic (1 limit), multi-limit, floor-not-round (0.059→0.05 not 0.06)
    - Fixed mode, clamp to min (wide SL), clamp to max_lot_per_order, fallback on None

49. tests/test_tp_engine.py
    - should_trigger: dollars mode pass/fail, others<0 blocks, pips mode pass/fail
    - execute: pct=0 (set_trailing, no close), pct=100 (close all), pct=50 (close_vol=0.5*vol)
    - Multiple positions: earlier positions closed before newest

50. tests/test_trailing.py
    - Long: initial sl=0 set, ratchets up, never retreats
    - Short: ratchets down, never retreats
    - Pips mode: trail_pips*pip_size used for price distance

51. tests/test_sync_cycle.py
    - Idempotency: known limit not re-placed (twice)
    - Spread hour: cancels pending, skips new placements
    - Offset drift: patched check_drift=True → cancelled for re-placement

52. tests/test_reconciler.py
    - Case 1: pending+in MT5 orders → no change
    - Case 2: pending+in positions → mark_filled + update_ticket on hedging mismatch
    - Case 3: pending+gone → mark_cancelled
    - Case 4: filled+gone → mark_closed
    - Case 5: filled+trailing+in MT5 → trailing_resumed count
    - Orphan: untracked MT5 order → orphans++ no cancel
    - Mixed: all cases together
```
