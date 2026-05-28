import { useEffect, useRef } from 'react'
import type { LogEntry } from '../types'

interface Props {
  logs: LogEntry[]
}

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: '#475569',
  INFO: '#94a3b8',
  WARNING: '#f59e0b',
  ERROR: '#ef4444',
  CRITICAL: '#ef4444',
}

export function LogPanel({ logs }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <div className="panel" style={{ flex: 1, minHeight: 0 }}>
      <h2>Logs</h2>
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          fontFamily: 'monospace',
          fontSize: 12,
          lineHeight: 1.6,
          display: 'flex',
          flexDirection: 'column',
          gap: 1,
          minHeight: 0,
        }}
      >
        {logs.length === 0 && (
          <span style={{ color: '#475569' }}>No log output yet.</span>
        )}
        {logs.map((entry, i) => (
          <div key={i} style={{ color: LEVEL_COLORS[entry.level] ?? '#94a3b8' }}>
            <span style={{ color: '#475569', marginRight: 8 }}>
              {entry.timestamp.slice(11, 19)}
            </span>
            <span style={{ marginRight: 8, minWidth: 60, display: 'inline-block' }}>
              {entry.level}
            </span>
            {entry.message}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
