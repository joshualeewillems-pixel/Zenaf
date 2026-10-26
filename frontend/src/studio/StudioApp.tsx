/**
 * Operator-only Studio surface: LLM bakeoffs and prompt tooling.
 * ai-trace-exempt: studio_admin_surface (see frontend/src/ai-actions/aiTraceExemptRegistry.ts)
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { AuthGate } from '../auth/AuthGate'
import { login as loginSession, logout as logoutSession } from '../auth/session'

type TeacherMode = 'off' | 'shadow' | 'warn' | 'veto' | 'replace'

type TeacherSettings = {
  teacher_mode: TeacherMode
  teacher_provider?: string | null
  teacher_model?: string | null
  teacher_prompt_version?: string | null
  teacher_prompt_overlay?: string | null
  main_attachment_provider?: string | null
  main_attachment_model?: string | null
  local_attachment_provider?: string | null
  local_attachment_model?: string | null
  experimental_google_provider?: string | null
  experimental_google_model?: string | null
  experimental_xai_provider?: string | null
  experimental_xai_model?: string | null
  capability_teacher_modes?: Record<string, string>
}

type StudioRun = {
  id: string
  created_at: string
  teacher_mode: string
  teacher_enforcement_mode?: string | null
  teacher_vetoed?: boolean
  teacher_warning?: boolean
  teacher_final_source?: string | null
  teacher_reason_codes?: string[]
  teacher_notes?: string | null
  final_selection_policy?: string | null
  native_provider?: string | null
  native_model?: string | null
  teacher_provider_effective?: string | null
  teacher_model_effective?: string | null
  teacher_succeeded?: boolean
  comparison?: {
    teacher_present?: boolean
    native_summary?: string | null
    teacher_summary?: string | null
    same_decision?: boolean | null
    same_next_move?: boolean | null
    notes?: string | null
  }
}

type RunDebugSeat = {
  seat_index?: number
  seat_name?: string
  seat_id?: string | null
  seat_kind?: string
  raw_perspective_definition?: Record<string, unknown> | null
  normalized_persona_block?: string
  prompt_decomposition?: Record<string, unknown>
  full_compiled_prompt?: string
  compiled_prompt?: string
  raw_output?: string
  parsed_seat_judgment?: Record<string, unknown>
}

type RunDebugPayload = {
  run_meta?: Record<string, unknown>
  prompt_stack?: Record<string, unknown>
  seats?: RunDebugSeat[]
  synthesis?: Record<string, unknown>
  selection?: Record<string, unknown>
}

type StudioRunDetail = StudioRun & {
  user_id?: string | null
  execution_scope?: string | null
  execution_principal_ref?: string | null
  prompt_version?: string | null
  native_text?: string | null
  teacher_text?: string | null
  native_artifact?: Record<string, any>
  teacher_artifact?: Record<string, any>
  native_run_debug?: RunDebugPayload
  teacher_run_debug?: RunDebugPayload
  comparison?: {
    teacher_present?: boolean
    native_summary?: string | null
    teacher_summary?: string | null
    same_decision?: boolean | null
    same_next_move?: boolean | null
    notes?: string | null
  }
}

type SystemIndexEntryPoint = {
  label?: string
  location?: string
  method?: string
  path?: string
  mode?: string
}

type SystemIndexCapability = {
  id: string
  name: string
  purpose: string
  status: string
  inspectability?: string
  teacher_support: string
  ui_entry_points?: SystemIndexEntryPoint[]
  api_entry_points?: SystemIndexEntryPoint[]
  main_files?: string[]
  artifacts?: string[]
}

type SystemIndexPrompt = {
  id: string
  name: string
  definition: string
  composition: string
  versioning: string
  exposed_in_studio: boolean
}

type SystemIndexArtifact = {
  id: string
  name: string
  schema_anchor: string
  persistence: string
  access: string[]
  status: string
  inspectability?: string
  teacher_support?: string
  ui_access?: string
}

type SystemIndexUiSurface = {
  id: string
  location: string
  purpose: string
  status: string
}

type SystemIndexPayload = {
  generated_for: string
  status_legend?: Record<string, string>
  inspectability_legend?: Record<string, string>
  teacher_support_legend?: Record<string, string>
  summary?: Record<string, string | number | null>
  capabilities: SystemIndexCapability[]
  ui_surfaces: SystemIndexUiSurface[]
  prompt_systems: SystemIndexPrompt[]
  artifact_systems: SystemIndexArtifact[]
  hidden_unsurfaced?: {
    capabilities_without_studio_inspection?: SystemIndexCapability[]
    prompts_not_exposed?: SystemIndexPrompt[]
    artifacts_without_ui_access?: SystemIndexArtifact[]
    orphan_or_experimental_surfaces?: SystemIndexUiSurface[]
  }
}

type CredentialVisibilityPayload = {
  option_b_note?: string
  anonymous_openai_cloud_allowed?: boolean
  system?: {
    openai_env_var?: string
    openai_configured?: boolean
  }
  account_authenticated?: {
    principal_ref?: string
    openai_env_key_present?: boolean
    openai_settings_key_present?: boolean
    openai_effective_source?: string
  }
}

type ProviderPolicyPayload = {
  schema_version?: number
  implicit_default_sources?: Array<Record<string, unknown>>
  fallback_order_explanation?: string[]
  planes?: Record<string, Record<string, unknown>>
  current_session?: Record<string, unknown>
  example_routing_intent_workspace_council?: Record<string, unknown>
}

type BakeoffResultRow = {
  provider: string
  model: string | null
  ok: boolean
  latency_ms: number | null
  output_preview: string | null
  error: string | null
  grounding_score?: number
  structure_score?: number
  specificity_score?: number
  constraint_obedience_score?: number
  usefulness_score?: number
  total_score?: number
  score_notes?: string | null
  suggested_default_model?: string | null
}

type BakeoffScoringMeta = {
  scoring_enabled?: boolean
  judge_provider?: string
  judge_model?: string
}

type BakeoffResponse = {
  lane: string
  prompt: string
  principal_ref: string
  credential_namespace: string
  scoring?: BakeoffScoringMeta
  results: BakeoffResultRow[]
}

const BAKEOFF_LANE = 'council_native_attachment'
const DEFAULT_BAKEOFF_PROMPT = 'What is the next step for improving council grounding?'
/** Fallback before GET /studio/provider-default-models (matches provider modules). */
const FALLBACK_BAKEOFF_PROVIDERS_JSON = `[
  {"provider": "ollama", "model": "qwen3:8b"},
  {"provider": "openai", "model": "gpt-4o-mini"},
  {"provider": "anthropic", "model": "claude-haiku-4-5"},
  {"provider": "google", "model": "gemini-3.8-flash"},
  {"provider": "xai", "model": "grok-4-1-fast-reasoning"}
]`

