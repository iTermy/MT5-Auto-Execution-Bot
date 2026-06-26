# Supabase (PostgreSQL) — asyncpg, positional params $1 $2 ...

FETCH_ACTIVE_SIGNALS_WITH_LIMITS = """
SELECT
    s.id              AS signal_id,
    s.instrument,
    s.direction,
    s.stop_loss,
    s.status          AS signal_status,
    s.type            AS signal_type,
    s.channel_id,
    s.closed_reason,
    l.id              AS limit_id,
    l.price_level,
    l.sequence_number
FROM signals s
JOIN limits l ON l.signal_id = s.id
WHERE s.status IN ('active', 'hit')
  AND l.status = 'pending'
ORDER BY s.id, l.sequence_number
"""

# Limits the TM has marked 'hit' on a still-live signal. Their local pending
# order is held (not stale-cancelled) — the feed reached the level but our
# broker hasn't filled yet, usually a sub-pip mismatch. A final signal status
# drops the signal out of this set, so genuine cancels/closes still cancel.
FETCH_HIT_LIMIT_IDS = """
SELECT l.id AS limit_id
FROM signals s
JOIN limits l ON l.signal_id = s.id
WHERE s.status IN ('active', 'hit')
  AND l.status = 'hit'
"""

# Every limit of a signal the TM marked 'profit'. Marking 'profit' is a final
# status on the TM side, which flips the signal's still-pending limits to
# 'cancelled' (not 'pending'), so we can't filter on the limit status here. We
# map each limit to its signal and let the caller spare the ones we still hold
# as local pending orders while a filled position remains — keeping the
# remaining entries live until our own TP engine closes the trade.
FETCH_PROFIT_LIMIT_IDS = """
SELECT l.id AS limit_id, l.signal_id
FROM signals s
JOIN limits l ON l.signal_id = s.id
WHERE s.status = 'profit'
"""

FETCH_LIVE_PRICES = """
SELECT symbol, bid, ask, feed, updated_at
FROM live_prices
WHERE symbol = ANY($1)
"""

FETCH_MODE_GATES = """
SELECT news_mode, vol_guard FROM bot_mode_status WHERE id = 1
"""

FETCH_FEED_HEALTH = """
SELECT feed, status FROM feed_health
"""

# SQLite — aiosqlite, ? placeholders

CREATE_ORDER_MAPPINGS = """
CREATE TABLE IF NOT EXISTS order_mappings (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    limit_id                BIGINT NOT NULL UNIQUE,
    signal_id               BIGINT NOT NULL,
    mt5_ticket              BIGINT NOT NULL UNIQUE,
    order_type              TEXT NOT NULL,
    lot_size                REAL,
    placed_at               TEXT NOT NULL,
    filled_at               TEXT,
    cancelled_at            TEXT,
    status                  TEXT NOT NULL DEFAULT 'pending',
    feed_price_at_placement REAL,
    mt5_price_at_placement  REAL,
    offset_at_placement     REAL,
    last_offset_check       TEXT,
    db_stop_loss            REAL,
    last_known_mt5_sl       REAL,
    signal_type             TEXT NOT NULL DEFAULT 'standard',
    is_trailing             INTEGER NOT NULL DEFAULT 0,
    sl_stripped             INTEGER NOT NULL DEFAULT 0,
    symbol                  TEXT,
    realized_pnl            REAL,
    channel_id              INTEGER,
    sequence_number         INTEGER,
    mfe_price               REAL NOT NULL DEFAULT 0,
    mae_price               REAL NOT NULL DEFAULT 0
)
"""

