import { CollapsibleSection } from './shared'
import type { OneToOneOverrideRow } from './shared'

interface Props {
  open: boolean
  onToggle: () => void
  oneToOneDefault: string
  setOneToOneDefault: (v: string) => void
  oneToOneRows: OneToOneOverrideRow[]
  updateOneToOneRow: (i: number, field: 'asset' | 'value', value: string) => void
  addOneToOneRow: () => void
  removeOneToOneRow: (i: number) => void
  touch: () => void
}

export function OneToOneSection({
  open,
  onToggle,
  oneToOneDefault,
  setOneToOneDefault,
  oneToOneRows,
  updateOneToOneRow,
  addOneToOneRow,
  removeOneToOneRow,
  touch,
}: Props) {
  return (
    <CollapsibleSection
      head={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <h3>1-1 fixed TP</h3>
          <span className="sub">
            1-1 trades always close at this $ amount · trailing disabled
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
          <label>Global TP ($)</label>
          <input
            className="inp num mono"
            value={oneToOneDefault}
            onChange={e => {
              setOneToOneDefault(e.target.value)
              touch()
            }}
            style={{ width: 100 }}
          />
        </div>
      </div>
      <table className="tbl" style={{ maxWidth: 460 }}>
        <thead>
          <tr>
            <th>Asset class</th>
            <th className="num">Override TP ($)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {oneToOneRows.map((r, i) => (
            <tr key={i}>
              <td>
                <input
                  className="inp mono"
                  value={r.asset}
                  onChange={e => updateOneToOneRow(i, 'asset', e.target.value)}
                  placeholder="forex, metals, …"
                  style={{ width: 150 }}
                />
              </td>
              <td className="num">
                <input
                  className="inp num mono"
                  value={r.value}
                  onChange={e => updateOneToOneRow(i, 'value', e.target.value)}
                  style={{ width: 88 }}
                />
              </td>
              <td style={{ width: 40 }}>
                <button className="btn sm ghost" onClick={() => removeOneToOneRow(i)}>
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={addOneToOneRow}>
        + Add asset override
      </button>
    </CollapsibleSection>
  )
}