function providerDefaultsResponseToBakeoffJson(data: Record<string, unknown>): string {
  const order = ['ollama', 'openai', 'anthropic', 'google', 'xai'] as const
  const rows: { provider: string; model: string }[] = []
  for (const k of order) {
    const m = data[k]
    if (typeof m === 'string' && m.trim()) rows.push({ provider: k, model: m.trim() })
  }
  return JSON.stringify(rows, null, 2)
}

export function StudioApp() {
  const [activeTab, setActiveTab] = useState<'index' | 'teacher' | 'runs' | 'policy'>('index')
  const [authState, setAuthState] = useState<'loading' | 'login' | 'denied' | 'ready'>('loading')
  const [me, setMe] = useState<{ email: string; display_name: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [prompts, setPrompts] = useState<Record<string, unknown> | null>(null)
  const [systemIndex, setSystemIndex] = useState<SystemIndexPayload | null>(null)
  const [settings, setSettings] = useState<TeacherSettings>({
    teacher_mode: 'shadow',
    teacher_provider: 'ollama',
    teacher_model: 'qwen3:8b',
    teacher_prompt_version: 'council_teacher_v1',
    teacher_prompt_overlay: '',
    main_attachment_provider: 'ollama',
    main_attachment_model: 'qwen3:8b',
    local_attachment_provider: 'ollama',
    local_attachment_model: 'qwen3:8b',
    experimental_google_provider: 'google',
    experimental_google_model: 'gemini-3.8-flash',
    experimental_xai_provider: 'xai',
    experimental_xai_model: 'grok-4-1-fast-reasoning',
    capability_teacher_modes: {},
  })
  const [runs, setRuns] = useState<StudioRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedRunDetail, setSelectedRunDetail] = useState<StudioRunDetail | null>(null)
  const [runTab, setRunTab] = useState<'overview' | 'native' | 'teacher' | 'synthesis' | 'compare'>('overview')
  const [selectedNativeSeat, setSelectedNativeSeat] = useState<number>(0)
  const [selectedTeacherSeat, setSelectedTeacherSeat] = useState<number>(0)
  const [saving, setSaving] = useState(false)
  const [providerPolicy, setProviderPolicy] = useState<ProviderPolicyPayload | null>(null)
  const [bakeoffPrompt, setBakeoffPrompt] = useState(DEFAULT_BAKEOFF_PROMPT)
  const [bakeoffProvidersJson, setBakeoffProvidersJson] = useState(FALLBACK_BAKEOFF_PROVIDERS_JSON)
  const [bakeoffResponse, setBakeoffResponse] = useState<BakeoffResponse | null>(null)
  const [bakeoffBusy, setBakeoffBusy] = useState(false)
  const [bakeoffErr, setBakeoffErr] = useState<string | null>(null)
  const bakeoffDefaultsAppliedRef = useRef(false)

  const sortedBakeoffResults = useMemo(() => {
    const rows = bakeoffResponse?.results ?? []
    return [...rows].sort((a, b) => {
      const ts = (Number(b.total_score) || 0) - (Number(a.total_score) || 0)
      if (ts !== 0) return ts
      const la = a.latency_ms ?? Number.POSITIVE_INFINITY
      const lb = b.latency_ms ?? Number.POSITIVE_INFINITY
      return la - lb
    })
  }, [bakeoffResponse])

  const loadAll = async () => {
    setErr(null)
    const meRes = await fetch('/studio/me', { credentials: 'include' })
    if (meRes.status === 401) {
      setAuthState('login')
      return
    }
    if (meRes.status === 403) {
      setAuthState('denied')
      return
    }
    if (!meRes.ok) throw new Error(`Studio auth failed (${meRes.status})`)
    const meData = await meRes.json()
    setMe(meData)
    setAuthState('ready')
    const [pRes, sRes, rRes] = await Promise.all([
      fetch('/studio/council/prompts', { credentials: 'include' }),
      fetch('/studio/council/teacher-settings', { credentials: 'include' }),
      fetch('/studio/council/recent-runs?limit=25', { credentials: 'include' }),
    ])
    const iRes = await fetch('/studio/system-index', { credentials: 'include' })
    const polRes = await fetch('/studio/provider-default-policy?scope=current', { credentials: 'include' })
    if (pRes.ok) setPrompts(await pRes.json())
    if (sRes.ok) setSettings(await sRes.json())
    if (rRes.ok) {
      const d = await rRes.json()
      setRuns(Array.isArray(d?.items) ? d.items : [])
    }
    if (iRes.ok) setSystemIndex(await iRes.json())
    if (polRes.ok) setProviderPolicy(await polRes.json())
    const dmRes = await fetch('/studio/provider-default-models', { credentials: 'include' })
    if (dmRes.ok && !bakeoffDefaultsAppliedRef.current) {
      const dm = (await dmRes.json()) as Record<string, unknown>
      setBakeoffProvidersJson(providerDefaultsResponseToBakeoffJson(dm))
      bakeoffDefaultsAppliedRef.current = true
    }
  }

  useEffect(() => {
    void loadAll().catch((e) => {
      setErr(e instanceof Error ? e.message : String(e))
      setAuthState('login')
    })
  }, [])

  const onLogin = async (email: string, password: string) => {
    await loginSession(email, password)
    await loadAll()
  }

  const saveSettings = async () => {
    setSaving(true)
    setErr(null)
    try {
      const res = await fetch('/studio/council/teacher-settings', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(String(data?.detail || `Save failed (${res.status})`))
      setSettings(data)
      const rr = await fetch('/studio/council/recent-runs?limit=25', { credentials: 'include' })
      if (rr.ok) {
        const d = await rr.json()
        setRuns(Array.isArray(d?.items) ? d.items : [])
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const seatContracts = useMemo(() => {
    const p = prompts as Record<string, any> | null
    return p?.personas ? Object.entries(p.personas) : []
  }, [prompts])

  const statusLegend = useMemo(() => systemIndex?.status_legend ?? {}, [systemIndex])
  const inspectabilityLegend = useMemo(() => systemIndex?.inspectability_legend ?? {}, [systemIndex])
  const teacherSupportLegend = useMemo(() => systemIndex?.teacher_support_legend ?? {}, [systemIndex])

  const badgeClass = (kind: string, value: string | undefined) => {
    const v = (value ?? '').toLowerCase()
    const base = 'px-2 py-0.5 rounded text-[11px] border'
    if (kind === 'status') {
      if (v === 'active') return `${base} border-emerald-700 text-emerald-300`
      if (v === 'experimental') return `${base} border-violet-700 text-violet-300`
      if (v === 'partial') return `${base} border-amber-700 text-amber-300`
      return `${base} border-slate-700 text-slate-300`
    }
    if (kind === 'inspectability') {
      if (v === 'detailed') return `${base} border-cyan-700 text-cyan-300`
      if (v === 'summary') return `${base} border-blue-700 text-blue-300`
      return `${base} border-slate-700 text-slate-300`
    }
    if (kind === 'teacher') {
      if (v === 'available') return `${base} border-emerald-700 text-emerald-300`
      if (v === 'council-only') return `${base} border-amber-700 text-amber-300`
      return `${base} border-slate-700 text-slate-300`
    }
    return `${base} border-slate-700 text-slate-300`
  }

  const studioTabLink = (label: string, tab: 'index' | 'teacher' | 'runs' | 'policy') => (
    <button
      type="button"
      onClick={() => setActiveTab(tab)}
      className="underline text-amber-300 hover:text-amber-200"
    >
      {label}
    </button>
  )

  const buildSimpleDiff = (nativeText: string, teacherText: string) => {
    const n = nativeText.split(/\r?\n/)
    const t = teacherText.split(/\r?\n/)
    const out: string[] = []
    const max = Math.max(n.length, t.length)
    for (let i = 0; i < max; i += 1) {
      const nl = n[i] ?? ''
      const tl = t[i] ?? ''
      if (nl !== tl) {
        out.push(`- N: ${nl}`)
        out.push(`+ T: ${tl}`)
      }
      if (out.length >= 80) break
    }
    return out.join('\n')
  }

  const renderIndexTab = () => (
    <div className="space-y-4">
      <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
        <h2 className="font-medium mb-2">System Summary</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 lg:grid-cols-5 gap-2 text-xs text-slate-200">
          <div className="rounded border border-slate-800 px-2 py-2">
            <div className="text-slate-400">Total capabilities</div>
            <div className="text-lg font-semibold">{String(systemIndex?.summary?.total_capabilities ?? '—')}</div>
          </div>
          <div className="rounded border border-slate-800 px-2 py-2">
            <div className="text-slate-400">Active</div>
            <div className="text-lg font-semibold">{String(systemIndex?.summary?.active_capabilities ?? '—')}</div>
          </div>
          <div className="rounded border border-slate-800 px-2 py-2">
            <div className="text-slate-400">Partial/Experimental</div>
            <div className="text-lg font-semibold">{String(systemIndex?.summary?.partial_or_experimental_capabilities ?? '—')}</div>
          </div>
          <div className="rounded border border-slate-800 px-2 py-2">
            <div className="text-slate-400">Teacher-supported</div>
            <div className="text-lg font-semibold">{String(systemIndex?.summary?.capabilities_with_teacher_support ?? '—')}</div>
          </div>
          <div className="rounded border border-slate-800 px-2 py-2">
            <div className="text-slate-400">Artifacts not in UI</div>
            <div className="text-lg font-semibold">{String(systemIndex?.summary?.artifact_systems_not_surfaced_in_ui ?? '—')}</div>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
        <h2 className="font-medium mb-2">Capability Catalog</h2>
        <div className="space-y-3 text-xs">
          {(systemIndex?.capabilities ?? []).map((c) => (
            <div key={c.id} className="rounded border border-slate-800 p-3 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="font-semibold text-slate-100">{c.name}</div>
                  <div className="text-slate-300">{c.purpose}</div>
                </div>
                <div className="text-right flex gap-1 flex-wrap justify-end">
                  <span className={badgeClass('status', c.status)}>{c.status}</span>
                  <span className={badgeClass('inspectability', c.inspectability)}>{c.inspectability ?? 'none'}</span>
                  <span className={badgeClass('teacher', c.teacher_support)}>{c.teacher_support}</span>
                </div>
              </div>
              <div className="text-slate-300">
                <span className="text-slate-400">UI:</span>{' '}
                {(c.ui_entry_points ?? []).map((x, i) => (
                  <span key={`${c.id}-ui-${i}`} className="mr-2">
                    {x.label ?? x.location}
                    {x.location ? ` (${x.location})` : ''}
                  </span>
                ))}
              </div>
              <div className="text-slate-300">
                <span className="text-slate-400">API:</span>{' '}
                {(c.api_entry_points ?? []).map((x, i) => (
                  <a
                    key={`${c.id}-api-${i}`}
                    className="mr-2 underline text-amber-300 hover:text-amber-200"
                    href={x.path ? x.path : '#'}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {x.method ? `${x.method} ` : ''}
                    {x.path ?? ''}
                    {x.mode ? ` [mode=${x.mode}]` : ''}
                  </a>
                ))}
              </div>
              <div className="text-slate-300">
                <span className="text-slate-400">Studio shortcuts:</span>{' '}
                {studioTabLink('Index', 'index')} · {studioTabLink('Teacher Controls', 'teacher')} · {studioTabLink('Recent Runs', 'runs')}
              </div>
              <div className="text-slate-300">
                <span className="text-slate-400">Files:</span> {(c.main_files ?? []).join(', ')}
              </div>
              <div className="text-slate-300">
                <span className="text-slate-400">Artifacts:</span> {(c.artifacts ?? []).join(', ')}
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
          <h2 className="font-medium mb-2">Prompt Catalog</h2>
          <div className="space-y-2 text-xs">
            {(systemIndex?.prompt_systems ?? []).map((p) => (
              <div key={p.id} className="rounded border border-slate-800 p-2">
                <div className="font-semibold">{p.name}</div>
                <div className="text-slate-300">Definition: {p.definition}</div>
                <div className="text-slate-300">Compose: {p.composition}</div>
                <div className="text-slate-300">
                  Versioning: {p.versioning} · Exposed in Studio: {p.exposed_in_studio ? 'yes' : 'no'}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
          <h2 className="font-medium mb-2">Artifact + Trace Catalog</h2>
          <div className="space-y-2 text-xs">
            {(systemIndex?.artifact_systems ?? []).map((a) => (
              <div key={a.id} className="rounded border border-slate-800 p-2">
                <div className="font-semibold flex items-center justify-between">
                  <span>{a.name}</span>
                  <span className="flex gap-1">
                    <span className={badgeClass('status', a.status)}>{a.status}</span>
                    <span className={badgeClass('inspectability', a.inspectability)}>{a.inspectability ?? 'none'}</span>
                    <span className={badgeClass('teacher', a.teacher_support)}>{a.teacher_support ?? 'none'}</span>
                  </span>
                </div>
                <div className="text-slate-300">Schema: {a.schema_anchor}</div>
                <div className="text-slate-300">Persistence: {a.persistence}</div>
                <div className="text-slate-300">
                  Access:{' '}
                  {a.access.map((entry) => (
                    <a key={`${a.id}-${entry}`} href={entry.startsWith('/') ? entry : '#'} target="_blank" rel="noreferrer" className="mr-2 underline text-amber-300 hover:text-amber-200">
                      {entry}
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
        <h2 className="font-medium mb-2">Hidden / Unsurfaced</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 text-xs">
          <div className="rounded border border-slate-800 p-2">
            <div className="text-slate-400 mb-1">Capabilities without Studio inspection</div>
            {(systemIndex?.hidden_unsurfaced?.capabilities_without_studio_inspection ?? []).map((c) => (
              <div key={`hcap-${c.id}`} className="text-slate-200">{c.name}</div>
            ))}
          </div>
          <div className="rounded border border-slate-800 p-2">
            <div className="text-slate-400 mb-1">Prompts not exposed in Studio</div>
            {(systemIndex?.hidden_unsurfaced?.prompts_not_exposed ?? []).map((p) => (
              <div key={`hprompt-${p.id}`} className="text-slate-200">{p.name}</div>
            ))}
          </div>
          <div className="rounded border border-slate-800 p-2">
            <div className="text-slate-400 mb-1">Artifacts/traces with no UI access</div>
            {(systemIndex?.hidden_unsurfaced?.artifacts_without_ui_access ?? []).map((a) => (
              <div key={`hart-${a.id}`} className="text-slate-200">{a.name}</div>
            ))}
          </div>
          <div className="rounded border border-slate-800 p-2">
            <div className="text-slate-400 mb-1">Likely orphaned/experimental surfaces</div>
            {(systemIndex?.hidden_unsurfaced?.orphan_or_experimental_surfaces ?? []).map((s) => (
              <div key={`hsurf-${s.id}`} className="text-slate-200">{s.location}</div>
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
        <h2 className="font-medium mb-2">UI Surface Inventory</h2>
        <div className="space-y-2 text-xs">
          {(systemIndex?.ui_surfaces ?? []).map((s) => (
            <div key={s.id} className="rounded border border-slate-800 p-2">
              <div className="font-semibold">{s.location}</div>
              <div className="text-slate-300">{s.purpose}</div>
              <div className="text-amber-300">Status: {s.status}</div>
            </div>
          ))}
        </div>
      </section>

      {Object.keys(statusLegend).length > 0 && (
        <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
          <h2 className="font-medium mb-2">Legends</h2>
          <div className="space-y-1 text-xs text-slate-300">
            {Object.entries(statusLegend).map(([k, v]) => (
              <div key={k}>
                <span className={badgeClass('status', k)}>{k}</span> {v}
              </div>
            ))}
            {Object.entries(inspectabilityLegend).map(([k, v]) => (
              <div key={`inspect-${k}`}>
                <span className={badgeClass('inspectability', k)}>{k}</span> {v}
              </div>
            ))}
            {Object.entries(teacherSupportLegend).map(([k, v]) => (
              <div key={`teacher-${k}`}>
                <span className={badgeClass('teacher', k)}>{k}</span> {v}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )

  const renderPolicyTab = () => {
    const planes = providerPolicy?.planes ?? {}
    const cur = providerPolicy?.current_session as Record<string, unknown> | undefined
    const usable = (cur?.usable_providers as Array<Record<string, unknown>> | undefined) ?? []
    const credVis = cur?.credential_visibility as CredentialVisibilityPayload | undefined
    const sys = credVis?.system
    const acct = credVis?.account_authenticated

    return (
      <div className="space-y-4">
        {credVis && (
          <section className="rounded-xl border border-amber-900/50 bg-slate-900/60 p-4">
            <h2 className="font-medium mb-1 text-amber-200">System & credential visibility (admin)</h2>
            <p className="text-xs text-slate-400 mb-3">{credVis.option_b_note}</p>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 text-xs">
              <div className="rounded border border-slate-800 p-3 space-y-1">
                <div className="font-semibold text-slate-200">System OpenAI</div>
                <div>
                  <span className="text-slate-400">Env var:</span>{' '}
                  <code className="text-amber-300">{sys?.openai_env_var ?? 'ZENAF_SYSTEM_OPENAI_KEY'}</code>
                </div>
                <div>
                  <span className="text-slate-400">Key present:</span>{' '}
                  {sys?.openai_configured ? 'yes' : 'no'}
                </div>
                <p className="text-slate-500 mt-1">Set on the API server process; not editable from this UI.</p>
              </div>
              <div className="rounded border border-slate-800 p-3 space-y-1">
                <div className="font-semibold text-slate-200">Account lane (this signed-in admin)</div>
                <div>
                  <span className="text-slate-400">Principal:</span> {acct?.principal_ref ?? '—'}
                </div>
                <div>
                  <span className="text-slate-400">OPENAI_API_KEY on server:</span>{' '}
                  {acct?.openai_env_key_present ? 'set (non-empty)' : 'not set'}
                </div>
                <div>
                  <span className="text-slate-400">OpenAI key in Settings:</span>{' '}
                  {acct?.openai_settings_key_present ? 'saved' : 'not saved'}
                </div>
                <div>
                  <span className="text-slate-400">Effective OpenAI source:</span>{' '}
                  <code className="text-amber-300">{acct?.openai_effective_source ?? '—'}</code>
                </div>
              </div>
              <div className="rounded border border-slate-800 p-3 lg:col-span-2 space-y-1">
                <div className="font-semibold text-slate-200">Anonymous cloud OpenAI</div>
                <div>
                  <span className="text-slate-400">Allowed:</span>{' '}
                  {credVis.anonymous_openai_cloud_allowed ? 'yes' : 'no (Option B)'}
                </div>
              </div>
            </div>
          </section>
        )}
        <section className="rounded-xl border border-emerald-900/40 bg-slate-900/60 p-4">
          <h2 className="font-medium mb-1 text-emerald-200">Council native bakeoff (admin)</h2>
          <p className="text-xs text-slate-400 mb-3">
            Same prompt, sequential runs via <code className="text-emerald-300">get_council_llm_adapter_for_principal</code> with
            explicit provider/model. Default provider list is loaded from{' '}
            <code className="text-emerald-300">GET /studio/provider-default-models</code> (canonical module defaults). Heuristics + a
            fixed judge (default OpenAI via env) produce 0–5 dimension scores; results sort by total score then latency.
          </p>
          <div className="space-y-2 text-xs">
            <label className="block text-slate-400">Prompt</label>
            <textarea
              className="w-full min-h-[72px] rounded border border-slate-600 bg-slate-950 px-2 py-1 text-slate-100"
              value={bakeoffPrompt}
              onChange={(e) => setBakeoffPrompt(e.target.value)}
              disabled={bakeoffBusy}
            />
            <label className="block text-slate-400">Providers JSON (array of &#123; provider, model &#125;)</label>
            <textarea
              className="w-full min-h-[120px] font-mono rounded border border-slate-600 bg-slate-950 px-2 py-1 text-slate-100"
              value={bakeoffProvidersJson}
              onChange={(e) => setBakeoffProvidersJson(e.target.value)}
              disabled={bakeoffBusy}
            />
            <div className="flex gap-2 items-center">
              <button
                type="button"
                disabled={bakeoffBusy}
                onClick={async () => {
                  setBakeoffErr(null)
                  setBakeoffResponse(null)
                  let providers: Array<{ provider: string; model: string }>
                  try {
                    const parsed = JSON.parse(bakeoffProvidersJson.trim())
                    if (!Array.isArray(parsed)) throw new Error('providers must be a JSON array')
                    providers = parsed.map((x: unknown) => {
                      if (!x || typeof x !== 'object') throw new Error('each entry must be an object')
                      const o = x as Record<string, unknown>
                      const provider = String(o.provider ?? '').trim()
                      if (!provider) throw new Error('each entry needs provider')
                      return { provider, model: String(o.model ?? '') }
                    })
                  } catch (e) {
                    setBakeoffErr(e instanceof Error ? e.message : 'Invalid providers JSON')
                    return
                  }
                  setBakeoffBusy(true)
                  try {
                    const res = await fetch('/studio/attachment-lane/bakeoff', {
                      method: 'POST',
                      credentials: 'include',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        lane: BAKEOFF_LANE,
                        prompt: bakeoffPrompt.trim(),
                        providers,
                        score_bakeoff: true,
                      }),
                    })
                    const data = await res.json().catch(() => ({}))
                    if (!res.ok) {
                      const d = typeof data?.detail === 'string' ? data.detail : JSON.stringify(data?.detail ?? data)
                      throw new Error(d || `Bakeoff failed (${res.status})`)
                    }
                    setBakeoffResponse(data as BakeoffResponse)
                  } catch (e) {
                    setBakeoffErr(e instanceof Error ? e.message : 'Bakeoff failed')
                  } finally {
                    setBakeoffBusy(false)
                  }
                }}
                className="px-3 py-1.5 rounded bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-sm text-white"
              >
                {bakeoffBusy ? 'Running…' : 'Run bakeoff'}
              </button>
              {bakeoffErr && <span className="text-red-300">{bakeoffErr}</span>}
            </div>
            {bakeoffResponse && (
              <div className="mt-3 space-y-2">
                <div className="text-slate-400">
                  <span className="text-slate-500">principal:</span> {bakeoffResponse.principal_ref} ·{' '}
                  <span className="text-slate-500">namespace:</span> {bakeoffResponse.credential_namespace}
                  {bakeoffResponse.scoring && (
                    <span className="block mt-1 text-slate-500">
                      judge: {bakeoffResponse.scoring.judge_provider}/{bakeoffResponse.scoring.judge_model}{' '}
                      {bakeoffResponse.scoring.scoring_enabled === false ? '(disabled)' : ''}
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                  {sortedBakeoffResults.map((row, i) => (
                    <div
                      key={`${row.provider}-${row.model ?? ''}-${i}`}
                      className={`rounded border p-2 ${row.ok ? 'border-emerald-800/80' : 'border-amber-900/60'}`}
                    >
                      <div className="font-semibold text-slate-200 flex flex-wrap gap-x-2 items-baseline">
                        <span>
                          {row.provider}
                          {row.model != null && row.model !== '' ? ` / ${row.model}` : ''}
                        </span>
                        <span className="text-amber-300 font-mono text-[11px]">
                          total {(row.total_score ?? 0)}/25
                        </span>
                        <span className="text-slate-500 font-normal text-[11px]">
                          {row.latency_ms != null ? `${row.latency_ms} ms` : '—'}
                        </span>
                        <span className={`font-normal text-[11px] ${row.ok ? 'text-emerald-400' : 'text-amber-400'}`}>
                          {row.ok ? 'ok' : 'failed'}
                        </span>
                      </div>
                      <div className="mt-1 text-[10px] text-slate-500 font-mono">
                        g{row.grounding_score ?? 0} · s{row.structure_score ?? 0} · sp{row.specificity_score ?? 0} · c
                        {row.constraint_obedience_score ?? 0} · u{row.usefulness_score ?? 0}
                      </div>
                      {row.score_notes && (
                        <p className="mt-1 text-[11px] text-slate-400 whitespace-pre-wrap">{row.score_notes}</p>
                      )}
                      {row.suggested_default_model && (
                        <p className="mt-1 text-[11px] text-cyan-300">
                          Try current default model: <code className="text-cyan-200">{row.suggested_default_model}</code>
                        </p>
                      )}
                      {row.error && (
                        <pre className="mt-1 whitespace-pre-wrap text-amber-200/90 text-[11px]">{row.error}</pre>
                      )}
                      {row.output_preview && (
                        <pre className="mt-1 whitespace-pre-wrap text-slate-300 text-[11px]">{row.output_preview}</pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
        <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
          <h2 className="font-medium mb-2">Provider default policy (read-only)</h2>
          <p className="text-xs text-slate-400 mb-3">
            Normalized view of implicit defaults, policy JSON excerpts, and per-plane baselines. Does not change execution.
          </p>
          {!providerPolicy && <div className="text-sm text-slate-400">Loading…</div>}
          {providerPolicy && (
            <div className="space-y-4 text-xs">
              <div>
                <div className="text-slate-400 mb-1">Fallback order (conceptual)</div>
                <ul className="list-disc list-inside text-slate-300 space-y-1">
                  {(providerPolicy.fallback_order_explanation ?? []).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="text-slate-400 mb-1">Example: workspace_council intent (policy merge only)</div>
                <pre className="whitespace-pre-wrap rounded border border-slate-800 px-2 py-2">
                  {JSON.stringify(providerPolicy.example_routing_intent_workspace_council ?? {}, null, 2)}
                </pre>
              </div>
              <div>
                <div className="text-slate-400 mb-1">Implicit sources (where defaults live)</div>
                <div className="space-y-2">
                  {(providerPolicy.implicit_default_sources ?? []).map((s) => (
                    <div key={String(s.id)} className="rounded border border-slate-800 p-2">
                      <div className="font-semibold text-amber-300">{String(s.id)}</div>
                      <div className="text-slate-300">{String(s.summary ?? '')}</div>
                      {Array.isArray(s.code_refs) && (
                        <div className="text-slate-500 mt-1">
                          {(s.code_refs as string[]).join(' · ')}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-slate-400 mb-1">Planes (account auth / anonymous / system)</div>
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-2">
                  {Object.entries(planes).map(([k, pl]) => (
                    <div key={k} className="rounded border border-slate-800 p-2">
                      <div className="font-semibold text-slate-100">{k}</div>
                      <div className="text-slate-400">principal_ref: {String(pl.principal_ref ?? '')}</div>
                      <pre className="mt-1 whitespace-pre-wrap text-[11px]">{JSON.stringify(pl.implicit_general, null, 2)}</pre>
                      <pre className="mt-1 whitespace-pre-wrap text-[11px]">{JSON.stringify(pl.implicit_council, null, 2)}</pre>
                    </div>
                  ))}
                </div>
              </div>
              {cur && (
                <div>
                  <div className="text-slate-400 mb-1">Current session (this admin user)</div>
                  <pre className="whitespace-pre-wrap rounded border border-slate-800 px-2 py-2 mb-2">
                    {JSON.stringify(cur.live_profile_snippet ?? {}, null, 2)}
                  </pre>
                  <div className="overflow-auto">
                    <table className="w-full text-[11px]">
                      <thead className="text-slate-400">
                        <tr>
                          <th className="text-left p-1">Provider</th>
                          <th className="text-left p-1">Gate</th>
                          <th className="text-left p-1">Configured</th>
                          <th className="text-left p-1">Usable</th>
                        </tr>
                      </thead>
                      <tbody>
                        {usable.map((row) => (
                          <tr key={String(row.provider_id)} className="border-t border-slate-800">
                            <td className="p-1">{String(row.display_name ?? row.provider_id)}</td>
                            <td className="p-1">{row.prefs_gate_ok ? 'ok' : String(row.prefs_gate_detail ?? 'blocked')}</td>
                            <td className="p-1">{row.configured_for_credentials ? 'yes' : 'no'}</td>
                            <td className="p-1">{row.usable_for_execution ? 'yes' : 'no'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
        <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 text-xs text-slate-400">
          <p>
            POST <code className="text-amber-300">/run</code> responses include <code className="text-amber-300">provider_resolution</code>
            : seam vs council requested/effective fields and fallback reasons (no behavior change).
          </p>
        </section>
      </div>
    )
  }

  const renderTeacherTab = () => (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 space-y-3">
        <h2 className="font-medium">Teacher Controls</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 text-sm">
          <label className="text-slate-300">Mode</label>
          <select
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1"
            value={settings.teacher_mode}
            onChange={(e) => setSettings((s) => ({ ...s, teacher_mode: e.target.value as TeacherMode }))}
          >
            <option value="off">off</option>
            <option value="shadow">shadow</option>
            <option value="warn">warn</option>
            <option value="veto">veto</option>
            <option value="replace">replace (admin)</option>
          </select>
          <label className="text-slate-300">Teacher provider</label>
          <input
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1"
            value={settings.teacher_provider ?? ''}
            onChange={(e) => setSettings((s) => ({ ...s, teacher_provider: e.target.value }))}
          />
          <label className="text-slate-300">Teacher model</label>
          <input
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1"
            value={settings.teacher_model ?? ''}
            onChange={(e) => setSettings((s) => ({ ...s, teacher_model: e.target.value }))}
          />
          <label className="text-slate-300">Prompt version</label>
          <input
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1"
            value={settings.teacher_prompt_version ?? 'council_teacher_v1'}
            onChange={(e) => setSettings((s) => ({ ...s, teacher_prompt_version: e.target.value }))}
          />
          <label className="text-slate-300">Council mode override</label>
          <select
            className="bg-slate-800 border border-slate-600 rounded px-2 py-1"
            value={settings.capability_teacher_modes?.council ?? ''}
            onChange={(e) => {
              const v = e.target.value
              setSettings((s) => {
                const next = { ...(s.capability_teacher_modes ?? {}) }
                if (!v) delete next.council
                else next.council = v
                return { ...s, capability_teacher_modes: next }
              })
            }}
          >
            <option value="">(use default mode above)</option>
            <option value="off">off</option>
            <option value="shadow">shadow</option>
            <option value="warn">warn</option>
            <option value="veto">veto</option>
            <option value="replace">replace</option>
          </select>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 text-sm border-t border-slate-700 pt-3">
          <div className="col-span-2 text-slate-400 text-xs">Attachment roles (defaults when POST /run omits native_provider)</div>
          <label className="text-slate-300">Main (cloud)</label>
          <div className="flex gap-1">
            <input
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 flex-1"
              placeholder="provider"
              value={settings.main_attachment_provider ?? ''}
              onChange={(e) => setSettings((s) => ({ ...s, main_attachment_provider: e.target.value }))}
            />
            <input
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 flex-1"
              placeholder="model"
              value={settings.main_attachment_model ?? ''}
              onChange={(e) => setSettings((s) => ({ ...s, main_attachment_model: e.target.value }))}
            />
          </div>
          <label className="text-slate-300">Local (privacy lane)</label>
          <div className="flex gap-1">
            <input
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 flex-1"
              placeholder="provider"
              value={settings.local_attachment_provider ?? ''}
              onChange={(e) => setSettings((s) => ({ ...s, local_attachment_provider: e.target.value }))}
            />
            <input
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 flex-1"
              placeholder="model"
              value={settings.local_attachment_model ?? ''}
              onChange={(e) => setSettings((s) => ({ ...s, local_attachment_model: e.target.value }))}
            />
          </div>
          <label className="text-slate-300">Experimental Google</label>
          <div className="flex gap-1">
            <input
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 flex-1"
              value={settings.experimental_google_provider ?? ''}
              onChange={(e) => setSettings((s) => ({ ...s, experimental_google_provider: e.target.value }))}
            />
            <input
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 flex-1"
              value={settings.experimental_google_model ?? ''}
              onChange={(e) => setSettings((s) => ({ ...s, experimental_google_model: e.target.value }))}
            />
          </div>
          <label className="text-slate-300">Experimental xAI</label>
          <div className="flex gap-1">
            <input
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 flex-1"
              value={settings.experimental_xai_provider ?? ''}
              onChange={(e) => setSettings((s) => ({ ...s, experimental_xai_provider: e.target.value }))}
            />
            <input
              className="bg-slate-800 border border-slate-600 rounded px-2 py-1 flex-1"
              value={settings.experimental_xai_model ?? ''}
              onChange={(e) => setSettings((s) => ({ ...s, experimental_xai_model: e.target.value }))}
            />
          </div>
        </div>
        <div>
          <label className="text-slate-300 text-sm">Teacher prompt overlay</label>
          <textarea
            className="mt-1 w-full bg-slate-800 border border-slate-600 rounded px-2 py-2 text-xs"
            rows={4}
            value={settings.teacher_prompt_overlay ?? ''}
            onChange={(e) => setSettings((s) => ({ ...s, teacher_prompt_overlay: e.target.value }))}
          />
        </div>
        <button
          type="button"
          onClick={saveSettings}
          disabled={saving}
          className="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 disabled:opacity-60 text-sm"
        >
          {saving ? 'Saving…' : 'Save teacher settings'}
        </button>
      </section>

      <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 space-y-3">
        <h2 className="font-medium">Council Prompt Components</h2>
        <div className="text-xs text-slate-300 space-y-2 max-h-80 overflow-auto">
          <div>
            <div className="text-slate-400 mb-1">Built-in seat contracts</div>
            {seatContracts.map(([name, v]) => (
              <div key={name} className="mb-2">
                <div className="font-semibold text-amber-300">{name}</div>
                <pre className="whitespace-pre-wrap">{JSON.stringify(v, null, 2)}</pre>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )

  const renderRunsTab = () => (
    <section className="rounded-xl border border-slate-700 bg-slate-900/60 p-4">
      <h2 className="font-medium mb-2">Recent Council Teacher Artifacts</h2>
      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead className="text-slate-400">
            <tr>
              <th className="text-left p-1">Time</th>
              <th className="text-left p-1">Mode</th>
              <th className="text-left p-1">Veto</th>
              <th className="text-left p-1">Warn</th>
              <th className="text-left p-1">Final src</th>
              <th className="text-left p-1">Native</th>
              <th className="text-left p-1">Teacher</th>
              <th className="text-left p-1">Same decision</th>
              <th className="text-left p-1">Same next</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr
                key={r.id}
                className={`border-t border-slate-800 cursor-pointer ${selectedRunId === r.id ? 'bg-slate-800/60' : 'hover:bg-slate-800/30'}`}
                onClick={async () => {
                  setSelectedRunId(r.id)
                  setRunTab('overview')
                  setSelectedNativeSeat(0)
                  setSelectedTeacherSeat(0)
                  const res = await fetch(`/studio/council/runs/${encodeURIComponent(r.id)}`, { credentials: 'include' })
                  if (res.ok) {
                    const d = await res.json()
                    setSelectedRunDetail(d)
                  }
                }}
              >
                <td className="p-1">{r.created_at}</td>
                <td className="p-1">{r.teacher_enforcement_mode ?? r.teacher_mode}</td>
                <td className="p-1">{r.teacher_vetoed ? 'yes' : '—'}</td>
                <td className="p-1">{r.teacher_warning ? 'yes' : '—'}</td>
                <td className="p-1">{r.teacher_final_source ?? '—'}</td>
                <td className="p-1">{`${r.native_provider ?? '—'} / ${r.native_model ?? '—'}`}</td>
                <td className="p-1">{`${r.teacher_provider_effective ?? '—'} / ${r.teacher_model_effective ?? '—'}`}</td>
                <td className="p-1">{r.comparison?.same_decision == null ? '—' : r.comparison.same_decision ? 'yes' : 'no'}</td>
                <td className="p-1">{r.comparison?.same_next_move == null ? '—' : r.comparison.same_next_move ? 'yes' : 'no'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selectedRunDetail && (
        <div className="mt-4 rounded border border-slate-700 p-3 space-y-3">
          <div className="flex gap-2">
            {(['overview', 'native', 'teacher', 'synthesis', 'compare'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setRunTab(t)}
                className={`px-2 py-1 rounded text-xs ${runTab === t ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-200'}`}
              >
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>

          {runTab === 'overview' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 text-xs">
              <div><span className="text-slate-400">run id:</span> {selectedRunDetail.id}</div>
              <div><span className="text-slate-400">timestamp:</span> {selectedRunDetail.created_at}</div>
              <div><span className="text-slate-400">question:</span> {String(selectedRunDetail.native_artifact?.question ?? '—')}</div>
              <div><span className="text-slate-400">execution:</span> {selectedRunDetail.execution_scope ?? '—'} / {selectedRunDetail.execution_principal_ref ?? '—'}</div>
              <div><span className="text-slate-400">teacher mode:</span> {selectedRunDetail.teacher_mode}</div>
              <div><span className="text-slate-400">enforcement:</span> {selectedRunDetail.teacher_enforcement_mode ?? selectedRunDetail.teacher_mode}</div>
              <div><span className="text-slate-400">vetoed:</span> {selectedRunDetail.teacher_vetoed ? 'yes' : 'no'}</div>
              <div><span className="text-slate-400">warning:</span> {selectedRunDetail.teacher_warning ? 'yes' : 'no'}</div>
              <div><span className="text-slate-400">reason codes:</span> {(selectedRunDetail.teacher_reason_codes ?? []).join(', ') || '—'}</div>
              <div className="lg:col-span-2"><span className="text-slate-400">teacher notes:</span> {selectedRunDetail.teacher_notes ?? '—'}</div>
              <div><span className="text-slate-400">final policy:</span> {selectedRunDetail.final_selection_policy ?? '—'}</div>
              <div><span className="text-slate-400">native:</span> {selectedRunDetail.native_provider ?? '—'} / {selectedRunDetail.native_model ?? '—'}</div>
              <div><span className="text-slate-400">teacher:</span> {selectedRunDetail.teacher_provider_effective ?? '—'} / {selectedRunDetail.teacher_model_effective ?? '—'}</div>
              <div><span className="text-slate-400">selected source:</span> {String(selectedRunDetail.teacher_run_debug?.selection?.selected_source ?? selectedRunDetail.native_run_debug?.selection?.selected_source ?? 'unknown')}</div>
            </div>
          )}

          {runTab === 'native' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 text-xs">
              <div className="rounded border border-slate-800 p-2 space-y-1">
                {(selectedRunDetail.native_run_debug?.seats ?? []).map((s, idx) => (
                  <button
                    key={`nseat-${idx}`}
                    type="button"
                    onClick={() => setSelectedNativeSeat(idx)}
                    className={`w-full text-left px-2 py-1 rounded ${selectedNativeSeat === idx ? 'bg-amber-700/40' : 'bg-slate-800/60'}`}
                  >
                    #{s.seat_index ?? idx} {s.seat_name ?? 'Seat'} ({s.seat_kind ?? 'unknown'})
                  </button>
                ))}
              </div>
              <div className="lg:col-span-2 rounded border border-slate-800 p-2 space-y-2">
                {(() => {
                  const s = (selectedRunDetail.native_run_debug?.seats ?? [])[selectedNativeSeat]
                  if (!s) return <div className="text-slate-400">No native seat detail.</div>
                  return (
                    <>
                      <div><span className="text-slate-400">seat id:</span> {s.seat_id ?? '—'}</div>
                      <div><span className="text-slate-400">raw perspective:</span><pre className="whitespace-pre-wrap">{JSON.stringify(s.raw_perspective_definition ?? null, null, 2)}</pre></div>
                      <div><span className="text-slate-400">normalized persona:</span><pre className="whitespace-pre-wrap">{s.normalized_persona_block ?? ''}</pre></div>
                      <div><span className="text-slate-400">prompt decomposition:</span><pre className="whitespace-pre-wrap">{JSON.stringify(s.prompt_decomposition ?? {}, null, 2)}</pre></div>
                      <div><span className="text-slate-400">full compiled prompt:</span><pre className="whitespace-pre-wrap">{s.full_compiled_prompt ?? s.compiled_prompt ?? ''}</pre></div>
                      <div><span className="text-slate-400">raw output:</span><pre className="whitespace-pre-wrap">{s.raw_output ?? ''}</pre></div>
                      <div><span className="text-slate-400">parsed SeatJudgment:</span><pre className="whitespace-pre-wrap">{JSON.stringify(s.parsed_seat_judgment ?? {}, null, 2)}</pre></div>
                    </>
                  )
                })()}
              </div>
            </div>
          )}

          {runTab === 'teacher' && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 text-xs">
              <div className="rounded border border-slate-800 p-2 space-y-1">
                {(selectedRunDetail.teacher_run_debug?.seats ?? []).map((s, idx) => (
                  <button
                    key={`tseat-${idx}`}
                    type="button"
                    onClick={() => setSelectedTeacherSeat(idx)}
                    className={`w-full text-left px-2 py-1 rounded ${selectedTeacherSeat === idx ? 'bg-amber-700/40' : 'bg-slate-800/60'}`}
                  >
                    #{s.seat_index ?? idx} {s.seat_name ?? 'Seat'} ({s.seat_kind ?? 'unknown'})
                  </button>
                ))}
              </div>
              <div className="lg:col-span-2 rounded border border-slate-800 p-2 space-y-2">
                {(() => {
                  const s = (selectedRunDetail.teacher_run_debug?.seats ?? [])[selectedTeacherSeat]
                  if (!s) return <div className="text-slate-400">No teacher seat detail.</div>
                  return (
                    <>
                      <div><span className="text-slate-400">seat id:</span> {s.seat_id ?? '—'}</div>
                      <div><span className="text-slate-400">raw perspective:</span><pre className="whitespace-pre-wrap">{JSON.stringify(s.raw_perspective_definition ?? null, null, 2)}</pre></div>
                      <div><span className="text-slate-400">normalized persona:</span><pre className="whitespace-pre-wrap">{s.normalized_persona_block ?? ''}</pre></div>
                      <div><span className="text-slate-400">prompt decomposition:</span><pre className="whitespace-pre-wrap">{JSON.stringify(s.prompt_decomposition ?? {}, null, 2)}</pre></div>
                      <div><span className="text-slate-400">full compiled prompt:</span><pre className="whitespace-pre-wrap">{s.full_compiled_prompt ?? s.compiled_prompt ?? ''}</pre></div>
                      <div><span className="text-slate-400">raw output:</span><pre className="whitespace-pre-wrap">{s.raw_output ?? ''}</pre></div>
                      <div><span className="text-slate-400">parsed SeatJudgment:</span><pre className="whitespace-pre-wrap">{JSON.stringify(s.parsed_seat_judgment ?? {}, null, 2)}</pre></div>
                    </>
                  )
                })()}
              </div>
            </div>
          )}

          {runTab === 'synthesis' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 text-xs">
              <div className="rounded border border-slate-800 p-2">
                <div className="font-semibold mb-1">Native synthesis</div>
                <pre className="whitespace-pre-wrap">{JSON.stringify(selectedRunDetail.native_run_debug?.synthesis ?? {}, null, 2)}</pre>
              </div>
              <div className="rounded border border-slate-800 p-2">
                <div className="font-semibold mb-1">Teacher synthesis</div>
                <pre className="whitespace-pre-wrap">{JSON.stringify(selectedRunDetail.teacher_run_debug?.synthesis ?? {}, null, 2)}</pre>
              </div>
              <div className="rounded border border-slate-800 p-2 lg:col-span-2">
                <div className="font-semibold mb-1">Final selected synthesis/source</div>
                <pre className="whitespace-pre-wrap">
                  {JSON.stringify({
                    selected_source: selectedRunDetail.teacher_run_debug?.selection?.selected_source ?? selectedRunDetail.native_run_debug?.selection?.selected_source ?? 'unknown',
                    final_selection_policy: selectedRunDetail.final_selection_policy ?? null,
                    native_synthesis_text: selectedRunDetail.native_artifact?.synthesis_text ?? null,
                    teacher_synthesis_text: selectedRunDetail.teacher_artifact?.synthesis_text ?? null,
                  }, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {runTab === 'compare' && (
            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                <div><span className="text-slate-400">same_decision:</span> {String(selectedRunDetail.comparison?.same_decision ?? '—')}</div>
                <div><span className="text-slate-400">same_next_move:</span> {String(selectedRunDetail.comparison?.same_next_move ?? '—')}</div>
              </div>
              <div>
                <span className="text-slate-400">comparison notes:</span>
                <pre className="whitespace-pre-wrap">{String(selectedRunDetail.comparison?.notes ?? '')}</pre>
              </div>
              <div>
                <span className="text-slate-400">manual winner selector (placeholder):</span>
                <div className="mt-1 flex gap-2">
                  <button type="button" className="px-2 py-1 rounded bg-slate-800">Native</button>
                  <button type="button" className="px-2 py-1 rounded bg-slate-800">Teacher</button>
                  <button type="button" className="px-2 py-1 rounded bg-slate-800">Tie/Merged</button>
                </div>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <div className="rounded border border-slate-800 p-2">
                  <div className="font-semibold mb-1">Native output</div>
                  <pre className="whitespace-pre-wrap">{selectedRunDetail.native_text ?? ''}</pre>
                </div>
                <div className="rounded border border-slate-800 p-2">
                  <div className="font-semibold mb-1">Teacher output</div>
                  <pre className="whitespace-pre-wrap">{selectedRunDetail.teacher_text ?? ''}</pre>
                </div>
              </div>
              <div className="rounded border border-slate-800 p-2">
                <div className="font-semibold mb-1">Line diff (native vs teacher)</div>
                <pre className="whitespace-pre-wrap">
                  {buildSimpleDiff(selectedRunDetail.native_text ?? '', selectedRunDetail.teacher_text ?? '') || 'No line-level differences.'}
                </pre>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )

  if (authState === 'loading') return <div className="p-6 text-slate-200">Loading studio…</div>
  if (authState === 'login') return <AuthGate onLogin={onLogin} />
  if (authState === 'denied') {
    return (
      <div data-testid="studio-admin-denied" className="min-h-screen bg-slate-900 text-slate-100 p-6">
        <div className="max-w-3xl mx-auto rounded-xl border border-slate-700 bg-slate-800/60 p-6 space-y-3">
          <h1 className="text-xl font-semibold">Zenaf Studio</h1>
          <p className="text-red-300">This surface requires admin access.</p>
          <button
            type="button"
            onClick={async () => {
              await logoutSession().catch(() => {})
              setAuthState('login')
            }}
            className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-sm"
          >
            Sign in as admin
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Zenaf Studio</h1>
            <p className="text-xs text-slate-400">System index + council supervision console</p>
          </div>
          <div className="text-xs text-slate-400">{me?.display_name} · {me?.email}</div>
        </div>

        {err && <div className="rounded border border-red-700 bg-red-900/20 px-3 py-2 text-red-200 text-sm">{err}</div>}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setActiveTab('index')}
            className={`px-3 py-1.5 rounded text-sm ${activeTab === 'index' ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-200'}`}
          >
            Index
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('teacher')}
            className={`px-3 py-1.5 rounded text-sm ${activeTab === 'teacher' ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-200'}`}
          >
            Teacher Controls
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('runs')}
            className={`px-3 py-1.5 rounded text-sm ${activeTab === 'runs' ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-200'}`}
          >
            Recent Runs
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('policy')}
            className={`px-3 py-1.5 rounded text-sm ${activeTab === 'policy' ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-200'}`}
          >
            Provider policy
          </button>
        </div>

        {activeTab === 'index' && renderIndexTab()}
        {activeTab === 'teacher' && renderTeacherTab()}
        {activeTab === 'runs' && renderRunsTab()}
        {activeTab === 'policy' && renderPolicyTab()}
      </div>
    </div>
  )
}

