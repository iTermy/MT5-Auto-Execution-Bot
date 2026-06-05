export type AssetClass = 'forex' | 'forex_jpy' | 'metals' | 'indices' | 'stocks' | 'crypto' | 'oil'

const METALS = new Set(['XAUUSD', 'XAGUSD', 'GOLD', 'SILVER'])
const OIL_KEYWORDS = ['OIL', 'WTI', 'BRENT']
const INDEX_KEYWORDS = [
  'SPX',
  'NAS',
  'DAX',
  'DE30',
  'DE40',
  'JP225',
  'UK100',
  'US500',
  'USTEC',
  'US30',
]

export function detectAssetClass(dbSymbol: string): AssetClass {
  const s = dbSymbol.toUpperCase()

  if (METALS.has(s)) return 'metals'
  if (OIL_KEYWORDS.some(k => s.includes(k))) return 'oil'
  if (s.endsWith('.NAS') || s.endsWith('.NYSE')) return 'stocks'
  if (s.startsWith('MGC') || s.startsWith('GC')) return 'metals'
  if (INDEX_KEYWORDS.some(k => s.includes(k))) return 'indices'
  if ((s.endsWith('USD') || s.endsWith('USDT')) && s.length > 6) return 'crypto'
  if (s.includes('JPY')) return 'forex_jpy'
  return 'forex'
}
