import { useState, useEffect } from 'react'
import { fetchConfig } from './api'
import { useSSE } from './hooks/useSSE'
import { StatusBar } from './components/StatusBar'
import { LicensePanel } from './components/LicensePanel'
import { ControlPanel } from './components/ControlPanel'
import { LogPanel } from './components/LogPanel'
import type { Config } from './types'

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const { logs, status, connected } = useSSE()

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {})
  }, [])

  return (
    <div className="app">
      <StatusBar status={status} connected={connected} />
      <div className="panels">
        <LicensePanel
          config={config}
          status={status}
          onConfigSaved={setConfig}
        />
        <ControlPanel
          config={config}
          status={status}
          onConfigSaved={setConfig}
        />
      </div>
      <LogPanel logs={logs} />
    </div>
  )
}
