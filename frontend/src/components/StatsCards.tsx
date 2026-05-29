import type { HistoryStats } from '../types'

interface Props {
  stats: HistoryStats
}

export function StatsCards({ stats }: Props) {
  return (
    <div className="metrics-row">
      <div className="metric-card">
        <span className="card-label">Total Trades</span>
        <span className="card-value">{stats.total_trades}</span>
      </div>
      <div className="metric-card">
        <span className="card-label">Wins</span>
        <span className="card-value positive">{stats.wins}</span>
      </div>
      <div className="metric-card">
        <span className="card-label">Losses</span>
        <span className="card-value negative">{stats.losses}</span>
      </div>
      <div className="metric-card">
        <span className="card-label">Win Rate</span>
        <span className="card-value">{stats.win_rate.toFixed(1)}%</span>
      </div>
      <div className="metric-card">
        <span className="card-label">Total P&L</span>
        <span className={`card-value ${stats.total_pnl >= 0 ? 'positive' : 'negative'}`}>
          {stats.total_pnl >= 0 ? '+' : ''}{stats.total_pnl.toFixed(2)}
        </span>
      </div>
    </div>
  )
}
