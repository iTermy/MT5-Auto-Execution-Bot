# Architecture

## Tech Stack
| Layer | Tech | Notes |
|-------|------|-------|
| Language | Python 3.13 | Windows-only (MT5 constraint) |
| MT5 | MetaTrader5 package | Synchronous, binds to calling thread |
| Remote DB | asyncpg | Direct PostgreSQL to Supabase |
| Local DB | aiosqlite | `orders.db` for all mutable state |
| Backend | FastAPI + Uvicorn | Async, serves API + static files |
| Frontend | React + TypeScript + Vite | SPA bundled into `frontend/dist/` |
| Real-time | Server-Sent Events (SSE) | Logs + status streamed to browser |
| Config | Pydantic v2 | Typed config.json validation |
| Tray | pystray + Pillow | System tray icon with menu |
| Build | PyInstaller | Single `.exe` with bundled dist/ |
| Env | python-dotenv | `.env` for contributor DSN |

## Concurrency Model
```
Main Thread (pystray)
  |  System tray icon event loop (Windows message pump)
  |  Spawns engine thread on startup
  |
  +-- Engine Thread (threading.Thread)
        |  mt5.initialize() HERE (binds MT5 to this thread)
        |  asyncio.run(engine.run_forever())
        |
        +-- Task: uvicorn.Server.serve() — FastAPI at :8501
        +-- Task: supabase_sync_loop() — polls Supabase every 30s
        +-- Task: tp_monitor_loop() — 1s when positions/orders exist
        +-- Task: license_heartbeat() — HTTP POST every 15 min
```

MT5 calls are sync but <50ms. Called directly in the async loop (no executor). Safe because asyncio is single-threaded — tasks yield between MT5 calls.

## Core Loop (sync_cycle.py)
```
1. Query Supabase: active/hit signals + pending limits (1 query)
2. Query Supabase: live_prices for offset instruments (1 query, only if needed)
3. Diff against SQLite order_mappings locally
4. For new limits: calculate lot, compute offset+spread, place MT5 order, write SQLite
5. For stale limits: cancel MT5 order, update SQLite
6. For price drift on offset instruments: modify MT5 order price
```

## TP Engine (tp/)
```
TPStrategy (Protocol)
  +-- DefaultTPStrategy
        should_trigger() — newest pos >= threshold AND others_pnl >= 0
        execute()        — close earlier positions, partial-close newest, trail remainder
        update_trailing() — ratchet SL (up for longs, down for shorts)

TrailingStopManager
  Called every 1s for is_trailing=1 positions
  SL = bid - trail_distance (longs) or ask + trail_distance (shorts)
  SL only moves in favorable direction, never retreats

TPEngine (engine.py)
  Groups positions by signal_id (via SQLite)
  Delegates to strategy per signal group
```

