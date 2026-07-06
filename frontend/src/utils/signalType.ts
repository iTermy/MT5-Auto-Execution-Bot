import type { SignalType } from '../types'

const LABELS: Record<SignalType, string> = {
  standard: 'Standard',
  scalp: 'Scalp',
  swing: 'Swing',
  toll: 'Toll',
  pa: 'PA',
  '1-1': '1-1',
  risky: 'Risky',
}

const BADGE_CLASS: Record<SignalType, string> = {
  standard: 'ghost',
  scalp: 'scalp',
  swing: 'swing',
  toll: 'toll',
  pa: 'pa',
  '1-1': 'one-to-one',
  risky: 'risky',
}

export const SIGNAL_TYPES: SignalType[] = [
  'standard',
  'scalp',
  'swing',
  'toll',
  'pa',
  '1-1',
  'risky',
]

export function formatSignalType(t: SignalType | string | null | undefined): string {
  if (!t) return 'Standard'
  return LABELS[t as SignalType] ?? 'Standard'
}

export function badgeClassFor(t: SignalType | string | null | undefined): string {
  if (!t) return 'ghost'
  return BADGE_CLASS[t as SignalType] ?? 'ghost'
}
