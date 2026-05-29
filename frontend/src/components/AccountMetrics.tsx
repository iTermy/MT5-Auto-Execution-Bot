import type { AccountData, DashboardSummary } from '../types'

interface Props {
  account: AccountData | null
  summary: DashboardSummary | null
}

export function AccountMetrics({ account, summary }: Props) {
  if (!account) {
    return <div className="metrics-row"><span className="muted">Waiting for account data...</span></div>
  }

  return (
    <div className="metrics-row">
      <Card label="Balance" value={account.balance} currency={account.currency} />
      <Card label="Equity" value={account.equity} currency={account.currency} />
      <Card label="Margin" value={account.margin} currency={account.currency} />
      <Card label="Free Margin" value={account.margin_free} currency={account.currency} />
      <Card label="Leverage" value={account.leverage} plain />
      <Card
        label="Unrealized P&L"
        value={summary?.total_profit ?? 0}
        currency={account.currency}
        colored
      />
    </div>
  )
}

function Card({ label, value, currency, colored, plain }: {
  label: string
  value: number
  currency?: string
  colored?: boolean
  plain?: boolean
}) {
  const fmt = plain ? `1:${value}` : `${value.toFixed(2)}${currency ? ' ' + currency : ''}`
  let cls = 'card-value'
  if (colored) {
    cls += value > 0 ? ' positive' : value < 0 ? ' negative' : ''
  }
  return (
    <div className="metric-card">
      <span className="card-label">{label}</span>
      <span className={cls}>{fmt}</span>
    </div>
  )
}
