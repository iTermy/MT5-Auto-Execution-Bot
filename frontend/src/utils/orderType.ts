export function directionFromOrderType(dir: string): 'long' | 'short' {
  return dir.includes('buy') || dir.includes('long') ? 'long' : 'short'
}
