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
  fixed_lot: number
  max_lot_per_order: number
}

export interface Config {
  license_key: string
  lot_sizing: LotSizingConfig
  [key: string]: unknown
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
