import { Icon } from './Icon'

interface Props {
  connected: boolean
}

export function ShutdownOverlay({ connected }: Props) {
  // While still connected the teardown is in flight; once the SSE drops the
  // process is gone and the tab can be closed.
  const down = !connected

  return (
    <div className="shutdown-overlay">
      <div className="shutdown-card">
        {down ? (
          <>
            <div className="shutdown-mark">
              <Icon name="power" size={26} strokeWidth={2.2} />
            </div>
            <div className="shutdown-title">Bot has shut down</div>
            <p className="shutdown-sub">
              It’s now safe to close this tab. Open positions stay on MT5 — relaunch the bot to
              resume tracking them.
            </p>
            <button className="btn primary" onClick={() => window.close()}>
              Close tab
            </button>
          </>
        ) : (
          <>
            <div className="shutdown-spinner" />
            <div className="shutdown-title">Shutting down…</div>
            <p className="shutdown-sub">Stopping the bot and closing the dashboard.</p>
          </>
        )}
      </div>
    </div>
  )
}
