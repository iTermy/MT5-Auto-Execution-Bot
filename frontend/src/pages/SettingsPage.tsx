import { useState, useEffect } from 'react'
import { Icon } from '../components/Icon'
import { Seg } from '../components/Seg'
import { startEngine, stopEngine, shutdownEngine, updateConfig } from '../api'
import type { Config, StatusData } from '../types'

interface TpRow {
  asset: string
  thr: string
  unit: string
  trail: string
  sThr: string
  sTrail: string
}

interface SymbolRow {
  db: string
  mt5: string
  feed: boolean
}

interface Props {
  config: Config | null
  status: StatusData | null
  onConfigSaved: (config: Config) => void
}

export function SettingsPage({ config, status, onConfigSaved }: Props) {
  const [lotMode, setLotMode] = useState('risk_percent')
  const [riskPct, setRiskPct] = useState('1.0')
  const [fixedLot, setFixedLot] = useState('0.01')
  const [maxLot, setMaxLot] = useState('5.0')
  const [licenseKey, setLicenseKey] = useState('')
  const [partial, setPartial] = useState(50)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [tpRows, setTpRows] = useState<TpRow[]>([])
  const [symbolRows, setSymbolRows] = useState<SymbolRow[]>([])

  useEffect(() => {
    if (config) {
      setLotMode(config.lot_sizing.mode)
      setRiskPct(String(config.lot_sizing.risk_percent))
      setFixedLot(String(config.lot_sizing.fixed_lot))
      setMaxLot(String(config.lot_sizing.max_lot_per_order))
      setLicenseKey(config.license_key)

      const pct = config.partial_close_pct as number | undefined
      if (pct != null) setPartial(pct)

      const tp = config.tp_config as Record<string, unknown>[] | undefined
      if (tp && Array.isArray(tp)) {
        setTpRows(tp.map((r: Record<string, unknown>) => ({
          asset: String(r.asset_class ?? r.asset ?? ''),
          thr: String(r.profit_threshold ?? r.thr ?? ''),
          unit: String(r.unit ?? ''),
          trail: String(r.trail_distance ?? r.trail ?? ''),
          sThr: String(r.scalp_threshold ?? r.sThr ?? ''),
          sTrail: String(r.scalp_trail ?? r.sTrail ?? ''),
        })))
      }

      const sym = config.symbol_overrides as Record<string, string> | undefined
      if (sym && typeof sym === 'object') {
        setSymbolRows(Object.entries(sym).map(([db, mt5]) => ({
          db,
          mt5: String(mt5),
          feed: false,
        })))
      }
    }
  }, [config])

  const touch = () => setDirty(true)

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
          fixed_lot: parseFloat(fixedLot) || 0.01,
          max_lot_per_order: parseFloat(maxLot) || 5.0,
        },
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
    setDirty(false)
    if (config) {
      setLotMode(config.lot_sizing.mode)
      setRiskPct(String(config.lot_sizing.risk_percent))
      setFixedLot(String(config.lot_sizing.fixed_lot))
      setMaxLot(String(config.lot_sizing.max_lot_per_order))
      setLicenseKey(config.license_key)
    }
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
          <button className="btn">Validate</button>
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
          <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end', flexWrap: 'wrap' }}>
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
          <div style={{ display: 'flex', gap: 28, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div className="field">
              <label>Fixed lot size</label>
              <input
                className="inp num mono"
                value={fixedLot}
                onChange={e => { setFixedLot(e.target.value); touch() }}
              />
            </div>
          </div>
        )}
      </div>

      {/* TAKE PROFIT & TRAILING */}
      {tpRows.length > 0 && (
        <div className="panel pad">
          <div className="panel-head">
            <h3>Take-profit &amp; trailing</h3>
            <span className="sub">per asset class · scalp overrides faded</span>
          </div>
          <div style={{ display: 'flex', gap: 18, alignItems: 'center', marginBottom: 20, flexWrap: 'wrap' }}>
            <label style={{ fontSize: 13, color: 'var(--text-2)', fontWeight: 500 }}>Partial close on trigger</label>
            <span className="mono" style={{ fontSize: 18, fontWeight: 600, color: 'var(--accent)', width: 52 }}>{partial}%</span>
            <input
              type="range"
              min={0} max={100} step={5}
              value={partial}
              onChange={e => { setPartial(+e.target.value); touch() }}
              style={{ flex: 1, maxWidth: 320, accentColor: 'var(--accent)' }}
            />
          </div>
          <table className="tbl">
            <thead>
              <tr>
                <th>Asset class</th>
                <th className="num">Threshold</th>
                <th>Unit</th>
                <th className="num">Trail dist.</th>
                <th className="num">Scalp thr.</th>
                <th className="num">Scalp trail</th>
              </tr>
            </thead>
            <tbody>
              {tpRows.map(t => (
                <tr key={t.asset}>
                  <td><span className="sym">{t.asset}</span></td>
                  <td className="num"><input className="inp num mono" defaultValue={t.thr} style={{ width: 76 }} onChange={touch} /></td>
                  <td className="dim">{t.unit}</td>
                  <td className="num"><input className="inp num mono" defaultValue={t.trail} style={{ width: 76 }} onChange={touch} /></td>
                  <td className="num"><input className="inp num mono" defaultValue={t.sThr} style={{ width: 70, opacity: .6 }} onChange={touch} /></td>
                  <td className="num"><input className="inp num mono" defaultValue={t.sTrail} style={{ width: 70, opacity: .6 }} onChange={touch} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* SYMBOL MAPPING */}
      {symbolRows.length > 0 && (
        <div className="panel pad">
          <div className="panel-head">
            <h3>Symbol mapping</h3>
            <span className="sub">DB instrument → your broker's MT5 symbol</span>
          </div>
          <table className="tbl" style={{ maxWidth: 620 }}>
            <thead>
              <tr>
                <th>DB instrument</th>
                <th />
                <th>MT5 symbol</th>
                <th>Feed</th>
              </tr>
            </thead>
            <tbody>
              {symbolRows.map(m => (
                <tr key={m.db}>
                  <td><input className="inp mono" defaultValue={m.db} style={{ width: 150 }} onChange={touch} /></td>
                  <td className="faint" style={{ width: 24 }}>→</td>
                  <td><input className="inp mono" defaultValue={m.mt5} style={{ width: 150 }} onChange={touch} /></td>
                  <td>{m.feed ? <span className="tag long">offset feed</span> : <span className="tag ghost">direct</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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
