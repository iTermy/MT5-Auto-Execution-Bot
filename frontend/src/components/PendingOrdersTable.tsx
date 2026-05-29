import { useState } from 'react'
import type { PendingOrderData } from '../types'

interface Props {
  orders: PendingOrderData[]
}

type SortKey = 'symbol' | 'direction' | 'volume' | 'price_level' | 'current_price' | 'distance' | 'sl'

export function PendingOrdersTable({ orders }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('distance')
  const [sortAsc, setSortAsc] = useState(true)

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc(!sortAsc)
    } else {
      setSortKey(key)
      setSortAsc(key === 'symbol' || key === 'distance')
    }
  }

  const sorted = [...orders].sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey]
    const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number)
    return sortAsc ? cmp : -cmp
  })

  return (
    <div className="table-section">
      <h3 className="section-title">
        Pending Orders
        <span className="section-count">{orders.length}</span>
      </h3>
      {orders.length === 0 ? (
        <p className="muted">No pending orders</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <Th label="Symbol" sortKey="symbol" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <Th label="Dir" sortKey="direction" current={sortKey} asc={sortAsc} onClick={handleSort} />
              <Th label="Volume" sortKey="volume" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="Price" sortKey="price_level" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="Current" sortKey="current_price" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="Distance" sortKey="distance" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
              <Th label="SL" sortKey="sl" current={sortKey} asc={sortAsc} onClick={handleSort} align="right" />
            </tr>
          </thead>
          <tbody>
            {sorted.map(o => (
              <tr key={o.ticket}>
                <td>{o.symbol}</td>
                <td className={o.direction === 'long' ? 'positive' : 'negative'}>{o.direction.toUpperCase()}</td>
                <td className="num">{o.volume.toFixed(2)}</td>
                <td className="num">{o.price_level.toFixed(5)}</td>
                <td className="num">{o.current_price.toFixed(5)}</td>
                <td className="num">{o.distance.toFixed(5)}</td>
                <td className="num">{o.sl.toFixed(5)}</td>
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
