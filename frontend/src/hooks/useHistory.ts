import { useState, useEffect } from 'react'
import { fetchHistory } from '../api'
import type { HistoryData } from '../types'

export function useHistory(intervalMs: number = 5000) {
  const [data, setData] = useState<HistoryData | null>(null)

  useEffect(() => {
    let alive = true
    async function poll() {
      try {
        const d = await fetchHistory()
        if (alive) setData(d)
      } catch {
        /* ignore */
      }
    }
    poll()
    const timer = setInterval(poll, intervalMs)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [intervalMs])

  return data
}
