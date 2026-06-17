import type { Config, DashboardData, HistoryData, StatusData } from './types'

export async function fetchStatus(): Promise<StatusData> {
  const r = await fetch('/api/status')
  if (!r.ok) throw new Error(`GET /api/status ${r.status}`)
  return r.json()
}

export async function fetchConfig(): Promise<Config> {
  const r = await fetch('/api/config')
  if (!r.ok) throw new Error(`GET /api/config ${r.status}`)
  return r.json()
}

export async function updateConfig(config: Config): Promise<void> {
  const r = await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!r.ok) throw new Error(`PUT /api/config ${r.status}`)
}

export async function startEngine(): Promise<void> {
  const r = await fetch('/api/engine/start', { method: 'POST' })
  if (!r.ok) throw new Error(`POST /api/engine/start ${r.status}`)
}

export async function stopEngine(): Promise<void> {
  const r = await fetch('/api/engine/stop', { method: 'POST' })
  if (!r.ok) throw new Error(`POST /api/engine/stop ${r.status}`)
}

export async function shutdownEngine(): Promise<void> {
  const r = await fetch('/api/engine/shutdown', { method: 'POST' })
  if (!r.ok) throw new Error(`POST /api/engine/shutdown ${r.status}`)
}

export async function installUpdate(): Promise<void> {
  const r = await fetch('/api/update/install', { method: 'POST' })
  if (!r.ok) throw new Error(`POST /api/update/install ${r.status}`)
}

export async function fetchDashboard(): Promise<DashboardData> {
  const r = await fetch('/api/dashboard')
  if (!r.ok) throw new Error(`GET /api/dashboard ${r.status}`)
  return r.json()
}

export async function scanMt5Terminals(): Promise<string[]> {
  const r = await fetch('/api/mt5/terminals')
  if (!r.ok) throw new Error(`GET /api/mt5/terminals ${r.status}`)
  const data = (await r.json()) as { paths: string[] }
  return data.paths
}

export async function fetchMt5Symbols(): Promise<string[]> {
  const r = await fetch('/api/mt5/symbols')
  if (!r.ok) throw new Error(`GET /api/mt5/symbols ${r.status}`)
  const data = (await r.json()) as { symbols: string[] }
  return data.symbols
}

export async function fetchNotFoundSymbols(): Promise<string[]> {
  const r = await fetch('/api/mt5/not-found-symbols')
  if (!r.ok) throw new Error(`GET /api/mt5/not-found-symbols ${r.status}`)
  const data = (await r.json()) as { symbols: string[] }
  return data.symbols
}

export async function fetchHistory(fromDate?: string, toDate?: string): Promise<HistoryData> {
  const params = new URLSearchParams()
  if (fromDate) params.set('from_date', fromDate)
  if (toDate) params.set('to_date', toDate)
  const q = params.toString()
  const r = await fetch(`/api/history${q ? '?' + q : ''}`)
  if (!r.ok) throw new Error(`GET /api/history ${r.status}`)
  return r.json()
}
