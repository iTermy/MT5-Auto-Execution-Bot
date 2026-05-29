import { useState, useEffect, useMemo } from 'react'
import { fetchHistory } from '../api'
import { Seg } from '../components/Seg'
import { useSort } from '../hooks/useSort'
import { money } from '../utils/money'
import { computeDetailedStats, formatHoldTime } from '../utils/stats'
import type { HistoryData } from '../types'

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

function monthAgoStr(): string {
  const d = new Date()
  d.setMonth(d.getMonth() - 1)
  return d.toISOString().slice(0, 10)
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('en', { month: 'short', day: 'numeric' }) + ' · ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function HistoryPage() {
  const [fromDate, setFromDate] = useState(monthAgoStr)
  const [toDate, setToDate] = useState(todayStr)
  const [data, setData] = useState<HistoryData | null>(null)
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')

  useEffect(() => {
    const from = `${fromDate}T00:00:00`
    const to = `${toDate}T23:59:59`
    fetchHistory(from, to).then(setData).catch(() => {})
  }, [fromDate, toDate])

  const trades = data?.trades ?? []

  const filtered = useMemo(() => {
    let rows = trades
    if (typeFilter !== 'all') {
      rows = rows.filter(t => {
        if (typeFilter === 'scalp') return t.is_scalp
        return !t.is_scalp && typeFilter === 'standard'
      })
    }
    if (statusFilter !== 'all') {
      rows = rows.filter(t => t.status === statusFilter)
    }
    return rows
  }, [trades, typeFilter, statusFilter])

  const h = useSort(
    filtered.map(t => ({
      ...t,
      t: t.closed_at || t.placed_at,
      sym: t.symbol,
      side: t.direction,
      lot: t.lot_size,
      kind: t.is_scalp ? 'scalp' : 'standard',
      pnl: t.realized_pnl,
    })),
    't'
  )

  const detailedStats = useMemo(() => computeDetailedStats(trades), [trades])

  const stat = (label: string, value: string, cls?: string, note?: string, small?: boolean) => (
    <div className="statcell">
      <div className="l">{label}</div>
      <div className={`v ${small ? 's ' : ''}${cls || ''}`}>{value}</div>
      {note && <div className="n">{note}</div>}
    </div>
  )

  const tradeCount = trades.filter(t => t.status === 'closed').length

  return (
    <div className="page">
      <div>
        <div className="eyebrow">Analytics</div>
        <h2 style={{ margin: '4px 0 0', fontSize: 24, fontWeight: 700, letterSpacing: '-0.01em' }}>Trade history</h2>
      </div>

      {/* FILTERS */}
      <div className="panel pad">
        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="field">
            <label>From</label>
            <input
              type="date"
              className="inp mono"
              value={fromDate}
              onChange={e => setFromDate(e.target.value)}
              style={{ width: 160, colorScheme: 'light' }}
            />
          </div>
          <div className="field">
            <label>To</label>
            <input
              type="date"
              className="inp mono"
              value={toDate}
              onChange={e => setToDate(e.target.value)}
              style={{ width: 160, colorScheme: 'light' }}
            />
          </div>
          <div className="field">
            <label>Status</label>
            <Seg
              value={statusFilter}
              options={[
                { value: 'all', label: 'All' },
                { value: 'closed', label: 'Closed' },
                { value: 'cancelled', label: 'Cancelled' },
              ]}
              onChange={setStatusFilter}
            />
          </div>
          <div className="field">
            <label>Type</label>
            <Seg
              value={typeFilter}
              options={[
                { value: 'all', label: 'All' },
                { value: 'standard', label: 'Standard' },
                { value: 'scalp', label: 'Scalp' },
              ]}
              onChange={setTypeFilter}
            />
          </div>
        </div>
      </div>

      {/* STATISTICS */}
      {trades.length > 0 && (
        <div className="panel" style={{ overflow: 'hidden' }}>
          <div className="panel-head" style={{ padding: '20px 22px 0', marginBottom: 0 }}>
            <h3>Performance <span className="sub" style={{ fontWeight: 400 }}>— {tradeCount} trades</span></h3>
          </div>
          <div className="statgrid" style={{ marginTop: 18 }}>
            {stat('Net P&L', money(detailedStats.netPnl), detailedStats.netPnl >= 0 ? 'pos' : 'neg')}
            {stat('Win rate', `${detailedStats.winRate.toFixed(0)}%`, '', `${detailedStats.wins} W · ${detailedStats.losses} L`)}
            {stat('Profit factor', detailedStats.profitFactor === Infinity ? '∞' : detailedStats.profitFactor.toFixed(2))}
            {stat('Expectancy', money(detailedStats.expectancy), detailedStats.expectancy >= 0 ? 'pos' : 'neg', 'avg per trade')}
            {stat('Average win', money(detailedStats.avgWin), 'pos', `across ${detailedStats.wins} wins`, true)}
            {stat('Average loss', money(detailedStats.avgLoss), 'neg', `across ${detailedStats.losses} losses`, true)}
            {stat('Best trade', money(detailedStats.bestTrade.pnl), 'pos', detailedStats.bestTrade.symbol, true)}
            {stat('Worst trade', money(detailedStats.worstTrade.pnl), 'neg', detailedStats.worstTrade.symbol, true)}
            {stat('Win streak', String(detailedStats.winStreak), '', undefined, true)}
            {stat('Loss streak', String(detailedStats.lossStreak), '', undefined, true)}
            {stat('Avg hold', formatHoldTime(detailedStats.avgHoldMinutes), '', 'open → close', true)}
            {stat('Scalp share', `${detailedStats.scalpShare.toFixed(0)}%`, '', undefined, true)}
          </div>
        </div>
      )}

      {/* TRADES TABLE */}
      <div className="panel pad">
        <div className="panel-head">
          <h3>Trades</h3>
          <span className="sub">{filtered.length} results · click any header to sort</span>
        </div>
        {filtered.length === 0 ? (
          <p className="faint" style={{ padding: '12px 0' }}>No trades match filters</p>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th onClick={() => h.onSort('t')}>Closed{h.ind('t')}</th>
                <th onClick={() => h.onSort('sym')}>Symbol{h.ind('sym')}</th>
                <th onClick={() => h.onSort('side')}>Side{h.ind('side')}</th>
                <th className="num" onClick={() => h.onSort('lot')}>Lot{h.ind('lot')}</th>
                <th onClick={() => h.onSort('kind')}>Type{h.ind('kind')}</th>
                <th>Status</th>
                <th className="num" onClick={() => h.onSort('pnl')}>Realized P&L{h.ind('pnl')}</th>
              </tr>
            </thead>
            <tbody>
              {h.sorted.map((r, i) => (
                <tr key={i}>
                  <td className="t-sub mono">{formatTime(r.t)}</td>
                  <td><span className="sym">{r.sym || '—'}</span></td>
                  <td>
                    <span className={`tag ${r.side.includes('buy') || r.side.includes('long') ? 'long' : 'short'}`}>
                      {r.side.includes('buy') || r.side.includes('long') ? 'long' : 'short'}
                    </span>
                  </td>
                  <td className="num mono">{r.lot?.toFixed(2) ?? '—'}</td>
                  <td>
                    {r.kind === 'scalp'
                      ? <span className="tag scalp">Scalp</span>
                      : <span className="t-sub">Standard</span>}
                  </td>
                  <td>
                    {r.status === 'closed'
                      ? <span className="tag trail">closed</span>
                      : <span className="tag ghost">{r.status}</span>}
                  </td>
                  <td className={`num mono ${r.pnl > 0 ? 'pos' : r.pnl < 0 ? 'neg' : 'faint'}`} style={{ fontWeight: 600 }}>
                    {r.pnl === 0 ? '—' : money(r.pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
