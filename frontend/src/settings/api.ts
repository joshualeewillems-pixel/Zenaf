const BASE = '/settings'

export interface OpenAIExecutionInfo {
  env_key_present: boolean
  settings_key_saved: boolean
  effective_source: 'env' | 'settings' | 'none'
  status: 'no_key_configured' | 'env_override_active' | 'saved_key_available'
  note: string
}

export interface ProviderStatusRow {
  id: string
  display_name: string
  needs_api_key: boolean
  key_saved: boolean
  enabled: boolean
  configured: boolean
  available: boolean
  default_model: string
  test_status: 'never' | 'passed' | 'failed'
  last_test_at: string | null
  last_test_error: string | null
  status_message: string | null
}

export interface LLMSettingsResponse {
  default_provider: string
  default_model: string | null
  ollama_base_url: string | null
  ollama_model: string | null
  credentials_present: Record<string, boolean>
  encryption_configured: boolean
  providers?: ProviderStatusRow[]
  /** Persisted council seat id → provider id (excludes auto). */
  council_seat_providers?: Record<string, string>
  active_summary: { provider: string; model: string }
  openai_execution?: OpenAIExecutionInfo
}

export async function fetchLLMSettings(): Promise<LLMSettingsResponse> {
  const res = await fetch(`${BASE}/llm`, { credentials: 'include' })
  if (!res.ok) throw new Error('Failed to load LLM settings')
  return res.json()
}

export async function saveLLMProfile(body: {
  default_provider: string
  default_model: string | null
  ollama_base_url: string | null
  ollama_model: string | null
}): Promise<void> {
  const res = await fetch(`${BASE}/llm/profile`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error(d.detail || 'Save failed')
  }
}

export async function saveCredential(provider: string, apiKey: string): Promise<void> {
  const res = await fetch(`${BASE}/llm/credentials/${provider}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error(typeof d.detail === 'string' ? d.detail : 'Save key failed')
  }
}

export async function testLLM(provider: string, apiKey?: string, model?: string | null): Promise<{ ok: boolean; error?: string }> {
  // ai-trace-exempt: settings_llm_connectivity_test (see AI_ACTION_TRACE_EXEMPTS)
  const res = await fetch(`${BASE}/llm/test`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, api_key: apiKey || null, model: model || null }),
  })
  return res.json()
}

/** "Sign in with OpenRouter" (OAuth PKCE) helpers. */
export interface OpenRouterOAuthInitiateResult {
  auth_url: string
  code_verifier: string
  code_challenge: string
}

export async function initiateOpenRouterOAuth(callbackUrl: string): Promise<OpenRouterOAuthInitiateResult> {
  const res = await fetch(`${BASE}/llm/openrouter/oauth/initiate`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ callback_url: callbackUrl }),
  })
  const body = (await res.json().catch(() => ({}))) as Partial<OpenRouterOAuthInitiateResult> & {
    detail?: unknown
  }
  if (!res.ok || !body.auth_url || !body.code_verifier) {
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not start OpenRouter sign-in')
  }
  return body as OpenRouterOAuthInitiateResult
}

export async function exchangeOpenRouterOAuth(code: string, codeVerifier: string): Promise<void> {
  const res = await fetch(`${BASE}/llm/openrouter/oauth/exchange`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, code_verifier: codeVerifier }),
  })
  if (!res.ok) {
    const d = (await res.json().catch(() => ({}))) as { detail?: unknown }
    throw new Error(typeof d.detail === 'string' ? d.detail : 'OpenRouter sign-in failed')
  }
}

export async function updateProviderEnabled(provider: string, enabled: boolean): Promise<ProviderStatusRow[]> {
  const res = await fetch(`${BASE}/llm/providers/${encodeURIComponent(provider)}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error(typeof d.detail === 'string' ? d.detail : 'Update failed')
  }
  const body = (await res.json()) as { providers?: ProviderStatusRow[] }
  return body.providers ?? []
}

export async function fetchLLMProviders(): Promise<ProviderStatusRow[]> {
  const res = await fetch(`${BASE}/llm/providers`, { credentials: 'include' })
  if (!res.ok) throw new Error('Failed to load providers')
  const body = (await res.json()) as { providers?: ProviderStatusRow[] }
  return body.providers ?? []
}

