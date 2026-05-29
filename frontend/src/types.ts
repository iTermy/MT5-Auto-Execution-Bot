export interface StatusData {
  engine_running: boolean
  trading_active: boolean
  license_valid: boolean
  mt5_connected: boolean
  supabase_connected: boolean
  pending_count: number
  open_count: number
  trailing_count: number
}

export interface LogEntry {
  level: string
  message: string
  timestamp: string
}

export interface LotSizingConfig {
  mode: string
  risk_percent: number
  fixed_lot: number | Record<string, number>
  max_lot_per_order: number
}

export interface AssetTPConfig {
  profit_threshold: number
  threshold_unit: string
  trailing_distance: number
}

export interface ScalpOverrideConfig {
  profit_threshold: number
  trailing_distance: number
}

export interface TPConfig {
  partial_close_percent: number
  forex: AssetTPConfig
  forex_jpy: AssetTPConfig
  metals: AssetTPConfig
  indices: AssetTPConfig
  stocks: AssetTPConfig
  crypto: AssetTPConfig
  oil: AssetTPConfig
  scalp_overrides: Record<string, ScalpOverrideConfig>
  instrument_overrides: Record<string, Record<string, unknown>>
}

export interface PollingConfig {
  supabase_interval_seconds: number
  tp_active_interval_seconds: number
  license_heartbeat_seconds: number
}

export interface SpreadHourConfig {
  daily_start: string
  daily_end: string
  timezone: string
  weekend_start_day: string
  weekend_end_day: string
}

export interface Config {
  license_key: string
  lot_sizing: LotSizingConfig
  polling: PollingConfig
  magic_number: number
  symbol_map: Record<string, string>
  stock_suffix: string
  stock_no_suffix: string[]
  excluded_symbols: string[]
  offset_instruments: string[]
  offset_drift_threshold_pips: number
  feed_max_staleness_seconds: number
  spread_hour: SpreadHourConfig
  tp_config: TPConfig
}

export interface AccountData {
  login: number
  balance: number
  equity: number
  margin: number
  margin_free: number
  leverage: number
  currency: string
}

export interface PositionData {
  ticket: number
  symbol: string
  direction: string
  volume: number
  price_open: number
  current_price: number
  sl: number
  profit: number
  is_trailing: boolean
  signal_id: number
  channel_id: string | null
}

export interface PendingOrderData {
  ticket: number
  symbol: string
  direction: string
  volume: number
  price_level: number
  current_price: number
  sl: number
  distance: number
  signal_id: number
  channel_id: string | null
}

export interface DashboardSummary {
  total_profit: number
  open_count: number
  pending_count: number
  trailing_count: number
}

export interface DashboardData {
  account: AccountData
  positions: PositionData[]
  pending_orders: PendingOrderData[]
  summary: DashboardSummary
  updated_at: string
}

export interface TradeData {
  id: number
  signal_id: number
  symbol: string
  direction: string
  lot_size: number
  placed_at: string
  filled_at: string
  closed_at: string
  status: string
  is_scalp: boolean
  realized_pnl: number
  channel_id: string | null
}

export interface HistoryStats {
  total_trades: number
  wins: number
  losses: number
  win_rate: number
  total_pnl: number
}

export interface HistoryData {
  trades: TradeData[]
  stats: HistoryStats
}

export type Page = 'dashboard' | 'history' | 'settings'
