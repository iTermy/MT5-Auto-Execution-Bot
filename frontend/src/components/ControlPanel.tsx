import { useState, useEffect } from 'react'
import { startEngine, stopEngine, updateConfig } from '../api'
import type { Config, StatusData } from '../types'

interface Props {
  config: Config | null
  status: StatusData | null
  onConfigSaved: (config: Config) => void
}

export function ControlPanel({ config, status, onConfigSaved }: Props) {
  const [lotMode, setLotMode] = useState('risk_percent')
  const [riskPct, setRiskPct] = useState(1.0)
  const [fixedLot, setFixedLot] = useState(0.01)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (config) {
      setLotMode(config.lot_sizing.mode)
      setRiskPct(config.lot_sizing.risk_percent)
      setFixedLot(config.lot_sizing.fixed_lot)
    }
  }, [config])

  async function saveConfig(patch: Partial<Config['lot_sizing']>) {
    if (!config) return
    const updated: Config = {
      ...config,
      lot_sizing: { ...config.lot_sizing, ...patch },
    }
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
    await saveConfig({ mode })
  }

  async function handleEngineToggle() {
    setBusy(true)
    setError(null)
    try {
      if (status?.engine_running) {
        await stopEngine()
      } else {
        await startEngine()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  const isRunning = status?.engine_running ?? false
  const mt5Ok = status?.mt5_connected ?? false
  const supabaseOk = status?.supabase_connected ?? false

  return (
    <div className="panel">
      <h2>Engine</h2>

      <div className="row">
        <span className={`dot ${mt5Ok ? 'green' : 'red'}`} title="MT5 connection" />
        <span style={{ color: '#64748b' }}>MT5</span>
        <span className={`dot ${supabaseOk ? 'green' : 'red'}`} title="Supabase connection" style={{ marginLeft: 8 }} />
        <span style={{ color: '#64748b' }}>Supabase</span>
      </div>

      <button
        className={`btn ${isRunning ? 'btn-danger' : 'btn-primary'}`}
        onClick={handleEngineToggle}
        disabled={busy}
      >
        {busy ? '…' : isRunning ? 'Stop' : 'Start'}
      </button>

      <h2 style={{ marginTop: 4 }}>Lot Sizing</h2>

      <div className="row" style={{ gap: 16 }}>
        <label>
          <input
            type="radio"
            value="risk_percent"
            checked={lotMode === 'risk_percent'}
            onChange={() => handleLotModeChange('risk_percent')}
          />
          Risk %
        </label>
        <label>
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
        <div className="row">
          <span style={{ color: '#64748b' }}>Risk %</span>
          <input
            type="number"
            value={riskPct}
            min={0.01}
            step={0.1}
            style={{ width: 80 }}
            onChange={e => setRiskPct(parseFloat(e.target.value))}
            onBlur={() => saveConfig({ risk_percent: riskPct })}
          />
        </div>
      ) : (
        <div className="row">
          <span style={{ color: '#64748b' }}>Fixed lot</span>
          <input
            type="number"
            value={fixedLot}
            min={0.01}
            step={0.01}
            style={{ width: 80 }}
            onChange={e => setFixedLot(parseFloat(e.target.value))}
            onBlur={() => saveConfig({ fixed_lot: fixedLot })}
          />
        </div>
      )}

      {error && <span style={{ color: '#ef4444', fontSize: 12 }}>{error}</span>}
    </div>
  )
}
