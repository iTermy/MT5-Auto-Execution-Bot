# V5 Cross-Codebase Review: Bug Fixes & Hardening

**STATUS: COMPLETE — all 7 steps implemented. See STATE.md decisions 58–64.**

7 implementation steps across 4 phases. All changes are in the Execution Bot only — no Alert Bot or DB schema changes needed.

**Origin:** Full lifecycle trace across the Alert Bot (signal producer, `C:\Python Stuff\TM Bot`) and Execution Bot (order executor). The DB contract between the bots is sound. All findings are Execution Bot implementation bugs.

**Read STATE.md** before starting. All prior decisions (1–64) are final.

---

## Background Context for Implementor

### How offset instruments work
The Alert Bot writes signals with feed prices (OANDA for indices, Binance for crypto). The Execution Bot trades on ICMarkets MT5, which quotes different prices. The difference is the "offset": `offset = mt5_mid - feed_mid`. For indices like SPX, this offset is typically 2–10 points. For crypto like BTCUSD, it can be 10–100+ points.

The offset is calculated at placement time from the `live_prices` Supabase table (written by the Alert Bot every 5 seconds, OANDA + Binance feeds only).

**Which instruments need offset:** Configured in `config.json` → `offset_instruments` (default: `["SPX500USD", "NAS100USD", "BTCUSDT", "ETHUSDT"]`).

### How SL adjustment works
The DB stop_loss is in feed price space. When placing an MT5 order, the SL must be translated:
- **Long:** `mt5_sl = db_sl + offset - spread` (SL below entry; bid triggers)
- **Short:** `mt5_sl = db_sl + offset + spread` (SL above entry; ask triggers)

The `spread` is the current MT5 spread (`tick.ask - tick.bid`).

### How force exit works
The sync cycle monitors signal statuses via `fetch_signal_statuses()`. When a signal transitions from `hit` → `cancelled` or `hit` → `breakeven`, all filled positions for that signal are market-closed. The transition detection uses an in-memory dict `_last_signal_status` that maps `signal_id → last_seen_status`.

---

## Phase 1: Critical money-safety fixes

### Step 1: Add offset to SL at order placement

**File:** `bot/trading/order_placer.py`

**Bug:** The entry price is correctly offset-adjusted on line 41 (`base_price = db_price + (offset or 0.0)`), but the SL is NOT offset-adjusted on lines 45 and 54. For offset instruments, this places the MT5 SL at the wrong price — off by the entire offset amount.

Example: SPX signal with `db_sl=4990.0`, offset=+5.0, spread=1.5:
- Current (wrong): `mt5_sl = 4990.0 - 1.5 = 4988.50`
- Correct: `mt5_sl = 4990.0 + 5.0 - 1.5 = 4993.50`
- Error: SL is 5 points wider than intended

**Fix:** Add `(offset or 0.0)` to both `adj_sl` calculations:

Line 45 (long):
```python
# BEFORE:
adj_sl = round(db_stop_loss - spread, info.digits)
# AFTER:
adj_sl = round(db_stop_loss + (offset or 0.0) - spread, info.digits)
```

Line 54 (short):
```python
# BEFORE:
adj_sl = round(db_stop_loss + spread, info.digits)
# AFTER:
adj_sl = round(db_stop_loss + (offset or 0.0) + spread, info.digits)
```

**Verify:** Place a pending order on an offset instrument (e.g., US500). Check that `mt5_sl ≈ db_sl + offset ± spread`.

---

### Step 2: Floor partial close volume to volume_step

**File:** `bot/tp/default_strategy.py`

**Bug:** Line 120 uses `round(newest.volume * pct / 100, 2)` which rounds to 2 decimal places. For instruments where `volume_step = 0.1` (common for indices), this can produce invalid volumes (e.g., 0.15 → rejected by MT5 with `TRADE_RETCODE_INVALID_VOLUME`). The lot calculator (`bot/trading/lot_calculator.py:22-27`) correctly floors to volume_step.

**Fix:** Replace line 120 with volume_step-aware rounding:

```python
import math  # add to imports at top of file

# In the partial close branch (around line 116-120):
sym_info = mt5_client.symbol_info(newest.symbol)
raw_vol = newest.volume * pct / 100
if sym_info and sym_info.volume_step > 0:
    close_vol = math.floor(raw_vol / sym_info.volume_step) * sym_info.volume_step
    close_vol = round(close_vol, 8)  # float precision cleanup
    close_vol = max(close_vol, sym_info.volume_min)
else:
    close_vol = round(raw_vol, 2)
```

