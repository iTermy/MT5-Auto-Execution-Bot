import { useState, useEffect } from 'react'
import { fetchDashboard } from '../api'
import type { DashboardData } from '../types'

export function useDashboard(intervalMs: number = 2000) {
  const [data, setData] = useState<DashboardData | null>(null)

  useEffect(() => {
    let alive = true
    async function poll() {
      try {
        const d = await fetchDashboard()
        if (alive) setData(d)
      } catch { /* ignore */ }
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
