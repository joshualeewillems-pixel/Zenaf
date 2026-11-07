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
  steward_derivation: boolean
  steward_coordination: boolean
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
  // Increment A: Narrative Steward derivation (proposal §1.8).
  // Default off; normalizeUserPermissionFlags fills false for
  // stored rows that lack the key, so existing users are NOT
  // opted in by the addition (permissions-v1 kept, no forced
  // re-acknowledgement).
  steward_derivation: false,
  // Permission Slice 1 (foundation) — R3 DEAD-FLAG REPAIR
  // (inventory §1.4): steward_coordination existed in the
  // consent gate and its consumer but was absent from these
  // defaults AND the backend key list, so it could never persist
  // (normalizeUserPermissionFlags drops unknown keys, and the
  // backend normalize dropped it too). Default off; existing
  // users are NOT opted in by the repair, and no forced
  // re-acknowledgement. Slice 1 bound: defaults (data) only —
  // no Settings UI component change; the coordination row lands
  // with the Slice 2 Settings surface.
  steward_coordination: false,
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

// --- Permission framework surface (Slice 2) -------------------------------
// Grouped stance surface (Rev2 §2.2–§2.3), global pause (C4), and
// retained-information counts (Rev2 §4.2). The backend is the
// authority; these normalizers only defend the UI against a malformed
// payload (unknown stances fall back to the capability default).

export type FrameworkStance = 'ask_me' | 'just_do_it' | 'dont_do_it'

export const FRAMEWORK_STANCES: FrameworkStance[] = ['ask_me', 'just_do_it', 'dont_do_it']

export function stanceLabel(stance: FrameworkStance): string {
  if (stance === 'ask_me') return 'Ask me'
  if (stance === 'just_do_it') return 'Just do it'
  return "Don't do it"
}

function isFrameworkStance(value: unknown): value is FrameworkStance {
  return typeof value === 'string' && (FRAMEWORK_STANCES as string[]).includes(value)
}

export type FrameworkRow = {
  key: string
  label: string
  kind: string
  stance: FrameworkStance
  stance_source: 'user' | 'default'
  granted_at: string | null
  last_changed_at: string | null
  surface: string | null
}

export type FrameworkCapability = {
  id: string
  covers: string
  does_not_allow: string
  default_stance: FrameworkStance
  supported_stances: FrameworkStance[]
  exception_classes: string[]
  /**
   * Retained-item count: a number when the read succeeded, null when
   * the read failed. A failed read is UNAVAILABLE, never zero —
   * the surface must render it as unavailable, never as "0 items"
   * (founder verdict check 2, 2026-11-06).
   */
  retained_count: number | null
  retained_count_status: 'available' | 'unavailable'
  quieted: boolean
  paused: boolean
  rows: FrameworkRow[]
}

export type FrameworkPause = {
  paused: boolean
  paused_at: string | null
  surface: string | null
}

export type FrameworkState = {
  paused: boolean
  pause: FrameworkPause
  capabilities: FrameworkCapability[]
}

