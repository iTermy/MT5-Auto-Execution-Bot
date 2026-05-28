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
