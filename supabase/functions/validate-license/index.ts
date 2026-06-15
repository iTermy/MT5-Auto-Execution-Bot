// @ts-nocheck -- Supabase Edge Function runs on Deno; VS Code's TS server lacks Deno globals and remote-URL imports.
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

interface RequestBody {
  license_key?: string
  mt5_account?: number
}

interface LicenseRow {
  mt5_account: string
  status: string
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method !== 'POST') {
    return json({ status: 'error', expires_at: null, message: 'Method not allowed' }, 405)
  }

  let body: RequestBody
  try {
    body = await req.json()
  } catch {
    return json({ status: 'error', expires_at: null, message: 'Invalid JSON body' }, 400)
  }

  const { license_key, mt5_account } = body
  if (!license_key || mt5_account === undefined || mt5_account === null) {
    return json({ status: 'error', expires_at: null, message: 'Missing license_key or mt5_account' }, 400)
  }

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  )

  const { data, error } = await supabase
    .from('licenses')
    .select('mt5_account, status')
    .eq('license_key', license_key)
    .single<LicenseRow>()

  // A query error means the lookup failed (DB unreachable, pool exhausted, timeout),
  // NOT that the key is invalid. Surface it as a transient error (HTTP 500) so the bot
  // treats it as "couldn't determine" and never tears down a valid user. Only a
  // successful query that returns no row is a genuinely unknown key.
  if (error) {
    return json({ status: 'error', expires_at: null, message: 'License lookup failed' }, 500)
  }
  if (!data) {
    return json({ status: 'invalid', expires_at: null, message: 'Unknown license key' })
  }

  if (data.status === 'revoked') {
    return json({ status: 'invalid', expires_at: null, message: 'License revoked' })
  }

  if (Number(data.mt5_account) !== mt5_account) {
    return json({
      status: 'invalid',
      expires_at: null,
      message: `License is bound to MT5 account ${data.mt5_account}, but bot is connected to ${mt5_account}. Log into account ${data.mt5_account} in MT5.`,
    })
  }

  return json({ status: 'valid', expires_at: null, message: 'OK' })
})

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
