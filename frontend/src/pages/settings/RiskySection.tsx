import { CollapsibleSection } from './shared'

interface Props {
  open: boolean
  onToggle: () => void
  riskyTp: string
  setRiskyTp: (v: string) => void
  riskyTrail: string
  setRiskyTrail: (v: string) => void
  riskyPartial: string
  setRiskyPartial: (v: string) => void
  riskySl: string
  setRiskySl: (v: string) => void
  riskyWindows: string[]
  updateRiskyWindow: (i: number, value: string) => void
  addRiskyWindow: () => void
  removeRiskyWindow: (i: number) => void
  touch: () => void
}

export function RiskySection({
  open,
  onToggle,
  riskyTp,
  setRiskyTp,
  riskyTrail,
  setRiskyTrail,
  riskyPartial,
  setRiskyPartial,
  riskySl,
  setRiskySl,
  riskyWindows,
  updateRiskyWindow,
  addRiskyWindow,
  removeRiskyWindow,
  touch,
}: Props) {
  return (
    <CollapsibleSection
      head={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <h3>Risky</h3>
          <span className="sub">
            Trailing TP · custom stop-loss from the deepest limit · disabled in the UTC windows
            below
          </span>
        </div>
      }
      open={open}
      onToggle={onToggle}
    >
      <div
        style={{
          display: 'flex',
          gap: 28,
          alignItems: 'flex-end',
          flexWrap: 'wrap',
          marginBottom: 18,
        }}
      >
        <div className="field">
          <label>TP ($)</label>
          <input
            className="inp num mono"
            value={riskyTp}
            onChange={e => {
              setRiskyTp(e.target.value)
              touch()
            }}
            style={{ width: 100 }}
          />
        </div>
        <div className="field">
          <label>Trailing distance ($)</label>
          <input
            className="inp num mono"
            value={riskyTrail}
            onChange={e => {
              setRiskyTrail(e.target.value)
              touch()
            }}
            style={{ width: 100 }}
          />
        </div>
        <div className="field">
          <label>Partial close (%)</label>
          <input
            className="inp num mono"
            value={riskyPartial}
            onChange={e => {
              setRiskyPartial(e.target.value)
              touch()
            }}
            style={{ width: 100 }}
          />
        </div>
        <div className="field">
          <label>Custom SL ($ from deepest limit)</label>
          <input
            className="inp num mono"
            value={riskySl}
            onChange={e => {
              setRiskySl(e.target.value)
              touch()
            }}
            placeholder="DB default"
            style={{ width: 130 }}
          />
        </div>
      </div>
      <span className="sub" style={{ display: 'block', marginBottom: 18 }}>
        Leave Custom SL blank to use the stop-loss from the signal. When set, it applies to every
        limit measured from the deepest one (lowest for longs, highest for shorts).
      </span>
      <label style={{ display: 'block', marginBottom: 8, fontWeight: 600 }}>
        Disabled windows (UTC)
      </label>
      <table className="tbl" style={{ maxWidth: 320 }}>
        <thead>
          <tr>
            <th>Window (HH:MM-HH:MM)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {riskyWindows.map((w, i) => (
            <tr key={i}>
              <td>
                <input
                  className="inp mono"
                  value={w}
                  onChange={e => updateRiskyWindow(i, e.target.value)}
                  placeholder="21:55-23:10"
                  style={{ width: 180 }}
                />
              </td>
              <td style={{ width: 40 }}>
                <button className="btn sm ghost" onClick={() => removeRiskyWindow(i)}>
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={addRiskyWindow}>
        + Add window
      </button>
    </CollapsibleSection>
  )
}
