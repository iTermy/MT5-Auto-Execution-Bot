import { CHANNELS } from '../../utils/channels'
import {
  ASSET_CLASSES,
  ASSET_CLASS_LABELS,
  CollapsibleSection,
  LOT_SIGNAL_TYPES,
  SIGNAL_TYPES,
} from './shared'
import type { ExcludedChannelAssetRow, ExcludedTradeRow } from './shared'

interface Props {
  open: boolean
  onToggle: () => void
  excludedTrades: ExcludedTradeRow[]
  updateExcludedTrade: (i: number, field: 'symbol' | 'signalType', value: string) => void
  addExcludedTrade: () => void
  removeExcludedTrade: (i: number) => void
  excludedChannelAssets: ExcludedChannelAssetRow[]
  updateExcludedChannelAsset: (i: number, field: 'channel' | 'assetClass', value: string) => void
  addExcludedChannelAsset: () => void
  removeExcludedChannelAsset: (i: number) => void
  disabledSignalTypes: string[]
  disabledChannels: string[]
  toggleDisabled: (list: string[], setList: (v: string[]) => void, key: string) => void
  setDisabledSignalTypes: (v: string[]) => void
  setDisabledChannels: (v: string[]) => void
}

export function ExclusionsSection({
  open,
  onToggle,
  excludedTrades,
  updateExcludedTrade,
  addExcludedTrade,
  removeExcludedTrade,
  excludedChannelAssets,
  updateExcludedChannelAsset,
  addExcludedChannelAsset,
  removeExcludedChannelAsset,
  disabledSignalTypes,
  disabledChannels,
  toggleDisabled,
  setDisabledSignalTypes,
  setDisabledChannels,
}: Props) {
  return (
    <CollapsibleSection
      head={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <h3>Excluded trades</h3>
          <span className="sub">skip signals before they are ever placed</span>
        </div>
      }
      open={open}
      onToggle={onToggle}
    >
      <div className="panel-head" style={{ marginBottom: 6 }}>
        <h3 style={{ fontSize: 14 }}>By symbol</h3>
        <span className="sub">Use DB instrument (e.g. "SPX500USD" not "US500")</span>
      </div>
      {excludedTrades.length > 0 && (
        <table className="tbl" style={{ maxWidth: 520 }}>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Signal type</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {excludedTrades.map((r, i) => (
              <tr key={i}>
                <td>
                  <input
                    className="inp mono"
                    value={r.symbol}
                    onChange={e => updateExcludedTrade(i, 'symbol', e.target.value)}
                    placeholder="XAUUSD, BTCUSDT, …"
                    style={{ width: 180 }}
                  />
                </td>
                <td>
                  <select
                    className="inp"
                    value={r.signalType}
                    onChange={e => updateExcludedTrade(i, 'signalType', e.target.value)}
                    style={{ width: 130 }}
                  >
                    {LOT_SIGNAL_TYPES.map(t => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </td>
                <td style={{ width: 40 }}>
                  <button className="btn sm ghost" onClick={() => removeExcludedTrade(i)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button className="btn sm ghost" style={{ marginTop: 10 }} onClick={addExcludedTrade}>
        + Add exclusion
      </button>

      <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

      <div className="panel-head" style={{ marginBottom: 6 }}>
        <h3 style={{ fontSize: 14 }}>By channel &amp; asset</h3>
        <span className="sub">
          drop a channel's signals for a given asset class (e.g. indices from one channel) — leave
          a column on "All" to wildcard it
        </span>
      </div>
      {excludedChannelAssets.length > 0 && (
        <table className="tbl" style={{ maxWidth: 520 }}>
          <thead>
            <tr>
              <th>Channel</th>
              <th>Asset class</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {excludedChannelAssets.map((r, i) => (
              <tr key={i}>
                <td>
                  <select
                    className="inp"
                    value={r.channel}
                    onChange={e => updateExcludedChannelAsset(i, 'channel', e.target.value)}
                    style={{ width: 180 }}
                  >
                    <option value="">All channels</option>
                    {CHANNELS.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    className="inp"
                    value={r.assetClass}
                    onChange={e => updateExcludedChannelAsset(i, 'assetClass', e.target.value)}
                    style={{ width: 150 }}
                  >
                    <option value="">All assets</option>
                    {ASSET_CLASSES.map(a => (
                      <option key={a} value={a}>
                        {ASSET_CLASS_LABELS[a]}
                      </option>
                    ))}
                  </select>
                </td>
                <td style={{ width: 40 }}>
                  <button className="btn sm ghost" onClick={() => removeExcludedChannelAsset(i)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button
        className="btn sm ghost"
        style={{ marginTop: 10 }}
        onClick={addExcludedChannelAsset}
      >
        + Add exclusion
      </button>

      <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

      <div className="panel-head" style={{ marginBottom: 10 }}>
        <h3 style={{ fontSize: 14 }}>By signal type</h3>
        <span className="sub">unchecked types are skipped</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 26px' }}>
        {SIGNAL_TYPES.map(t => (
          <label
            key={t.value}
            style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
          >
            <span className="mono" style={{ fontSize: 13 }}>
              {t.label}
            </span>
            <input
              type="checkbox"
              checked={!disabledSignalTypes.includes(t.value)}
              onChange={() => toggleDisabled(disabledSignalTypes, setDisabledSignalTypes, t.value)}
              style={{ accentColor: 'var(--accent)', width: 16, height: 16 }}
            />
          </label>
        ))}
      </div>

      <div style={{ height: 1, background: 'var(--hairline)', margin: '20px 0' }} />

      <div className="panel-head" style={{ marginBottom: 10 }}>
        <h3 style={{ fontSize: 14 }}>By channel</h3>
        <span className="sub">unchecked channels are skipped</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 26px' }}>
        {CHANNELS.map(c => (
          <label
            key={c.id}
            style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
          >
            <span className="mono" style={{ fontSize: 13 }}>
              {c.name}
            </span>
            <input
              type="checkbox"
              checked={!disabledChannels.includes(c.id)}
              onChange={() => toggleDisabled(disabledChannels, setDisabledChannels, c.id)}
              style={{ accentColor: 'var(--accent)', width: 16, height: 16 }}
            />
          </label>
        ))}
      </div>
    </CollapsibleSection>
  )
}
