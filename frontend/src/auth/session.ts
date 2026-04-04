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
    throw new Error(data?.detail || 'Login failed')
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
