import { useState, useEffect } from 'react'

interface DonutProps {
  pct: number
  size?: number
  strokeW?: number
}

export function Donut({ pct, size = 160, strokeW = 13 }: DonutProps) {
  const r = size / 2 - strokeW / 2 - 2
  const c = size / 2
  const circ = 2 * Math.PI * r
  const [draw, setDraw] = useState(0)

  useEffect(() => {
    const t = setTimeout(() => setDraw(pct), 60)
    return () => clearTimeout(t)
  }, [pct])

  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size }}>
      <circle cx={c} cy={c} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={strokeW} />
      <circle
        cx={c}
        cy={c}
        r={r}
        fill="none"
        stroke="var(--accent)"
        strokeWidth={strokeW}
        strokeLinecap="round"
        strokeDasharray={`${(draw / 100) * circ} ${circ}`}
        transform={`rotate(-90 ${c} ${c})`}
        style={{ transition: 'stroke-dasharray 1s cubic-bezier(.4,0,.2,1)' }}
      />
      <text
        x={c}
        y={c - 2}
        textAnchor="middle"
        fontSize="30"
        fontWeight="700"
        fill="var(--text)"
        fontFamily="var(--font)"
      >
        {Math.round(pct)}%
      </text>
      <text
        x={c}
        y={c + 18}
        textAnchor="middle"
        fontSize="11"
        fill="var(--text-3)"
        fontFamily="var(--font)"
        letterSpacing="0.06em"
      >
        WIN RATE
      </text>
    </svg>
  )
}
