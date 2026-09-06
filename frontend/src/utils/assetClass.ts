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

// DB symbols only — never a broker symbol. Trades carry the backend's own
// `asset_class`; use that (via basketOf) rather than reclassifying here, because
// order_mappings stores the *broker* symbol and reversing it needs symbol_map and
// suffix config this module doesn't have. The one legitimate caller is the settings
// grouping of tp_config.instrument_overrides, whose keys are DB symbols by definition.
//
// Keep these three lists byte-for-byte in step with _METALS / _OIL_KEYWORDS /
// _INDEX_KEYWORDS in bot/trading/symbol_mapper.py, which is authoritative.
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

/** Collapse a backend asset_class into the coarser basket the history filters use.
 * Takes the class, never a symbol, so a broker symbol can't be classified by mistake. */
export function basketOf(assetClass: string): AssetBasket {
  if (assetClass === 'forex_jpy') return 'forex'
  if (assetClass === 'oil') return 'energy'
  if (assetClass in ASSET_BASKET_LABELS) return assetClass as AssetBasket
  return 'forex'
}
