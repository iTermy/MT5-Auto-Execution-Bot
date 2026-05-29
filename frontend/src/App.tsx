import { useState, useEffect } from 'react'
import { fetchConfig, fetchHistory, startEngine, stopEngine } from './api'
import { useSSE } from './hooks/useSSE'
import { useDashboard } from './hooks/useDashboard'
import { NavSidebar } from './components/NavSidebar'
import { TopBar } from './components/TopBar'
import { LogDrawer } from './components/LogDrawer'
import { DashboardPage } from './pages/DashboardPage'
import { HistoryPage } from './pages/HistoryPage'
import { SettingsPage } from './pages/SettingsPage'
import type { Config, HistoryData, Page } from './types'

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [logOpen, setLogOpen] = useState(false)
  const [config, setConfig] = useState<Config | null>(null)
  const [history, setHistory] = useState<HistoryData | null>(null)
  const { logs, status, connected } = useSSE()
  const dashboard = useDashboard()

  const engineRunning = status?.trading_active ?? false

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {})
  }, [])

  useEffect(() => {
    fetchHistory().then(setHistory).catch(() => {})
  }, [])

  async function handleEngineToggle() {
    try {
      if (engineRunning) await stopEngine()
      else await startEngine()
    } catch { /* status SSE will update */ }
  }

  return (
    <div className="app">
      <TopBar
        dashboard={dashboard}
        status={status}
        connected={connected}
        engineRunning={engineRunning}
        onEngineToggle={handleEngineToggle}
      />
      <div className="app-body">
        <NavSidebar
          page={page}
          onNavigate={setPage}
          logOpen={logOpen}
          onToggleLog={() => setLogOpen(!logOpen)}
        />
        <div className="main">
          <div className="content">
            {page === 'dashboard' && <DashboardPage dashboard={dashboard} history={history} />}
            {page === 'history' && <HistoryPage />}
            {page === 'settings' && (
              <SettingsPage config={config} status={status} onConfigSaved={setConfig} />
            )}
          </div>
          <LogDrawer open={logOpen} onToggle={() => setLogOpen(!logOpen)} logs={logs} />
        </div>
      </div>
    </div>
  )
}
