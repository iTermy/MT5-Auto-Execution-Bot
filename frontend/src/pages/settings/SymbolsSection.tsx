import { CollapsibleSection, LOCKED_OFFSET_INSTRUMENTS, MultiClassPicker } from './shared'
import type { AssetKey, SuffixRuleRow, SymbolRow } from './shared'

interface Props {
  open: boolean
  onToggle: () => void
  symbolRows: SymbolRow[]
  updateSymbolRow: (i: number, field: 'db' | 'mt5', value: string) => void
  updateSymbolFeed: (i: number, feed: boolean) => void
  addSymbolRow: () => void
  removeSymbolRow: (i: number) => void
  isUnknownSymbol: (sym: string) => boolean
  stockSuffix: string
  setStockSuffix: (v: string) => void
  suffixRules: SuffixRuleRow[]
  updateSuffixRuleSuffix: (i: number, value: string) => void
  toggleSuffixRuleClass: (i: number, cls: AssetKey) => void
  addSuffixRule: () => void
  removeSuffixRule: (i: number) => void
  touch: () => void
}

export function SymbolsSection({
  open,
  onToggle,
  symbolRows,
  updateSymbolRow,
  updateSymbolFeed,
  addSymbolRow,
  removeSymbolRow,
  isUnknownSymbol,
  stockSuffix,
  setStockSuffix,
  suffixRules,
  updateSuffixRuleSuffix,
  toggleSuffixRuleClass,
  addSuffixRule,
  removeSuffixRule,
  touch,
}: Props) {
  return (
    <CollapsibleSection
      head={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <h3>Symbol mapping</h3>
          <span className="sub">DB instrument → your broker's MT5 symbol</span>
          <span className="sub">
            Offset feed for indices, oil &amp; crypto · direct feed for forex, metals &amp; stocks
          </span>
        </div>
      }
      open={open}
      onToggle={onToggle}
    >
      <table className="tbl" style={{ maxWidth: 680 }}>
        <thead>
          <tr>
            <th>DB instrument</th>
            <th />
            <th>MT5 symbol</th>
            <th>Feed</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {symbolRows.map((m, i) => {
            const locked = LOCKED_OFFSET_INSTRUMENTS.has(m.db.trim())
            return (
              <tr key={i}>
                <td>
                  <input
                    className="inp mono"
                    value={m.db}
                    onChange={e => updateSymbolRow(i, 'db', e.target.value)}
                    disabled={locked}
                    style={{ width: 150 }}
                  />
                </td>
                <td className="faint" style={{ width: 24, textAlign: 'center' }}>
                  →
                </td>
                <td>
                  <input
                    className="inp mono"
                    list="broker-symbols"
                    value={m.mt5}
                    onChange={e => updateSymbolRow(i, 'mt5', e.target.value)}
                    style={{
                      width: 150,
                      borderColor: isUnknownSymbol(m.mt5) ? 'var(--neg, #c0392b)' : undefined,
                    }}
                    title={
                      isUnknownSymbol(m.mt5)
                        ? 'Not found in this broker’s symbol list'
                        : undefined
                    }
                  />
                </td>
                <td>
                  <select
                    className="inp"
                    value={locked || m.feed ? 'offset' : 'direct'}
                    onChange={e => updateSymbolFeed(i, e.target.value === 'offset')}
                    disabled={locked}
                    title={locked ? 'Built-in default — feed type is fixed' : undefined}
                    style={{ width: 130 }}
                  >
                    <option value="offset">offset feed</option>
                    <option value="direct">direct feed</option>
                  </select>
                  {locked && (
                    <span className="tag ghost faint" style={{ marginLeft: 6 }}>
                      default
                    </span>
                  )}
                  {isUnknownSymbol(m.mt5) && (
                    <span
                      className="tag ghost"
                      style={{ color: 'var(--neg, #c0392b)', marginLeft: 6 }}
                    >
                      not found
                    </span>
                  )}
                </td>
                <td style={{ width: 40 }}>
                  {!locked && (
                    <button className="btn sm ghost" onClick={() => removeSymbolRow(i)}>
                      ×
                    </button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div style={{ marginTop: 14 }}>
        <button className="btn sm ghost" onClick={addSymbolRow}>
          + Add mapping
        </button>
      </div>
      <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />
      <div className="field" style={{ marginBottom: 0 }}>
        <label>Stock suffix</label>
        <input
          className="inp mono"
          value={stockSuffix}
          onChange={e => {
            setStockSuffix(e.target.value)
            touch()
          }}
          placeholder="-24"
          style={{ width: 120 }}
        />
        <span className="faint" style={{ fontSize: 12 }}>
          appended to .NAS / .NYSE stocks only
        </span>
      </div>

      <div style={{ marginTop: 22 }}>
        <div className="panel-head" style={{ marginBottom: 4 }}>
          <h3 style={{ fontSize: 14 }}>Broker suffixes</h3>
          <span className="sub">
            append a broker tag (e.g. Exness “m”) to chosen asset classes · each class can belong
            to one suffix
          </span>
        </div>
        {suffixRules.map((rule, i) => {
          const takenByOthers = new Set<AssetKey>(
            suffixRules.flatMap((r, j) => (j === i ? [] : r.classes))
          )
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 14,
                marginBottom: 10,
                flexWrap: 'wrap',
              }}
            >
              <input
                className="inp mono"
                value={rule.suffix}
                onChange={e => updateSuffixRuleSuffix(i, e.target.value)}
                placeholder="e.g. m"
                style={{ width: 90 }}
              />
              <span className="faint" style={{ fontSize: 12.5 }}>
                on
              </span>
              <MultiClassPicker
                selected={rule.classes}
                disabledClasses={takenByOthers}
                onToggle={cls => toggleSuffixRuleClass(i, cls)}
              />
              <button className="btn sm ghost" onClick={() => removeSuffixRule(i)}>
                ×
              </button>
            </div>
          )
        })}
        <button className="btn sm ghost" style={{ marginTop: 6 }} onClick={addSuffixRule}>
          + Add suffix
        </button>
      </div>
    </CollapsibleSection>
  )
}