INSERT_ORDER = """
INSERT OR IGNORE INTO order_mappings
    (limit_id, signal_id, mt5_ticket, order_type, lot_size, placed_at,
     db_stop_loss, signal_type, feed_price_at_placement, mt5_price_at_placement,
     offset_at_placement, symbol, channel_id, sequence_number)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

MARK_FILLED = """
UPDATE order_mappings SET status = 'filled', filled_at = ? WHERE mt5_ticket = ?
"""

MARK_CANCELLED = """
UPDATE order_mappings SET status = ?, cancelled_at = ? WHERE mt5_ticket = ?
"""

MARK_CLOSED = """
UPDATE order_mappings SET status = 'closed', cancelled_at = datetime('now'), realized_pnl = ? WHERE mt5_ticket = ?
"""

SET_TRAILING = """
UPDATE order_mappings SET is_trailing = ? WHERE mt5_ticket = ?
"""

SET_SL_STRIPPED = """
UPDATE order_mappings SET sl_stripped = ? WHERE mt5_ticket = ?
"""

GET_PENDING_ORDERS = """
SELECT * FROM order_mappings WHERE status = 'pending'
"""

GET_FILLED_POSITIONS = """
SELECT * FROM order_mappings WHERE status = 'filled'
"""

GET_TRAILING_POSITIONS = """
SELECT * FROM order_mappings WHERE status = 'filled' AND is_trailing = 1
"""

GET_ALL_ACTIVE = """
SELECT * FROM order_mappings WHERE status IN ('pending', 'filled')
"""

UPDATE_SL = """
UPDATE order_mappings SET last_known_mt5_sl = ? WHERE mt5_ticket = ?
"""

UPDATE_EXCURSION = """
UPDATE order_mappings SET mfe_price = ?, mae_price = ? WHERE mt5_ticket = ?
"""

UPDATE_TICKET = """
UPDATE order_mappings SET mt5_ticket = ? WHERE mt5_ticket = ? AND status = 'filled'
"""

INSERT_CLAIMED_ORDER = """
INSERT OR IGNORE INTO order_mappings
    (limit_id, signal_id, mt5_ticket, order_type, lot_size, placed_at,
     db_stop_loss, signal_type, feed_price_at_placement, mt5_price_at_placement,
     offset_at_placement, symbol, channel_id, sequence_number, status)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claimed')
