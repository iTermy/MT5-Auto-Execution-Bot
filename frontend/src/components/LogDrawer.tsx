import { useEffect, useRef } from 'react'
import { Icon } from './Icon'
import type { LogEntry } from '../types'

interface Props {
  open: boolean
  onToggle: () => void
  logs: LogEntry[]
}

function levelClass(level: string): string {
  switch (level) {
    case 'INFO':
      return 'INFO'
    case 'WARNING':
      return 'WARNING'
    case 'ERROR':
    case 'CRITICAL':
      return 'ERROR'
    default:
      return 'INFO'
  }
}

function levelLabel(level: string): string {
  switch (level) {
    case 'WARNING':
      return 'WARN'
    case 'CRITICAL':
      return 'ERR'
    default:
      return level
  }
}

export function LogDrawer({ open, onToggle, logs }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs, open])

  return (
    <div className={'logdrawer' + (open ? ' open' : '')}>
      <div className="logdrawer-head">
        <span className="lab">
          <Icon name="logs" size={15} /> Activity log
        </span>
        <span className="pill">{logs.length} events</span>
        <button className="close" onClick={onToggle} aria-label="Close log">
          <Icon name="x" size={16} />
        </button>
      </div>
      <div className="logfeed">
        {logs.length === 0 && <span className="faint">No log output yet.</span>}
        {logs.map((l, i) => (
          <div className="logline" key={i}>
            <span className="ts">{l.timestamp.slice(11, 19)}</span>
            <span className={`lv ${levelClass(l.level)}`}>{levelLabel(l.level)}</span>
            <span className="msg">{l.message}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
