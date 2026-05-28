# Post-MVP Fixes & Robustness Improvements

Original 52 steps (14 phases) are complete. These are the post-MVP improvements
applied after testing revealed TP system bugs and missing V1 robustness features.

See STATE.md decisions 31-37 for rationale behind each change.

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
