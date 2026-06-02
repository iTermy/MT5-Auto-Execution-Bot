interface SegOption {
  value: string
  label: string
}

interface SegProps {
  value: string
  options: (string | SegOption)[]
  onChange: (value: string) => void
  accent?: boolean
}

export function Seg({ value, options, onChange, accent }: SegProps) {
  return (
    <div className={'seg' + (accent ? ' accent' : '')}>
      {options.map(o => {
        const v = typeof o === 'string' ? o : o.value
        const label = typeof o === 'string' ? o : o.label
        return (
          <button key={v} className={value === v ? 'on' : ''} onClick={() => onChange(v)}>
            {label}
          </button>
        )
      })}
    </div>
  )
}
