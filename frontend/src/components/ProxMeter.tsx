interface ProxMeterProps {
  pct: number
  label: string
}

export function ProxMeter({ pct, label }: ProxMeterProps) {
  return (
    <div className="prox">
      <div className="prox-track">
        <div className="prox-fill" style={{ width: pct + '%' }} />
      </div>
      <small>{label}</small>
    </div>
  )
}
