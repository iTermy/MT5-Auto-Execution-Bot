const CHANNEL_NAMES: Record<string, string> = {
  '1402971916339380244': 'Daily Setup',
  '1402971964343320636': 'Scalps',
  '1402972132920787077': 'Forex Exotics',
  '1402972164256432220': 'Gold',
  '1402972289993019463': 'Oil',
  '1402972348193177745': 'Indices',
  '1402972426014429254': 'Crypto',
  '1402972455990984774': 'Stocks',
  '1402972635847200838': 'Swings',
  '1402972674082476102': 'OT Calls',
  '1406127169448575098': 'Proper Calls',
  '1403532013511905434': 'Crypto Alts',
  '1402972075446239303': 'Price Action',
  '1402972221953019986': 'Gold PA',
  '1472685381315989730': 'Gold Tolls',
  '1477339674166169911': 'General Tolls',
  '1484316173515489392': 'Oil Tolls',
  '1500246110491639818': 'Legends',
}

export function getChannelName(channelId: string | null | undefined): string {
  if (!channelId) return 'Unknown'
  return CHANNEL_NAMES[channelId] ?? 'Unknown'
}
