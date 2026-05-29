import type { DashboardData, StatusData } from '../types'

interface Props {
  dashboard: DashboardData | null
  status: StatusData | null
  connected: boolean
}

export function TopBar({ dashboard, status, connected }: Props) {
  const acct = dashboard?.account
  const summary = dashboard?.summary
  const mt5Ok = status?.mt5_connected ?? false
  const supaOk = status?.supabase_connected ?? false
  const profit = summary?.total_profit ?? 0

  return (
    <div className="top-bar">
      <div className="top-bar-metrics">
        <Metric label="Balance" value={acct?.balance} currency={acct?.currency} />
        <Metric label="Equity" value={acct?.equity} currency={acct?.currency} />
        <Metric label="Unrealized P&L" value={profit} currency={acct?.currency} colored />
        <Metric label="Free Margin" value={acct?.margin_free} currency={acct?.currency} />
      </div>
      <div className="top-bar-status">
        <span className={`dot-sm ${mt5Ok ? 'green' : 'red'}`} />
        <span className="status-label">MT5</span>
        <span className={`dot-sm ${supaOk ? 'green' : 'red'}`} />
        <span className="status-label">DB</span>
        <span className={`dot-sm ${connected ? 'green' : 'red'}`} />
        <span className="status-label">UI</span>
      </div>
    </div>
  )
}

function Metric({ label, value, currency, colored }: {
  label: string
  value?: number
  currency?: string
  colored?: boolean
}) {
  const fmt = value != null ? value.toFixed(2) : '—'
  const suffix = currency ? ` ${currency}` : ''
  let cls = 'metric-value'
  if (colored && value != null) {
    cls += value > 0 ? ' positive' : value < 0 ? ' negative' : ''
  }
  return (
    <div className="top-metric">
      <span className="metric-label">{label}</span>
      <span className={cls}>{fmt}{suffix}</span>
    </div>
  )
}
