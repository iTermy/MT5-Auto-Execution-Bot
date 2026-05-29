import { useState, useEffect } from 'react'
import { startEngine, stopEngine, shutdownEngine, updateConfig } from '../api'
import type { Config, StatusData } from '../types'

interface Props {
  config: Config | null
  status: StatusData | null
  onConfigSaved: (config: Config) => void
}

export function SettingsPage({ config, status, onConfigSaved }: Props) {
  const [lotMode, setLotMode] = useState('risk_percent')
  const [riskPct, setRiskPct] = useState(1.0)
  const [fixedLot, setFixedLot] = useState(0.01)
  const [licenseKey, setLicenseKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showShutdownConfirm, setShowShutdownConfirm] = useState(false)

  useEffect(() => {
    if (config) {
      setLotMode(config.lot_sizing.mode)
      setRiskPct(config.lot_sizing.risk_percent)
      setFixedLot(config.lot_sizing.fixed_lot)
      setLicenseKey(config.license_key)
    }
  }, [config])

  async function saveConfig(patch: Partial<Config>) {
    if (!config) return
    const updated: Config = { ...config, ...patch }
    if (patch.lot_sizing) updated.lot_sizing = { ...config.lot_sizing, ...patch.lot_sizing }
    setError(null)
    try {
      await updateConfig(updated)
      onConfigSaved(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    }
  }

  async function handleLotModeChange(mode: string) {
    setLotMode(mode)
    await saveConfig({ lot_sizing: { ...config!.lot_sizing, mode } })
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
    try {
      await shutdownEngine()
    } catch { /* connection will drop */ }
  }

  const isActive = status?.trading_active ?? false
  const mt5Ok = status?.mt5_connected ?? false
  const supaOk = status?.supabase_connected ?? false
  const licenseOk = status?.license_valid ?? false

  return (
    <div className="page settings-page">
      <section className="settings-section">
        <h3 className="section-title">Connection Status</h3>
        <div className="status-grid">
          <StatusRow label="MT5" ok={mt5Ok} />
          <StatusRow label="Supabase" ok={supaOk} />
          <StatusRow label="License" ok={licenseOk} />
        </div>
      </section>

      <section className="settings-section">
        <h3 className="section-title">License</h3>
        <div className="settings-row">
          <input
            type="text"
            value={licenseKey}
            placeholder="License key"
            className="settings-input"
            onChange={e => setLicenseKey(e.target.value)}
            onBlur={() => saveConfig({ license_key: licenseKey })}
          />
        </div>
      </section>

      <section className="settings-section">
        <h3 className="section-title">Lot Sizing</h3>
        <div className="settings-row" style={{ gap: 20 }}>
          <label className="radio-label">
            <input
              type="radio"
              value="risk_percent"
              checked={lotMode === 'risk_percent'}
              onChange={() => handleLotModeChange('risk_percent')}
            />
            Risk %
          </label>
          <label className="radio-label">
            <input
              type="radio"
              value="fixed"
              checked={lotMode === 'fixed'}
              onChange={() => handleLotModeChange('fixed')}
            />
            Fixed
          </label>
        </div>
        {lotMode === 'risk_percent' ? (
          <div className="settings-row">
            <span className="settings-label">Risk %</span>
            <input
              type="number"
              value={riskPct}
              min={0.01}
              step={0.1}
              className="settings-input-sm"
              onChange={e => setRiskPct(parseFloat(e.target.value))}
              onBlur={() => saveConfig({ lot_sizing: { ...config!.lot_sizing, risk_percent: riskPct } })}
            />
          </div>
        ) : (
          <div className="settings-row">
            <span className="settings-label">Fixed lot</span>
            <input
              type="number"
              value={fixedLot}
              min={0.01}
              step={0.01}
              className="settings-input-sm"
              onChange={e => setFixedLot(parseFloat(e.target.value))}
              onBlur={() => saveConfig({ lot_sizing: { ...config!.lot_sizing, fixed_lot: fixedLot } })}
            />
          </div>
        )}
      </section>

      <section className="settings-section">
        <h3 className="section-title">Engine</h3>
        <div className="settings-row" style={{ gap: 12 }}>
          <button
            className={`btn ${isActive ? 'btn-danger' : 'btn-primary'}`}
            onClick={handleEngineToggle}
            disabled={busy}
          >
            {busy ? '...' : isActive ? 'Stop Trading' : 'Start Trading'}
          </button>
          {!showShutdownConfirm ? (
            <button
              className="btn btn-shutdown"
              onClick={() => setShowShutdownConfirm(true)}
            >
              Shutdown Bot
            </button>
          ) : (
            <div className="shutdown-confirm">
              <span>Shut down the entire bot?</span>
              <button className="btn btn-danger" onClick={handleShutdown}>Yes, shut down</button>
              <button className="btn btn-neutral" onClick={() => setShowShutdownConfirm(false)}>Cancel</button>
            </div>
          )}
        </div>
      </section>

      {error && <p className="error-msg">{error}</p>}
    </div>
  )
}

function StatusRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="status-row">
      <span className={`dot-sm ${ok ? 'green' : 'red'}`} />
      <span>{label}</span>
      <span className="muted">{ok ? 'Connected' : 'Disconnected'}</span>
    </div>
  )
}
