import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon'
import type { SignalAction } from '../types'

interface Props {
  action: 'skip' | 'manual' | null
  placed: boolean
  onAction: (action: SignalAction) => void
}

export function SignalMenu({ action, placed, onAction }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  function pick(a: SignalAction) {
    setOpen(false)
    onAction(a)
  }

  const items =
    action === 'skip'
      ? [{ key: 'none' as const, label: 'Un-skip signal' }]
      : action === 'manual'
        ? [{ key: 'none' as const, label: 'Resume bot management' }]
        : [
            { key: 'skip' as const, label: 'Skip signal' },
            ...(placed ? [{ key: 'manual' as const, label: 'Handle manually' }] : []),
          ]

  return (
    <div className="signal-menu" ref={ref}>
      <button
        className="signal-menu-btn"
        onClick={() => setOpen(o => !o)}
        aria-label="Signal actions"
      >
        <Icon name="menu" size={16} />
      </button>
      {open && (
        <div className="signal-menu-drop">
          {items.map(it => (
            <button key={it.key} onClick={() => pick(it.key)}>
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
