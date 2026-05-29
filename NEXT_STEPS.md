# V4 Frontend Integration & Bug Fix Plan

All previous phases complete. V3 frontend redesign done (decision 47).
This plan addresses integration bugs and missing features found during verification.

See STATE.md for rationale behind each change.
See the Claude Design handoff bundle for the original design spec.

**Design handoff URL:** `https://api.anthropic.com/v1/design/h/RPbvg2peILYI047ReM_z0A?open_file=Trading+Dashboard.html`

---

## Phase 1: Critical Backend Fixes (unblocks everything else)

### Step 1: Fix MARK_CLOSED timestamp bug
```
bot/db/queries.py — MARK_CLOSED must set cancelled_at = datetime('now')
```
**Bug:** `MARK_CLOSED` (line 70-72) sets `status='closed'` and `realized_pnl` but never sets
`cancelled_at`. The SQLite schema has no `closed_at` column — `cancelled_at` doubles as the
close timestamp. Since it's never set for closed trades, `/api/history` returns `closed_at: ""`
for every closed trade.

**Impact:** `computeCumulativePnl()` in `stats.ts:99` filters `t.status === 'closed' && t.closed_at`
— the falsy `""` eliminates ALL closed trades. Equity curve, daily P&L bars, recent trades,
and hold time calculations are all empty/broken.

**Fix:** Change `MARK_CLOSED` to:
```sql
UPDATE order_mappings SET status = 'closed', cancelled_at = datetime('now'), realized_pnl = ? WHERE mt5_ticket = ?
```

### Step 2: Add channel_id to data pipeline
```
bot/db/queries.py              — Add s.channel_id to FETCH_ACTIVE_SIGNALS_WITH_LIMITS SELECT
                                 Add channel_id column to CREATE_ORDER_MAPPINGS schema
                                 Add channel_id to INSERT_ORDER and GET_ORDER_HISTORY
bot/db/sqlite.py               — Column migration for channel_id; update insert_order signature
bot/trading/order_placer.py    — Pass channel_id through to insert_order
bot/core/dashboard_cache.py    — Include channel_id in position/pending_order dicts
bot/api/routes.py              — Include channel_id in history trade objects
frontend/src/types.ts          — Add channel_id: number to PendingOrderData, PositionData, TradeData
```
The Supabase `signals` table has `channel_id` (Discord channel ID). This enables showing
channel names and deriving signal types (Scalp/Swing/Tolls/Standard) on the frontend.

**Channel ID → Name/Type mapping** (hardcode in frontend `utils/channels.ts`):
```
1402971916339380244 → Daily Setup       (Standard)
1402971964343320636 → Scalps            (Scalp)
1402972132920787077 → Forex Exotics     (Standard)
1402972164256432220 → Gold              (Standard)
1402972289993019463 → Oil               (Standard)
1402972348193177745 → Indices           (Standard)
1402972426014429254 → Crypto            (Standard)
1402972455990984774 → Stocks            (Standard)
1402972635847200838 → Swings            (Swing)
1402972674082476102 → OT Calls          (Standard)
1406127169448575098 → Proper Calls      (Standard)
1403532013511905434 → Crypto Alts       (Standard)
1402972075446239303 → Price Action      (Standard)
1402972221953019986 → Gold PA           (Standard)
1472685381315989730 → Gold Tolls        (Tolls)
1477339674166169911 → General Tolls     (Tolls)
1484316173515489392 → Oil Tolls         (Tolls)
1500246110491639818 → Legends           (Standard)
```

### Step 3: Frontend timestamp fallback + utilities
```
frontend/src/utils/stats.ts    — Fix timestamp fallbacks in computeCumulativePnl, computeDailyBars,
                                 computeDetailedStats; add filterTradesByPeriod(), groupBySignalId()
frontend/src/utils/channels.ts — New file: channel ID mapping, getChannelName(), getSignalType()
```
Existing closed rows in SQLite have NULL `cancelled_at`. Frontend must use
`t.closed_at || t.filled_at || t.placed_at` as fallback everywhere.

Add `filterTradesByPeriod(trades, 'daily'|'weekly'|'all')` for P&L period toggles.
Add `groupBySignalId(items)` — generic grouper reused by dashboard and history.

---

## Phase 2: Dashboard Page Fixes

### Step 4: Reorder sections
```
frontend/src/pages/DashboardPage.tsx — Swap Positions and Closest Signals JSX blocks
```
Current order: Hero → Closest Signals → Positions → Recent+Daily
New order: Hero → Positions → Closest Signals → Recent+Daily

### Step 5: Fix P&L period filtering
```
frontend/src/pages/DashboardPage.tsx — Use filterTradesByPeriod before computing curve/bars/stats
```
Currently the Day/Week/All toggle changes the label but doesn't filter data.
Must filter trades before computing curve, daily bars, and win/loss stats.
Compute win/loss from filtered trades instead of backend `stats` (no period awareness).

### Step 6: Group Closest Signals by signal_id
```
frontend/src/pages/DashboardPage.tsx — Group pendingOrders by signal_id for card display
```
Group pending orders by `signal_id`. Each card shows: symbol, direction, limit count,
closest distance (min of all limits in group), proximity meter, channel name, signal type
(from `channels.ts`).

