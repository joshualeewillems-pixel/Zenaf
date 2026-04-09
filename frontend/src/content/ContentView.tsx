import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import type { ContentBrief, ContentBriefPayload, ContentBriefStatus, ContentConfig } from './types'
import { DEFAULT_BRIEF_PAYLOAD, apiBriefToBrief, briefToRunPayload } from './types'
import type { Initiative } from '../vision-execution/types'
import type { Project } from '../vision-execution/types'
import type { AiActionTrace } from '../ai-actions/types'
import { ContentBriefEditor } from './ContentBriefEditor'
import { ContentOutputsPane } from './ContentOutputsPane'
import type { OutputTabId } from './ContentOutputsPane'
import { ContentExportPane } from './ContentExportPane'
import { TranscriptSorter } from './TranscriptSorter'
import { contentActionIntentForRun, contentRunRoutingContext } from './contentRoutingContext'
import {
  buildContentBriefGenerationSnapshot,
  emitContentBriefDistillTrace,
  emitContentBriefTraceFromRun,
  recordContentTraceOutcome,
} from './contentRunWithTrace'

interface ContentRunResponse {
  ok?: boolean
  result?: unknown
  error?: string
  detail?: string
  model_used?: string | null
  provider_used?: string | null
  routing_override_active?: boolean | null
  execution_blocked?: boolean | null
  privacy_block_reason?: string | null
}

const VE_PATH = '/vision-execution'
const BRIEFS_PATH = '/vision-execution/content-briefs'

/** Shown when ContentView renders its own header (not inside ContentFrontDoor). */
const CONTENT_TAB_SUBTITLE =
  'Narrative packages are stored as content briefs: link initiatives and projects, generate script and newsletter drafts, and hand off to tasks. In-tab journaling, council-as-record, richer artifact types, and registries are roadmap — see docs/02_ACTIVE_DESIGN/CONTENT_NARRATIVE_REGISTRAR_ROADMAP.md.'

function statusBadgeClass(status: ContentBriefStatus): string {
  switch (status) {
    case 'in_production':
      return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50'
    case 'generated':
      return 'bg-amber-500/20 text-amber-300 border-amber-500/50'
    default:
      return 'bg-slate-500/20 text-slate-300 border-slate-500/50'
  }
}

const ZERO_STATE_PLACEHOLDERS = [
  'e.g. Reflection after a hard week — what shifted and what you need next',
  'e.g. Council session notes to tie to an initiative before you shape a script',
  'e.g. Origin story for a talk; start as a package then generate script',
]

export interface ContentViewProps {
  /** Legacy: pass apiBase when not using config. */
  apiBase?: string
  /** Preferred: apiBase + optional veApiBase for Content front door. */
  config?: ContentConfig
  /** When false, TranscriptSorter is not rendered (e.g. when used inside ContentFrontDoor). Default true. */
  showTranscriptSorter?: boolean
  /** When true, the internal "Content" / orchestration header is not shown (e.g. front door has its own). Default false. */
  hideHeader?: boolean
  /** Called when zero state (no briefs) changes so parent can hide e.g. transcript section. */
  onZeroState?: (isZero: boolean) => void
}

function resolveContentUrls(config?: ContentConfig | null, apiBase?: string): { runBase: string; veApi: string; briefsApi: string; transcriptBase: string } {
  const base = config?.apiBase ?? apiBase ?? ''
  const veBase = config ? (config.veApiBase ?? config.apiBase) : (apiBase ?? '')
  return {
    runBase: base,
    veApi: veBase ? `${veBase.replace(/\/$/, '')}${VE_PATH}` : VE_PATH,
    briefsApi: veBase ? `${veBase.replace(/\/$/, '')}${BRIEFS_PATH}` : BRIEFS_PATH,
    transcriptBase: base,
  }
}

