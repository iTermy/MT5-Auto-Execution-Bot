import { useState, useEffect } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { fetchHistory } from '../api'
import { StatsCards } from '../components/StatsCards'
import { TradesTable } from '../components/TradesTable'
import type { HistoryData } from '../types'

function todayStr(): string {
  const d = new Date()
  return d.toISOString().slice(0, 10)
}

function monthAgoStr(): string {
  const d = new Date()
  d.setMonth(d.getMonth() - 1)
  return d.toISOString().slice(0, 10)
}

export function HistoryPage() {
  const [fromDate, setFromDate] = useState(monthAgoStr)
  const [toDate, setToDate] = useState(todayStr)
  const [data, setData] = useState<HistoryData | null>(null)

  useEffect(() => {
    const from = `${fromDate}T00:00:00`
    const to = `${toDate}T23:59:59`
    fetchHistory(from, to).then(setData).catch(() => {})
  }, [fromDate, toDate])

  const chartData = data?.trades
    .filter(t => t.status === 'closed' && t.realized_pnl !== 0)
    .map(t => ({
      name: t.symbol || `#${t.signal_id}`,
      pnl: t.realized_pnl,
    })) ?? []

  return (
    <div className="page">
      <div className="history-controls">
        <label className="date-label">
          From
          <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} />
        </label>
        <label className="date-label">
          To
          <input type="date" value={toDate} onChange={e => setToDate(e.target.value)} />
        </label>
      </div>

      {data && <StatsCards stats={data.stats} />}

      {chartData.length > 0 && (
        <div className="chart-section">
          <h3 className="section-title">P&L by Trade</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="name" tick={{ fill: '#6b7280', fontSize: 11 }} />
              <YAxis tick={{ fill: '#6b7280', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6, color: '#e5e7eb' }}
              />
              <Bar dataKey="pnl" radius={[3, 3, 0, 0]}>
                {chartData.map((entry, i) => (
                  <Cell key={i} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {data && <TradesTable trades={data.trades} />}
    </div>
  )
}
