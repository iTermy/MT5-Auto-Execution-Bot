const PATHS: Record<string, string> = {
  spark: 'M12 2.6l2.1 6.1 6.3.2-5 3.8 1.8 6-5.2-3.5-5.2 3.5 1.8-6-5-3.8 6.3-.2z',
  dashboard: 'M4 4h7v9H4zM13 4h7v5h-7zM13 11h7v9h-7zM4 15h7v5H4z',
  history: 'M12 7v5l3.5 2 M3.05 11a9 9 0 1 1 .5 4 M3 15v-4h4',
  settings: 'M4 7h10 M18 7h2 M4 17h2 M10 17h10 M14 5v4 M8 15v4',
  logs: 'M4 5h16v14H4z M7 9l3 3-3 3 M13 15h4',
  bell: 'M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6 M10 20a2 2 0 0 0 4 0',
  power: 'M12 4v8 M7.5 7a7 7 0 1 0 9 0',
  search: 'M11 11m-7 0a7 7 0 1 0 14 0a7 7 0 1 0-14 0 M20 20l-3.5-3.5',
  cal: 'M5 5h14v15H5z M5 9h14 M9 3v4 M15 3v4',
  plus: 'M12 5v14 M5 12h14',
  x: 'M6 6l12 12 M18 6L6 18',
  chevDown: 'M6 9l6 6 6-6',
  arrowUpRight: 'M7 17L17 7 M8 7h9v9',
  check: 'M5 12l4.5 4.5L19 7',
}

interface IconProps {
  name: string
  size?: number
  strokeWidth?: number
  style?: React.CSSProperties
}

export function Icon({ name, size = 22, strokeWidth = 1.8, style }: IconProps) {
  const path = PATHS[name]
  if (!path) return null
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
    >
      {path.split(/(?=M)/).map((d, i) => (
        <path key={i} d={d.trim()} />
      ))}
    </svg>
  )
}