"""

PROMOTE_CLAIMED_TO_PENDING = """
UPDATE order_mappings SET mt5_ticket = ?, status = 'pending' WHERE limit_id = ? AND status = 'claimed'
"""

DELETE_CLAIMED_ORDER = """
DELETE FROM order_mappings WHERE limit_id = ? AND status = 'claimed'
"""

GET_CLAIMED_ORDERS = """
SELECT * FROM order_mappings WHERE status = 'claimed'
"""

GET_CLAIMED_BY_SIGNAL_LIMIT = """
SELECT * FROM order_mappings WHERE signal_id = ? AND limit_id = ? AND status = 'claimed'
"""

FETCH_SIGNAL_STATUS = """
SELECT status FROM signals WHERE id = $1
"""

GET_PENDING_BY_SIGNAL = """
SELECT * FROM order_mappings WHERE signal_id = ? AND status = 'pending'
"""

GET_ORDER_BY_TICKET = """
SELECT * FROM order_mappings WHERE mt5_ticket = ?
"""

GET_FILLED_SIGNAL_IDS = """
SELECT DISTINCT signal_id FROM order_mappings WHERE status = 'filled'
"""

# Limits that have filled on our end at least once — currently open ('filled') or
# already closed after TP / SL / force-exit ('closed'). Once a limit has filled it
# must never be re-placed, even if the upstream signal/limit is still marked active
# in Supabase: a stale or out-of-sync DB row would otherwise make the bot re-enter
# the exact same level on a loop. Never-filled cancellations ('cancelled' /
# 'spread_cancelled') are intentionally excluded so they still re-place as before.
GET_FILLED_LIMIT_IDS = """
SELECT DISTINCT limit_id FROM order_mappings WHERE status IN ('filled', 'closed')
"""

# (signal_id, db price_level) pairs we have already filled or closed. The limit_id
# guard above misses an edit that regenerated the limit_id (the TM rebuilds limit
# rows with fresh IDENTITY ids on every message edit), so the same price level can
# reappear under a new limit_id and get re-entered. This pairs the durable fill with
# its price so a re-issued level is never placed a second time. feed_price_at_placement
# holds the DB price_level captured at placement (NULL only for legacy/test rows).
GET_FILLED_SIGNAL_PRICES = """
SELECT DISTINCT signal_id, feed_price_at_placement
FROM order_mappings
WHERE status IN ('filled', 'closed') AND feed_price_at_placement IS NOT NULL
"""

# Signals where at least one limit has ever filled (currently open or already closed).
# Used by the offset-drift gate to avoid cancelling pending siblings of a signal
# whose other limits already hit.
GET_SIGNALS_WITH_FILLS = """
SELECT DISTINCT signal_id FROM order_mappings WHERE status IN ('filled', 'closed')
"""

# SQLite — guard table marking a signal's full-trade outcome as already recorded.
CREATE_SIGNAL_FINALIZED = """
CREATE TABLE IF NOT EXISTS signal_finalized (
    signal_id    BIGINT PRIMARY KEY,
    finalized_at TEXT NOT NULL
)
"""

# SQLite — per-signal user override. 'skip' = never place; cancel/close everything.
# 'manual' = orphan the placed limits; the bot stops touching the signal entirely.
# Reversible: deleting the row hands the signal back to normal bot management.
CREATE_SIGNAL_ACTIONS = """
CREATE TABLE IF NOT EXISTS signal_actions (
    signal_id  BIGINT PRIMARY KEY,
    action     TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

SET_SIGNAL_ACTION = """
INSERT INTO signal_actions (signal_id, action, created_at)
VALUES (?, ?, ?)
ON CONFLICT(signal_id) DO UPDATE SET action = excluded.action, created_at = excluded.created_at
"""

DELETE_SIGNAL_ACTION = """
DELETE FROM signal_actions WHERE signal_id = ?
"""

GET_SIGNAL_ACTIONS = """
SELECT signal_id, action FROM signal_actions
"""

MARK_SIGNAL_FINALIZED = """
INSERT OR IGNORE INTO signal_finalized (signal_id, finalized_at) VALUES (?, ?)
"""

# Signals that have had at least one real fill, have nothing still open or pending,
# and have not yet been finalized — i.e. the trade is fully settled.
GET_SETTLED_UNFINALIZED_SIGNALS = """
SELECT DISTINCT om.signal_id
FROM order_mappings om
WHERE om.signal_id NOT IN (SELECT signal_id FROM signal_finalized)
  AND EXISTS (
      SELECT 1 FROM order_mappings f
      WHERE f.signal_id = om.signal_id
        AND f.status IN ('filled', 'closed')
        AND f.order_type != 'remainder'
  )
  AND NOT EXISTS (
      SELECT 1 FROM order_mappings a
      WHERE a.signal_id = om.signal_id
        AND a.status IN ('filled', 'pending', 'claimed')
  )
"""

# Full-trade aggregate for a settled signal. realized_pnl and excursions span every
# ticket (including trailing remainders); entry/risk/level stats use only real limits.
GET_SIGNAL_FINAL_AGGREGATE = """
SELECT
    SUM(COALESCE(realized_pnl, 0))                                       AS realized_pnl,
    MAX(mfe_price)                                                       AS mfe_price,
    MAX(mae_price)                                                       AS mae_price,
    MAX(is_trailing)                                                     AS any_trailing,
    MIN(filled_at)                                                       AS first_filled_at,
    MAX(cancelled_at)                                                    AS last_closed_at,
    MAX(symbol)                                                          AS symbol,
    MAX(signal_type)                                                     AS signal_type,
    MAX(channel_id)                                                      AS channel_id,
    MAX(CASE WHEN order_type != 'remainder' THEN db_stop_loss END)       AS stop_loss,
    MAX(CASE WHEN order_type != 'remainder' THEN sequence_number END)    AS level_sequence,
    SUM(CASE WHEN order_type != 'remainder' THEN lot_size ELSE 0 END)    AS total_volume,
    SUM(CASE WHEN order_type != 'remainder'
             THEN mt5_price_at_placement * lot_size ELSE 0 END)          AS entry_x_volume,
    MAX(CASE WHEN order_type != 'remainder' THEN order_type END)         AS order_type
FROM order_mappings
WHERE signal_id = ? AND status = 'closed'
"""

UPDATE_DB_STOP_LOSS = """
UPDATE order_mappings SET db_stop_loss = ?, last_known_mt5_sl = ? WHERE mt5_ticket = ?
"""

UPDATE_LAST_OFFSET_CHECK = """
UPDATE order_mappings SET last_offset_check = ? WHERE mt5_ticket = ?
"""

# Reset the account to "new": drop every terminal trade row (closed / cancelled)
# so all history-derived stats and dashboard visuals go to zero. Open and pending
# orders ('pending', 'filled', 'claimed') are intentionally kept untouched.
CLEAR_HISTORY = """
DELETE FROM order_mappings WHERE status IN ('closed', 'cancelled', 'spread_cancelled')
"""

CLEAR_SIGNAL_FINALIZED = """
DELETE FROM signal_finalized
"""

GET_ORDER_HISTORY = """
SELECT
    signal_id,
    MIN(symbol)        AS symbol,
    MIN(order_type)    AS direction,
    SUM(lot_size)      AS total_lots,
    MIN(placed_at)     AS placed_at,
    MIN(filled_at)     AS first_filled_at,
    MAX(cancelled_at)  AS last_closed_at,
    SUM(COALESCE(realized_pnl, 0)) AS total_pnl,
    MIN(signal_type)   AS signal_type,
    MIN(channel_id)    AS channel_id,
    COUNT(*)           AS fills_count,
    SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_count,
    SUM(CASE WHEN status IN ('cancelled', 'spread_cancelled') THEN 1 ELSE 0 END) AS cancelled_count
FROM order_mappings
WHERE status IN ('closed', 'cancelled', 'spread_cancelled')
  AND placed_at >= ? AND placed_at <= ?
GROUP BY signal_id
ORDER BY MAX(cancelled_at) DESC
"""

# Supabase — fetch signal statuses by IDs
FETCH_SIGNAL_STATUSES = """
SELECT id, status, closed_reason FROM signals WHERE id = ANY($1)
"""

# Supabase — append a TP outcome record (write-only)
INSERT_TP_OUTCOME = """
INSERT INTO tp_outcomes (
    signal_id, mt5_account, channel_id, signal_type, asset_class,
    symbol, direction,
    total_limits, limits_filled, limits_pending, limits_cancelled,
    avg_entry_price, tp_trigger_price, stop_loss,
    threshold_value, threshold_unit,
    move_at_trigger, realized_pnl, others_pnl, total_volume,
    partial_close_pct, trailing_started,
    risk_per_limit, r_multiple, risk_percent_cfg,
    bot_version, tp_strategy, notes,
    stage, mfe_price, mfe_r, mae_price, mae_r,
    level_sequence, total_levels, seconds_to_trigger, hold_seconds, exit_reason
)
VALUES (
    $1, $2, $3, $4, $5,
    $6, $7,
    $8, $9, $10, $11,
    $12, $13, $14,
    $15, $16,
    $17, $18, $19, $20,
    $21, $22,
    $23, $24, $25,
    $26, $27, $28,
    $29, $30, $31, $32, $33,
    $34, $35, $36, $37, $38
)
"""

# SQLite — aggregated lifetime stats across all closed signals.
# Treats one signal_id as one trade (matches the History view); pnl is the
# sum of realized_pnl across all closed limits for that signal.
GET_USER_STATS = """
WITH signal_pnl AS (
    SELECT signal_id, SUM(COALESCE(realized_pnl, 0)) AS pnl
    FROM order_mappings
    WHERE status = 'closed'
    GROUP BY signal_id
)
SELECT
    COUNT(*) AS total_trades,
    COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins,
    COALESCE(SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), 0) AS losses,
    COALESCE(SUM(pnl), 0) AS total_pnl
FROM signal_pnl
"""

# Supabase — UPSERT one row per user (keyed on license_key). Pulls user_id
# from the licenses table; if the license_key is unknown the INSERT inserts
# zero rows (and there's nothing to update either). Schemas are qualified
# explicitly because Supabase ships an `auth.users` table that otherwise
# wins via search_path in some pooler sessions.
UPSERT_USER_SNAPSHOT = """
INSERT INTO public.users (
    license_id, license_key, mt5_account,
    balance, equity, currency, leverage,
    open_positions_count, total_realized_pnl,
    total_trades, wins, losses, win_rate,
    bot_version, last_update_at
)
SELECT
    l.id, $1, $2,
    $3, $4, $5, $6,
    $7, $8,
    $9, $10, $11, $12,
    $13, now()
FROM public.licenses l
WHERE l.license_key = $1
ON CONFLICT (license_key) DO UPDATE SET
    mt5_account = EXCLUDED.mt5_account,
    balance = EXCLUDED.balance,
    equity = EXCLUDED.equity,
    currency = EXCLUDED.currency,
    leverage = EXCLUDED.leverage,
    open_positions_count = EXCLUDED.open_positions_count,
    total_realized_pnl = EXCLUDED.total_realized_pnl,
    total_trades = EXCLUDED.total_trades,
    wins = EXCLUDED.wins,
    losses = EXCLUDED.losses,
    win_rate = EXCLUDED.win_rate,
    bot_version = EXCLUDED.bot_version,
    last_update_at = EXCLUDED.last_update_at
"""

# SQLite — aggregate counts of a signal's limits (filled / pending / cancelled / closed)
SIGNAL_SUMMARY = """
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN status = 'filled' THEN 1 ELSE 0 END) AS filled,
    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
    SUM(CASE WHEN status IN ('cancelled', 'spread_cancelled') THEN 1 ELSE 0 END) AS cancelled,
    SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed
FROM order_mappings
WHERE signal_id = ? AND order_type != 'remainder'
"""