export function normalizeFrameworkState(raw: unknown): FrameworkState {
  const fallback: FrameworkState = {
    paused: false,
    pause: { paused: false, paused_at: null, surface: null },
    capabilities: [],
  }
  if (!isRecord(raw)) return fallback
  const pauseRaw = isRecord(raw.pause) ? raw.pause : {}
  const capabilities: FrameworkCapability[] = []
  if (Array.isArray(raw.capabilities)) {
    for (const entry of raw.capabilities) {
      if (!isRecord(entry)) continue
      const defaultStance = isFrameworkStance(entry.default_stance)
        ? entry.default_stance
        : 'dont_do_it'
      const supported = Array.isArray(entry.supported_stances)
        ? (entry.supported_stances as unknown[]).filter(isFrameworkStance)
        : [defaultStance]
      const rows: FrameworkRow[] = []
      if (Array.isArray(entry.rows)) {
        for (const row of entry.rows) {
          if (!isRecord(row)) continue
          rows.push({
            key: String(row.key ?? ''),
            label: String(row.label ?? ''),
            kind: String(row.kind ?? ''),
            stance: isFrameworkStance(row.stance) ? row.stance : defaultStance,
            stance_source: row.stance_source === 'user' ? 'user' : 'default',
            granted_at: typeof row.granted_at === 'string' ? row.granted_at : null,
            last_changed_at: typeof row.last_changed_at === 'string' ? row.last_changed_at : null,
            surface: typeof row.surface === 'string' ? row.surface : null,
          })
        }
      }
      capabilities.push({
        id: String(entry.id ?? ''),
        covers: String(entry.covers ?? ''),
        does_not_allow: String(entry.does_not_allow ?? ''),
        default_stance: defaultStance,
        supported_stances: supported.length > 0 ? supported : [defaultStance],
        exception_classes: Array.isArray(entry.exception_classes)
          ? (entry.exception_classes as unknown[]).map(String)
          : [],
        // A failed/unavailable read is null, never 0: the normalizer
        // must not collapse it into a verified zero. An explicit
        // 'unavailable' status from the server wins over any number
        // present (fail-closed direction).
        retained_count:
          entry.retained_count_status === 'unavailable'
            ? null
            : typeof entry.retained_count === 'number' && Number.isFinite(entry.retained_count)
              ? Math.max(0, Math.floor(entry.retained_count))
              : null,
        retained_count_status:
          entry.retained_count_status === 'unavailable'
            ? 'unavailable'
            : typeof entry.retained_count === 'number' && Number.isFinite(entry.retained_count)
              ? 'available'
              : 'unavailable',
        quieted: Boolean(entry.quieted),
        paused: Boolean(entry.paused),
        rows,
      })
    }
  }
  const paused = Boolean(raw.paused) || Boolean(pauseRaw.paused)
  return {
    paused,
    pause: {
      paused,
      paused_at: typeof pauseRaw.paused_at === 'string' ? pauseRaw.paused_at : null,
      surface: typeof pauseRaw.surface === 'string' ? pauseRaw.surface : null,
    },
    capabilities,
  }
}

export async function fetchFrameworkPermissions(): Promise<FrameworkState> {
  const res = await fetch(`${BASE}/permissions/framework`, { credentials: 'include' })
  if (!res.ok) throw new Error('Failed to load permission framework')
  return normalizeFrameworkState(await res.json().catch(() => ({})))
}

export type FrameworkStanceResponse = {
  record: Record<string, unknown>
  retained_count: number | null
  retained_count_status: 'available' | 'unavailable'
  retained_choice_offered: boolean
  state: FrameworkState
}

export async function setFrameworkStance(
  capability: string,
  rowKey: string | null,
  stance: FrameworkStance,
): Promise<FrameworkStanceResponse> {
  const res = await fetch(`${BASE}/permissions/framework/stance`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ capability, row_key: rowKey, stance }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail
    throw new Error(typeof detail === 'string' ? detail : 'Failed to save stance')
  }
  return {
    record: isRecord(body.record) ? body.record : {},
    retained_count:
      body.retained_count_status === 'unavailable'
        ? null
        : typeof body.retained_count === 'number'
          ? body.retained_count
          : null,
    retained_count_status:
      body.retained_count_status === 'unavailable'
        ? 'unavailable'
        : typeof body.retained_count === 'number'
          ? 'available'
          : 'unavailable',
    retained_choice_offered: Boolean(body.retained_choice_offered),
    state: normalizeFrameworkState(body.state),
  }
}

export type FrameworkPauseResponse = {
  pause: FrameworkPause
  canceled_operations: unknown[]
  state: FrameworkState
}

export async function setFrameworkPause(paused: boolean): Promise<FrameworkPauseResponse> {
  const res = await fetch(`${BASE}/permissions/framework/pause`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paused }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail
    throw new Error(typeof detail === 'string' ? detail : 'Failed to save pause')
  }
  const pauseRaw = isRecord(body.pause) ? body.pause : {}
  return {
    pause: {
      paused: Boolean(pauseRaw.paused),
      paused_at: typeof pauseRaw.paused_at === 'string' ? pauseRaw.paused_at : null,
      surface: typeof pauseRaw.surface === 'string' ? pauseRaw.surface : null,
    },
    canceled_operations: Array.isArray(body.canceled_operations) ? body.canceled_operations : [],
    state: normalizeFrameworkState(body.state),
  }
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
