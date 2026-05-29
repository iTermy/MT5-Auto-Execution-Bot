import { useState } from 'react'
import { money } from '../utils/money'

interface BarData {
  date: string
  label: string
  value: number
}

interface BarsProps {
  data: BarData[]
  height?: number
}

export function Bars({ data, height = 172 }: BarsProps) {
  const [hi, setHi] = useState<number | null>(null)

  if (data.length === 0) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span className="faint">No daily P&L data</span>
      </div>
    )
  }

  const posMax = Math.max(0, ...data.map(d => d.value))
  const negMax = Math.max(0, ...data.map(d => -d.value))
  const span = (posMax + negMax) || 1
  const chartH = height - 4
  const ppx = chartH / span
  const zeroY = posMax * ppx
  const n = data.length

  return (
    <div className="bars">
      <div className="bars-plot" style={{ height: chartH }}>
        <div className="bars-zero" style={{ top: zeroY }} />
        {data.map((d, i) => {
          const barH = Math.max(2, Math.abs(d.value) * ppx)
          const up = d.value >= 0
          return (
            <div
              key={i}
              className="bars-col"
              onMouseEnter={() => setHi(i)}
              onMouseLeave={() => setHi(null)}
            >
              <div
                className="bars-bar"
                style={{
                  top: up ? zeroY - barH : zeroY,
                  height: barH,
                  background: up ? 'var(--accent)' : 'var(--neg)',
                  opacity: hi === null ? (up ? 0.92 : 0.82) : (hi === i ? 1 : 0.4),
                  transformOrigin: up ? 'bottom' : 'top',
                  animation: `grow .5s ${i * 0.03}s ease both`,
                }}
              />
            </div>
          )
        })}
      </div>
      <div className="bars-labels">
        {data.map((d, i) => (
          <span key={i} className="mono">{d.label}</span>
        ))}
      </div>
      {hi !== null && (
        <div
          className="bars-tip"
          style={{
            left: `${((hi + 0.5) / n) * 100}%`,
            top: (data[hi].value >= 0 ? zeroY - Math.max(2, data[hi].value * ppx) : zeroY) - 10,
          }}
        >
          <div className="d mono">{data[hi].date}</div>
          <div className="v" style={{ color: data[hi].value >= 0 ? 'var(--pos)' : 'var(--neg)' }}>
            {money(data[hi].value)}
          </div>
        </div>
      )}
    </div>
  )
}
