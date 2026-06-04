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

FETCH_LIVE_PRICES = """
SELECT symbol, bid, ask, feed, updated_at, ic_bid, ic_ask
FROM live_prices
WHERE symbol = ANY($1)
"""

FETCH_NEWS_MODE = """
SELECT news_mode FROM bot_mode_status WHERE id = 1
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
    symbol                  TEXT,
    realized_pnl            REAL,
    channel_id              INTEGER
)
"""

INSERT_ORDER = """
INSERT OR IGNORE INTO order_mappings
    (limit_id, signal_id, mt5_ticket, order_type, lot_size, placed_at,
     db_stop_loss, signal_type, feed_price_at_placement, mt5_price_at_placement,
     offset_at_placement, symbol, channel_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

UPDATE_TICKET = """
UPDATE order_mappings SET mt5_ticket = ? WHERE mt5_ticket = ? AND status = 'filled'
"""

INSERT_CLAIMED_ORDER = """
INSERT OR IGNORE INTO order_mappings
    (limit_id, signal_id, mt5_ticket, order_type, lot_size, placed_at,
     db_stop_loss, signal_type, feed_price_at_placement, mt5_price_at_placement,
     offset_at_placement, symbol, channel_id, status)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'claimed')
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

UPDATE_DB_STOP_LOSS = """
UPDATE order_mappings SET db_stop_loss = ?, last_known_mt5_sl = ? WHERE mt5_ticket = ?
"""

UPDATE_LAST_OFFSET_CHECK = """
UPDATE order_mappings SET last_offset_check = ? WHERE mt5_ticket = ?
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
    bot_version, tp_strategy, notes
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
    $26, $27, $28
)
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
