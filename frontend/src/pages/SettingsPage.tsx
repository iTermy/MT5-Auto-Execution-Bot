import { useState, useEffect, useCallback } from 'react'
import { Icon } from '../components/Icon'
import { Seg } from '../components/Seg'
import { startEngine, stopEngine, shutdownEngine, updateConfig } from '../api'
import type { Config, TPConfig, AssetTPConfig, ScalpOverrideConfig } from '../types'

const ASSET_CLASSES = ['forex', 'forex_jpy', 'metals', 'indices', 'stocks', 'crypto', 'oil'] as const
type AssetKey = typeof ASSET_CLASSES[number]

type OverrideType = 'scalp' | 'toll' | 'swing' | 'pa'
const OVERRIDE_TYPES: OverrideType[] = ['scalp', 'toll', 'swing', 'pa']

interface OverridePair {
  thr: string
  trail: string
  partial: string  // empty string means "inherit from standard"
}

interface TpRow {
  asset: string
  thr: string
  unit: string
  trail: string
  partial: string  // per-asset standard partial close % (default 50)
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

interface FixedLotRow {
  instrument: string
  lot: string
}

interface Props {
  config: Config | null
  status: { trading_active?: boolean; mt5_connected?: boolean; supabase_connected?: boolean; license_valid?: boolean } | null
  onConfigSaved: (config: Config) => void
}

export function SettingsPage({ config, status, onConfigSaved }: Props) {
  const [lotMode, setLotMode] = useState('risk_percent')
  const [riskPct, setRiskPct] = useState('1.0')
  const [maxLot, setMaxLot] = useState('5.0')
  const [fixedLotRows, setFixedLotRows] = useState<FixedLotRow[]>([{ instrument: 'default', lot: '0.01' }])
  const [licenseKey, setLicenseKey] = useState('')
  const [tpRows, setTpRows] = useState<TpRow[]>([])
  const [tpTab, setTpTab] = useState<'standard' | OverrideType>('standard')
  const [oneToOneDefault, setOneToOneDefault] = useState('10')
  const [oneToOneRows, setOneToOneRows] = useState<OneToOneOverrideRow[]>([])
  const [symbolRows, setSymbolRows] = useState<SymbolRow[]>([])
  const [stockSuffix, setStockSuffix] = useState('-24')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const touch = () => setDirty(true)

  const initFromConfig = useCallback((cfg: Config) => {
    setLotMode(cfg.lot_sizing.mode)
    setRiskPct(String(cfg.lot_sizing.risk_percent))
    setMaxLot(String(cfg.lot_sizing.max_lot_per_order))
    setLicenseKey(cfg.license_key)

    const fl = cfg.lot_sizing.fixed_lot
    if (typeof fl === 'number') {
      setFixedLotRows([{ instrument: 'default', lot: String(fl) }])
    } else if (fl && typeof fl === 'object') {
      const entries = Object.entries(fl)
      const def = entries.find(([k]) => k === 'default')
      const others = entries.filter(([k]) => k !== 'default')
      setFixedLotRows([
        { instrument: 'default', lot: String(def ? def[1] : 0.01) },
        ...others.map(([k, v]) => ({ instrument: k, lot: String(v) })),
      ])
    }

    const tp = cfg.tp_config
    if (tp) {
      const globalPartialFallback = tp.partial_close_percent ?? 50
      const overrideSources: Record<OverrideType, Record<string, ScalpOverrideConfig> | undefined> = {
        scalp: tp.scalp_overrides,
        toll:  tp.toll_overrides,
        swing: tp.swing_overrides,
        pa:    tp.pa_overrides,
      }
      setTpRows(ASSET_CLASSES.map(asset => {
        const acfg = tp[asset as AssetKey] as AssetTPConfig | undefined
        const overrides = {} as Record<OverrideType, OverridePair>
        for (const t of OVERRIDE_TYPES) {
          const ov = overrideSources[t]?.[asset]
          overrides[t] = {
            thr: ov ? String(ov.profit_threshold) : '',
            trail: ov ? String(ov.trailing_distance) : '',
            partial: ov && ov.partial_close_percent != null ? String(ov.partial_close_percent) : '',
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
      }))
      const one = tp.one_to_one
      setOneToOneDefault(String(one?.profit_threshold ?? 10))
      setOneToOneRows(Object.entries(one?.overrides ?? {}).map(([asset, value]) => ({
        asset, value: String(value),
      })))
    }

    const offsetInst = cfg.offset_instruments ?? []
    setSymbolRows(Object.entries(cfg.symbol_map ?? {}).map(([db, mt5]) => ({
      db, mt5: String(mt5), feed: offsetInst.includes(db),
    })))
    setStockSuffix(cfg.stock_suffix ?? '-24')
  }, [])

  useEffect(() => {
    if (config) initFromConfig(config)
  }, [config, initFromConfig])

  function updateTpStandard(i: number, field: 'thr' | 'unit' | 'trail' | 'partial', value: string) {
    setTpRows(prev => prev.map((r, j) => j === i ? { ...r, [field]: value } : r))
    touch()
  }

  function updateTpOverride(i: number, type: OverrideType, field: 'thr' | 'trail' | 'partial', value: string) {
    setTpRows(prev => prev.map((r, j) => {
      if (j !== i) return r
      const pair = { ...r.overrides[type], [field]: value }
      return { ...r, overrides: { ...r.overrides, [type]: pair } }
    }))
    touch()
  }

  function updateOneToOneRow(i: number, field: 'asset' | 'value', value: string) {
    setOneToOneRows(prev => prev.map((r, j) => j === i ? { ...r, [field]: value } : r))
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
    setSymbolRows(prev => prev.map((r, j) => j === i ? { ...r, [field]: value } : r))
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

  function updateFixedLotRow(i: number, field: 'instrument' | 'lot', value: string) {
    setFixedLotRows(prev => prev.map((r, j) => j === i ? { ...r, [field]: value } : r))
    touch()
  }

  function addFixedLotRow() {
    setFixedLotRows(prev => [...prev, { instrument: '', lot: '0.01' }])
    touch()
  }

  function removeFixedLotRow(i: number) {
    setFixedLotRows(prev => prev.filter((_, j) => j !== i))
    touch()
  }

  function buildFixedLot(): number | Record<string, number> {
    if (fixedLotRows.length === 1 && fixedLotRows[0].instrument === 'default') {
      return parseFloat(fixedLotRows[0].lot) || 0.01
    }
    return Object.fromEntries(
      fixedLotRows
        .filter(r => r.instrument.trim())
        .map(r => [r.instrument.trim(), parseFloat(r.lot) || 0.01])
    )
  }

  function buildTpConfig(): TPConfig {
    const assetEntries = Object.fromEntries(
      tpRows.map(row => [row.asset, {
        profit_threshold: parseFloat(row.thr) || 0,
        threshold_unit: row.unit,
        trailing_distance: parseFloat(row.trail) || 0,
        partial_close_percent: parseInt(row.partial, 10) || 50,
      }])
    )
    const overrideMaps = {} as Record<`${OverrideType}_overrides`, Record<string, ScalpOverrideConfig>>
    for (const t of OVERRIDE_TYPES) {
      overrideMaps[`${t}_overrides`] = Object.fromEntries(
        tpRows
          .filter(row => row.overrides[t].thr !== '' || row.overrides[t].trail !== '' || row.overrides[t].partial !== '')
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
    } as TPConfig
  }

  function buildSymbolMap(): Record<string, string> {
    return Object.fromEntries(
      symbolRows
        .filter(r => r.db.trim() && r.mt5.trim())
        .map(r => [r.db.trim(), r.mt5.trim()])
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
        lot_sizing: {
          mode: lotMode,
          risk_percent: parseFloat(riskPct) || 1.0,
          fixed_lot: buildFixedLot(),
          max_lot_per_order: parseFloat(maxLot) || 5.0,
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
      const updated: Config = { ...config, license_key: licenseKey }
      await updateConfig(updated)
      onConfigSaved(updated)
    } catch { /* ignore */ }
  }

  async function handleEngineToggle() {
    setBusy(true)
    setError(null)
    try {
      if (status?.trading_active) await stopEngine()
      else await startEngine()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleShutdown() {
    try { await shutdownEngine() } catch { /* connection will drop */ }
  }

  const isActive = status?.trading_active ?? false
  const mt5Ok = status?.mt5_connected ?? false
  const supaOk = status?.supabase_connected ?? false
  const licenseOk = status?.license_valid ?? false

  return (
    <div className="page">
      <div>
        <div className="eyebrow">Configuration</div>
        <h2 style={{ margin: '4px 0 0', fontSize: 24, fontWeight: 700, letterSpacing: '-0.01em' }}>Settings</h2>
      </div>

      {/* ENGINE & CONNECTION */}
      <div className="panel pad">
        <div className="panel-head"><h3>Engine &amp; connection</h3></div>
        <div style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className={`conn ${mt5Ok ? 'live' : 'off'}`}><span className="d" /> MT5 {mt5Ok ? 'connected' : 'disconnected'}</div>
          <div className={`conn ${supaOk ? 'live' : 'off'}`}><span className="d" /> Database {supaOk ? 'connected' : 'disconnected'}</div>
          <div className={`conn ${licenseOk ? 'live' : 'off'}`}><span className="d" /> License {licenseOk ? 'valid' : 'invalid'}</div>
          <div style={{ flex: 1 }} />
          <button className="btn" onClick={handleEngineToggle} disabled={busy}>
            <Icon name="power" size={14} strokeWidth={2.2} /> {isActive ? 'Stop engine' : 'Start engine'}
          </button>
          <button className="btn danger" onClick={handleShutdown}>
            <Icon name="power" size={14} strokeWidth={2.2} /> Shut down
          </button>
        </div>
        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />
        <div style={{ display: 'flex', gap: 14, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="field">
            <label>License key</label>
            <input
              className="inp mono"
              value={licenseKey}
              onChange={e => { setLicenseKey(e.target.value); touch() }}
              style={{ width: 280 }}
            />
          </div>
          <button className="btn" onClick={handleValidate}>Validate</button>
        </div>
      </div>

      {/* LOT SIZING */}
      <div className="panel pad">
        <div className="panel-head"><h3>Lot sizing</h3></div>
        <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div className="field">
            <label>Mode</label>
            <Seg
              accent
              value={lotMode}
              options={[
                { value: 'risk_percent', label: 'Risk %' },
                { value: 'fixed', label: 'Fixed lot' },
              ]}
              onChange={v => { setLotMode(v); touch() }}
            />
          </div>
          <div className="field">
            <label>Max lot / order</label>
            <input
              className="inp num mono"
              value={maxLot}
              onChange={e => { setMaxLot(e.target.value); touch() }}
            />
          </div>
        </div>

        <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

        {lotMode === 'risk_percent' ? (
          <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end' }}>
            <div className="field">
              <label>Risk per signal (%)</label>
              <input
                className="inp num mono"
                value={riskPct}
                onChange={e => { setRiskPct(e.target.value); touch() }}
              />
            </div>
          </div>
        ) : (
          <div>
            <table className="tbl" style={{ maxWidth: 460 }}>
              <thead>
                <tr>
                  <th>Instrument</th>
                  <th className="num">Fixed lot</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {fixedLotRows.map((r, i) => (
                  <tr key={i}>
                    <td>
                      {r.instrument === 'default'
                        ? <span className="t-sub">Default</span>
                        : <input
                            className="inp mono"
                            value={r.instrument}
                            onChange={e => updateFixedLotRow(i, 'instrument', e.target.value)}
                            style={{ width: 150 }}
                          />}
                    </td>
                    <td className="num">
                      <input
                        className="inp num mono"
                        value={r.lot}
                        onChange={e => updateFixedLotRow(i, 'lot', e.target.value)}
                        style={{ width: 88 }}
                      />
                    </td>
                    <td style={{ width: 40 }}>
                      {r.instrument !== 'default' && (
                        <button className="btn sm ghost" onClick={() => removeFixedLotRow(i)}>×</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={addFixedLotRow}>
              + Add instrument
            </button>
          </div>
        )}
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
            <table className="tbl">
              <thead>
                <tr>
                  <th>Asset class</th>
                  <th className="num">Threshold</th>
                  <th>Unit</th>
                  <th className="num">Trail dist.</th>
                  <th>Partial close</th>
                </tr>
              </thead>
              <tbody>
                {tpRows.map((t, i) => (
                  <tr key={t.asset}>
                    <td><span className="sym">{t.asset}</span></td>
                    <td className="num">
                      <input className="inp num mono" value={t.thr} style={{ width: 76 }}
                        onChange={e => updateTpStandard(i, 'thr', e.target.value)} />
                    </td>
                    <td className="dim">{t.unit}</td>
                    <td className="num">
                      <input className="inp num mono" value={t.trail} style={{ width: 76 }}
                        onChange={e => updateTpStandard(i, 'trail', e.target.value)} />
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <input
                          type="range" min={0} max={100} step={5}
                          value={parseInt(t.partial, 10) || 50}
                          onChange={e => updateTpStandard(i, 'partial', e.target.value)}
                          style={{ width: 140, accentColor: 'var(--accent)' }}
                        />
                        <span className="mono" style={{ width: 40, fontWeight: 600 }}>{parseInt(t.partial, 10) || 50}%</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <>
              <p className="faint" style={{ marginTop: 0, marginBottom: 12, fontSize: 12.5 }}>
                {tpTab === 'swing'
                  ? 'Leave blank to fall back to 3× the standard threshold. Partial close left blank inherits from Standard.'
                  : 'Leave blank to fall back to the standard asset-class settings.'}
              </p>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Asset class</th>
                    <th className="num">Threshold</th>
                    <th>Unit</th>
                    <th className="num">Trail dist.</th>
                    <th>Partial close</th>
                  </tr>
                </thead>
                <tbody>
                  {tpRows.map((t, i) => {
                    const partialSet = t.overrides[tpTab].partial !== ''
                    const partialNum = parseInt(t.overrides[tpTab].partial, 10) || 50
                    return (
                      <tr key={t.asset}>
                        <td><span className="sym">{t.asset}</span></td>
                        <td className="num">
                          <input className="inp num mono" value={t.overrides[tpTab].thr} style={{ width: 76 }}
                            onChange={e => updateTpOverride(i, tpTab, 'thr', e.target.value)} />
                        </td>
                        <td className="dim">{t.unit}</td>
                        <td className="num">
                          <input className="inp num mono" value={t.overrides[tpTab].trail} style={{ width: 76 }}
                            onChange={e => updateTpOverride(i, tpTab, 'trail', e.target.value)} />
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <input
                              type="range" min={0} max={100} step={5}
                              value={partialNum}
                              onChange={e => updateTpOverride(i, tpTab, 'partial', e.target.value)}
                              style={{ width: 140, accentColor: 'var(--accent)' }}
                            />
                            <span className="mono" style={{ width: 56, fontWeight: 600 }}>
                              {partialSet ? `${partialNum}%` : <span className="faint">inherit</span>}
                            </span>
                            {partialSet && (
                              <button className="btn sm ghost" onClick={() => updateTpOverride(i, tpTab, 'partial', '')}>×</button>
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
        <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 18 }}>
          <div className="field">
            <label>Global TP ($)</label>
            <input
              className="inp num mono"
              value={oneToOneDefault}
              onChange={e => { setOneToOneDefault(e.target.value); touch() }}
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
                  <input className="inp mono" value={r.asset}
                    onChange={e => updateOneToOneRow(i, 'asset', e.target.value)}
                    placeholder="forex, metals, …"
                    style={{ width: 150 }} />
                </td>
                <td className="num">
                  <input className="inp num mono" value={r.value}
                    onChange={e => updateOneToOneRow(i, 'value', e.target.value)}
                    style={{ width: 88 }} />
                </td>
                <td style={{ width: 40 }}>
                  <button className="btn sm ghost" onClick={() => removeOneToOneRow(i)}>×</button>
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
                  <input className="inp mono" value={m.db}
                    onChange={e => updateSymbolRow(i, 'db', e.target.value)}
                    style={{ width: 150 }} />
                </td>
                <td className="faint" style={{ width: 24, textAlign: 'center' }}>→</td>
                <td>
                  <input className="inp mono" value={m.mt5}
                    onChange={e => updateSymbolRow(i, 'mt5', e.target.value)}
                    style={{ width: 150 }} />
                </td>
                <td>{m.feed ? <span className="tag long">offset feed</span> : <span className="tag ghost">direct</span>}</td>
                <td style={{ width: 40 }}>
                  <button className="btn sm ghost" onClick={() => removeSymbolRow(i)}>×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-end', marginTop: 14, flexWrap: 'wrap' }}>
          <button className="btn sm ghost" onClick={addSymbolRow}>+ Add mapping</button>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Stock suffix</label>
            <input
              className="inp mono"
              value={stockSuffix}
              onChange={e => { setStockSuffix(e.target.value); touch() }}
              style={{ width: 80 }}
            />
          </div>
        </div>
      </div>

      {/* SAVE */}
      <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
        <button className="btn ghost" onClick={handleDiscard}>Reset</button>
        <button className="btn primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save configuration'}
        </button>
      </div>

      {error && <p style={{ color: 'var(--neg)', fontSize: 13 }}>{error}</p>}

      {dirty && !toast && (
        <div className="savebar">
          <span className="msg"><b>Unsaved changes</b></span>
          <div className="acts">
            <button className="btn sm ghost" onClick={handleDiscard} disabled={saving}>Discard</button>
            <button className="btn sm primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </div>
      )}
      {toast && (
        <div className="toast"><Icon name="check" size={15} strokeWidth={2.6} /> Changes saved</div>
      )}
    </div>
  )
}
