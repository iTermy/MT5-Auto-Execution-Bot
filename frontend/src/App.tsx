import { useState, useEffect } from 'react'
import { fetchConfig } from './api'
import { useSSE } from './hooks/useSSE'
import { useDashboard } from './hooks/useDashboard'
import { NavSidebar } from './components/NavSidebar'
import { TopBar } from './components/TopBar'
import { LogDrawer } from './components/LogDrawer'
import { DashboardPage } from './pages/DashboardPage'
import { HistoryPage } from './pages/HistoryPage'
import { SettingsPage } from './pages/SettingsPage'
import type { Config, Page } from './types'

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [logOpen, setLogOpen] = useState(false)
  const [config, setConfig] = useState<Config | null>(null)
  const { logs, status, connected } = useSSE()
  const dashboard = useDashboard()

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {})
  }, [])

  return (
    <div className="app-layout">
      <NavSidebar
        page={page}
        onNavigate={setPage}
        logOpen={logOpen}
        onToggleLog={() => setLogOpen(!logOpen)}
      />
      <div className="main-area">
        <TopBar dashboard={dashboard} status={status} connected={connected} />
        <div className={`page-container${logOpen ? ' with-log' : ''}`}>
          {page === 'dashboard' && <DashboardPage dashboard={dashboard} />}
          {page === 'history' && <HistoryPage />}
          {page === 'settings' && (
            <SettingsPage config={config} status={status} onConfigSaved={setConfig} />
          )}
        </div>
        {logOpen && <LogDrawer logs={logs} onClose={() => setLogOpen(false)} />}
      </div>
    </div>
  )
}
