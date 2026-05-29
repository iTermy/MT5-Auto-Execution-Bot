import { useState } from 'react'
import type { TradeData } from '../types'

interface Props {
  trades: TradeData[]
}

type SortKey = 'symbol' | 'direction' | 'lot_size' | 'placed_at' | 'status' | 'realized_pnl'

const FILTER_OPTIONS = ['All', 'closed', 'cancelled', 'spread_cancelled'] as const

export function TradesTable({ trades }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('placed_at')
  const [sortAsc, setSortAsc] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string>('All')
  const [symbolFilter, setSymbolFilter] = useState('')

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(false) }
  }

  const symbols = [...new Set(trades.map(t => t.symbol).filter(Boolean))].sort()

  let filtered = trades
  if (statusFilter !== 'All') filtered = filtered.filter(t => t.status === statusFilter)
  if (symbolFilter) filtered = filtered.filter(t => t.symbol === symbolFilter)

  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey]
    const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number)
    return sortAsc ? cmp : -cmp
  })

  return (
    <div className="table-section">
      <div className="table-header">
        <h3 className="section-title">
          Trades
          <span className="section-count">{filtered.length}</span>
        </h3>
        <div className="table-filters">
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            {FILTER_OPTIONS.map(s => <option key={s} value={s}>{s === 'All' ? 'All Statuses' : s}</option>)}
          </select>
          <select value={symbolFilter} onChange={e => setSymbolFilter(e.target.value)}>
            <option value="">All Symbols</option>
            {symbols.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>
      {sorted.length === 0 ? (
        <p className="muted">No trades match filters</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <Th label="Symbol" k="symbol" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <Th label="Dir" k="direction" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <Th label="Lot" k="lot_size" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="Placed" k="placed_at" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <Th label="Status" k="status" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <th>Scalp</th>
              <Th label="P&L" k="realized_pnl" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
            </tr>
          </thead>
          <tbody>
            {sorted.map(t => (
              <tr key={t.id}>
                <td>{t.symbol || '—'}</td>
                <td className={t.direction.includes('buy') || t.direction.includes('long') ? 'positive' : 'negative'}>
                  {t.direction}
                </td>
                <td className="num">{t.lot_size?.toFixed(2) ?? '—'}</td>
                <td>{formatTime(t.placed_at)}</td>
                <td><span className={`status-badge ${t.status}`}>{t.status}</span></td>
                <td>{t.is_scalp ? 'Yes' : ''}</td>
                <td className={`num ${t.realized_pnl > 0 ? 'positive' : t.realized_pnl < 0 ? 'negative' : ''}`}>
                  {t.realized_pnl !== 0 ? (t.realized_pnl > 0 ? '+' : '') + t.realized_pnl.toFixed(2) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function Th({ label, k, current, asc, onClick, align }: {
  label: string
  k: SortKey
  current: SortKey
  asc: boolean
  onClick: (k: SortKey) => void
  align?: string
}) {
  const arrow = current === k ? (asc ? ' ▲' : ' ▼') : ''
  return (
    <th className={`sortable ${align === 'right' ? 'num' : ''}`} onClick={() => onClick(k)}>
      {label}{arrow}
    </th>
  )
}
