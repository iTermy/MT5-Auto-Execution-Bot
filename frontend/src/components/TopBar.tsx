import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon'
import { fmtBalance, money } from '../utils/money'
import type { DashboardData, StatusData } from '../types'

interface Props {
  dashboard: DashboardData | null
  status: StatusData | null
  connected: boolean
  engineRunning: boolean
  onEngineToggle: () => void
  onShutdown: () => void
}

export function TopBar({
  dashboard,
  status,
  connected,
  engineRunning,
  onEngineToggle,
  onShutdown,
}: Props) {
  const acct = dashboard?.account
  const totalProfit = dashboard?.summary?.total_profit ?? 0
  const mt5Ok = status?.mt5_connected ?? false
  const supaOk = status?.supabase_connected ?? false
  const licenseOk = status?.license_valid ?? false

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

  return (
    <header className="topbar">
      <div className="tb-title">
        <span className="t">Auto-Execution Bot</span>
        {status?.bot_version && <span className="s">v{status.bot_version}</span>}
        <span className="s">ICMarkets{acct ? ` · #${acct.login}` : ''}</span>
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
      </div>
      <div className="tb-right">
        <div className="conns">
          <div className={`conn ${mt5Ok ? 'live' : 'off'}`}>
            <span className="d" /> MT5
          </div>
          <div className={`conn ${supaOk ? 'live' : 'off'}`}>
            <span className="d" /> Database
          </div>
          <div
            className={`conn ${licenseOk && connected ? 'live' : 'off'}`}
            title={!licenseOk ? status?.license_message || undefined : undefined}
          >
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
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
