import { Icon } from './Icon'
import type { Page } from '../types'

interface Props {
  page: Page
  onNavigate: (page: Page) => void
  logOpen: boolean
  onToggleLog: () => void
}

export function NavSidebar({ page, onNavigate, logOpen, onToggleLog }: Props) {
  const item = (id: Page, icon: string) => (
    <button
      className={'nav-btn' + (page === id ? ' active' : '')}
      onClick={() => onNavigate(id)}
    >
      <Icon name={icon} />
      <span className="nav-tip">{id[0].toUpperCase() + id.slice(1)}</span>
    </button>
  )

  return (
    <aside className="rail">
      <div className="brand">
        <Icon name="spark" size={22} strokeWidth={0} style={{ fill: '#1a1410', stroke: '#1a1410', strokeWidth: 0.5 }} />
      </div>
      {item('dashboard', 'dashboard')}
      {item('history', 'history')}
      {item('settings', 'settings')}
      <div className="nav-sp" />
      <button className={'nav-btn' + (logOpen ? ' active' : '')} onClick={onToggleLog}>
        <Icon name="logs" />
        <span className="nav-tip">Logs</span>
      </button>
    </aside>
  )
}