### TP Trigger Conditions (both must be true simultaneously)
1. Most-recently-filled position (highest ticket#) moved >= `profit_threshold`
2. Combined P&L of ALL OTHER positions for same signal >= 0

### On Trigger
- Earlier positions: close 100% at market
- Newest position: close `partial_close_percent`% at market
- Remainder: enter trailing phase (`is_trailing=1` in SQLite)
- If partial_close_percent=100: close everything, no trail
- If partial_close_percent=0: trail full position, close nothing

### Partial Close Ticket Handling
ICMarkets hedging mode: partial close creates a **new ticket** for the remainder. Original ticket is closed. Fill detector must:
1. Detect new ticket via MT5 deal history
2. Create new SQLite row inheriting signal_id, signal_type, is_trailing from parent

### Asset Class Detection Order (symbol_mapper.py)
1. Metals: `XAUUSD`, `XAGUSD`, `GOLD`, `SILVER`
2. Oil: contains `OIL`, `WTI`, `BRENT`
3. **Stocks**: ends in `.NAS` or `.NYSE` (MUST check before indices)
4. Indices: contains `SPX`, `NAS`, `DAX`, `JP225`, `UK100`, `US500`, `USTEC`, etc.
5. Crypto: ends in `USD`/`USDT` and `len > 6`
6. Forex (default); `JPY` in name -> `forex_jpy`

### TP Defaults
```
Standard:                              Scalp (roughly halved):
  forex:     7 pip / 3 pip trail         forex:     5 pip / 2 pip trail
  forex_jpy: 7 pip / 3 pip trail         forex_jpy: 5 pip / 3 pip trail
  metals:    $4 / $2 trail               metals:    $2 / $1 trail
  indices:   $20 / $5 trail              indices:   $10 / $3 trail
  stocks:    $1 / $0.50 trail            stocks:    $0.50 / $0.25 trail
  crypto:    $300 / $50 trail            crypto:    $150 / $25 trail
  oil:       $0.50 / $0.20 trail         oil:       $0.25 / $0.10 trail
```

## Spread Adjustment (order_placer.py)
On every pending order placement, adjust price and SL for current spread:
```
spread = ask - bid  (from MT5 live tick)

Long (buy) limits:   adjusted_price = limit_price + spread
                     adjusted_sl    = stop_loss - spread

Short (sell) limits: adjusted_price = limit_price - spread
                     adjusted_sl    = stop_loss + spread
```
Raw DB prices stored in SQLite for reference. Adjusted prices sent to MT5.

## Feed Offset (offset_calculator.py)
For indices/crypto where DB prices come from OANDA/Binance feeds:
```
offset = mt5_mid - feed_mid
mt5_order_price = db_limit_price + offset  (then apply spread adjustment)
```
Offset instruments: SPX500USD->US500, NAS100USD->USTEC, BTCUSDT->BTCUSD, ETHUSDT->ETHUSD.
Freshness check: `live_prices.updated_at` must be within 30s. Skip placement if stale.
Readjust existing orders if offset drift > threshold (default 5 pips).

## Symbol Mapping
| DB Instrument | MT5 Symbol | Offset? |
|---------------|-----------|---------|
| XAUUSD / GOLD | XAUUSD | No |
| EURUSD, etc. | same | No |
| SPX500USD | US500 | Yes (OANDA) |
| NAS100USD | USTEC | Yes (OANDA) |
| BTCUSDT | BTCUSD | Yes (Binance) |
| ETHUSDT | ETHUSD | Yes (Binance) |
| AMD.NAS | AMD.NAS-24 | No |
| MSFT.NYSE | MSFT.NYSE-24 | No |

Stock suffix `-24` means 24-hour trading (permanent, not yearly). Configurable in config.json.

## Lot Sizing — Two Modes
**Risk % (default):** `lot = (balance * risk%) / (num_limits * avg_sl_distance_pips * pip_value_per_lot)`
**Fixed lot:** flat lot per limit, ignoring balance/SL/signal size.
Clamped to MT5 symbol volume_min/volume_max, rounded to volume_step.

## Market Hours / Spread Hour (scheduler.py)
Pause placement + cancel pending during:
- Mon-Thu: 4:45 PM - 6:00 PM EST
- Weekend: Fri 4:45 PM - Sun 6:00 PM EST

Cancelled orders marked `spread_cancelled` in SQLite. Re-placed automatically when markets reopen (sync cycle sees DB limit still pending + no active SQLite mapping).

## Polling Strategy
| State | MT5 calls/min | Supabase queries/min |
|-------|--------------|---------------------|
| Idle (no signals/orders) | 0 | 2 |
| Pending orders (watching fills) | 120 | 2 |
| Positions open (TP monitoring) | 120 | 2 |
| Trailing | 120 + SL mods | 2 |

Scalp strategy — every second matters. 1s polling when any pending orders or positions exist.

## License System
- Supabase Edge Function (Deno/TypeScript) at `supabase/functions/validate-license/`
- Bot POSTs `{license_key, mt5_account}` to Edge Function URL
- Validates key exists, active, not expired, MT5 account matches
- Startup: validate or refuse to start
- Heartbeat: re-validate every 15 min
- On failure: block new placements, keep managing open positions
- URL: production hardcoded in constants.py, contributors override via `.env`

## Startup Reconciliation (reconciler.py)
1. Get MT5 orders + positions filtered by magic number
2. Compare against SQLite order_mappings
3. Pending in SQLite + in MT5 positions -> mark filled
4. Pending in SQLite + gone from MT5 -> mark cancelled
5. Filled in SQLite + gone from MT5 -> mark closed
6. Filled + is_trailing=1 + still in MT5 -> resume trailing
7. MT5 orders with our magic but not in SQLite -> log warning (orphans), do NOT auto-cancel

## Signal Tracking
Multiple signals can exist for same instrument. signal_id encoded in MT5 order comment: `"s{signal_id}"` (e.g. `"s12345"`). Primary mapping is SQLite `order_mappings.signal_id`. Comment is reconciliation fallback.

## Supabase Schema (Read-Only)
**signals**: id, instrument, direction(long/short), stop_loss, status(active/hit/profit/breakeven/stop_loss/cancelled), type(standard/scalp/swing/toll/pa/1-1), expiry_time, channel_id
**limits**: id, signal_id(FK), price_level, sequence_number, status(pending/hit/cancelled)
**live_prices**: symbol(PK), bid, ask, feed(oanda/binance), updated_at
**licenses**: (queried by Edge Function, not by bot directly)

## SQLite Schema (orders.db)
```sql
CREATE TABLE IF NOT EXISTS order_mappings (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    limit_id                BIGINT NOT NULL UNIQUE,
    signal_id               BIGINT NOT NULL,
    mt5_ticket              BIGINT NOT NULL UNIQUE,
    order_type              TEXT NOT NULL,        -- buy_limit/sell_limit/buy_stop/sell_stop
    lot_size                REAL,
    placed_at               TEXT NOT NULL,        -- ISO timestamp
    filled_at               TEXT,
    cancelled_at            TEXT,
    status                  TEXT NOT NULL DEFAULT 'pending',  -- pending/filled/cancelled/spread_cancelled/error
    feed_price_at_placement REAL,
    mt5_price_at_placement  REAL,
    offset_at_placement     REAL,
    last_offset_check       TEXT,
    db_stop_loss            REAL,
    last_known_mt5_sl       REAL,
    signal_type             TEXT NOT NULL DEFAULT 'standard',  -- standard|scalp|swing|toll|pa|1-1
    is_trailing             INTEGER NOT NULL DEFAULT 0
);
```

## config.json Full Structure
```json
{
  "license_key": "",

  "lot_sizing": {
    "mode": "risk_percent",
    "risk_percent": 1.0,
    "fixed_lot": 0.01,
    "max_lot_per_order": 5.0
  },

  "polling": {
    "supabase_interval_seconds": 30,
    "tp_active_interval_seconds": 1,
    "license_heartbeat_seconds": 900
  },

  "magic_number": 20250001,

  "symbol_map": {
    "SPX500USD": "US500",
    "NAS100USD": "USTEC",
    "BTCUSDT": "BTCUSD",
    "ETHUSDT": "ETHUSD"
  },
  "stock_suffix": "-24",

  "offset_instruments": ["SPX500USD", "NAS100USD", "BTCUSDT", "ETHUSDT"],
  "offset_drift_threshold_pips": 5,
  "feed_max_staleness_seconds": 30,

  "spread_hour": {
    "daily_start": "16:45",
    "daily_end": "18:00",
    "timezone": "US/Eastern",
    "weekend_start_day": "Friday",
    "weekend_end_day": "Sunday"
  },

  "tp_config": {
    "partial_close_percent": 50,
    "forex":     { "profit_threshold": 7,     "threshold_unit": "pips",    "trailing_distance": 3 },
    "forex_jpy": { "profit_threshold": 7,     "threshold_unit": "pips",    "trailing_distance": 3 },
    "metals":    { "profit_threshold": 4.0,   "threshold_unit": "dollars", "trailing_distance": 2.0 },
    "indices":   { "profit_threshold": 20.0,  "threshold_unit": "dollars", "trailing_distance": 5.0 },
    "stocks":    { "profit_threshold": 1.0,   "threshold_unit": "dollars", "trailing_distance": 0.5 },
    "crypto":    { "profit_threshold": 300.0, "threshold_unit": "dollars", "trailing_distance": 50.0 },
    "oil":       { "profit_threshold": 0.5,   "threshold_unit": "dollars", "trailing_distance": 0.2 },
    "scalp_overrides": {
      "forex":     { "profit_threshold": 5,   "trailing_distance": 2 },
      "forex_jpy": { "profit_threshold": 5,   "trailing_distance": 3 },
      "metals":    { "profit_threshold": 2.0,  "trailing_distance": 1.0 },
      "indices":   { "profit_threshold": 10.0, "trailing_distance": 3.0 },
      "stocks":    { "profit_threshold": 0.5,  "trailing_distance": 0.25 },
      "crypto":    { "profit_threshold": 150.0,"trailing_distance": 25.0 },
      "oil":       { "profit_threshold": 0.25, "trailing_distance": 0.1 }
    },
    "toll_overrides":  {},
    "swing_overrides": {},
    "pa_overrides":    {},
    "one_to_one": {
      "profit_threshold": 10.0,
      "overrides": {}
    },
    "instrument_overrides": {}
  }
}
```

Per-type override fallback rules (see `bot/tp/asset_config.py`):

- `standard` — uses the base asset-class config.
- `scalp`, `toll`, `pa` — use the per-asset override if present; otherwise fall back to the base asset-class config.
- `swing` — uses the per-asset override if present; otherwise falls back to `3 × base.profit_threshold`.
- `1-1` — engine forces `threshold_unit='dollars'`, `partial_close_percent=100`, and `trailing_distance=0`. Only `one_to_one.profit_threshold` (and per-asset `overrides`) is user-tunable. Trailing is also gated off explicitly in `TPEngine._process_group`.

## Order Type Selection Logic
The order type depends on signal direction and limit price relative to current market:
```
direction=long:
  limit_price < current_ask  -> BUY_LIMIT  (price below market, expect bounce up)
  limit_price > current_ask  -> BUY_STOP   (price above market, expect breakout up)

direction=short:
  limit_price > current_bid  -> SELL_LIMIT (price above market, expect reversal down)
  limit_price < current_bid  -> SELL_STOP  (price below market, expect breakdown)
```
After spread adjustment is applied to the price, the comparison uses the adjusted price.

## FastAPI Endpoints (bot/api/routes.py)
```
GET  /api/status         — { engine_running, license_valid, mt5_connected, supabase_connected, pending_count, open_count, trailing_count }
GET  /api/config         — current config.json as JSON
PUT  /api/config         — update config fields (Pydantic validates, writes to file, hot-reloads)
POST /api/engine/start   — start the trading engine
POST /api/engine/stop    — stop the trading engine (keeps managing open positions until closed)
GET  /api/logs           — SSE stream: { event: "log", data: { level, timestamp, message } }
GET  /api/status/stream  — SSE stream: { event: "status", data: { ...status fields } }
```

Static files: FastAPI serves `frontend/dist/` at `/`. In dev, Vite dev server on `:5173` proxies `/api/*` to FastAPI on `:8501`.

## React Components (frontend/src/components/)
- **LicensePanel**: text input for license key, "Validate" button, green/red status dot
- **ControlPanel**: Start/Stop toggle button, lot mode radio (Risk % / Fixed) with contextual number inputs, MT5 + Supabase connection indicator dots
- **LogPanel**: auto-scrolling div, log entries color-coded by severity (INFO=gray, WARNING=yellow, ERROR=red), receives from SSE /api/logs
- **StatusBar**: numeric counts — active signals, pending orders, open positions, trailing positions

## Implementation Clarifications (decided during build, treat as final)

- **OrderStatus.CLOSED**: Added to the enum in `constants.py`. SQLite schema `status` column
  supports it. Reconciler uses it for "filled + gone from MT5" positions.

- **cancel_pending_order** added to `MT5Client` — uses `TRADE_ACTION_REMOVE`. Single attempt,
  no retry (cancellation is idempotent from the broker's perspective).

- **Partial close detection**: `FillDetector.detect_partial_close_tickets()` uses comment matching
  (`position.comment == "s{signal_id}"`) against positions not yet in SQLite. Does NOT parse
  `history_deals_get()`. This is simpler and reliable for ICMarkets hedging mode.

- **Pip size**: `symbol_info.point * 10` for instruments with `digits in (3, 5)` (FX and JPY);
  `symbol_info.point` for all others (metals, indices, crypto). Used in lot_calculator.py and
  will be needed for pip-unit TP threshold comparisons in the TP engine.

- **LotCalculator.calculate()** signature: `(stop_loss: float, limit_prices: list[float], mt5_symbol: str)`
  — takes primitives, not asyncpg.Record. Caller extracts fields before calling.

- **SQLiteDB**: holds a single persistent connection opened by `init_schema()`. Must be called
  once at startup before any other SQLiteDB method.

- **OffsetCalculator.check_drift()** threshold parameter is in absolute price units, not pips.
  Caller converts `offset_drift_threshold_pips * pip_size` before calling.

- **MarketScheduler** is defined in `bot/utils/time_utils.py`. `bot/core/scheduler.py` (step 28)
  imports it directly — no logic is duplicated there.

- **ICMarkets hedging: position ticket ≠ order ticket.** When an order fills, `position.identifier`
  == order ticket, but `position.ticket` is a NEW ID. SQLite stores the order ticket at placement.
  After fill detection, `sqlite.update_ticket(order_ticket, position_ticket)` rewrites the row so
  all downstream lookups (`{p.ticket: p for p in positions}`) work correctly.

- **Partial close remainder insert.** When `FillDetector.detect_partial_close_tickets()` returns a
  `NewTicketEvent`, sync_cycle inserts a new SQLite row with `limit_id = -new_ticket` (synthetic
  negative, guaranteed unique and never mistaken for a Supabase limit ID), `order_type = "remainder"`,
  then immediately calls `mark_filled()` and `set_trailing()`.

- **TP trigger uses price movement, not account P&L.** `profit_threshold` is compared to:
  - pips mode: `(bid - price_open) / pip_size` for longs, `(price_open - ask) / pip_size` for shorts
  - dollars mode: `bid - price_open` for longs, `price_open - ask` for shorts
  The "others combined P&L >= 0" guard uses `position.profit` (account currency).

- **db_symbol_from_mt5()** in `bot/trading/symbol_mapper.py` reverse-maps MT5 symbols to DB symbols
  (e.g., "BTCUSD" → "BTCUSDT", "AMD.NAS-24" → "AMD.NAS"). Required by TPEngine so it can call
  `detect_asset_class()` with the correct DB symbol.

- **close_position() and modify_position_sl()** added to `MT5Client`. close_position() uses
  `TRADE_ACTION_DEAL` with retry on transient errors. modify_position_sl() uses `TRADE_ACTION_SLTP`,
  single attempt (trailing retries naturally next cycle).

- **Adaptive polling.** Both sync_loop and tp_loop sleep `tp_active_interval_seconds` (1s) when
  `sqlite.get_all_active()` is non-empty; sleep `supabase_interval_seconds` (30s) when idle.

- **SyncCycle.run(placement_active=bool).** When False (engine stopped or license invalid), skips
  order placement and cancellation but still detects fills and partial close tickets.

- **Offset drift cancel-and-re-place.** Drifted pending orders are cancelled (status='cancelled').
  Since cancelled rows are excluded from `get_all_active()`, the limit reappears in `new_limit_ids`
  on the next cycle and is placed with the current offset.

- **SSEBroadcaster.last_msg** caches the most recent status broadcast. GET /api/status reads this
  cache — no MT5 call is made from the FastAPI handler (MT5 is engine-thread only).

- **Engine.app set externally.** main.py: `engine = Engine(...)`, `engine.app = create_app(engine)`,
  then starts the engine thread. `run_forever()` starts uvicorn only if `engine.app is not None`.

- **LicenseValidator dev bypass.** If `url` is empty string, `validate()` returns VALID immediately.
  Contributors without a live Edge Function can run the bot without license errors.

## DSN / Contributor Access

### DSN Loading (bot/config/settings.py)
1. Check for `.env` file -> load `SUPABASE_DSN` and `LICENSE_API_URL`
2. If no `.env` -> fall back to `_PRODUCTION_DSN` and `_PRODUCTION_LICENSE_URL` in `bot/config/constants.py`
3. Both constants are `""` (empty) in the repo. Owner fills them before compiling production binary.

### Owner's Production Build Workflow (document in CONTRIBUTING.md)
1. Edit `bot/config/constants.py`: set `_PRODUCTION_DSN` and `_PRODUCTION_LICENSE_URL` to real values
2. `cd frontend && npm run build` (produces `frontend/dist/`)
3. `pyinstaller bot.spec` (produces `.exe` with bundled dist/)
4. **Revert** `constants.py` to empty placeholders before pushing to git

### Contributor Role Setup (document in CONTRIBUTING.md with exact SQL)
1. Create read-only Postgres role in Supabase SQL editor:
   ```sql
   CREATE ROLE contributor_bot WITH LOGIN PASSWORD 'initial_password';
   GRANT USAGE ON SCHEMA public TO contributor_bot;
   GRANT SELECT ON signals, limits, live_prices TO contributor_bot;
   ```
2. Monthly password rotation:
   ```sql
   ALTER ROLE contributor_bot WITH PASSWORD 'new_password_here';
   ```
3. Share new `.env` with contributors containing updated DSN

### .env Format
```
SUPABASE_DSN=postgresql://contributor_bot:PASSWORD@db.xxxxx.supabase.co:5432/postgres
LICENSE_API_URL=https://xxxxx.supabase.co/functions/v1/validate-license
```
