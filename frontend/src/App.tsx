import { useState, useEffect } from 'react'
import { fetchConfig, startEngine, stopEngine, shutdownEngine, installUpdate } from './api'
import { useSSE } from './hooks/useSSE'
import { useDashboard } from './hooks/useDashboard'
import { useHistory } from './hooks/useHistory'
import { NavSidebar } from './components/NavSidebar'
import { TopBar } from './components/TopBar'
import { UpdateModal } from './components/UpdateModal'
import { LogDrawer } from './components/LogDrawer'
import { DashboardPage } from './pages/DashboardPage'
import { HistoryPage } from './pages/HistoryPage'
import { SettingsPage } from './pages/SettingsPage'
import type { Config, Page } from './types'

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [logOpen, setLogOpen] = useState(false)
  const [config, setConfig] = useState<Config | null>(null)
  const [updateModalOpen, setUpdateModalOpen] = useState(false)
  const { logs, status, connected } = useSSE()
  const dashboard = useDashboard()
  const history = useHistory(5000)

  const engineRunning = status?.trading_active ?? false

  useEffect(() => {
    fetchConfig()
      .then(setConfig)
      .catch(() => {})
  }, [])

  async function handleEngineToggle() {
    try {
      if (engineRunning) await stopEngine()
      else await startEngine()
    } catch {
      /* status SSE will update */
    }
  }

  async function handleShutdown() {
    try {
      await shutdownEngine()
    } catch {
      /* connection will drop */
    }
  }

  async function handleConfirmUpdate() {
    try {
      await installUpdate()
    } catch {
      /* progress/errors arrive over the status SSE */
    }
  }

  // Keep the modal up while an install is mid-flight even if the user didn't open it.
  const showUpdateModal = updateModalOpen || (status?.update_in_progress ?? false)

  return (
    <div className="app">
      <TopBar
        dashboard={dashboard}
        status={status}
        connected={connected}
        engineRunning={engineRunning}
        onEngineToggle={handleEngineToggle}
        onShutdown={handleShutdown}
        onUpdate={() => setUpdateModalOpen(true)}
      />
      {showUpdateModal && (
        <UpdateModal
          status={status}
          connected={connected}
          onConfirm={handleConfirmUpdate}
          onClose={() => setUpdateModalOpen(false)}
        />
      )}
      {status?.shutdown_reason === 'netting_account' && (
        <div
          style={{
            background: 'rgba(192,57,43,0.1)',
            borderBottom: '1px solid rgba(192,57,43,0.35)',
            color: '#a32020',
            padding: '10px 20px',
            fontSize: 13.5,
            fontWeight: 600,
          }}
        >
          This MT5 account is in netting mode. The bot requires a hedging account and will not trade
          — switch to a hedging account and restart.
        </div>
      )}
      <div className="app-body">
        <NavSidebar
          page={page}
          onNavigate={setPage}
          logOpen={logOpen}
          onToggleLog={() => setLogOpen(!logOpen)}
        />
        <div className="main">
          <div className="content">
            {page === 'dashboard' && (
              <DashboardPage
                dashboard={dashboard}
                history={history}
                config={config}
                onNavigate={setPage}
              />
            )}
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
