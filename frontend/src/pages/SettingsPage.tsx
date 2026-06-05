import { useState, useEffect, useCallback, useRef, Fragment } from 'react'
import { Icon } from '../components/Icon'
import { Seg } from '../components/Seg'
import { startEngine, stopEngine, shutdownEngine, updateConfig } from '../api'
import type {
  Config,
  TPConfig,
  AssetTPConfig,
  ScalpOverrideConfig,
  LotExceptionConfig,
} from '../types'
import { detectAssetClass } from '../utils/assetClass'

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

type OverrideType = 'scalp' | 'toll' | 'swing' | 'pa'
const OVERRIDE_TYPES: OverrideType[] = ['scalp', 'toll', 'swing', 'pa']

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
  mode: 'risk_percent' | 'fixed'
  value: string
}

interface InstrumentOverrideRow {
  symbol: string
  thr: string
  trail: string
  partial: string // stored as partial_close_percent in config; UI displays trailing
}

interface Props {
  config: Config | null
  status: {
    trading_active?: boolean
    mt5_connected?: boolean
    supabase_connected?: boolean
    license_valid?: boolean
  } | null
  onConfigSaved: (config: Config) => void
}

export function SettingsPage({ config, status, onConfigSaved }: Props) {
  const [lotMode, setLotMode] = useState('risk_percent')
  const [riskPct, setRiskPct] = useState('1.0')
  const [fixedLotDefault, setFixedLotDefault] = useState('0.01')
  const [maxLot, setMaxLot] = useState('5.0')
  const [lotExceptions, setLotExceptions] = useState<LotExceptionRow[]>([])
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
  const [symbolRows, setSymbolRows] = useState<SymbolRow[]>([])
  const [stockSuffix, setStockSuffix] = useState('-24')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stopMenuOpen, setStopMenuOpen] = useState(false)
  const stopMenuRef = useRef<HTMLDivElement | null>(null)

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

    // Load exceptions. Prefer the new `exceptions` field; if absent, migrate
    // any legacy non-`default` keys from risk_percent / fixed_lot dicts.
    const exceptions: LotExceptionRow[] = []
    const seen = new Set<string>()
    if (cfg.lot_sizing.exceptions) {
      for (const [sym, ex] of Object.entries(cfg.lot_sizing.exceptions)) {
        exceptions.push({ symbol: sym, mode: ex.mode, value: String(ex.value) })
        seen.add(sym)
      }
    }
    if (rp && typeof rp === 'object') {
      for (const [sym, value] of Object.entries(rp as Record<string, number>)) {
        if (sym === 'default' || seen.has(sym)) continue
        exceptions.push({ symbol: sym, mode: 'risk_percent', value: String(value) })
        seen.add(sym)
      }
    }
    if (fl && typeof fl === 'object') {
      for (const [sym, value] of Object.entries(fl as Record<string, number>)) {
        if (sym === 'default' || seen.has(sym)) continue
        exceptions.push({ symbol: sym, mode: 'fixed', value: String(value) })
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

      // Group per-symbol instrument overrides by detected asset class.
      const grouped = Object.fromEntries(
        ASSET_CLASSES.map(a => [a, [] as InstrumentOverrideRow[]])
      ) as Record<AssetKey, InstrumentOverrideRow[]>
      for (const [sym, inst] of Object.entries(tp.instrument_overrides ?? {})) {
        const ac = detectAssetClass(sym) as AssetKey
        const i = inst as Record<string, unknown>
        grouped[ac].push({
          symbol: sym,
          thr: i.profit_threshold != null ? String(i.profit_threshold) : '',
          trail: i.trailing_distance != null ? String(i.trailing_distance) : '',
          partial: i.partial_close_percent != null ? String(i.partial_close_percent) : '',
        })
      }
      setInstrumentOverrides(grouped)
    }

    const offsetInst = cfg.offset_instruments ?? []
    setSymbolRows(
      Object.entries(cfg.symbol_map ?? {}).map(([db, mt5]) => ({
        db,
        mt5: String(mt5),
        feed: offsetInst.includes(db),
      }))
    )
    setStockSuffix(cfg.stock_suffix ?? '-24')
  }, [])

  useEffect(() => {
    if (config) initFromConfig(config)
  }, [config, initFromConfig])

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

  function removeOneToOneRow(i: number) {
    setOneToOneRows(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function updateSymbolRow(i: number, field: 'db' | 'mt5', value: string) {
    setSymbolRows(prev => prev.map((r, j) => (j === i ? { ...r, [field]: value } : r)))
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

  function updateLotException(i: number, field: 'symbol' | 'mode' | 'value', value: string) {
    setLotExceptions(prev =>
      prev.map((r, j) => {
        if (j !== i) return r
        if (field === 'mode') return { ...r, mode: value as 'risk_percent' | 'fixed' }
        return { ...r, [field]: value }
      })
    )
    touch()
  }

  function addLotException() {
    setLotExceptions(prev => [...prev, { symbol: '', mode: 'risk_percent', value: '1.0' }])
    touch()
  }

  function removeLotException(i: number) {
    setLotExceptions(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function buildLotExceptions(): Record<string, LotExceptionConfig> {
    return Object.fromEntries(
      lotExceptions
        .filter(r => r.symbol.trim())
        .map(r => [r.symbol.trim(), { mode: r.mode, value: parseFloat(r.value) || 0 }])
    )
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
      [asset]: [...prev[asset], { symbol: '', thr: '', trail: '', partial: '' }],
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
        const entry: Record<string, unknown> = {}
        if (row.thr !== '') entry.profit_threshold = parseFloat(row.thr) || 0
        if (row.trail !== '') entry.trailing_distance = parseFloat(row.trail) || 0
        if (row.partial !== '') entry.partial_close_percent = parseInt(row.partial, 10) || 0
        if (Object.keys(entry).length === 0) continue
        out[sym] = entry
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
    return {
      ...config!.tp_config,
      ...assetEntries,
      ...overrideMaps,
      one_to_one: oneToOne,
      instrument_overrides: buildInstrumentOverrides(),
    } as TPConfig
  }

  function buildSymbolMap(): Record<string, string> {
    return Object.fromEntries(
      symbolRows.filter(r => r.db.trim() && r.mt5.trim()).map(r => [r.db.trim(), r.mt5.trim()])
    )
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
          max_lot_per_order: parseFloat(maxLot) || 5.0,
          exceptions: buildLotExceptions(),
        },
        tp_config: buildTpConfig(),
        symbol_map: buildSymbolMap(),
        stock_suffix: stockSuffix,
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
    try {
      const updated: Config = {
        ...config,
        license_key: licenseKey,
        mt5_terminal_path: mt5TerminalPath,
      }
      await updateConfig(updated)
      onConfigSaved(updated)
    } catch {
      /* ignore */
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

  const isActive = status?.trading_active ?? false
  const mt5Ok = status?.mt5_connected ?? false
  const supaOk = status?.supabase_connected ?? false
  const licenseOk = status?.license_valid ?? false

  return (
    <div className="page">
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
          <div className={`conn ${mt5Ok ? 'live' : 'off'}`}>
            <span className="d" /> MT5 {mt5Ok ? 'connected' : 'disconnected'}
          </div>
          <div className={`conn ${supaOk ? 'live' : 'off'}`}>
            <span className="d" /> Database {supaOk ? 'connected' : 'disconnected'}
          </div>
          <div className={`conn ${licenseOk ? 'live' : 'off'}`}>
            <span className="d" /> License {licenseOk ? 'valid' : 'invalid'}
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
            <input
              className="inp mono"
              value={mt5TerminalPath}
              onChange={e => {
                setMt5TerminalPath(e.target.value)
                touch()
              }}
              placeholder="C:\Program Files\MetaTrader 5\terminal64.exe"
              style={{ width: 420 }}
            />
          </div>
          <button className="btn" onClick={handleValidate}>
            Save &amp; validate
          </button>
        </div>
      </div>

      {/* LOT SIZING */}
      <div className="panel pad">
        <div className="panel-head">
          <h3>Lot sizing</h3>
        </div>
        <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="field">
            <label>Default mode</label>
            <Seg
              accent
              value={lotMode}
              options={[
                { value: 'risk_percent', label: 'Risk %' },
                { value: 'fixed', label: 'Fixed lot' },
              ]}
              onChange={v => {
                setLotMode(v)
                touch()
              }}
            />
          </div>
          {lotMode === 'risk_percent' ? (
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
          ) : (
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
        </div>

        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

        <div className="panel-head" style={{ marginBottom: 6 }}>
          <h3 style={{ fontSize: 14 }}>Exceptions</h3>
          <span className="sub">override mode and value for specific MT5 symbols</span>
        </div>
        {lotExceptions.length > 0 && (
          <table className="tbl" style={{ maxWidth: 600 }}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Mode</th>
                <th className="num">Value</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lotExceptions.map((r, i) => (
                <tr key={i}>
                  <td>
                    <input
                      className="inp mono"
                      value={r.symbol}
                      onChange={e => updateLotException(i, 'symbol', e.target.value)}
                      placeholder="BTCUSD, XAUUSD, …"
                      style={{ width: 160 }}
                    />
                  </td>
                  <td>
                    <Seg
                      value={r.mode}
                      options={[
                        { value: 'risk_percent', label: 'Risk %' },
                        { value: 'fixed', label: 'Fixed' },
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
      </div>

      {/* TAKE PROFIT & TRAILING */}
      {tpRows.length > 0 && (
        <div className="panel pad">
          <div className="panel-head">
            <h3>Take-profit &amp; trailing</h3>
            <span className="sub">per asset class · per signal type</span>
          </div>
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
                    <th style={{ width: 32 }} />
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
                          <td>
                            <span className="sym">{t.asset}</span>
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
                          <td style={{ textAlign: 'right' }}>
                            <button
                              className="btn sm ghost"
                              onClick={() =>
                                setExpandedAsset(isExpanded ? null : (t.asset as AssetKey))
                              }
                              title={
                                isExpanded
                                  ? 'Hide per-symbol overrides'
                                  : 'Add per-symbol overrides'
                              }
                            >
                              {isExpanded ? '−' : '+'}
                              {overrides.length > 0 && !isExpanded && (
                                <span className="faint" style={{ marginLeft: 4 }}>
                                  {overrides.length}
                                </span>
                              )}
                            </button>
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr>
                            <td
                              colSpan={6}
                              style={{
                                background: 'var(--panel-soft, transparent)',
                                padding: '10px 14px',
                              }}
                            >
                              <div className="faint" style={{ fontSize: 12, marginBottom: 8 }}>
                                Per-symbol overrides for <b>{t.asset}</b> · blank = inherit
                                asset-class value · applies to all signal types
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
                    return (
                      <tr key={t.asset}>
                        <td>
                          <span className="sym">{t.asset}</span>
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
                    )
                  })}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      {/* 1-1 FIXED TP */}
      <div className="panel pad">
        <div className="panel-head">
          <h3>1-1 fixed TP</h3>
          <span className="sub">1-1 trades always close at this $ amount · trailing disabled</span>
        </div>
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
      </div>

      {/* SYMBOL MAPPING */}
      <div className="panel pad">
        <div className="panel-head">
          <h3>Symbol mapping</h3>
          <span className="sub">DB instrument → your broker's MT5 symbol</span>
        </div>
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
            {symbolRows.map((m, i) => (
              <tr key={i}>
                <td>
                  <input
                    className="inp mono"
                    value={m.db}
                    onChange={e => updateSymbolRow(i, 'db', e.target.value)}
                    style={{ width: 150 }}
                  />
                </td>
                <td className="faint" style={{ width: 24, textAlign: 'center' }}>
                  →
                </td>
                <td>
                  <input
                    className="inp mono"
                    value={m.mt5}
                    onChange={e => updateSymbolRow(i, 'mt5', e.target.value)}
                    style={{ width: 150 }}
                  />
                </td>
                <td>
                  {m.feed ? (
                    <span className="tag long">offset feed</span>
                  ) : (
                    <span className="tag ghost">direct</span>
                  )}
                </td>
                <td style={{ width: 40 }}>
                  <button className="btn sm ghost" onClick={() => removeSymbolRow(i)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div
          style={{
            display: 'flex',
            gap: 20,
            alignItems: 'flex-end',
            marginTop: 14,
            flexWrap: 'wrap',
          }}
        >
          <button className="btn sm ghost" onClick={addSymbolRow}>
            + Add mapping
          </button>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Stock suffix</label>
            <input
              className="inp mono"
              value={stockSuffix}
              onChange={e => {
                setStockSuffix(e.target.value)
                touch()
              }}
              style={{ width: 80 }}
            />
          </div>
        </div>
      </div>

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
