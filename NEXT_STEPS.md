# Post-MVP Fixes, V2 Dashboard Overhaul

Original 52 steps (14 phases) are complete. Post-MVP fixes applied (decisions 31-37).
V2 dashboard overhaul applied (decisions 38-46).

See STATE.md for rationale behind each change.

---

## [DONE] Phase 1: Fix TP Partial Close (Critical Bug)
```
1. bot/tp/default_strategy.py — set is_trailing after successful partial close
2. bot/core/sync_cycle.py     — mark original closed when remainder found
```

## [DONE] Phase 2: Cancel Pending Orders on TP Fire
```
3. bot/db/queries.py + bot/db/sqlite.py — GET_PENDING_BY_SIGNAL query + method
4. bot/tp/engine.py — _cancel_pending_for_signal() after execute()
```

## [DONE] Phase 3: SL Sync for Filled Positions
```
5. bot/db/queries.py + bot/db/sqlite.py — UPDATE_DB_STOP_LOSS query + method
6. bot/core/sync_cycle.py — _sync_filled_sls() method, called from run()
```

## [DONE] Phase 4: Forced Exit on Signal Cancellation
```
7. bot/db/queries.py + bot/db/supabase.py — FETCH_SIGNAL_STATUSES + fetch_signal_statuses()
8. bot/db/queries.py + bot/db/sqlite.py — GET_FILLED_SIGNAL_IDS + get_filled_signal_ids()
9. bot/core/sync_cycle.py — _check_forced_exits() method, called from run()
```

## [DONE] Phase 5: Orphan Sweep + Pending SL Change Detection
```
10. bot/core/reconciler.py — cancel orphan orders instead of just logging
11. bot/core/sync_cycle.py — detect SL changes on pending orders, cancel for re-placement
```

## [DONE] Phase 6: Config Snapshot in TP Loop
```
12. bot/core/engine.py — snapshot config at cycle start in _tp_loop()
```

## [DONE] Phase 7: Documentation Update
```
13. STATE.md — decisions 31-37, supersede decision #16
14. NEXT_STEPS.md — this file (replaced original 52-step plan)
```

---

# V2 Dashboard Overhaul (decisions 38-46)

## [DONE] Phase 8: Log Timing Fix
```
15. bot/api/sse.py        — 200-message replay buffer in SSEBroadcaster
16. bot/core/engine.py    — API-first startup (api_ready event, await before init)
17. bot/api/app.py        — set engine.api_ready in FastAPI lifespan
```

## [DONE] Phase 9: Symbol Handling
```
18. bot/config/settings.py      — excluded_symbols + stock_no_suffix fields
19. config.json                 — excluded_symbols: ["USOILSPOT"], stock_no_suffix: []
20. bot/core/sync_cycle.py      — filter excluded symbols early, stock suffix fallback + persist
21. bot/trading/symbol_mapper.py — map_symbol checks stock_no_suffix before appending suffix
```

## [DONE] Phase 10: Shutdown Button
```
22. bot/core/engine.py   — _shutdown_callback + set_shutdown_callback(), invoked in shutdown()
23. main.py              — tray icon created before engine thread, callback wired
24. bot/api/routes.py    — POST /api/engine/shutdown endpoint
```

## [DONE] Phase 11: Dashboard Backend
```
25. bot/core/dashboard_cache.py — DashboardCache + DashboardData (new file)
26. bot/core/engine.py          — dashboard_cache update at end of sync loop
27. bot/db/queries.py           — realized_pnl + symbol in schema, GET_ORDER_HISTORY
28. bot/db/sqlite.py            — migrations, mark_closed(+pnl), insert_order(+symbol), get_order_history()
29. bot/api/routes.py           — GET /api/dashboard, GET /api/history
30. bot/trading/order_placer.py — passes mt5_symbol to insert_order
31. bot/tp/default_strategy.py  — passes pos.profit to mark_closed
32. bot/core/sync_cycle.py      — passes pos.profit (forced exit), symbol (partial close) to SQLite
```

## [DONE] Phase 12: Frontend Redesign
```
33. frontend/src/types.ts              — Dashboard, History, Position, Account interfaces
34. frontend/src/api.ts                — fetchDashboard, fetchHistory, shutdownEngine
35. frontend/src/hooks/useDashboard.ts — polling hook (2s)
36. frontend/src/App.tsx               — page navigation, log drawer toggle
37. frontend/src/pages/*               — DashboardPage, HistoryPage, SettingsPage
38. frontend/src/components/*          — NavSidebar, TopBar, LogDrawer, tables, metrics, stats
39. frontend/src/index.css             — professional dark theme overhaul
40. Deleted: StatusBar, ControlPanel, LicensePanel, LogPanel
```

## [DONE] Phase 13: Documentation Update
```
41. CLAUDE.md      — updated status, concurrency, decisions, file layout
42. STATE.md       — decisions 38-46, updated module listings
43. NEXT_STEPS.md  — this section
```
