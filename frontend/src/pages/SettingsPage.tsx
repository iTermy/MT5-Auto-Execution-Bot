import { useState, useEffect, useCallback, useMemo, useRef, Fragment } from 'react'
import type { ReactNode } from 'react'
import { Icon } from '../components/Icon'
import { Seg } from '../components/Seg'
import {
  startEngine,
  stopEngine,
  shutdownEngine,
  updateConfig,
  scanMt5Terminals,
  fetchMt5Symbols,
  fetchNotFoundSymbols,
  fetchApproximateLots,
} from '../api'
import type {
  Config,
  StatusData,
  TPConfig,
  AssetTPConfig,
  ScalpOverrideConfig,
  LotExceptionConfig,
  ExcludedTradeConfig,
  ExcludedChannelAssetConfig,
  SymbolSuffixRule,
} from '../types'
import { detectAssetClass } from '../utils/assetClass'
import { deriveConnStatuses, CONN_CLASS, type ConnState } from '../utils/connStatus'
import { CHANNELS } from '../utils/channels'

const ASSET_CLASSES = [
  'forex',
  'forex_jpy',
  'metals',
  'indices',
  'stocks',
  'crypto',
  'oil',
] as const
type AssetKey = (typeof ASSET_CLASSES)[number]

// Display labels for the asset-class dropdowns.
const ASSET_CLASS_LABELS: Record<AssetKey, string> = {
  forex: 'Forex',
  forex_jpy: 'Forex (JPY)',
  metals: 'Metals',
  indices: 'Indices',
  stocks: 'Stocks',
  crypto: 'Crypto',
  oil: 'Oil',
}

type OverrideType = 'scalp' | 'toll' | 'swing' | 'pa'
const OVERRIDE_TYPES: OverrideType[] = ['scalp', 'toll', 'swing', 'pa']

// Lot-sizing exceptions can target a specific signal type; "all" = every type.
const LOT_SIGNAL_TYPES: { value: string; label: string }[] = [
  { value: 'all', label: 'All types' },
  { value: 'standard', label: 'Standard' },
  { value: 'scalp', label: 'Scalp' },
  { value: 'swing', label: 'Swing' },
  { value: 'toll', label: 'Toll' },
  { value: 'pa', label: 'PA' },
  { value: '1-1', label: '1-1' },
  { value: 'risky', label: 'Risky' },
]

// Concrete signal types (no "all") — used for the wholesale skip checkboxes.
const SIGNAL_TYPES = LOT_SIGNAL_TYPES.filter(t => t.value !== 'all')

// Built-in offset-feed instruments. Their feed type and presence are fixed — users
// can only re-map the broker symbol, not change the feed or remove the row. Must
// stay in sync with DEFAULT_OFFSET_INSTRUMENTS in bot/config/settings.py.
const LOCKED_OFFSET_INSTRUMENTS = new Set([
  'SPX500USD',
  'NAS100USD',
  'BTCUSDT',
  'ETHUSDT',
  'US30USD',
  'US2000USD',
  'USOILSPOT',
  'DE30EUR',
  'UK100USD',
  'JP225',
])

// Status word for a connection indicator: its own verb when live/error, "idle" otherwise.
const connWord = (state: ConnState, live: string, error: string) =>
  state === 'live' ? live : state === 'error' ? error : 'idle'

// Trailing % is the inverse of partial_close_percent (storage unchanged).
const partialToTrailing = (p: number) => Math.max(0, Math.min(100, 100 - p))
const trailingToPartial = (t: number) => Math.max(0, Math.min(100, 100 - t))

interface OverridePair {
  thr: string
  trail: string
  partial: string // empty string means "inherit from standard"
}

interface TpRow {
  asset: string
  thr: string
  unit: string
  trail: string
  partial: string // per-asset standard partial close % (default 50)
  overrides: Record<OverrideType, OverridePair>
}

interface OneToOneOverrideRow {
  asset: string
  value: string
}

interface SymbolRow {
  db: string
  mt5: string
  feed: boolean
}

interface LotExceptionRow {
  symbol: string
  channel: string
  signalType: string
  mode: 'risk_percent' | 'fixed' | 'total_lot'
  value: string
}

interface SuffixRuleRow {
  suffix: string
  classes: AssetKey[]
}

interface ExcludedTradeRow {
  symbol: string
  signalType: string
}

interface ExcludedChannelAssetRow {
  channel: string
  assetClass: string
}

interface InstrumentOverrideRow {
  symbol: string
  // Standard fields — empty string means "inherit asset-class value".
  thr: string
  trail: string
  partial: string // stored as partial_close_percent in config; UI displays trailing
  // Per-signal-type overrides — empty strings mean "inherit".
  overrides: Record<OverrideType, OverridePair>
}

const FLAT_OVERRIDE_FIELDS = [
  'profit_threshold',
  'trailing_distance',
  'threshold_unit',
  'partial_close_percent',
] as const

const emptyOverridePairs = (): Record<OverrideType, OverridePair> =>
  Object.fromEntries(OVERRIDE_TYPES.map(t => [t, { thr: '', trail: '', partial: '' }])) as Record<
    OverrideType,
    OverridePair
  >