Also add a guard: if `close_vol <= 0` after rounding, skip the partial close and trail the full position instead (same as `pct <= 0` branch).

**Verify:** Set up a TP trigger on an instrument with `volume_step=0.1`. With position volume=0.3 and pct=50, the close volume should be 0.1 (floored from 0.15), not 0.15. Confirm MT5 accepts it.

---

### Step 3: Guard against Supabase outage mass-cancellation

**Files:** `bot/db/supabase.py`, `bot/core/sync_cycle.py`

**Bug:** `fetch_active_signals()` (supabase.py:27-32) catches `asyncpg.PostgresError` and returns `[]`. The sync cycle then sees `supabase_limit_ids` as empty, treats ALL pending orders as stale (limit_id not in empty set), and cancels every one. When the connection restores, orders re-place but potentially at different prices or order types (LIMIT→STOP if price moved past the limit level).

**Fix (two parts):**

**Part A — supabase.py:** Change `fetch_active_signals` to re-raise instead of swallowing:
```python
async def fetch_active_signals(self) -> list[asyncpg.Record]:
    async with self._pool.acquire() as conn:
        return await conn.fetch(FETCH_ACTIVE_SIGNALS_WITH_LIMITS)
```
Remove the try/except. Let the error propagate.

Do the same for `fetch_live_prices` and `fetch_signal_statuses` — remove their try/excepts and let errors propagate. The caller should decide what to do.

**Part B — sync_cycle.py:** In `run()`, wrap the Supabase-dependent section. Fill detection (which uses MT5 + SQLite only) must still run even if Supabase is down:

```python
async def run(self, supabase, sqlite, mt5_client, config, scheduler, placement_active=True):
    result = SyncResult()

    # --- Supabase-dependent section ---
    try:
        supabase_rows = await supabase.fetch_active_signals()
    except Exception:
        logger.error("Supabase fetch failed — skipping placement phase, running fill detection only", exc_info=True)
        supabase_rows = None

    if supabase_rows is not None:
        # ... all existing placement, stale-cancel, SL sync logic (lines 126-456) ...
        # (indent this entire block inside the if)

    # --- MT5-only section (always runs) ---
    # Fill detection, partial close detection (lines 408-441)
    # ... existing code from "Always detect fills" onward ...
    
    # Forced exit needs supabase_by_signal — only run if supabase succeeded
    if supabase_rows is not None:
        await self._sync_filled_sls(...)
        await self._check_forced_exits(...)

    return result
```

The key insight: fill detection and partial close detection only need MT5 + SQLite. SL sync, forced exits, and stale-cancel need Supabase. Keep them separate.

**Verify:** Set an invalid Supabase DSN temporarily. Run 3 sync cycles. Confirm pending orders survive and fill detection still works. Restore DSN, confirm normal operation.

---

## Phase 2: Force-exit reliability

### Step 4: Remove `previous != "hit"` guard in force exit

**File:** `bot/core/sync_cycle.py`, method `_check_forced_exits`, around line 557-562

**Bug:** On restart, `_last_signal_status` (line 111) is empty (in-memory dict). If a signal transitions from `hit` → `cancelled` during the restart window:
- `previous = self._last_signal_status.get(signal_id)` → `None`
- `if previous != "hit": continue` → skips force exit
- Positions remain open permanently (force exit never retries)

The `previous == current` check on line 559 already prevents re-triggering on steady state, making the `previous != "hit"` guard redundant.

This is also safe for non-hit signals: `filled_sids` only contains signals that have filled positions in SQLite. If a signal goes `active` → `cancelled` (never hit, no fills), it won't be in `filled_sids`.

**Fix:** Remove line 561-562:
```python
# BEFORE:
if current not in _FORCE_EXIT_STATUSES:
    continue
if previous == current:
    continue
if previous != "hit":    # <-- REMOVE THIS LINE
    continue             # <-- REMOVE THIS LINE

# AFTER:
if current not in _FORCE_EXIT_STATUSES:
    continue
if previous == current:
    continue
```

**Verify:** Start the bot with a signal that has filled positions and status `cancelled` in Supabase (`_last_signal_status` is empty on startup). Verify force exit triggers on the first cycle.

---

### Step 5: Retry force exit on partial failure

**File:** `bot/core/sync_cycle.py`, method `_check_forced_exits`, around lines 564-593

**Bug:** `_last_signal_status[signal_id]` is set to the current status at line 555 (before the close loop). If some position closures fail (MT5 transient error), next cycle sees `previous == current` → skip. The unclosed positions are permanently orphaned from force exit.