### Step 7: Group Recent Trades by signal_id
```
frontend/src/pages/DashboardPage.tsx — Group closed trades by signal_id in recent trades table
```
Each row: symbol, side, limit count, total P&L (aggregated), close time.

### Step 8: Increase dashboard poll rate
```
frontend/src/hooks/useDashboard.ts — Change default interval from 2000 to 1000
```

---

## Phase 3: History Page Fixes

### Step 9: Add missing filter controls
```
frontend/src/pages/HistoryPage.tsx — Add Instrument dropdown, expanded Type Seg, Sort by dropdown
```
- **Instrument dropdown**: `<select>` with "All" + unique symbols from trades
- **Type filter**: Expand Seg to All/Standard/Scalp/Tolls/Swings/1-1. Derive type from
  `channel_id` via `getSignalType()`.
- **Sort by**: Dropdown with Newest, Oldest, P&L High→Low, P&L Low→High, Symbol A→Z

### Step 10: Group trades by signal_id
```
frontend/src/pages/HistoryPage.tsx — Group filtered trades by signal_id, aggregate P&L/lots
```
Define `SignalGroup`: `{signalId, symbol, direction, totalLots, totalPnl, tradeCount, closedAt,
status, isScalp, channelId}`. Table columns: Closed, Symbol, Side, Limits, Total Lots, Type,
Status, Total P&L.

Performance stats grid (`computeDetailedStats`) stays trade-level — win rate, streaks, and
expectancy are per-trade metrics.

---

## Phase 4: Settings Page Fixes

### Step 11: Update Config type
```
frontend/src/types.ts — Replace loose Config interface with full typed shape matching Settings model
```
Add interfaces: `AssetTPConfig`, `ScalpOverrideConfig`, `TPConfig`, `PollingConfig`,
`SpreadHourConfig`. Add all fields: `symbol_map`, `stock_suffix`, `tp_config`, etc.

### Step 12: Fix TP Config rendering
```
frontend/src/pages/SettingsPage.tsx — Parse tp_config as object (not array), remove visibility guard
```
**Bug:** Code reads `config.tp_config` as array (`Array.isArray(tp)`) — it's an object with named
asset class keys (forex, metals, etc.). Parse by iterating asset class keys. Exclude `oil` per
design. Read `partial_close_percent` from `tp_config.partial_close_percent`, not `config.partial_close_pct`.

### Step 13: Make TP Config editable and saveable
```
frontend/src/pages/SettingsPage.tsx — Replace defaultValue with controlled inputs, reconstruct
                                      tp_config object on save
```
Replace all `defaultValue` with `value` + `onChange` handlers that update `tpRows` state.
In `handleSave`, rebuild the `tp_config` object in Pydantic-compatible shape.
Preserve `oil` from original config (hidden from UI but not deleted).

### Step 14: Fix Symbol Mapping
```
frontend/src/pages/SettingsPage.tsx — Read from config.symbol_map (not symbol_overrides),
                                      detect feed from offset_instruments, remove visibility guard
```
**Bug:** Code reads `config.symbol_overrides` — field doesn't exist. Correct field is `config.symbol_map`.

### Step 15: Make Symbol Mapping editable
```
frontend/src/pages/SettingsPage.tsx — Controlled inputs, add/remove mapping rows, stock suffix input
```
Add mapping button (appends empty row), delete button per row, stock suffix field.
Reconstruct `symbol_map` dict and `stock_suffix` in `handleSave`.

### Step 16: Fixed Lot per instrument table
```
frontend/src/pages/SettingsPage.tsx — Show per-instrument fixed lot table when mode=fixed
bot/config/settings.py              — Update LotSizingConfig.fixed_lot to accept float | dict
```
When "Fixed lot" mode selected, show table: Default row (always present) + per-instrument rows
with add/remove. Backend `LotSizingConfig.fixed_lot` must become `float | dict[str, float]`.
Implement UI to handle both formats (float from legacy config, dict from new).

### Step 17: Wire Validate button
```
frontend/src/pages/SettingsPage.tsx — onClick: save license_key via PUT /api/config
```
Engine's heartbeat will re-validate. Status SSE updates `license_valid` indicator.

### Step 18: Expand handleSave to save ALL settings
```
frontend/src/pages/SettingsPage.tsx — Include tp_config, symbol_map, stock_suffix in save payload
```
Current `handleSave` only saves `license_key` and `lot_sizing`. Must include all changed fields.
Spread original config to preserve fields not shown in UI (polling, spread_hour, etc.).

---

## Phase 5: CSS Polish

### Step 19: Select element styling + audit
```
frontend/src/index.css — Style <select> elements consistent with .inp class
```
Verify all new JSX references existing CSS classes. Add dropdown arrow styling for native selects.

---

## Implementation Order

Phases should be executed in order (1→2→3→4→5). Within each phase, steps can be done
sequentially. Phase 1 is critical — it unblocks the broken charts and enables signal grouping
with channel/type data.

**Backend changes (Phase 1) must be done before frontend phases can be fully verified.**

Steps 4, 8, 11, and 19 are small/independent and can be done at any time.