// Select-styled dropdown that toggles multiple asset classes. Matches the native
// `.inp.sel` controls; selected rows are filled with the accent tint, classes
// already claimed by another suffix rule are disabled.
function MultiClassPicker({
  selected,
  disabledClasses,
  onToggle,
}: {
  selected: AssetKey[]
  disabledClasses: Set<AssetKey>
  onToggle: (cls: AssetKey) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])
  const summary = selected.length ? selected.join(', ') : 'Select asset classes'
  return (
    <div
      ref={ref}
      data-classpicker-open={open ? '' : undefined}
      style={{ position: 'relative', width: 280 }}
    >
      <div className="inp sel mono" onClick={() => setOpen(o => !o)} style={{ width: '100%' }}>
        <span
          className={selected.length ? undefined : 'faint'}
          style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {summary}
        </span>
        <Icon
          name="chevDown"
          size={14}
          strokeWidth={2.2}
          style={{
            flexShrink: 0,
            opacity: 0.6,
            transform: open ? 'rotate(180deg)' : 'none',
            transition: 'transform 120ms ease',
          }}
        />
      </div>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 4px)',
            left: 0,
            width: '100%',
            background: 'var(--surface)',
            border: '1px solid var(--hairline-strong)',
            borderRadius: 10,
            boxShadow: 'var(--shadow)',
            padding: 4,
            zIndex: 30,
          }}
        >
          {ASSET_CLASSES.map(cls => {
            const active = selected.includes(cls)
            const disabled = !active && disabledClasses.has(cls)
            return (
              <button
                key={cls}
                type="button"
                disabled={disabled}
                onClick={() => onToggle(cls)}
                title={disabled ? 'Already assigned to another suffix' : undefined}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                  width: '100%',
                  textAlign: 'left',
                  border: 'none',
                  borderRadius: 7,
                  padding: '7px 10px',
                  fontSize: 13,
                  fontFamily: 'var(--mono)',
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  background: active ? 'var(--accent-tint)' : 'transparent',
                  color: active ? 'var(--accent)' : 'var(--text)',
                  opacity: disabled ? 0.45 : 1,
                }}
              >
                {cls}
                {active && <Icon name="check" size={14} strokeWidth={2.6} />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// Collapsible settings panel. The header bar toggles; when collapsed only the
// header shows, so the page stays short once a section is configured.
function CollapsibleSection({
  head,
  open,
  onToggle,
  children,
}: {
  head: ReactNode
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <div className="panel pad">
      <div
        className="panel-head"
        onClick={onToggle}
        style={{ cursor: 'pointer', userSelect: 'none', marginBottom: open ? 16 : 0 }}
      >
        {head}
        <Icon
          name="chevDown"
          size={18}
          strokeWidth={2.2}
          style={{
            flexShrink: 0,
            opacity: 0.55,
            transform: open ? 'rotate(180deg)' : 'none',
            transition: 'transform 120ms ease',
          }}
        />
      </div>
      {open && children}
    </div>
  )
}

type SectionKey = 'lot' | 'tp' | 'oneToOne' | 'risky' | 'symbols' | 'excluded' | 'misc'

interface Props {
  config: Config | null
  status: StatusData | null
  connected: boolean
  onConfigSaved: (config: Config) => void
}

export function SettingsPage({ config, status, connected, onConfigSaved }: Props) {
  const [lotMode, setLotMode] = useState('risk_percent')
  const [riskPct, setRiskPct] = useState('1.0')
  const [fixedLotDefault, setFixedLotDefault] = useState('0.01')
  const [totalLotDefault, setTotalLotDefault] = useState('0.1')
  const [maxLot, setMaxLot] = useState('5.0')
  const [lotExceptions, setLotExceptions] = useState<LotExceptionRow[]>([])
  const [approxLoading, setApproxLoading] = useState(false)
  const [approxMsg, setApproxMsg] = useState<{ kind: 'success' | 'error'; text: string } | null>(
    null
  )
  const [licenseKey, setLicenseKey] = useState('')
  const [mt5TerminalPath, setMt5TerminalPath] = useState('')
  const [tpRows, setTpRows] = useState<TpRow[]>([])
  const [tpTab, setTpTab] = useState<'standard' | OverrideType>('standard')
  const [instrumentOverrides, setInstrumentOverrides] = useState<
    Record<AssetKey, InstrumentOverrideRow[]>
  >(
    () =>
      Object.fromEntries(ASSET_CLASSES.map(a => [a, [] as InstrumentOverrideRow[]])) as Record<
        AssetKey,
        InstrumentOverrideRow[]
      >
  )
  const [expandedAsset, setExpandedAsset] = useState<AssetKey | null>(null)
  const [oneToOneDefault, setOneToOneDefault] = useState('10')
  const [oneToOneRows, setOneToOneRows] = useState<OneToOneOverrideRow[]>([])
  const [riskyTp, setRiskyTp] = useState('4')
  const [riskyTrail, setRiskyTrail] = useState('2')
  const [riskyPartial, setRiskyPartial] = useState('50')
  const [riskySl, setRiskySl] = useState('') // '' = use the signal's DB stop-loss
  const [riskyWindows, setRiskyWindows] = useState<string[]>([])
  const [symbolRows, setSymbolRows] = useState<SymbolRow[]>([])
  const [brokerSymbols, setBrokerSymbols] = useState<string[]>([])
  const [notFoundSymbols, setNotFoundSymbols] = useState<string[]>([])
  const [stockSuffix, setStockSuffix] = useState('-24')
  const [suffixRules, setSuffixRules] = useState<SuffixRuleRow[]>([])
  const [excludedTrades, setExcludedTrades] = useState<ExcludedTradeRow[]>([])
  const [excludedChannelAssets, setExcludedChannelAssets] = useState<ExcludedChannelAssetRow[]>([])
  const [disabledSignalTypes, setDisabledSignalTypes] = useState<string[]>([])
  const [disabledChannels, setDisabledChannels] = useState<string[]>([])
  const [disableAutoTp, setDisableAutoTp] = useState(false)
  const [volatilityGuard, setVolatilityGuard] = useState(false)
  const [openSections, setOpenSections] = useState<Record<SectionKey, boolean>>(() => {
    const defaults: Record<SectionKey, boolean> = {
      lot: true,
      tp: true,
      oneToOne: true,
      risky: true,
      symbols: true,
      excluded: true,
      misc: true,
    }
    try {
      const stored = localStorage.getItem('settingsOpenSections')
      return stored ? { ...defaults, ...JSON.parse(stored) } : defaults
    } catch {
      return defaults
    }
  })
  const toggleSection = (key: SectionKey) =>
    setOpenSections(prev => {
      const next = { ...prev, [key]: !prev[key] }
      localStorage.setItem('settingsOpenSections', JSON.stringify(next))
      return next
    })
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stopMenuOpen, setStopMenuOpen] = useState(false)
  const stopMenuRef = useRef<HTMLDivElement | null>(null)
  const [pathMenuOpen, setPathMenuOpen] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)
  const [terminalPaths, setTerminalPaths] = useState<string[]>([])
  const pathMenuRef = useRef<HTMLDivElement | null>(null)
  const [validateMsg, setValidateMsg] = useState<{
    kind: 'info' | 'success' | 'error'
    text: string
  } | null>(null)

  const touch = () => setDirty(true)

  const initFromConfig = useCallback((cfg: Config) => {
    setLotMode(cfg.lot_sizing.mode)
    setMaxLot(String(cfg.lot_sizing.max_lot_per_order))
    setLicenseKey(cfg.license_key)
    setMt5TerminalPath(cfg.mt5_terminal_path ?? '')

    // Global Risk % default — accept flat number, or "default" key of a dict.
    const rp = cfg.lot_sizing.risk_percent
    if (typeof rp === 'number') {
      setRiskPct(String(rp))
    } else if (rp && typeof rp === 'object') {
      setRiskPct(String((rp as Record<string, number>).default ?? 1.0))
    }

    // Global Fixed lot default — accept flat number, or "default" key of a dict.
    const fl = cfg.lot_sizing.fixed_lot
    if (typeof fl === 'number') {
      setFixedLotDefault(String(fl))
    } else if (fl && typeof fl === 'object') {
      setFixedLotDefault(String((fl as Record<string, number>).default ?? 0.01))
    }

    // Global Total lot default — accept flat number, or "default" key of a dict.
    const tl = cfg.lot_sizing.total_lot
    if (typeof tl === 'number') {
      setTotalLotDefault(String(tl))
    } else if (tl && typeof tl === 'object') {
      setTotalLotDefault(String((tl as Record<string, number>).default ?? 0.1))
    }

    // Load exceptions. Prefer the new `exceptions` field; if absent, migrate
    // any legacy non-`default` keys from risk_percent / fixed_lot dicts.
    const exceptions: LotExceptionRow[] = []
    const seen = new Set<string>()
    if (Array.isArray(cfg.lot_sizing.exceptions)) {
      for (const ex of cfg.lot_sizing.exceptions) {
        exceptions.push({
          symbol: ex.symbol,
          channel: ex.channel ?? '',
          signalType: ex.signal_type || 'all',
          mode: ex.mode,
          value: String(ex.value),
        })
        seen.add(ex.symbol)
      }
    }
    if (rp && typeof rp === 'object') {
      for (const [sym, value] of Object.entries(rp as Record<string, number>)) {
        if (sym === 'default' || seen.has(sym)) continue
        exceptions.push({
          symbol: sym,
          channel: '',
          signalType: 'all',
          mode: 'risk_percent',
          value: String(value),
        })
        seen.add(sym)
      }
    }
    if (fl && typeof fl === 'object') {
      for (const [sym, value] of Object.entries(fl as Record<string, number>)) {
        if (sym === 'default' || seen.has(sym)) continue
        exceptions.push({
          symbol: sym,
          channel: '',
          signalType: 'all',
          mode: 'fixed',
          value: String(value),
        })
        seen.add(sym)
      }
    }
    setLotExceptions(exceptions)

    const tp = cfg.tp_config
    if (tp) {
      const globalPartialFallback = tp.partial_close_percent ?? 50
      const overrideSources: Record<OverrideType, Record<string, ScalpOverrideConfig> | undefined> =
        {
          scalp: tp.scalp_overrides,
          toll: tp.toll_overrides,
          swing: tp.swing_overrides,
          pa: tp.pa_overrides,
        }
      setTpRows(
        ASSET_CLASSES.map(asset => {
          const acfg = tp[asset as AssetKey] as AssetTPConfig | undefined
          const overrides = {} as Record<OverrideType, OverridePair>
          for (const t of OVERRIDE_TYPES) {
            const ov = overrideSources[t]?.[asset]
            overrides[t] = {
              thr: ov ? String(ov.profit_threshold) : '',
              trail: ov ? String(ov.trailing_distance) : '',
              partial:
                ov && ov.partial_close_percent != null ? String(ov.partial_close_percent) : '',
            }
          }
          return {
            asset,
            thr: String(acfg?.profit_threshold ?? ''),
            unit: acfg?.threshold_unit ?? '',
            trail: String(acfg?.trailing_distance ?? ''),
            partial: String(acfg?.partial_close_percent ?? globalPartialFallback),
            overrides,
          }
        })
      )
      const one = tp.one_to_one
      setOneToOneDefault(String(one?.profit_threshold ?? 10))
      setOneToOneRows(
        Object.entries(one?.overrides ?? {}).map(([asset, value]) => ({
          asset,
          value: String(value),
        }))
      )

      const risky = tp.risky
      setRiskyTp(String(risky?.profit_threshold ?? 4))
      setRiskyTrail(String(risky?.trailing_distance ?? 2))
      setRiskyPartial(String(risky?.partial_close_percent ?? 50))
      setRiskySl(risky?.stop_loss == null ? '' : String(risky.stop_loss))
      setRiskyWindows(risky?.disabled_windows ?? ['21:55-23:10', '00:55-02:00', '11:55-14:00'])

      // Group per-symbol instrument overrides by detected asset class.
      const grouped = Object.fromEntries(
        ASSET_CLASSES.map(a => [a, [] as InstrumentOverrideRow[]])
      ) as Record<AssetKey, InstrumentOverrideRow[]>
      for (const [sym, inst] of Object.entries(tp.instrument_overrides ?? {})) {
        const ac = detectAssetClass(sym) as AssetKey
        const i = inst as Record<string, unknown>
        const isFlat = FLAT_OVERRIDE_FIELDS.some(f => f in i)
        const std = (isFlat ? i : ((i.standard as Record<string, unknown>) ?? {})) as Record<
          string,
          unknown
        >
        const overrides = emptyOverridePairs()
        if (!isFlat) {
          for (const t of OVERRIDE_TYPES) {
            const ov = i[t] as Record<string, unknown> | undefined
            if (!ov) continue
            overrides[t] = {
              thr: ov.profit_threshold != null ? String(ov.profit_threshold) : '',
              trail: ov.trailing_distance != null ? String(ov.trailing_distance) : '',
              partial: ov.partial_close_percent != null ? String(ov.partial_close_percent) : '',
            }
          }
        }
        grouped[ac].push({
          symbol: sym,
          thr: std.profit_threshold != null ? String(std.profit_threshold) : '',
          trail: std.trailing_distance != null ? String(std.trailing_distance) : '',
          partial: std.partial_close_percent != null ? String(std.partial_close_percent) : '',
          overrides,
        })
      }
      setInstrumentOverrides(grouped)
    }

    const offsetInst = cfg.offset_instruments ?? []
    const mapped = new Set(Object.keys(cfg.symbol_map ?? {}))
    const rows: SymbolRow[] = Object.entries(cfg.symbol_map ?? {}).map(([db, mt5]) => ({
      db,
      mt5: String(mt5),
      feed: offsetInst.includes(db),
    }))
    // Offset instruments without a symbol_map entry (e.g. JP225, USOILSPOT) still
    // belong in the table so their feed type can be edited and they aren't dropped on
    // save — they map to themselves on the broker.
    for (const db of offsetInst) {
      if (!mapped.has(db)) rows.push({ db, mt5: db, feed: true })
    }
    setSymbolRows(rows)
    setStockSuffix(cfg.stock_suffix ?? '-24')
    const rawSuffixes = cfg.symbol_suffixes ?? []
    const legacyUniversal = (cfg as { universal_suffix?: string }).universal_suffix
    setSuffixRules(
      rawSuffixes.length === 0 && legacyUniversal
        ? [{ suffix: legacyUniversal, classes: [...ASSET_CLASSES] }]
        : rawSuffixes.map(r => ({
            suffix: r.suffix,
            classes: (r.asset_classes as AssetKey[]).filter(c => ASSET_CLASSES.includes(c)),
          }))
    )

    // Excluded trades — new structured list plus any legacy flat excluded_symbols.
    const trades: ExcludedTradeRow[] = (cfg.excluded_trades ?? []).map(t => ({
      symbol: t.symbol,
      signalType: t.signal_type || 'all',
    }))
    for (const sym of cfg.excluded_symbols ?? []) {
      if (!trades.some(t => t.symbol === sym && t.signalType === 'all')) {
        trades.push({ symbol: sym, signalType: 'all' })
      }
    }
    setExcludedTrades(trades)
    setExcludedChannelAssets(
      (cfg.excluded_channel_assets ?? []).map(r => ({
        channel: r.channel || '',
        assetClass: r.asset_class || '',
      }))
    )
    setDisabledSignalTypes(cfg.disabled_signal_types ?? [])
    setDisabledChannels(cfg.disabled_channels ?? [])
    setDisableAutoTp(cfg.disable_auto_tp ?? false)
    setVolatilityGuard(cfg.volatility_guard ?? false)
  }, [])

  useEffect(() => {
    if (config) initFromConfig(config)
  }, [config, initFromConfig])

  // Broker symbol catalogue for the mapping picker. broker_symbols only fills once
  // MT5 is connected and a sync cycle has run, so (re)fetch whenever the connection
  // comes up — fetching only on mount leaves the dropdown empty if Settings is opened
  // before MT5 connects. A transient disconnect keeps the last good list.
  useEffect(() => {
    if (!status?.mt5_connected) return
    fetchMt5Symbols()
      .then(setBrokerSymbols)
      .catch(() => {})
  }, [status?.mt5_connected])

  // Symbols that have a signal but no matching MT5 symbol on this broker. Polled so
  // the list drops entries as soon as a saved mapping resolves on the next cycle.
  useEffect(() => {
    if (!status?.mt5_connected) return
    const load = () =>
      fetchNotFoundSymbols()
        .then(setNotFoundSymbols)
        .catch(() => {})
    load()
    const id = setInterval(load, 15000)
    return () => clearInterval(id)
  }, [status?.mt5_connected])

  const brokerSymbolSet = useMemo(() => new Set(brokerSymbols), [brokerSymbols])
  // Flag a mapping whose target isn't in the broker's catalogue (only once it's loaded).
  const isUnknownSymbol = (sym: string) =>
    brokerSymbolSet.size > 0 && sym.trim().length > 0 && !brokerSymbolSet.has(sym.trim())

  function updateTpStandard(i: number, field: 'thr' | 'unit' | 'trail' | 'partial', value: string) {
    setTpRows(prev => prev.map((r, j) => (j === i ? { ...r, [field]: value } : r)))
    touch()
  }

  function updateTpOverride(
    i: number,
    type: OverrideType,
    field: 'thr' | 'trail' | 'partial',
    value: string
  ) {
    setTpRows(prev =>
      prev.map((r, j) => {
        if (j !== i) return r
        const pair = { ...r.overrides[type], [field]: value }
        return { ...r, overrides: { ...r.overrides, [type]: pair } }
      })
    )
    touch()
  }

  function updateOneToOneRow(i: number, field: 'asset' | 'value', value: string) {
    setOneToOneRows(prev => prev.map((r, j) => (j === i ? { ...r, [field]: value } : r)))
    touch()
  }

  function addOneToOneRow() {
    setOneToOneRows(prev => [...prev, { asset: '', value: '10' }])
    touch()
  }

  function updateRiskyWindow(i: number, value: string) {
    setRiskyWindows(prev => prev.map((w, j) => (j === i ? value : w)))
    touch()
  }

  function addRiskyWindow() {
    setRiskyWindows(prev => [...prev, ''])
    touch()
  }

  function removeRiskyWindow(i: number) {
    setRiskyWindows(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function removeOneToOneRow(i: number) {
    setOneToOneRows(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function updateSymbolRow(i: number, field: 'db' | 'mt5', value: string) {
    setSymbolRows(prev => prev.map((r, j) => (j === i ? { ...r, [field]: value } : r)))
    touch()
  }

  function updateSymbolFeed(i: number, feed: boolean) {
    setSymbolRows(prev => prev.map((r, j) => (j === i ? { ...r, feed } : r)))
    touch()
  }

  function addSymbolRow() {
    setSymbolRows(prev => [...prev, { db: '', mt5: '', feed: false }])
    touch()
  }

  function removeSymbolRow(i: number) {
    setSymbolRows(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function addSuffixRule() {
    setSuffixRules(prev => [...prev, { suffix: '', classes: [] }])
    touch()
  }

  function removeSuffixRule(i: number) {
    setSuffixRules(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function updateSuffixRuleSuffix(i: number, value: string) {
    setSuffixRules(prev => prev.map((r, j) => (j === i ? { ...r, suffix: value } : r)))
    touch()
  }

  // Toggle a class on a rule; a class assigned elsewhere is blocked in the UI, so
  // rules stay conflict-free (the backend rejects conflicts on save too).
  function toggleSuffixRuleClass(i: number, cls: AssetKey) {
    setSuffixRules(prev =>
      prev.map((r, j) => {
        if (j !== i) return r
        const has = r.classes.includes(cls)
        return { ...r, classes: has ? r.classes.filter(c => c !== cls) : [...r.classes, cls] }
      })
    )
    touch()
  }

  function buildSuffixRules(): SymbolSuffixRule[] {
    return suffixRules
      .filter(r => r.suffix.trim() && r.classes.length > 0)
      .map(r => ({ suffix: r.suffix.trim(), asset_classes: r.classes }))
  }

  function updateLotException(
    i: number,
    field: 'symbol' | 'channel' | 'signalType' | 'mode' | 'value',
    value: string
  ) {
    setLotExceptions(prev =>
      prev.map((r, j) => {
        if (j !== i) return r
        if (field === 'mode') return { ...r, mode: value as 'risk_percent' | 'fixed' | 'total_lot' }
        return { ...r, [field]: value }
      })
    )
    touch()
  }

  function addLotException() {
    setLotExceptions(prev => [
      ...prev,
      { symbol: '', channel: '', signalType: 'all', mode: 'risk_percent', value: '1.0' },
    ])
    touch()
  }

  function removeLotException(i: number) {
    setLotExceptions(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function buildLotExceptions(): LotExceptionConfig[] {
    return lotExceptions
      .filter(r => r.value.trim() !== '')
      .map(r => ({
        symbol: r.symbol.trim(),
        channel: r.channel,
        signal_type: r.signalType,
        mode: r.mode,
        value: parseFloat(r.value) || 0,
      }))
  }

  // Fetch per-instrument lots sized for ~5% average risk and upsert them into the
  // exceptions table (by symbol + signal type), leaving unrelated rows untouched. Uses
  // the active global mode so total-lot mode gets total-per-signal lots, not per-limit.
  async function handleCalculateApproxLots() {
    const mode = lotMode === 'total_lot' ? 'total_lot' : 'fixed'
    setApproxLoading(true)
    setApproxMsg(null)
    try {
      const data = await fetchApproximateLots(mode)
      if (data.exceptions.length === 0) {
        setApproxMsg({ kind: 'error', text: 'No supported instruments found on this broker.' })
        return
      }
      setLotExceptions(prev => {
        const next = [...prev]
        for (const ex of data.exceptions) {
          const value = String(ex.value)
          const channel = ex.channel ?? ''
          const i = next.findIndex(
            r =>
              r.symbol.trim() === ex.symbol &&
              r.channel === channel &&
              r.signalType === ex.signal_type
          )
          if (i >= 0) next[i] = { ...next[i], mode: ex.mode, value }
          else
            next.push({
              symbol: ex.symbol,
              channel,
              signalType: ex.signal_type,
              mode: ex.mode,
              value,
            })
        }
        return next
      })
      touch()
      const bal = data.balance.toLocaleString(undefined, { maximumFractionDigits: 0 })
      const label = mode === 'total_lot' ? 'total lots' : 'fixed lots'
      setApproxMsg({
        kind: 'success',
        text: `Set ${data.exceptions.length} ${label} for ~5% avg risk on ${data.currency ?? ''} ${bal} balance. Review and save.`,
      })
    } catch (e) {
      setApproxMsg({ kind: 'error', text: e instanceof Error ? e.message : 'Calculation failed' })
    } finally {
      setApproxLoading(false)
    }
  }

  function updateExcludedTrade(i: number, field: 'symbol' | 'signalType', value: string) {
    setExcludedTrades(prev => prev.map((r, j) => (j === i ? { ...r, [field]: value } : r)))
    touch()
  }

  function addExcludedTrade() {
    setExcludedTrades(prev => [...prev, { symbol: '', signalType: 'all' }])
    touch()
  }

  function removeExcludedTrade(i: number) {
    setExcludedTrades(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function buildExcludedTrades(): ExcludedTradeConfig[] {
    return excludedTrades
      .filter(r => r.symbol.trim())
      .map(r => ({ symbol: r.symbol.trim(), signal_type: r.signalType }))
  }

  function updateExcludedChannelAsset(i: number, field: 'channel' | 'assetClass', value: string) {
    setExcludedChannelAssets(prev => prev.map((r, j) => (j === i ? { ...r, [field]: value } : r)))
    touch()
  }

  function addExcludedChannelAsset() {
    setExcludedChannelAssets(prev => [...prev, { channel: '', assetClass: '' }])
    touch()
  }

  function removeExcludedChannelAsset(i: number) {
    setExcludedChannelAssets(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  // Drop rows with no constraint (both wildcards) — they'd exclude every trade.
  function buildExcludedChannelAssets(): ExcludedChannelAssetConfig[] {
    return excludedChannelAssets
      .filter(r => r.channel || r.assetClass)
      .map(r => ({ channel: r.channel, asset_class: r.assetClass }))
  }

  // Checkboxes store the *disabled* set (default empty = all enabled), so a toggle
  // adds/removes the item from that list.
  function toggleDisabled(list: string[], setList: (v: string[]) => void, key: string) {
    setList(list.includes(key) ? list.filter(k => k !== key) : [...list, key])
    touch()
  }

  function updateInstrumentOverride(
    asset: AssetKey,
    i: number,
    field: 'symbol' | 'thr' | 'trail' | 'partial',
    value: string
  ) {
    setInstrumentOverrides(prev => ({
      ...prev,
      [asset]: prev[asset].map((r, j) => (j === i ? { ...r, [field]: value } : r)),
    }))
    touch()
  }

  function addInstrumentOverride(asset: AssetKey) {
    setInstrumentOverrides(prev => ({
      ...prev,
      [asset]: [
        ...prev[asset],
        { symbol: '', thr: '', trail: '', partial: '', overrides: emptyOverridePairs() },
      ],
    }))
    touch()
  }

  function updateInstrumentOverrideTyped(
    asset: AssetKey,
    i: number,
    type: OverrideType,
    field: 'thr' | 'trail' | 'partial',
    value: string
  ) {
    setInstrumentOverrides(prev => ({
      ...prev,
      [asset]: prev[asset].map((r, j) => {
        if (j !== i) return r
        const pair = { ...r.overrides[type], [field]: value }
        return { ...r, overrides: { ...r.overrides, [type]: pair } }
      }),
    }))
    touch()
  }

  function removeInstrumentOverride(asset: AssetKey, i: number) {
    setInstrumentOverrides(prev => ({
      ...prev,
      [asset]: prev[asset].filter((_, j) => j !== i),
    }))
    touch()
  }

  function buildInstrumentOverrides(): Record<string, Record<string, unknown>> {
    const out: Record<string, Record<string, unknown>> = {}
    for (const asset of ASSET_CLASSES) {
      for (const row of instrumentOverrides[asset]) {
        const sym = row.symbol.trim()
        if (!sym) continue

        const std: Record<string, unknown> = {}
        if (row.thr !== '') std.profit_threshold = parseFloat(row.thr) || 0
        if (row.trail !== '') std.trailing_distance = parseFloat(row.trail) || 0
        if (row.partial !== '') std.partial_close_percent = parseInt(row.partial, 10) || 0

        const perType: Record<string, Record<string, unknown>> = {}
        for (const t of OVERRIDE_TYPES) {
          const ov = row.overrides[t]
          const block: Record<string, unknown> = {}
          if (ov.thr !== '') block.profit_threshold = parseFloat(ov.thr) || 0
          if (ov.trail !== '') block.trailing_distance = parseFloat(ov.trail) || 0
          if (ov.partial !== '') block.partial_close_percent = parseInt(ov.partial, 10) || 0
          if (Object.keys(block).length > 0) perType[t] = block
        }

        const hasStd = Object.keys(std).length > 0
        const hasOverrides = Object.keys(perType).length > 0
        if (!hasStd && !hasOverrides) continue

        if (hasOverrides) {
          const entry: Record<string, unknown> = { ...perType }
          if (hasStd) entry.standard = std
          out[sym] = entry
        } else {
          out[sym] = std
        }
      }
    }
    return out
  }

  function buildTpConfig(): TPConfig {
    const assetEntries = Object.fromEntries(
      tpRows.map(row => [
        row.asset,
        {
          profit_threshold: parseFloat(row.thr) || 0,
          threshold_unit: row.unit,
          trailing_distance: parseFloat(row.trail) || 0,
          partial_close_percent: parseInt(row.partial, 10) || 50,
        },
      ])
    )
    const overrideMaps = {} as Record<
      `${OverrideType}_overrides`,
      Record<string, ScalpOverrideConfig>
    >
    for (const t of OVERRIDE_TYPES) {
      overrideMaps[`${t}_overrides`] = Object.fromEntries(
        tpRows
          .filter(
            row =>
              row.overrides[t].thr !== '' ||
              row.overrides[t].trail !== '' ||
              row.overrides[t].partial !== ''
          )
          .map(row => {
            const entry: ScalpOverrideConfig = {
              profit_threshold: parseFloat(row.overrides[t].thr) || 0,
              trailing_distance: parseFloat(row.overrides[t].trail) || 0,
            }
            if (row.overrides[t].partial !== '') {
              entry.partial_close_percent = parseInt(row.overrides[t].partial, 10) || 50
            }
            return [row.asset, entry]
          })
      )
    }
    const oneToOne = {
      profit_threshold: parseFloat(oneToOneDefault) || 10,
      overrides: Object.fromEntries(
        oneToOneRows
          .filter(r => r.asset.trim())
          .map(r => [r.asset.trim(), parseFloat(r.value) || 0])
      ),
    }
    const slParsed = parseFloat(riskySl)
    const risky = {
      profit_threshold: parseFloat(riskyTp) || 4,
      threshold_unit: 'dollars',
      trailing_distance: parseFloat(riskyTrail) || 0,
      partial_close_percent: parseInt(riskyPartial, 10) || 50,
      stop_loss: riskySl.trim() === '' || isNaN(slParsed) ? null : slParsed,
      disabled_windows: riskyWindows.map(w => w.trim()).filter(Boolean),
      overrides: config!.tp_config.risky?.overrides ?? {},
    }
    return {
      ...config!.tp_config,
      ...assetEntries,
      ...overrideMaps,
      one_to_one: oneToOne,
      risky,
      instrument_overrides: buildInstrumentOverrides(),
    } as TPConfig
  }

  function buildSymbolMap(): Record<string, string> {
    // Skip identity rows (mt5 === db): they're no-op mappings, used only to surface an
    // offset-only instrument in the table. Their feed type is persisted via
    // offset_instruments, not symbol_map.
    return Object.fromEntries(
      symbolRows
        .filter(r => r.db.trim() && r.mt5.trim() && r.db.trim() !== r.mt5.trim())
        .map(r => [r.db.trim(), r.mt5.trim()])
    )
  }

  function buildOffsetInstruments(): string[] {
    // Locked built-in defaults are always offset feeds regardless of the (disabled) toggle.
    return symbolRows
      .filter(r => r.db.trim() && (r.feed || LOCKED_OFFSET_INSTRUMENTS.has(r.db.trim())))
      .map(r => r.db.trim())
  }

  async function handleSave() {
    if (!config) return
    setSaving(true)
    setError(null)
    try {
      const updated: Config = {
        ...config,
        license_key: licenseKey,
        mt5_terminal_path: mt5TerminalPath,
        lot_sizing: {
          mode: lotMode,
          risk_percent: parseFloat(riskPct) || 1.0,
          fixed_lot: parseFloat(fixedLotDefault) || 0.01,
          total_lot: parseFloat(totalLotDefault) || 0.1,
          max_lot_per_order: parseFloat(maxLot) || 5.0,
          exceptions: buildLotExceptions(),
        },
        tp_config: buildTpConfig(),
        symbol_map: buildSymbolMap(),
        offset_instruments: buildOffsetInstruments(),
        stock_suffix: stockSuffix,
        symbol_suffixes: buildSuffixRules(),
        excluded_trades: buildExcludedTrades(),
        excluded_channel_assets: buildExcludedChannelAssets(),
        excluded_symbols: [], // migrated into excluded_trades
        disabled_signal_types: disabledSignalTypes,
        disabled_channels: disabledChannels,
        disable_auto_tp: disableAutoTp,
        volatility_guard: volatilityGuard,
      }
      await updateConfig(updated)
      onConfigSaved(updated)
      setSaving(false)
      setDirty(false)
      setToast(true)
      setTimeout(() => setToast(false), 2600)
    } catch (e) {
      setSaving(false)
      setError(e instanceof Error ? e.message : 'Save failed')
    }
  }

  function handleDiscard() {
    if (config) {
      initFromConfig(config)
      setDirty(false)
    }
  }

  async function handleValidate() {
    if (!config) return
    setValidateMsg({ kind: 'info', text: 'Saving — waiting for license check…' })
    try {
      const updated: Config = {
        ...config,
        license_key: licenseKey,
        mt5_terminal_path: mt5TerminalPath,
      }
      await updateConfig(updated)
      onConfigSaved(updated)
    } catch (e) {
      setValidateMsg({
        kind: 'error',
        text: 'Save failed: ' + (e instanceof Error ? e.message : 'unknown'),
      })
    }
  }

  async function handleStart() {
    setBusy(true)
    setError(null)
    try {
      await startEngine()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  async function handlePauseTrading() {
    setBusy(true)
    setError(null)
    setStopMenuOpen(false)
    try {
      await stopEngine()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleShutdown() {
    setStopMenuOpen(false)
    try {
      await shutdownEngine()
    } catch {
      /* connection will drop */
    }
  }

  useEffect(() => {
    if (!stopMenuOpen) return
    function onClick(e: MouseEvent) {
      if (stopMenuRef.current && !stopMenuRef.current.contains(e.target as Node)) {
        setStopMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [stopMenuOpen])

  useEffect(() => {
    if (!pathMenuOpen) return
    function onClick(e: MouseEvent) {
      if (pathMenuRef.current && !pathMenuRef.current.contains(e.target as Node)) {
        setPathMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [pathMenuOpen])

  async function handleScanTerminals() {
    setPathMenuOpen(true)
    setScanning(true)
    setScanError(null)
    try {
      const paths = await scanMt5Terminals()
      setTerminalPaths(paths)
    } catch (e) {
      setScanError(e instanceof Error ? e.message : 'Scan failed')
      setTerminalPaths([])
    } finally {
      setScanning(false)
    }
  }

  function pickTerminalPath(p: string) {
    setMt5TerminalPath(p)
    setPathMenuOpen(false)
    touch()
  }

  const isActive = status?.trading_active ?? false
  const mt5Ok = status?.mt5_connected ?? false
  const conns = deriveConnStatuses(status, connected)

  // Once a Save & validate is pending, watch the status feed for the engine's
  // verdict on both the MT5 terminal and the license. The engine reconnects MT5
  // and re-validates asynchronously after its next sync cycle; surface whichever
  // is failing instead of leaving the toast stuck on "waiting".
  useEffect(() => {
    if (!validateMsg || validateMsg.kind !== 'info') return
    // MT5 first — the license can't validate without the terminal (it needs the account).
    if (conns.mt5.state === 'error') {
      setValidateMsg({ kind: 'error', text: `MT5 terminal not connected: ${conns.mt5.detail}` })
      return
    }
    if (conns.mt5.state === 'live' && conns.license.state === 'live') {
      setValidateMsg({ kind: 'success', text: 'MT5 connected and license valid — engine running.' })
      return
    }
    // A confirmed license rejection (wrong key/account/expired) — report right away.
    if (conns.license.state === 'error') {
      setValidateMsg({
        kind: 'error',
        text: status?.license_message || 'License rejected — check the key and MT5 account.',
      })
      return
    }
    const t = setTimeout(() => {
      setValidateMsg({
        kind: 'error',
        text:
          status?.license_message ||
          'Could not validate. Check the license key and MT5 terminal path, then retry.',
      })
    }, 30000)
    return () => clearTimeout(t)
  }, [conns.mt5.state, conns.mt5.detail, conns.license.state, validateMsg, status?.license_message])

  useEffect(() => {
    if (!validateMsg || validateMsg.kind === 'info') return
    const t = setTimeout(() => setValidateMsg(null), 5000)
    return () => clearTimeout(t)
  }, [validateMsg])

  return (
    <div className="page">
      <datalist id="broker-symbols">
        {brokerSymbols.map(s => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <div>
        <div className="eyebrow">Configuration</div>
        <h2 style={{ margin: '4px 0 0', fontSize: 24, fontWeight: 700, letterSpacing: '-0.01em' }}>
          Settings
        </h2>
      </div>

      {/* ENGINE & CONNECTION */}
      <div className="panel pad">
        <div className="panel-head">
          <h3>Engine &amp; connection</h3>
        </div>
        <div style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className={`conn ${CONN_CLASS[conns.mt5.state]}`} title={conns.mt5.detail ?? ''}>
            <span className="d" /> MT5 {connWord(conns.mt5.state, 'connected', 'error')}
            {conns.mt5.state === 'error' && conns.mt5.detail && (
              <span className="faint" style={{ marginLeft: 6, fontSize: 11 }}>
                · {conns.mt5.detail}
              </span>
            )}
          </div>
          <div
            className={`conn ${CONN_CLASS[conns.database.state]}`}
            title={conns.database.detail ?? ''}
          >
            <span className="d" /> Database {connWord(conns.database.state, 'connected', 'error')}
            {conns.database.state === 'error' && conns.database.detail && (
              <span className="faint" style={{ marginLeft: 6, fontSize: 11 }}>
                · {conns.database.detail}
              </span>
            )}
          </div>
          <div
            className={`conn ${CONN_CLASS[conns.license.state]}`}
            title={conns.license.detail ?? ''}
          >
            <span className="d" /> License {connWord(conns.license.state, 'valid', 'invalid')}
            {conns.license.state === 'error' && conns.license.detail && (
              <span className="faint" style={{ marginLeft: 6, fontSize: 11 }}>
                · {conns.license.detail}
              </span>
            )}
          </div>
          <div style={{ flex: 1 }} />
          {isActive ? (
            <div ref={stopMenuRef} style={{ position: 'relative' }}>
              <button className="btn" onClick={() => setStopMenuOpen(o => !o)} disabled={busy}>
                <Icon name="power" size={14} strokeWidth={2.2} /> Stop engine ▾
              </button>
              {stopMenuOpen && (
                <div
                  style={{
                    position: 'absolute',
                    top: 'calc(100% + 4px)',
                    right: 0,
                    minWidth: 200,
                    background: 'var(--bg-panel, #fff)',
                    border: '1px solid var(--hairline, rgba(0,0,0,0.12))',
                    borderRadius: 8,
                    boxShadow: '0 6px 18px rgba(0,0,0,0.12)',
                    padding: 4,
                    zIndex: 20,
                  }}
                >
                  <button
                    className="btn"
                    style={{
                      width: '100%',
                      justifyContent: 'flex-start',
                      background: 'transparent',
                      border: 'none',
                    }}
                    onClick={handlePauseTrading}
                    title="Freeze new placements but keep TP/trailing running for open positions"
                  >
                    Pause trading
                  </button>
                  <button
                    className="btn danger"
                    style={{
                      width: '100%',
                      justifyContent: 'flex-start',
                      background: 'transparent',
                      border: 'none',
                    }}
                    onClick={handleShutdown}
                    title="Stop all loops and exit the bot process"
                  >
                    Full shutdown
                  </button>
                </div>
              )}
            </div>
          ) : (
            <>
              <button className="btn" onClick={handleStart} disabled={busy}>
                <Icon name="power" size={14} strokeWidth={2.2} /> Start engine
              </button>
              <button className="btn danger" onClick={handleShutdown}>
                <Icon name="power" size={14} strokeWidth={2.2} /> Full shutdown
              </button>
            </>
          )}
        </div>
        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />
        <div style={{ display: 'flex', gap: 14, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="field">
            <label>License key</label>
            <input
              className="inp mono"
              value={licenseKey}
              onChange={e => {
                setLicenseKey(e.target.value)
                touch()
              }}
              style={{ width: 280 }}
            />
          </div>
          <div className="field">
            <label>MT5 terminal path (optional)</label>
            <div
              ref={pathMenuRef}
              style={{ display: 'flex', gap: 6, alignItems: 'center', position: 'relative' }}
            >
              <input
                className="inp mono"
                value={mt5TerminalPath}
                onChange={e => {
                  setMt5TerminalPath(e.target.value)
                  touch()
                }}
                placeholder="e.g. C:\Program Files\MetaTrader 5\terminal64.exe"
                style={{ width: 420 }}
              />
              <button
                type="button"
                className="btn sm ghost"
                onClick={handleScanTerminals}
                disabled={scanning}
                title="Search this PC for installed MT5 terminals"
                style={{ padding: '6px 10px' }}
              >
                <Icon name="folder" size={15} strokeWidth={2} />
              </button>
              {pathMenuOpen && (
                <div
                  style={{
                    position: 'absolute',
                    top: 'calc(100% + 4px)',
                    left: 0,
                    minWidth: 420,
                    maxWidth: 560,
                    background: 'var(--surface)',
                    border: '1px solid var(--hairline-strong)',
                    borderRadius: 10,
                    boxShadow: 'var(--shadow)',
                    padding: 4,
                    zIndex: 30,
                    maxHeight: 240,
                    overflowY: 'auto',
                  }}
                >
                  {scanning ? (
                    <div className="faint" style={{ padding: '8px 12px', fontSize: 12.5 }}>
                      Searching…
                    </div>
                  ) : scanError ? (
                    <div
                      style={{
                        padding: '8px 12px',
                        fontSize: 12.5,
                        color: 'var(--neg)',
                      }}
                    >
                      {scanError}
                    </div>
                  ) : terminalPaths.length === 0 ? (
                    <div className="faint" style={{ padding: '8px 12px', fontSize: 12.5 }}>
                      No MT5 terminals found
                    </div>
                  ) : (
                    terminalPaths.map(p => (
                      <button
                        key={p}
                        type="button"
                        className="btn sm ghost mono"
                        onClick={() => pickTerminalPath(p)}
                        style={{
                          width: '100%',
                          justifyContent: 'flex-start',
                          border: 'none',
                          textAlign: 'left',
                          fontSize: 12.5,
                          padding: '6px 10px',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: 'block',
                        }}
                        title={p}
                      >
                        {p}
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
          <button className="btn" onClick={handleValidate}>
            Save &amp; validate
          </button>
          {validateMsg && (
            <div
              style={{
                fontSize: 13,
                padding: '6px 12px',
                borderRadius: 6,
                color:
                  validateMsg.kind === 'success'
                    ? '#1f7a1f'
                    : validateMsg.kind === 'error'
                      ? '#a32020'
                      : 'var(--ink-muted, #666)',
                background:
                  validateMsg.kind === 'success'
                    ? 'rgba(31,122,31,0.08)'
                    : validateMsg.kind === 'error'
                      ? 'rgba(163,32,32,0.08)'
                      : 'rgba(0,0,0,0.04)',
                border:
                  '1px solid ' +
                  (validateMsg.kind === 'success'
                    ? 'rgba(31,122,31,0.25)'
                    : validateMsg.kind === 'error'
                      ? 'rgba(163,32,32,0.25)'
                      : 'rgba(0,0,0,0.08)'),
                alignSelf: 'center',
              }}
            >
              {validateMsg.text}
            </div>
          )}
        </div>
      </div>

      {/* LOT SIZING */}
      <CollapsibleSection
        head={<h3>Lot sizing</h3>}
        open={openSections.lot}
        onToggle={() => toggleSection('lot')}
      >
        <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="field">
            <label>Default mode</label>
            <Seg
              accent
              value={lotMode}
              options={[
                { value: 'risk_percent', label: 'Risk %' },
                {
                  value: 'fixed',
                  label: (
                    <>
                      Fixed lot
                      <span
                        style={{ color: 'var(--pos)', marginLeft: 4 }}
                        title="This lot-sizing method is recommended as it ensures more consistent results. Please find an appropriate fixed lot for all symbol types, and add overrides where necessary."
                      >
                        ★
                      </span>
                    </>
                  ),
                },
                {
                  value: 'total_lot',
                  label: (
                    <>
                      Total lot
                      <span
                        style={{ color: 'var(--warn)', marginLeft: 4 }}
                        title="Experimental: The value selected gets distributed among limits. Example: Value = 1, # of Limits = 2, Each limit = 0.5. More limits = lower risk."
                      >
                        ★
                      </span>
                    </>
                  ),
                },
              ]}
              onChange={v => {
                setLotMode(v)
                touch()
              }}
            />
          </div>
          {lotMode === 'risk_percent' && (
            <div className="field">
              <label>Risk per signal (%)</label>
              <input
                className="inp num mono"
                value={riskPct}
                onChange={e => {
                  setRiskPct(e.target.value)
                  touch()
                }}
                style={{ width: 100 }}
              />
            </div>
          )}
          {lotMode === 'fixed' && (
            <div className="field">
              <label>Fixed lot</label>
              <input
                className="inp num mono"
                value={fixedLotDefault}
                onChange={e => {
                  setFixedLotDefault(e.target.value)
                  touch()
                }}
                style={{ width: 100 }}
              />
            </div>
          )}
          {lotMode === 'total_lot' && (
            <div className="field">
              <label>Total lot</label>
              <input
                className="inp num mono"
                value={totalLotDefault}
                onChange={e => {
                  setTotalLotDefault(e.target.value)
                  touch()
                }}
                style={{ width: 100 }}
              />
            </div>
          )}
          <div className="field">
            <label>Max lot / order</label>
            <input
              className="inp num mono"
              value={maxLot}
              onChange={e => {
                setMaxLot(e.target.value)
                touch()
              }}
              style={{ width: 100 }}
            />
          </div>
          {(lotMode === 'fixed' || lotMode === 'total_lot') && (
            <div
              className="field"
              style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}
            >
              <label>&nbsp;</label>
              <button
                type="button"
                className="btn"
                onClick={handleCalculateApproxLots}
                disabled={approxLoading || !mt5Ok}
                title={
                  mt5Ok
                    ? `Suggest ${lotMode === 'total_lot' ? 'total' : 'fixed'} lots per instrument that put a typical signal near 5% account risk, and add them as exceptions below`
                    : 'Connect MT5 first — sizing needs your account balance'
                }
              >
                {approxLoading ? 'Calculating…' : 'Calculate approximate sizes'}
              </button>
            </div>
          )}
        </div>
        {(lotMode === 'fixed' || lotMode === 'total_lot') && approxMsg && (
          <div
            style={{
              marginTop: 10,
              fontSize: 12.5,
              color: approxMsg.kind === 'success' ? 'var(--pos)' : 'var(--neg)',
            }}
          >
            {approxMsg.text}
          </div>
        )}

        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

        <div className="panel-head" style={{ marginBottom: 6 }}>
          <h3 style={{ fontSize: 14 }}>Exceptions</h3>
          <span className="sub">
            most specific match wins — channel beats symbol beats signal type
          </span>
        </div>
        {lotExceptions.length > 0 && (
          <table className="tbl" style={{ maxWidth: 860 }}>
            <thead>
              <tr>
                <th>Channel</th>
                <th>Symbol</th>
                <th>Signal type</th>
                <th>Mode</th>
                <th className="num">Value</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lotExceptions.map((r, i) => (
                <tr key={i}>
                  <td>
                    <select
                      className="inp"
                      value={r.channel}
                      onChange={e => updateLotException(i, 'channel', e.target.value)}
                      style={{ width: 140 }}
                    >
                      <option value="">All channels</option>
                      {CHANNELS.map(c => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      className="inp mono"
                      list="broker-symbols"
                      value={r.symbol}
                      onChange={e => updateLotException(i, 'symbol', e.target.value)}
                      placeholder="All symbols"
                      style={{ width: 160 }}
                    />
                  </td>
                  <td>
                    <select
                      className="inp"
                      value={r.signalType}
                      onChange={e => updateLotException(i, 'signalType', e.target.value)}
                      style={{ width: 130 }}
                    >
                      {LOT_SIGNAL_TYPES.map(t => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <Seg
                      value={r.mode}
                      options={[
                        { value: 'risk_percent', label: 'Risk %' },
                        { value: 'fixed', label: 'Fixed' },
                        { value: 'total_lot', label: 'Total' },
                      ]}
                      onChange={v => updateLotException(i, 'mode', v)}
                    />
                  </td>
                  <td className="num">
                    <input
                      className="inp num mono"
                      value={r.value}
                      onChange={e => updateLotException(i, 'value', e.target.value)}
                      style={{ width: 88 }}
                    />
                  </td>
                  <td style={{ width: 40 }}>
                    <button className="btn sm ghost" onClick={() => removeLotException(i)}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={addLotException}>
          + Add exception
        </button>
      </CollapsibleSection>

      {/* TAKE PROFIT & TRAILING */}
      {tpRows.length > 0 && (
        <CollapsibleSection
          head={
            <div
              style={{
                display: 'flex',
                flex: 1,
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
              }}
            >
              <h3>Take-profit &amp; trailing</h3>
              <span className="sub">
                Use the instrument name as shown in the Discord alert channel
              </span>
            </div>
          }
          open={openSections.tp}
          onToggle={() => toggleSection('tp')}
        >
          <div style={{ marginBottom: 16 }}>
            <Seg
              accent
              value={tpTab}
              options={[
                { value: 'standard', label: 'Standard' },
                { value: 'scalp', label: 'Scalp' },
                { value: 'toll', label: 'Toll' },
                { value: 'swing', label: 'Swing' },
                { value: 'pa', label: 'PA' },
              ]}
              onChange={v => setTpTab(v as 'standard' | OverrideType)}
            />
          </div>
          {tpTab === 'standard' ? (
            <>
              <p className="faint" style={{ marginTop: 0, marginBottom: 12, fontSize: 12.5 }}>
                Trailing 25% = trail 25% of position, close 75% at TP trigger.
              </p>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Asset class</th>
                    <th className="num">Threshold</th>
                    <th>Unit</th>
                    <th className="num">Trail dist.</th>
                    <th>Trailing %</th>
                  </tr>
                </thead>
                <tbody>
                  {tpRows.map((t, i) => {
                    const partial = parseInt(t.partial, 10) || 50
                    const trailing = partialToTrailing(partial)
                    const overrides = instrumentOverrides[t.asset as AssetKey]
                    const isExpanded = expandedAsset === t.asset
                    return (
                      <Fragment key={t.asset}>
                        <tr>
                          <td
                            onClick={() =>
                              setExpandedAsset(isExpanded ? null : (t.asset as AssetKey))
                            }
                            style={{ cursor: 'pointer', userSelect: 'none' }}
                            title={isExpanded ? 'Click to collapse' : 'Click to expand'}
                          >
                            <span className="sym">{t.asset}</span>
                            <Icon
                              name="chevDown"
                              size={14}
                              strokeWidth={2}
                              style={{
                                marginLeft: 6,
                                verticalAlign: 'middle',
                                opacity: 0.55,
                                transform: isExpanded ? 'rotate(180deg)' : 'none',
                                transition: 'transform 120ms ease',
                              }}
                            />
                          </td>
                          <td className="num">
                            <input
                              className="inp num mono"
                              value={t.thr}
                              style={{ width: 76 }}
                              onChange={e => updateTpStandard(i, 'thr', e.target.value)}
                            />
                          </td>
                          <td className="dim">{t.unit}</td>
                          <td className="num">
                            <input
                              className="inp num mono"
                              value={t.trail}
                              style={{ width: 76 }}
                              onChange={e => updateTpStandard(i, 'trail', e.target.value)}
                            />
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <input
                                type="range"
                                min={0}
                                max={100}
                                step={5}
                                value={trailing}
                                onChange={e =>
                                  updateTpStandard(
                                    i,
                                    'partial',
                                    String(trailingToPartial(parseInt(e.target.value, 10)))
                                  )
                                }
                                style={{ width: 140, accentColor: 'var(--accent)' }}
                              />
                              <span className="mono" style={{ width: 40, fontWeight: 600 }}>
                                {trailing}%
                              </span>
                            </div>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr>
                            <td
                              colSpan={5}
                              style={{
                                background: 'var(--panel-soft, transparent)',
                                padding: '10px 14px',
                              }}
                            >
                              <div className="faint" style={{ fontSize: 12, marginBottom: 8 }}>
                                Per-symbol <b>standard</b> overrides for <b>{t.asset}</b> · blank =
                                inherit asset-class value · switch tabs to edit scalp/toll/swing/pa
                              </div>
                              {overrides.length > 0 && (
                                <table className="tbl" style={{ marginBottom: 8 }}>
                                  <thead>
                                    <tr>
                                      <th>Symbol</th>
                                      <th className="num">Threshold</th>
                                      <th className="num">Trail dist.</th>
                                      <th>Trailing %</th>
                                      <th />
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {overrides.map((r, j) => {
                                      const ovPartialSet = r.partial !== ''
                                      const ovPartial = parseInt(r.partial, 10) || 50
                                      const ovTrailing = partialToTrailing(ovPartial)
                                      return (
                                        <tr key={j}>
                                          <td>
                                            <input
                                              className="inp mono"
                                              value={r.symbol}
                                              onChange={e =>
                                                updateInstrumentOverride(
                                                  t.asset as AssetKey,
                                                  j,
                                                  'symbol',
                                                  e.target.value
                                                )
                                              }
                                              placeholder="SPX500USD, AMD.NAS, …"
                                              style={{ width: 160 }}
                                            />
                                          </td>
                                          <td className="num">
                                            <input
                                              className="inp num mono"
                                              value={r.thr}
                                              style={{ width: 76 }}
                                              onChange={e =>
                                                updateInstrumentOverride(
                                                  t.asset as AssetKey,
                                                  j,
                                                  'thr',
                                                  e.target.value
                                                )
                                              }
                                            />
                                          </td>
                                          <td className="num">
                                            <input
                                              className="inp num mono"
                                              value={r.trail}
                                              style={{ width: 76 }}
                                              onChange={e =>
                                                updateInstrumentOverride(
                                                  t.asset as AssetKey,
                                                  j,
                                                  'trail',
                                                  e.target.value
                                                )
                                              }
                                            />
                                          </td>
                                          <td>
                                            <div
                                              style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: 10,
                                              }}
                                            >
                                              <input
                                                type="range"
                                                min={0}
                                                max={100}
                                                step={5}
                                                value={ovTrailing}
                                                onChange={e =>
                                                  updateInstrumentOverride(
                                                    t.asset as AssetKey,
                                                    j,
                                                    'partial',
                                                    String(
                                                      trailingToPartial(
                                                        parseInt(e.target.value, 10)
                                                      )
                                                    )
                                                  )
                                                }
                                                style={{ width: 140, accentColor: 'var(--accent)' }}
                                              />
                                              <span
                                                className="mono"
                                                style={{ width: 56, fontWeight: 600 }}
                                              >
                                                {ovPartialSet ? (
                                                  `${ovTrailing}%`
                                                ) : (
                                                  <span className="faint">inherit</span>
                                                )}
                                              </span>
                                              {ovPartialSet && (
                                                <button
                                                  className="btn sm ghost"
                                                  onClick={() =>
                                                    updateInstrumentOverride(
                                                      t.asset as AssetKey,
                                                      j,
                                                      'partial',
                                                      ''
                                                    )
                                                  }
                                                >
                                                  ×
                                                </button>
                                              )}
                                            </div>
                                          </td>
                                          <td style={{ width: 40 }}>
                                            <button
                                              className="btn sm ghost"
                                              onClick={() =>
                                                removeInstrumentOverride(t.asset as AssetKey, j)
                                              }
                                            >
                                              ×
                                            </button>
                                          </td>
                                        </tr>
                                      )
                                    })}
                                  </tbody>
                                </table>
                              )}
                              <button
                                className="btn sm ghost"
                                onClick={() => addInstrumentOverride(t.asset as AssetKey)}
                              >
                                + Add symbol
                              </button>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </>
          ) : (
            <>
              <p className="faint" style={{ marginTop: 0, marginBottom: 12, fontSize: 12.5 }}>
                {tpTab === 'swing'
                  ? 'Leave blank to fall back to 3× the standard threshold. Trailing % left blank inherits from Standard.'
                  : 'Leave blank to fall back to the standard asset-class settings.'}
              </p>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Asset class</th>
                    <th className="num">Threshold</th>
                    <th>Unit</th>
                    <th className="num">Trail dist.</th>
                    <th>Trailing %</th>
                  </tr>
                </thead>
                <tbody>
                  {tpRows.map((t, i) => {
                    const partialSet = t.overrides[tpTab].partial !== ''
                    const partialNum = parseInt(t.overrides[tpTab].partial, 10) || 50
                    const trailingNum = partialToTrailing(partialNum)
                    const overrides = instrumentOverrides[t.asset as AssetKey]
                    const isExpanded = expandedAsset === t.asset
                    return (
                      <Fragment key={t.asset}>
                        <tr>
                          <td
                            onClick={() =>
                              setExpandedAsset(isExpanded ? null : (t.asset as AssetKey))
                            }
                            style={{ cursor: 'pointer', userSelect: 'none' }}
                            title={isExpanded ? 'Click to collapse' : 'Click to expand'}
                          >
                            <span className="sym">{t.asset}</span>
                            <Icon
                              name="chevDown"
                              size={14}
                              strokeWidth={2}
                              style={{
                                marginLeft: 6,
                                verticalAlign: 'middle',
                                opacity: 0.55,
                                transform: isExpanded ? 'rotate(180deg)' : 'none',
                                transition: 'transform 120ms ease',
                              }}
                            />
                          </td>
                          <td className="num">
                            <input
                              className="inp num mono"
                              value={t.overrides[tpTab].thr}
                              style={{ width: 76 }}
                              onChange={e => updateTpOverride(i, tpTab, 'thr', e.target.value)}
                            />
                          </td>
                          <td className="dim">{t.unit}</td>
                          <td className="num">
                            <input
                              className="inp num mono"
                              value={t.overrides[tpTab].trail}
                              style={{ width: 76 }}
                              onChange={e => updateTpOverride(i, tpTab, 'trail', e.target.value)}
                            />
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <input
                                type="range"
                                min={0}
                                max={100}
                                step={5}
                                value={trailingNum}
                                onChange={e =>
                                  updateTpOverride(
                                    i,
                                    tpTab,
                                    'partial',
                                    String(trailingToPartial(parseInt(e.target.value, 10)))
                                  )
                                }
                                style={{ width: 140, accentColor: 'var(--accent)' }}
                              />
                              <span className="mono" style={{ width: 56, fontWeight: 600 }}>
                                {partialSet ? (
                                  `${trailingNum}%`
                                ) : (
                                  <span className="faint">inherit</span>
                                )}
                              </span>
                              {partialSet && (
                                <button
                                  className="btn sm ghost"
                                  onClick={() => updateTpOverride(i, tpTab, 'partial', '')}
                                >
                                  ×
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr>
                            <td
                              colSpan={5}
                              style={{
                                background: 'var(--panel-soft, transparent)',
                                padding: '10px 14px',
                              }}
                            >
                              <div className="faint" style={{ fontSize: 12, marginBottom: 8 }}>
                                Per-symbol <b>{tpTab}</b> overrides for <b>{t.asset}</b> · blank =
                                inherit asset-class {tpTab} value
                              </div>
                              {overrides.length > 0 && (
                                <table className="tbl" style={{ marginBottom: 8 }}>
                                  <thead>
                                    <tr>
                                      <th>Symbol</th>
                                      <th className="num">Threshold</th>
                                      <th className="num">Trail dist.</th>
                                      <th>Trailing %</th>
                                      <th />
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {overrides.map((r, j) => {
                                      const ovPair = r.overrides[tpTab]
                                      const ovPartialSet = ovPair.partial !== ''
                                      const ovPartial = parseInt(ovPair.partial, 10) || 50
                                      const ovTrailing = partialToTrailing(ovPartial)
                                      return (
                                        <tr key={j}>
                                          <td>
                                            <input
                                              className="inp mono"
                                              value={r.symbol}
                                              onChange={e =>
                                                updateInstrumentOverride(
                                                  t.asset as AssetKey,
                                                  j,
                                                  'symbol',
                                                  e.target.value
                                                )
                                              }
                                              placeholder="SPX500USD, AMD.NAS, …"
                                              style={{ width: 160 }}
                                            />
                                          </td>
                                          <td className="num">
                                            <input
                                              className="inp num mono"
                                              value={ovPair.thr}
                                              style={{ width: 76 }}
                                              onChange={e =>
                                                updateInstrumentOverrideTyped(
                                                  t.asset as AssetKey,
                                                  j,
                                                  tpTab,
                                                  'thr',
                                                  e.target.value
                                                )
                                              }
                                            />
                                          </td>
                                          <td className="num">
                                            <input
                                              className="inp num mono"
                                              value={ovPair.trail}
                                              style={{ width: 76 }}
                                              onChange={e =>
                                                updateInstrumentOverrideTyped(
                                                  t.asset as AssetKey,
                                                  j,
                                                  tpTab,
                                                  'trail',
                                                  e.target.value
                                                )
                                              }
                                            />
                                          </td>
                                          <td>
                                            <div
                                              style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: 10,
                                              }}
                                            >
                                              <input
                                                type="range"
                                                min={0}
                                                max={100}
                                                step={5}
                                                value={ovTrailing}
                                                onChange={e =>
                                                  updateInstrumentOverrideTyped(
                                                    t.asset as AssetKey,
                                                    j,
                                                    tpTab,
                                                    'partial',
                                                    String(
                                                      trailingToPartial(
                                                        parseInt(e.target.value, 10)
                                                      )
                                                    )
                                                  )
                                                }
                                                style={{ width: 140, accentColor: 'var(--accent)' }}
                                              />
                                              <span
                                                className="mono"
                                                style={{ width: 56, fontWeight: 600 }}
                                              >
                                                {ovPartialSet ? (
                                                  `${ovTrailing}%`
                                                ) : (
                                                  <span className="faint">inherit</span>
                                                )}
                                              </span>
                                              {ovPartialSet && (
                                                <button
                                                  className="btn sm ghost"
                                                  onClick={() =>
                                                    updateInstrumentOverrideTyped(
                                                      t.asset as AssetKey,
                                                      j,
                                                      tpTab,
                                                      'partial',
                                                      ''
                                                    )
                                                  }
                                                >
                                                  ×
                                                </button>
                                              )}
                                            </div>
                                          </td>
                                          <td style={{ width: 40 }}>
                                            <button
                                              className="btn sm ghost"
                                              onClick={() =>
                                                removeInstrumentOverride(t.asset as AssetKey, j)
                                              }
                                            >
                                              ×
                                            </button>
                                          </td>
                                        </tr>
                                      )
                                    })}
                                  </tbody>
                                </table>
                              )}
                              <button
                                className="btn sm ghost"
                                onClick={() => addInstrumentOverride(t.asset as AssetKey)}
                              >
                                + Add symbol
                              </button>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </>
          )}
        </CollapsibleSection>
      )}

      {/* 1-1 FIXED TP */}
      <CollapsibleSection
        head={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <h3>1-1 fixed TP</h3>
            <span className="sub">
              1-1 trades always close at this $ amount · trailing disabled
            </span>
          </div>
        }
        open={openSections.oneToOne}
        onToggle={() => toggleSection('oneToOne')}
      >
        <div
          style={{
            display: 'flex',
            gap: 28,
            alignItems: 'flex-end',
            flexWrap: 'wrap',
            marginBottom: 18,
          }}
        >
          <div className="field">
            <label>Global TP ($)</label>
            <input
              className="inp num mono"
              value={oneToOneDefault}
              onChange={e => {
                setOneToOneDefault(e.target.value)
                touch()
              }}
              style={{ width: 100 }}
            />
          </div>
        </div>
        <table className="tbl" style={{ maxWidth: 460 }}>
          <thead>
            <tr>
              <th>Asset class</th>
              <th className="num">Override TP ($)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {oneToOneRows.map((r, i) => (
              <tr key={i}>
                <td>
                  <input
                    className="inp mono"
                    value={r.asset}
                    onChange={e => updateOneToOneRow(i, 'asset', e.target.value)}
                    placeholder="forex, metals, …"
                    style={{ width: 150 }}
                  />
                </td>
                <td className="num">
                  <input
                    className="inp num mono"
                    value={r.value}
                    onChange={e => updateOneToOneRow(i, 'value', e.target.value)}
                    style={{ width: 88 }}
                  />
                </td>
                <td style={{ width: 40 }}>
                  <button className="btn sm ghost" onClick={() => removeOneToOneRow(i)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={addOneToOneRow}>
          + Add asset override
        </button>
      </CollapsibleSection>

      {/* RISKY */}
      <CollapsibleSection
        head={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <h3>Risky</h3>
            <span className="sub">
              Trailing TP · custom stop-loss from the deepest limit · disabled in the UTC windows
              below
            </span>
          </div>
        }
        open={openSections.risky}
        onToggle={() => toggleSection('risky')}
      >
        <div
          style={{
            display: 'flex',
            gap: 28,
            alignItems: 'flex-end',
            flexWrap: 'wrap',
            marginBottom: 18,
          }}
        >
          <div className="field">
            <label>TP ($)</label>
            <input
              className="inp num mono"
              value={riskyTp}
              onChange={e => {
                setRiskyTp(e.target.value)
                touch()
              }}
              style={{ width: 100 }}
            />
          </div>
          <div className="field">
            <label>Trailing distance ($)</label>
            <input
              className="inp num mono"
              value={riskyTrail}
              onChange={e => {
                setRiskyTrail(e.target.value)
                touch()
              }}
              style={{ width: 100 }}
            />
          </div>
          <div className="field">
            <label>Partial close (%)</label>
            <input
              className="inp num mono"
              value={riskyPartial}
              onChange={e => {
                setRiskyPartial(e.target.value)
                touch()
              }}
              style={{ width: 100 }}
            />
          </div>
          <div className="field">
            <label>Custom SL ($ from deepest limit)</label>
            <input
              className="inp num mono"
              value={riskySl}
              onChange={e => {
                setRiskySl(e.target.value)
                touch()
              }}
              placeholder="DB default"
              style={{ width: 130 }}
            />
          </div>
        </div>
        <span className="sub" style={{ display: 'block', marginBottom: 18 }}>
          Leave Custom SL blank to use the stop-loss from the signal. When set, it applies to every
          limit measured from the deepest one (lowest for longs, highest for shorts).
        </span>
        <label style={{ display: 'block', marginBottom: 8, fontWeight: 600 }}>
          Disabled windows (UTC)
        </label>
        <table className="tbl" style={{ maxWidth: 320 }}>
          <thead>
            <tr>
              <th>Window (HH:MM-HH:MM)</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {riskyWindows.map((w, i) => (
              <tr key={i}>
                <td>
                  <input
                    className="inp mono"
                    value={w}
                    onChange={e => updateRiskyWindow(i, e.target.value)}
                    placeholder="21:55-23:10"
                    style={{ width: 180 }}
                  />
                </td>
                <td style={{ width: 40 }}>
                  <button className="btn sm ghost" onClick={() => removeRiskyWindow(i)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={addRiskyWindow}>
          + Add window
        </button>
      </CollapsibleSection>

      {/* SYMBOL MAPPING */}
      <CollapsibleSection
        head={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <h3>Symbol mapping</h3>
            <span className="sub">DB instrument → your broker's MT5 symbol</span>
            <span className="sub">
              Offset feed for indices, oil &amp; crypto · direct feed for forex, metals &amp; stocks
            </span>
          </div>
        }
        open={openSections.symbols}
        onToggle={() => toggleSection('symbols')}
      >
        <table className="tbl" style={{ maxWidth: 680 }}>
          <thead>
            <tr>
              <th>DB instrument</th>
              <th />
              <th>MT5 symbol</th>
              <th>Feed</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {symbolRows.map((m, i) => {
              const locked = LOCKED_OFFSET_INSTRUMENTS.has(m.db.trim())
              return (
                <tr key={i}>
                  <td>
                    <input
                      className="inp mono"
                      value={m.db}
                      onChange={e => updateSymbolRow(i, 'db', e.target.value)}
                      disabled={locked}
                      style={{ width: 150 }}
                    />
                  </td>
                  <td className="faint" style={{ width: 24, textAlign: 'center' }}>
                    →
                  </td>
                  <td>
                    <input
                      className="inp mono"
                      list="broker-symbols"
                      value={m.mt5}
                      onChange={e => updateSymbolRow(i, 'mt5', e.target.value)}
                      style={{
                        width: 150,
                        borderColor: isUnknownSymbol(m.mt5) ? 'var(--neg, #c0392b)' : undefined,
                      }}
                      title={
                        isUnknownSymbol(m.mt5)
                          ? 'Not found in this broker’s symbol list'
                          : undefined
                      }
                    />
                  </td>
                  <td>
                    <select
                      className="inp"
                      value={locked || m.feed ? 'offset' : 'direct'}
                      onChange={e => updateSymbolFeed(i, e.target.value === 'offset')}
                      disabled={locked}
                      title={locked ? 'Built-in default — feed type is fixed' : undefined}
                      style={{ width: 130 }}
                    >
                      <option value="offset">offset feed</option>
                      <option value="direct">direct feed</option>
                    </select>
                    {locked && (
                      <span className="tag ghost faint" style={{ marginLeft: 6 }}>
                        default
                      </span>
                    )}
                    {isUnknownSymbol(m.mt5) && (
                      <span
                        className="tag ghost"
                        style={{ color: 'var(--neg, #c0392b)', marginLeft: 6 }}
                      >
                        not found
                      </span>
                    )}
                  </td>
                  <td style={{ width: 40 }}>
                    {!locked && (
                      <button className="btn sm ghost" onClick={() => removeSymbolRow(i)}>
                        ×
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div style={{ marginTop: 14 }}>
          <button className="btn sm ghost" onClick={addSymbolRow}>
            + Add mapping
          </button>
        </div>
        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />
        <div className="field" style={{ marginBottom: 0 }}>
          <label>Stock suffix</label>
          <input
            className="inp mono"
            value={stockSuffix}
            onChange={e => {
              setStockSuffix(e.target.value)
              touch()
            }}
            placeholder="-24"
            style={{ width: 120 }}
          />
          <span className="faint" style={{ fontSize: 12 }}>
            appended to .NAS / .NYSE stocks only
          </span>
        </div>

        <div style={{ marginTop: 22 }}>
          <div className="panel-head" style={{ marginBottom: 4 }}>
            <h3 style={{ fontSize: 14 }}>Broker suffixes</h3>
            <span className="sub">
              append a broker tag (e.g. Exness “m”) to chosen asset classes · each class can belong
              to one suffix
            </span>
          </div>
          {suffixRules.map((rule, i) => {
            const takenByOthers = new Set<AssetKey>(
              suffixRules.flatMap((r, j) => (j === i ? [] : r.classes))
            )
            return (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  marginBottom: 10,
                  flexWrap: 'wrap',
                }}
              >
                <input
                  className="inp mono"
                  value={rule.suffix}
                  onChange={e => updateSuffixRuleSuffix(i, e.target.value)}
                  placeholder="e.g. m"
                  style={{ width: 90 }}
                />
                <span className="faint" style={{ fontSize: 12.5 }}>
                  on
                </span>
                <MultiClassPicker
                  selected={rule.classes}
                  disabledClasses={takenByOthers}
                  onToggle={cls => toggleSuffixRuleClass(i, cls)}
                />
                <button className="btn sm ghost" onClick={() => removeSuffixRule(i)}>
                  ×
                </button>
              </div>
            )
          })}
          <button className="btn sm ghost" style={{ marginTop: 6 }} onClick={addSuffixRule}>
            + Add suffix
          </button>
        </div>
      </CollapsibleSection>

      {/* NOT FOUND SYMBOLS */}
      <div className="panel pad">
        <div className="panel-head">
          <h3>Not found symbols</h3>
          <span className="sub">
            signals whose instrument has no matching MT5 symbol on this broker · add a mapping above
            to resolve
          </span>
        </div>
        {notFoundSymbols.length > 0 ? (
          <p className="mono" style={{ fontSize: 13, lineHeight: 1.7, margin: 0 }}>
            {notFoundSymbols.join(', ')}
          </p>
        ) : (
          <p className="faint" style={{ fontSize: 13, margin: 0 }}>
            None — every signalled instrument maps to a symbol on this broker.
          </p>
        )}
      </div>

      {/* EXCLUDED TRADES */}
      <CollapsibleSection
        head={
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <h3>Excluded trades</h3>
            <span className="sub">skip signals before they are ever placed</span>
          </div>
        }
        open={openSections.excluded}
        onToggle={() => toggleSection('excluded')}
      >
        <div className="panel-head" style={{ marginBottom: 6 }}>
          <h3 style={{ fontSize: 14 }}>By symbol</h3>
          <span className="sub">Use DB instrument (e.g. "SPX500USD" not "US500")</span>
        </div>
        {excludedTrades.length > 0 && (
          <table className="tbl" style={{ maxWidth: 520 }}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Signal type</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {excludedTrades.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input
                      className="inp mono"
                      value={r.symbol}
                      onChange={e => updateExcludedTrade(i, 'symbol', e.target.value)}
                      placeholder="XAUUSD, BTCUSDT, …"
                      style={{ width: 180 }}
                    />
                  </td>
                  <td>
                    <select
                      className="inp"
                      value={r.signalType}
                      onChange={e => updateExcludedTrade(i, 'signalType', e.target.value)}
                      style={{ width: 130 }}
                    >
                      {LOT_SIGNAL_TYPES.map(t => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td style={{ width: 40 }}>
                    <button className="btn sm ghost" onClick={() => removeExcludedTrade(i)}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={addExcludedTrade}>
          + Add exclusion
        </button>

        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

        <div className="panel-head" style={{ marginBottom: 6 }}>
          <h3 style={{ fontSize: 14 }}>By channel &amp; asset</h3>
          <span className="sub">
            drop a channel's signals for a given asset class (e.g. indices from one channel) — leave
            a column on "All" to wildcard it
          </span>
        </div>
        {excludedChannelAssets.length > 0 && (
          <table className="tbl" style={{ maxWidth: 520 }}>
            <thead>
              <tr>
                <th>Channel</th>
                <th>Asset class</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {excludedChannelAssets.map((r, i) => (
                <tr key={i}>
                  <td>
                    <select
                      className="inp"
                      value={r.channel}
                      onChange={e => updateExcludedChannelAsset(i, 'channel', e.target.value)}
                      style={{ width: 180 }}
                    >
                      <option value="">All channels</option>
                      {CHANNELS.map(c => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      className="inp"
                      value={r.assetClass}
                      onChange={e => updateExcludedChannelAsset(i, 'assetClass', e.target.value)}
                      style={{ width: 150 }}
                    >
                      <option value="">All assets</option>
                      {ASSET_CLASSES.map(a => (
                        <option key={a} value={a}>
                          {ASSET_CLASS_LABELS[a]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td style={{ width: 40 }}>
                    <button className="btn sm ghost" onClick={() => removeExcludedChannelAsset(i)}>
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button
          className="btn sm ghost"
          style={{ marginTop: 10 }}
          onClick={addExcludedChannelAsset}
        >
          + Add exclusion
        </button>

        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

        <div className="panel-head" style={{ marginBottom: 10 }}>
          <h3 style={{ fontSize: 14 }}>By signal type</h3>
          <span className="sub">unchecked types are skipped</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 26px' }}>
          {SIGNAL_TYPES.map(t => (
            <label
              key={t.value}
              style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
            >
              <span className="mono" style={{ fontSize: 13 }}>
                {t.label}
              </span>
              <input
                type="checkbox"
                checked={!disabledSignalTypes.includes(t.value)}
                onChange={() =>
                  toggleDisabled(disabledSignalTypes, setDisabledSignalTypes, t.value)
                }
                style={{ accentColor: 'var(--accent)', width: 16, height: 16 }}
              />
            </label>
          ))}
        </div>

        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

        <div className="panel-head" style={{ marginBottom: 10 }}>
          <h3 style={{ fontSize: 14 }}>By channel</h3>
          <span className="sub">unchecked channels are skipped</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 26px' }}>
          {CHANNELS.map(c => (
            <label
              key={c.id}
              style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
            >
              <span className="mono" style={{ fontSize: 13 }}>
                {c.name}
              </span>
              <input
                type="checkbox"
                checked={!disabledChannels.includes(c.id)}
                onChange={() => toggleDisabled(disabledChannels, setDisabledChannels, c.id)}
                style={{ accentColor: 'var(--accent)', width: 16, height: 16 }}
              />
            </label>
          ))}
        </div>
      </CollapsibleSection>

      {/* MISC */}
      <CollapsibleSection
        head={<h3>Misc</h3>}
        open={openSections.misc}
        onToggle={() => toggleSection('misc')}
      >
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={disableAutoTp}
            onChange={() => {
              setDisableAutoTp(v => !v)
              touch()
            }}
            style={{ accentColor: 'var(--accent)', width: 16, height: 16, marginTop: 2 }}
          />
          <span style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 13.5, fontWeight: 600 }}>Disable auto-TP</span>
            <span className="faint" style={{ fontSize: 12.5, maxWidth: 560 }}>
              The bot still places, updates, and cancels limits, but never trails or takes profit —
              you manage every exit. Once you fully close a signal, its remaining pending limits are
              cancelled automatically.
            </span>
          </span>
        </label>

        <label
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 10,
            cursor: 'pointer',
            marginTop: 16,
          }}
        >
          <input
            type="checkbox"
            checked={volatilityGuard}
            onChange={() => {
              setVolatilityGuard(v => !v)
              touch()
            }}
            style={{ accentColor: 'var(--accent)', width: 16, height: 16, marginTop: 2 }}
          />
          <span style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 13.5, fontWeight: 600 }}>Volatility guard</span>
            <span className="faint" style={{ fontSize: 12.5, maxWidth: 560 }}>
              React to sharp market moves like news mode: when the signal service flags volatility
              market-wide, all affected trades are cancelled and any open positions closed; when it
              flags specific currencies, only signals involving those currencies are gated. Crypto
              and 24-hour instruments are exempt.
            </span>
          </span>
        </label>
      </CollapsibleSection>

      {/* SAVE */}
      <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
        <button className="btn ghost" onClick={handleDiscard}>
          Reset
        </button>
        <button className="btn primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save configuration'}
        </button>
      </div>

      {error && <p style={{ color: 'var(--neg)', fontSize: 13 }}>{error}</p>}

      {dirty && !toast && (
        <div className="savebar">
          <span className="msg">
            <b>Unsaved changes</b>
          </span>
          <div className="acts">
            <button className="btn sm ghost" onClick={handleDiscard} disabled={saving}>
              Discard
            </button>
            <button className="btn sm primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </div>
      )}
      {toast && (
        <div className="toast">
          <Icon name="check" size={15} strokeWidth={2.6} /> Changes saved
        </div>
      )}
    </div>
  )
}
