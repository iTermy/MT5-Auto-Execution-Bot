import { useState, useMemo } from 'react'

export function useSort<T extends Record<string, unknown>>(rows: T[], initKey: keyof T & string, initDir: 'asc' | 'desc' = 'desc') {
  const [key, setKey] = useState(initKey)
  const [dir, setDir] = useState(initDir)

  const sorted = useMemo(() => {
    const r = [...rows]
    r.sort((a, b) => {
      let x = a[key] as string | number
      let y = b[key] as string | number
      if (typeof x === 'string') { x = x.toLowerCase(); y = (y as string).toLowerCase() }
      if (x < y) return dir === 'asc' ? -1 : 1
      if (x > y) return dir === 'asc' ? 1 : -1
      return 0
    })
    return r
  }, [rows, key, dir])

  const onSort = (k: keyof T & string) => {
    if (k === key) setDir(dir === 'asc' ? 'desc' : 'asc')
    else { setKey(k); setDir('desc') }
  }

  const ind = (k: keyof T & string) =>
    k === key ? <span className="ind">{dir === 'asc' ? '▲' : '▼'}</span> : null

  return { sorted, onSort, ind }
}
