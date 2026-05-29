import { useState, useMemo } from 'react'
import { Icon } from '../components/Icon'
import { Seg } from '../components/Seg'
import { ProxMeter } from '../components/ProxMeter'
import { EquityCurve } from '../charts/EquityCurve'
import { Donut } from '../charts/Donut'
import { Bars } from '../charts/Bars'
import { useSort } from '../hooks/useSort'
import { money } from '../utils/money'
import { computeCumulativePnl, computeDailyBars } from '../utils/stats'
import type { DashboardData, HistoryData, TradeData } from '../types'

interface Props {
  dashboard: DashboardData | null
  history: HistoryData | null
}

function proximityPct(order: { price_level: number; current_price: number; distance: number }): number {
  const maxDist = Math.abs(order.price_level - order.current_price)
  if (maxDist === 0) return 100
  const closeness = 1 - (Math.abs(order.distance) / (maxDist * 2))
  return Math.max(0, Math.min(100, Math.round(closeness * 100)))
}

function formatDist(d: number): string {
  const abs = Math.abs(d)
  if (abs >= 1) return abs.toFixed(1) + ' pts'
  return (abs * 10000).toFixed(1) + ' pips'
}

export function DashboardPage({ dashboard, history }: Props) {
  const [pnlP, setPnlP] = useState('all')
  const [wlP, setWlP] = useState('all')
  const [showAll, setShowAll] = useState(false)

  const positions = dashboard?.positions ?? []
  const pendingOrders = dashboard?.pending_orders ?? []
  const totalPnl = positions.reduce((s, p) => s + p.profit, 0)

  const posRows = useMemo(() => positions.map(p => ({
    sym: p.symbol,
    side: p.direction as 'long' | 'short',
    lot: p.volume,
    entry: p.price_open,
    cur: p.current_price,
    pnl: p.profit,
    trailing: p.is_trailing,
    ticket: p.ticket,
  })), [positions])

  const pos = useSort(posRows, 'pnl')

  const pending = useMemo(() =>
    [...pendingOrders]
      .sort((a, b) => Math.abs(a.distance) - Math.abs(b.distance))
      .map(o => ({
        sym: o.symbol,
        side: o.direction as 'long' | 'short',
        dist: formatDist(o.distance),
        limit: o.price_level.toFixed(5),
        lot: o.volume.toFixed(2),
        pct: proximityPct(o),
      })),
    [pendingOrders]
  )

  const visible = showAll ? pending : pending.slice(0, 3)

  const trades: TradeData[] = history?.trades ?? []
  const curve = useMemo(() => computeCumulativePnl(trades), [trades])
  const dailyBars = useMemo(() => computeDailyBars(trades), [trades])

  const curveData = curve.map(p => p.value)
  const curveLabels = curve.map(p => p.label)

  const stats = history?.stats
  const winRate = stats ? stats.win_rate : 0
  const wins = stats?.wins ?? 0
  const losses = stats?.losses ?? 0

  const recentTrades = useMemo(() =>
    trades
      .filter(t => t.status === 'closed')
      .sort((a, b) => (b.closed_at ?? '').localeCompare(a.closed_at ?? ''))
      .slice(0, 5),
    [trades]
  )

  const periods = [
    { value: 'daily', label: 'Day' },
    { value: 'weekly', label: 'Week' },
    { value: 'all', label: 'All' },
  ]

  const pnlValue = pnlP === 'all' ? (curve.length > 0 ? curve[curve.length - 1].value : 0) : totalPnl
  const pnlLabel = pnlP === 'daily' ? "Today's P&L" : pnlP === 'weekly' ? 'P&L · this week' : 'Cumulative P&L · all time'

  return (
    <div className="page">
      {/* HERO */}
      <div className="row">
        <div className="panel pad" style={{ flex: 2.1, minWidth: 0 }}>
          <div className="panel-head">
            <div>
              <div className="eyebrow">{pnlLabel}</div>
              <div className="metric" style={{ marginTop: 10 }}>
                <span className={`big mono ${pnlValue >= 0 ? 'pos' : 'neg'}`}>{money(pnlValue)}</span>
              </div>
            </div>
            <Seg value={pnlP} options={periods} onChange={setPnlP} />
          </div>
          <EquityCurve data={curveData} labels={curveLabels} height={210} />
          {curveLabels.length > 2 && (
            <div className="axisrow">
              {[curveLabels[0], curveLabels[Math.floor(curveLabels.length / 4)], curveLabels[Math.floor(curveLabels.length / 2)], curveLabels[Math.floor(curveLabels.length * 3 / 4)], curveLabels[curveLabels.length - 1]].filter(Boolean).map((a, i) => (
                <span key={i} className="mono">{a}</span>
              ))}
            </div>
          )}
        </div>

        <div className="panel pad" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <div className="panel-head">
            <div className="eyebrow">Win / loss</div>
            <Seg value={wlP} options={periods} onChange={setWlP} />
          </div>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16 }}>
            <Donut pct={winRate} size={160} />
            <div className="legend">
              <span><i style={{ background: 'var(--accent)' }} />{wins} wins</span>
              <span><i style={{ background: 'var(--surface-3)' }} />{losses} losses</span>
            </div>
          </div>
        </div>
      </div>

      {/* CLOSEST SIGNALS */}
      {pending.length > 0 && (
        <div className="panel pad">
          <div className="panel-head">
            <h3><Icon name="bell" size={17} /> Closest Signals</h3>
            {pending.length > 3 && (
              <button className="btn sm ghost" onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Show fewer' : `Show all ${pending.length}`}{' '}
                <Icon name="chevDown" size={14} style={{ transform: showAll ? 'rotate(180deg)' : '', transition: '.2s' }} />
              </button>
            )}
          </div>
          <div className="fill-grid">
            {visible.map((o, i) => (
              <div className={'fill-card' + (o.pct >= 75 ? ' hot' : '')} key={o.sym + i}>
                <div className="top">
                  <span className="sym">{o.sym}</span>
                  <span className={'tag ' + o.side}>{o.side}</span>
                </div>
                <ProxMeter pct={o.pct} label={o.dist} />
                <div className="fill-kv">
                  <div className="r"><span className="k">Limit</span><span className="val mono">{o.limit}</span></div>
                  <div className="r"><span className="k">Size</span><span className="val mono">{o.lot} lot</span></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* POSITIONS */}
      <div className="panel pad">
        <div className="panel-head">
          <h3>Open positions <span className="sub" style={{ fontWeight: 400 }}>— {positions.length} live</span></h3>
          <span className="sub">total <span className={`mono ${totalPnl >= 0 ? 'pos' : 'neg'}`} style={{ fontWeight: 600 }}>{money(totalPnl)}</span></span>
        </div>
        {positions.length === 0 ? (
          <p className="faint" style={{ padding: '12px 0' }}>No open positions</p>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th onClick={() => pos.onSort('sym')}>Symbol{pos.ind('sym')}</th>
                <th onClick={() => pos.onSort('side')}>Side{pos.ind('side')}</th>
                <th className="num" onClick={() => pos.onSort('lot')}>Lot{pos.ind('lot')}</th>
                <th className="num">Entry</th>
                <th className="num">Current</th>
                <th className="num" onClick={() => pos.onSort('pnl')}>P&L{pos.ind('pnl')}</th>
                <th>Stage</th>
              </tr>
            </thead>
            <tbody>
              {pos.sorted.map(p => (
                <tr key={p.ticket}>
                  <td><span className="sym">{p.sym}</span></td>
                  <td><span className={'tag ' + p.side}>{p.side}</span></td>
                  <td className="num mono">{p.lot.toFixed(2)}</td>
                  <td className="num mono dim">{p.entry.toFixed(5)}</td>
                  <td className="num mono">{p.cur.toFixed(5)}</td>
                  <td className={'num mono ' + (p.pnl >= 0 ? 'pos' : 'neg')} style={{ fontWeight: 600 }}>{money(p.pnl)}</td>
                  <td>
                    {p.trailing
                      ? <span className="tag trail"><span className="dot-live" /> trailing</span>
                      : <span className="tag ghost">holding</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* RECENT + DAILY */}
      <div className="row">
        <div className="panel pad" style={{ flex: 1.25, minWidth: 0 }}>
          <div className="panel-head">
            <h3>Recent trades</h3>
            <span className="sub">closed · last 24h</span>
          </div>
          {recentTrades.length === 0 ? (
            <p className="faint">No recent trades</p>
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th className="num">Total P&L</th>
                  <th className="num">Time</th>
                </tr>
              </thead>
              <tbody>
                {recentTrades.map((r, i) => (
                  <tr key={i}>
                    <td><span className="sym">{r.symbol || '—'}</span></td>
                    <td><span className={'tag ' + (r.direction.includes('buy') || r.direction.includes('long') ? 'long' : 'short')}>
                      {r.direction.includes('buy') || r.direction.includes('long') ? 'long' : 'short'}
                    </span></td>
                    <td className="num mono" style={{ color: r.realized_pnl >= 0 ? 'var(--pos)' : 'var(--neg)', fontWeight: 600 }}>
                      {money(r.realized_pnl)}
                    </td>
                    <td className="num t-sub">
                      {r.closed_at ? new Date(r.closed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="panel pad" style={{ flex: 1, minWidth: 0 }}>
          <div className="panel-head">
            <h3>Daily P&L</h3>
            <span className="sub">{dailyBars.length} sessions</span>
          </div>
          <Bars data={dailyBars} height={172} />
        </div>
      </div>
    </div>
  )
}
