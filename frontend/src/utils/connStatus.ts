import type { StatusData } from '../types'

// Each connection indicator is one of three independent states:
//   live  — connected and working now (green)
//   idle  — not attempted yet / can't determine (grey)
//   error — a known, active failure (red)
export type ConnState = 'live' | 'idle' | 'error'

export interface ConnStatus {
  state: ConnState
  detail?: string
}

export interface ConnStatuses {
  mt5: ConnStatus
  database: ConnStatus
  license: ConnStatus
}

// Derive the three indicators independently from the backend status. Each uses its
// own error field as the discriminator between "idle" (never attempted / unknown)
// and "error" (a real, reported failure) so they never bleed into each other.
export function deriveConnStatuses(status: StatusData | null, connected: boolean): ConnStatuses {
  // No live feed from the backend → nothing is known, show everything as idle.
  if (!connected || !status) {
    return { mt5: { state: 'idle' }, database: { state: 'idle' }, license: { state: 'idle' } }
  }

  // MT5: connected → live; a recorded init/connection error → error; else not attempted.
  const mt5: ConnStatus = status.mt5_connected
    ? { state: 'live' }
    : status.mt5_error
      ? { state: 'error', detail: status.mt5_error }
      : { state: 'idle' }

  // Database: pool open → live; a recorded connection failure → error; else idle.
  const database: ConnStatus = status.supabase_connected
    ? { state: 'live' }
    : status.supabase_error
      ? { state: 'error', detail: status.supabase_error }
      : { state: 'idle' }

  // License: valid → live; a confirmed rejection (invalid/expired key or wrong account)
  // → error; an unreachable server or a check that hasn't run yet stays idle (unknown).
  const license: ConnStatus = status.license_valid
    ? { state: 'live' }
    : status.license_status === 'invalid' || status.license_status === 'expired'
      ? { state: 'error', detail: status.license_message || undefined }
      : { state: 'idle' }

  return { mt5, database, license }
}

// Maps a state to its `.conn` modifier class (see index.css).
export const CONN_CLASS: Record<ConnState, string> = {
  live: 'live',
  idle: 'idle',
  error: 'err',
}
