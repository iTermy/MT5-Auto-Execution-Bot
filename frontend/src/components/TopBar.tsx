import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon'
import { fmtBalance, money } from '../utils/money'
import { deriveConnStatuses, CONN_CLASS } from '../utils/connStatus'
import type { DashboardData, StatusData } from '../types'

interface Props {
  dashboard: DashboardData | null
  status: StatusData | null
  connected: boolean
  engineRunning: boolean
  onEngineToggle: () => void
  onShutdown: () => void
  onUpdate: () => void
}

export function TopBar({
  dashboard,
  status,
  connected,
  engineRunning,
  onEngineToggle,
  onShutdown,
  onUpdate,
}: Props) {
  const acct = dashboard?.account
  const totalProfit = dashboard?.summary?.total_profit ?? 0
  const conns = deriveConnStatuses(status, connected)

  const [stopMenuOpen, setStopMenuOpen] = useState(false)
  const stopMenuRef = useRef<HTMLDivElement | null>(null)

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

  function handleToggleClick() {
    if (engineRunning) {
      setStopMenuOpen(o => !o)
    } else {
      onEngineToggle()
    }
  }

  function handlePauseClick() {
    setStopMenuOpen(false)
    onEngineToggle()
  }

  function handleShutdownClick() {
    setStopMenuOpen(false)
    onShutdown()
  }

  function handleUpdateClick() {
    setStopMenuOpen(false)
    onUpdate()
  }

  const updateAvailable = status?.update_available ?? false

  return (
    <header className="topbar">
      <div className="tb-title">
        <span className="t">Auto-Execution Bot</span>
        {status?.bot_version && <span className="s">Version {status.bot_version}</span>}
        <span className="s">
          {acct?.company || acct?.server || 'MT5'}
          {acct ? ` · #${acct.login}` : ''}
          {acct && acct.hedging === false && (
            <span
              className="s"
              style={{ color: 'var(--neg, #c0392b)' }}
              title="Account is not in hedging mode — position tracking assumes hedging"
            >
              {' '}
              · netting
            </span>
          )}
        </span>
      </div>
      <div className="divider-v" />
      <div className="tb-figs">
        <div className="tb-fig">
          <span className="l">Balance</span>
          <span className="v mono">{acct ? fmtBalance(acct.balance) : '—'}</span>
        </div>
        <div className="tb-fig">
          <span className="l">Equity</span>
          <span className="v mono">{acct ? fmtBalance(acct.equity) : '—'}</span>
        </div>
        <div className="tb-fig">
          <span className="l">Unrealized P&L</span>
          <span className={`v mono ${totalProfit >= 0 ? 'pos' : 'neg'}`}>
            {acct ? money(totalProfit) : '—'}
          </span>
        </div>
        {updateAvailable && (
          <button
            className="tb-update-cta"
            onClick={onUpdate}
            title={`Version ${status?.update_version} available — click to update`}
          >
            <span className="d" /> Update available
          </button>
        )}
      </div>
      <div className="tb-right">
        <div className="conns">
          <div className={`conn ${CONN_CLASS[conns.mt5.state]}`} title={conns.mt5.detail}>
            <span className="d" /> MT5
          </div>
          <div className={`conn ${CONN_CLASS[conns.database.state]}`} title={conns.database.detail}>
            <span className="d" /> Database
          </div>
          <div className={`conn ${CONN_CLASS[conns.license.state]}`} title={conns.license.detail}>
            <span className="d" /> License
          </div>
        </div>
        <div className="divider-v" />
        <div className={'engine' + (engineRunning ? '' : ' stopped')}>
          <span className="stat">
            <span className="d" /> {engineRunning ? 'Running' : 'Stopped'}
          </span>
          <div className="tb-stop" ref={stopMenuRef}>
            <button className="toggle" onClick={handleToggleClick}>
              <Icon name="power" size={13} strokeWidth={2.4} />
              {engineRunning ? 'Stop' : 'Start'}
              {engineRunning && (
                <Icon
                  name="chevDown"
                  size={11}
                  strokeWidth={2.6}
                  style={{ marginLeft: -1, opacity: 0.85 }}
                />
              )}
            </button>
            {stopMenuOpen && (
              <div className="tb-stop-menu">
                <button
                  className="item"
                  onClick={handlePauseClick}
                  title="Freeze new placements but keep TP/trailing running for open positions"
                >
                  Pause bot
                </button>
                <button
                  className="item danger"
                  onClick={handleShutdownClick}
                  title="Stop all loops and exit the bot process"
                >
                  Shutdown
                </button>
                {updateAvailable && (
                  <button
                    className="item accent"
                    onClick={handleUpdateClick}
                    title="Download the latest version and restart"
                  >
                    Update and restart
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
