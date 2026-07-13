import { CollapsibleSection } from './shared'

interface Props {
  open: boolean
  onToggle: () => void
  disableAutoTp: boolean
  setDisableAutoTp: (fn: (v: boolean) => boolean) => void
  volatilityGuard: boolean
  setVolatilityGuard: (fn: (v: boolean) => boolean) => void
  touch: () => void
}

export function MiscSection({
  open,
  onToggle,
  disableAutoTp,
  setDisableAutoTp,
  volatilityGuard,
  setVolatilityGuard,
  touch,
}: Props) {
  return (
    <CollapsibleSection head={<h3>Misc</h3>} open={open} onToggle={onToggle}>
      <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}>
        <input
          type="checkbox"
          checked={disableAutoTp}
          onChange={() => {
            setDisableAutoTp(v => !v)
            touch()
          }}
          style={{ accentColor: 'var(--accent)', width: 16, height: 16, marginTop: 2 }}
        />
        <span style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>Disable auto-TP</span>
          <span className="faint" style={{ fontSize: 12.5, maxWidth: 560 }}>
            The bot still places, updates, and cancels limits, but never trails or takes profit —
            you manage every exit. Once you fully close a signal, its remaining pending limits are
            cancelled automatically.
          </span>
        </span>
      </label>

      <label
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 10,
          cursor: 'pointer',
          marginTop: 16,
        }}
      >
        <input
          type="checkbox"
          checked={volatilityGuard}
          onChange={() => {
            setVolatilityGuard(v => !v)
            touch()
          }}
          style={{ accentColor: 'var(--accent)', width: 16, height: 16, marginTop: 2 }}
        />
        <span style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>Volatility guard</span>
          <span className="faint" style={{ fontSize: 12.5, maxWidth: 560 }}>
            React to sharp market moves like news mode: when the signal service flags volatility
            market-wide, all affected trades are cancelled and any open positions closed; when it
            flags specific currencies, only signals involving those currencies are gated. Crypto
            and 24-hour instruments are exempt.
          </span>
        </span>
      </label>
    </CollapsibleSection>
  )
}
