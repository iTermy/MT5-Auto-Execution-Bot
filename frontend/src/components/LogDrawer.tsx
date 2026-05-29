import { useEffect, useRef } from 'react'
import type { LogEntry } from '../types'

interface Props {
  logs: LogEntry[]
  onClose: () => void
}

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: '#6b7280',
  INFO: '#9ca3af',
  WARNING: '#f59e0b',
  ERROR: '#ef4444',
  CRITICAL: '#ef4444',
}

export function LogDrawer({ logs, onClose }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <div className="log-drawer">
      <div className="log-drawer-header">
        <span className="log-drawer-title">Logs</span>
        <span className="log-drawer-count">{logs.length}</span>
        <button className="log-close-btn" onClick={onClose} title="Close logs">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
          </svg>
        </button>
      </div>
      <div className="log-drawer-body">
        {logs.length === 0 && <span className="muted">No log output yet.</span>}
        {logs.map((entry, i) => (
          <div key={i} className="log-line" style={{ color: LEVEL_COLORS[entry.level] ?? '#9ca3af' }}>
            <span className="log-ts">{entry.timestamp.slice(11, 19)}</span>
            <span className="log-level">{entry.level}</span>
            {entry.message}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
