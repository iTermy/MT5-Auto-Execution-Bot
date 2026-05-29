import { useState, useRef, useId } from 'react'
import { smoothPath } from './smoothPath'
import { money } from '../utils/money'

interface EquityCurveProps {
  data: number[]
  labels?: string[]
  height?: number
}

export function EquityCurve({ data, labels, height = 210 }: EquityCurveProps) {
  const gid = useId().replace(/:/g, '')
  const wrapRef = useRef<HTMLDivElement>(null)
  const [hi, setHi] = useState<number | null>(null)

  if (data.length < 2) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <span className="faint">Not enough data</span>
      </div>
    )
  }

  const w = 720
  const h = height + 20
  const pad = 8
  const min = Math.min(...data)
  const max = Math.max(...data)
  const rng = max - min || 1
  const n = data.length

  const X = (i: number) => pad + (i * (w - pad * 2)) / (n - 1)
  const Y = (v: number) => h - pad - ((v - min) / rng) * (h - pad * 2 - 14) - 8
  const pts: [number, number][] = data.map((v, i) => [X(i), Y(v)])
  const line = smoothPath(pts)
  const area = `${line} L ${X(n - 1)},${h} L ${X(0)},${h} Z`

  const onMove = (e: React.MouseEvent) => {
    const r = wrapRef.current!.getBoundingClientRect()
    const fx = (e.clientX - r.left) / r.width
    setHi(Math.max(0, Math.min(n - 1, Math.round(fx * (n - 1)))))
  }

  const hxPct = hi != null ? (X(hi) / w) * 100 : 0
  const hyPct = hi != null ? (Y(data[hi]) / h) * 100 : 0

  return (
    <div
      ref={wrapRef}
      className="eqwrap"
      style={{ position: 'relative', height }}
      onMouseMove={onMove}
      onMouseLeave={() => setHi(null)}
    >
      <svg
        className="chart"
        viewBox={`0 0 ${w} ${h}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: '100%', display: 'block' }}
      >
        <defs>
          <linearGradient id={`g${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.32} />
            <stop offset="60%" stopColor="var(--accent)" stopOpacity={0.06} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map(g => (
          <line key={g} x1={pad} x2={w - pad} y1={h * g} y2={h * g} stroke="var(--hairline)" strokeWidth="1" />
        ))}
        <path d={area} fill={`url(#g${gid})`} />
        <path
          d={line}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2.4"
          strokeLinecap="round"
          pathLength={1}
          style={{ strokeDasharray: 1, strokeDashoffset: 1, animation: 'draw 1.1s ease forwards' }}
        />
        {hi == null && (
          <>
            <circle cx={X(n - 1)} cy={Y(data[n - 1])} r={4.5} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2.5} />
            <circle cx={X(n - 1)} cy={Y(data[n - 1])} r={4.5} fill="none" stroke="var(--accent)" strokeWidth={1.5} opacity={0.5}>
              <animate attributeName="r" from="4.5" to="11" dur="1.8s" repeatCount="indefinite" />
              <animate attributeName="opacity" from="0.5" to="0" dur="1.8s" repeatCount="indefinite" />
            </circle>
          </>
        )}
      </svg>
      {hi != null && (
        <>
          <div className="eq-guide" style={{ left: hxPct + '%' }} />
          <div className="eq-dot" style={{ left: hxPct + '%', top: hyPct + '%' }} />
          <div className="eq-tip" style={{ left: hxPct + '%', top: hyPct + '%' }}>
            {labels && labels[hi] && <div className="d mono">{labels[hi]}</div>}
            <div className="v">{money(data[hi])}</div>
          </div>
        </>
      )}
    </div>
  )
}
