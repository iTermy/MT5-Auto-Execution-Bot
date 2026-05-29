import { Icon } from './Icon'
import { fmtBalance, money } from '../utils/money'
import type { DashboardData, StatusData } from '../types'

interface Props {
  dashboard: DashboardData | null
  status: StatusData | null
  connected: boolean
  engineRunning: boolean
  onEngineToggle: () => void
}

export function TopBar({ dashboard, status, connected, engineRunning, onEngineToggle }: Props) {
  const acct = dashboard?.account
  const totalProfit = dashboard?.summary?.total_profit ?? 0
  const mt5Ok = status?.mt5_connected ?? false
  const supaOk = status?.supabase_connected ?? false
  const licenseOk = status?.license_valid ?? false

  return (
    <header className="topbar">
      <div className="tb-title">
        <span className="t">Auto-Execution Bot</span>
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
          <div className={`conn ${mt5Ok ? 'live' : 'off'}`}><span className="d" /> MT5</div>
          <div className={`conn ${supaOk ? 'live' : 'off'}`}><span className="d" /> Database</div>
          <div className={`conn ${licenseOk && connected ? 'live' : 'off'}`}><span className="d" /> License</div>
        </div>
        <div className="divider-v" />
        <div className={'engine' + (engineRunning ? '' : ' stopped')}>
          <span className="stat"><span className="d" /> {engineRunning ? 'Running' : 'Stopped'}</span>
          <button className="toggle" onClick={onEngineToggle}>
            <Icon name="power" size={13} strokeWidth={2.4} /> {engineRunning ? 'Stop' : 'Start'}
          </button>
        </div>
      </div>
    </header>
  )
}
