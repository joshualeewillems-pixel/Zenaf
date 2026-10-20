export interface CurrentUser {
  id: string
  email: string
  display_name: string
  is_admin?: boolean
  avatar_data_url?: string | null
}

const AUTH_BASE = '/auth'

export async function getCurrentUser(): Promise<CurrentUser | null> {
  const res = await fetch(`${AUTH_BASE}/me`, {
    method: 'GET',
    credentials: 'include',
  })
  if (res.status === 401) return null
  if (!res.ok) {
    throw new Error(`Failed to load current user (${res.status})`)
  }
  return res.json()
}

export async function login(email: string, password: string): Promise<CurrentUser> {
  const res = await fetch(`${AUTH_BASE}/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const d = data?.detail
    const msg =
      typeof d === 'string'
        ? d
        : Array.isArray(d)
          ? d.map((x: unknown) => (typeof x === 'object' && x != null && 'msg' in x ? String((x as { msg: string }).msg) : String(x))).join('; ')
          : ''
    throw new Error(msg || 'Login failed')
  }
  return data.user as CurrentUser
}

export async function logout(): Promise<void> {
  const res = await fetch(`${AUTH_BASE}/logout`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!res.ok) {
    throw new Error('Logout failed')
  }
}

export async function patchCurrentUser(updates: {
  display_name?: string
  avatar_data_url?: string | null
}): Promise<CurrentUser> {
  const res = await fetch(`${AUTH_BASE}/me`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const d = data?.detail
    throw new Error(typeof d === 'string' ? d : Array.isArray(d) ? d[0]?.msg || 'Update failed' : 'Update failed')
  }
  return data as CurrentUser
}

export async function updateDisplayName(displayName: string): Promise<CurrentUser> {
  return patchCurrentUser({ display_name: displayName })
}

export interface InviteInfo {
  valid: boolean
  display_name?: string | null
}

export interface InviteCreated {
  code: string
  invite_url: string
  expires_at: number
}

function authError(data: unknown, fallback: string): string {
  const d = (data as { detail?: unknown })?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    return d
      .map((x: unknown) => (typeof x === 'object' && x != null && 'msg' in x ? String((x as { msg: string }).msg) : String(x)))
      .join('; ')
  }
  return fallback
}

export async function getInvite(code: string): Promise<InviteInfo> {
  const res = await fetch(`${AUTH_BASE}/invite/${encodeURIComponent(code)}`, {
    method: 'GET',
    credentials: 'include',
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(authError(data, 'Could not check this invite link'))
  }
  return data as InviteInfo
}

export async function signupWithInvite(input: {
  email: string
  password: string
  display_name: string
  invite_code: string
}): Promise<CurrentUser> {
  const res = await fetch(`${AUTH_BASE}/signup`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(authError(data, 'Signup failed'))
  }
  return data.user as CurrentUser
}

export async function createInvite(displayName?: string): Promise<InviteCreated> {
  const res = await fetch(`${AUTH_BASE}/admin/invites`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName ?? '' }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(authError(data, 'Could not create an invite link'))
  }
  return data as InviteCreated
}

export interface KeystoneSeedEntry {
  email: string | null
  created: boolean
  initiative_id: string
}

export interface KeystoneBackfillResult {
  ok: boolean
  seeded: KeystoneSeedEntry[]
}

export async function seedKeystones(): Promise<KeystoneBackfillResult> {
  const res = await fetch(`${AUTH_BASE}/admin/seed-keystones`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(authError(data, 'Could not run the keystone backfill'))
  }
  return data as KeystoneBackfillResult
}
