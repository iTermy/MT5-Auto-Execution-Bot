import { useState, useEffect } from 'react'
import { updateConfig } from '../api'
import type { Config, StatusData } from '../types'

interface Props {
  config: Config | null
  status: StatusData | null
  onConfigSaved: (config: Config) => void
}

export function LicensePanel({ config, status, onConfigSaved }: Props) {
  const [key, setKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (config) setKey(config.license_key)
  }, [config])

  async function handleValidate() {
    if (!config) return
    const updated = { ...config, license_key: key }
    setSaving(true)
    setError(null)
    try {
      await updateConfig(updated)
      onConfigSaved(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const isValid = status?.license_valid ?? false

  return (
    <div className="panel">
      <h2>License</h2>
      <div className="row">
        <span className={`dot ${isValid ? 'green' : 'red'}`} />
        <span style={{ color: isValid ? '#22c55e' : '#ef4444' }}>
          {isValid ? 'Valid' : 'Invalid'}
        </span>
      </div>
      <div className="row">
        <input
          type="text"
          value={key}
          onChange={e => setKey(e.target.value)}
          placeholder="License key"
          style={{ flex: 1 }}
        />
        <button
          className="btn btn-neutral"
          onClick={handleValidate}
          disabled={saving || !config}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
      {error && <span style={{ color: '#ef4444', fontSize: 12 }}>{error}</span>}
    </div>
  )
}
