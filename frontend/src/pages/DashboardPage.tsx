import { AccountMetrics } from '../components/AccountMetrics'
import { PositionsTable } from '../components/PositionsTable'
import { PendingOrdersTable } from '../components/PendingOrdersTable'
import type { DashboardData } from '../types'

interface Props {
  dashboard: DashboardData | null
}

export function DashboardPage({ dashboard }: Props) {
  return (
    <div className="page">
      <AccountMetrics
        account={dashboard?.account ?? null}
        summary={dashboard?.summary ?? null}
      />
      <PositionsTable positions={dashboard?.positions ?? []} />
      <PendingOrdersTable orders={dashboard?.pending_orders ?? []} />
    </div>
  )
}
