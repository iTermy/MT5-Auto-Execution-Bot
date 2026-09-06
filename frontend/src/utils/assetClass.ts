export type AssetClass = 'forex' | 'forex_jpy' | 'metals' | 'indices' | 'stocks' | 'crypto' | 'oil'

export type AssetBasket = 'forex' | 'metals' | 'indices' | 'stocks' | 'crypto' | 'energy'

export const ASSET_BASKET_LABELS: Record<AssetBasket, string> = {
  forex: 'Forex',
  metals: 'Metals',
  indices: 'Indices',
  stocks: 'Stocks',
  crypto: 'Crypto',
  energy: 'Energy',
}

// Keep these three lists byte-for-byte in step with _METALS / _OIL_KEYWORDS /
// _INDEX_KEYWORDS in bot/trading/symbol_mapper.py — that module is authoritative and
// this is a display-side port. A keyword missing here silently buckets an index or oil
// trade under "Forex" in the breakdowns (XTIUSD, F40, HK50, CHINA50, AUS2000, US2000).
const METALS = new Set(['XAUUSD', 'XAGUSD', 'GOLD', 'SILVER'])
const OIL_KEYWORDS = ['OIL', 'WTI', 'BRENT', 'XTI']
const INDEX_KEYWORDS = [
  'SPX',
  'NAS',
  'DAX',
  'DE30',
  'DE40',
  'F40',
  'JP225',
  'UK100',
  'US30',
  'US500',
  'US2000',
  'AUS200',
  'USTEC',
  'HK50',
  'CHINA',
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

export function getAssetBasket(dbSymbol: string): AssetBasket {
  const assetClass = detectAssetClass(dbSymbol)
  if (assetClass === 'forex_jpy') return 'forex'
  if (assetClass === 'oil') return 'energy'
  return assetClass
}