**Fix:** Move the status update to after the close loop, and only commit if all positions were successfully closed:

```python
# In _check_forced_exits, restructure the loop:
for signal_id in filled_sids:
    current = status_map.get(signal_id)
    if current is None:
        continue

    previous = self._last_signal_status.get(signal_id)
    # DON'T update _last_signal_status here yet

    if current not in _FORCE_EXIT_STATUSES:
        self._last_signal_status[signal_id] = current  # safe to update for non-exit statuses
        continue
    if previous == current:
        continue

    logger.warning(...)

    all_closed = True
    filled_rows = await sqlite.get_filled_positions()
    for row in filled_rows:
        if row["signal_id"] != signal_id:
            continue
        ticket = row["mt5_ticket"]
        pos = pos_by_ticket.get(ticket)
        if pos is None:
            continue
        res = mt5_client.close_position(
            ticket=pos.ticket, symbol=pos.symbol, volume=pos.volume,
            position_type=pos.type, comment=f"force_{current}",
        )
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            await sqlite.mark_closed(ticket, pos.profit)
            logger.info("Forced exit closed ticket=%d signal=%d", ticket, signal_id)
        else:
            retcode = res.retcode if res else "None"
            logger.error("Forced exit close failed ticket=%d retcode=%s", ticket, retcode)
            all_closed = False

    if all_closed:
        self._last_signal_status[signal_id] = current
    # else: leave previous status so next cycle retries
```

**Verify:** Mock `close_position` to fail on a specific ticket. Confirm the force exit retries on the next cycle for the failed ticket.

---

## Phase 3: SL sync offset improvement

### Step 6: Use current offset in SL sync

**File:** `bot/core/sync_cycle.py`, method `_sync_filled_sls`

**Bug:** Line 509 uses `offset = row["offset_at_placement"] or 0.0`. The DB SL is an absolute price in feed space, not a distance from entry. When the DB SL changes and the SL sync fires, it should translate the new absolute price using the current offset, not the stale placement offset. If the feed-to-MT5 offset has drifted since placement, the new MT5 SL will be inaccurate.

**Fix:**

1. Pass `live_prices` dict into `_sync_filled_sls` (it's already available in `run()`):

```python
# In run(), change the call:
await self._sync_filled_sls(
    sqlite, mt5_client, mt5_positions, supabase_by_signal, config, live_prices
)
```

2. Update `_sync_filled_sls` signature and offset calculation:

```python
async def _sync_filled_sls(
    self, sqlite, mt5_client, mt5_positions, supabase_by_signal, config, live_prices
):
    ...
    # Replace lines 504-509:
    offset = 0.0
    if needs_offset(instrument, config):
        live_row = live_prices.get(instrument)
        if live_row is not None:
            current_offset = self._offset_calc.get_offset(
                mt5_sym, live_row, mt5_client, config.feed_max_staleness_seconds
            )
            if current_offset is not None:
                offset = current_offset
            else:
                offset = row["offset_at_placement"] or 0.0  # fallback to placement offset
        else:
            offset = row["offset_at_placement"] or 0.0  # fallback if no live price
    ...
```

Note: `live_prices` may be empty if no offset instruments needed prices this cycle. The fallback to `offset_at_placement` handles that case.

**Verify:** On an offset instrument with a filled position, change the DB SL in Supabase. Verify the new MT5 SL uses the current offset (check logs for the calculated values).

---

## Phase 4: Documentation

### Step 7: Fix MAGIC_NUMBER in CLAUDE.md

**File:** `CLAUDE.md`

**Bug:** CLAUDE.md says "All MT5 orders use magic number `20260001`" but `bot/config/constants.py:6` and `bot/config/settings.py:67` both have `20250001`.

**Fix:** Update CLAUDE.md to say `20250001` wherever `20260001` appears.

Also update STATE.md with a new decision entry for this V5 review (decision 58+), documenting the fixes made.

---

## Implementation Order

Execute phases 1→2→3→4 in order. Within Phase 1, do steps 1→2→3 sequentially (step 3 restructures the sync cycle flow, so do the simpler fixes first).

**No Alert Bot changes needed.** No DB schema changes. No frontend changes. All fixes are backend Python in the `bot/` directory.

**After all fixes:** Run the bot against live MT5 (paper or demo account) and verify:
1. Offset instruments place orders with correct SL
2. TP partial close produces valid volumes
3. Pending orders survive a temporary Supabase disconnect
4. Force exit works after a cold restart
5. SL sync uses current offset values