export function ContentView({ apiBase, config, showTranscriptSorter = true, hideHeader = false, onZeroState }: ContentViewProps) {
  const urls = useMemo(() => resolveContentUrls(config, apiBase), [config, apiBase])
  const { runBase, briefsApi, veApi, transcriptBase } = urls

  const [briefs, setBriefs] = useState<ContentBrief[]>([])
  const [selectedBriefId, setSelectedBriefId] = useState<string | null>(null)
  const [brief, setBrief] = useState<ContentBrief | null>(null)
  const [scriptText, setScriptText] = useState('')
  const [newsletterText, setNewsletterText] = useState('')
  const [outputTab, setOutputTab] = useState<OutputTabId>('script')
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [initiatives, setInitiatives] = useState<Initiative[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const triggerFirstGenerateRef = useRef(false)
  /** Latest successful brief `/run` trace for outcome hooks (copy / export / regenerate). */
  const contentOutcomeTargetRef = useRef<{
    trace: AiActionTrace
    briefId: string
    outputKind: 'script' | 'newsletter'
  } | null>(null)

  const fetchBriefs = useCallback(async () => {
    try {
      const res = await fetch(briefsApi, { credentials: 'include' })
      const data = res.ok ? await res.json() : []
      const list = Array.isArray(data) ? data.map((api: { id: string; title: string; status: string; payload: ContentBriefPayload }) => apiBriefToBrief(api)) : []
      setBriefs(list)
      setSelectedBriefId((prev) => (prev && list.some((b: ContentBrief) => b.id === prev)) ? prev : (list[0]?.id ?? null))
    } catch {
      setBriefs([])
    }
  }, [briefsApi])

  useEffect(() => {
    fetchBriefs()
  }, [fetchBriefs])

  const isZeroState = briefs.length === 0
  useEffect(() => {
    onZeroState?.(isZeroState)
  }, [isZeroState, onZeroState])

  useEffect(() => {
    if (!selectedBriefId) {
      setBrief(null)
      return
    }
    const found = briefs.find((b) => b.id === selectedBriefId)
    if (found) {
      setBrief(found)
      return
    }
    fetch(`${briefsApi}/${selectedBriefId}`, { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((api) => {
        if (api) setBrief(apiBriefToBrief(api))
        else setBrief(null)
      })
      .catch(() => setBrief(null))
  }, [selectedBriefId, briefs])

  useEffect(() => {
    fetch(`${veApi}/initiatives`, { credentials: 'include' }).then((res) => (res.ok ? res.json() : [])).then((d) => setInitiatives(Array.isArray(d) ? d : [])).catch(() => setInitiatives([]))
    fetch(`${veApi}/projects`, { credentials: 'include' }).then((res) => (res.ok ? res.json() : [])).then((d) => setProjects(Array.isArray(d) ? d : [])).catch(() => setProjects([]))
  }, [])

  const saveBrief = useCallback((next: ContentBrief) => {
    if (!next.id) return
    const payload: ContentBriefPayload = {
      title: next.title,
      linked_initiative_id: next.linked_initiative_id,
      linked_project_id: next.linked_project_id,
      linked_task_ids: next.linked_task_ids ?? [],
      audience: next.audience,
      content_goal: next.content_goal,
      key_themes: next.key_themes ?? [],
      claims: next.claims ?? [],
      cta: next.cta,
      tone_voice: next.tone_voice,
      target_formats: next.target_formats ?? [],
      source_materials: next.source_materials ?? '',
      notes: next.notes ?? '',
    }
    fetch(`${briefsApi}/${next.id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: next.title, status: next.status, payload }),
    }).then(() => fetchBriefs())
  }, [fetchBriefs])

  const handleBriefChange = useCallback((next: ContentBrief) => {
    setBrief(next)
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    saveTimeoutRef.current = setTimeout(() => saveBrief(next), 600)
  }, [saveBrief])

  const handleCreateBrief = useCallback(async () => {
    setGenerateError(null)
    try {
      const res = await fetch(briefsApi, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Untitled brief', status: 'draft', payload: DEFAULT_BRIEF_PAYLOAD }),
      })
      const api = await res.json().catch(() => null)
      if (!res.ok || !api?.id) throw new Error(api?.detail || 'Create failed')
      const newBrief = apiBriefToBrief(api)
      setBriefs((prev) => [newBrief, ...prev])
      setSelectedBriefId(newBrief.id)
      setBrief(newBrief)
      setScriptText('')
      setNewsletterText('')
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : 'Create failed')
    }
  }, [briefsApi])

  const handleCreateFromZeroState = useCallback(
    async (userInput: string) => {
      const trimmed = userInput.trim() || 'My first narrative package'
      const title = trimmed.slice(0, 80)
      const payload: ContentBriefPayload = {
        ...DEFAULT_BRIEF_PAYLOAD,
        title,
        content_goal: trimmed,
      }
      setGenerateError(null)
      setGenerating(true)
      try {
        const res = await fetch(briefsApi, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, status: 'draft', payload }),
        })
        const api = await res.json().catch(() => null)
        if (!res.ok || !api?.id) throw new Error(api?.detail || 'Create failed')
        const newBrief = apiBriefToBrief(api)
        setBriefs((prev) => [newBrief, ...prev])
        setSelectedBriefId(newBrief.id)
        setBrief(newBrief)
        setScriptText('')
        setNewsletterText('')
        triggerFirstGenerateRef.current = true
      } catch (e) {
        setGenerateError(e instanceof Error ? e.message : 'Create failed')
        setGenerating(false)
      }
    },
    [briefsApi]
  )

  const runContentGenerate = useCallback(
    async (outputType: 'script' | 'newsletter', refinement?: string) => {
      if (!brief) return
      setGenerateError(null)
      setGenerating(true)
      try {
        const payload = briefToRunPayload(brief, outputType)
        const hadPriorOutput =
          outputType === 'script' ? Boolean(scriptText?.trim()) : Boolean(newsletterText?.trim())
        const actionIntent = contentActionIntentForRun(outputType, { hadPriorOutput, refinement })
        const body: Record<string, unknown> = {
          mode: outputType === 'script' ? 'content_script' : 'content_newsletter',
          params: {
            content_brief: payload,
            content_source: brief.source_materials || '',
            content_output_type: outputType,
          },
          routing_context: contentRunRoutingContext(actionIntent),
        }
        if (refinement) (body.params as Record<string, unknown>).content_refinement = refinement
        const res = await fetch(`${runBase}/run`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        const data = (await res.json().catch(() => ({}))) as ContentRunResponse
        if (!res.ok) {
          const err = data.detail || data.error || res.statusText
          setGenerateError(typeof err === 'string' ? err : JSON.stringify(err))
          return
        }
        if (data.execution_blocked) {
          setGenerateError(
            data.error ||
              'Generation was blocked by your privacy settings. No model was used. Use a local model or change Privacy mode in Settings.',
          )
          return
        }
        if (data.ok === false) {
          setGenerateError(data.error || 'Generation failed')
          return
        }
        const text = typeof data.result === 'string' ? data.result : ''
        if (outputType === 'script') setScriptText(text)
        else setNewsletterText(text)
        try {
          const tr = emitContentBriefTraceFromRun({
            action_intent: actionIntent,
            brief_id: brief.id,
            input_snapshot: buildContentBriefGenerationSnapshot({
              briefId: brief.id,
              title: brief.title,
              outputType,
              refinement,
              sourceMaterialsLen: (brief.source_materials ?? '').length,
            }),
            output_text: text,
            resolved_model_used: data.model_used ?? undefined,
            resolved_provider_used: data.provider_used ?? undefined,
          })
          contentOutcomeTargetRef.current = {
            trace: tr,
            briefId: brief.id,
            outputKind: outputType,
          }
        } catch {
          /* trace must not affect Content UX */
        }
        await fetch(`${briefsApi}/${brief.id}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'generated' }),
        })
        fetchBriefs()
        if (brief) setBrief((prev) => (prev ? { ...prev, status: 'generated' } : null))
      } catch (e) {
        setGenerateError(e instanceof Error ? e.message : 'Request failed')
      } finally {
        setGenerating(false)
      }
    },
    [runBase, brief, fetchBriefs, briefsApi, scriptText, newsletterText]
  )

  const contentRecordRegenerateIntent = useCallback(
    (tab: OutputTabId) => {
      const hasText = tab === 'script' ? Boolean(scriptText?.trim()) : Boolean(newsletterText?.trim())
      if (!hasText || !brief?.id) return
      const w = contentOutcomeTargetRef.current
      if (!w || w.briefId !== brief.id || w.outputKind !== tab) return
      try {
        recordContentTraceOutcome(w.trace, 'edited')
      } catch {
        /* ignore */
      }
    },
    [brief?.id, scriptText, newsletterText],
  )

  const onContentCopyScriptOutcome = useCallback(() => {
    const w = contentOutcomeTargetRef.current
    if (!w || !brief?.id || w.briefId !== brief.id || w.outputKind !== 'script') return
    try {
      recordContentTraceOutcome(w.trace, 'copied')
    } catch {
      /* ignore */
    }
  }, [brief?.id])

  const onContentCopyNewsletterOutcome = useCallback(() => {
    const w = contentOutcomeTargetRef.current
    if (!w || !brief?.id || w.briefId !== brief.id || w.outputKind !== 'newsletter') return
    try {
      recordContentTraceOutcome(w.trace, 'copied')
    } catch {
      /* ignore */
    }
  }, [brief?.id])

  const onContentExportScriptOutcome = useCallback(() => {
    const w = contentOutcomeTargetRef.current
    if (!w || !brief?.id || w.briefId !== brief.id || w.outputKind !== 'script') return
    try {
      recordContentTraceOutcome(w.trace, 'applied')
    } catch {
      /* ignore */
    }
  }, [brief?.id])

  const onContentCreateTasksSuccess = useCallback(() => {
    const w = contentOutcomeTargetRef.current
    if (!w || !brief?.id || w.briefId !== brief.id) return
    try {
      recordContentTraceOutcome(w.trace, 'applied')
    } catch {
      /* ignore */
    }
  }, [brief?.id])

  const markBriefInProduction = useCallback(async () => {
    if (!brief?.id) return
    await fetch(`${briefsApi}/${brief.id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'in_production' }),
    })
    fetchBriefs()
    setBrief((p) => (p ? { ...p, status: 'in_production' } : null))
    const w = contentOutcomeTargetRef.current
    if (w?.briefId === brief.id) {
      try {
        recordContentTraceOutcome(w.trace, 'applied')
      } catch {
        /* ignore */
      }
    }
  }, [brief?.id, briefsApi, fetchBriefs])

  useEffect(() => {
    if (brief && triggerFirstGenerateRef.current) {
      triggerFirstGenerateRef.current = false
      runContentGenerate('script')
    }
  }, [brief, runContentGenerate])

  const createVETask = useCallback(async (projectId: string, title: string) => {
    const res = await fetch(`${veApi}/tasks`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, title: title || 'Untitled', status: 'Todo' }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || err.error || res.statusText)
    }
  }, [veApi])

  const linkedInitiative = brief?.linked_initiative_id ? initiatives.find((i) => i.id === brief.linked_initiative_id) : null
  const linkedProject = brief?.linked_project_id ? projects.find((p) => p.id === brief.linked_project_id) : null

  if (isZeroState) {
    return (
      <div className="flex-1 flex flex-col min-h-0">
        {!hideHeader && (
          <div className="p-4 border-b border-slate-700">
            <h2 className="text-xl font-semibold text-slate-100">Content</h2>
            <p className="text-slate-400 text-sm mt-1">{CONTENT_TAB_SUBTITLE}</p>
          </div>
        )}
        <div className="flex-1 min-h-0 overflow-auto flex items-center justify-center p-6">
          <div className="w-full max-w-xl">
            {generateError && (
              <div className="mb-4 rounded-lg bg-red-900/30 border border-red-700 text-red-200 text-sm p-3">
                {generateError}
              </div>
            )}
            <label htmlFor="content-zero-state-input" className="block text-sm font-medium text-slate-300 mb-2">
              Start a narrative package (content brief)
            </label>
            <textarea
              id="content-zero-state-input"
              data-testid="content-zero-state-input"
              placeholder={ZERO_STATE_PLACEHOLDERS[0]}
              title={ZERO_STATE_PLACEHOLDERS.join(' ')}
              rows={4}
              className="w-full rounded-xl border border-slate-600 bg-slate-800 text-slate-100 placeholder:text-slate-500 p-4 text-base focus:border-amber-500 focus:ring-1 focus:ring-amber-500 resize-none"
              disabled={generating}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  const target = e.target as HTMLTextAreaElement
                  if (target.value.trim()) handleCreateFromZeroState(target.value)
                }
              }}
            />
            <p className="mt-2 text-xs text-slate-500">
              {ZERO_STATE_PLACEHOLDERS.slice(1).join(' · ')}
            </p>
            <button
              type="button"
              onClick={() => {
                const el = document.getElementById('content-zero-state-input') as HTMLTextAreaElement | null
                const value = el?.value?.trim()
                if (value) handleCreateFromZeroState(value)
                else handleCreateFromZeroState('My first narrative package')
              }}
              disabled={generating}
              className="mt-4 w-full py-3 px-4 rounded-xl bg-amber-600 hover:bg-amber-500 disabled:bg-slate-600 disabled:text-slate-400 text-white font-medium text-base transition-colors"
            >
              {generating ? 'Creating and generating…' : 'Create package and draft script'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {!hideHeader && (
        <div className="p-4 border-b border-slate-700">
          <h2 className="text-xl font-semibold text-slate-100">Content</h2>
          <p className="text-slate-400 text-sm mt-1">{CONTENT_TAB_SUBTITLE}</p>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-auto p-4">
        {generateError && (
          <div className="mb-4 rounded-lg bg-red-900/30 border border-red-700 text-red-200 text-sm p-3">
            {generateError}
          </div>
        )}
        <div className="max-w-6xl mx-auto grid gap-4 lg:grid-cols-[340px_1fr_260px]">
          <aside className="rounded-xl border border-slate-600 bg-slate-800/80 overflow-hidden flex flex-col">
            <div className="p-3 border-b border-slate-700 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-slate-200">Briefs</h3>
                <p className="text-[10px] text-slate-500 mt-0.5 leading-tight">Narrative packages (API: content briefs)</p>
              </div>
              <button
                type="button"
                onClick={handleCreateBrief}
                className="px-2 py-1 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium"
              >
                + New brief
              </button>
            </div>
            <ul className="flex-1 overflow-y-auto min-h-0 p-2 space-y-1">
              {briefs.length === 0 && (
                <li className="text-slate-500 text-xs p-2">No packages yet. Create a brief to get started.</li>
              )}
              {briefs.map((b) => (
                <li key={b.id}>
                  <button
                    type="button"
                    onClick={() => { setSelectedBriefId(b.id); setScriptText(''); setNewsletterText('') }}
                    className={`w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors ${
                      selectedBriefId === b.id ? 'border-amber-500 bg-amber-900/20 text-slate-100' : 'border-slate-600 bg-slate-800/50 text-slate-300 hover:bg-slate-700/50'
                    }`}
                  >
                    <span className="font-medium truncate block">{b.title || 'Untitled brief'}</span>
                    <span className={`inline-flex items-center mt-1 px-1.5 py-0.5 rounded text-[10px] uppercase border ${statusBadgeClass(b.status)}`}>
                      {b.status.replace('_', ' ')}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {brief && (
              <div className="p-3 border-t border-slate-700">
                {linkedInitiative && (
                  <p className="text-xs text-slate-400">
                    Supports: <span className="text-slate-200">{linkedInitiative.title || linkedInitiative.id}</span>
                  </p>
                )}
                {linkedProject && !linkedInitiative && (
                  <p className="text-xs text-slate-400">
                    Project: <span className="text-slate-200">{linkedProject.title || linkedProject.id}</span>
                  </p>
                )}
                {!linkedInitiative && !linkedProject && brief.linked_project_id && (
                  <p className="text-xs text-slate-500">Link initiative or project in the brief for context.</p>
                )}
              </div>
            )}
          </aside>

          <main className="min-w-0 flex flex-col">
            {brief ? (
              <>
                <div className="rounded-xl border border-slate-600 bg-slate-800/80 overflow-hidden mb-4">
                  <div className="p-3 border-b border-slate-700 flex items-center justify-between flex-wrap gap-2">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] uppercase border ${statusBadgeClass(brief.status)}`}>
                      {brief.status.replace('_', ' ')}
                    </span>
                    {(linkedInitiative || linkedProject) && (
                      <span className="text-xs text-slate-400">
                        {linkedInitiative && <>Supports: {linkedInitiative.title || linkedInitiative.id}</>}
                        {linkedProject && linkedInitiative && ' · '}
                        {linkedProject && <>Project: {linkedProject.title || linkedProject.id}</>}
                      </span>
                    )}
                  </div>
                  <div className="p-4 overflow-y-auto max-h-[320px]">
                    <ContentBriefEditor
                      brief={brief}
                      onChange={handleBriefChange}
                      initiatives={initiatives}
                      projects={projects}
                      onDistillSource={async (source) => {
                        const res = await fetch(`${veApi}/distill-source`, {
                          method: 'POST',
                          credentials: 'include',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ source_materials: source }),
                        })
                        const data = (await res.json().catch(() => ({}))) as {
                          key_themes?: string[]
                          claims?: string[]
                          error?: string
                        }
                        const keyThemes = Array.isArray(data.key_themes) ? data.key_themes : []
                        const claims = Array.isArray(data.claims) ? data.claims : []
                        if (brief?.id) {
                          try {
                            emitContentBriefDistillTrace({
                              brief_id: brief.id,
                              source_materials_len: source.length,
                              key_themes_n: keyThemes.length,
                              claims_n: claims.length,
                              had_error: !res.ok || Boolean(data.error),
                            })
                          } catch {
                            /* ignore trace errors */
                          }
                        }
                        return { key_themes: keyThemes, claims }
                      }}
                    />
                  </div>
                </div>
                <ContentOutputsPane
                  activeTab={outputTab}
                  onTabChange={setOutputTab}
                  scriptText={scriptText}
                  newsletterText={newsletterText}
                  onGenerateScript={() => runContentGenerate('script')}
                  onGenerateNewsletter={() => runContentGenerate('newsletter')}
                  onRegenerateScript={() => runContentGenerate('script')}
                  onRegenerateNewsletter={() => runContentGenerate('newsletter')}
                  onRegenerateWithRefinement={(tab, refinement) => runContentGenerate(tab, refinement)}
                  onBeforeRunOutput={contentRecordRegenerateIntent}
                  generating={generating}
                  hasOutput={!!(scriptText || newsletterText)}
                />
              </>
            ) : (
              <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-8 text-center text-slate-500 text-sm">
                Select a brief or create one to start.
              </div>
            )}
          </main>

          <aside className="min-w-0">
            <ContentExportPane
              scriptText={scriptText}
              newsletterText={newsletterText}
              linkedProjectId={brief?.linked_project_id ?? ''}
              projects={projects}
              onCreateVETasks={createVETask}
              onCopyScriptSuccess={onContentCopyScriptOutcome}
              onCopyNewsletterSuccess={onContentCopyNewsletterOutcome}
              onExportScriptSuccess={onContentExportScriptOutcome}
              onCreateTasksSuccess={onContentCreateTasksSuccess}
              onMarkInProduction={brief ? markBriefInProduction : undefined}
            />
          </aside>
        </div>
        {showTranscriptSorter && <TranscriptSorter apiBase={transcriptBase} />}
      </div>
    </div>
  )
}
