import type { Config, StatusData } from './types'

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
