import { useState, useEffect, useRef } from 'react'
import type { LogEntry, StatusData } from '../types'

const MAX_LOGS = 500
const RECONNECT_DELAY_MS = 3000

export function useSSE() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [status, setStatus] = useState<StatusData | null>(null)
  const [connected, setConnected] = useState(false)

  const logSrcRef = useRef<EventSource | null>(null)
  const statusSrcRef = useRef<EventSource | null>(null)

  useEffect(() => {
    let logTimer: ReturnType<typeof setTimeout> | null = null
    let statusTimer: ReturnType<typeof setTimeout> | null = null
    let alive = true

    function connectLogs() {
      if (!alive) return
      const src = new EventSource('/api/logs')
      logSrcRef.current = src

      src.addEventListener('log', (e: MessageEvent) => {
        try {
          const entry = JSON.parse(e.data) as LogEntry
          setLogs(prev => [...prev.slice(-(MAX_LOGS - 1)), entry])
        } catch { /* malformed message — skip */ }
      })

      src.onerror = () => {
        src.close()
        if (alive) logTimer = setTimeout(connectLogs, RECONNECT_DELAY_MS)
      }
    }

    function connectStatus() {
      if (!alive) return
      const src = new EventSource('/api/status/stream')
      statusSrcRef.current = src

      src.addEventListener('status', (e: MessageEvent) => {
        try {
          setStatus(JSON.parse(e.data) as StatusData)
          setConnected(true)
        } catch { /* malformed message — skip */ }
      })

      src.onerror = () => {
        setConnected(false)
        src.close()
        if (alive) statusTimer = setTimeout(connectStatus, RECONNECT_DELAY_MS)
      }
    }

    connectLogs()
    connectStatus()

    return () => {
      alive = false
      if (logTimer) clearTimeout(logTimer)
      if (statusTimer) clearTimeout(statusTimer)
      logSrcRef.current?.close()
      statusSrcRef.current?.close()
    }
  }, [])

  return { logs, status, connected }
}
