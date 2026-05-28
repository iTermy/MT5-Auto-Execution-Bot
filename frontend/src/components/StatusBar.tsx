import type { StatusData } from '../types'

interface Props {
  status: StatusData | null
  connected: boolean
}

export function StatusBar({ status, connected }: Props) {
  const s = status
  return (
    <div style={{
      background: '#161b27',
      border: '1px solid #2d3448',
      borderRadius: '6px',
      padding: '8px 14px',
      display: 'flex',
      alignItems: 'center',
      gap: '20px',
      fontSize: '13px',
    }}>
      <span style={{ fontWeight: 600, color: '#94a3b8', marginRight: 4 }}>
        MT5 Auto Execution Bot
      </span>
      <Stat label="Pending" value={s?.pending_count ?? 0} />
      <Stat label="Open" value={s?.open_count ?? 0} />
      <Stat label="Trailing" value={s?.trailing_count ?? 0} />
      <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          className={`dot ${connected ? 'green' : 'red'}`}
          title={connected ? 'UI connected' : 'UI disconnected'}
        />
        <span style={{ color: '#64748b' }}>{connected ? 'Connected' : 'Disconnected'}</span>
      </span>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <span style={{ color: '#64748b' }}>{label}:</span>
      <span style={{ fontWeight: 600 }}>{value}</span>
    </span>
  )
}
