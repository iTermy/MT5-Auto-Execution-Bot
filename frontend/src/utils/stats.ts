import type { TradeData, HistoryStats } from '../types'

export interface DetailedStats {
  netPnl: number
  winRate: number
  wins: number
  losses: number
  profitFactor: number
  expectancy: number
  avgWin: number
  avgLoss: number
  bestTrade: { pnl: number; symbol: string }
  worstTrade: { pnl: number; symbol: string }
  winStreak: number
  lossStreak: number
  avgHoldMinutes: number
  scalpShare: number
  totalTrades: number
}

export function computeDetailedStats(trades: TradeData[]): DetailedStats {
  const closed = trades.filter(t => t.status === 'closed')
  const wins = closed.filter(t => t.realized_pnl > 0)
  const losses = closed.filter(t => t.realized_pnl < 0)

  const grossWin = wins.reduce((s, t) => s + t.realized_pnl, 0)
  const grossLoss = Math.abs(losses.reduce((s, t) => s + t.realized_pnl, 0))
  const netPnl = closed.reduce((s, t) => s + t.realized_pnl, 0)

  const best = closed.reduce((b, t) => t.realized_pnl > b.pnl ? { pnl: t.realized_pnl, symbol: t.symbol } : b, { pnl: -Infinity, symbol: '' })
  const worst = closed.reduce((w, t) => t.realized_pnl < w.pnl ? { pnl: t.realized_pnl, symbol: t.symbol } : w, { pnl: Infinity, symbol: '' })

  let winStreak = 0, lossStreak = 0, curWin = 0, curLoss = 0
  for (const t of closed) {
    if (t.realized_pnl > 0) { curWin++; curLoss = 0 }
    else if (t.realized_pnl < 0) { curLoss++; curWin = 0 }
    winStreak = Math.max(winStreak, curWin)
    lossStreak = Math.max(lossStreak, curLoss)
  }

  let totalHold = 0, holdCount = 0
  for (const t of closed) {
    const closeTs = t.closed_at || t.filled_at || t.placed_at
    if (t.filled_at && closeTs) {
      const ms = new Date(closeTs).getTime() - new Date(t.filled_at).getTime()
      if (ms > 0) { totalHold += ms; holdCount++ }
    }
  }

  const scalps = closed.filter(t => t.is_scalp).length

  return {
    netPnl,
    winRate: closed.length > 0 ? (wins.length / closed.length) * 100 : 0,
    wins: wins.length,
    losses: losses.length,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? Infinity : 0,
    expectancy: closed.length > 0 ? netPnl / closed.length : 0,
    avgWin: wins.length > 0 ? grossWin / wins.length : 0,
    avgLoss: losses.length > 0 ? grossLoss / losses.length : 0,
    bestTrade: best.pnl === -Infinity ? { pnl: 0, symbol: '—' } : best,
    worstTrade: worst.pnl === Infinity ? { pnl: 0, symbol: '—' } : worst,
    winStreak,
    lossStreak,
    avgHoldMinutes: holdCount > 0 ? totalHold / holdCount / 60000 : 0,
    scalpShare: closed.length > 0 ? (scalps / closed.length) * 100 : 0,
    totalTrades: closed.length,
  }
}

export interface DailyBar {
  date: string
  label: string
  value: number
}

export function computeDailyBars(trades: TradeData[]): DailyBar[] {
  const byDay = new Map<string, number>()
  for (const t of trades) {
    if (t.status !== 'closed') continue
    const ts = t.closed_at || t.filled_at || t.placed_at
    if (!ts) continue
    const day = ts.slice(0, 10)
    byDay.set(day, (byDay.get(day) ?? 0) + t.realized_pnl)
  }
  const sorted = [...byDay.entries()].sort(([a], [b]) => a.localeCompare(b))
  return sorted.slice(-14).map(([date, value]) => {
    const d = new Date(date + 'T00:00:00')
    const label = String(d.getDate())
    const month = d.toLocaleDateString('en', { month: 'short' })
    return { date: `${month} ${label}`, label, value: Math.round(value * 100) / 100 }
  })
}

export interface CurvePoint {
  label: string
  value: number
}

export function computeCumulativePnl(trades: TradeData[]): CurvePoint[] {
  const closed = trades
    .filter(t => t.status === 'closed' && (t.closed_at || t.filled_at || t.placed_at))
    .sort((a, b) => {
      const ta = a.closed_at || a.filled_at || a.placed_at
      const tb = b.closed_at || b.filled_at || b.placed_at
      return ta.localeCompare(tb)
    })

  if (closed.length === 0) return [{ label: 'Start', value: 0 }]

  const points: CurvePoint[] = [{ label: 'Start', value: 0 }]
  let cum = 0
  for (const t of closed) {
    cum += t.realized_pnl
    const ts = t.closed_at || t.filled_at || t.placed_at
    const d = new Date(ts)
    const label = d.toLocaleDateString('en', { month: 'short', day: 'numeric' })
    points.push({ label, value: Math.round(cum * 100) / 100 })
  }
  return points
}

export function computeBasicStats(stats: HistoryStats | null) {
  if (!stats) return null
  return {
    winRate: stats.win_rate,
    wins: stats.wins,
    losses: stats.losses,
  }
}

export function formatHoldTime(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return `${h}h ${m}m`
}

export type Period = 'daily' | 'weekly' | 'all'

export function filterTradesByPeriod(trades: TradeData[], period: Period): TradeData[] {
  if (period === 'all') return trades
  const cutoff = Date.now() - (period === 'daily' ? 86400000 : 7 * 86400000)
  return trades.filter(t => {
    const ts = t.closed_at || t.filled_at || t.placed_at
    return ts && new Date(ts).getTime() >= cutoff
  })
}

export function groupBySignalId<T extends { signal_id: number }>(items: T[]): Map<number, T[]> {
  const map = new Map<number, T[]>()
  for (const item of items) {
    const group = map.get(item.signal_id) ?? []
    group.push(item)
    map.set(item.signal_id, group)
  }
  return map
}

