export function money(v: number, dp = 2): string {
  const sign = v >= 0 ? '+' : '−'
  return sign + '$' + Math.abs(v).toFixed(dp).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

export function fmtBalance(v: number): string {
  return '$' + v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}
