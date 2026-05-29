import { useState } from 'react'
import type { PositionData } from '../types'

interface Props {
  positions: PositionData[]
}

type SortKey = 'symbol' | 'direction' | 'volume' | 'price_open' | 'current_price' | 'profit' | 'sl'

export function PositionsTable({ positions }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('profit')
  const [sortAsc, setSortAsc] = useState(false)

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(key === 'symbol')
    }
  }

  const sorted = [...positions].sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey]
    const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number)
    return sortAsc ? cmp : -cmp
  })

  return (
    <div className="table-section">
      <h3 className="section-title">
        Open Positions
        <span className="section-count">{positions.length}</span>
      </h3>
      {positions.length === 0 ? (
        <p className="muted">No open positions</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <Th label="Symbol" sortKey="symbol" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <Th label="Dir" sortKey="direction" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <Th label="Volume" sortKey="volume" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="Open" sortKey="price_open" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="Current" sortKey="current_price" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="SL" sortKey="sl" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="P&L" sortKey="profit" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <th>Trail</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(pos => (
              <tr key={pos.ticket}>
                <td>{pos.symbol}</td>
                <td className={pos.direction === 'long' ? 'positive' : 'negative'}>{pos.direction.toUpperCase()}</td>
                <td className="num">{pos.volume.toFixed(2)}</td>
                <td className="num">{pos.price_open.toFixed(5)}</td>
                <td className="num">{pos.current_price.toFixed(5)}</td>
                <td className="num">{pos.sl.toFixed(5)}</td>
                <td className={`num ${pos.profit >= 0 ? 'positive' : 'negative'}`}>
                  {pos.profit >= 0 ? '+' : ''}{pos.profit.toFixed(2)}
                </td>
                <td>{pos.is_trailing ? 'Yes' : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function Th({ label, sortKey, current, asc, onClick, align }: {
  label: string
  sortKey: SortKey
  current: SortKey
  asc: boolean
  onClick: (key: SortKey) => void
  align?: string
}) {
  const arrow = current === sortKey ? (asc ? ' ▲' : ' ▼') : ''
  return (
    <th className={`sortable ${align === 'right' ? 'num' : ''}`} onClick={() => onClick(sortKey)}>
      {label}{arrow}
    </th>
  )
}