export async function saveCouncilSeatLlm(seatId: string, llmProvider: string): Promise<Record<string, string>> {
  const res = await fetch(`${BASE}/llm/council-seats/${encodeURIComponent(seatId)}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ llm_provider: llmProvider }),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error(typeof d.detail === 'string' ? d.detail : 'Save failed')
  }
  const body = (await res.json()) as { council_seat_providers?: Record<string, string> }
  return body.council_seat_providers ?? {}
}

/** Canonical nested notification prefs (matches backend / storage). */
export type NotificationPrefs = {
  in_app: {
    task_activity: boolean
    matching: boolean
    share_revoke: boolean
    sync_system: boolean
  }
  email: {
    enabled: boolean
    task_activity: boolean
    matching: boolean
    share_revoke: boolean
    sync_system: boolean
  }
}

export const NOTIFICATION_PREFS_DEFAULT: NotificationPrefs = {
  in_app: {
    task_activity: true,
    matching: true,
    share_revoke: true,
    sync_system: true,
  },
  email: {
    enabled: false,
    task_activity: false,
    matching: false,
    share_revoke: false,
    sync_system: false,
  },
}

const IN_APP_KEYS = ['task_activity', 'matching', 'share_revoke', 'sync_system'] as const
const EMAIL_KEYS = ['enabled', 'task_activity', 'matching', 'share_revoke', 'sync_system'] as const

function isRecord(x: unknown): x is Record<string, unknown> {
  return x !== null && typeof x === 'object' && !Array.isArray(x)
}

/** Normalize API/legacy input to canonical nested shape (same rules as backend). */
export function normalizeNotificationPrefsFromServer(raw: unknown): NotificationPrefs {
  const out: NotificationPrefs = {
    in_app: { ...NOTIFICATION_PREFS_DEFAULT.in_app },
    email: { ...NOTIFICATION_PREFS_DEFAULT.email },
  }
  if (!isRecord(raw)) return out
  const inApp = raw.in_app
  if (typeof inApp === 'boolean') {
    for (const k of IN_APP_KEYS) out.in_app[k] = inApp
  } else if (isRecord(inApp)) {
    for (const k of IN_APP_KEYS) {
      const v = inApp[k]
      if (typeof v === 'boolean') out.in_app[k] = v
    }
  }
  const email = raw.email
  if (typeof email === 'boolean') {
    out.email.enabled = email
  } else if (isRecord(email)) {
    for (const k of EMAIL_KEYS) {
      const v = email[k]
      if (typeof v === 'boolean') out.email[k] = v
    }
  }
  return out
}

export async function fetchNotificationSettings(): Promise<{ prefs: NotificationPrefs; updated_at: string }> {
  const res = await fetch(`${BASE}/notifications`, { credentials: 'include' })
  if (!res.ok) throw new Error('Failed to load notifications')
  const body = (await res.json()) as { prefs?: unknown; updated_at: string }
  return {
    prefs: normalizeNotificationPrefsFromServer(body.prefs),
    updated_at: body.updated_at,
  }
}

export async function saveNotificationSettings(prefs: NotificationPrefs): Promise<void> {
  const res = await fetch(`${BASE}/notifications`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prefs }),
  })
  if (!res.ok) throw new Error('Save notifications failed')
}

export type UserPermissionFlags = {
  behavioral_tracking: boolean
  personalization: boolean
  interaction_pattern_storage: boolean
  profile_learning: boolean
  analytics_product_improvement: boolean
  aspiration_store_explicit: boolean
  aspiration_infer_suggestions: boolean
  aspiration_use_in_guidance: boolean
}

export const USER_PERMISSION_DEFAULTS: UserPermissionFlags = {
  behavioral_tracking: false,
  personalization: false,
  interaction_pattern_storage: false,
  profile_learning: false,
  analytics_product_improvement: false,
  aspiration_store_explicit: false,
  aspiration_infer_suggestions: false,
  aspiration_use_in_guidance: false,
}

export type UserPermissionsSettings = {
  consent_given: boolean
  consent_version: string
  consent_at: string | null
  updated_at: string
  permissions: UserPermissionFlags
}

export function normalizeUserPermissionFlags(raw: unknown): UserPermissionFlags {
  const out: UserPermissionFlags = { ...USER_PERMISSION_DEFAULTS }
  if (!isRecord(raw)) return out
  ;(Object.keys(out) as (keyof UserPermissionFlags)[]).forEach((k) => {
    if (typeof raw[k] === 'boolean') out[k] = raw[k] as boolean
  })
  return out
}

export async function fetchUserPermissionsSettings(): Promise<UserPermissionsSettings> {
  const res = await fetch(`${BASE}/permissions`, { credentials: 'include' })
  if (!res.ok) throw new Error('Failed to load permissions')
  const body = (await res.json()) as Partial<UserPermissionsSettings>
  return {
    consent_given: Boolean(body.consent_given),
    consent_version: String(body.consent_version ?? ''),
    consent_at: typeof body.consent_at === 'string' ? body.consent_at : null,
    updated_at: String(body.updated_at ?? ''),
    permissions: normalizeUserPermissionFlags(body.permissions),
  }
}

export async function saveUserPermissionsSettings(payload: {
  consent_acknowledged: boolean
  consent_version: string
  permissions: UserPermissionFlags
}): Promise<UserPermissionsSettings> {
  const res = await fetch(`${BASE}/permissions`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail
    throw new Error(typeof detail === 'string' ? detail : 'Failed to save permissions')
  }
  return {
    consent_given: Boolean(body.consent_given),
    consent_version: String(body.consent_version ?? ''),
    consent_at: typeof body.consent_at === 'string' ? body.consent_at : null,
    updated_at: String(body.updated_at ?? ''),
    permissions: normalizeUserPermissionFlags(body.permissions),
  }
}

export interface IdentityScopesResponse {
  active: string[]
  known_scopes: Record<string, string>
}

export async function fetchIdentityScopes(): Promise<IdentityScopesResponse> {
  const res = await fetch('/identity/scopes', { credentials: 'include' })
  if (!res.ok) throw new Error('Failed to load identity scopes')
  const body = (await res.json()) as Partial<IdentityScopesResponse>
  return {
    active: Array.isArray(body.active) ? body.active.map(String) : [],
    known_scopes:
      body.known_scopes && typeof body.known_scopes === 'object'
        ? (body.known_scopes as Record<string, string>)
        : {},
  }
}

export async function changeIdentityScope(
  scope: string,
  action: 'grant' | 'revoke',
  note = '',
): Promise<string[]> {
  const res = await fetch('/identity/scopes', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scope, action, note }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail
    throw new Error(typeof detail === 'string' ? detail : `Failed to ${action} scope`)
  }
  const active = (body as { active?: unknown }).active
  return Array.isArray(active) ? active.map(String) : []
}
