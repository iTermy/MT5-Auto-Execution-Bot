const CHANNEL_NAMES: Record<string, string> = {
  '1100964697550889040': 'Daily Setup',
  '1199297150161526874': 'Scalps',
  '1097881491494666360': 'Forex Exotics',
  '1155216376286416998': 'Gold',
  '1155216316010078301': 'Oil',
  '1155489797025058896': 'Indices',
  '1097968916984242208': 'Crypto',
  '1098550430960722051': 'Stocks',
  '1137136940714573925': 'Swings',
  '1286732751067676762': 'OT Calls',
  '1362256516371058718': 'Proper Calls',
  '1347531759591358464': 'Crypto Alts',
  '1162112450934612079': 'Price Action',
  '1395599935101206630': 'Gold PA',
  '1468625458252873931': 'Gold Tolls',
  '1477103720390197248': 'General Tolls',
  '1483856749936115742': 'Oil Tolls',
  '1499065407342903296': 'Legends',
  '1506112997938958537': 'Gold 1-1',
}

export function getChannelName(channelId: string | null | undefined): string {
  if (!channelId) return 'Unknown'
  return CHANNEL_NAMES[channelId] ?? 'Unknown'
}
