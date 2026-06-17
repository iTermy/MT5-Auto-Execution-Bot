import type { StatusData } from '../types'

interface Props {
  status: StatusData | null
  connected: boolean
  onConfirm: () => void
  onClose: () => void
}

export function UpdateModal({ status, connected, onConfirm, onClose }: Props) {
  const inProgress = status?.update_in_progress ?? false
  const progress = status?.update_progress ?? 0
  const error = status?.update_error
  const openCount = status?.open_count ?? 0
  const pendingCount = status?.pending_count ?? 0
  const hasOrders = openCount > 0 || pendingCount > 0
  // Once the install is underway and the connection drops, the bot is restarting.
  const restarting = inProgress && !connected

  return (
    <div className="modal-overlay" onClick={inProgress ? undefined : onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">
          {inProgress ? 'Updating' : `Update to version ${status?.update_version ?? ''}`}
        </div>

        {!inProgress && (
          <>
            {status?.update_notes && <p className="modal-notes">{status.update_notes}</p>}
            {hasOrders && (
              <div className="modal-warn">
                You have {openCount} open position{openCount === 1 ? '' : 's'} and {pendingCount}{' '}
                pending order{pendingCount === 1 ? '' : 's'}. The bot will close the dashboard and
                restart — open positions stay on MT5 and resume tracking after the restart.
              </div>
            )}
            <p className="modal-sub">
              The bot will download the new version, replace itself, and relaunch automatically.
            </p>
            <div className="modal-actions">
              <button className="btn ghost" onClick={onClose}>
                Cancel
              </button>
              <button className="btn primary" onClick={onConfirm}>
                Update and restart
              </button>
            </div>
          </>
        )}

        {inProgress && !error && (
          <>
            <div className="modal-progress">
              <div className="modal-progress-bar" style={{ width: `${progress}%` }} />
            </div>
            <p className="modal-sub">
              {restarting ? 'Restarting — reconnecting…' : `Downloading… ${progress}%`}
            </p>
          </>
        )}

        {error && (
          <>
            <div className="modal-warn">Update failed: {error}</div>
            <div className="modal-actions">
              <button className="btn ghost" onClick={onClose}>
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
