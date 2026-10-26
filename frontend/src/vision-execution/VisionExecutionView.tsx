import { Fragment, useState, useEffect, useCallback, useRef, useMemo, type MutableRefObject } from 'react'
import {
  VISION_EXECUTION_API,
  type CoreProfile,
  type Idea,
  type Initiative,
  type Project,
  type Task,
  type Person,
  type CapacityProfile,
  type Asset,
  type ExtractMeetingResponse,
  type RadarResponse,
  type RadarItem,
  type RadarSignalItem,
  type ExecutionStep,
} from './types'
import type { VeRadarBucketId } from './veRadarAwareness'
import { canonicalCoreProfileId, coreProfileInfluencePickLabel } from './canonicalCoreProfile'
import { TaskSoilDevAppend } from './dev/TaskSoilDevAppend'
import type { VisionMapEntityBundle } from '../vision-map/blockersFromVe'
import { VE_EVALUATE_ACTION_INTENTS, visionExecutionEvaluateRouting } from './veRunRoutingContext'
import { ProjectsViewModeToggle, ProjectsTimelineView } from './timeline'
import type { ProjectsViewMode } from './timeline'
import {
  buildManualProcessingChunks,
  buildExternalBudgetChunks,
  parseLegacyExtractResponse,
  mergeSegmentExtractionResults,
  buildStagingArea,
  buildExtractionContext,
  commitStagedItems,
  stagingForSingleItemCommit,
  mergeForwardedCandidateIntoStaging,
  ReviewExtractionScreen,
  formatStagedItemForTaskNotes,
  parseTraceabilityFromNotes,
  EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS,
  applyDocumentLevelExtractionBudget,
} from '../meeting-intelligence'
import { postMeetingExtractionRecognition } from './recognitionDecisions'
import { LinkChooser, type NoteTargetEntityType } from '../meeting-intelligence/LinkChooser'
import {
  CLIENT_HINT_DEFAULT_OLLAMA_MODEL,
  EMBEDDED_EXECUTION_POLICY,
} from '../ai-actions/executionPolicy/defaultPolicy'
import { fetchLLMSettings, type ProviderStatusRow } from '../settings/api'

/** Interactive POST /extract-meeting: use default evidence preset (segment timeout/chunking aligned with working server path). */
const INTERACTIVE_EXTRACT_MEETING_PRESET = 'default' as const

/** Before GET /settings/llm loads — aligned with Studio bakeoff fallback / provider modules. */
function fallbackMeetingExternalEngineOptions(): { value: string; label: string }[] {
  const cloud = EMBEDDED_EXECUTION_POLICY.defaults?.cloud as
    | { provider?: string; model?: string | null }
    | undefined
  const prov = (typeof cloud?.provider === 'string' && cloud.provider.trim()
    ? cloud.provider.trim().toLowerCase()
    : 'ollama') as string
  const cloudModel =
    typeof cloud?.model === 'string' && cloud.model.trim() ? cloud.model.trim() : null

  const out: { value: string; label: string }[] = []
  if (prov === 'ollama') {
    const m = cloudModel ?? CLIENT_HINT_DEFAULT_OLLAMA_MODEL
    out.push({ value: `ollama:${m}`, label: `Ollama — ${m} (policy default)` })
  } else if (prov === 'openai') {
    const m = cloudModel ?? 'gpt-4o-mini'
    out.push({ value: `openai:${m}`, label: `OpenAI — ${m} (policy default)` })
  }

  const extras: { value: string; label: string }[] = [
    { value: `ollama:${CLIENT_HINT_DEFAULT_OLLAMA_MODEL}`, label: `Ollama — ${CLIENT_HINT_DEFAULT_OLLAMA_MODEL} (local)` },
    { value: 'openai:gpt-4o-mini', label: 'OpenAI — gpt-4o-mini' },
    { value: 'openai:gpt-4.1-mini', label: 'OpenAI — gpt-4.1-mini' },
    { value: 'anthropic:claude-haiku-4-5', label: 'Anthropic — claude-haiku-4-5' },
    { value: 'google:gemini-3.8-flash', label: 'Google (Gemini) — gemini-3.8-flash' },
    { value: 'xai:grok-4-1-fast-reasoning', label: 'xAI — grok-4-1-fast-reasoning' },
  ]
  const firstVal = out[0]?.value
  for (const e of extras) {
    if (e.value !== firstVal) out.push(e)
  }
  return out
}

function meetingExternalEngineOptionsFromProviders(rows: ProviderStatusRow[]): { value: string; label: string }[] {
  return rows.map((row) => {
    const model = (row.default_model || '').trim()
    const value = `${row.id}:${model}`
    const localTag = row.id === 'ollama' ? ' (local)' : ''
    let hint = ''
    if (!row.available) {
      hint = row.enabled ? ' — needs credentials' : ' — off in Settings'
    }
    return { value, label: `${row.display_name} — ${model}${localTag}${hint}` }
  })
}

/**
 * Extraction-time packet: populated from GET /workspace-identity (branch-safe) or legacy manual JSON.
 * Meeting extract never scans the filesystem; server builds packet from gitignored snapshot only.
 */
const WORKSPACE_PACKET_SESSION_KEY = 'zenaf_workspace_packet'
const WORKSPACE_IDENTITY_BRANCH_SESSION_KEY = 'zenaf_workspace_identity_branch'
/** Absolute paths; persisted in this browser only. Empty → scan uses server default (repo root). */
const WORKSPACE_IDENTITY_SCAN_ROOTS_STORAGE_KEY = 'zenaf_workspace_identity_scan_roots'

export type WorkspaceIdentityStatusResponse = {
  status: string
  branchKeyCurrent: string
  branchKeySnapshot: string | null
  generatedAt: string | null
  ageSeconds: number | null
  suggestRefreshDueToAge: boolean
  workspacePacket: {
    schemaVersion?: number
    domainHints: string[]
    literalAnchors?: string[]
    reasoningCapsule?: { themes?: string[]; namedPrograms?: string[]; tags?: string[] }
  } | null
  snapshotSummary: {
    schemaVersion?: number
    domainHintCount: number
    surfaceCount: number
    scanKind: string | null
    nodeCapReached: boolean
    sourceRootCount: number
    pathRecords?: number
    reasoningThemeCount?: number
    clusterCount?: number
  } | null
  /** Server Zenaf repo root when client sends roots: [] */
  defaultScanRoot?: string
  /** Paths recorded in the last snapshot */
  lastScanSourceRoots?: string[] | null
  /** Present when heuristics detect mostly generic / artifact filenames */
  identityQualityWarning?: string | null
}

function parseScanRootsFromStorage(): string[] {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(WORKSPACE_IDENTITY_SCAN_ROOTS_STORAGE_KEY)
    if (!raw?.trim()) return []
    const p = JSON.parse(raw) as unknown
    if (!Array.isArray(p)) return []
    return p.map((x) => String(x).trim()).filter(Boolean)
  } catch {
    return []
  }
}

function saveScanRootsToStorage(roots: string[]): void {
  if (typeof localStorage === 'undefined') return
  try {
    if (roots.length === 0) localStorage.removeItem(WORKSPACE_IDENTITY_SCAN_ROOTS_STORAGE_KEY)
    else localStorage.setItem(WORKSPACE_IDENTITY_SCAN_ROOTS_STORAGE_KEY, JSON.stringify(roots))
  } catch {
    /* ignore quota */
  }
}

function applyWorkspaceIdentityGetToSession(data: WorkspaceIdentityStatusResponse): void {
  if (typeof sessionStorage === 'undefined') return
  if (data.status === 'ok' && data.workspacePacket?.domainHints?.length) {
    sessionStorage.setItem(WORKSPACE_PACKET_SESSION_KEY, JSON.stringify(data.workspacePacket))
    sessionStorage.setItem(WORKSPACE_IDENTITY_BRANCH_SESSION_KEY, data.branchKeyCurrent)
  } else {
    sessionStorage.removeItem(WORKSPACE_PACKET_SESSION_KEY)
    sessionStorage.removeItem(WORKSPACE_IDENTITY_BRANCH_SESSION_KEY)
  }
}

/** Ideas/initiatives/etc. must be strings in the UI; DB or bad merges can leave objects in scalar fields. */
function veEntityDisplayStr(v: unknown): string {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  return ''
}

function veClip(v: unknown, maxChars: number): string {
  const s = veEntityDisplayStr(v)
  if (!s) return ''
  return s.length <= maxChars ? s : `${s.slice(0, maxChars)}…`
}

function readWorkspacePacketForExtract(): { domainHints: string[] } | undefined {
  if (typeof sessionStorage === 'undefined') return undefined
  try {
    const raw = sessionStorage.getItem(WORKSPACE_PACKET_SESSION_KEY)
    if (!raw?.trim()) return undefined
    const o = JSON.parse(raw) as unknown
    if (!o || typeof o !== 'object') return undefined
    const hints = (o as { domainHints?: unknown }).domainHints
    if (!Array.isArray(hints) || hints.length === 0) return undefined
    const domainHints = hints.map((x) => String(x).trim()).filter((s) => s.length >= 3)
    if (domainHints.length === 0) return undefined
    return { domainHints }
  } catch {
    return undefined
  }
}

/** Labels derived from the workspace mirror packet (folder/file names + reasoning capsule). */
function workspacePacketSurfaceLines(
  packet: WorkspaceIdentityStatusResponse['workspacePacket'],
  maxItems = 14,
): string[] {
  if (!packet) return []
  const seen = new Set<string>()
  const out: string[] = []
  const push = (raw: unknown) => {
    const t = String(raw).trim()
    if (t.length < 2) return
    const k = t.toLowerCase()
    if (seen.has(k)) return
    seen.add(k)
    out.push(t)
  }
  for (const x of packet.domainHints ?? []) {
    if (typeof x === 'string') push(x)
  }
  for (const x of packet.literalAnchors ?? []) {
    if (out.length >= maxItems) break
    if (typeof x === 'string') push(x)
  }
  const cap = packet.reasoningCapsule
  if (cap) {
    for (const x of cap.themes ?? []) {
      if (out.length >= maxItems) break
      if (typeof x === 'string') push(x)
    }
    for (const x of cap.namedPrograms ?? []) {
      if (out.length >= maxItems) break
      if (typeof x === 'string') push(x)
    }
    for (const x of cap.tags ?? []) {
      if (out.length >= maxItems) break
      if (typeof x === 'string') push(x)
    }
  }
  return out.slice(0, maxItems)
}

/** Synced into POST /run council_preflight from the open idea editor (live form — not just the list cache). */
export type CouncilIdeaLabelsSnapshot = {
  entity_type: 'idea'
  entity_id: string
  ve_focus_title: string
  ve_focus_brief: string
  ve_focus_description: string
  /** Current status from the detail form (e.g. Captured / Clarify). */
  ve_focus_status?: string
}
import type {
  StagingArea,
  ExistingEntities,
  ManualProcessingChunk,
  StagingArraySectionKey,
  ExtractedSignal,
  StagedItem,
  ForwardableStagingSectionKey,
} from '../meeting-intelligence'
import type { CandidatePlacementResponse } from '../meeting-intelligence/candidatePlacementSuggest'
import type { CandidatePresortTriageApiResponse } from '../meeting-intelligence/candidatePresortTriage'
import { fileToText, ACCEPT_UPLOAD } from './fileToText'
import type { PerspectiveAgent } from '../perspectives/types'
import { BUILT_IN_PERSPECTIVES, normalizeStoredPerspectiveAgents } from '../perspectives/types'
import { DetailSection, DetailField, EntityMultiSelect, MetadataSection, ConfirmModal, Slider1To5 } from './detail-panel-shared'
import { DeferredPromptTodosSection } from './DeferredPromptTodosSection'
import { formatVeEntityPromptTitle } from '../developmentalGuidance/systemPromptTitle'
import { InfluencesLinksSection } from '../perspectives/InfluencesLinksSection'
import {
  VeFocusRegion,
  DetailPanelInviteChips,
  useVisionExecutionFocusOptional,
  useVisionExecutionGraphDataOptional,
  focusDescriptorFromVeSelection,
  ZENAF_VE_FOCUS_APPLY_REWRITE,
  type VeFocusApplyRewriteDetail,
  ZENAF_VE_FOCUS_INSERT_TEXT,
  insertTextAtSelection,
  type VeFocusInsertTextDetail,
} from './focus'
import {
  parseNextStepsPayload,
  serializeNextStepsPayload,
  emptyNextStepsPayload,
  nextStepsPrimaryLine,
  hasNextStepsContent,
} from './nextStepsPayload'
import {
  AiActionResultPanel,
  createAiActionTrace,
  pushAiActionTrace,
  withTraceOutcome,
  buildMeetingExtractionInputSnapshot,
  buildMeetingExtractionStagingOutputSummary,
  emitMeetingExtractionTrace,
  readPrivacyMode,
  recordMeetingExtractionTraceOutcome,
  type AiActionTrace,
  type AiUserOutcome,
  type MeetingExtractActionIntent,
  type MeetingExtractionPath,
} from '../ai-actions'
import {
  loadProjectSuggestionState,
  setGeneratedSuggestions,
  clearProjectSuggestions,
  toggleSuggestionChecked,
  PROJECT_SUGGESTION_KIND_LABEL,
  type ProjectSuggestionItem,
  type ProjectSuggestionKind,
} from './projectSuggestedWorkLocal'

type GlobalExtractionContext = {
  themes: string[]
  entities: string[]
  workstreams: string[]
}

type VisionLearningUserOutcome = 'applied' | 'edited' | 'dismissed' | 'copied'

/** Fire-and-forget learning buffer update (same endpoint as Core Profile conversation). */
function postVisionExecutionLearningOutcome(
  apiPost: <T>(path: string, body: unknown) => Promise<T>,
  learningRecordId: string | null | undefined,
  userOutcome: VisionLearningUserOutcome,
): void {
  const id = typeof learningRecordId === 'string' ? learningRecordId.trim() : ''
  if (!id) return
  void apiPost<{ ok: boolean }>('/learning-records/user-outcome', {
    learning_record_id: id,
    user_outcome: userOutcome,
    privacy_mode: readPrivacyMode(),
  }).catch(() => {
    /* non-blocking */
  })
}

function deriveGlobalExtractionContext(notes: string): GlobalExtractionContext {
  const text = notes.replace(/\r?\n+/g, ' ').trim()
  if (!text) return { themes: [], entities: [], workstreams: [] }

  const lower = text.toLowerCase()

  // Very lightweight keyword-based themes.
  const themeCandidates: { key: string; label: string }[] = [
    { key: 'risk', label: 'Risks & blockers' },
    { key: 'opportunity', label: 'Opportunities' },
    { key: 'capacity', label: 'Capacity & staffing' },
    { key: 'initiative', label: 'Initiatives' },
    { key: 'project', label: 'Projects' },
    { key: 'task', label: 'Tasks & follow-ups' },
    { key: 'patient', label: 'Patient care' },
    { key: 'clinic', label: 'Clinic operations' },
  ]
  const themes = themeCandidates
    .filter(({ key }) => lower.includes(key))
    .map(({ label }) => label)

  // Naive entity extraction: frequent capitalized tokens (potential names / systems).
  const entitySet = new Set<string>()
  const entityMatches = notes.match(/\b[A-Z][A-Za-z0-9\-]{3,}\b/g) ?? []
  for (const token of entityMatches) {
    if (entitySet.size >= 10) break
    entitySet.add(token)
  }

  // Workstream hints from lines that look like headings or bullet points.
  const workstreamSet = new Set<string>()
  notes.split(/\r?\n/).forEach((line) => {
    const trimmed = line.trim()
    if (!trimmed) return
    if (/^[-*]\s+/.test(trimmed) || /:$/.test(trimmed)) return
  })
  // Simple heuristic: top-level headings (lines without punctuation, moderately long, title-case).
  notes.split(/\r?\n/).forEach((line) => {
    const trimmed = line.trim()
    if (!trimmed || workstreamSet.size >= 6) return
    const isHeading = /^[A-Z][A-Za-z0-9\s]{8,}$/.test(trimmed) && !/[.!?]$/.test(trimmed)
    if (isHeading) workstreamSet.add(trimmed.slice(0, 80))
  })

  return {
    themes: Array.from(new Set(themes)).slice(0, 5),
    entities: Array.from(entitySet),
    workstreams: Array.from(workstreamSet),
  }
}

/** Substrate for meeting extraction API — aligns with server `meeting_extraction_execution`. */
function meetingExtractionRoutingContext(
  intent: MeetingExtractActionIntent,
  extras?: { diagnosticsChunkId?: string; meetingExtractChunked?: boolean },
) {
  return {
    surface: 'meeting_extraction' as const,
    action_kind: 'suggestion_batch' as const,
    action_intent: intent,
    streaming: false,
    privacy_mode: readPrivacyMode(),
    ...(extras?.diagnosticsChunkId ? { diagnosticsChunkId: extras.diagnosticsChunkId } : {}),
    ...(extras?.meetingExtractChunked ? { meetingExtractChunked: true as const } : {}),
  }
}

/** Merge API list with seed by id; seed entries override or append. */

/** Renders "Created from" / "Source excerpt" when notes/description contain meeting-extraction traceability. */
function TraceabilityMeta({ notesOrDescription }: { notesOrDescription: string | null | undefined }) {
  const parsed = parseTraceabilityFromNotes(notesOrDescription)
  if (!parsed.source) return null
  return (
    <div className="mb-4 p-3 rounded-lg border border-slate-600 bg-slate-800/50">
      <h4 className="text-xs font-medium text-slate-400 uppercase mb-1.5">Source</h4>
      <p className="text-slate-300 text-xs">Created from: {parsed.source}</p>
      {parsed.sourceExcerpt && (
        <p className="text-slate-500 text-xs mt-1.5 italic border-l-2 border-slate-600 pl-2">
          &ldquo;{parsed.sourceExcerpt.slice(0, 300)}{parsed.sourceExcerpt.length > 300 ? '…' : ''}&rdquo;
        </p>
      )}
    </div>
  )
}

/** Rollup of extractionMeta across succeeded chunks (present when server attaches it); operator-facing only. */
interface OperatorRunRollup {
  chunksWithMeta: number
  skipTrue: number
  pctSkip: number
  avgEvidencePhaseMsSkipLLM: number | null
  avgEvidencePhaseMsNoSkip: number | null
  totalLiteralCandidates: number
  totalModelCandidates: number
  lowValueLiteralChunks: number
  literalAnchorsCappedChunks: number
}

function formatOpBool(v: boolean | null): string {
  if (v === true) return 'Y'
  if (v === false) return 'N'
  return '—'
}

function formatOpNum(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return String(Math.round(v))
}

/** Simplified chunk progress: single bar + status text; details in collapsible Diagnostics. */
function ChunkProgressSimple({
  chunkModeChunks,
  chunkModeResults,
  extractLoading,
  chunkRunFocus,
  chunkProgressExtractKind,
  onRetryChunk,
  onRetryFailedChunks,
  onStopExtract,
}: {
  chunkModeChunks: ManualProcessingChunk[]
  chunkModeResults: { chunkId: string; status: string; response?: ExtractMeetingResponse; error?: string }[]
  extractLoading: boolean
  /** Which chunk index is awaiting POST /extract-meeting (opaque server/model tail). */
  chunkRunFocus: { chunkIndex: number; startedAt: number } | null
  chunkProgressExtractKind: 'local' | 'external_budget'
  onRetryChunk: (chunkId: string) => void
  onRetryFailedChunks: () => void
  onStopExtract: () => void
}) {
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false)
  const operatorExtractionSummary = useMemo(() => {
    const rows: {
      rowKey: string
      chunkId: string
      skipLLM: boolean | null
      evidencePhaseMs: number | null
      candidateCountPerChunk: number | null
      literalCandidateCount: number | null
      modelCandidateCount: number | null
      lowValueLiteralAnchor: boolean | null
      literalAnchorsCapped: boolean | null
      status: string
    }[] = []
    for (const chunk of chunkModeChunks) {
      const result = chunkModeResults.find((r) => r.chunkId === chunk.id)
      const status = result?.status ?? 'pending'
      const meta = result?.response?.extractionMeta
      const skip =
        meta == null ? null : (meta.skipLLM ?? (meta.llmSkippedCount === 1 ? true : meta.llmSkippedCount === 0 ? false : null))
      rows.push({
        rowKey: chunk.id,
        chunkId: (meta?.diagnosticsChunkId as string | null | undefined) ?? chunk.id,
        skipLLM: skip,
        evidencePhaseMs: meta?.evidencePhaseMs ?? null,
        candidateCountPerChunk: meta?.candidateCountPerChunk ?? null,
        literalCandidateCount: meta?.literalCandidateCount ?? null,
        modelCandidateCount: meta?.modelCandidateCount ?? null,
        lowValueLiteralAnchor: meta?.lowValueLiteralAnchor ?? null,
        literalAnchorsCapped: meta?.literalAnchorsCapped ?? null,
        status,
      })
    }

    const ok = chunkModeResults.filter((r) => r.status === 'succeeded' && r.response?.extractionMeta)
    if (ok.length === 0) {
      return { rows, run: null as null | OperatorRunRollup }
    }

    let skipTrue = 0
    const phaseWhenSkip: number[] = []
    const phaseWhenNoSkip: number[] = []
    let totalLiteral = 0
    let totalModel = 0
    let lowValueChunks = 0
    let cappedChunks = 0

    for (const r of ok) {
      const m = r.response!.extractionMeta!
      const didSkip = m.skipLLM === true || m.llmSkippedCount === 1
      if (didSkip) skipTrue += 1
      const ph = m.evidencePhaseMs
      if (ph != null && Number.isFinite(ph)) {
        if (didSkip) phaseWhenSkip.push(ph)
        else phaseWhenNoSkip.push(ph)
      }
      totalLiteral += m.literalCandidateCount ?? 0
      totalModel += m.modelCandidateCount ?? 0
      if (m.lowValueLiteralAnchor === true) lowValueChunks += 1
      if (m.literalAnchorsCapped === true) cappedChunks += 1
    }

    const n = ok.length
    const avg = (xs: number[]) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : null)
    const run: OperatorRunRollup = {
      chunksWithMeta: n,
      skipTrue,
      pctSkip: Math.round((skipTrue / n) * 1000) / 10,
      avgEvidencePhaseMsSkipLLM: avg(phaseWhenSkip),
      avgEvidencePhaseMsNoSkip: avg(phaseWhenNoSkip),
      totalLiteralCandidates: totalLiteral,
      totalModelCandidates: totalModel,
      lowValueLiteralChunks: lowValueChunks,
      literalAnchorsCappedChunks: cappedChunks,
    }
    return { rows, run }
  }, [chunkModeChunks, chunkModeResults])
  const total = chunkModeChunks.length
  const succeeded = chunkModeResults.filter((r) => r.status === 'succeeded').length
  const failed = chunkModeResults.filter((r) => r.status === 'failed').length
  const running = chunkModeResults.some((r) => r.status === 'running')
  const completed = succeeded + failed
  const pct = total ? Math.round((completed / total) * 100) : 0
  const statusText = running
    ? 'Processing meeting…'
    : failed > 0
      ? `${succeeded} of ${total} chunks complete, ${failed} failed`
      : `${succeeded} of ${total} chunks complete`
  const runIdx = chunkRunFocus?.chunkIndex
  const extBudgetK = Math.round(EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS / 1000)
  const runHint =
    running && runIdx != null && total > 0
      ? chunkProgressExtractKind === 'external_budget'
        ? runIdx === total - 1
          ? 'Finishing last transcript segment — one full external extraction pass.'
          : `Extracting part ${runIdx + 1} of ${total} — each part is one external model pass (up to ~${extBudgetK}k characters of transcript).`
        : runIdx === total - 1
          ? 'Finishing last chunk — the local model may scan several sub-sections inside this excerpt before responding.'
          : `Extracting chunk ${runIdx + 1} of ${total} — each excerpt can trigger multiple internal model passes.`
      : null
  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4">
      <div className="flex items-center justify-between gap-2 mb-1 flex-wrap">
        <span className="text-sm text-slate-300">{statusText}</span>
        {extractLoading && (
          <button
            type="button"
            onClick={onStopExtract}
            className="px-3 py-1 rounded-lg border border-red-500/70 text-red-200 hover:bg-red-950/40 text-xs font-medium shrink-0"
          >
            Stop
          </button>
        )}
      </div>
      {runHint && <p className="text-xs text-slate-400 mb-2 leading-snug">{runHint}</p>}
      <div className="h-2 rounded-full bg-slate-700 overflow-hidden mb-3">
        <div
          className="h-full bg-emerald-600 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      {failed > 0 && (
        <button
          type="button"
          onClick={onRetryFailedChunks}
          disabled={extractLoading}
          className="px-3 py-1.5 rounded-lg border border-amber-600 text-amber-200 hover:bg-amber-900/30 disabled:opacity-50 text-sm mb-2"
        >
          Retry failed chunks
        </button>
      )}
      <button
        type="button"
        onClick={() => setDiagnosticsOpen((o) => !o)}
        className="text-xs text-slate-500 hover:text-slate-300"
      >
        {diagnosticsOpen ? '▼' : '▶'} Technical details
      </button>
      {diagnosticsOpen && (
        <ul className="space-y-2 mt-2 pt-2 border-t border-slate-700">
          {!extractLoading && operatorExtractionSummary.run && (
            <li className="text-[11px] text-slate-400 font-mono leading-relaxed pb-3 border-b border-slate-700/80 space-y-1">
              <div className="text-slate-500 uppercase tracking-wide text-[10px] mb-1">Extraction run (operator)</div>
              <div>
                skipLLM: {operatorExtractionSummary.run.skipTrue}/{operatorExtractionSummary.run.chunksWithMeta} (
                {operatorExtractionSummary.run.pctSkip}%)
              </div>
              <div>
                avg evidencePhaseMs: skip={operatorExtractionSummary.run.avgEvidencePhaseMsSkipLLM ?? '—'}ms · noSkip=
                {operatorExtractionSummary.run.avgEvidencePhaseMsNoSkip ?? '—'}ms
              </div>
              <div>
                candidates total: literal {operatorExtractionSummary.run.totalLiteralCandidates} · model{' '}
                {operatorExtractionSummary.run.totalModelCandidates}
              </div>
              <div>
                lowValueLiteralAnchor chunks: {operatorExtractionSummary.run.lowValueLiteralChunks} · literalAnchorsCapped
                chunks: {operatorExtractionSummary.run.literalAnchorsCappedChunks}
              </div>
            </li>
          )}
          {!extractLoading && operatorExtractionSummary.rows.length > 0 && (
            <li className="text-[10px] text-slate-500 font-mono leading-snug pb-2 border-b border-slate-700/80 overflow-x-auto">
              <div className="text-slate-500 uppercase tracking-wide mb-1">Per chunk</div>
              <div className="grid gap-x-2 gap-y-0.5 text-slate-400" style={{ gridTemplateColumns: 'minmax(4rem,1fr) repeat(7, auto)' }}>
                <span>chunkId</span>
                <span>skip</span>
                <span>phaseMs</span>
                <span>cands</span>
                <span>lit</span>
                <span>model</span>
                <span>lowV</span>
                <span>cap</span>
                {operatorExtractionSummary.rows.map((row) => (
                  <Fragment key={row.rowKey}>
                    <span className="truncate text-slate-300" title={row.chunkId}>
                      {row.chunkId}
                    </span>
                    <span>{formatOpBool(row.skipLLM)}</span>
                    <span>{formatOpNum(row.evidencePhaseMs)}</span>
                    <span>{formatOpNum(row.candidateCountPerChunk)}</span>
                    <span>{formatOpNum(row.literalCandidateCount)}</span>
                    <span>{formatOpNum(row.modelCandidateCount)}</span>
                    <span>{formatOpBool(row.lowValueLiteralAnchor)}</span>
                    <span>{formatOpBool(row.literalAnchorsCapped)}</span>
                  </Fragment>
                ))}
              </div>
            </li>
          )}
          {chunkModeChunks.map((chunk) => {
            const result = chunkModeResults.find((r) => r.chunkId === chunk.id)
            const status = result?.status ?? 'pending'
            const resp = result?.response
            const emptyDurable =
              status === 'succeeded' &&
              resp &&
              !resp.error &&
              (resp.noDurableCandidates === true || (Array.isArray(resp.candidates) && resp.candidates.length === 0))
            const meta = resp?.extractionMeta
            const chunkIndex = chunkModeChunks.findIndex((c) => c.id === chunk.id)
            const runningThis = status === 'running' && runIdx != null && chunkIndex === runIdx
            return (
              <li key={chunk.id} className="py-1.5 border-b border-slate-700 last:border-0 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-400 truncate flex-1" title={veEntityDisplayStr(chunk.title) || chunk.id}>
                    {veEntityDisplayStr(chunk.title) || chunk.id}
                  </span>
                  <span className="flex items-center gap-2 shrink-0">
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      status === 'succeeded' ? 'bg-emerald-900/50 text-emerald-200' :
                      status === 'failed' ? 'bg-red-900/50 text-red-200' :
                      status === 'running' ? 'bg-amber-900/50 text-amber-200' : 'bg-slate-700 text-slate-400'
                    }`}>{status}</span>
                    {status === 'failed' && (
                      <button type="button" onClick={() => onRetryChunk(chunk.id)} disabled={extractLoading} className="px-2 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-700 disabled:opacity-50 text-xs">Retry</button>
                    )}
                  </span>
                </div>
                {runningThis && (
                  <p className="text-slate-500 text-[11px] mt-1 pl-0.5">
                    {chunkProgressExtractKind === 'external_budget'
                      ? 'Waiting on external model for this transcript segment.'
                      : 'Waiting on server — model runs internal segments sequentially; empty excerpts still consume time.'}
                  </p>
                )}
                {emptyDurable && (
                  <p className="text-slate-500 text-xs mt-1 pl-0.5">No durable candidates found for this chunk.</p>
                )}
                {status === 'succeeded' && meta && typeof meta.evidenceSegmentsProcessed === 'number' && (
                  <p className="text-slate-500 text-[11px] mt-1 pl-0.5 font-mono">
                    Evidence passes {meta.evidenceSegmentsProcessed}/{meta.evidenceSegmentsPlanned ?? '—'} · LLM ~{Math.round(meta.evidenceLlmMsTotal ?? 0)}ms
                    {meta.evidencePostProcessMs != null ? ` · post ~${Math.round(meta.evidencePostProcessMs)}ms` : ''}
                    {meta.interactiveStopReason ? ` · stop=${meta.interactiveStopReason}` : ''}
                    {meta.skipLLM ? ' · skipLLM' : ''}
                    {meta.evidencePhaseMs != null ? ` · phase ${Math.round(meta.evidencePhaseMs)}ms` : ''}
                    {meta.lowValueLiteralAnchor ? ' · lowValueLiteral' : ''}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** Roadmap: view over initiatives → projects → tasks. Filter by status; emphasize approved/active. */
function RoadmapView({
  initiatives,
  projects,
  tasks,
  persons,
}: {
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  persons: Person[]
}) {
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const activeStatuses = ['Approved', 'Active']
  const initFiltered =
    statusFilter === 'all'
      ? initiatives
      : statusFilter === 'active'
        ? initiatives.filter((i) => activeStatuses.includes(i.status))
        : initiatives.filter((i) => i.status === statusFilter)
  const getPersonName = (id: string | null) => (id ? persons.find((p) => p.id === id)?.name ?? id : '—')
  return (
    <div className="space-y-4 flex-1 min-h-0 overflow-auto">
      <div className="flex items-center gap-3 flex-wrap">
        <h3 className="text-sm font-medium text-slate-200">Roadmap</h3>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-2 py-1 rounded bg-slate-900 border border-slate-600 text-slate-200 text-sm"
        >
          <option value="all">All statuses</option>
          <option value="active">Approved / Active</option>
          {['Draft', 'Evaluating', 'Approved', 'Active', 'Paused', 'Complete', 'Killed'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>
      <p className="text-slate-500 text-xs">Initiatives with child projects and tasks. No new core entity — view over existing data.</p>
      <div className="space-y-4">
        {initFiltered.length === 0 ? (
          <p className="text-slate-500 text-sm">No initiatives match the filter.</p>
        ) : (
          initFiltered.map((init) => {
            const initProjects = projects.filter((p) => p.initiative_id === init.id)
            const briefLine = veEntityDisplayStr(init.brief)
            return (
              <div key={init.id} className="rounded-xl border border-slate-600 bg-slate-800/50 p-4">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="font-medium text-slate-200">{veEntityDisplayStr(init.title)}</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-slate-700 text-slate-300">{veEntityDisplayStr(init.status)}</span>
                </div>
                {briefLine ? (
                  <p className="text-slate-500 text-xs mb-2">
                    {briefLine.slice(0, 160)}
                    {briefLine.length > 160 ? '…' : ''}
                  </p>
                ) : null}
                <div className="ml-3 space-y-2 border-l-2 border-slate-600 pl-3">
                  {initProjects.length === 0 ? (
                    <p className="text-slate-500 text-xs">No projects</p>
                  ) : (
                    initProjects.map((proj) => {
                      const projTasks = tasks.filter((t) => t.project_id === proj.id)
                      return (
                        <div key={proj.id} className="text-sm">
                          <div className="flex items-center gap-2 text-slate-300">
                            <span>{veEntityDisplayStr(proj.title)}</span>
                            <span className="text-xs text-slate-500">({veEntityDisplayStr(proj.status)})</span>
                            {proj.start_date || proj.end_date ? <span className="text-xs text-slate-500">{proj.start_date ?? '…'} → {proj.end_date ?? '…'}</span> : null}
                          </div>
                          <ul className="ml-3 mt-1 space-y-0.5 text-xs text-slate-400">
                            {projTasks.slice(0, 8).map((t) => (
                              <li key={t.id}>
                                · {veEntityDisplayStr(t.title)} {t.assignee_id ? `(${getPersonName(t.assignee_id)})` : ''} — {veEntityDisplayStr(t.status)}
                              </li>
                            ))}
                            {projTasks.length > 8 && <li className="text-slate-500">+{projTasks.length - 8} more</li>}
                          </ul>
                        </div>
                      )
                    })
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

/** Executive: minimal cockpit — top priorities, blocked, overcapacity only. High-signal, 1–3 items per section. */
function ExecutiveView({
  initiatives,
  projects,
  tasks,
  persons,
  capacityProfiles,
}: {
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  persons: Person[]
  capacityProfiles: CapacityProfile[]
}) {
  const blockedProjects = projects.filter((p) => p.status === 'Blocked')
  const blockedTasks = tasks.filter((t) => t.status === 'Blocked')
  const blocked = [...blockedProjects.map((p) => ({ type: 'project' as const, id: p.id, title: p.title })), ...blockedTasks.map((t) => ({ type: 'task' as const, id: t.id, title: t.title }))].slice(0, 3)
  const overcapacityPeople = capacityProfiles.filter((c) => c.overcapacity).slice(0, 3)
  const topPriorities = initiatives.filter((i) => ['Approved', 'Active'].includes(i.status)).slice(0, 3)
  return (
    <div className="space-y-6 flex-1 min-h-0 overflow-auto">
      <h3 className="text-sm font-medium text-slate-200">Executive view</h3>
      <p className="text-slate-500 text-xs">Immediate action. Top priorities, blocked work, overcapacity.</p>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4">
          <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">Top priorities</h4>
          {topPriorities.length === 0 ? <p className="text-slate-500 text-sm">None</p> : (
            <ul className="space-y-1 text-sm text-slate-200">
              {topPriorities.map((i) => (
                <li key={i.id}>
                  {veEntityDisplayStr(i.title)} <span className="text-slate-500">({veEntityDisplayStr(i.status)})</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4">
          <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">Blocked</h4>
          {blocked.length === 0 ? <p className="text-slate-500 text-sm">None</p> : (
            <ul className="space-y-1 text-sm text-slate-200">
              {blocked.map((b) => (
                <li key={`${b.type}-${b.id}`}>
                  {b.type === 'project' ? 'Project: ' : 'Task: '}
                  {veEntityDisplayStr(b.title)}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4">
          <h4 className="text-xs font-medium text-slate-400 uppercase mb-2">Overcapacity</h4>
          {overcapacityPeople.length === 0 ? <p className="text-slate-500 text-sm">None</p> : (
            <ul className="space-y-1 text-sm text-slate-200">
              {overcapacityPeople.map((c) => {
                const p = persons.find((x) => x.id === c.person_id)
                return (
                  <li key={c.person_id}>
                    {veEntityDisplayStr(p?.name) || c.person_id} — {c.activeWeeklyHours ?? 0}h / {c.weekly_capacity_hours ?? 0}h
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

export type VESelection = {
  tab: 'execution' | 'initiatives' | 'projects' | 'tasks' | 'assets' | 'ideas'
  initiativeId?: string
  projectId?: string
  taskId?: string
  assetId?: string
  ideaId?: string
}

export type VEWorkspaceTabId =
  | 'meeting_capture'
  | 'ideas'
  | 'execution'
  | 'people'
  | 'assets'
  | 'radar'
  | 'matching_internal'
  | 'roadmap'
  | 'executive'

type TabId = VEWorkspaceTabId

/** Derive App-level `VESelection` from open detail state (Pass 1 focus sync). */
function deriveVeSelectionFromDetailState(
  tab: TabId,
  detailIdeaId: string | null,
  detailInitiativeId: string | null,
  detailProjectId: string | null,
  detailTaskId: string | null,
  detailAssetId: string | null,
): VESelection | null {
  if (detailIdeaId) return { tab: 'ideas', ideaId: detailIdeaId }
  if (detailAssetId) return { tab: 'assets', assetId: detailAssetId }
  if (tab === 'execution') {
    if (detailTaskId) return { tab: 'tasks', taskId: detailTaskId, projectId: detailProjectId ?? undefined }
    if (detailProjectId) return { tab: 'projects', projectId: detailProjectId }
    if (detailInitiativeId) return { tab: 'initiatives', initiativeId: detailInitiativeId }
  }
  return null
}

const PERSPECTIVE_AGENTS_STORAGE_KEY = 'zenaf-perspective-agents'

const TABS: { id: TabId; label: string }[] = [
  { id: 'ideas', label: 'Ideas' },
  { id: 'execution', label: 'Execution' },
  { id: 'people', label: 'Team' },
  { id: 'assets', label: 'Assets' },
  { id: 'matching_internal', label: 'Matching (Internal)' },
]
// NOTE (2026-10-18): Meeting Capture, Radar, Roadmap, Executive View tabs were
// scrapped per Joshua's review — meeting capture is the conversation now; the
// other three were already condemned. Their render blocks below are kept so
// deep links / focus requests (e.g. the vision-map radar strip's
// focusTabRequest('radar')) still land on working content; the buttons are gone.
// Backend endpoints are untouched (flagged callerless for the later intentional gutting).

/** Inbox handoff: section keys allowed when merging a forwarded extraction row. */
const WORKSPACE_FORWARDABLE_SECTIONS = new Set<string>([
  'insights',
  'ideas',
  'initiatives',
  'projects',
  'tasks',
  'assets',
  'people',
  'signals',
])

type ShareVisibilityState = 'private' | 'shared_unindexed' | 'shared_indexed' | 'revoked' | 'inactive' | 'deleted'
type ShareIndexState = 'private' | 'shared_unindexed' | 'shared_indexed' | 'revoked' | 'inactive' | 'deleted'

type WorkspaceDirectoryUser = { id: string; email: string; display_name: string }

type WorkspaceMessageRow = {
  id: string
  from_user_id: string
  to_user_id: string
  from_display_name: string
  to_display_name: string
  title: string
  body: Record<string, unknown>
  read_at: string | null
  created_at: string
}

type SeatRequestRecord = {
  id: string
  title: string
  summary?: string
  context_type?: string
  context_id?: string | null
  role_tags: string[]
  capability_tags: string[]
  availability_window?: string | null
  commitment_type?: string
  collaboration_mode?: string
  timezone_pref?: string
  visibility: ShareVisibilityState
  index_state: ShareIndexState
  consent_version?: string
  share_until?: string | null
  is_active?: boolean
}

type CapabilityOfferRecord = {
  id: string
  title: string
  summary?: string
  role_tags: string[]
  capability_tags: string[]
  availability_window?: string | null
  commitment_type?: string
  collaboration_mode?: string
  timezone_pref?: string
  visibility: ShareVisibilityState
  index_state: ShareIndexState
  consent_version?: string
  share_until?: string | null
  is_active?: boolean
}

type CandidateOffer = {
  capability_offer_id: string
  score: number
  rationale: {
    matched_capability_tags?: string[]
    matched_role_tags?: string[]
    missing_capability_tags?: string[]
    missing_role_tags?: string[]
    score_components?: Record<string, number>
  }
  hard_constraints: {
    commitment_compatible: boolean
    collaboration_compatible: boolean
    timezone_compatible: boolean
  }
  offer: {
    id: string
    title: string
    capability_tags: string[]
    role_tags: string[]
    availability_window?: string | null
    commitment_type?: string
    collaboration_mode?: string
    timezone_pref?: string
  }
}

type CandidateRequest = {
  seat_request_id: string
  score: number
  rationale: {
    matched_capability_tags?: string[]
    matched_role_tags?: string[]
    missing_capability_tags?: string[]
    missing_role_tags?: string[]
    score_components?: Record<string, number>
  }
  hard_constraints: {
    commitment_compatible: boolean
    collaboration_compatible: boolean
    timezone_compatible: boolean
  }
  seat_request: {
    id: string
    title: string
    context_type?: string
    capability_tags: string[]
    role_tags: string[]
    availability_window?: string | null
    commitment_type?: string
    collaboration_mode?: string
    timezone_pref?: string
  }
}

type MaterialRequestRecord = {
  id: string
  title: string
  material_type: string
  resource_nature: string
  category_tags: string[]
  quantity_needed: number
  quantity_unit: string
  availability_start?: string | null
  availability_end?: string | null
  condition_min: string
  access_mode: string
  location_region: string
  cost_band_max?: string
  visibility: ShareVisibilityState
  index_state: ShareIndexState
  consent_version?: string
  share_until?: string | null
  is_active?: boolean
}

type MaterialOfferRecord = {
  id: string
  title: string
  material_type: string
  resource_nature: string
  category_tags: string[]
  quantity_available: number
  quantity_unit: string
  availability_start?: string | null
  availability_end?: string | null
  condition_state: string
  access_mode: string
  location_region: string
  cost_band?: string
  visibility: ShareVisibilityState
  index_state: ShareIndexState
  consent_version?: string
  share_until?: string | null
  is_active?: boolean
}

type MaterialCandidateOffer = {
  material_offer_id: string
  score: number
  rationale: Record<string, unknown>
  offer: {
    id: string
    title: string
    material_type: string
    resource_nature: string
    category_tags: string[]
    quantity_available: number
    quantity_unit: string
    availability_start?: string | null
    availability_end?: string | null
    condition_state: string
    access_mode: string
    location_region: string
    cost_band?: string
  }
}

type MaterialCandidateRequest = {
  material_request_id: string
  score: number
  rationale: Record<string, unknown>
  request: {
    id: string
    title: string
    material_type: string
    resource_nature: string
    category_tags: string[]
    quantity_needed: number
    quantity_unit: string
    availability_start?: string | null
    availability_end?: string | null
    condition_min: string
    access_mode: string
    location_region: string
    cost_band_max?: string
  }
}

const UI_ALLOWED_LIFECYCLE_TRANSITIONS: Record<ShareVisibilityState, ShareVisibilityState[]> = {
  private: ['shared_unindexed', 'inactive', 'deleted'],
  shared_unindexed: ['private', 'shared_indexed', 'revoked', 'inactive', 'deleted'],
  shared_indexed: ['private', 'shared_unindexed', 'revoked', 'inactive', 'deleted'],
  revoked: ['private', 'shared_unindexed', 'inactive', 'deleted'],
  inactive: ['private', 'shared_unindexed', 'deleted'],
  deleted: [],
}

async function apiErrorText(res: Response): Promise<string> {
  const text = await res.text().catch(() => res.statusText)
  try {
    const j = JSON.parse(text) as { detail?: unknown }
    if (j?.detail != null) {
      if (typeof j.detail === 'string') return j.detail
      if (Array.isArray(j.detail)) {
        const parts = j.detail
          .map((x) => (x && typeof x === 'object' && 'msg' in x ? String((x as { msg?: string }).msg ?? '') : ''))
          .filter(Boolean)
        if (parts.length) return parts.join('; ')
      }
    }
  } catch {
    /* ignore */
  }
  return text || res.statusText
}

function executionStepErrorMessage(e: unknown): string {
  return e instanceof Error ? e.message : 'Request failed'
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, { credentials: 'include' })
  if (!res.ok) throw new Error(await apiErrorText(res))
  return res.json()
}

function isAbortError(e: unknown): boolean {
  if (e instanceof DOMException && e.name === 'AbortError') return true
  if (e instanceof Error && e.name === 'AbortError') return true
  return false
}

async function apiPost<T>(path: string, body: unknown, init?: { signal?: AbortSignal }): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: init?.signal,
  })
  if (!res.ok) throw new Error(await apiErrorText(res))
  return res.json()
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await apiErrorText(res))
  return res.json()
}

async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await apiErrorText(res))
  return res.json()
}

async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, { method: 'DELETE', credentials: 'include' })
  if (!res.ok) throw new Error(await apiErrorText(res))
}

function traceCandidatePlacementSuggest(
  meetingId: string | null | undefined,
  clientCorrelationId: string | undefined,
  out: CandidatePlacementResponse,
): void {
  try {
    emitMeetingExtractionTrace({
      action_intent: 'candidate_placement_suggest',
      meeting_id: meetingId ?? null,
      input_snapshot: `candidate_placement_suggest\nclient_correlation_id:${clientCorrelationId ?? ''}`.slice(0, 8000),
      output_summary: JSON.stringify({
        proposed_type: out.proposed_type,
        placement_mode: out.placement_mode,
        execution_blocked: out.execution_blocked,
        error: out.error ?? null,
        confidence: out.confidence,
      }).slice(0, 12000),
      resolved_model_used: out.model_used ?? null,
      resolved_provider_used: out.provider_used ?? null,
    })
  } catch {
    /* ignore */
  }
}

function traceCandidatePresortTriage(
  meetingId: string | null | undefined,
  clientCorrelationId: string | undefined,
  out: CandidatePresortTriageApiResponse,
): void {
  try {
    emitMeetingExtractionTrace({
      action_intent: 'candidate_presort_triage',
      meeting_id: meetingId ?? null,
      input_snapshot: `candidate_presort_triage\nclient_correlation_id:${clientCorrelationId ?? ''}`.slice(0, 8000),
      output_summary: JSON.stringify({
        presort_bucket: out.presort_bucket,
        presort_type: out.presort_type,
        execution_blocked: out.execution_blocked,
        error: out.error ?? null,
      }).slice(0, 12000),
      resolved_model_used: out.model_used ?? null,
      resolved_provider_used: out.provider_used ?? null,
    })
  } catch {
    /* ignore */
  }
}

function traceMeetingExtractChunkRetry(
  meetingId: string | null | undefined,
  chunkId: string,
  notesCharLen: number,
  data: ExtractMeetingResponse,
): void {
  try {
    const meta = data.extractionMeta
    const baseSnap = buildMeetingExtractionInputSnapshot({
      meeting_id: meetingId ?? null,
      path: 'chunks',
      notes_char_len: notesCharLen,
    })
    emitMeetingExtractionTrace({
      action_intent: 'meeting_extract_chunks',
      meeting_id: meetingId ?? null,
      input_snapshot: `${baseSnap}\nchunk_retry:1\ndiagnostics_chunk_id:${chunkId}`.slice(0, 8000),
      output_summary: JSON.stringify({
        chunk_id: chunkId,
        chunk_retry: true,
        candidates_n: Array.isArray(data.candidates) ? data.candidates.length : 0,
        execution_blocked: data.execution_blocked,
        error: data.error ?? null,
      }).slice(0, 12000),
      resolved_model_used: meta?.resolvedModelUsed ?? null,
      resolved_provider_used: meta?.resolvedProviderUsed ?? null,
    })
  } catch {
    /* ignore */
  }
}

interface EvaluateProposal {
  learning_record_id?: string
  estimated_cost_ai?: string
  estimated_timeframe_ai?: string
  philosophical_alignment_ai?: string
  /** 3–5 concrete micro-steps from evaluation (serialized into next_step_ai on apply). */
  next_steps?: string[]
  recommendation?: string
  /** Model-suggested priority 0–5 (persisted as evaluation_priority on apply). */
  evaluation_priority?: number
  /** Evaluation-derived; informational only (manual scoring removed). */
  strategic_value?: number
  /** Evaluation-derived; informational only (manual scoring removed). */
  energy_impact?: number
  error?: string
  execution_blocked?: boolean
  privacy_block_reason?: string | null
  model_used?: string | null
  provider_used?: string | null
}

const INITIATIVE_EVAL_INVALID_UI = 'Evaluation failed — invalid AI response'

/** True if value looks like a bare JSON key / model fragment, not user-facing text. */
function isInitiativeEvalValueJunk(value: string | undefined | null): boolean {
  const t = String(value ?? '').trim()
  if (!t) return false
  return /^\s*[\r\n]*["']?(?:estimated_cost_ai|estimated_cost|estimated_timeframe_ai|estimated_timeframe|philosophical_alignment_ai|strategic_alignment|next_step_ai|next_step|recommendation)["']?\s*$/i.test(
    t,
  )
}

function initiativeEvalFieldRenderable(value: string | undefined | null): boolean {
  const t = String(value ?? '').trim()
  return t.length > 0 && !isInitiativeEvalValueJunk(value)
}

function hasProposalNumericScores(p: EvaluateProposal): boolean {
  const ok = (n: unknown) => {
    if (typeof n !== 'number' || !Number.isFinite(n)) return false
    const r = Math.round(n)
    return r >= 0 && r <= 5 && Math.abs(n - r) < 1e-6
  }
  return ok(p.evaluation_priority) && ok(p.strategic_value) && ok(p.energy_impact)
}

function hasProposalNextSteps(p: EvaluateProposal): boolean {
  if (!Array.isArray(p.next_steps)) return false
  const steps = p.next_steps.map((s) => String(s ?? '').trim()).filter(Boolean)
  return steps.length >= 3 && steps.length <= 5
}

/** Any non-error proposal row we can show without leaking broken model output. */
function initiativeProposalHasRenderableFields(p: EvaluateProposal): boolean {
  if (p.error) return false
  const filledStrings = [
    p.recommendation,
    p.estimated_cost_ai,
    p.estimated_timeframe_ai,
    p.philosophical_alignment_ai,
  ].filter((s) => initiativeEvalFieldRenderable(s)).length
  return filledStrings >= 2 && hasProposalNumericScores(p) && hasProposalNextSteps(p)
}

const INITIATIVE_STATUS_OPTIONS = ['Draft', 'Evaluating', 'Approved', 'Active', 'Paused', 'Complete', 'Killed'].map((s) => ({ value: s, label: s }))

type SeatRole = {
  role: string
  personId: string | null
  effort: string
  notes: string
}


function parseIdeaRequiredRolesToSeats(requiredRoles: string): SeatRole[] {
  const raw = (requiredRoles || '').trim()
  if (!raw) return []
  const parts = raw.split(/[,;]+/).map((p) => p.trim()).filter(Boolean)
  const seats: SeatRole[] = []
  for (const part of parts) {
    const m = part.match(/^([0-9]+(?:\.[0-9]+)?)\s*(.*)$/)
    if (m) {
      const effort = m[1]
      const role = (m[2] || '').trim()
      if (role) seats.push({ role, personId: null, effort, notes: '' })
      else seats.push({ role: part, personId: null, effort: '', notes: '' })
    } else {
      seats.push({ role: part, personId: null, effort: '', notes: '' })
    }
  }
  return seats
}

function InitiativeDetailPanel({
  initiativeId,
  persons,
  ideas,
  projects,
  assets,
  onClose,
  onSaved,
  apiGet,
  apiPatch,
  apiPost,
  apiDelete,
  serverWriteNonce = 0,
}: {
  initiativeId: string
  persons: Person[]
  ideas: Idea[]
  projects: Project[]
  assets: Asset[]
  onClose: () => void
  onSaved: () => void
  apiGet: <T>(path: string) => Promise<T>
  apiPatch: <T>(path: string, body: unknown) => Promise<T>
  apiPost: <T>(path: string, body: unknown) => Promise<T>
  apiDelete: (path: string) => Promise<void>
  /** Bumps when council/Lane A writes to VE server-side — reload open panel from API. */
  serverWriteNonce?: number
}) {
  const [initiative, setInitiative] = useState<Initiative | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [evaluateLoading, setEvaluateLoading] = useState(false)
  const [evaluateProposal, setEvaluateProposal] = useState<EvaluateProposal | null>(null)
  const [confirmAction, setConfirmAction] = useState<'kill' | 'delete' | null>(null)
  const [initiativeFooterMenuOpen, setInitiativeFooterMenuOpen] = useState(false)
  const [aiFieldsEditable, setAiFieldsEditable] = useState(false)
  const [aiDecision, setAiDecision] = useState<'none' | 'accepted' | 'modify' | 'defer'>('none')
  const [seats, setSeats] = useState<SeatRole[]>([])
  const [executionSteps, setExecutionSteps] = useState<ExecutionStep[]>([])
  const [newExecStepTitle, setNewExecStepTitle] = useState('')
  const [execStepsBusy, setExecStepsBusy] = useState(false)
  const [execStepsError, setExecStepsError] = useState<string | null>(null)
  /** Latest initiative evaluate trace for apply / dismiss / supersede parity */
  const lastInitiativeEvaluateTraceRef = useRef<AiActionTrace | null>(null)
  const lastInitiativeEvaluateLearningIdRef = useRef<string | null>(null)
  /** Collapsed by default; "+ Add step" reveals inline composer */
  const [execAddStepOpen, setExecAddStepOpen] = useState(false)
  const [execStepOverflowId, setExecStepOverflowId] = useState<string | null>(null)
  const [execStepEditingId, setExecStepEditingId] = useState<string | null>(null)
  const [execStepEditDraft, setExecStepEditDraft] = useState('')
  const [addStepSuggestHint, setAddStepSuggestHint] = useState<string | null>(null)
  const execStepEditingIdRef = useRef<string | null>(null)
  const execStepEditDraftRef = useRef('')

  const currentExecutionStepId = useMemo(() => {
    const next = executionSteps.find((s) => !s.is_done)
    return next?.id ?? null
  }, [executionSteps])

  useEffect(() => {
    setExecStepsError(null)
    setExecStepOverflowId(null)
    setExecStepEditingId(null)
    setExecStepEditDraft('')
    setExecAddStepOpen(false)
    setNewExecStepTitle('')
    setAddStepSuggestHint(null)
  }, [initiativeId])

  useEffect(() => {
    if (!execStepOverflowId) return
    const onDoc = (e: MouseEvent) => {
      const el = e.target as HTMLElement
      if (el.closest('[data-exec-step-overflow-root]')) return
      setExecStepOverflowId(null)
    }
    document.addEventListener('mousedown', onDoc, true)
    return () => document.removeEventListener('mousedown', onDoc, true)
  }, [execStepOverflowId])

  useEffect(() => {
    if (!initiativeFooterMenuOpen) return
    const onDoc = (e: MouseEvent) => {
      const el = e.target as HTMLElement
      if (el.closest('[data-initiative-footer-overflow-root]')) return
      setInitiativeFooterMenuOpen(false)
    }
    document.addEventListener('mousedown', onDoc, true)
    return () => document.removeEventListener('mousedown', onDoc, true)
  }, [initiativeFooterMenuOpen])

  useEffect(() => {
    execStepEditingIdRef.current = execStepEditingId
  }, [execStepEditingId])

  useEffect(() => {
    execStepEditDraftRef.current = execStepEditDraft
  }, [execStepEditDraft])

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<VeFocusApplyRewriteDetail>).detail
      if (!d || d.entity_type !== 'initiative' || d.entity_id !== initiativeId || !d.text) return
      const fk = d.field_key
      if (fk === 'brief') setForm((f) => ({ ...f, brief: d.text }))
      else if (fk === 'recommendation') setForm((f) => ({ ...f, recommendation: d.text }))
      else if (fk === 'philosophical_alignment_ai') setForm((f) => ({ ...f, philosophical_alignment_ai: d.text }))
      else if (fk === 'dependencies') setForm((f) => ({ ...f, dependencies: d.text }))
    }
    window.addEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, handler)
    return () => window.removeEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, handler)
  }, [initiativeId])

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d || d.entity_type !== 'initiative' || d.entity_id !== initiativeId || !d.text) return
      const map: Record<string, string> = {
        brief: 'brief',
        recommendation: 'recommendation',
        philosophical_alignment_ai: 'philosophical_alignment_ai',
        dependencies: 'dependencies',
      }
      const formKey = map[d.field_key]
      if (!formKey) return
      setForm((f) => {
        const prev = String((f as Record<string, unknown>)[formKey] ?? '')
        const next = insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd)
        return { ...f, [formKey]: next }
      })
    }
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, handler)
    return () => window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, handler)
  }, [initiativeId])

  const refreshExecutionSteps = useCallback(async () => {
    try {
      const rows = await apiGet<ExecutionStep[]>(`/initiatives/${initiativeId}/execution-steps`)
      setExecutionSteps(Array.isArray(rows) ? rows : [])
    } catch {
      setExecutionSteps([])
    }
  }, [initiativeId, apiGet])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      apiGet<Initiative>(`/initiatives/${initiativeId}`),
      apiGet<ExecutionStep[]>(`/initiatives/${initiativeId}/execution-steps`).catch(() => [] as ExecutionStep[]),
    ])
      .then(([data, steps]) => {
        if (cancelled) return
        setInitiative(data)
        const stepRows = Array.isArray(steps) ? steps : []
        setExecutionSteps(stepRows)
        const backendSeats = Array.isArray((data as any).seats) ? (data as any).seats as any[] : null
        const decodedSeats: SeatRole[] = backendSeats
          ? backendSeats.map((s) => ({
            role: String(s?.role ?? ''),
            personId: s?.assigned_person_id ? String(s.assigned_person_id) : null,
            effort: s?.estimated_effort ? String(s.estimated_effort) : '',
            notes: String(s?.notes ?? ''),
          }))
          : []
        const rowsExist = stepRows.length > 0
        setForm({
          title: data.title,
          brief: data.brief,
          status: data.status,
          source_idea_id: data.source_idea_id ?? '',
          owner_id: data.owner_id ?? '',
          evaluation_priority: data.evaluation_priority ?? null,
          estimated_cost_ai: data.estimated_cost_ai ?? '',
          estimated_timeframe_ai: data.estimated_timeframe_ai ?? '',
          philosophical_alignment_ai: data.philosophical_alignment_ai ?? '',
          next_step_ai: rowsExist ? '' : (data.next_step_ai ?? ''),
          recommendation: data.recommendation ?? '',
          required_assets: data.required_assets ?? [],
          dependencies: data.dependencies ?? '',
          risks: data.risks ?? '',
          kill_criteria: data.kill_criteria ?? '',
          notes: data.notes ?? '',
        })
        setSeats(decodedSeats)
      })
      .catch(() => {
        if (!cancelled) setInitiative(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [initiativeId, apiGet, persons, serverWriteNonce])

  const handleEvaluate = async () => {
    const prevT = lastInitiativeEvaluateTraceRef.current
    if (prevT) {
      postVisionExecutionLearningOutcome(apiPost, lastInitiativeEvaluateLearningIdRef.current, 'edited')
      pushAiActionTrace(withTraceOutcome(prevT, 'edited'))
      lastInitiativeEvaluateTraceRef.current = null
      lastInitiativeEvaluateLearningIdRef.current = null
    }
    setEvaluateLoading(true)
    setEvaluateProposal(null)
    setAiDecision('none')
    try {
      const res = await apiPost<EvaluateProposal>(`/initiatives/${initiativeId}/evaluate`, {
        routing_context: visionExecutionEvaluateRouting(VE_EVALUATE_ACTION_INTENTS.initiative_evaluate),
      })
      setEvaluateProposal(res)
      if (res && typeof res === 'object' && !res.error) {
        const lid =
          typeof res.learning_record_id === 'string' && res.learning_record_id.trim()
            ? res.learning_record_id.trim()
            : null
        lastInitiativeEvaluateLearningIdRef.current = lid
        const tr = createAiActionTrace({
          surface: 'vision_execution',
          action_kind: 'structured_evaluation',
          action_intent: 'initiative_evaluate',
          subject_type: 'initiative',
          subject_id: initiativeId,
          field_key: null,
          input_snapshot: 'POST /initiatives/{id}/evaluate',
          prompt_version: 've_initiative_evaluate_v1',
          model_used: res.model_used ?? null,
          provider_used: res.provider_used ?? null,
          output: JSON.stringify({
            has_recommendation: Boolean(res.recommendation && String(res.recommendation).trim()),
            next_steps_n: Array.isArray(res.next_steps) ? res.next_steps.length : 0,
          }),
          user_outcome: 'none',
        })
        lastInitiativeEvaluateTraceRef.current = tr
        pushAiActionTrace(tr)
      }
    } catch (e) {
      setEvaluateProposal({ error: e instanceof Error ? e.message : 'Evaluate failed' })
    } finally {
      setEvaluateLoading(false)
    }
  }

  /** Same rules for close-without-Apply and save-without-Apply: modify + visible proposal → edited, else dismissed. */
  const inferredInitiativeEvalOutcomeWhenNotApplied = (): VisionLearningUserOutcome => {
    const proposalOpen =
      evaluateProposal != null &&
      !evaluateProposal.error &&
      initiativeProposalHasRenderableFields(evaluateProposal)
    return aiDecision === 'modify' && proposalOpen ? 'edited' : 'dismissed'
  }

  /**
   * Panel close without going through Save / explicit decline buttons.
   * TODO: closing vs explicit "Dismiss" could get separate outcomes later without extending AiUserOutcome.
   */
  const recordInitiativeEvalDismissedIfPending = () => {
    const t = lastInitiativeEvaluateTraceRef.current
    if (t) {
      const outcome = inferredInitiativeEvalOutcomeWhenNotApplied()
      postVisionExecutionLearningOutcome(apiPost, lastInitiativeEvaluateLearningIdRef.current, outcome)
      pushAiActionTrace(withTraceOutcome(t, outcome))
      lastInitiativeEvaluateTraceRef.current = null
      lastInitiativeEvaluateLearningIdRef.current = null
    }
  }

  const handleInitiativePanelClose = () => {
    recordInitiativeEvalDismissedIfPending()
    onClose()
  }

  const handleApplyProposal = async () => {
    if (!evaluateProposal || evaluateProposal.error || !initiativeProposalHasRenderableFields(evaluateProposal)) return
    const newSug = evaluateProposal.evaluation_priority as number
    const stepsClean = (evaluateProposal.next_steps ?? []).map((s) => String(s ?? '').trim()).filter(Boolean)
    const existingSteps = await apiGet<ExecutionStep[]>(`/initiatives/${initiativeId}/execution-steps`).catch(() => [] as ExecutionStep[])
    const hadRows = Array.isArray(existingSteps) && existingSteps.length > 0
    let materializeFailed = false
    if (!hadRows && stepsClean.length >= 3) {
      try {
        await apiPost<ExecutionStep[]>(`/initiatives/${initiativeId}/execution-steps/materialize`, {
          titles: stepsClean,
          replace: false,
          source: 'ai',
        })
        setExecStepsError(null)
        await refreshExecutionSteps()
      } catch (e) {
        materializeFailed = true
        setExecStepsError(executionStepErrorMessage(e))
      }
    }
    const applied = {
      estimated_cost_ai: evaluateProposal.estimated_cost_ai ?? '',
      estimated_timeframe_ai: evaluateProposal.estimated_timeframe_ai ?? '',
      philosophical_alignment_ai: evaluateProposal.philosophical_alignment_ai ?? '',
      recommendation: evaluateProposal.recommendation ?? '',
      evaluation_priority: newSug,
    }
    try {
      await apiPost<{ id: string }>('/decisions', {
        user_id: null,
        entity_type: 'initiative',
        entity_id: initiativeId,
        decision_type: 'evaluation_applied',
        ai_proposal_snapshot: evaluateProposal,
        final_values_snapshot: {
          ...applied,
          execution_steps_materialized: !hadRows && stepsClean.length >= 3 && !materializeFailed,
        },
      })
    } catch {
      // best-effort: still apply to form
    }
    setForm((f) => ({
      ...f,
      ...applied,
      next_step_ai: '',
    }))
    setInitiative((prev) =>
      prev
        ? {
            ...prev,
            evaluation_priority: newSug,
            next_step_ai: '',
          }
        : prev,
    )
    setAiDecision('accepted')
    setAiFieldsEditable(false)
    if (!materializeFailed) {
      setEvaluateProposal(null)
    }
    const evalTrace = lastInitiativeEvaluateTraceRef.current
    if (evalTrace) {
      postVisionExecutionLearningOutcome(apiPost, lastInitiativeEvaluateLearningIdRef.current, 'applied')
      pushAiActionTrace(withTraceOutcome(evalTrace, 'applied'))
      lastInitiativeEvaluateTraceRef.current = null
      lastInitiativeEvaluateLearningIdRef.current = null
    }
    await refreshExecutionSteps()
  }

  const handleSave = async () => {
    setSaveError(null)
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        title: form.title,
        brief: form.brief,
        status: form.status,
        source_idea_id: (form.source_idea_id as string) || null,
        owner_id: (form.owner_id as string) || null,
        evaluation_priority: form.evaluation_priority === '' || form.evaluation_priority === undefined ? null : Number(form.evaluation_priority),
        estimated_cost_ai: form.estimated_cost_ai ?? '',
        estimated_timeframe_ai: form.estimated_timeframe_ai ?? '',
        philosophical_alignment_ai: form.philosophical_alignment_ai ?? '',
        next_step_ai: executionSteps.length > 0 ? '' : (form.next_step_ai ?? ''),
        recommendation: form.recommendation ?? '',
        required_assets: Array.isArray(form.required_assets) ? form.required_assets : [],
        seats: seats.map((s) => ({
          role: s.role,
          assigned_person_id: s.personId || null,
          estimated_effort: s.effort.trim() ? s.effort.trim() : null,
          notes: s.notes || '',
        })),
        dependencies: form.dependencies ?? '',
        risks: form.risks ?? '',
        kill_criteria: form.kill_criteria ?? '',
        notes: form.notes ?? '',
      }
      const status = form.status as string
      if (status === 'Approved' || status === 'Killed') {
        try {
          await apiPost<{ id: string }>('/decisions', {
            user_id: null,
            entity_type: 'initiative',
            entity_id: initiativeId,
            decision_type: status === 'Approved' ? 'initiative_approved' : 'initiative_rejected',
            ai_proposal_snapshot: null,
            final_values_snapshot: payload,
          })
        } catch {
          // best-effort: still save initiative
        }
      }
      await apiPatch<Initiative>(`/initiatives/${initiativeId}`, payload)
      onSaved()
      const pendingEval = lastInitiativeEvaluateTraceRef.current
      if (pendingEval) {
        const outcome = inferredInitiativeEvalOutcomeWhenNotApplied()
        postVisionExecutionLearningOutcome(apiPost, lastInitiativeEvaluateLearningIdRef.current, outcome)
        pushAiActionTrace(withTraceOutcome(pendingEval, outcome))
        lastInitiativeEvaluateTraceRef.current = null
        lastInitiativeEvaluateLearningIdRef.current = null
      }
      onClose()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const linkedProjects = projects.filter((p) => p.initiative_id === initiativeId)

  if (loading) {
    return (
      <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0 overflow-auto">
        <p className="text-slate-500 text-sm">Loading initiative…</p>
      </div>
    )
  }
  if (!initiative) {
    return (
      <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0 overflow-auto">
        <p className="text-slate-500 text-sm">Initiative not found.</p>
        <button type="button" onClick={handleInitiativePanelClose} className="mt-2 text-slate-400 hover:text-slate-200 text-sm">Close</button>
      </div>
    )
  }

  const onConfirmKill = async () => {
    setConfirmAction(null)
    setSaving(true)
    try {
      await apiPatch<Initiative>(`/initiatives/${initiativeId}`, { status: 'Killed' })
      setEvaluateProposal(null)
      setAiDecision('none')
      onSaved(); handleInitiativePanelClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Update failed') } finally { setSaving(false) }
  }
  const onConfirmDelete = async () => {
    setConfirmAction(null)
    setSaving(true)
    try {
      await apiDelete(`/initiatives/${initiativeId}`)
      setEvaluateProposal(null)
      setAiDecision('none')
      onSaved(); handleInitiativePanelClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Delete failed') } finally { setSaving(false) }
  }

  const reqAssets = (form.required_assets as string[]) ?? []

  const commitSeats = (nextSeats: SeatRole[]) => {
    setSeats(nextSeats)
  }

  const updateSeat = (idx: number, patch: Partial<SeatRole>) => {
    const next = seats.map((s, i) => (i === idx ? { ...s, ...patch } : s))
    commitSeats(next)
  }

  const removeSeat = (idx: number) => {
    const next = seats.filter((_, i) => i !== idx)
    commitSeats(next)
  }

  const addSeat = () => {
    const next: SeatRole[] = [...seats, { role: '', personId: null, effort: '', notes: '' }]
    commitSeats(next)
  }
  /** Row added but not yet started — do not treat as resourcing gaps or readiness debt. */
  const isDraftSeat = (s: SeatRole) =>
    !s.role.trim() && !s.personId && !s.effort.trim() && !s.notes.trim()
  const resourcingSeats = seats.filter((s) => !isDraftSeat(s))

  const seatInputBase = 'w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm'
  const ownerOptions = persons.map((p) => ({ value: p.id, label: p.name }))
  const ideaOptions = [{ value: '', label: 'None' }, ...ideas.map((i) => ({ value: i.id, label: i.title || i.id }))]

  const seatRowCount = seats.length
  const seatTotal = resourcingSeats.length
  const seatFilled = resourcingSeats.filter((s) => Boolean(s.personId)).length
  const seatUnfilled = Math.max(0, seatTotal - seatFilled)
  const seatRoleMissing = resourcingSeats.filter((s) => !s.role.trim()).length
  const seatEffortMissing = resourcingSeats.filter((s) => !s.effort.trim()).length
  const seatEffortProvided = seatTotal - seatEffortMissing

  const parseFirstNumber = (text: string): number | null => {
    const m = String(text).match(/-?\d+(\.\d+)?/)
    if (!m) return null
    const n = Number(m[0])
    return Number.isFinite(n) ? n : null
  }
  const effortNumbers = resourcingSeats
    .map((s) => parseFirstNumber(s.effort.trim()))
    .filter((n): n is number => typeof n === 'number')
  const effortTotalHeuristic = effortNumbers.length ? effortNumbers.reduce((a, b) => a + b, 0) : null

  const readiness = (() => {
    if (seatTotal === 0) return 'low'
    const roleRatio = seatRoleMissing === 0 ? 1 : (seatTotal - seatRoleMissing) / seatTotal
    const assigneeRatio = seatFilled / seatTotal
    const effortRatio = seatEffortMissing === 0 ? 1 : seatEffortProvided / seatTotal
    const score = 0.4 * assigneeRatio + 0.3 * roleRatio + 0.3 * effortRatio
    if (score >= 0.9 && seatRoleMissing === 0 && seatEffortMissing === 0) return 'high'
    if (score >= 0.6) return 'medium'
    return 'low'
  })()

  const assetGapIds = (reqAssets as string[]).filter((id) => {
    const a = assets.find((x) => x.id === id)
    return !a || a.status === 'Unavailable' || a.status === 'Archived'
  })
  const missingAssetLabels = assetGapIds.map((id) => {
    const a = assets.find((x) => x.id === id)
    return (a && a.name) ? a.name : 'Unknown asset'
  })

  const gapLines: string[] = []
  if (seatTotal > 0 && seatRoleMissing > 0) {
    gapLines.push(`${seatRoleMissing} seat${seatRoleMissing === 1 ? '' : 's'} missing role name${seatRoleMissing === 1 ? '' : 's'}`)
  }
  if (seatTotal > 0 && seatUnfilled > 0) {
    gapLines.push(`${seatUnfilled} seat${seatUnfilled === 1 ? '' : 's'} unfilled`)
  }
  const unassignedRoleSeats = resourcingSeats
    .filter((s) => Boolean(s.role.trim()) && !s.personId)
    .slice(0, 2)
    .map((s) => `${s.role.trim()} seat has no assignee`)
  if (unassignedRoleSeats.length) gapLines.push(...unassignedRoleSeats)
  if (seatTotal > 0 && seatEffortMissing > 0) {
    gapLines.push(`No effort estimates for ${seatEffortMissing} seat${seatEffortMissing === 1 ? '' : 's'}`)
  }
  if (missingAssetLabels.length > 0) {
    gapLines.push(missingAssetLabels.length === 1 ? `Missing: ${missingAssetLabels[0]}` : `Missing: ${missingAssetLabels.join(' and ')}`)
  }

  const initiativeRecommendation = String(form.recommendation ?? '').trim()
  const initiativeNextStep = nextStepsPrimaryLine(String(form.next_step_ai ?? ''))
  const initiativeStatus = String(form.status ?? initiative.status ?? '').trim()
  const initiativeRecLower = initiativeRecommendation.toLowerCase()
  const isInitiativeBlocked = (() => {
    const statusLower = initiativeStatus.toLowerCase()
    if (statusLower === 'killed') return true
    if (statusLower === 'rejected') return true
    if (initiativeRecLower.includes('reject') || initiativeRecLower.includes('kill')) return true
    return false
  })()

  const initiativeFirstGap = gapLines[0] ?? ''
  const initiativeSynthesisSentence = (() => {
    if (isInitiativeBlocked) return `Blocked — ${initiativeFirstGap || 'decision locked'}`
    if (!initiativeRecommendation) return 'Decision pending'
    if (readiness === 'high' && missingAssetLabels.length === 0) return 'Ready to execute'
    if (readiness === 'high' && missingAssetLabels.length > 0) return `Ready except missing assets — ${missingAssetLabels.length === 1 ? missingAssetLabels[0] : 'required assets'}`
    if (readiness === 'medium') {
      return initiativeFirstGap
        ? `Proceed, but resourcing is partial — ${initiativeFirstGap}`
        : 'Proceed, but resourcing is partial'
    }
    return initiativeFirstGap
      ? `Proceed, but resourcing is incomplete — ${initiativeFirstGap}`
      : 'Proceed, but resourcing is incomplete'
  })()

  /** Hero “Next” line body only — label “Next:” is rendered in JSX (aligned with Project/Task). */
  const initiativeNextStepContent = (() => {
    if (isInitiativeBlocked) return 'Resolve blocking issues'
    if (!initiativeRecommendation) return 'Run evaluation'
    const hasSeatGaps = seatRoleMissing > 0 || seatUnfilled > 0 || seatEffortMissing > 0
    const hasAssetGaps = missingAssetLabels.length > 0
    if (seatRoleMissing > 0 && hasAssetGaps) return 'Name roles and add required assets'
    if (seatRoleMissing > 0) return 'Name missing roles'
    if (seatUnfilled > 0 && hasAssetGaps) return 'Fill seats and add required assets'
    if (seatUnfilled > 0) return 'Fill remaining seats'
    if (seatEffortMissing > 0 && hasAssetGaps) return 'Add effort estimates and required assets'
    if (seatEffortMissing > 0) return 'Add effort estimates'
    if (hasAssetGaps) return missingAssetLabels.length === 1 ? `Add ${missingAssetLabels[0]}` : 'Secure required assets'
    if (initiativeNextStep) return initiativeNextStep
    if (readiness === 'high') return 'Start first project'
    return 'Tighten resourcing'
  })()

  const initiativeReadinessClass = readiness === 'high' ? 'text-emerald-200' : readiness === 'medium' ? 'text-amber-200' : 'text-red-200'

  return (
    <div className="flex-1 min-h-0 rounded-xl border border-slate-600 bg-slate-800/50 p-4 min-w-0 overflow-hidden flex flex-col">
      <div className="flex justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-200">Initiative</h3>
        <button type="button" onClick={handleInitiativePanelClose} className="text-slate-400 hover:text-slate-200 text-sm">Close</button>
      </div>
      <div className="space-y-4 flex-1 overflow-y-auto min-h-0">
        {/* Summary strip — density aligned with Project/Task detail heroes */}
        <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] uppercase tracking-wide border max-w-[18rem] truncate ${
                isInitiativeBlocked
                  ? 'border-red-500/60 text-red-200 bg-red-900/20'
                  : readiness === 'high'
                    ? 'border-emerald-500/60 text-emerald-200 bg-emerald-900/20'
                    : 'border-amber-500/60 text-amber-200 bg-amber-900/20'
              }`}
            >
              {initiativeRecommendation ? initiativeRecommendation.replace(/\s+/g, ' ') : 'Decision pending'}
            </span>
          </div>
          <div
            className={`mt-1 text-[11px] ${isInitiativeBlocked ? 'text-red-200/80' : 'text-slate-500'}`}
          >
            <span className={initiativeReadinessClass}>{readiness}</span>
            <span className="text-slate-600"> · </span>
            {initiativeSynthesisSentence}
          </div>
          <div className="mt-1.5 text-[11px] text-slate-500">
            Next: <span className="text-slate-200">{initiativeNextStepContent}</span>
          </div>
        </div>
        <TraceabilityMeta notesOrDescription={initiative.notes} />
        {saveError && <p className="text-red-400 text-xs">{saveError}</p>}
        <div
          className="rounded-lg border border-slate-700/80 bg-slate-900/40 px-3 py-2 mb-2 space-y-1"
          data-testid="initiative-channel-legend"
        >
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Fields by maintenance channel</div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-400 leading-snug">
            <span>
              <span className="text-slate-300 font-medium">Water</span> — owner, seats, timeframe, execution cadence
            </span>
            <span>
              <span className="text-slate-300 font-medium">Soil</span> — brief, decision narrative, alignment, recommendation
            </span>
            <span>
              <span className="text-slate-300 font-medium">Condition</span> — status, risks, dependencies, next step, kill criteria
            </span>
            <span>
              <span className="text-slate-300 font-medium">Fruit</span> — execution steps checklist, measurable outputs
            </span>
          </div>
        </div>
        <DetailSection title="Identity / scope" defaultOpen={true}>
          <DetailField label="Title" value={(form.title as string) ?? ''} onChange={(v) => setForm((f) => ({ ...f, title: v }))} />
          <VeFocusRegion
            entity_type="initiative"
            entity_id={initiativeId}
            field_key="brief"
            field_label="Brief"
            field_kind="long_form_strategy"
            getCurrentText={() => String(form.brief ?? '')}
          >
            <DetailField label="Brief" value={(form.brief as string) ?? ''} onChange={(v) => setForm((f) => ({ ...f, brief: v }))} textarea rows={3} />
          </VeFocusRegion>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            <DetailField label="Owner" value={(form.owner_id as string) ?? ''} onChange={(v) => setForm((f) => ({ ...f, owner_id: v || null }))} options={[{ value: '', label: 'None' }, ...ownerOptions]} />
            <DetailField label="Status" value={(form.status as string) ?? 'Draft'} onChange={(v) => setForm((f) => ({ ...f, status: v }))} options={INITIATIVE_STATUS_OPTIONS} />
          </div>
          <DetailField label="Source idea" value={(form.source_idea_id as string) ?? ''} onChange={(v) => setForm((f) => ({ ...f, source_idea_id: v || null }))} options={ideaOptions} />
          {linkedProjects.length > 0 ? (
            <div className="mt-2 text-xs text-slate-400">
              Linked projects: {linkedProjects.map((p) => p.title).join(', ')}
            </div>
          ) : (
            <div className="mt-2 text-[11px] text-slate-500">No projects linked yet — link or create one from the project list.</div>
          )}
        </DetailSection>

        <DetailSection title="Decision / Summary" defaultOpen={false}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-slate-300">Decision & action</span>
            <button
              type="button"
              data-testid="initiative-run-evaluation"
              onClick={handleEvaluate}
              disabled={evaluateLoading}
              className="px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs"
            >
              {evaluateLoading ? 'Evaluating…' : 'Run evaluation'}
            </button>
          </div>
          {evaluateLoading && !evaluateProposal && (
            <div className="mb-2 p-2 rounded-lg border border-amber-700/70 bg-amber-900/30 text-xs text-amber-100">
              Running evaluation… AI proposes scores, recommendation, next step, and resourcing estimates.
            </div>
          )}
          {evaluateProposal && (
            <div className="mb-2 p-3 rounded-lg border border-amber-700 bg-amber-900/20">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-medium text-amber-200">AI proposal</h4>
                <span className="px-1.5 py-0.5 rounded-full border border-amber-500 text-[10px] uppercase tracking-wide text-amber-200">
                  AI
                </span>
              </div>
              {evaluateProposal.error ? (
                <p className="text-red-400 text-xs">{evaluateProposal.error}</p>
              ) : !initiativeProposalHasRenderableFields(evaluateProposal) ? (
                <p className="text-red-400 text-xs">{INITIATIVE_EVAL_INVALID_UI}</p>
              ) : (
                <div className="space-y-1.5 text-xs text-slate-300">
                  {initiativeEvalFieldRenderable(evaluateProposal.recommendation) && (
                    <p>
                      <span className="text-slate-500">Recommendation:</span>{' '}
                      {String(evaluateProposal.recommendation).replace(/\s+/g, ' ')}
                    </p>
                  )}
                  {hasProposalNextSteps(evaluateProposal) && (
                    <div>
                      <span className="text-slate-500">Next steps:</span>
                      <ol className="list-decimal list-inside mt-0.5 space-y-0.5 text-slate-300">
                        {(evaluateProposal.next_steps ?? []).map((step, i) => (
                          <li key={i}>{String(step).replace(/\s+/g, ' ')}</li>
                        ))}
                      </ol>
                    </div>
                  )}
                  {initiativeEvalFieldRenderable(evaluateProposal.estimated_cost_ai) && (
                    <p>
                      <span className="text-slate-500">Cost:</span>{' '}
                      {String(evaluateProposal.estimated_cost_ai).replace(/\s+/g, ' ')}
                    </p>
                  )}
                  {initiativeEvalFieldRenderable(evaluateProposal.estimated_timeframe_ai) && (
                    <p>
                      <span className="text-slate-500">Timeframe:</span>{' '}
                      {String(evaluateProposal.estimated_timeframe_ai).replace(/\s+/g, ' ')}
                    </p>
                  )}
                  {hasProposalNumericScores(evaluateProposal) && (
                    <p className="text-slate-400 border-t border-slate-700/80 pt-1.5 mt-1">
                      <span className="text-slate-500">Evaluation scores (0–5):</span>{' '}
                      priority {evaluateProposal.evaluation_priority}, strategic {evaluateProposal.strategic_value}, energy{' '}
                      {evaluateProposal.energy_impact}
                    </p>
                  )}
                </div>
              )}
              {evaluateProposal && !evaluateProposal.error && initiativeProposalHasRenderableFields(evaluateProposal) && executionSteps.length > 0 && hasProposalNextSteps(evaluateProposal) && (
                <div className="mt-2 pt-2 border-t border-amber-800/40 space-y-1">
                  <p className="text-[10px] text-amber-100/90">
                    You already have execution checklist rows. <strong>Apply decision</strong> updates decision fields only — it does <strong>not</strong> add or replace checklist rows. To load these AI steps, confirm replace below (this removes existing rows).
                  </p>
                  <button
                    type="button"
                    disabled={execStepsBusy}
                    onClick={async () => {
                      const titles = (evaluateProposal.next_steps ?? []).map((s) => String(s ?? '').trim()).filter(Boolean)
                      if (titles.length < 3) return
                      if (!window.confirm('Delete all current execution steps and replace them with this AI list?')) return
                      setExecStepsBusy(true)
                      setExecStepsError(null)
                      try {
                        await apiPost<ExecutionStep[]>(`/initiatives/${initiativeId}/execution-steps/materialize`, {
                          titles,
                          replace: true,
                          source: 'ai',
                        })
                        setForm((f) => ({ ...f, next_step_ai: '' }))
                        setExecStepsError(null)
                        await refreshExecutionSteps()
                        const repT = lastInitiativeEvaluateTraceRef.current
                        if (repT) {
                          postVisionExecutionLearningOutcome(
                            apiPost,
                            lastInitiativeEvaluateLearningIdRef.current,
                            'applied',
                          )
                          pushAiActionTrace(withTraceOutcome(repT, 'applied'))
                          lastInitiativeEvaluateTraceRef.current = null
                          lastInitiativeEvaluateLearningIdRef.current = null
                        }
                      } catch (e) {
                        setExecStepsError(executionStepErrorMessage(e))
                      } finally {
                        setExecStepsBusy(false)
                      }
                    }}
                    className="px-2 py-1 rounded border border-amber-600 text-amber-100 hover:bg-amber-900/40 text-[11px] disabled:opacity-50"
                  >
                    Replace all execution steps with this evaluation
                  </button>
                </div>
              )}
              <div className="flex flex-wrap gap-2 mt-2 text-xs">
                <button
                  type="button"
                  disabled={!!evaluateProposal.error || !initiativeProposalHasRenderableFields(evaluateProposal)}
                  onClick={() => {
                    setAiDecision('accepted')
                    handleApplyProposal()
                  }}
                  className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50 disabled:pointer-events-none"
                >
                  Apply decision
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAiDecision('modify')
                    setAiFieldsEditable(true)
                  }}
                  className="px-2 py-1 rounded border border-slate-500 text-slate-200 hover:bg-slate-700"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAiDecision('defer')
                    const t = lastInitiativeEvaluateTraceRef.current
                    if (t) {
                      // Declined to apply this evaluation; keep existing initiative fields — same outcome label as explicit Dismiss.
                      postVisionExecutionLearningOutcome(apiPost, lastInitiativeEvaluateLearningIdRef.current, 'dismissed')
                      pushAiActionTrace(withTraceOutcome(t, 'dismissed'))
                      lastInitiativeEvaluateTraceRef.current = null
                      lastInitiativeEvaluateLearningIdRef.current = null
                    }
                    setEvaluateProposal(null)
                  }}
                  className="px-2 py-1 rounded bg-slate-700 text-slate-200 hover:bg-slate-600"
                >
                  Keep current
                </button>
                <button
                  type="button"
                  data-testid="initiative-eval-dismiss"
                  onClick={() => {
                    const t = lastInitiativeEvaluateTraceRef.current
                    if (t) {
                      postVisionExecutionLearningOutcome(apiPost, lastInitiativeEvaluateLearningIdRef.current, 'dismissed')
                      pushAiActionTrace(withTraceOutcome(t, 'dismissed'))
                      lastInitiativeEvaluateTraceRef.current = null
                      lastInitiativeEvaluateLearningIdRef.current = null
                    }
                    setEvaluateProposal(null)
                  }}
                  className="px-2 py-1 rounded bg-slate-600 text-slate-200 hover:bg-slate-500 ml-auto"
                >
                  Dismiss
                </button>
              </div>
              {aiDecision !== 'none' && (
                <p className="mt-2 text-[11px] text-slate-400">
                  Decision: {aiDecision === 'accepted' ? 'Applied to decision fields.' : aiDecision === 'modify' ? 'You can edit the AI fields, then save.' : 'Deferred – no changes applied.'}
                </p>
              )}
            </div>
          )}

          {(initiative.weightedScore != null || initiative.approvalReady != null) && (
            <div className="flex flex-wrap gap-3 mb-2 text-xs text-slate-400">
              {initiative.weightedScore != null && (
                <span>
                  Weighted score: <strong className="text-slate-300">{initiative.weightedScore}</strong>
                </span>
              )}
              {initiative.approvalReady != null && (
                <span>
                  Approval ready: <strong className="text-slate-300">{initiative.approvalReady ? 'Yes' : 'No'}</strong>
                </span>
              )}
            </div>
          )}

          {typeof form.evaluation_priority === 'number' && (
            <div className="rounded-lg border border-slate-700 bg-slate-900/40 px-3 py-2 text-sm text-slate-300">
              AI-suggested priority: <strong className="text-slate-100">{form.evaluation_priority} / 5</strong>
              <span className="ml-2 text-xs text-slate-500">Run an evaluation to refresh it — no manual scoring.</span>
            </div>
          )}

          <div className="mt-2 rounded-lg border border-slate-700 bg-slate-900/40 p-2 space-y-1">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-slate-300">Decision fields</span>
              <button
                type="button"
                onClick={() => setAiFieldsEditable((e) => !e)}
                className="text-[11px] text-slate-300 hover:text-white"
              >
                {aiFieldsEditable ? 'Lock' : 'Edit'}
              </button>
            </div>
            <VeFocusRegion
              entity_type="initiative"
              entity_id={initiativeId}
              field_key="recommendation"
              field_label="Recommendation"
              field_kind="evaluation_narrative"
              getCurrentText={() => String(form.recommendation ?? '')}
            >
              <DetailField
                label="Recommendation"
                value={(form.recommendation as string) ?? ''}
                onChange={(v) => setForm((f) => ({ ...f, recommendation: v }))}
                readOnly={!aiFieldsEditable}
              />
            </VeFocusRegion>
            <div className="rounded border border-slate-700/80 bg-slate-900/30 p-2 space-y-1">
              <p className="text-xs text-slate-400">
                Checklist-style next steps are in the <strong className="text-slate-300">Execution</strong> section (canonical rows). Legacy{' '}
                <code className="text-slate-500">next_step_ai</code> is transitional only.
              </p>
              {executionSteps.length === 0 && hasNextStepsContent(String(form.next_step_ai ?? '')) && (
                <button
                  type="button"
                  disabled={execStepsBusy}
                  onClick={async () => {
                    const parsed = parseNextStepsPayload(String(form.next_step_ai ?? ''))
                    if (parsed.steps.length === 0) return
                    setExecStepsBusy(true)
                    setExecStepsError(null)
                    try {
                      await apiPost<ExecutionStep[]>(`/initiatives/${initiativeId}/execution-steps/materialize`, {
                        titles: parsed.steps,
                        replace: false,
                        source: 'import',
                      })
                      setForm((f) => ({ ...f, next_step_ai: '' }))
                      await refreshExecutionSteps()
                    } catch (e) {
                      setExecStepsError(executionStepErrorMessage(e))
                    } finally {
                      setExecStepsBusy(false)
                    }
                  }}
                  className="px-2 py-1 rounded bg-slate-600 hover:bg-slate-500 text-slate-100 text-[11px] disabled:opacity-50"
                >
                  Import legacy next-step text into Execution checklist
                </button>
              )}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
              <DetailField
                label="Estimated cost"
                value={(form.estimated_cost_ai as string) ?? ''}
                onChange={(v) => setForm((f) => ({ ...f, estimated_cost_ai: v }))}
                placeholder="Run evaluation to fill"
                readOnly={!aiFieldsEditable}
              />
              <DetailField
                label="Estimated timeframe"
                value={(form.estimated_timeframe_ai as string) ?? ''}
                onChange={(v) => setForm((f) => ({ ...f, estimated_timeframe_ai: v }))}
                placeholder="Run evaluation to fill"
                readOnly={!aiFieldsEditable}
              />
            </div>
            <VeFocusRegion
              entity_type="initiative"
              entity_id={initiativeId}
              field_key="philosophical_alignment_ai"
              field_label="Strategic alignment (AI)"
              field_kind="evaluation_narrative"
              getCurrentText={() => String(form.philosophical_alignment_ai ?? '')}
            >
              <DetailField
                label="Strategic alignment (AI)"
                value={(form.philosophical_alignment_ai as string) ?? ''}
                onChange={(v) => setForm((f) => ({ ...f, philosophical_alignment_ai: v }))}
                textarea
                rows={2}
                readOnly={!aiFieldsEditable}
              />
            </VeFocusRegion>
          </div>
        </DetailSection>

        <DetailSection title="Execution" defaultOpen>
          <p className="text-[11px] text-slate-500 mb-2">
            Checklist rows are canonical (saved immediately). Legacy text field <code className="text-slate-600">next_step_ai</code> is not used when rows exist. See{' '}
            <code className="text-slate-600">docs/02_ACTIVE_DESIGN/EXECUTION_STEPS_DESIGN.md</code>.
          </p>
          <p className="text-[11px] text-slate-600 mb-2 border-l-2 border-amber-800/50 pl-2">
            Projects will use a separate <strong className="text-slate-400">Suggested work (AI)</strong> lane (mediation-driven), not this checklist. Planned later: convert steps to tasks, move to projects, promote to initiatives, replace/break down — see{' '}
            <code className="text-slate-600">docs/02_ACTIVE_DESIGN/MEDIATION_EXECUTION_DIRECTION.md</code>.
          </p>
          {execStepsError && (
            <div
              className="mb-2 p-2 rounded border border-red-800/80 bg-red-950/40 text-red-100 text-xs flex flex-wrap items-start justify-between gap-2"
              role="alert"
            >
              <span className="min-w-0 flex-1">{execStepsError}</span>
              <button
                type="button"
                className="shrink-0 text-red-300 hover:text-white underline text-[11px]"
                onClick={() => setExecStepsError(null)}
              >
                Dismiss
              </button>
            </div>
          )}
          <div className="space-y-2">
            {executionSteps.map((step) => {
              const isCurrent = currentExecutionStepId === step.id
              const isEditing = execStepEditingId === step.id
              const doneVisual = step.is_done
              return (
                <div
                  key={step.id}
                  className={`flex flex-wrap items-start gap-2 p-2 rounded border bg-slate-900/30 ${
                    isCurrent && !doneVisual
                      ? 'border-amber-600/50 ring-1 ring-amber-500/25 bg-amber-950/15'
                      : 'border-slate-700'
                  } ${doneVisual ? 'opacity-65' : ''}`}
                >
                  <div className="flex-1 min-w-[12rem] min-h-[1.75rem]">
                    {isEditing ? (
                      <input
                        autoFocus
                        className="w-full px-2 py-1 rounded bg-slate-900 border border-amber-600/60 text-slate-100 text-xs"
                        value={execStepEditDraft}
                        onChange={(e) => setExecStepEditDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') {
                            e.preventDefault()
                            setExecStepEditingId(null)
                            setExecStepEditDraft('')
                          }
                        }}
                        onBlur={() => {
                          const sid = step.id
                          const originalTitle = step.title
                          window.setTimeout(async () => {
                            if (execStepEditingIdRef.current !== sid) return
                            const v = execStepEditDraftRef.current.trim()
                            setExecStepEditingId(null)
                            setExecStepEditDraft('')
                            if (!v) return
                            if (v === originalTitle) return
                            setExecStepsBusy(true)
                            setExecStepsError(null)
                            try {
                              await apiPatch<ExecutionStep>(`/execution-steps/${step.id}`, { title: v })
                              await refreshExecutionSteps()
                            } catch (err) {
                              setExecStepsError(executionStepErrorMessage(err))
                            } finally {
                              setExecStepsBusy(false)
                            }
                          }, 0)
                        }}
                        disabled={execStepsBusy}
                        aria-label={`Edit title: ${veEntityDisplayStr(step.title)}`}
                      />
                    ) : (
                      <p
                        className={`text-xs text-slate-100 px-1 py-0.5 rounded ${doneVisual ? 'line-through text-slate-500' : ''}`}
                      >
                        {veEntityDisplayStr(step.title)}
                      </p>
                    )}
                  </div>
                  <span className="text-[10px] text-slate-600 shrink-0 pt-1" title="Source">
                    {veEntityDisplayStr(step.source)}
                  </span>
                  <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                    <button
                      type="button"
                      disabled={execStepsBusy}
                      onClick={async () => {
                        setExecStepOverflowId(null)
                        setExecStepsBusy(true)
                        setExecStepsError(null)
                        try {
                          await apiPatch<ExecutionStep>(`/execution-steps/${step.id}`, { is_done: !step.is_done })
                          await refreshExecutionSteps()
                        } catch (err) {
                          setExecStepsError(executionStepErrorMessage(err))
                        } finally {
                          setExecStepsBusy(false)
                        }
                      }}
                      className={`px-2 py-1 rounded text-[11px] font-medium ${
                        step.is_done
                          ? 'border border-slate-600 text-slate-300 hover:bg-slate-800'
                          : 'bg-emerald-700/90 text-white hover:bg-emerald-600'
                      } disabled:opacity-50`}
                    >
                      {step.is_done ? 'Reopen' : 'Done'}
                    </button>
                    <button
                      type="button"
                      disabled={execStepsBusy}
                      onClick={() => {
                        setExecStepOverflowId(null)
                        if (isEditing) {
                          setExecStepEditingId(null)
                          setExecStepEditDraft('')
                        } else {
                          setExecStepEditingId(step.id)
                          setExecStepEditDraft(step.title)
                        }
                      }}
                      className="px-2 py-1 rounded border border-slate-600 text-slate-300 text-[11px] hover:bg-slate-800 disabled:opacity-50"
                    >
                      {isEditing ? 'Cancel' : 'Edit'}
                    </button>
                    <div className="relative shrink-0" data-exec-step-overflow-root>
                      <button
                        type="button"
                        disabled={execStepsBusy}
                        aria-expanded={execStepOverflowId === step.id}
                        aria-haspopup="menu"
                        aria-label="More step actions"
                        className="px-2 py-1 rounded border border-slate-600 text-slate-400 text-sm leading-none hover:bg-slate-800 disabled:opacity-50"
                        onClick={(e) => {
                          e.stopPropagation()
                          setExecStepOverflowId((id) => (id === step.id ? null : step.id))
                        }}
                      >
                        ⋯
                      </button>
                      {execStepOverflowId === step.id && (
                        <div
                          className="absolute right-0 top-full z-30 mt-1 min-w-[12.5rem] rounded border border-slate-600 bg-slate-900 py-1 shadow-xl text-[11px]"
                          role="menu"
                        >
                          <button
                            type="button"
                            role="menuitem"
                            className="w-full text-left px-3 py-1.5 text-slate-200 hover:bg-slate-800"
                            onClick={async () => {
                              setExecStepOverflowId(null)
                              if (!window.confirm('Remove this execution step?')) return
                              setExecStepsBusy(true)
                              setExecStepsError(null)
                              try {
                                await apiDelete(`/execution-steps/${step.id}`)
                                await refreshExecutionSteps()
                              } catch (err) {
                                setExecStepsError(executionStepErrorMessage(err))
                              } finally {
                                setExecStepsBusy(false)
                              }
                            }}
                          >
                            Remove
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="w-full text-left px-3 py-1.5 text-slate-200 hover:bg-slate-800"
                            onClick={async () => {
                              setExecStepOverflowId(null)
                              setExecStepsBusy(true)
                              setExecStepsError(null)
                              try {
                                await apiPost<ExecutionStep>(`/initiatives/${initiativeId}/execution-steps`, {
                                  title: step.title,
                                })
                                await refreshExecutionSteps()
                              } catch (err) {
                                setExecStepsError(executionStepErrorMessage(err))
                              } finally {
                                setExecStepsBusy(false)
                              }
                            }}
                          >
                            Duplicate
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
            {executionSteps.length === 0 && (
              <p className="text-xs text-slate-500">No steps yet. Use + Add step, apply an evaluation (when none exist), or import legacy text from Decision fields.</p>
            )}
          </div>
          <div className="mt-3 space-y-2">
            {!execAddStepOpen ? (
              <button
                type="button"
                disabled={execStepsBusy}
                onClick={() => {
                  setExecAddStepOpen(true)
                  setAddStepSuggestHint(null)
                }}
                className="px-2 py-1.5 rounded border border-dashed border-slate-600 text-slate-300 text-xs hover:border-slate-500 hover:bg-slate-800/50 disabled:opacity-50"
              >
                + Add step
              </button>
            ) : (
              <div className="flex flex-col gap-2 p-2 rounded-lg border border-slate-600 bg-slate-900/40">
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    value={newExecStepTitle}
                    onChange={(e) => setNewExecStepTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.preventDefault()
                    }}
                    placeholder="Step title"
                    autoFocus
                    className="flex-1 min-w-[10rem] px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs"
                  />
                  <button
                    type="button"
                    disabled={execStepsBusy}
                    onClick={() => {
                      const raw = (evaluateProposal?.next_steps ?? []).map((s) => String(s ?? '').trim()).filter(Boolean)
                      const existing = new Set(executionSteps.map((s) => s.title.trim().toLowerCase()))
                      const pick = raw.find((t) => !existing.has(t.toLowerCase()))
                      if (pick) {
                        setNewExecStepTitle(pick)
                        setAddStepSuggestHint(null)
                      } else if (raw.length > 0) {
                        setAddStepSuggestHint('All evaluation steps already appear in your list.')
                      } else {
                        setAddStepSuggestHint('Run evaluation first to get suggested steps.')
                      }
                    }}
                    className="px-2 py-1.5 rounded border border-amber-700/60 text-amber-200 text-[11px] hover:bg-amber-950/40 disabled:opacity-50"
                  >
                    Suggest
                  </button>
                  <button
                    type="button"
                    disabled={execStepsBusy || !newExecStepTitle.trim()}
                    onClick={async () => {
                      const t = newExecStepTitle.trim()
                      if (!t) return
                      setExecStepsBusy(true)
                      setExecStepsError(null)
                      try {
                        await apiPost<ExecutionStep>(`/initiatives/${initiativeId}/execution-steps`, { title: t })
                        setNewExecStepTitle('')
                        setExecAddStepOpen(false)
                        setAddStepSuggestHint(null)
                        await refreshExecutionSteps()
                        setForm((f) => ({ ...f, next_step_ai: '' }))
                      } catch (err) {
                        setExecStepsError(executionStepErrorMessage(err))
                      } finally {
                        setExecStepsBusy(false)
                      }
                    }}
                    className="px-2 py-1.5 rounded bg-emerald-700/90 hover:bg-emerald-600 text-white text-xs disabled:opacity-50"
                  >
                    Add
                  </button>
                  <button
                    type="button"
                    disabled={execStepsBusy}
                    onClick={() => {
                      setExecAddStepOpen(false)
                      setNewExecStepTitle('')
                      setAddStepSuggestHint(null)
                    }}
                    className="px-2 py-1.5 rounded border border-slate-600 text-slate-400 text-xs hover:bg-slate-800"
                  >
                    Cancel
                  </button>
                </div>
                {addStepSuggestHint && <p className="text-[11px] text-amber-200/90">{addStepSuggestHint}</p>}
              </div>
            )}
          </div>
        </DetailSection>

        <DetailSection title="Resourcing reality" defaultOpen={false}>
          <div className="mb-2 rounded-lg border border-slate-700 bg-slate-900/30 p-2">
            <div className="flex flex-wrap gap-3 text-xs text-slate-300">
              <span>Total seats: <strong className="text-slate-100">{seatRowCount}</strong></span>
              <span>
                Filled vs unfilled:{' '}
                {seatTotal > 0 ? (
                  <>
                    <strong className="text-slate-100">{seatFilled}</strong>/<span className="text-slate-500">{seatTotal}</span>
                    <span className="text-slate-500"> ({seatUnfilled} unfilled)</span>
                  </>
                ) : seatRowCount > 0 ? (
                  <span className="text-slate-500">— (empty row — add role, assignee, effort, or notes)</span>
                ) : (
                  <span className="text-slate-500">—</span>
                )}
              </span>
              {effortTotalHeuristic != null && (
                <span>
                  Total estimated effort (heuristic): <strong className="text-slate-100">{effortTotalHeuristic}</strong>
                </span>
              )}
            </div>
          </div>

          {gapLines.length > 0 && (
            <div className="mb-2 p-2 rounded-lg border border-amber-700/70 bg-amber-900/30 text-xs text-amber-100">
              <div className="font-medium mb-1">What's missing</div>
              {gapLines.map((line, i) => (
                <p key={i} className="leading-relaxed">{line}</p>
              ))}
            </div>
          )}

          <EntityMultiSelect
            label="Required assets"
            selectedIds={reqAssets}
            onChange={(ids) => setForm((f) => ({ ...f, required_assets: ids }))}
            options={assets as any}
            getLabel={(a) => (a as Asset).name}
          />

          <div className="mt-3 space-y-2">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-2">
              <div>
                <span className="text-xs font-medium text-slate-300">Required seats / roles</span>
                <p className="text-[11px] text-slate-500 mt-0.5 max-w-xl leading-snug">
                  <strong className="text-slate-400">Effort</strong> is a rough estimate for this seat on this initiative (any units you use—hours, days, story points; the first number is summed in the header).
                  <span className="text-slate-600"> · </span>
                  <strong className="text-slate-400">Seat notes</strong> are optional context for this role only (skills, constraints, pairing). Use <strong className="text-slate-400">Dependencies</strong> below for cross-cutting blockers or handoffs.
                </p>
              </div>
              <button type="button" onClick={addSeat} className="shrink-0 px-2 py-1 rounded bg-slate-700 text-slate-200 hover:bg-slate-600 text-[11px] self-start">
                Add seat
              </button>
            </div>
            {seats.length === 0 ? (
              <div className="text-xs text-slate-500">No seats set yet.</div>
            ) : (
              <div className="space-y-3">
                {seats.map((seat, idx) => (
                  <div key={idx} className="space-y-1.5 rounded-md border border-slate-700/60 bg-slate-900/40 p-2">
                    <div className="grid grid-cols-12 gap-2 items-start">
                      <div className="col-span-12 sm:col-span-4">
                        <label className="sr-only" htmlFor={`seat-role-${idx}`}>Role / seat</label>
                        <input
                          id={`seat-role-${idx}`}
                          className={seatInputBase}
                          value={seat.role}
                          onChange={(e) => updateSeat(idx, { role: e.target.value })}
                          placeholder="Role / seat"
                        />
                      </div>
                      <div className="col-span-12 sm:col-span-4">
                        <label className="sr-only" htmlFor={`seat-person-${idx}`}>Assignee</label>
                        <select
                          id={`seat-person-${idx}`}
                          className={seatInputBase}
                          value={seat.personId ?? ''}
                          onChange={(e) => updateSeat(idx, { personId: e.target.value || null })}
                        >
                          <option value="">Unassigned</option>
                          {persons.map((p) => (
                            <option key={p.id} value={p.id}>{p.name || p.id}</option>
                          ))}
                        </select>
                      </div>
                      <div className="col-span-12 sm:col-span-3">
                        <label className="sr-only" htmlFor={`seat-effort-${idx}`}>Estimated effort</label>
                        <input
                          id={`seat-effort-${idx}`}
                          className={seatInputBase}
                          value={seat.effort}
                          onChange={(e) => updateSeat(idx, { effort: e.target.value })}
                          placeholder="e.g. 40h, 2d, 5 SP"
                          title="Rough estimate for this seat; first number is used for the total-effort hint above"
                        />
                      </div>
                      <div className="col-span-12 sm:col-span-1 flex sm:justify-end">
                        <button type="button" onClick={() => removeSeat(idx)} className="w-full sm:w-auto px-2 py-1 rounded border border-red-600 text-red-200 hover:bg-red-900/30 text-[11px]">
                          Remove
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="sr-only" htmlFor={`seat-notes-${idx}`}>Notes for this seat</label>
                      <textarea
                        id={`seat-notes-${idx}`}
                        rows={2}
                        className={`${seatInputBase} w-full resize-y min-h-[2.5rem]`}
                        value={seat.notes}
                        onChange={(e) => updateSeat(idx, { notes: e.target.value })}
                        placeholder="Optional: scope for this seat only—skills, constraints, who to pair with…"
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <VeFocusRegion
            entity_type="initiative"
            entity_id={initiativeId}
            field_key="dependencies"
            field_label="Dependencies"
            field_kind="dependencies_scope"
            getCurrentText={() => String(form.dependencies ?? '')}
          >
            <DetailField
              label="Dependencies"
              value={(form.dependencies as string) ?? ''}
              onChange={(v) => setForm((f) => ({ ...f, dependencies: v }))}
              textarea
              rows={2}
            />
          </VeFocusRegion>
        </DetailSection>

        <DetailSection title="Risks / admin" defaultOpen={false}>
          <DetailField label="Risks" value={(form.risks as string) ?? ''} onChange={(v) => setForm((f) => ({ ...f, risks: v }))} textarea rows={2} />
          <DetailField label="Kill criteria" value={(form.kill_criteria as string) ?? ''} onChange={(v) => setForm((f) => ({ ...f, kill_criteria: v }))} textarea rows={2} />
          <DetailField
            label="Diagnostics / admin notes"
            value={(form.notes as string) ?? ''}
            onChange={(v) => setForm((f) => ({ ...f, notes: v }))}
            textarea
            rows={3}
          />
        </DetailSection>
        <DeferredPromptTodosSection
          entityType="initiative"
          entityId={initiativeId}
          contextTitle={formatVeEntityPromptTitle(
            'initiative',
            (form.title as string) || initiative?.title,
          )}
        />
        <MetadataSection data={{ id: initiative.id, created_at: initiative.created_at, updated_at: initiative.updated_at }} />
      </div>
      <div className="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-slate-600">
        <button type="button" onClick={handleSave} disabled={saving} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-medium">Save</button>
        <button type="button" onClick={handleInitiativePanelClose} className="px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800 text-sm">Cancel</button>
        <div className="relative ml-auto sm:ml-0" data-initiative-footer-overflow-root>
          <button
            type="button"
            aria-expanded={initiativeFooterMenuOpen}
            aria-haspopup="menu"
            aria-label="More initiative actions"
            className="px-2.5 py-1.5 rounded-lg border border-slate-600 text-slate-400 text-sm hover:bg-slate-800"
            onClick={() => setInitiativeFooterMenuOpen((o) => !o)}
          >
            ⋯
          </button>
          {initiativeFooterMenuOpen && (
            <div
              className="absolute bottom-full right-0 sm:right-auto sm:left-0 mb-1 z-30 min-w-[10rem] rounded border border-slate-600 bg-slate-900 py-1 shadow-xl text-sm"
              role="menu"
            >
              <button
                type="button"
                role="menuitem"
                className="w-full text-left px-3 py-2 text-amber-200 hover:bg-slate-800 disabled:opacity-50"
                disabled={saving}
                onClick={() => {
                  setInitiativeFooterMenuOpen(false)
                  setConfirmAction('kill')
                }}
              >
                Mark killed…
              </button>
              <button
                type="button"
                role="menuitem"
                className="w-full text-left px-3 py-2 text-red-300 hover:bg-slate-800 disabled:opacity-50"
                disabled={saving}
                onClick={() => {
                  setInitiativeFooterMenuOpen(false)
                  setConfirmAction('delete')
                }}
              >
                Delete…
              </button>
            </div>
          )}
        </div>
      </div>
      {confirmAction === 'kill' && <ConfirmModal title="Mark initiative as killed" message="Set status to Killed. Projects under this initiative will be unlinked." confirmLabel="Kill" variant="warning" onConfirm={onConfirmKill} onCancel={() => setConfirmAction(null)} />}
      {confirmAction === 'delete' && <ConfirmModal title="Delete initiative" message="This cannot be undone. Projects will be unlinked from this initiative." confirmLabel="Delete" onConfirm={onConfirmDelete} onCancel={() => setConfirmAction(null)} />}
    </div>
  )
}

/** Idea workflow stage (UI). Stored via existing backend status. */
type IdeaStage = 'capture' | 'clarify' | 'evaluate' | 'decide'

function statusToStage(status: string): IdeaStage {
  const s = (status ?? '').toLowerCase()
  if (s === 'captured') return 'capture'
  if (s === 'clarifying' || s === 'contextualized') return 'clarify'
  if (s === 'evaluated') return 'evaluate'
  return 'decide'
}

function stageToStatus(stage: IdeaStage): string {
  switch (stage) {
    case 'capture': return 'Captured'
    case 'clarify': return 'Clarifying'
    case 'evaluate': return 'Evaluated'
    case 'decide': return 'Evaluated'
    default: return 'Captured'
  }
}

/** Backend response from POST /ideas/:id/evaluate (MVP contract: docs/04_REFERENCE/IDEA_EVALUATION_SPEC.md). */
interface IdeaEvaluateResponse {
  estimated_cost_range?: string
  time_to_build?: string
  time_to_roi?: string
  roi_potential?: 'conservative' | 'expected' | 'speculative'
  required_roles?: string
  likely_dependencies?: string
  major_risks?: string
  strategic_alignment?: string
  suggested_next_step?: string
  recommendation?: string
  error?: string
  execution_blocked?: boolean
  privacy_block_reason?: string | null
  model_used?: string | null
  provider_used?: string | null
  learning_record_id?: string
}

/** In-memory decision analysis (MVP contract; not persisted to Idea yet). */
type IdeaDecisionAnalysis = {
  estimated_cost_range: string
  time_to_build: string
  time_to_roi: string
  roi_potential: 'conservative' | 'expected' | 'speculative'
  required_roles: string
  likely_dependencies: string
  major_risks: string
  strategic_alignment: string
  suggested_next_step: string
  recommendation: string
}

const EMPTY_ANALYSIS: IdeaDecisionAnalysis = {
  estimated_cost_range: '',
  time_to_build: '',
  time_to_roi: '',
  roi_potential: 'expected',
  required_roles: '',
  likely_dependencies: '',
  major_risks: '',
  strategic_alignment: '',
  suggested_next_step: '',
  recommendation: '',
}

function IdeaDetailPanel({
  ideaId,
  ideas,
  persons,
  assets,
  initiatives,
  projects,
  tasks,
  councilIdeaLabelsRef,
  onCouncilIdeaLiveLabelsUpdated,
  onClose,
  onSaved,
  apiGet,
  apiPatch,
  apiPost,
  apiDelete,
}: {
  ideaId: string
  ideas: Idea[]
  persons: Person[]
  assets: Asset[]
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  councilIdeaLabelsRef?: MutableRefObject<CouncilIdeaLabelsSnapshot | null>
  onCouncilIdeaLiveLabelsUpdated?: () => void
  onClose: () => void
  onSaved: () => void
  apiGet: <T>(path: string) => Promise<T>
  apiPatch: <T>(path: string, body: unknown) => Promise<T>
  apiPost: <T>(path: string, body: unknown) => Promise<T>
  apiDelete: (path: string) => Promise<void>
}) {
  const [idea, setIdea] = useState<Idea | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [stage, setStage] = useState<IdeaStage>('capture')
  const [clarifyLoading, setClarifyLoading] = useState(false)
  const [evaluateLoading, setEvaluateLoading] = useState(false)
  const [evaluateError, setEvaluateError] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<IdeaDecisionAnalysis>(EMPTY_ANALYSIS)
  const [hasEvaluationResults, setHasEvaluationResults] = useState(false)
  const [analysisEditable, setAnalysisEditable] = useState(false)
  const [confirmAction, setConfirmAction] = useState<'shelve' | 'reject' | null>(null)
  const [promotionTarget, setPromotionTarget] = useState<'initiative' | 'project' | 'task'>('initiative')
  const [promotionInitiativeId, setPromotionInitiativeId] = useState<string>('')
  const [promotionProjectId, setPromotionProjectId] = useState<string>('')
  const [promotionParentTaskId, setPromotionParentTaskId] = useState<string>('')
  const lastIdeaEvaluateTraceRef = useRef<AiActionTrace | null>(null)
  const lastIdeaEvaluateLearningIdRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    apiGet<Idea>(`/ideas/${ideaId}`).then((data) => {
      if (!cancelled) {
        setIdea(data)
        setForm({
          title: data.title,
          summary: data.summary ?? '',
          description: data.description ?? '',
          status: data.status ?? 'Captured',
          desired_outcome: data.desired_outcome ?? '',
        })
        setStage(statusToStage(data.status ?? 'Captured'))
      }
    }).catch(() => { if (!cancelled) setIdea(null) }).finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [ideaId, apiGet])

  useEffect(() => {
    if (!councilIdeaLabelsRef) return
    if (!ideaId) return
    if (!idea || idea.id !== ideaId) {
      if (councilIdeaLabelsRef.current?.entity_id !== ideaId) {
        councilIdeaLabelsRef.current = null
      }
      return
    }
    councilIdeaLabelsRef.current = {
      entity_type: 'idea',
      entity_id: ideaId,
      ve_focus_title: String(form.title ?? idea.title ?? ''),
      ve_focus_brief: String(form.summary ?? idea.summary ?? '').trim(),
      ve_focus_description: String(form.description ?? idea.description ?? '').trim(),
      ve_focus_status: String(form.status ?? idea.status ?? '').trim() || undefined,
    }
    onCouncilIdeaLiveLabelsUpdated?.()
  }, [
    councilIdeaLabelsRef,
    ideaId,
    idea,
    form.title,
    form.summary,
    form.description,
    form.status,
    onCouncilIdeaLiveLabelsUpdated,
  ])

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<VeFocusApplyRewriteDetail>).detail
      if (!d || d.entity_type !== 'idea' || d.entity_id !== ideaId || !d.text) return
      if (d.field_key === 'description') setForm((p) => ({ ...p, description: d.text }))
      if (d.field_key === 'title') setForm((p) => ({ ...p, title: d.text }))
      if (d.field_key === 'summary') setForm((p) => ({ ...p, summary: d.text }))
    }
    window.addEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, handler)
    return () => window.removeEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, handler)
  }, [ideaId])

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d || d.entity_type !== 'idea' || d.entity_id !== ideaId || !d.text) return
      const map: Record<string, 'title' | 'summary' | 'description'> = {
        title: 'title',
        summary: 'summary',
        description: 'description',
      }
      const formKey = map[d.field_key]
      if (!formKey) return
      setForm((p) => {
        const prev = String((p as Record<string, unknown>)[formKey] ?? '')
        const next = insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd)
        return { ...p, [formKey]: next }
      })
    }
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, handler)
    return () => window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, handler)
  }, [ideaId])

  const handleSave = async (nextStatus?: string) => {
    setSaveError(null); setSaving(true)
    try {
      const status = nextStatus ?? (form.status as string) ?? 'Captured'
      await apiPatch<Idea>(`/ideas/${ideaId}`, {
        title: form.title,
        summary: form.summary ?? '',
        description: form.description ?? '',
        status,
        desired_outcome: form.desired_outcome ?? '',
      })
      if (nextStatus === 'Evaluated') {
        const t = lastIdeaEvaluateTraceRef.current
        if (t && hasEvaluationResults) {
          postVisionExecutionLearningOutcome(apiPost, lastIdeaEvaluateLearningIdRef.current, 'applied')
          pushAiActionTrace(withTraceOutcome(t, 'applied'))
          lastIdeaEvaluateTraceRef.current = null
          lastIdeaEvaluateLearningIdRef.current = null
        }
      }
      setForm((p) => ({ ...p, status }))
      setStage(statusToStage(status))
      onSaved()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Save failed') } finally { setSaving(false) }
  }

  /** Local template suggestions only — no LLM or API call (product honesty). */
  const handleClarifyLocalTemplates = async () => {
    setClarifyLoading(true)
    try {
      await new Promise((r) => setTimeout(r, 600))
      setForm((p) => ({
        ...p,
        description: (p.description as string) || `Expanded from: "${(p.title as string) || 'this idea'}". Consider goals, scope, and success criteria.`,
        desired_outcome: (p.desired_outcome as string) || 'Clarify what success looks like and how you will measure it.',
      }))
    } finally { setClarifyLoading(false) }
  }

  const handleRunEvaluation = async () => {
    console.log('[idea-eval] handler entered (run evaluation)', { ideaId })
    const payload = {
      routing_context: visionExecutionEvaluateRouting(VE_EVALUATE_ACTION_INTENTS.idea_evaluate),
    }
    console.log('[idea-eval] Run evaluation clicked', { ideaId, payload })
    setEvaluateError(null)
    setEvaluateLoading(true)
    if (lastIdeaEvaluateTraceRef.current && hasEvaluationResults) {
      postVisionExecutionLearningOutcome(apiPost, lastIdeaEvaluateLearningIdRef.current, 'edited')
      pushAiActionTrace(withTraceOutcome(lastIdeaEvaluateTraceRef.current, 'edited'))
      lastIdeaEvaluateTraceRef.current = null
      lastIdeaEvaluateLearningIdRef.current = null
    }
    try {
      const res = await apiPost<IdeaEvaluateResponse>(`/ideas/${ideaId}/evaluate`, payload)
      const raw = typeof res === 'object' && res !== null ? JSON.stringify(res).slice(0, 500) : String(res)
      console.log('[idea-eval] Run evaluation raw API response', { hasError: !!(res && typeof res === 'object' && 'error' in res && res.error), responseSample: raw })
      if (typeof res !== 'object' || res === null || res.error) {
        console.log('[idea-eval] Run evaluation -> error path', { error: res && typeof res === 'object' ? res.error : 'non-object or null' })
        const msg = res && typeof res === 'object' && typeof res.error === 'string' ? res.error : ''
        setEvaluateError(
          res && typeof res === 'object' && res.execution_blocked
            ? msg || 'Execution blocked by policy or privacy settings.'
            : msg.toLowerCase().includes('provider')
              ? msg
              : 'Evaluation failed — the AI could not generate a valid structured response.',
        )
        return
      }
      console.log('[idea-eval] Run evaluation -> success path')
      const roi = res.roi_potential && ['conservative', 'expected', 'speculative'].includes(res.roi_potential)
        ? res.roi_potential
        : 'expected'
      setAnalysis({
        estimated_cost_range: res.estimated_cost_range ?? '',
        time_to_build: res.time_to_build ?? '',
        time_to_roi: res.time_to_roi ?? '',
        roi_potential: roi,
        required_roles: res.required_roles ?? '',
        likely_dependencies: res.likely_dependencies ?? '',
        major_risks: res.major_risks ?? '',
        strategic_alignment: res.strategic_alignment ?? '',
        suggested_next_step: res.suggested_next_step ?? '',
        recommendation: res.recommendation ?? '',
      })
      setHasEvaluationResults(true)
      const lid =
        typeof res.learning_record_id === 'string' && res.learning_record_id.trim()
          ? res.learning_record_id.trim()
          : null
      lastIdeaEvaluateLearningIdRef.current = lid
      const tr = createAiActionTrace({
        surface: 'vision_execution',
        action_kind: 'structured_evaluation',
        action_intent: 'idea_evaluate',
        subject_type: 'idea',
        subject_id: ideaId,
        field_key: null,
        input_snapshot: 'POST /ideas/{id}/evaluate',
        prompt_version: 've_idea_evaluate_v1',
        model_used: res.model_used ?? null,
        provider_used: res.provider_used ?? null,
        output: JSON.stringify({
          has_recommendation: Boolean(res.recommendation && String(res.recommendation).trim()),
        }),
        user_outcome: 'none',
      })
      lastIdeaEvaluateTraceRef.current = tr
      pushAiActionTrace(tr)
    } catch (e) {
      console.log('[idea-eval] Run evaluation -> catch (request failed)', e)
      setEvaluateError('Evaluation failed — the AI could not generate a valid structured response.')
    } finally {
      setEvaluateLoading(false)
    }
  }

  const handleRunQuickEvaluation = async () => {
    console.log('[idea-eval] handler entered (quick evaluation)', { ideaId })
    const payload = {
      relaxed: true,
      routing_context: visionExecutionEvaluateRouting(VE_EVALUATE_ACTION_INTENTS.idea_evaluate),
    }
    console.log('[idea-eval] Quick evaluation clicked', { ideaId, payload })
    setEvaluateError(null)
    setEvaluateLoading(true)
    if (lastIdeaEvaluateTraceRef.current && hasEvaluationResults) {
      postVisionExecutionLearningOutcome(apiPost, lastIdeaEvaluateLearningIdRef.current, 'edited')
      pushAiActionTrace(withTraceOutcome(lastIdeaEvaluateTraceRef.current, 'edited'))
      lastIdeaEvaluateTraceRef.current = null
      lastIdeaEvaluateLearningIdRef.current = null
    }
    try {
      const res = await apiPost<IdeaEvaluateResponse>(`/ideas/${ideaId}/evaluate`, payload)
      const raw = typeof res === 'object' && res !== null ? JSON.stringify(res).slice(0, 500) : String(res)
      console.log('[idea-eval] Quick evaluation raw API response', { hasError: !!(res && typeof res === 'object' && 'error' in res && res.error), responseSample: raw })
      if (typeof res !== 'object' || res === null || res.error) {
        console.log('[idea-eval] Quick evaluation -> error path', { error: res && typeof res === 'object' ? res.error : 'non-object or null' })
        const msg = res && typeof res === 'object' && typeof res.error === 'string' ? res.error : ''
        setEvaluateError(
          res && typeof res === 'object' && res.execution_blocked
            ? msg || 'Execution blocked by policy or privacy settings.'
            : msg.toLowerCase().includes('provider')
              ? msg
              : 'Evaluation failed — the AI could not generate a valid structured response.',
        )
        return
      }
      console.log('[idea-eval] Quick evaluation -> success path')
      const roi = res.roi_potential && ['conservative', 'expected', 'speculative'].includes(res.roi_potential)
        ? res.roi_potential
        : 'expected'
      setAnalysis({
        estimated_cost_range: res.estimated_cost_range ?? '',
        time_to_build: res.time_to_build ?? '',
        time_to_roi: res.time_to_roi ?? '',
        roi_potential: roi,
        required_roles: res.required_roles ?? '',
        likely_dependencies: res.likely_dependencies ?? '',
        major_risks: res.major_risks ?? '',
        strategic_alignment: res.strategic_alignment ?? '',
        suggested_next_step: res.suggested_next_step ?? '',
        recommendation: res.recommendation ?? '',
      })
      setHasEvaluationResults(true)
      const lidQ =
        typeof res.learning_record_id === 'string' && res.learning_record_id.trim()
          ? res.learning_record_id.trim()
          : null
      lastIdeaEvaluateLearningIdRef.current = lidQ
      const trQuick = createAiActionTrace({
        surface: 'vision_execution',
        action_kind: 'structured_evaluation',
        action_intent: 'idea_evaluate',
        subject_type: 'idea',
        subject_id: ideaId,
        field_key: null,
        input_snapshot: 'POST /ideas/{id}/evaluate?relaxed',
        prompt_version: 've_idea_evaluate_v1',
        model_used: res.model_used ?? null,
        provider_used: res.provider_used ?? null,
        output: JSON.stringify({
          has_recommendation: Boolean(res.recommendation && String(res.recommendation).trim()),
        }),
        user_outcome: 'none',
      })
      lastIdeaEvaluateTraceRef.current = trQuick
      pushAiActionTrace(trQuick)
    } catch (e) {
      console.log('[idea-eval] Quick evaluation -> catch (request failed)', e)
      setEvaluateError('Evaluation failed — the AI could not generate a valid structured response.')
    } finally {
      setEvaluateLoading(false)
    }
  }

  const recordIdeaEvalAppliedIfPending = () => {
    const t = lastIdeaEvaluateTraceRef.current
    if (t && hasEvaluationResults) {
      postVisionExecutionLearningOutcome(apiPost, lastIdeaEvaluateLearningIdRef.current, 'applied')
      pushAiActionTrace(withTraceOutcome(t, 'applied'))
      lastIdeaEvaluateTraceRef.current = null
      lastIdeaEvaluateLearningIdRef.current = null
    }
  }

  /** Close without Apply: edited if user opened override editing; else dismissed. TODO: close vs explicit dismiss. */
  const recordIdeaEvalDismissedIfPending = () => {
    const t = lastIdeaEvaluateTraceRef.current
    if (t && hasEvaluationResults) {
      const outcome = analysisEditable ? 'edited' : 'dismissed'
      postVisionExecutionLearningOutcome(apiPost, lastIdeaEvaluateLearningIdRef.current, outcome)
      pushAiActionTrace(withTraceOutcome(t, outcome))
      lastIdeaEvaluateTraceRef.current = null
      lastIdeaEvaluateLearningIdRef.current = null
    }
  }

  const handleIdeaPanelClose = () => {
    recordIdeaEvalDismissedIfPending()
    onClose()
  }

  const handlePromote = async () => {
    setSaveError(null); setSaving(true)
    try {
      const baseTitle = (form.title as string) || 'Untitled'
      const baseBrief = (form.summary as string) || (form.description as string) || ''

      if (promotionTarget === 'initiative') {
        const inheritedFromIdeaEvaluation: Partial<Initiative> = {}
        if (hasEvaluationResults) {
          const cost = analysis.estimated_cost_range?.trim()
          if (cost) inheritedFromIdeaEvaluation.estimated_cost_ai = cost

          const timeframe = (analysis.time_to_build || analysis.time_to_roi)?.trim()
          if (timeframe) inheritedFromIdeaEvaluation.estimated_timeframe_ai = timeframe

          const alignment = analysis.strategic_alignment?.trim()
          if (alignment) inheritedFromIdeaEvaluation.philosophical_alignment_ai = alignment

          const nextStep = analysis.suggested_next_step?.trim()
          if (nextStep) {
            inheritedFromIdeaEvaluation.next_step_ai = serializeNextStepsPayload({
              ...emptyNextStepsPayload(),
              steps: [nextStep],
            })
          }

          const recommendation = analysis.recommendation?.trim()
          if (recommendation) inheritedFromIdeaEvaluation.recommendation = recommendation

          const requiredRoles = analysis.required_roles?.trim()
          if (requiredRoles) {
            const parsedSeats = parseIdeaRequiredRolesToSeats(requiredRoles)
            if (parsedSeats.length > 0) {
              inheritedFromIdeaEvaluation.seats = parsedSeats.map((s) => ({
                role: s.role,
                assigned_person_id: s.personId || null,
                estimated_effort: s.effort.trim() ? s.effort.trim() : null,
                notes: s.notes || '',
              })) as any
            }
          }
        }

        if (promotionInitiativeId) {
          // Attach to existing initiative as the home for this idea.
          await apiPatch<Initiative>(`/initiatives/${promotionInitiativeId}`, {
            source_idea_id: ideaId,
            ...inheritedFromIdeaEvaluation,
          })
          await apiPatch<Idea>(`/ideas/${ideaId}`, { status: 'Advanced' })
          recordIdeaEvalAppliedIfPending()
          onSaved(); onClose()
          return
        } else {
          const created = await apiPost<Initiative>('/initiatives', {
            source_idea_id: ideaId,
            title: baseTitle,
            brief: baseBrief,
            status: 'Draft',
            ...inheritedFromIdeaEvaluation,
          })
          void created
          await apiPatch<Idea>(`/ideas/${ideaId}`, { status: 'Advanced' })
          recordIdeaEvalAppliedIfPending()
          onSaved(); onClose()
          return
        }
      }

      if (promotionTarget === 'project') {
        const initiativeId = promotionInitiativeId || null
        await apiPost<Project>('/projects', {
          initiative_id: initiativeId,
          title: baseTitle,
          brief: baseBrief,
          status: 'Draft',
        })
        await apiPatch<Idea>(`/ideas/${ideaId}`, { status: 'Advanced' })
        recordIdeaEvalAppliedIfPending()
        onSaved(); onClose()
        return
      }

      if (promotionTarget === 'task') {
        if (!promotionProjectId) {
          throw new Error('Choose a project to hold the new task.')
        }
        await apiPost<Task>('/tasks', {
          project_id: promotionProjectId,
          parent_task_id: promotionParentTaskId || null,
          title: baseTitle,
          description: baseBrief,
          status: 'Todo',
          priority: '',
          completion_criteria: '',
          notes: '',
        })
        await apiPatch<Idea>(`/ideas/${ideaId}`, { status: 'Advanced' })
        recordIdeaEvalAppliedIfPending()
        onSaved(); onClose()
        return
      }
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Promote failed') } finally { setSaving(false) }
  }

  const handleShelve = async () => {
    setConfirmAction(null); setSaving(true)
    try {
      await apiPatch<Idea>(`/ideas/${ideaId}`, { status: 'Parked' })
      onSaved(); handleIdeaPanelClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Shelve failed') } finally { setSaving(false) }
  }

  const handleReject = async () => {
    setConfirmAction(null); setSaving(true)
    try {
      await apiDelete(`/ideas/${ideaId}`)
      onSaved(); handleIdeaPanelClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Reject failed') } finally { setSaving(false) }
  }

  const handleIncubate = () => {
    handleIdeaPanelClose()
  }

  if (loading) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0 overflow-auto"><p className="text-slate-500 text-sm">Loading…</p></div>
  if (!idea) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0 overflow-auto"><p className="text-slate-500 text-sm">Idea not found.</p><button type="button" onClick={handleIdeaPanelClose} className="mt-2 text-slate-400 hover:text-slate-200 text-sm">Close</button></div>

  const stages: { id: IdeaStage; step: number; label: string }[] = [
    { id: 'capture', step: 1, label: 'Capture' },
    { id: 'clarify', step: 2, label: 'Clarify' },
    { id: 'evaluate', step: 3, label: 'Evaluate' },
    { id: 'decide', step: 4, label: 'Decide' },
  ]

  return (
    <div className="flex-1 min-h-0 rounded-xl border border-slate-600 bg-slate-800/50 p-4 min-w-0 overflow-hidden flex flex-col">
      <div className="flex justify-between items-center mb-3 flex-wrap gap-2">
        <h3 className="text-sm font-medium text-slate-200">Idea</h3>
        <button type="button" onClick={handleIdeaPanelClose} className="text-slate-400 hover:text-slate-200 text-sm">Close</button>
      </div>
      <div className="flex gap-1 mb-4 border-b border-slate-700 pb-2" role="tablist" aria-label="Idea stages">
        {stages.map(({ id, step, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={stage === id}
            onClick={() => setStage(id)}
            className={`px-2.5 py-1.5 rounded text-xs font-medium ${stage === id ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-slate-200 bg-slate-800/50'}`}
          >
            <span className="text-slate-500 mr-1">{step}.</span> {label}
          </button>
        ))}
      </div>
      {saveError && <p className="text-red-400 text-xs mb-2">{saveError}</p>}

      <DetailPanelInviteChips
        entityType="idea"
        entityId={ideaId}
        titleLine={veEntityDisplayStr((form.title as string) ?? idea?.title ?? '') || 'Idea'}
        className="mb-2 shrink-0"
      />

      <div className="min-h-0 flex-1 overflow-y-auto">
      {stage === 'capture' && (
        <div className="space-y-3 flex-1">
          <p className="text-slate-500 text-xs">Lightweight. Jot it down; refine in Clarify.</p>
          <VeFocusRegion
            entity_type="idea"
            entity_id={ideaId}
            field_key="title"
            field_label="Title"
            field_kind="idea_body"
            getCurrentText={() => String(form.title ?? '')}
          >
            <DetailField label="Title" value={(form.title as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, title: v }))} placeholder="What’s the idea?" />
          </VeFocusRegion>
          <VeFocusRegion
            entity_type="idea"
            entity_id={ideaId}
            field_key="summary"
            field_label="Short note"
            field_kind="idea_body"
            getCurrentText={() => String(form.summary ?? '')}
          >
            <DetailField label="Short note" value={(form.summary as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, summary: v }))} textarea rows={2} placeholder="Optional" />
          </VeFocusRegion>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={() => handleSave('Captured')} disabled={saving} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm">Save</button>
            <button type="button" onClick={() => { setStage('clarify'); handleSave('Clarifying') }} disabled={saving} className="px-3 py-1.5 rounded-lg border border-slate-500 text-slate-200 text-sm">Next: Clarify</button>
          </div>
        </div>
      )}

      {stage === 'clarify' && (
        <div className="space-y-3 flex-1">
          <p className="text-slate-500 text-xs">Refine the idea before evaluation.</p>
          <VeFocusRegion
            entity_type="idea"
            entity_id={ideaId}
            field_key="title"
            field_label="Title"
            field_kind="idea_body"
            getCurrentText={() => String(form.title ?? '')}
          >
            <DetailField label="Title" value={(form.title as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, title: v }))} />
          </VeFocusRegion>
          <VeFocusRegion
            entity_type="idea"
            entity_id={ideaId}
            field_key="summary"
            field_label="Short note"
            field_kind="idea_body"
            getCurrentText={() => String(form.summary ?? '')}
          >
            <DetailField label="Short note" value={(form.summary as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, summary: v }))} textarea rows={2} />
          </VeFocusRegion>
          <button
            type="button"
            onClick={handleClarifyLocalTemplates}
            disabled={clarifyLoading}
            title="Fills empty fields with local templates only — no model call."
            className="px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs"
          >
            {clarifyLoading ? 'Applying…' : 'Suggest text (local, no LLM)'}
          </button>
          <VeFocusRegion
            entity_type="idea"
            entity_id={ideaId}
            field_key="description"
            field_label="Expanded description"
            field_kind="idea_body"
            getCurrentText={() => String(form.description ?? '')}
          >
            <DetailField label="Expanded description" value={(form.description as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, description: v }))} textarea rows={3} placeholder="Expand the idea" />
          </VeFocusRegion>
          <DetailField label="Intent / what this idea is trying to become" value={(form.desired_outcome as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, desired_outcome: v }))} textarea rows={2} placeholder="What success looks like" />
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={() => handleSave('Clarifying')} disabled={saving} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm">Save</button>
            <button type="button" onClick={() => { setStage('evaluate'); handleSave('Evaluated') }} disabled={saving} className="px-3 py-1.5 rounded-lg border border-slate-500 text-slate-200 text-sm">Next: Evaluate</button>
          </div>
        </div>
      )}

      {stage === 'evaluate' && (
        <div className="space-y-4 flex-1">
          <p className="text-slate-500 text-xs">Get AI-generated analysis to support your decision. Run evaluation, then review.</p>
          {evaluateLoading && (
            <div className="p-4 rounded-lg border border-amber-700/70 bg-amber-900/30 text-sm text-amber-100">
              Running evaluation… AI is reviewing this idea for cost, timeline, roles, risks, and recommendation.
            </div>
          )}
          {evaluateError && (
            <div className="p-3 rounded-lg border border-red-700/70 bg-red-900/30 text-sm text-red-200">
              {evaluateError}
              {hasEvaluationResults && (
                <p className="mt-2 text-red-200/90 text-xs">Showing last successful evaluation.</p>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" onClick={() => setStage('clarify')} className="px-2 py-1.5 rounded border border-slate-500 text-slate-200 hover:bg-slate-700 text-xs">
                  Refine idea before retrying
                </button>
                <button type="button" onClick={handleRunQuickEvaluation} disabled={evaluateLoading} className="px-2 py-1.5 rounded border border-amber-500 text-amber-200 hover:bg-amber-900/30 text-xs disabled:opacity-50">
                  Run quick evaluation (less strict)
                </button>
              </div>
            </div>
          )}
          {!evaluateLoading && (
            <>
              <div className="flex items-center gap-2 flex-wrap">
                <button type="button" onClick={handleRunEvaluation} disabled={saving} className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm">
                  {hasEvaluationResults ? 'Run evaluation again' : 'Run evaluation'}
                </button>
                {hasEvaluationResults && (
                  <button type="button" onClick={() => setAnalysisEditable((e) => !e)} className="px-2 py-1 rounded border border-slate-500 text-slate-300 hover:text-slate-100 text-xs">
                    {analysisEditable ? 'Lock overrides' : 'Edit overrides'}
                  </button>
                )}
              </div>
              {!hasEvaluationResults && (
                <p className="text-slate-500 text-xs">No evaluation results available yet.</p>
              )}
              <div className="rounded-lg border border-amber-700/50 bg-slate-900/80 p-4 space-y-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-medium text-amber-400/90 bg-amber-900/30 px-1.5 py-0.5 rounded">AI-generated</span>
                  <span className="text-slate-500 text-xs">
                    {hasEvaluationResults
                      ? (analysisEditable ? 'Overriding individual fields.' : 'Read-only. Use Edit overrides to change.')
                      : 'Run evaluation to fill. Empty fields show placeholders until then.'}
                  </span>
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-2 text-xs">
                  <DetailField label="Estimated cost (range)" value={analysis.estimated_cost_range} onChange={(v) => setAnalysis((a) => ({ ...a, estimated_cost_range: v }))} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
                  <DetailField label="Time to build" value={analysis.time_to_build} onChange={(v) => setAnalysis((a) => ({ ...a, time_to_build: v }))} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
                  <DetailField label="Time to ROI" value={analysis.time_to_roi} onChange={(v) => setAnalysis((a) => ({ ...a, time_to_roi: v }))} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
                  <div className="space-y-1">
                    <label className="block text-xs font-medium text-slate-400">ROI potential</label>
                    <select value={analysis.roi_potential} onChange={(e) => setAnalysis((a) => ({ ...a, roi_potential: e.target.value as IdeaDecisionAnalysis['roi_potential'] }))} disabled={!hasEvaluationResults || !analysisEditable} className="w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm disabled:opacity-75 disabled:cursor-not-allowed">
                      <option value="conservative">Conservative</option>
                      <option value="expected">Expected</option>
                      <option value="speculative">Speculative</option>
                    </select>
                  </div>
                </div>
                <DetailField label="Required roles" value={analysis.required_roles} onChange={(v) => setAnalysis((a) => ({ ...a, required_roles: v }))} textarea rows={1} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
                <DetailField label="Dependencies" value={analysis.likely_dependencies} onChange={(v) => setAnalysis((a) => ({ ...a, likely_dependencies: v }))} textarea rows={1} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
                <DetailField label="Risks" value={analysis.major_risks} onChange={(v) => setAnalysis((a) => ({ ...a, major_risks: v }))} textarea rows={1} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
                <DetailField label="Strategic alignment" value={analysis.strategic_alignment} onChange={(v) => setAnalysis((a) => ({ ...a, strategic_alignment: v }))} textarea rows={1} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
                <DetailField label="Suggested next step" value={analysis.suggested_next_step} onChange={(v) => setAnalysis((a) => ({ ...a, suggested_next_step: v }))} textarea rows={1} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
                <DetailField label="Recommendation" value={analysis.recommendation} onChange={(v) => setAnalysis((a) => ({ ...a, recommendation: v }))} textarea rows={1} placeholder="No estimate returned" readOnly={!hasEvaluationResults || !analysisEditable} />
              </div>
            </>
          )}
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={() => handleSave('Evaluated')} disabled={saving} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm">Save</button>
            <button type="button" onClick={() => setStage('decide')} className="px-3 py-1.5 rounded-lg border border-slate-500 text-slate-200 text-sm">Next: Decide</button>
          </div>
        </div>
      )}

      {stage === 'decide' && (
          <div className="space-y-4 flex-1">
          <p className="text-slate-400 text-sm">Choose what to do with this idea. Use the vocabulary: Promote, Incubate, Shelve, Reject.</p>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="font-medium text-slate-300">Promote target:</span>
            <select
              value={promotionTarget}
              onChange={(e) => setPromotionTarget(e.target.value as 'initiative' | 'project' | 'task')}
              className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs"
            >
              <option value="initiative">Initiative</option>
              <option value="project">Project</option>
              <option value="task">Task</option>
            </select>
            {promotionTarget === 'initiative' && (
              <select
                value={promotionInitiativeId}
                onChange={(e) => setPromotionInitiativeId(e.target.value)}
                className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs"
              >
                <option value="">Create new initiative</option>
                {initiatives.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.title || i.id}
                  </option>
                ))}
              </select>
            )}
            {promotionTarget === 'project' && (
              <select
                value={promotionInitiativeId}
                onChange={(e) => setPromotionInitiativeId(e.target.value)}
                className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs"
              >
                <option value="">No initiative (standalone project)</option>
                {initiatives.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.title || i.id}
                  </option>
                ))}
              </select>
            )}
            {promotionTarget === 'task' && (
              <>
                <select
                  value={promotionProjectId}
                  onChange={(e) => {
                    setPromotionProjectId(e.target.value)
                    setPromotionParentTaskId('')
                  }}
                  className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs"
                >
                  <option value="">Choose project</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title || p.id}
                    </option>
                  ))}
                </select>
                {promotionProjectId && (
                  <select
                    value={promotionParentTaskId}
                    onChange={(e) => setPromotionParentTaskId(e.target.value)}
                    className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs"
                  >
                    <option value="">Top-level task</option>
                    {tasks.filter((t) => t.project_id === promotionProjectId).map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.title || t.id}
                      </option>
                    ))}
                  </select>
                )}
              </>
            )}
            <button
              type="button"
              onClick={handlePromote}
              disabled={saving}
              className="ml-auto px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs"
            >
              Promote
            </button>
          </div>
          {analysis.recommendation && (
            <div className="p-3 rounded-lg border border-amber-700/50 bg-amber-900/20">
              <span className="text-xs font-medium text-amber-300">AI recommendation</span>
              <p className="text-slate-200 text-sm mt-1">{analysis.recommendation}</p>
            </div>
          )}
          <div className="rounded-lg border border-slate-600 bg-slate-800/30 p-3 mt-3">
            <span className="block text-xs font-medium text-slate-400 uppercase tracking-wide mb-1">Decision</span>
            <p className="text-[11px] text-slate-500 mb-3">
              This will move the idea into the selected target and mark it as advanced, or keep/shelve/reject it below.
            </p>
            <div className="flex flex-col gap-2">
              <button type="button" onClick={handleIncubate} className="px-3 py-2 rounded-lg border border-slate-500 text-slate-200 hover:bg-slate-700 text-sm text-left">
                Incubate — keep in ideas
              </button>
              <button type="button" onClick={() => setConfirmAction('shelve')} disabled={saving} className="px-3 py-2 rounded-lg border border-amber-600 text-amber-200 hover:bg-amber-900/30 text-sm text-left">
                Shelve — park for later
              </button>
              <button type="button" onClick={() => setConfirmAction('reject')} disabled={saving} className="px-3 py-2 rounded-lg border border-red-600 text-red-200 hover:bg-red-900/30 text-sm text-left">
                Reject — remove from consideration
              </button>
            </div>
          </div>
        </div>
      )}
      </div>

      {confirmAction === 'shelve' && <ConfirmModal title="Shelve idea" message="Move to Parked. You can bring it back later." confirmLabel="Shelve" variant="warning" onConfirm={handleShelve} onCancel={() => setConfirmAction(null)} />}
      {confirmAction === 'reject' && <ConfirmModal title="Reject idea" message="Remove from active consideration (delete). This cannot be undone." confirmLabel="Reject" onConfirm={handleReject} onCancel={() => setConfirmAction(null)} />}
      <DeferredPromptTodosSection
        entityType="idea"
        entityId={ideaId}
        contextTitle={formatVeEntityPromptTitle('idea', (form.title as string) || idea?.title)}
      />
    </div>
  )
}

/** On first load, fold legacy `deliverables` into the brief editor (single surface). */

/** Map stored project priority (free text or digit) to 1–5 for the slider. */
function parseProjectPriority1to5(priority: string | undefined | null): number {
  const t = String(priority ?? '').trim().toLowerCase()
  if (!t) return 3
  const n = parseInt(t, 10)
  if (!Number.isNaN(n) && n >= 1 && n <= 5) return n
  if (t.includes('high')) return 4
  if (t.includes('medium') || t === 'med') return 3
  if (t.includes('low')) return 2
  return 3
}

function ProjectDetailPanel({
  projectId,
  initiatives,
  persons,
  onClose,
  onSaved,
  apiGet,
  apiPatch,
  apiPost,
  apiDelete,
  serverWriteNonce = 0,
}: {
  projectId: string
  initiatives: Initiative[]
  persons: Person[]
  onClose: () => void
  onSaved: () => void
  apiGet: <T>(path: string) => Promise<T>
  apiPatch: <T>(path: string, body: unknown) => Promise<T>
  apiPost: <T>(path: string, body: unknown) => Promise<T>
  apiDelete: (path: string) => Promise<void>
  serverWriteNonce?: number
}) {
  const [project, setProject] = useState<Project | null>(null)
  const [projectTasks, setProjectTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [supportingOwnerIds, setSupportingOwnerIds] = useState<string[]>([])
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [projectFooterMenuOpen, setProjectFooterMenuOpen] = useState(false)
  const [suggestedWork, setSuggestedWork] = useState<{ items: ProjectSuggestionItem[]; checkedIds: string[] }>({
    items: [],
    checkedIds: [],
  })
  const [suggestLoading, setSuggestLoading] = useState(false)
  const [suggestError, setSuggestError] = useState<string | null>(null)
  const lastSuggestedWorkTraceRef = useRef<AiActionTrace | null>(null)
  const [suggestedWorkPanelOutcome, setSuggestedWorkPanelOutcome] = useState<AiUserOutcome>('none')
  const [suggestedWorkOutcomeNote, setSuggestedWorkOutcomeNote] = useState<string | null>(null)

  const closeProjectPanel = () => {
    const t = lastSuggestedWorkTraceRef.current
    if (t) {
      // Avoid a second ring entry after copy / acknowledge / batch dismiss already logged an outcome.
      if (suggestedWorkPanelOutcome === 'none') {
        pushAiActionTrace(withTraceOutcome(t, 'dismissed'))
      }
      lastSuggestedWorkTraceRef.current = null
    }
    setSuggestedWorkPanelOutcome('none')
    onClose()
  }

  useEffect(() => {
    const s = loadProjectSuggestionState(projectId)
    setSuggestedWork(s ? { items: s.items, checkedIds: s.checkedIds } : { items: [], checkedIds: [] })
    setSuggestError(null)
    setSuggestedWorkPanelOutcome('none')
    setSuggestedWorkOutcomeNote(null)
  }, [projectId])

  useEffect(() => {
    if (!projectFooterMenuOpen) return
    const onDoc = (e: MouseEvent) => {
      const el = e.target as HTMLElement
      if (el.closest('[data-project-footer-overflow-root]')) return
      setProjectFooterMenuOpen(false)
    }
    document.addEventListener('mousedown', onDoc, true)
    return () => document.removeEventListener('mousedown', onDoc, true)
  }, [projectFooterMenuOpen])

  useEffect(() => {
    let c = false
    setLoading(true)
    Promise.all([apiGet<Project>(`/projects/${projectId}`), apiGet<Task[]>(`/tasks?project_id=${encodeURIComponent(projectId)}`)]).then(([p, t]) => {
      if (!c) {
        setProject(p)
        setProjectTasks(Array.isArray(t) ? t : [])
        setForm({
          title: p.title,
          brief: p.brief ?? '',
          status: p.status,
          initiative_id: p.initiative_id ?? '',
          owner_id: p.owner_id ?? '',
          project_priority_1_5: parseProjectPriority1to5(p.priority),
          start_date: p.start_date ?? '',
          end_date: p.end_date ?? '',
          estimated_weekly_hours: p.estimated_weekly_hours ?? '',
          next_step_ai: p.next_step_ai ?? '',
          notes: p.notes ?? '',
        })
        setSupportingOwnerIds(Array.isArray(p.supporting_owner_ids) ? p.supporting_owner_ids : [])
      }
    }).catch(() => { if (!c) setProject(null) }).finally(() => { if (!c) setLoading(false) })
    return () => { c = true }
  }, [projectId, apiGet, serverWriteNonce])

  const suggestedCheckedSet = useMemo(() => new Set(suggestedWork.checkedIds), [suggestedWork.checkedIds])

  const handleSave = async () => {
    setSaveError(null); setSaving(true)
    try {
      const pr = form.project_priority_1_5
      const priorityStr =
        typeof pr === 'number' && pr >= 1 && pr <= 5 ? String(Math.round(pr)) : String(parseProjectPriority1to5(String(project?.priority ?? '')))
      const payload = {
        title: form.title,
        brief: form.brief,
        status: form.status,
        initiative_id: (form.initiative_id as string) || null,
        owner_id: (form.owner_id as string) || null,
        supporting_owner_ids: supportingOwnerIds,
        priority: priorityStr,
        start_date: (form.start_date as string) || null,
        end_date: (form.end_date as string) || null,
        estimated_weekly_hours: form.estimated_weekly_hours === '' ? null : Number(form.estimated_weekly_hours),
        deliverables: '',
        complexity: '',
        current_focus: '',
        next_step_ai: form.next_step_ai,
        notes: form.notes,
      }
      await apiPatch<Project>(`/projects/${projectId}`, payload)
      onSaved(); closeProjectPanel()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Save failed') } finally { setSaving(false) }
  }
  const handleArchive = async () => {
    setSaveError(null)
    setSaving(true)
    try {
      await apiPatch<Project>(`/projects/${projectId}`, { status: 'Parked' })
      onSaved(); setShowArchiveConfirm(false); setProjectFooterMenuOpen(false); closeProjectPanel()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Archive failed') } finally { setSaving(false) }
  }
  const handleDelete = async () => {
    try {
      await apiDelete(`/projects/${projectId}`)
      onSaved(); setShowDeleteConfirm(false); closeProjectPanel()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Delete failed') }
  }
  if (loading) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0"><p className="text-slate-500 text-sm">Loading…</p></div>
  if (!project) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0"><p className="text-slate-500 text-sm">Project not found.</p><button type="button" onClick={closeProjectPanel} className="mt-2 text-slate-400 hover:text-slate-200 text-sm">Close</button></div>
  const statusOptions = ['Draft', 'Ready', 'Active', 'Blocked', 'Complete', 'Parked']

  const projectStatus = String(form.status ?? project.status ?? 'Draft').trim()
  const projectOwnerId = String((form.owner_id as string) ?? project.owner_id ?? '')
  const projectOwnerName = persons.find((p) => p.id === projectOwnerId)?.name ?? ''
  const legacyNextStepLine = nextStepsPrimaryLine(String(form.next_step_ai ?? project.next_step_ai ?? ''))
  const projectEstimateHours = form.estimated_weekly_hours ?? project.estimated_weekly_hours ?? ''
  const projectEstimateText =
    projectEstimateHours === '' || projectEstimateHours == null ? '' : `${projectEstimateHours}h/week`

  const firstOpenProjectTask = projectTasks.find((t) => {
    const s = String(t.status ?? 'Todo').trim().toLowerCase()
    return s !== 'done' && s !== 'dropped'
  })
  const firstOpenTaskTitle = firstOpenProjectTask ? String(firstOpenProjectTask.title ?? '').trim() : ''
  const concreteNextLine = firstOpenTaskTitle || legacyNextStepLine
  const heroNextLine =
    concreteNextLine ||
    'Add a task — or capture context in Brief and use Earlier suggestion (AI) below when needed.'

  const projectPrioritySlider = (() => {
    const v = form.project_priority_1_5
    if (typeof v === 'number' && v >= 1 && v <= 5) return Math.round(v)
    return parseProjectPriority1to5(String(project?.priority ?? ''))
  })()
  const hasConcreteNext = Boolean(concreteNextLine)

  const supportingHint =
    supportingOwnerIds.length > 0 ? ` · +${supportingOwnerIds.length} supporting` : ''

  const hasDerivedRadar =
    project.duration != null || project.completionReadiness != null || project.unanchoredFlag != null

  const projectReadiness = (() => {
    const hasOwner = Boolean(projectOwnerName.trim())
    const hasNextSignal = hasConcreteNext
    const hasEstimate = projectEstimateText !== ''
    const score = (hasOwner ? 1 : 0) + (hasNextSignal ? 1 : 0) + (hasEstimate ? 1 : 0)
    if (projectStatus.toLowerCase() === 'parked') return 'low'
    if (score >= 3) return 'high'
    if (score >= 2) return 'medium'
    return 'low'
  })()

  const projectReadinessClass =
    projectReadiness === 'high' ? 'text-emerald-200' : projectReadiness === 'medium' ? 'text-amber-200' : 'text-red-200'

  const projectSynthesisSentence = (() => {
    if (projectStatus.toLowerCase() === 'blocked') return 'Blocked — resolve ownership / next steps'
    if (projectStatus.toLowerCase() === 'complete') return 'Complete — execution closed'
    if (projectReadiness === 'high') return 'Ready to execute this slice'
    if (projectReadiness === 'medium') return 'In motion — refine cadence or tasks'
    return 'Needs coordination — assign owner and tasks'
  })()

  const parseSuggestionKind = (k: string): ProjectSuggestionKind => {
    const allowed: ProjectSuggestionKind[] = [
      'missing_ownership',
      'uncovered_work',
      'coordination_gap',
      'unclear_scope',
    ]
    return allowed.includes(k as ProjectSuggestionKind) ? (k as ProjectSuggestionKind) : 'coordination_gap'
  }

  const handleGenerateSuggestedWork = async () => {
    setSuggestLoading(true)
    setSuggestError(null)
    try {
      const res = await apiPost<{ suggestions?: { id: string; kind: string; text: string }[]; error?: string }>(
        `/projects/${projectId}/suggested-work`,
        {},
      )
      if (res && typeof res === 'object' && typeof res.error === 'string' && res.error) {
        setSuggestError(res.error)
        return
      }
      const raw = Array.isArray(res?.suggestions) ? res.suggestions : []
      const items: ProjectSuggestionItem[] = raw
        .filter((r) => r && typeof r.id === 'string' && typeof r.text === 'string')
        .map((r) => ({
          id: r.id,
          kind: parseSuggestionKind(String(r.kind ?? '')),
          text: String(r.text).trim(),
        }))
      setGeneratedSuggestions(projectId, items)
      setSuggestedWork({ items, checkedIds: [] })
      setSuggestedWorkPanelOutcome('none')
      setSuggestedWorkOutcomeNote(null)
      const outText = items
        .map((it) => `${PROJECT_SUGGESTION_KIND_LABEL[it.kind]}: ${it.text}`)
        .join('\n')
      const tr = createAiActionTrace({
        surface: 'vision_execution',
        action_kind: 'suggestion_batch',
        action_intent: 'project_suggested_work',
        subject_type: 'project',
        subject_id: projectId,
        field_key: null,
        input_snapshot: 'POST /projects/{id}/suggested-work',
        prompt_version: 've_project_suggestion_batch_v1',
        output: outText.slice(0, 4000),
        user_outcome: 'none',
      })
      lastSuggestedWorkTraceRef.current = tr
      pushAiActionTrace(tr)
    } catch (e) {
      setSuggestError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setSuggestLoading(false)
    }
  }

  const handleToggleSuggestedItem = (suggestionId: string) => {
    toggleSuggestionChecked(projectId, suggestionId)
    const s = loadProjectSuggestionState(projectId)
    if (s) setSuggestedWork({ items: s.items, checkedIds: s.checkedIds })
  }

  return (
    <div className="flex-1 min-h-0 rounded-xl border border-slate-600 bg-slate-800/50 p-4 min-w-0 overflow-hidden flex flex-col">
      <div className="flex justify-between mb-3"><h3 className="text-sm font-medium text-slate-200">Project</h3><button type="button" onClick={closeProjectPanel} className="text-slate-400 hover:text-slate-200 text-sm">Close</button></div>
      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-2.5 mb-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] uppercase tracking-wide border border-slate-500/60 text-slate-200 bg-slate-950/30">
            {projectStatus}
          </span>
          <span className="text-[11px] text-slate-500">
            Owner: <span className="text-slate-300">{projectOwnerName || '—'}</span>
            {supportingHint ? <span className="text-slate-500">{supportingHint}</span> : null}
          </span>
        </div>
        <div className="mt-1.5 text-[11px] text-slate-500">
          Next:{' '}
          <span className={concreteNextLine ? 'text-slate-200' : 'text-slate-500'}>{heroNextLine}</span>
        </div>
        {projectReadiness !== 'high' ? (
          <div className="mt-1 text-[11px] text-slate-500">
            <span className={projectReadinessClass}>{projectReadiness}</span>
            <span className="text-slate-600"> · </span>
            {projectSynthesisSentence}
          </div>
        ) : (
          <div className="mt-1 text-[11px] text-emerald-200/90">{projectSynthesisSentence}</div>
        )}
      </div>
      <TraceabilityMeta notesOrDescription={project.notes} />
      {saveError && <p className="text-red-400 text-xs mb-2">{saveError}</p>}

      <DetailPanelInviteChips
        entityType="project"
        entityId={projectId}
        titleLine={veEntityDisplayStr((form.title as string) ?? project?.title ?? '') || 'Project'}
        className="mb-2 shrink-0"
      />

      <div className="rounded-lg border border-slate-700 bg-slate-900/30 p-2.5 mb-2 shrink-0">
        <h4 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-1.5">Tasks in this project</h4>
        {projectTasks.length === 0 ? (
          <p className="text-[11px] text-slate-500 leading-relaxed">
            No tasks yet — add from the task list in this view, or create a task linked to this project.
          </p>
        ) : (
          <ul className="space-y-1 max-h-40 overflow-y-auto pr-1">
            {projectTasks.map((t) => (
              <li key={t.id} className="text-slate-300 text-sm">
                {veEntityDisplayStr(t.title) || '(Untitled)'}{' '}
                <span className="text-slate-500 text-xs">({veEntityDisplayStr(t.status)})</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-2 flex-1 overflow-y-auto min-h-0">
        <DetailSection title="Identity / scope" defaultOpen>
          <DetailField label="Title" value={(form.title as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, title: v }))} />
          <DetailField
            label="Brief (scope & outcomes)"
            value={(form.brief as string) ?? ''}
            onChange={(v) => setForm((p) => ({ ...p, brief: v }))}
            textarea
            rows={4}
            placeholder="Scope, outcomes, and deliverables — one narrative."
          />
          <DetailField label="Status" value={(form.status as string) ?? 'Draft'} onChange={(v) => setForm((p) => ({ ...p, status: v }))} options={statusOptions.map((s) => ({ value: s, label: s }))} />
          <DetailField label="Initiative" value={(form.initiative_id as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, initiative_id: v }))} options={[{ value: '', label: 'None' }, ...initiatives.map((i) => ({ value: i.id, label: i.title || i.id }))]} />
        </DetailSection>

        <DetailSection title="Plan & cadence" defaultOpen>
          <DetailField label="Owner" value={(form.owner_id as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, owner_id: v }))} options={[{ value: '', label: 'None' }, ...persons.map((p) => ({ value: p.id, label: veEntityDisplayStr(p.name) || p.id }))]} />
          <EntityMultiSelect label="Supporting owners" selectedIds={supportingOwnerIds} onChange={setSupportingOwnerIds} options={persons} getLabel={(p) => (p as Person).name} />
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-400">Priority (1–5)</label>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={1}
                max={5}
                step={1}
                value={projectPrioritySlider}
                onChange={(e) => setForm((p) => ({ ...p, project_priority_1_5: Number(e.target.value) }))}
                className="flex-1 h-2 rounded bg-slate-700 accent-amber-500"
                aria-valuemin={1}
                aria-valuemax={5}
                aria-valuenow={projectPrioritySlider}
              />
              <span className="text-slate-300 text-sm w-5 tabular-nums">{projectPrioritySlider}</span>
            </div>
            <p className="text-[10px] text-slate-500 leading-snug">Stored as a number on save (legacy text priorities map to a default when you first open).</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <DetailField label="Start date" value={(form.start_date as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, start_date: v }))} />
            <DetailField label="End date" value={(form.end_date as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, end_date: v }))} />
          </div>
          <DetailField label="Estimated weekly hours" value={(form.estimated_weekly_hours as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, estimated_weekly_hours: v }))} type="number" />
          <div className="rounded-lg border border-amber-900/45 bg-amber-950/20 p-3 space-y-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs font-medium text-amber-200/95">Suggested work (AI)</p>
                <p className="text-[10px] text-slate-500 mt-0.5 leading-snug max-w-xl">
                  AI reads your brief, tasks, assignees, and dependencies. These are coordination observations — not initiative execution steps and not auto-created tasks.
                  Check items off as you resolve them; checked items stay visible.
                </p>
              </div>
              <button
                type="button"
                disabled={suggestLoading}
                onClick={() => void handleGenerateSuggestedWork()}
                className="shrink-0 px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-medium"
              >
                {suggestLoading ? 'Generating…' : 'Generate suggestions'}
              </button>
            </div>
            {suggestError && <p className="text-red-400 text-xs">{suggestError}</p>}
            {suggestedWorkOutcomeNote && (
              <p className="text-[11px] text-emerald-200/90 border border-emerald-800/35 rounded px-2 py-1 bg-emerald-950/25" role="status">
                {suggestedWorkOutcomeNote}
              </p>
            )}
            {!suggestLoading && suggestedWork.items.length === 0 && (
              <p className="text-[11px] text-slate-500">No suggestions yet — generate to refresh from the current project snapshot.</p>
            )}
            {suggestedWork.items.length > 0 && (
              <ul className="space-y-2 pt-1 border-t border-amber-900/30">
                {suggestedWork.items.map((item) => {
                  const done = suggestedCheckedSet.has(item.id)
                  return (
                    <li key={item.id} className={`flex gap-2.5 items-start ${done ? 'opacity-60' : ''}`}>
                      <input
                        type="checkbox"
                        checked={done}
                        onChange={() => handleToggleSuggestedItem(item.id)}
                        className="mt-1 shrink-0 rounded border-slate-500 accent-amber-600"
                        aria-label={`Addressed: ${item.text.slice(0, 80)}`}
                      />
                      <div className="min-w-0 flex-1">
                        <span className="text-[10px] uppercase tracking-wide text-amber-200/70">
                          {PROJECT_SUGGESTION_KIND_LABEL[item.kind]}
                        </span>
                        <p className={`text-sm ${done ? 'text-slate-500 line-through' : 'text-slate-200'}`}>{item.text}</p>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
            {suggestedWork.items.length > 0 && (
              <AiActionResultPanel
                className="mt-2"
                heading="AI suggestions (review)"
                subheading={`${suggestedWork.items.length} item(s) — checklist only; not auto-saved as tasks`}
                recordedOutcome={suggestedWorkPanelOutcome}
                applyLabel="Acknowledge"
                onApply={() => {
                  const t = lastSuggestedWorkTraceRef.current
                  if (t) {
                    pushAiActionTrace(withTraceOutcome(t, 'applied'))
                    lastSuggestedWorkTraceRef.current = null
                    void apiPost<{ activity_event_id: string }>('/coordination/client-checkpoint', {
                      checkpoint: 'ai_suggestion_applied',
                      entity_type: 'project',
                      entity_id: projectId,
                      user_outcome: 'applied',
                      trace_id: t.trace_id,
                      action_intent: t.action_intent ?? undefined,
                    }).catch(() => {})
                  }
                  setSuggestedWorkPanelOutcome('applied')
                  setSuggestedWorkOutcomeNote('Recorded in your action log: you acknowledged this batch.')
                  setSuggestError(null)
                }}
                dismissLabel="Dismiss batch"
                onDismiss={() => {
                  const t = lastSuggestedWorkTraceRef.current
                  if (t) {
                    pushAiActionTrace(withTraceOutcome(t, 'dismissed'))
                    lastSuggestedWorkTraceRef.current = null
                  }
                  void apiPost<{ activity_event_id: string }>('/coordination/client-checkpoint', {
                    checkpoint: 'ai_suggestion_applied',
                    entity_type: 'project',
                    entity_id: projectId,
                    user_outcome: 'dismissed',
                    ...(t
                      ? { trace_id: t.trace_id, action_intent: t.action_intent ?? undefined }
                      : {}),
                  }).catch(() => {})
                  setSuggestedWorkPanelOutcome('dismissed')
                  setSuggestedWorkOutcomeNote(
                    'Recorded: friction checkpoint on this project (dismissed batch).',
                  )
                  clearProjectSuggestions(projectId)
                  setSuggestedWork({ items: [], checkedIds: [] })
                }}
                copyLabel="Copy all"
                onCopy={async () => {
                  const text = suggestedWork.items
                    .map((it) => `${PROJECT_SUGGESTION_KIND_LABEL[it.kind]}: ${it.text}`)
                    .join('\n')
                  try {
                    await navigator.clipboard.writeText(text)
                    const t = lastSuggestedWorkTraceRef.current
                    if (t) pushAiActionTrace(withTraceOutcome(t, 'copied'))
                    setSuggestedWorkPanelOutcome('copied')
                    setSuggestedWorkOutcomeNote('Recorded in your action log: you copied this batch.')
                  } catch {
                    setSuggestError('Could not copy — select text manually.')
                  }
                }}
              />
            )}
          </div>
        </DetailSection>

        <p className="text-[11px] text-slate-500 px-0.5 -mb-1">
          Earlier AI suggestion — optional. Prefer tasks and Brief above — keep only for legacy or transitional text.
        </p>
        <DetailSection title="Earlier suggestion (AI)" defaultOpen={false}>
          <DetailField
            label="Earlier suggestion (AI)"
            value={(form.next_step_ai as string) ?? ''}
            onChange={(v) => setForm((p) => ({ ...p, next_step_ai: v }))}
            textarea
            rows={3}
            placeholder="Older model text — initiatives use structured execution steps as the checklist."
          />
        </DetailSection>

        <DetailSection title="Notes / admin" defaultOpen={false}>
          <DetailField label="Notes" value={(form.notes as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, notes: v }))} textarea rows={3} />
        </DetailSection>

        {hasDerivedRadar ? (
          <>
            <p className="text-[11px] text-slate-500 px-0.5 -mb-1">Radar — read-only hints from evaluation — optional context.</p>
            <DetailSection title="Radar (read-only)" defaultOpen={false}>
              {project.duration != null && <p className="text-xs text-slate-400">Duration: {project.duration} days</p>}
              {project.completionReadiness != null && <p className="text-xs text-slate-400">Readiness: {project.completionReadiness}</p>}
              {project.unanchoredFlag != null && <p className="text-xs text-slate-400">Unanchored: {project.unanchoredFlag ? 'Yes' : 'No'}</p>}
            </DetailSection>
          </>
        ) : null}

        <DeferredPromptTodosSection
          entityType="project"
          entityId={projectId}
          contextTitle={formatVeEntityPromptTitle('project', (form.title as string) || project?.title)}
        />
        <MetadataSection data={{ id: project.id, initiative_id: project.initiative_id, owner_id: project.owner_id, created_at: project.created_at, updated_at: project.updated_at }} />
      </div>
      <div className="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-slate-600">
        <button type="button" onClick={handleSave} disabled={saving} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-medium">
          Save
        </button>
        <button type="button" onClick={closeProjectPanel} className="px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800 text-sm">
          Cancel
        </button>
        <div className="relative ml-auto sm:ml-0" data-project-footer-overflow-root>
          <button
            type="button"
            aria-expanded={projectFooterMenuOpen}
            aria-haspopup="menu"
            aria-label="More project actions"
            className="px-2.5 py-1.5 rounded-lg border border-slate-600 text-slate-400 text-sm hover:bg-slate-800"
            onClick={() => setProjectFooterMenuOpen((o) => !o)}
          >
            ⋯
          </button>
          {projectFooterMenuOpen && (
            <div
              className="absolute bottom-full right-0 sm:right-auto sm:left-0 mb-1 z-30 min-w-[10rem] rounded border border-slate-600 bg-slate-900 py-1 shadow-xl text-sm"
              role="menu"
            >
              <button
                type="button"
                role="menuitem"
                className="w-full text-left px-3 py-2 text-amber-200 hover:bg-slate-800"
                onClick={() => {
                  setProjectFooterMenuOpen(false)
                  setShowArchiveConfirm(true)
                }}
              >
                Archive (Park)…
              </button>
              <button
                type="button"
                role="menuitem"
                className="w-full text-left px-3 py-2 text-red-300 hover:bg-slate-800"
                onClick={() => {
                  setProjectFooterMenuOpen(false)
                  setShowDeleteConfirm(true)
                }}
              >
                Delete…
              </button>
            </div>
          )}
        </div>
      </div>
      {showArchiveConfirm && <ConfirmModal title="Archive project?" message="Set status to Parked. You can change it later." confirmLabel="Archive" variant="warning" onConfirm={handleArchive} onCancel={() => setShowArchiveConfirm(false)} />}
      {showDeleteConfirm && <ConfirmModal title="Delete project?" message="This will remove the project and its tasks. This cannot be undone." confirmLabel="Delete" onConfirm={handleDelete} onCancel={() => setShowDeleteConfirm(false)} />}
    </div>
  )
}

function TaskDetailPanel({
  taskId,
  projects,
  tasks,
  persons,
  onClose,
  onSaved,
  apiGet,
  apiPatch,
  apiPost,
  apiDelete,
  serverWriteNonce = 0,
}: {
  taskId: string
  projects: Project[]
  tasks: Task[]
  persons: Person[]
  onClose: () => void
  onSaved: () => void
  apiGet: <T>(path: string) => Promise<T>
  apiPatch: <T>(path: string, body: unknown) => Promise<T>
  apiPost: <T>(path: string, body: unknown) => Promise<T>
  apiDelete: (path: string) => Promise<void>
  serverWriteNonce?: number
}) {
  const [task, setTask] = useState<Task | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [dependencyIds, setDependencyIds] = useState<string[]>([])
  const [showDropConfirm, setShowDropConfirm] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [taskFooterMenuOpen, setTaskFooterMenuOpen] = useState(false)

  useEffect(() => {
    if (!taskFooterMenuOpen) return
    const onDoc = (e: MouseEvent) => {
      const el = e.target as HTMLElement
      if (el.closest('[data-task-footer-overflow-root]')) return
      setTaskFooterMenuOpen(false)
    }
    document.addEventListener('mousedown', onDoc, true)
    return () => document.removeEventListener('mousedown', onDoc, true)
  }, [taskFooterMenuOpen])

  useEffect(() => {
    let c = false
    setLoading(true)
    apiGet<Task>(`/tasks/${taskId}`).then((data) => {
      if (!c) {
        setTask(data)
        setForm({
          title: data.title,
          description: data.description ?? '',
          status: data.status ?? 'Todo',
          project_id: data.project_id ?? '',
          assignee_id: data.assignee_id ?? '',
          priority: data.priority ?? '',
          estimated_hours: data.estimated_hours ?? '',
          due_date: data.due_date ?? '',
          completion_criteria: data.completion_criteria ?? '',
          notes: data.notes ?? '',
        })
        setDependencyIds(Array.isArray(data.dependency_ids) ? data.dependency_ids : [])
      }
    }).catch(() => { if (!c) setTask(null) }).finally(() => { if (!c) setLoading(false) })
    return () => { c = true }
  }, [taskId, apiGet, serverWriteNonce])

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<VeFocusApplyRewriteDetail>).detail
      if (!d || d.entity_type !== 'task' || d.entity_id !== taskId || !d.text) return
      if (d.field_key === 'title') setForm((p) => ({ ...p, title: d.text }))
      if (d.field_key === 'description') setForm((p) => ({ ...p, description: d.text }))
    }
    window.addEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, handler)
    return () => window.removeEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, handler)
  }, [taskId])

  useEffect(() => {
    const handler = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d || d.entity_type !== 'task' || d.entity_id !== taskId || !d.text) return
      if (d.field_key !== 'title' && d.field_key !== 'description') return
      const formKey = d.field_key as 'title' | 'description'
      setForm((p) => {
        const prev = String((p as Record<string, unknown>)[formKey] ?? '')
        const next = insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd)
        return { ...p, [formKey]: next }
      })
    }
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, handler)
    return () => window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, handler)
  }, [taskId])

  const handleSave = async () => {
    setSaveError(null); setSaving(true)
    try {
      await apiPatch<Task>(`/tasks/${taskId}`, {
        title: form.title,
        description: form.description,
        status: form.status,
        project_id: (form.project_id as string)?.trim() ? (form.project_id as string).trim() : null,
        assignee_id: (form.assignee_id as string) || null,
        priority: form.priority,
        estimated_hours: form.estimated_hours === '' ? null : Number(form.estimated_hours),
        due_date: (form.due_date as string) || null,
        dependency_ids: dependencyIds,
        completion_criteria: form.completion_criteria,
        notes: form.notes,
      })
      onSaved(); onClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Save failed') } finally { setSaving(false) }
  }
  const handleDrop = async () => {
    setSaving(true)
    try {
      await apiPatch<Task>(`/tasks/${taskId}`, { status: 'Dropped' })
      onSaved(); setShowDropConfirm(false); onClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Drop failed') } finally { setSaving(false) }
  }
  const handleDelete = async () => {
    try {
      await apiDelete(`/tasks/${taskId}`)
      onSaved(); setShowDeleteConfirm(false); onClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Delete failed') }
  }

  const handleToggleDone = async () => {
    if (!task) return
    const cur = String(form.status ?? task.status ?? 'Todo').trim().toLowerCase()
    if (cur === 'dropped') return
    const next = cur === 'done' ? 'Todo' : 'Done'
    setSaveError(null)
    setSaving(true)
    try {
      await apiPatch<Task>(`/tasks/${taskId}`, { status: next })
      setForm((p) => ({ ...p, status: next }))
      onSaved()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0"><p className="text-slate-500 text-sm">Loading…</p></div>
  if (!task) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0"><p className="text-slate-500 text-sm">Task not found.</p><button type="button" onClick={onClose} className="mt-2 text-slate-400 hover:text-slate-200 text-sm">Close</button></div>
  const taskOptions = tasks.filter((t) => t.id !== taskId)

  const taskStatus = String(form.status ?? task.status ?? 'Todo').trim()
  const taskAssigneeId = String((form.assignee_id as string) ?? task.assignee_id ?? '')
  const taskAssigneeName = persons.find((p) => p.id === taskAssigneeId)?.name ?? ''
  const taskDueDate = String(form.due_date ?? task.due_date ?? '').trim()
  const taskCompletionCriteria = String(form.completion_criteria ?? task.completion_criteria ?? '').trim()

  const taskReadiness = (() => {
    const hasAssignee = Boolean(taskAssigneeName.trim())
    const hasDue = Boolean(taskDueDate)
    const hasCriteria = Boolean(taskCompletionCriteria)
    const score = (hasAssignee ? 1 : 0) + (hasDue ? 1 : 0) + (hasCriteria ? 1 : 0)
    if (taskStatus.toLowerCase() === 'done') return 'high'
    if (score >= 3) return 'high'
    if (score >= 2) return 'medium'
    return 'low'
  })()

  const taskReadinessClass =
    taskReadiness === 'high' ? 'text-emerald-200' : taskReadiness === 'medium' ? 'text-amber-200' : 'text-red-200'

  const taskSynthesisSentence = (() => {
    if (taskStatus.toLowerCase() === 'done') return 'Done — completion verified'
    if (taskStatus.toLowerCase() === 'blocked') return 'Blocked — unblock before executing'
    if (taskReadiness === 'high') return 'Ready to execute this action'
    if (taskReadiness === 'medium') return 'In motion — tighten assignment and criteria'
    return 'Needs setup — define who + when + how to know'
  })()

  const statusLower = taskStatus.toLowerCase()
  const canToggleDone = statusLower !== 'dropped'

  return (
    <div className="flex-1 min-h-0 rounded-xl border border-slate-600 bg-slate-800/50 p-4 min-w-0 overflow-hidden flex flex-col">
      <div className="flex justify-between mb-3"><h3 className="text-sm font-medium text-slate-200">Task</h3><button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-200 text-sm">Close</button></div>
      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-2.5 mb-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] uppercase tracking-wide border border-slate-500/60 text-slate-200 bg-slate-950/30">
            {taskStatus}
          </span>
          {taskReadiness !== 'high' ? (
            <span className="text-[11px] text-slate-500">
              <span className={taskReadinessClass}>{taskReadiness}</span>
              <span className="text-slate-600"> · </span>
              {taskSynthesisSentence}
            </span>
          ) : (
            <span className="text-[11px] text-emerald-200/90">{taskSynthesisSentence}</span>
          )}
        </div>
      </div>
      <TraceabilityMeta notesOrDescription={task.notes} />
      {saveError && <p className="text-red-400 text-xs mb-2">{saveError}</p>}

      <DetailPanelInviteChips
        entityType="task"
        entityId={taskId}
        titleLine={veEntityDisplayStr((form.title as string) ?? task?.title ?? '') || 'Task'}
        className="mb-2 shrink-0"
      />

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        <DetailSection title="Task" defaultOpen>
          <VeFocusRegion
            entity_type="task"
            entity_id={taskId}
            field_key="title"
            field_label="Title"
            field_kind="idea_body"
            getCurrentText={() => String(form.title ?? '')}
          >
            <DetailField label="Title" value={(form.title as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, title: v }))} />
          </VeFocusRegion>
          <VeFocusRegion
            entity_type="task"
            entity_id={taskId}
            field_key="description"
            field_label="Description"
            field_kind="idea_body"
            getCurrentText={() => String(form.description ?? '')}
          >
            <DetailField label="Description" value={(form.description as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, description: v }))} textarea rows={3} />
          </VeFocusRegion>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <DetailField label="Assignee" value={(form.assignee_id as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, assignee_id: v }))} options={[{ value: '', label: 'None' }, ...persons.map((p) => ({ value: p.id, label: veEntityDisplayStr(p.name) || p.id }))]} />
            <DetailField label="Due date" value={(form.due_date as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, due_date: v }))} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <DetailField label="Priority" value={(form.priority as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, priority: v }))} placeholder="e.g. High" />
            <DetailField label="Estimated hours" value={(form.estimated_hours as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, estimated_hours: v }))} type="number" />
          </div>
          <DetailField
            label="Status"
            value={(form.status as string) ?? 'Todo'}
            onChange={(v) => setForm((p) => ({ ...p, status: v }))}
            options={['Todo', 'In Progress', 'Blocked', 'Done', 'Dropped'].map((s) => ({ value: s, label: s }))}
          />
          <p className="text-[11px] text-slate-500 -mt-1">Use <strong className="text-slate-400">Done</strong> below for quick completion — or change status here (e.g. Blocked, Dropped).</p>
        </DetailSection>
        <DetailSection title="Dependencies" defaultOpen={false}>
          <p className="text-[11px] text-slate-500 mb-2">Add only if this task is blocked by another — empty is normal.</p>
          <EntityMultiSelect label="Depends on (tasks)" selectedIds={dependencyIds} onChange={setDependencyIds} options={taskOptions} getLabel={(t) => (t as Task).title} placeholder="Search tasks…" />
        </DetailSection>
        <p className="text-[11px] text-slate-500 px-0.5 -mb-1">Completion criteria — optional. Expand to define how you’ll know this is done.</p>
        <DetailSection title="Completion criteria" defaultOpen={false}>
          <DetailField label="Completion criteria" value={(form.completion_criteria as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, completion_criteria: v }))} textarea rows={2} />
        </DetailSection>
        <DetailSection title="Notes / admin" defaultOpen={false}>
          <DetailField label="Notes" value={(form.notes as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, notes: v }))} textarea rows={3} />
        </DetailSection>
        <DeferredPromptTodosSection
          entityType="task"
          entityId={taskId}
          contextTitle={formatVeEntityPromptTitle('task', (form.title as string) || task?.title)}
        />
        <MetadataSection data={{ id: task.id, project_id: task.project_id, assignee_id: task.assignee_id, created_at: task.created_at, updated_at: task.updated_at }} />
        {import.meta.env.DEV && (
          <TaskSoilDevAppend
            taskId={taskId}
            taskTitle={String((form.title as string) ?? task.title ?? '')}
            apiPost={apiPost}
          />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-slate-600">
        <button
          type="button"
          disabled={saving || !canToggleDone}
          onClick={() => void handleToggleDone()}
          title={!canToggleDone ? 'Use Status to change a dropped task' : undefined}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium disabled:opacity-50 ${
            statusLower === 'done'
              ? 'border border-slate-500 text-slate-200 hover:bg-slate-800'
              : 'bg-emerald-600 hover:bg-emerald-500 text-white'
          }`}
        >
          {statusLower === 'done' ? 'Reopen' : 'Done'}
        </button>
        <button type="button" onClick={handleSave} disabled={saving} className="px-3 py-1.5 rounded-lg bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-slate-100 text-sm font-medium">Save</button>
        <button type="button" onClick={onClose} className="px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800 text-sm">Cancel</button>
        <div className="relative ml-auto sm:ml-0" data-task-footer-overflow-root>
          <button
            type="button"
            aria-expanded={taskFooterMenuOpen}
            aria-haspopup="menu"
            aria-label="More task actions"
            className="px-2.5 py-1.5 rounded-lg border border-slate-600 text-slate-400 text-sm hover:bg-slate-800"
            onClick={() => setTaskFooterMenuOpen((o) => !o)}
          >
            ⋯
          </button>
          {taskFooterMenuOpen && (
            <div
              className="absolute bottom-full right-0 sm:right-auto sm:left-0 mb-1 z-30 min-w-[10rem] rounded border border-slate-600 bg-slate-900 py-1 shadow-xl text-sm"
              role="menu"
            >
              <button
                type="button"
                role="menuitem"
                className="w-full text-left px-3 py-2 text-amber-200 hover:bg-slate-800"
                onClick={() => {
                  setTaskFooterMenuOpen(false)
                  setShowDropConfirm(true)
                }}
              >
                Drop task…
              </button>
              <button
                type="button"
                role="menuitem"
                className="w-full text-left px-3 py-2 text-red-300 hover:bg-slate-800"
                onClick={() => {
                  setTaskFooterMenuOpen(false)
                  setShowDeleteConfirm(true)
                }}
              >
                Delete…
              </button>
            </div>
          )}
        </div>
      </div>
      {showDropConfirm && <ConfirmModal title="Drop task?" message="Set status to Dropped. You can change it later." confirmLabel="Drop" variant="warning" onConfirm={handleDrop} onCancel={() => setShowDropConfirm(false)} />}
      {showDeleteConfirm && <ConfirmModal title="Delete task?" message="This cannot be undone." confirmLabel="Delete" onConfirm={handleDelete} onCancel={() => setShowDeleteConfirm(false)} />}
    </div>
  )
}

/** Deterministic capacity status for display (Over capacity / Near capacity / Available for more work). */
function getCapacityStatus(cap: CapacityProfile | undefined): 'Over capacity' | 'Near capacity' | 'Available for more work' {
  if (!cap || cap.weekly_capacity_hours == null || cap.weekly_capacity_hours <= 0) return 'Available for more work'
  if (cap.overcapacity) return 'Over capacity'
  const active = cap.activeWeeklyHours ?? 0
  if (active / cap.weekly_capacity_hours >= 0.8) return 'Near capacity'
  return 'Available for more work'
}

/** Humanized capacity summary: e.g. "20h active of 40h" or "20h available". */
function formatCapacitySummary(cap: CapacityProfile | undefined): string {
  if (!cap) return '—'
  const weekly = cap.weekly_capacity_hours ?? 0
  const active = cap.activeWeeklyHours ?? 0
  if (weekly <= 0) return active > 0 ? `${active}h active` : '—'
  const available = Math.max(0, weekly - active)
  if (cap.overcapacity) return `${active}h active of ${weekly}h (over)`
  if (available === 0) return `${active}h active of ${weekly}h`
  return `${active}h active of ${weekly}h · ${available}h available`
}

function PersonDetailPanel({
  personId,
  capacityProfiles,
  initiatives,
  projects,
  tasks,
  assets,
  onClose,
  onSaved,
  onAssignmentChange,
  apiGet,
  apiPatch,
  apiPut,
  apiDelete,
  influenceLinkLists,
  canonicalCoreProfileId,
}: {
  personId: string
  capacityProfiles: CapacityProfile[]
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  assets: Asset[]
  onClose: () => void
  onSaved: () => void
  onAssignmentChange?: () => void
  apiGet: <T>(path: string) => Promise<T>
  apiPatch: <T>(path: string, body: unknown) => Promise<T>
  apiPut: <T>(path: string, body: unknown) => Promise<T>
  apiDelete: (path: string) => Promise<void>
  influenceLinkLists?: {
    coreProfiles: { id: string; label: string }[]
    perspectiveAgents: { id: string; label: string }[]
  }
  canonicalCoreProfileId?: string | null
}) {
  const [person, setPerson] = useState<Person | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [capacityHours, setCapacityHours] = useState<string>('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [showAssignSeat, setShowAssignSeat] = useState(false)
  const [assignInitiativeId, setAssignInitiativeId] = useState('')
  const [assignSeatRoleMode, setAssignSeatRoleMode] = useState<'existing' | 'new'>('existing')
  const [assignSeatRoleIndex, setAssignSeatRoleIndex] = useState(0)
  const [assignSeatNewRole, setAssignSeatNewRole] = useState('')
  const [showAssignProject, setShowAssignProject] = useState(false)
  const [assignProjectId, setAssignProjectId] = useState('')
  const [assignProjectRole, setAssignProjectRole] = useState<'owner' | 'supporting'>('owner')
  const [showAssignTask, setShowAssignTask] = useState(false)
  const [assignTaskId, setAssignTaskId] = useState('')
  const [assignError, setAssignError] = useState<string | null>(null)
  const [assigning, setAssigning] = useState(false)
  useEffect(() => {
    let c = false
    setLoading(true)
    apiGet<Person>(`/persons/${personId}`).then((data) => { if (!c) { setPerson(data); setForm({ name: data.name, role: data.role ?? '', relationship_type: data.relationship_type ?? '', contact_info: data.contact_info ?? '', strengths: data.strengths ?? '', needs: data.needs ?? '', wants: data.wants ?? '', availability: data.availability ?? '', notes: data.notes ?? '' }); const cap = capacityProfiles.find((cp) => cp.person_id === personId); setCapacityHours(cap ? String(cap.weekly_capacity_hours) : '') } }).catch(() => { if (!c) setPerson(null) }).finally(() => { if (!c) setLoading(false) })
    return () => { c = true }
  }, [personId, capacityProfiles, apiGet])
  const handleSave = async () => {
    setSaveError(null); setSaving(true)
    try {
      await apiPatch<Person>(`/persons/${personId}`, form)
      if (capacityHours !== '') await apiPut(`/capacity-profiles`, { person_id: personId, weekly_capacity_hours: Number(capacityHours) })
      onSaved(); onClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Save failed') } finally { setSaving(false) }
  }
  const handleDelete = async () => {
    try {
      await apiDelete(`/persons/${personId}`)
      onSaved(); setShowDeleteConfirm(false); onClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Delete failed') }
  }

  const handleAssignToSeat = async () => {
    if (!assignInitiativeId) return
    const init = initiatives.find((i) => i.id === assignInitiativeId)
    if (!init) return
    setAssignError(null); setAssigning(true)
    try {
      const currentSeats = Array.isArray(init.seats) ? init.seats : []
      const seatsPayload: { role: string; assigned_person_id: string | null; estimated_effort: string | null; notes: string }[] = currentSeats.map((s) => ({
        role: s.role ?? '',
        assigned_person_id: s.assigned_person_id ?? null,
        estimated_effort: s.estimated_effort ?? null,
        notes: s.notes ?? '',
      }))
      if (assignSeatRoleMode === 'existing') {
        const idx = assignSeatRoleIndex
        if (idx >= 0 && idx < seatsPayload.length) seatsPayload[idx]!.assigned_person_id = personId
      } else {
        const newRole = (assignSeatNewRole || '').trim() || 'Role'
        seatsPayload.push({ role: newRole, assigned_person_id: personId, estimated_effort: null, notes: '' })
      }
      await apiPatch<Initiative>(`/initiatives/${assignInitiativeId}`, { seats: seatsPayload })
      onAssignmentChange?.(); setShowAssignSeat(false); setAssignInitiativeId(''); setAssignSeatNewRole('')
    } catch (e) { setAssignError(e instanceof Error ? e.message : 'Assign failed') } finally { setAssigning(false) }
  }

  const handleAssignToProject = async () => {
    if (!assignProjectId) return
    const proj = projects.find((p) => p.id === assignProjectId)
    if (!proj) return
    setAssignError(null); setAssigning(true)
    try {
      if (assignProjectRole === 'owner') {
        await apiPatch<Project>(`/projects/${assignProjectId}`, { owner_id: personId })
      } else {
        const current = proj.supporting_owner_ids ?? []
        const next = current.includes(personId) ? current : [...current, personId]
        await apiPatch<Project>(`/projects/${assignProjectId}`, { supporting_owner_ids: next })
      }
      onAssignmentChange?.(); setShowAssignProject(false); setAssignProjectId('')
    } catch (e) { setAssignError(e instanceof Error ? e.message : 'Assign failed') } finally { setAssigning(false) }
  }

  const handleAssignToTask = async () => {
    if (!assignTaskId) return
    setAssignError(null); setAssigning(true)
    try {
      await apiPatch<Task>(`/tasks/${assignTaskId}`, { assignee_id: personId })
      onAssignmentChange?.(); setShowAssignTask(false); setAssignTaskId('')
    } catch (e) { setAssignError(e instanceof Error ? e.message : 'Assign failed') } finally { setAssigning(false) }
  }

  if (loading) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0"><p className="text-slate-500 text-sm">Loading…</p></div>
  if (!person) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0"><p className="text-slate-500 text-sm">Person not found.</p><button type="button" onClick={onClose} className="mt-2 text-slate-400 hover:text-slate-200 text-sm">Close</button></div>
  const cap = capacityProfiles.find((cp) => cp.person_id === personId)
  const capacityStatus = getCapacityStatus(cap)
  const inputBase = 'w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm'

  // Current participation (derived from loaded data only)
  const initiativesOwned = initiatives.filter((i) => i.owner_id === personId)
  const seatsAssigned = initiatives.flatMap((i) => (i.seats ?? []).filter((s) => s.assigned_person_id === personId).map((s) => ({ initiative: i, role: s.role })))
  const projectsOwned = projects.filter((p) => p.owner_id === personId)
  const projectsSupporting = projects.filter((p) => Array.isArray(p.supporting_owner_ids) && p.supporting_owner_ids.includes(personId))
  const tasksAssigned = tasks.filter((t) => t.assignee_id === personId)
  const assetsOwned = assets.filter((a) => a.owner_id === personId)

  const statusBadgeClass = capacityStatus === 'Over capacity' ? 'bg-amber-500/20 text-amber-300 border-amber-500/50' : capacityStatus === 'Near capacity' ? 'bg-slate-500/20 text-slate-300 border-slate-500/50' : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50'

  return (
    <div className="flex-1 min-h-0 rounded-xl border border-slate-600 bg-slate-800/50 p-4 min-w-0 overflow-hidden flex flex-col">
      <div className="flex justify-between mb-3"><h3 className="text-sm font-medium text-slate-200">Person</h3><button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-200 text-sm">Close</button></div>
      {saveError && <p className="text-red-400 text-xs mb-2">{saveError}</p>}

      {/* Top summary strip */}
      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 mb-4">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <span className="font-semibold text-slate-100 truncate">{(form.name as string) || person.name || 'Unnamed'}</span>
          {(form.role as string) && <span className="text-slate-500 text-xs">· {(form.role as string)}</span>}
          {(form.relationship_type as string) && <span className="text-slate-500 text-xs">· {(form.relationship_type as string)}</span>}
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] uppercase tracking-wide border ${statusBadgeClass}`}>{capacityStatus}</span>
        </div>
        <p className="text-[13px] text-slate-300">{formatCapacitySummary(cap)}</p>
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-400">
          {cap && (cap.weekly_capacity_hours != null || cap.activeWeeklyHours != null) && (
            <>
              {cap.weekly_capacity_hours != null && <span>Weekly capacity: {cap.weekly_capacity_hours}h</span>}
              {cap.activeWeeklyHours != null && <span>Active: {cap.activeWeeklyHours}h</span>}
              {cap.capacityDelta != null && <span>Delta: {cap.capacityDelta > 0 ? `+${cap.capacityDelta}` : cap.capacityDelta}h</span>}
            </>
          )}
          {(!cap || (cap.weekly_capacity_hours == null && cap.activeWeeklyHours == null)) && <span>No capacity set</span>}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        <DetailSection title="Identity" defaultOpen={true}>
          <DetailField label="Name" value={(form.name as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, name: v }))} />
          <DetailField label="Contact info" value={(form.contact_info as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, contact_info: v }))} />
          <DetailField label="Role" value={(form.role as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, role: v }))} />
          <DetailField label="Relationship type" value={(form.relationship_type as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, relationship_type: v }))} />
        </DetailSection>
        {influenceLinkLists ? (
          <InfluencesLinksSection
            sourceKind="person"
            sourceId={personId}
            coreProfiles={influenceLinkLists.coreProfiles}
            perspectiveAgents={influenceLinkLists.perspectiveAgents}
            canonicalCoreProfileId={canonicalCoreProfileId}
          />
        ) : null}
        <DetailSection title="Capacity & load" defaultOpen={true}>
          <div className="space-y-1">
            <label className="block text-xs font-medium text-slate-400">Weekly capacity (hours)</label>
            <input type="number" value={capacityHours} onChange={(e) => setCapacityHours(e.target.value)} className={inputBase} />
          </div>
          {(cap?.activeWeeklyHours != null || cap?.weekly_capacity_hours != null) && (
            <div className="pt-2 space-y-1 text-sm text-slate-300">
              <p>{formatCapacitySummary(cap)}</p>
              {cap?.capacityDelta != null && <p className="text-xs text-slate-400">Delta: {cap.capacityDelta > 0 ? `+${cap.capacityDelta}h over` : `${cap.capacityDelta}h available`}</p>}
              <p className={`text-xs ${cap?.overcapacity ? 'text-amber-400' : 'text-slate-400'}`}>{capacityStatus}</p>
            </div>
          )}
        </DetailSection>
        <DetailSection title="Current participation" defaultOpen={true}>
          <div className="space-y-2 text-sm">
            <div className="flex flex-wrap gap-2 mb-2">
              <button type="button" onClick={() => { setAssignError(null); setShowAssignSeat(true); setAssignInitiativeId(''); setAssignSeatRoleMode('existing'); setAssignSeatRoleIndex(0); setAssignSeatNewRole('') }} className="px-2 py-1 rounded bg-slate-600 hover:bg-slate-500 text-slate-200 text-xs">+ Assign to seat</button>
              <button type="button" onClick={() => { setAssignError(null); setShowAssignProject(true); setAssignProjectId(''); setAssignProjectRole('owner') }} className="px-2 py-1 rounded bg-slate-600 hover:bg-slate-500 text-slate-200 text-xs">+ Assign to project</button>
              <button type="button" onClick={() => { setAssignError(null); setShowAssignTask(true); setAssignTaskId('') }} className="px-2 py-1 rounded bg-slate-600 hover:bg-slate-500 text-slate-200 text-xs">+ Assign to task</button>
            </div>
            {initiativesOwned.length > 0 && (
              <div>
                <span className="text-[11px] text-slate-500 uppercase block mb-1">Initiatives owned</span>
                <ul className="flex flex-wrap gap-1">
                  {initiativesOwned.map((i) => (
                    <li
                      key={i.id}
                      className="inline-flex items-center px-2 py-0.5 rounded bg-slate-700/60 text-slate-200 truncate max-w-[200px]"
                      title={veEntityDisplayStr(i.title) || i.id}
                    >
                      {veEntityDisplayStr(i.title) || i.id}{' '}
                      {veEntityDisplayStr(i.status) ? (
                        <span className="ml-1 text-[10px] text-slate-500">{veEntityDisplayStr(i.status)}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {seatsAssigned.length > 0 && (
              <div>
                <span className="text-[11px] text-slate-500 uppercase block mb-1">Seats assigned</span>
                <ul className="flex flex-wrap gap-1">
                  {seatsAssigned.map((s, idx) => (
                    <li
                      key={`${s.initiative.id}-${s.role}-${idx}`}
                      className="inline-flex items-center px-2 py-0.5 rounded bg-slate-700/60 text-slate-200 truncate max-w-[200px]"
                      title={`${s.role}: ${veEntityDisplayStr(s.initiative.title) || s.initiative.id}`}
                    >
                      {s.role} · {veEntityDisplayStr(s.initiative.title) || s.initiative.id}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(projectsOwned.length > 0 || projectsSupporting.length > 0) && (
              <div>
                <span className="text-[11px] text-slate-500 uppercase block mb-1">Projects</span>
                <ul className="flex flex-wrap gap-1">
                  {projectsOwned.map((p) => (
                    <li
                      key={p.id}
                      className="inline-flex items-center px-2 py-0.5 rounded bg-slate-700/60 text-slate-200 truncate max-w-[200px]"
                      title={veEntityDisplayStr(p.title) || p.id}
                    >
                      Owner: {veEntityDisplayStr(p.title) || p.id}{' '}
                      <span className="ml-1 text-[10px] text-slate-500">{veEntityDisplayStr(p.status)}</span>
                    </li>
                  ))}
                  {projectsSupporting.map((p) => (
                    <li
                      key={p.id}
                      className="inline-flex items-center px-2 py-0.5 rounded bg-slate-700/40 text-slate-300 truncate max-w-[200px]"
                      title={veEntityDisplayStr(p.title) || p.id}
                    >
                      Supporting: {veEntityDisplayStr(p.title) || p.id}{' '}
                      <span className="ml-1 text-[10px] text-slate-500">{veEntityDisplayStr(p.status)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {tasksAssigned.length > 0 && (
              <div>
                <span className="text-[11px] text-slate-500 uppercase block mb-1">Tasks assigned</span>
                <ul className="flex flex-wrap gap-1">
                  {tasksAssigned.map((t) => (
                    <li
                      key={t.id}
                      className="inline-flex items-center px-2 py-0.5 rounded bg-slate-700/60 text-slate-200 truncate max-w-[200px]"
                      title={veEntityDisplayStr(t.title) || t.id}
                    >
                      {veEntityDisplayStr(t.title) || t.id}{' '}
                      <span className="ml-1 text-[10px] text-slate-500">{veEntityDisplayStr(t.status)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {assetsOwned.length > 0 && (
              <div>
                <span className="text-[11px] text-slate-500 uppercase block mb-1">Assets owned</span>
                <ul className="flex flex-wrap gap-1">
                  {assetsOwned.map((a) => (
                    <li
                      key={a.id}
                      className="inline-flex items-center px-2 py-0.5 rounded bg-slate-700/60 text-slate-200 truncate max-w-[200px]"
                      title={veEntityDisplayStr(a.name) || a.id}
                    >
                      {veEntityDisplayStr(a.name) || a.id}{' '}
                      {veEntityDisplayStr(a.asset_type) ? (
                        <span className="ml-1 text-[10px] text-slate-500">{veEntityDisplayStr(a.asset_type)}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {initiativesOwned.length === 0 && seatsAssigned.length === 0 && projectsOwned.length === 0 && projectsSupporting.length === 0 && tasksAssigned.length === 0 && assetsOwned.length === 0 && (
              <p className="text-slate-500 text-sm">No initiatives, projects, tasks, or assets assigned (from loaded data).</p>
            )}
          </div>
        </DetailSection>
        <DetailSection title="Strengths / needs / wants" defaultOpen={false}>
          <DetailField label="Strengths" value={(form.strengths as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, strengths: v }))} textarea rows={2} />
          <DetailField label="Needs" value={(form.needs as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, needs: v }))} textarea rows={2} />
          <DetailField label="Wants" value={(form.wants as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, wants: v }))} textarea rows={2} />
          <DetailField label="Availability" value={(form.availability as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, availability: v }))} />
        </DetailSection>
        <DetailSection title="Notes" defaultOpen={false}>
          <DetailField label="Notes" value={(form.notes as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, notes: v }))} textarea rows={3} />
        </DetailSection>
        <MetadataSection data={{ id: person.id, created_at: person.created_at, updated_at: person.updated_at }} />
      </div>
      <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-slate-600">
        <button type="button" onClick={handleSave} disabled={saving} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm">Save</button>
        <button type="button" onClick={onClose} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">Cancel</button>
        <button type="button" onClick={() => setShowDeleteConfirm(true)} className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm">Delete</button>
      </div>
      {showDeleteConfirm && <ConfirmModal title="Delete person?" message="References (owner, assignee) will be cleared. Capacity profile will be removed. This cannot be undone." confirmLabel="Delete" onConfirm={handleDelete} onCancel={() => setShowDeleteConfirm(false)} />}

      {/* Assign to seat */}
      {showAssignSeat && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowAssignSeat(false)}>
          <div className="rounded-xl border border-slate-600 bg-slate-800 p-4 max-w-sm w-full shadow-xl space-y-3" onClick={(e) => e.stopPropagation()}>
            <h4 className="text-sm font-medium text-slate-200">Assign to seat</h4>
            {assignError && <p className="text-red-400 text-xs">{assignError}</p>}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Initiative</label>
              <select value={assignInitiativeId} onChange={(e) => setAssignInitiativeId(e.target.value)} className="w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm">
                <option value="">— Select —</option>
                {initiatives.map((i) => (
                  <option key={i.id} value={i.id}>{i.title || i.id}</option>
                ))}
              </select>
            </div>
            {assignInitiativeId && (() => {
              const init = initiatives.find((i) => i.id === assignInitiativeId)
              const seatList = Array.isArray(init?.seats) ? init!.seats : []
              return (
                <>
                  <div className="flex gap-2">
                    <label className="flex items-center gap-1 text-xs text-slate-400"><input type="radio" checked={assignSeatRoleMode === 'existing'} onChange={() => { setAssignSeatRoleMode('existing'); setAssignSeatRoleIndex(0) }} /> Existing role</label>
                    <label className="flex items-center gap-1 text-xs text-slate-400"><input type="radio" checked={assignSeatRoleMode === 'new'} onChange={() => setAssignSeatRoleMode('new')} /> New role</label>
                  </div>
                  {assignSeatRoleMode === 'existing' && seatList.length > 0 && (
                    <div>
                      <label className="block text-xs text-slate-400 mb-1">Role</label>
                      <select value={assignSeatRoleIndex} onChange={(e) => setAssignSeatRoleIndex(Number(e.target.value))} className="w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm">
                        {seatList.map((s, idx) => (
                          <option key={idx} value={idx}>{s.role || '(unnamed)'}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  {assignSeatRoleMode === 'new' && (
                    <div>
                      <label className="block text-xs text-slate-400 mb-1">Role label</label>
                      <input type="text" value={assignSeatNewRole} onChange={(e) => setAssignSeatNewRole(e.target.value)} placeholder="e.g. Lead" className="w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm" />
                    </div>
                  )}
                </>
              )
            })()}
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowAssignSeat(false)} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">Cancel</button>
              <button type="button" onClick={handleAssignToSeat} disabled={assigning || !assignInitiativeId || (assignSeatRoleMode === 'existing' && ((initiatives.find((i) => i.id === assignInitiativeId)?.seats ?? []).length === 0))} className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm">Assign</button>
            </div>
          </div>
        </div>
      )}

      {/* Assign to project */}
      {showAssignProject && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowAssignProject(false)}>
          <div className="rounded-xl border border-slate-600 bg-slate-800 p-4 max-w-sm w-full shadow-xl space-y-3" onClick={(e) => e.stopPropagation()}>
            <h4 className="text-sm font-medium text-slate-200">Assign to project</h4>
            {assignError && <p className="text-red-400 text-xs">{assignError}</p>}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Project</label>
              <select value={assignProjectId} onChange={(e) => setAssignProjectId(e.target.value)} className="w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm">
                <option value="">— Select —</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.title || p.id}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Role</label>
              <div className="flex gap-3">
                <label className="flex items-center gap-1 text-sm text-slate-300"><input type="radio" checked={assignProjectRole === 'owner'} onChange={() => setAssignProjectRole('owner')} /> Owner</label>
                <label className="flex items-center gap-1 text-sm text-slate-300"><input type="radio" checked={assignProjectRole === 'supporting'} onChange={() => setAssignProjectRole('supporting')} /> Supporting</label>
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowAssignProject(false)} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">Cancel</button>
              <button type="button" onClick={handleAssignToProject} disabled={assigning || !assignProjectId} className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm">Assign</button>
            </div>
          </div>
        </div>
      )}

      {/* Assign to task */}
      {showAssignTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowAssignTask(false)}>
          <div className="rounded-xl border border-slate-600 bg-slate-800 p-4 max-w-sm w-full shadow-xl space-y-3" onClick={(e) => e.stopPropagation()}>
            <h4 className="text-sm font-medium text-slate-200">Assign to task</h4>
            {assignError && <p className="text-red-400 text-xs">{assignError}</p>}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Task</label>
              <select value={assignTaskId} onChange={(e) => setAssignTaskId(e.target.value)} className="w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm">
                <option value="">— Select —</option>
                {tasks.map((t) => {
                  const proj = t.project_id ? projects.find((p) => p.id === t.project_id) : undefined
                  return (
                    <option key={t.id} value={t.id}>
                      {t.title || t.id}
                      {proj ? ` (${proj.title || proj.id})` : ' (no project)'}
                    </option>
                  )
                })}
              </select>
            </div>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setShowAssignTask(false)} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">Cancel</button>
              <button type="button" onClick={handleAssignToTask} disabled={assigning || !assignTaskId} className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm">Assign</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function AssetDetailPanel({ assetId, ideas, initiatives, projects, persons, onClose, onSaved, apiGet, apiPatch, apiDelete }: { assetId: string; ideas: Idea[]; initiatives: Initiative[]; projects: Project[]; persons: Person[]; onClose: () => void; onSaved: () => void; apiGet: <T>(path: string) => Promise<T>; apiPatch: <T>(path: string, body: unknown) => Promise<T>; apiDelete: (path: string) => Promise<void> }) {
  const [asset, setAsset] = useState<Asset | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [linkedIdeaIds, setLinkedIdeaIds] = useState<string[]>([])
  const [linkedInitiativeIds, setLinkedInitiativeIds] = useState<string[]>([])
  const [linkedProjectIds, setLinkedProjectIds] = useState<string[]>([])
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  useEffect(() => {
    let c = false
    setLoading(true)
    apiGet<Asset>(`/assets/${assetId}`).then((data) => {
      if (!c) {
        setAsset(data)
        setForm({ name: data.name, asset_type: data.asset_type ?? '', owner_id: data.owner_id ?? '', status: data.status ?? '', availability: data.availability ?? '', cost: data.cost ?? '', time_availability: data.time_availability ?? '', notes: data.notes ?? '' })
        setLinkedIdeaIds(Array.isArray(data.linked_idea_ids) ? data.linked_idea_ids : [])
        setLinkedInitiativeIds(Array.isArray(data.linked_initiative_ids) ? data.linked_initiative_ids : [])
        setLinkedProjectIds(Array.isArray(data.linked_project_ids) ? data.linked_project_ids : [])
      }
    }).catch(() => { if (!c) setAsset(null) }).finally(() => { if (!c) setLoading(false) })
    return () => { c = true }
  }, [assetId, apiGet])
  const handleSave = async () => {
    setSaveError(null); setSaving(true)
    try {
      await apiPatch<Asset>(`/assets/${assetId}`, { name: form.name, asset_type: form.asset_type, owner_id: (form.owner_id as string) || null, status: form.status, availability: form.availability, cost: form.cost, time_availability: form.time_availability, linked_idea_ids: linkedIdeaIds, linked_initiative_ids: linkedInitiativeIds, linked_project_ids: linkedProjectIds, notes: form.notes })
      onSaved(); onClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Save failed') } finally { setSaving(false) }
  }
  const handleArchive = async () => {
    try {
      await apiPatch<Asset>(`/assets/${assetId}`, { status: 'Archived' })
      onSaved(); setShowArchiveConfirm(false); onClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Archive failed') } finally { setSaving(false) }
  }
  const handleDelete = async () => {
    try {
      await apiDelete(`/assets/${assetId}`)
      onSaved(); setShowDeleteConfirm(false); onClose()
    } catch (e) { setSaveError(e instanceof Error ? e.message : 'Delete failed') }
  }
  if (loading) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0"><p className="text-slate-500 text-sm">Loading…</p></div>
  if (!asset) return <div className="flex-1 rounded-xl border border-slate-600 bg-slate-800/50 p-6 min-w-0"><p className="text-slate-500 text-sm">Asset not found.</p><button type="button" onClick={onClose} className="mt-2 text-slate-400 hover:text-slate-200 text-sm">Close</button></div>

  const assetName = (form.name as string) ?? asset.name ?? ''
  const assetType = (form.asset_type as string) ?? asset.asset_type ?? ''
  const assetStatus = (form.status as string) ?? asset.status ?? ''
  const availability = (form.availability as string) ?? asset.availability ?? ''
  const timeAvailability = (form.time_availability as string) ?? asset.time_availability ?? ''
  const ownerId = (form.owner_id as string) ?? asset.owner_id ?? ''
  const ownerName = ownerId ? persons.find((p) => p.id === ownerId)?.name ?? '' : ''

  const requiredByInitiatives = initiatives.filter((i) => Array.isArray(i.required_assets) && i.required_assets.includes(assetId))
  const requiredByProjects = projects.filter((p) => Array.isArray(p.required_assets) && p.required_assets.includes(assetId))
  const linkedIdeas = linkedIdeaIds.map((id) => ideas.find((i) => i.id === id)).filter(Boolean) as Idea[]
  const linkedInits = linkedInitiativeIds.map((id) => initiatives.find((i) => i.id === id)).filter(Boolean) as Initiative[]
  const linkedProjs = linkedProjectIds.map((id) => projects.find((p) => p.id === id)).filter(Boolean) as Project[]

  const linkCounts = { ideas: linkedIdeaIds.length, initiatives: linkedInitiativeIds.length, projects: linkedProjectIds.length }
  const usedInParts: string[] = []
  if (linkCounts.ideas > 0) usedInParts.push(`${linkCounts.ideas} idea${linkCounts.ideas !== 1 ? 's' : ''}`)
  if (linkCounts.initiatives > 0) usedInParts.push(`${linkCounts.initiatives} initiative${linkCounts.initiatives !== 1 ? 's' : ''}`)
  if (linkCounts.projects > 0) usedInParts.push(`${linkCounts.projects} project${linkCounts.projects !== 1 ? 's' : ''}`)
  const usedInLine = usedInParts.length > 0 ? `Used in: ${usedInParts.join(', ')}` : null
  const requiredByParts: string[] = []
  if (requiredByInitiatives.length > 0) requiredByParts.push(`${requiredByInitiatives.length} initiative${requiredByInitiatives.length !== 1 ? 's' : ''}`)
  if (requiredByProjects.length > 0) requiredByParts.push(`${requiredByProjects.length} project${requiredByProjects.length !== 1 ? 's' : ''}`)
  const requiredByLine = requiredByParts.length > 0 ? `Required by: ${requiredByParts.join(', ')}` : null
  const availabilityLine = [availability, timeAvailability].filter(Boolean).length > 0
    ? `Availability: ${[availability, timeAvailability].filter(Boolean).join(' · ') || '—'}`
    : null
  const hasRequiredBy = requiredByInitiatives.length > 0 || requiredByProjects.length > 0
  const activeInitiative = requiredByInitiatives.some((i) => ['Active', 'Approved'].includes(i.status))
  const activeProject = requiredByProjects.some((p) => ['Active', 'In Progress'].includes(p.status))
  const operationalInterpretation = (() => {
    if (hasRequiredBy) {
      return activeInitiative || activeProject ? 'Required by active work' : 'Required by initiative(s) / project(s)'
    }
    if (linkCounts.ideas + linkCounts.initiatives + linkCounts.projects > 0) return 'Linked for context'
    return 'Unused asset'
  })()

  const statusOptions = ['', 'Active', 'Archived', 'Unavailable'].filter(Boolean).map((s) => ({ value: s, label: s }))
  return (
    <div className="flex-1 min-h-0 rounded-xl border border-slate-600 bg-slate-800/50 p-4 min-w-0 overflow-hidden flex flex-col">
      <div className="flex justify-between mb-3"><h3 className="text-sm font-medium text-slate-200">Asset</h3><button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-200 text-sm">Close</button></div>
      {saveError && <p className="text-red-400 text-xs mb-2">{saveError}</p>}
      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 mb-4">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <span className="font-semibold text-slate-100 truncate">{assetName || 'Unnamed asset'}</span>
          {assetType && <span className="text-slate-500 text-xs">· {assetType}</span>}
          {assetStatus && <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] uppercase tracking-wide border border-slate-500/60 text-slate-300 bg-slate-950/30">{assetStatus}</span>}
        </div>
        <p className="text-[13px] text-slate-300">{operationalInterpretation}</p>
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-400">
          {usedInLine && <span>{usedInLine}</span>}
          {requiredByLine && <span>{requiredByLine}</span>}
          {availabilityLine && <span>{availabilityLine}</span>}
          {ownerName && <span>Owner: {ownerName}</span>}
          {!usedInLine && !requiredByLine && !availabilityLine && !ownerName && <span>No usage or availability set</span>}
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        <DetailSection title="Identity" defaultOpen={true}>
          <DetailField label="Name" value={(form.name as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, name: v }))} />
          <DetailField label="Type" value={(form.asset_type as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, asset_type: v }))} placeholder="e.g. Tool, Document" />
          <DetailField label="Status" value={(form.status as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, status: v }))} options={[{ value: '', label: '—' }, ...statusOptions]} />
        </DetailSection>
        <DetailSection title="Operational use" defaultOpen={true}>
          <div className="space-y-3">
            <div>
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wide block mb-1">Required by</span>
              {!hasRequiredBy ? (
                <p className="text-slate-500 text-sm">Not required by any initiative or project (from loaded data).</p>
              ) : (
                <ul className="space-y-2">
                  {requiredByInitiatives.length > 0 && (
                    <>
                      <li className="text-[11px] text-slate-500 uppercase">Initiatives</li>
                      {requiredByInitiatives.map((i) => (
                        <li key={i.id} className="text-sm text-slate-200 flex items-center gap-2 pl-2">
                          <span className="truncate">{veEntityDisplayStr(i.title) || i.id}</span>
                          {veEntityDisplayStr(i.status) ? (
                            <span className="shrink-0 text-[11px] text-slate-500 uppercase">{veEntityDisplayStr(i.status)}</span>
                          ) : null}
                        </li>
                      ))}
                    </>
                  )}
                  {requiredByProjects.length > 0 && (
                    <>
                      <li className="text-[11px] text-slate-500 uppercase mt-1">Projects</li>
                      {requiredByProjects.map((p) => (
                        <li key={p.id} className="text-sm text-slate-200 flex items-center gap-2 pl-2">
                          <span className="truncate">{veEntityDisplayStr(p.title) || p.id}</span>
                          {veEntityDisplayStr(p.status) ? (
                            <span className="shrink-0 text-[11px] text-slate-500 uppercase">{veEntityDisplayStr(p.status)}</span>
                          ) : null}
                        </li>
                      ))}
                    </>
                  )}
                </ul>
              )}
            </div>
            <div>
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wide block mb-1">Linked to ideas</span>
              {linkedIdeas.length === 0 ? (
                <p className="text-slate-500 text-sm">None linked</p>
              ) : (
                <p className="text-slate-300 text-sm">
                  {linkedIdeas.map((i) => veEntityDisplayStr(i.title) || i.id).join(', ')}
                </p>
              )}
              <EntityMultiSelect
                label="Edit links"
                selectedIds={linkedIdeaIds}
                onChange={setLinkedIdeaIds}
                options={ideas}
                getLabel={(i) => veEntityDisplayStr((i as Idea).title) || (i as Idea).id}
                placeholder="Search ideas…"
              />
            </div>
            <div>
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wide block mb-1">Linked to initiatives</span>
              {linkedInits.length === 0 ? (
                <p className="text-slate-500 text-sm">None linked</p>
              ) : (
                <p className="text-slate-300 text-sm">
                  {linkedInits
                    .map((i) => {
                      const t = veEntityDisplayStr(i.title) || i.id
                      const st = veEntityDisplayStr(i.status)
                      return st ? `${t} (${st})` : t
                    })
                    .join(', ')}
                </p>
              )}
              <EntityMultiSelect
                label="Edit links"
                selectedIds={linkedInitiativeIds}
                onChange={setLinkedInitiativeIds}
                options={initiatives}
                getLabel={(i) => veEntityDisplayStr((i as Initiative).title) || (i as Initiative).id}
                placeholder="Search initiatives…"
              />
            </div>
            <div>
              <span className="text-xs font-medium text-slate-400 uppercase tracking-wide block mb-1">Linked to projects</span>
              {linkedProjs.length === 0 ? (
                <p className="text-slate-500 text-sm">None linked</p>
              ) : (
                <p className="text-slate-300 text-sm">
                  {linkedProjs
                    .map((proj) => {
                      const t = veEntityDisplayStr(proj.title) || proj.id
                      const st = veEntityDisplayStr(proj.status)
                      return st ? `${t} (${st})` : t
                    })
                    .join(', ')}
                </p>
              )}
              <EntityMultiSelect
                label="Edit links"
                selectedIds={linkedProjectIds}
                onChange={setLinkedProjectIds}
                options={projects}
                getLabel={(proj) => veEntityDisplayStr((proj as Project).title) || (proj as Project).id}
                placeholder="Search projects…"
              />
            </div>
          </div>
        </DetailSection>
        <DetailSection title="Availability & access" defaultOpen={false}>
          <DetailField label="Owner" value={(form.owner_id as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, owner_id: v }))} options={[{ value: '', label: 'None' }, ...persons.map((p) => ({ value: p.id, label: veEntityDisplayStr(p.name) || p.id }))]} />
          <DetailField label="Availability" value={(form.availability as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, availability: v }))} placeholder="e.g. Shared, Dedicated" />
          <DetailField label="Time availability" value={(form.time_availability as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, time_availability: v }))} placeholder="e.g. Business hours, Always" />
          <DetailField label="Cost" value={(form.cost as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, cost: v }))} />
        </DetailSection>
        <DetailSection title="Notes" defaultOpen={false}>
          <DetailField label="Notes" value={(form.notes as string) ?? ''} onChange={(v) => setForm((p) => ({ ...p, notes: v }))} textarea rows={3} />
        </DetailSection>
        <MetadataSection data={{ id: asset.id, owner_id: asset.owner_id, created_at: asset.created_at, updated_at: asset.updated_at }} />
      </div>
      <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-slate-600">
        <button type="button" onClick={handleSave} disabled={saving} className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm">Save</button>
        <button type="button" onClick={onClose} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">Cancel</button>
        <button type="button" onClick={() => setShowArchiveConfirm(true)} className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm">Archive</button>
        <button type="button" onClick={() => setShowDeleteConfirm(true)} className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm">Delete</button>
      </div>
      {showArchiveConfirm && <ConfirmModal title="Archive asset?" message="Set status to Archived." confirmLabel="Archive" variant="warning" onConfirm={handleArchive} onCancel={() => setShowArchiveConfirm(false)} />}
      {showDeleteConfirm && <ConfirmModal title="Delete asset?" message="This cannot be undone." confirmLabel="Delete" onConfirm={handleDelete} onCancel={() => setShowDeleteConfirm(false)} />}
    </div>
  )
}

export function VisionExecutionView({
  initialSelection,
  councilIdeaLabelsRef,
  councilVeEntityBundleRef,
  onCouncilIdeaLiveLabelsUpdated,
  focusTabRequest,
  onFocusTabRequestConsumed,
  onVeSelectionChange,
  recognitionUserId,
  councilServerWriteNonce = 0,
  radarScrollBucketRequest = null,
  onRadarScrollBucketConsumed,
}: {
  initialSelection?: VESelection | null
  councilIdeaLabelsRef?: MutableRefObject<CouncilIdeaLabelsSnapshot | null>
  /** Live ideas/projects/tasks for council growth-triad (off vision map tab). */
  councilVeEntityBundleRef?: MutableRefObject<VisionMapEntityBundle | null>
  /** Bumps when the open idea editor updates council snapshot (for scoped-thread banner label). */
  onCouncilIdeaLiveLabelsUpdated?: () => void
  /** When set, switches top tab once (e.g. from vision map triad). Not persisted. */
  focusTabRequest?: VEWorkspaceTabId | null
  onFocusTabRequestConsumed?: () => void
  /** Keeps App `veSelection` aligned with open detail / list context (Pass 1). */
  onVeSelectionChange?: (sel: VESelection | null) => void
  /** Optional account user id for recognition `decisions.user_id`. */
  recognitionUserId?: string | null
  /** Increment when council stream reports a server-side VE write (integration or Lane A) so open detail panels refetch. */
  councilServerWriteNonce?: number
  /** When set with Radar tab open, scroll to `ve-radar-bucket-*` once then clear. */
  radarScrollBucketRequest?: VeRadarBucketId | null
  onRadarScrollBucketConsumed?: () => void
} = {}) {
  const [tab, setTab] = useState<TabId>('execution')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (focusTabRequest == null) return
    setTab(focusTabRequest)
    onFocusTabRequestConsumed?.()
  }, [focusTabRequest, onFocusTabRequestConsumed])

  // Data
  const [coreProfiles, setCoreProfiles] = useState<CoreProfile[]>([])
  const [ideas, setIdeas] = useState<Idea[]>([])
  const [initiatives, setInitiatives] = useState<Initiative[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [persons, setPersons] = useState<Person[]>([])
  const [capacityProfiles, setCapacityProfiles] = useState<CapacityProfile[]>([])
  const [assets, setAssets] = useState<Asset[]>([])

  useEffect(() => {
    if (!councilVeEntityBundleRef) return
    councilVeEntityBundleRef.current = { ideas, initiatives, projects, tasks }
  }, [councilVeEntityBundleRef, ideas, initiatives, projects, tasks])

  const veGraphData = useVisionExecutionGraphDataOptional()
  useEffect(() => {
    if (!veGraphData) return
    veGraphData.setSnapshot({
      coreProfiles,
      ideas,
      initiatives,
      projects,
      tasks,
      persons,
      assets,
      capacityProfiles,
    })
    return () => {
      veGraphData.setSnapshot(null)
    }
  }, [veGraphData, coreProfiles, ideas, initiatives, projects, tasks, persons, assets, capacityProfiles])

  const [loading, setLoading] = useState(false)
  const [_selectedId, setSelectedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showCreateProject, setShowCreateProject] = useState(false)
  const [showCreateTask, setShowCreateTask] = useState(false)
  const [detailInitiativeId, setDetailInitiativeId] = useState<string | null>(null)
  const [detailIdeaId, setDetailIdeaId] = useState<string | null>(null)
  const [detailProjectId, setDetailProjectId] = useState<string | null>(null)
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null)
  const [detailPersonId, setDetailPersonId] = useState<string | null>(null)
  const [detailAssetId, setDetailAssetId] = useState<string | null>(null)
  const [perspectiveAgents, setPerspectiveAgents] = useState<PerspectiveAgent[]>([])

  useEffect(() => {
    try {
      const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(PERSPECTIVE_AGENTS_STORAGE_KEY) : null
      if (raw) {
        const parsed = JSON.parse(raw) as unknown
        if (Array.isArray(parsed) && parsed.length > 0) {
          const normalized = normalizeStoredPerspectiveAgents(parsed as PerspectiveAgent[])
          setPerspectiveAgents(normalized)
          try {
            if (typeof localStorage !== 'undefined') {
              localStorage.setItem(PERSPECTIVE_AGENTS_STORAGE_KEY, JSON.stringify(normalized))
            }
          } catch {
            /* ignore */
          }
          return
        }
      }
    } catch {
      /* ignore */
    }
    setPerspectiveAgents(BUILT_IN_PERSPECTIVES)
  }, [])

  const handlePerspectiveAgentsChange = useCallback((next: PerspectiveAgent[]) => {
    setPerspectiveAgents(next)
    try {
      if (typeof localStorage !== 'undefined') localStorage.setItem(PERSPECTIVE_AGENTS_STORAGE_KEY, JSON.stringify(next))
    } catch {
      /* ignore */
    }
  }, [])

  const influenceListBundles = useMemo(() => {
    const multi = coreProfiles.length > 1
    const cid = canonicalCoreProfileId(coreProfiles)
    return {
      coreProfiles: coreProfiles.map((p) => ({
        id: p.id,
        label: coreProfileInfluencePickLabel(p, cid, multi),
      })),
      perspectiveAgents: perspectiveAgents.map((a) => ({ id: a.id, label: a.name })),
    }
  }, [coreProfiles, perspectiveAgents])

  const veCanonicalCoreProfileId = useMemo(() => canonicalCoreProfileId(coreProfiles), [coreProfiles])

  const clearVeFocus = useVisionExecutionFocusOptional()?.clearFocus
  useEffect(() => {
    clearVeFocus?.()
  }, [detailInitiativeId, detailIdeaId, clearVeFocus])

  useEffect(() => {
    if (!councilIdeaLabelsRef) return
    if (!detailIdeaId) {
      councilIdeaLabelsRef.current = null
    }
    // Live title/summary/description/status are pushed from IdeaDetailPanel (unsaved edits included).
  }, [detailIdeaId, councilIdeaLabelsRef])

  const EXECUTION_VIEW_STORAGE_KEY = 'zenaf-execution-view-mode'
  const [executionViewMode, setExecutionViewMode] = useState<ProjectsViewMode>(() => {
    try {
      if (typeof localStorage !== 'undefined') {
        const stored = localStorage.getItem(EXECUTION_VIEW_STORAGE_KEY)
        if (stored === 'timeline' || stored === 'list') return stored
      }
    } catch {
      /* ignore */
    }
    return 'timeline'
  })
  useEffect(() => {
    try {
      if (typeof localStorage !== 'undefined') localStorage.setItem(EXECUTION_VIEW_STORAGE_KEY, executionViewMode)
    } catch {
      /* ignore */
    }
  }, [executionViewMode])
  const [executionListExpandedInitiatives, setExecutionListExpandedInitiatives] = useState<string[]>([])
  const [executionListExpandedProjects, setExecutionListExpandedProjects] = useState<string[]>([])
  const toggleExecutionListInitiative = useCallback((id: string) => {
    setExecutionListExpandedInitiatives((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }, [])
  const toggleExecutionListProject = useCallback((id: string) => {
    setExecutionListExpandedProjects((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }, [])

  // Meeting Capture: paste / upload → extract → staging → review → commit
  const STAGING_STORAGE_KEY = 'zenaf-meeting-staging'
  const SHOW_REVIEW_STORAGE_KEY = 'zenaf-meeting-show-review'
  const [meetingNotes, setMeetingNotes] = useState('')
  const [extractResult, setExtractResult] = useState<ExtractMeetingResponse | null>(null)
  const [meetingCaptureView, setMeetingCaptureView] = useState<'structured' | 'harvest'>('structured')
  const [extractLoading, setExtractLoading] = useState(false)
  const meetingExtractAbortRef = useRef<AbortController | null>(null)
  const [useExternalAiExtraction, setUseExternalAiExtraction] = useState(false)
  const [externalAiEngine, setExternalAiEngine] = useState('')
  const [meetingExtractLlmRows, setMeetingExtractLlmRows] = useState<ProviderStatusRow[] | null>(null)
  const [washDataForCall, setWashDataForCall] = useState(true)
  const [globalExtractionContext, setGlobalExtractionContext] = useState<GlobalExtractionContext | null>(null)
  const [stagingArea, setStagingArea] = useState<StagingArea | null>(() => {
    try {
      const raw = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(STAGING_STORAGE_KEY) : null
      return raw ? (JSON.parse(raw) as StagingArea) : null
    } catch {
      return null
    }
  })
  const [showReviewExtraction, setShowReviewExtraction] = useState(() => {
    try {
      return typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(SHOW_REVIEW_STORAGE_KEY) === 'true' : false
    } catch {
      return false
    }
  })
  useEffect(() => {
    if (typeof sessionStorage === 'undefined') return
    if (stagingArea != null) sessionStorage.setItem(STAGING_STORAGE_KEY, JSON.stringify(stagingArea))
    else sessionStorage.removeItem(STAGING_STORAGE_KEY)
  }, [stagingArea])
  useEffect(() => {
    if (typeof sessionStorage === 'undefined') return
    if (showReviewExtraction) sessionStorage.setItem(SHOW_REVIEW_STORAGE_KEY, 'true')
    else sessionStorage.removeItem(SHOW_REVIEW_STORAGE_KEY)
  }, [showReviewExtraction])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const d = await fetchLLMSettings()
        if (!cancelled && d.providers?.length) setMeetingExtractLlmRows(d.providers)
      } catch {
        if (!cancelled) setMeetingExtractLlmRows(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const meetingExternalEngineSelectOptions = useMemo(() => {
    if (meetingExtractLlmRows?.length) return meetingExternalEngineOptionsFromProviders(meetingExtractLlmRows)
    return fallbackMeetingExternalEngineOptions()
  }, [meetingExtractLlmRows])

  const [commitLoading, setCommitLoading] = useState(false)
  const [committingItemId, setCommittingItemId] = useState<string | null>(null)
  const [commitError, setCommitError] = useState<string | null>(null)
  const [workspaceUsers, setWorkspaceUsers] = useState<WorkspaceDirectoryUser[]>([])
  const [workspaceMessages, setWorkspaceMessages] = useState<WorkspaceMessageRow[]>([])
  const [workspaceMessageBox, setWorkspaceMessageBox] = useState<'inbox' | 'sent'>('inbox')
  const [workspaceMessagesLoading, setWorkspaceMessagesLoading] = useState(false)
  const [workspaceUnreadCount, setWorkspaceUnreadCount] = useState(0)
  const [expandedWorkspaceMessageId, setExpandedWorkspaceMessageId] = useState<string | null>(null)
  const [sendToModal, setSendToModal] = useState<null | { sectionKey: StagingArraySectionKey; item: StagedItem }>(null)
  const [sendToRecipientId, setSendToRecipientId] = useState('')
  const [sendToNote, setSendToNote] = useState('')
  const [sendToSeatRequestId, setSendToSeatRequestId] = useState('')
  const [sendToCapabilityOfferId, setSendToCapabilityOfferId] = useState('')
  const [sendToLoading, setSendToLoading] = useState(false)
  const [sendToError, setSendToError] = useState<string | null>(null)
  const [appendNoteModal, setAppendNoteModal] = useState<null | { sectionKey: StagingArraySectionKey; item: StagedItem }>(
    null
  )
  const [appendNoteSaving, setAppendNoteSaving] = useState(false)
  const [appendNoteError, setAppendNoteError] = useState<string | null>(null)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const meetingFileInputRef = useRef<HTMLInputElement>(null)

  // Assisted chunk mode: per-chunk status and results for retry-failed (processing view only — not a domain entity)
  type ChunkStatus = 'pending' | 'running' | 'succeeded' | 'failed'
  type ChunkResultEntry = { chunkId: string; status: ChunkStatus; response?: ExtractMeetingResponse; error?: string }
  const [chunkModeChunks, setChunkModeChunks] = useState<ManualProcessingChunk[] | null>(null)
  const [chunkModeResults, setChunkModeResults] = useState<ChunkResultEntry[]>([])
  /** Index of chunk currently awaiting POST /extract-meeting (for progress copy + dev timing). */
  const [chunkRunFocus, setChunkRunFocus] = useState<{ chunkIndex: number; startedAt: number } | null>(null)
  /** Chunked extract UX copy: local interactive-sized chunks vs external ~single-call-budget passes. */
  const [chunkProgressExtractKind, setChunkProgressExtractKind] = useState<'local' | 'external_budget'>('local')
  /** Last successful extract path (operator / trace alignment); cleared when a new extract starts. */
  const [meetingExtractPathDiag, setMeetingExtractPathDiag] = useState<{
    engine: 'external' | 'local'
    externalSingleCall: boolean
    transcriptChars: number
    thresholdChars: number
    extractCalls: number
    documentBudgetApplied: boolean
  } | null>(null)
  const chunkModeChunksRef = useRef<ManualProcessingChunk[] | null>(null)
  const chunkModeResultsRef = useRef<ChunkResultEntry[]>([])
  useEffect(() => {
    chunkModeChunksRef.current = chunkModeChunks
    chunkModeResultsRef.current = chunkModeResults
  }, [chunkModeChunks, chunkModeResults])
  const lastMeetingExtractTraceRef = useRef<AiActionTrace | null>(null)

  const dismissMeetingExtractTraceIfPending = useCallback(() => {
    const t = lastMeetingExtractTraceRef.current
    if (t) {
      recordMeetingExtractionTraceOutcome(t, 'dismissed')
      lastMeetingExtractTraceRef.current = null
    }
  }, [])

  const [workspaceIdentity, setWorkspaceIdentity] = useState<WorkspaceIdentityStatusResponse | null>(null)
  const [workspaceIdentityLoading, setWorkspaceIdentityLoading] = useState(false)
  const [workspaceScanBusy, setWorkspaceScanBusy] = useState(false)
  const [workspaceScanRootsUser, setWorkspaceScanRootsUser] = useState<string[]>(() => parseScanRootsFromStorage())
  const [workspaceScanRootDraft, setWorkspaceScanRootDraft] = useState('')
  const [workspacePickFolderBusy, setWorkspacePickFolderBusy] = useState(false)

  useEffect(() => {
    saveScanRootsToStorage(workspaceScanRootsUser)
  }, [workspaceScanRootsUser])

  const commitWorkspaceScanRootDraft = useCallback(() => {
    const t = workspaceScanRootDraft.trim()
    if (!t) return
    const norm = t.replace(/\/+$/, '')
    setWorkspaceScanRootsUser((prev) => {
      const low = norm.toLowerCase()
      if (prev.some((p) => p.replace(/\/+$/, '').toLowerCase() === low)) return prev
      return [...prev, norm]
    })
    setWorkspaceScanRootDraft('')
  }, [workspaceScanRootDraft])

  const pickWorkspaceFolderFromOs = useCallback(async () => {
    setWorkspacePickFolderBusy(true)
    setError(null)
    const ac = new AbortController()
    const tid = window.setTimeout(() => ac.abort(), 480_000)
    try {
      const res = await fetch(`${VISION_EXECUTION_API}/workspace-identity/pick-directory`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
        signal: ac.signal,
      })
      if (!res.ok) throw new Error(await apiErrorText(res))
      const data = (await res.json()) as { ok: boolean; path: string | null; cancelled: boolean }
      if (data.cancelled || !data.path?.trim()) return
      const norm = data.path.trim().replace(/\/+$/, '')
      setWorkspaceScanRootsUser((prev) => {
        const low = norm.toLowerCase()
        if (prev.some((p) => p.replace(/\/+$/, '').toLowerCase() === low)) return prev
        return [...prev, norm]
      })
    } catch (e: unknown) {
      const name = e && typeof e === 'object' && 'name' in e ? String((e as { name: string }).name) : ''
      if (name === 'AbortError') {
        setError(
          'Folder picker request timed out. Check for a folder dialog hidden behind other windows, or restart the Zenaf API if the server stopped responding.',
        )
      } else {
        setError(e instanceof Error ? e.message : 'Could not open folder picker')
      }
    } finally {
      window.clearTimeout(tid)
      setWorkspacePickFolderBusy(false)
    }
  }, [])

  const refreshWorkspaceIdentityFromServer = useCallback(async () => {
    setWorkspaceIdentityLoading(true)
    try {
      const data = await apiGet<WorkspaceIdentityStatusResponse>('/workspace-identity')
      setWorkspaceIdentity(data)
      applyWorkspaceIdentityGetToSession(data)
    } catch {
      setWorkspaceIdentity(null)
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.removeItem(WORKSPACE_PACKET_SESSION_KEY)
        sessionStorage.removeItem(WORKSPACE_IDENTITY_BRANCH_SESSION_KEY)
      }
    } finally {
      setWorkspaceIdentityLoading(false)
    }
  }, [])

  useEffect(() => {
    if (tab !== 'meeting_capture') return
    void refreshWorkspaceIdentityFromServer()
  }, [tab, refreshWorkspaceIdentityFromServer])

  const runWorkspaceIdentityScan = useCallback(
    async (mode: 'deep_initial' | 'light_refresh') => {
      setWorkspaceScanBusy(true)
      setError(null)
      try {
        const roots = workspaceScanRootsUser.length > 0 ? workspaceScanRootsUser : []
        await apiPost('/workspace-identity/scan', { roots, mode })
        await refreshWorkspaceIdentityFromServer()
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Workspace identity scan failed')
      } finally {
        setWorkspaceScanBusy(false)
      }
    },
    [refreshWorkspaceIdentityFromServer, workspaceScanRootsUser],
  )

  const workspaceMirrorLines = useMemo(
    () => workspacePacketSurfaceLines(workspaceIdentity?.workspacePacket ?? null),
    [workspaceIdentity],
  )

  const effectiveWorkspaceScanRoots = useMemo(() => {
    if (workspaceScanRootsUser.length > 0) return workspaceScanRootsUser
    const d = workspaceIdentity?.defaultScanRoot?.trim()
    return d ? [d] : []
  }, [workspaceScanRootsUser, workspaceIdentity?.defaultScanRoot])

  const [radarData, setRadarData] = useState<RadarResponse | null>(null)
  const [radarLoading, setRadarLoading] = useState(false)
  const [seatRequests, setSeatRequests] = useState<SeatRequestRecord[]>([])
  const [capabilityOffers, setCapabilityOffers] = useState<CapabilityOfferRecord[]>([])
  const [selectedSeatRequestId, setSelectedSeatRequestId] = useState<string | null>(null)
  const [selectedCapabilityOfferId, setSelectedCapabilityOfferId] = useState<string | null>(null)
  const [seatCandidates, setSeatCandidates] = useState<CandidateOffer[]>([])
  const [offerCandidates, setOfferCandidates] = useState<CandidateRequest[]>([])
  const [materialRequests, setMaterialRequests] = useState<MaterialRequestRecord[]>([])
  const [materialOffers, setMaterialOffers] = useState<MaterialOfferRecord[]>([])
  const [selectedMaterialRequestId, setSelectedMaterialRequestId] = useState<string | null>(null)
  const [selectedMaterialOfferId, setSelectedMaterialOfferId] = useState<string | null>(null)
  const [materialRequestCandidates, setMaterialRequestCandidates] = useState<MaterialCandidateOffer[]>([])
  const [materialOfferCandidates, setMaterialOfferCandidates] = useState<MaterialCandidateRequest[]>([])
  const [matchingLoading, setMatchingLoading] = useState(false)
  const [seatForm, setSeatForm] = useState({
    title: '',
    summary: '',
    context_type: '',
    role_tags_csv: '',
    capability_tags_csv: '',
    availability_window: '',
    commitment_type: '',
    collaboration_mode: '',
    timezone_pref: '',
    is_active: true,
  })
  const [offerForm, setOfferForm] = useState({
    title: '',
    summary: '',
    role_tags_csv: '',
    capability_tags_csv: '',
    availability_window: '',
    commitment_type: '',
    collaboration_mode: '',
    timezone_pref: '',
    is_active: true,
  })
  const [materialRequestForm, setMaterialRequestForm] = useState({
    title: '',
    material_type: '',
    resource_nature: '',
    category_tags_csv: '',
    quantity_needed: '',
    quantity_unit: '',
    availability_start: '',
    availability_end: '',
    condition_min: '',
    access_mode: '',
    location_region: '',
    cost_band_max: '',
  })
  const [materialOfferForm, setMaterialOfferForm] = useState({
    title: '',
    material_type: '',
    resource_nature: '',
    category_tags_csv: '',
    quantity_available: '',
    quantity_unit: '',
    availability_start: '',
    availability_end: '',
    condition_state: '',
    access_mode: '',
    location_region: '',
    cost_band: '',
  })
  const [seatConsentVersion, setSeatConsentVersion] = useState('')
  const [seatShareUntil, setSeatShareUntil] = useState('')
  const [offerConsentVersion, setOfferConsentVersion] = useState('')
  const [offerShareUntil, setOfferShareUntil] = useState('')
  const [materialRequestConsentVersion, setMaterialRequestConsentVersion] = useState('')
  const [materialRequestShareUntil, setMaterialRequestShareUntil] = useState('')
  const [materialOfferConsentVersion, setMaterialOfferConsentVersion] = useState('')
  const [materialOfferShareUntil, setMaterialOfferShareUntil] = useState('')

  const parseTagCsv = (value: string): string[] =>
    value.split(',').map((v) => v.trim()).filter(Boolean)

  const hydrateSeatForm = useCallback((item: SeatRequestRecord | null) => {
    if (!item) {
      setSeatForm({
        title: '',
        summary: '',
        context_type: '',
        role_tags_csv: '',
        capability_tags_csv: '',
        availability_window: '',
        commitment_type: '',
        collaboration_mode: '',
        timezone_pref: '',
        is_active: true,
      })
      return
    }
    setSeatForm({
      title: item.title || '',
      summary: item.summary || '',
      context_type: item.context_type || '',
      role_tags_csv: (item.role_tags || []).join(', '),
      capability_tags_csv: (item.capability_tags || []).join(', '),
      availability_window: item.availability_window || '',
      commitment_type: item.commitment_type || '',
      collaboration_mode: item.collaboration_mode || '',
      timezone_pref: item.timezone_pref || '',
      is_active: item.is_active !== false,
    })
  }, [])

  const hydrateOfferForm = useCallback((item: CapabilityOfferRecord | null) => {
    if (!item) {
      setOfferForm({
        title: '',
        summary: '',
        role_tags_csv: '',
        capability_tags_csv: '',
        availability_window: '',
        commitment_type: '',
        collaboration_mode: '',
        timezone_pref: '',
        is_active: true,
      })
      return
    }
    setOfferForm({
      title: item.title || '',
      summary: item.summary || '',
      role_tags_csv: (item.role_tags || []).join(', '),
      capability_tags_csv: (item.capability_tags || []).join(', '),
      availability_window: item.availability_window || '',
      commitment_type: item.commitment_type || '',
      collaboration_mode: item.collaboration_mode || '',
      timezone_pref: item.timezone_pref || '',
      is_active: item.is_active !== false,
    })
  }, [])

  const hydrateMaterialRequestForm = useCallback((item: MaterialRequestRecord | null) => {
    if (!item) {
      setMaterialRequestForm({
        title: '',
        material_type: '',
        resource_nature: '',
        category_tags_csv: '',
        quantity_needed: '',
        quantity_unit: '',
        availability_start: '',
        availability_end: '',
        condition_min: '',
        access_mode: '',
        location_region: '',
        cost_band_max: '',
      })
      return
    }
    setMaterialRequestForm({
      title: item.title || '',
      material_type: item.material_type || '',
      resource_nature: item.resource_nature || '',
      category_tags_csv: (item.category_tags || []).join(', '),
      quantity_needed: String(item.quantity_needed ?? ''),
      quantity_unit: item.quantity_unit || '',
      availability_start: item.availability_start || '',
      availability_end: item.availability_end || '',
      condition_min: item.condition_min || '',
      access_mode: item.access_mode || '',
      location_region: item.location_region || '',
      cost_band_max: item.cost_band_max || '',
    })
  }, [])

  const hydrateMaterialOfferForm = useCallback((item: MaterialOfferRecord | null) => {
    if (!item) {
      setMaterialOfferForm({
        title: '',
        material_type: '',
        resource_nature: '',
        category_tags_csv: '',
        quantity_available: '',
        quantity_unit: '',
        availability_start: '',
        availability_end: '',
        condition_state: '',
        access_mode: '',
        location_region: '',
        cost_band: '',
      })
      return
    }
    setMaterialOfferForm({
      title: item.title || '',
      material_type: item.material_type || '',
      resource_nature: item.resource_nature || '',
      category_tags_csv: (item.category_tags || []).join(', '),
      quantity_available: String(item.quantity_available ?? ''),
      quantity_unit: item.quantity_unit || '',
      availability_start: item.availability_start || '',
      availability_end: item.availability_end || '',
      condition_state: item.condition_state || '',
      access_mode: item.access_mode || '',
      location_region: item.location_region || '',
      cost_band: item.cost_band || '',
    })
  }, [])

  /** Load core profiles for Team → Person influences picklists (no global loading spinner). */
  const loadCoreProfilesForInfluenceBundle = useCallback(async () => {
    try {
      const data = await apiGet<CoreProfile[]>('/core-profiles')
      setCoreProfiles(Array.isArray(data) ? data : [])
    } catch {
      setCoreProfiles([])
    }
  }, [])

  const fetchIdeas = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<Idea[]>('/ideas')
      setIdeas(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchInitiatives = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<Initiative[]>('/initiatives')
      setInitiatives(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
      setInitiatives([])
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchProjects = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<Project[]>('/projects')
      setProjects(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
      setProjects([])
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchTasks = useCallback(async (projectId?: string) => {
    setLoading(true)
    setError(null)
    try {
      const path = projectId ? `/tasks?project_id=${encodeURIComponent(projectId)}` : '/tasks'
      const data = await apiGet<Task[]>(path)
      setTasks(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
      setTasks([])
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchPersons = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<Person[]>('/persons')
      setPersons(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchCapacity = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<CapacityProfile[]>('/capacity-profiles')
      setCapacityProfiles(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchAssets = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await apiGet<Asset[]>('/assets')
      setAssets(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
      setAssets([])
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchRadar = useCallback(async () => {
    setRadarLoading(true)
    setError(null)
    try {
      const data = await apiGet<RadarResponse>('/radar')
      setRadarData(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setRadarLoading(false)
    }
  }, [])

  useEffect(() => {
    if (radarScrollBucketRequest == null) return
    if (tab !== 'radar') return
    if (radarLoading || !radarData) return
    const el = document.getElementById(`ve-radar-bucket-${radarScrollBucketRequest}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
    onRadarScrollBucketConsumed?.()
  }, [tab, radarLoading, radarData, radarScrollBucketRequest, onRadarScrollBucketConsumed])

  const fetchSeatRequests = useCallback(async () => {
    setMatchingLoading(true)
    setError(null)
    try {
      const data = await apiGet<SeatRequestRecord[]>('/seat-requests')
      setSeatRequests(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load seat requests')
    } finally {
      setMatchingLoading(false)
    }
  }, [])

  const fetchCapabilityOffers = useCallback(async () => {
    setMatchingLoading(true)
    setError(null)
    try {
      const data = await apiGet<CapabilityOfferRecord[]>('/capability-offers')
      setCapabilityOffers(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load capability offers')
    } finally {
      setMatchingLoading(false)
    }
  }, [])

  const fetchMaterialRequests = useCallback(async () => {
    setMatchingLoading(true)
    setError(null)
    try {
      const data = await apiGet<MaterialRequestRecord[]>('/material-requests')
      setMaterialRequests(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load material requests')
    } finally {
      setMatchingLoading(false)
    }
  }, [])

  const fetchMaterialOffers = useCallback(async () => {
    setMatchingLoading(true)
    setError(null)
    try {
      const data = await apiGet<MaterialOfferRecord[]>('/material-offers')
      setMaterialOffers(Array.isArray(data) ? data : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load material offers')
    } finally {
      setMatchingLoading(false)
    }
  }, [])

  useEffect(() => {
    loadCoreProfilesForInfluenceBundle()
  }, [loadCoreProfilesForInfluenceBundle])

  // Apply navigation from Radar (or elsewhere): open the right tab and select entity
  useEffect(() => {
    if (!initialSelection) return
    if (initialSelection.ideaId) {
      setTab('ideas')
      setDetailIdeaId(initialSelection.ideaId)
      setDetailInitiativeId(null)
      setDetailProjectId(null)
      setDetailTaskId(null)
      setDetailAssetId(null)
      setSelectedId(initialSelection.ideaId)
      return
    }
    const tabId = initialSelection.tab
    const executionTab = tabId === 'initiatives' || tabId === 'projects' || tabId === 'tasks' ? 'execution' : tabId
    setTab(executionTab as TabId)
    setDetailIdeaId(null)
    setDetailInitiativeId(initialSelection.initiativeId ?? null)
    setDetailProjectId(initialSelection.projectId ?? null)
    setDetailTaskId(initialSelection.taskId ?? null)
    setDetailAssetId(initialSelection.assetId ?? null)
    setSelectedId(
      initialSelection.projectId ??
      initialSelection.taskId ??
      initialSelection.assetId ??
      initialSelection.initiativeId ??
      null
    )
  }, [initialSelection])

  const bundleForFocus = useMemo(
    (): VisionMapEntityBundle => ({ ideas, initiatives, projects, tasks }),
    [ideas, initiatives, projects, tasks],
  )
  const veFocusOpt = useVisionExecutionFocusOptional()
  const veFocusOptRef = useRef(veFocusOpt)
  veFocusOptRef.current = veFocusOpt

  /** True until detail state has caught up after `initialSelection` was set (avoids clearing App `veSelection` on first paint). */
  const veSelectionHydrationPendingRef = useRef(false)
  useEffect(() => {
    veSelectionHydrationPendingRef.current = !!initialSelection
  }, [initialSelection])

  // Push App `veSelection` only when detail/tab/initialSelection change — not when `ideas`/bundle refresh.
  useEffect(() => {
    const sel = deriveVeSelectionFromDetailState(
      tab,
      detailIdeaId,
      detailInitiativeId,
      detailProjectId,
      detailTaskId,
      detailAssetId,
    )
    const anyDetailOpen = !!(
      detailIdeaId ??
      detailInitiativeId ??
      detailProjectId ??
      detailTaskId ??
      detailAssetId
    )
    if (
      veSelectionHydrationPendingRef.current &&
      sel == null &&
      initialSelection &&
      !anyDetailOpen
    ) {
      return
    }
    if (sel != null || !initialSelection) {
      veSelectionHydrationPendingRef.current = false
    }

    onVeSelectionChange?.(sel)
  }, [
    tab,
    detailIdeaId,
    detailInitiativeId,
    detailProjectId,
    detailTaskId,
    detailAssetId,
    initialSelection,
    onVeSelectionChange,
  ])

  // Refresh conversation focus labels when entity lists change (titles, etc.) without re-pushing `veSelection`.
  useEffect(() => {
    const sel = deriveVeSelectionFromDetailState(
      tab,
      detailIdeaId,
      detailInitiativeId,
      detailProjectId,
      detailTaskId,
      detailAssetId,
    )
    const anyDetailOpen = !!(
      detailIdeaId ??
      detailInitiativeId ??
      detailProjectId ??
      detailTaskId ??
      detailAssetId
    )
    if (
      veSelectionHydrationPendingRef.current &&
      sel == null &&
      initialSelection &&
      !anyDetailOpen
    ) {
      return
    }
    const fc = veFocusOptRef.current
    if (!fc) return
    if (sel) {
      const desc = focusDescriptorFromVeSelection(sel, bundleForFocus, 'vision_execution')
      if (desc) fc.notifyConversationEntityFocus(desc)
      else fc.clearConversationEntityShell()
    } else {
      fc.clearConversationEntityShell()
    }
  }, [
    bundleForFocus,
    tab,
    detailIdeaId,
    detailInitiativeId,
    detailProjectId,
    detailTaskId,
    detailAssetId,
    initialSelection,
  ])

  useEffect(() => {
    if (tab === 'ideas') fetchIdeas()
    else if (tab === 'execution') {
      fetchInitiatives()
      fetchProjects()
      fetchTasks()
      fetchPersons()
      fetchIdeas()
    } else if (tab === 'people') {
      fetchPersons()
      fetchCapacity()
    } else if (tab === 'assets') fetchAssets()
    else if (tab === 'radar') fetchRadar()
    else if (tab === 'matching_internal') {
      fetchSeatRequests()
      fetchCapabilityOffers()
      fetchMaterialRequests()
      fetchMaterialOffers()
    }
    else if (tab === 'meeting_capture') {
      fetchInitiatives()
      fetchProjects()
      fetchTasks()
      fetchAssets()
      fetchPersons()
    }
  }, [tab, fetchIdeas, fetchInitiatives, fetchProjects, fetchTasks, fetchPersons, fetchCapacity, fetchAssets, fetchRadar, fetchSeatRequests, fetchCapabilityOffers, fetchMaterialRequests, fetchMaterialOffers])

  const refetch = useCallback(() => {
    if (tab === 'ideas') fetchIdeas()
    else if (tab === 'execution') {
      fetchInitiatives()
      fetchProjects()
      fetchTasks()
    } else if (tab === 'people') {
      fetchPersons()
      fetchCapacity()
    } else if (tab === 'assets') fetchAssets()
    else if (tab === 'radar') fetchRadar()
    else if (tab === 'matching_internal') { fetchSeatRequests(); fetchCapabilityOffers(); fetchMaterialRequests(); fetchMaterialOffers() }
  }, [tab, fetchIdeas, fetchInitiatives, fetchProjects, fetchTasks, fetchPersons, fetchCapacity, fetchAssets, fetchRadar, fetchSeatRequests, fetchCapabilityOffers, fetchMaterialRequests, fetchMaterialOffers])

  const selectedSeatRequest = seatRequests.find((r) => r.id === selectedSeatRequestId) ?? null
  const selectedCapabilityOffer = capabilityOffers.find((o) => o.id === selectedCapabilityOfferId) ?? null
  const selectedMaterialRequest = materialRequests.find((r) => r.id === selectedMaterialRequestId) ?? null
  const selectedMaterialOffer = materialOffers.find((o) => o.id === selectedMaterialOfferId) ?? null


  const handleCreateIdea = async (payload: { title: string; summary?: string; description?: string }) => {
    setError(null)
    try {
      await apiPost<Idea>('/ideas', {
        title: payload.title || 'Untitled',
        summary: payload.summary ?? '',
        description: payload.description ?? '',
        status: 'Captured',
      })
      setShowCreate(false)
      fetchIdeas()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreateInitiative = async (payload: { title: string; brief?: string }) => {
    setError(null)
    try {
      await apiPost<Initiative>('/initiatives', {
        title: payload.title || 'Untitled',
        brief: payload.brief ?? '',
        status: 'Draft',
      })
      setShowCreate(false)
      fetchInitiatives()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreateProject = async (payload: { title: string; brief?: string }) => {
    setError(null)
    try {
      await apiPost<Project>('/projects', {
        title: payload.title || 'Untitled',
        brief: payload.brief ?? '',
        status: 'Draft',
      })
      setShowCreate(false)
      fetchProjects()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreateTask = async (payload: { project_id: string | null; title: string }) => {
    setError(null)
    try {
      await apiPost<Task>('/tasks', {
        project_id: payload.project_id && payload.project_id.length > 0 ? payload.project_id : null,
        title: payload.title || 'Untitled',
        status: 'Todo',
      })
      setShowCreate(false)
      fetchTasks()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreatePerson = async (payload: { name: string; role?: string }) => {
    setError(null)
    try {
      await apiPost<Person>('/persons', {
        name: payload.name || 'Unnamed',
        role: payload.role ?? '',
      })
      setShowCreate(false)
      fetchPersons()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleCreateAsset = async (payload: { name: string; asset_type?: string }) => {
    setError(null)
    try {
      await apiPost<Asset>('/assets', {
        name: payload.name || 'Untitled',
        asset_type: payload.asset_type ?? '',
      })
      setShowCreate(false)
      fetchAssets()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    }
  }

  const handleMeetingFileSelect = useCallback(async (files: FileList | null) => {
    const file = files?.[0]
    if (!file) return
    setError(null)
    setUploadLoading(true)
    try {
      const text = await fileToText(file)
      setMeetingNotes(text)
      if (meetingFileInputRef.current) meetingFileInputRef.current.value = ''
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to read file')
    } finally {
      setUploadLoading(false)
    }
  }, [])

  /** Build staging from chunk mode results (succeeded only). Reused after initial extract and after retries. */
  const buildStagingFromChunkResults = useCallback(
    (chunks: ManualProcessingChunk[], results: ChunkResultEntry[]): StagingArea | null => {
      const succeeded = results.filter((r) => r.status === 'succeeded' && r.response && !r.response.error)
      if (succeeded.length === 0) return null
      const segmentResults = succeeded.map((r) => {
        const chunk = chunks.find((c) => c.id === r.chunkId)!
        const segment = {
          id: chunk.id,
          title: chunk.title,
          startOffset: chunk.startOffset,
          endOffset: chunk.endOffset,
          text: chunk.text,
        }
        return { segment, response: r.response! }
      })
      const extraction = mergeSegmentExtractionResults(segmentResults)
      return buildStagingArea(extraction)
    },
    []
  )

  const meetingExtractApiFields = () => ({
    useExternalAiExtraction,
    ...(useExternalAiExtraction && externalAiEngine.trim() ? { externalAiEngine: externalAiEngine.trim() } : {}),
    washDataForCall,
  })

  const stopMeetingExtraction = useCallback(() => {
    meetingExtractAbortRef.current?.abort()
  }, [])

  const handleExtractMeeting = async () => {
    setError(null)
    if (useExternalAiExtraction && !externalAiEngine.trim()) {
      setError('Choose an AI engine, or turn off external AI extraction.')
      return
    }
    setCommitError(null)
    // Lightweight pre-pass: derive themes and entities for orientation/progress only.
    const contextPreview = deriveGlobalExtractionContext(meetingNotes)
    setGlobalExtractionContext(contextPreview)
    const context = buildExtractionContext(initiatives, projects, tasks, assets, persons)
    const workspacePacketOpt = readWorkspacePacketForExtract()
    const notesTrimmed = meetingNotes.trim()
    if (!notesTrimmed) {
      setChunkModeChunks(null)
      setChunkModeResults([])
      setError('Add meeting notes or a transcript before extracting.')
      return
    }
    meetingExtractAbortRef.current?.abort()
    const abortController = new AbortController()
    meetingExtractAbortRef.current = abortController
    const signal = abortController.signal
    setExtractLoading(true)
    setMeetingExtractPathDiag(null)
    let chunkTotalForTrace: number | undefined
    try {
      const prevMeetingTrace = lastMeetingExtractTraceRef.current
      if (prevMeetingTrace) {
        pushAiActionTrace(withTraceOutcome(prevMeetingTrace, 'edited'))
        lastMeetingExtractTraceRef.current = null
      }
      /** Short external: one call. Local: interactive-sized chunks. Long external: ~one call per `EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS` of transcript. */
      const segmentResults = await (async () => {
        const useExternalPath = useExternalAiExtraction && !!externalAiEngine.trim()
        const extThreshold = EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS
        const transcriptLen = notesTrimmed.length

        if (useExternalPath && transcriptLen <= extThreshold) {
          setChunkProgressExtractKind('local')
          setChunkModeChunks(null)
          setChunkModeResults([])
          setChunkRunFocus(null)
          chunkTotalForTrace = undefined
          if (import.meta.env.DEV) {
            console.info('[VE extract] external single-call path', {
              external_single_call: true,
              transcriptChars: transcriptLen,
              thresholdChars: extThreshold,
              extract_calls_n: 1,
              chunks: 0,
            })
          }
          const clientT0 = typeof performance !== 'undefined' ? performance.now() : 0
          try {
            const data = await apiPost<ExtractMeetingResponse>(
              '/extract-meeting',
              {
                notes: notesTrimmed,
                context,
                includeHarvestLedger: true,
                evidenceExtractionPreset: INTERACTIVE_EXTRACT_MEETING_PRESET,
                globalContext: globalExtractionContext,
                routingContext: meetingExtractionRoutingContext('meeting_extract_external_single', {
                  diagnosticsChunkId: 'external-whole',
                }),
                ...meetingExtractApiFields(),
                ...(workspacePacketOpt ? { workspacePacket: workspacePacketOpt } : {}),
              },
              { signal },
            )
            setExtractResult(data)
            if (import.meta.env.DEV) {
              const waitMs = typeof performance !== 'undefined' ? performance.now() - clientT0 : 0
              console.debug('[VE extract external single]', {
                clientWaitMs: Math.round(waitMs),
                extractionMeta: data.extractionMeta,
                candidateCount: Array.isArray(data.candidates) ? data.candidates.length : 0,
              })
            }
            if (data.execution_blocked) {
              const msg =
                data.message ||
                data.error ||
                'Extraction was blocked by your privacy settings. No model was used. Try a local model or change Privacy mode in Settings.'
              setError(msg)
              return []
            }
            if (data.error) {
              const fr = data as { error?: unknown; message?: string }
              setError(fr.message ?? (typeof fr.error === 'string' ? fr.error : String(fr.error)))
              return []
            }
            return [
              {
                segment: {
                  id: 'external-whole',
                  title: 'Full transcript',
                  startOffset: 0,
                  endOffset: transcriptLen,
                  text: notesTrimmed,
                },
                response: data,
              },
            ]
          } catch (e) {
            if (isAbortError(e)) {
              return []
            }
            throw e
          }
        }

        if (useExternalPath && transcriptLen > extThreshold && import.meta.env.DEV) {
          console.info('[VE extract] external chunked path (transcript over single-call threshold)', {
            external_single_call: false,
            transcriptChars: transcriptLen,
            thresholdChars: extThreshold,
          })
        }

        const longExternal = useExternalPath && transcriptLen > extThreshold
        const chunks = longExternal
          ? buildExternalBudgetChunks(notesTrimmed, extThreshold)
          : buildManualProcessingChunks(notesTrimmed, { interactiveFast: true })
        setChunkProgressExtractKind(longExternal ? 'external_budget' : 'local')
        if (chunks.length === 0) {
          setChunkModeChunks(null)
          setChunkModeResults([])
          return []
        }
        chunkTotalForTrace = chunks.length
        setChunkModeChunks(chunks)
        const results: ChunkResultEntry[] = chunks.map((c) => ({ chunkId: c.id, status: 'pending' as ChunkStatus }))
        setChunkModeResults(results)
        for (let i = 0; i < chunks.length; i++) {
          if (signal.aborted) {
            for (let j = i; j < chunks.length; j++) {
              if (results[j]!.status === 'pending') {
                results[j] = { chunkId: chunks[j]!.id, status: 'failed' as ChunkStatus, error: 'Stopped' }
              }
            }
            setChunkRunFocus(null)
            setChunkModeResults([...results])
            const stagingEarly = buildStagingFromChunkResults(chunks, results)
            if (stagingEarly) {
              setStagingArea(stagingEarly)
              setShowReviewExtraction(true)
            }
            break
          }
          setChunkModeResults((prev) => prev.map((r, j) => (j === i ? { ...r, status: 'running' as ChunkStatus } : r)))
          const clientT0 = typeof performance !== 'undefined' ? performance.now() : 0
          setChunkRunFocus({ chunkIndex: i, startedAt: clientT0 })
          try {
            const data = await apiPost<ExtractMeetingResponse>(
              '/extract-meeting',
              {
                notes: chunks[i]!.text,
                context,
                includeHarvestLedger: true,
                evidenceExtractionPreset: INTERACTIVE_EXTRACT_MEETING_PRESET,
                globalContext: globalExtractionContext,
                routingContext: meetingExtractionRoutingContext('meeting_extract_chunks', {
                  diagnosticsChunkId: chunks[i]!.id,
                  meetingExtractChunked: true,
                }),
                ...meetingExtractApiFields(),
                ...(workspacePacketOpt ? { workspacePacket: workspacePacketOpt } : {}),
              },
              { signal },
            )
            if (import.meta.env.DEV) {
              const waitMs = typeof performance !== 'undefined' ? performance.now() - clientT0 : 0
              console.debug('[VE extract chunk]', chunks[i]!.id, {
                index: i,
                lastChunk: i === chunks.length - 1,
                clientWaitMs: Math.round(waitMs),
                extractionMeta: data.extractionMeta,
                noDurableCandidates: data.noDurableCandidates,
                candidateCount: Array.isArray(data.candidates) ? data.candidates.length : 0,
              })
            }
            if (data.execution_blocked) {
              const msg =
                data.message ||
                data.error ||
                'Extraction was blocked by your privacy settings. No model was used. Try a local model or change Privacy mode in Settings.'
              setError(msg)
              for (let j = i; j < chunks.length; j++) {
                results[j] = {
                  chunkId: chunks[j]!.id,
                  status: 'failed' as ChunkStatus,
                  error: msg,
                }
              }
              setChunkModeResults([...results])
              setChunkRunFocus(null)
              break
            }
            results[i] = {
              chunkId: chunks[i]!.id,
              status: data.error ? ('failed' as ChunkStatus) : ('succeeded' as ChunkStatus),
              response: data,
              error: data.error,
            }
          } catch (e) {
            if (isAbortError(e)) {
              results[i] = { chunkId: chunks[i]!.id, status: 'failed' as ChunkStatus, error: 'Stopped' }
              for (let j = i + 1; j < chunks.length; j++) {
                if (results[j]!.status === 'pending') {
                  results[j] = { chunkId: chunks[j]!.id, status: 'failed' as ChunkStatus, error: 'Stopped' }
                }
              }
              setChunkRunFocus(null)
              setChunkModeResults([...results])
              const stagingStop = buildStagingFromChunkResults(chunks, results)
              if (stagingStop) {
                setStagingArea(stagingStop)
                setShowReviewExtraction(true)
              }
              break
            }
            results[i] = {
              chunkId: chunks[i]!.id,
              status: 'failed' as ChunkStatus,
              error: e instanceof Error ? e.message : 'Extract failed',
            }
          }
          setChunkRunFocus(null)
          setChunkModeResults([...results])
          const staging = buildStagingFromChunkResults(chunks, results)
          if (staging) {
            setStagingArea(staging)
            setShowReviewExtraction(true)
          }
        }
        setExtractResult(results[0]?.response ?? null)
        const anySucceeded = results.some((r) => r.status === 'succeeded')
        if (!anySucceeded && results[0]) setError(results[0].error ?? 'All chunks failed')
        return results
          .filter((r) => r.status === 'succeeded' && r.response)
          .map((r) => {
            const chunk = chunks.find((c) => c.id === r.chunkId)!
            return {
              segment: { id: chunk.id, title: chunk.title, startOffset: chunk.startOffset, endOffset: chunk.endOffset, text: chunk.text },
              response: r.response!,
            }
          })
      })()
      const firstResponse = segmentResults[0]?.response
      setExtractResult(firstResponse ?? null)
      if (
        segmentResults.length === 0 ||
        firstResponse?.execution_blocked ||
        (firstResponse?.error && segmentResults.every((r) => r.response?.error))
      ) {
        setMeetingExtractPathDiag(null)
        setStagingArea(null)
        setShowReviewExtraction(false)
        if (segmentResults.length === 0) {
          setError((prev) => prev ?? 'No extractable meeting text. Paste notes or upload a file, or try simpler content if preprocessing removed everything.')
        }
        if (firstResponse?.execution_blocked) {
          setError(
            firstResponse.message ||
              (typeof firstResponse.error === 'string' ? firstResponse.error : null) ||
              'Extraction was blocked by your privacy settings.',
          )
        } else if (firstResponse?.error) {
          const fr = firstResponse as { error?: unknown; message?: string }
          setError(fr.message ?? (typeof fr.error === 'string' ? fr.error : String(fr.error)))
        }
      } else {
        const ranExternal = useExternalAiExtraction && !!externalAiEngine.trim()
        const extSingleCall = ranExternal && notesTrimmed.length <= EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS

        let extraction =
          segmentResults.length === 1
            ? parseLegacyExtractResponse(segmentResults[0].response)
            : mergeSegmentExtractionResults(segmentResults)
        if (segmentResults.length === 1 && segmentResults[0]) {
          const seg = segmentResults[0].segment
          const attach = <T extends { segmentId?: string; segmentTitle?: string }>(item: T): T => ({
            ...item,
            segmentId: seg.id,
            segmentTitle: seg.title ?? seg.id,
          })
          extraction.ideas = extraction.ideas.map(attach)
          extraction.initiatives = extraction.initiatives.map(attach)
          extraction.tasks = extraction.tasks.map(attach)
        }
        // Multi-segment: merge already consolidates cross-chunk rows; document-level budget once (full transcript).
        if (segmentResults.length > 1) {
          extraction = applyDocumentLevelExtractionBudget(extraction, notesTrimmed.length)
        }
        const stagingBuilt = buildStagingArea(extraction)
        setStagingArea(stagingBuilt)
        setShowReviewExtraction(true)

        const meta = firstResponse?.extractionMeta
        const actionIntent: MeetingExtractActionIntent = extSingleCall
          ? 'meeting_extract_external_single'
          : 'meeting_extract_chunks'
        const path: MeetingExtractionPath = extSingleCall ? 'single' : 'chunks'
        const mid = (firstResponse as { meeting_id?: string } | undefined)?.meeting_id
        const chunkSucceeded = segmentResults.length
        setMeetingExtractPathDiag({
          engine: ranExternal ? 'external' : 'local',
          externalSingleCall: extSingleCall,
          transcriptChars: notesTrimmed.length,
          thresholdChars: ranExternal ? EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS : 0,
          extractCalls: segmentResults.length,
          documentBudgetApplied: segmentResults.length > 1,
        })
        const inputSnap = buildMeetingExtractionInputSnapshot({
          meeting_id: mid,
          path,
          notes_char_len: notesTrimmed.length,
          chunk_total: extSingleCall ? undefined : chunkTotalForTrace,
          chunk_succeeded: chunkSucceeded,
          themes_n: contextPreview.themes?.length,
          external_single_call: ranExternal ? extSingleCall : undefined,
          external_chunk_threshold_chars: ranExternal ? EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS : undefined,
          extract_calls_n: segmentResults.length,
          document_budget_applied: segmentResults.length > 1 ? true : undefined,
        })
        const tr = emitMeetingExtractionTrace({
          action_intent: actionIntent,
          meeting_id: mid ?? null,
          input_snapshot: inputSnap,
          output_summary: buildMeetingExtractionStagingOutputSummary(stagingBuilt),
          resolved_model_used: meta?.resolvedModelUsed ?? null,
          resolved_provider_used: meta?.resolvedProviderUsed ?? null,
        })
        lastMeetingExtractTraceRef.current = tr
      }
    } catch (e) {
      setMeetingExtractPathDiag(null)
      setError(e instanceof Error ? e.message : 'Extract failed')
      setExtractResult(null)
      setStagingArea(null)
      setShowReviewExtraction(false)
    } finally {
      setChunkRunFocus(null)
      setExtractLoading(false)
      meetingExtractAbortRef.current = null
    }
  }

  const handleRetryChunk = useCallback(
    async (chunkId: string) => {
      const chunks = chunkModeChunksRef.current
      const currentResults = chunkModeResultsRef.current
      if (!chunks?.length || !currentResults.length) return
      const idx = currentResults.findIndex((r) => r.chunkId === chunkId)
      if (idx < 0) return
      const context = buildExtractionContext(initiatives, projects, tasks, assets, persons)
      const workspacePacketOpt = readWorkspacePacketForExtract()
      setError(null)
      meetingExtractAbortRef.current?.abort()
      const ac = new AbortController()
      meetingExtractAbortRef.current = ac
      const signal = ac.signal
      setExtractLoading(true)
      const results = [...currentResults]
      try {
        try {
          results[idx] = { ...results[idx]!, status: 'running' }
          setChunkModeResults(results)
          const clientT0 = typeof performance !== 'undefined' ? performance.now() : 0
          setChunkRunFocus({ chunkIndex: idx, startedAt: clientT0 })
          const data = await apiPost<ExtractMeetingResponse>(
            '/extract-meeting',
            {
              notes: chunks[idx]!.text,
              context,
              includeHarvestLedger: true,
              evidenceExtractionPreset: INTERACTIVE_EXTRACT_MEETING_PRESET,
              routingContext: meetingExtractionRoutingContext('meeting_extract_chunks', {
                diagnosticsChunkId: chunks[idx]!.id,
                meetingExtractChunked: true,
              }),
              ...meetingExtractApiFields(),
              ...(workspacePacketOpt ? { workspacePacket: workspacePacketOpt } : {}),
            },
            { signal },
          )
          traceMeetingExtractChunkRetry(
            extractResult?.meeting_id,
            chunks[idx]!.id,
            chunks[idx]!.text.length,
            data,
          )
          if (import.meta.env.DEV) {
            const waitMs = typeof performance !== 'undefined' ? performance.now() - clientT0 : 0
            console.debug('[VE extract chunk retry]', chunks[idx]!.id, { clientWaitMs: Math.round(waitMs), extractionMeta: data.extractionMeta })
          }
          if (data.execution_blocked) {
            const msg =
              data.message ||
              data.error ||
              'Extraction was blocked by your privacy settings. No model was used.'
            results[idx] = { chunkId: chunks[idx]!.id, status: 'failed', error: msg }
            setError(msg)
          } else {
            results[idx] = {
              chunkId: chunks[idx]!.id,
              status: data.error ? 'failed' : 'succeeded',
              response: data,
              error: data.error,
            }
          }
        } catch (e) {
          if (isAbortError(e)) {
            results[idx] = { ...results[idx]!, status: 'failed', error: 'Stopped' }
            setError('Extraction stopped.')
          } else {
            const errMsg = e instanceof Error ? e.message : 'Extract failed'
            results[idx] = { ...results[idx]!, status: 'failed', error: errMsg }
            setError(errMsg)
          }
        }
        setChunkRunFocus(null)
        setChunkModeResults([...results])
        const staging = buildStagingFromChunkResults(chunks, results)
        if (staging) setStagingArea(staging)
      } finally {
        setChunkRunFocus(null)
        setExtractLoading(false)
        meetingExtractAbortRef.current = null
      }
    },
    [
      initiatives,
      projects,
      tasks,
      assets,
      persons,
      buildStagingFromChunkResults,
      useExternalAiExtraction,
      externalAiEngine,
      washDataForCall,
      extractResult,
    ]
  )

  const handleRetryFailedChunks = useCallback(async () => {
    const chunks = chunkModeChunksRef.current
    const currentResults = chunkModeResultsRef.current
    if (!chunks?.length || !currentResults.length) return
    const failedIndices = currentResults
      .map((r, i) => (r.status === 'failed' ? i : -1))
      .filter((i) => i >= 0)
    if (failedIndices.length === 0) return
    const context = buildExtractionContext(initiatives, projects, tasks, assets, persons)
    const workspacePacketOpt = readWorkspacePacketForExtract()
    setError(null)
    meetingExtractAbortRef.current?.abort()
    const ac = new AbortController()
    meetingExtractAbortRef.current = ac
    const signal = ac.signal
    setExtractLoading(true)
    let results = [...currentResults]
    try {
      for (const i of failedIndices) {
        if (signal.aborted) break
        results[i] = { ...results[i]!, status: 'running' }
        setChunkModeResults([...results])
        const clientT0 = typeof performance !== 'undefined' ? performance.now() : 0
        setChunkRunFocus({ chunkIndex: i, startedAt: clientT0 })
        try {
          const data = await apiPost<ExtractMeetingResponse>(
            '/extract-meeting',
            {
              notes: chunks[i]!.text,
              context,
              includeHarvestLedger: true,
              evidenceExtractionPreset: INTERACTIVE_EXTRACT_MEETING_PRESET,
              routingContext: meetingExtractionRoutingContext('meeting_extract_chunks', {
                diagnosticsChunkId: chunks[i]!.id,
                meetingExtractChunked: true,
              }),
              ...meetingExtractApiFields(),
              ...(workspacePacketOpt ? { workspacePacket: workspacePacketOpt } : {}),
            },
            { signal },
          )
          traceMeetingExtractChunkRetry(
            extractResult?.meeting_id,
            chunks[i]!.id,
            chunks[i]!.text.length,
            data,
          )
          if (import.meta.env.DEV) {
            const waitMs = typeof performance !== 'undefined' ? performance.now() - clientT0 : 0
            console.debug('[VE extract chunk batch-retry]', chunks[i]!.id, { clientWaitMs: Math.round(waitMs), extractionMeta: data.extractionMeta })
          }
          if (data.execution_blocked) {
            const msg =
              data.message ||
              data.error ||
              'Extraction was blocked by your privacy settings. No model was used.'
            results[i] = { chunkId: chunks[i]!.id, status: 'failed', error: msg }
            setError(msg)
          } else {
            results[i] = {
              chunkId: chunks[i]!.id,
              status: data.error ? 'failed' : 'succeeded',
              response: data,
              error: data.error,
            }
          }
        } catch (e) {
          if (isAbortError(e)) {
            results[i] = { ...results[i]!, status: 'failed', error: 'Stopped' }
            setError('Extraction stopped.')
            break
          }
          const errMsg = e instanceof Error ? e.message : 'Extract failed'
          results[i] = { ...results[i]!, status: 'failed', error: errMsg }
          setError(errMsg)
        }
        setChunkRunFocus(null)
        setChunkModeResults([...results])
      }
      const staging = buildStagingFromChunkResults(chunks, results)
      if (staging) setStagingArea(staging)
    } finally {
      setChunkRunFocus(null)
      setExtractLoading(false)
      meetingExtractAbortRef.current = null
    }
  }, [
    initiatives,
    projects,
    tasks,
    assets,
    persons,
    buildStagingFromChunkResults,
    useExternalAiExtraction,
    externalAiEngine,
    washDataForCall,
    extractResult,
  ])

  const handleCommitReview = async () => {
    if (!stagingArea) return
    setCommitError(null)
    setCommitLoading(true)
    try {
      const result = await commitStagedItems(stagingArea, {
        apiPost: apiPost as (path: string, body: unknown) => Promise<{ id: string; title?: string }>,
        existingInitiatives: initiatives,
        existingProjects: projects,
      })
      if (result.errors.length > 0) {
        setCommitError(result.errors.join('; '))
      }
      const anyCreated =
        result.created.ideas > 0 ||
        result.created.initiatives > 0 ||
        result.created.projects > 0 ||
        result.created.tasks > 0 ||
        result.created.assets > 0 ||
        result.created.persons > 0
      if (anyCreated) {
        fetchIdeas()
        fetchInitiatives()
        fetchProjects()
        fetchTasks()
        fetchAssets()
        fetchPersons()
      }
      // Push approved signals to canonical Layer 1 Signal entity (Radar is a view over these)
      const signalKinds = ['attention', 'risk', 'opportunity', 'blocker'] as const
      const approvedSignals = stagingArea.signals.filter((s) => s.approved && signalKinds.includes(s.data.kind))
      if (approvedSignals.length > 0) {
        try {
          await apiPost('/signals', approvedSignals.map((item) => {
            const parent = item.parentLink
            const isParent = !parent?.relationshipType || parent.relationshipType === 'parent'
            return {
              kind: item.data.kind,
              title: item.data.label || item.data.kind,
              detail: item.data.detail ?? '',
              source: 'meeting-extraction',
              source_excerpt: item.data.sourceExcerpt ?? null,
              source_ref: { type: 'meeting', id: (extractResult as { meeting_id?: string } | null)?.meeting_id ?? '' },
              confidence: item.data.confidence ?? null,
              status: 'new',
              ...(isParent && parent?.parentType === 'initiative' && { linked_initiative_id: parent.parentId }),
              ...(isParent && parent?.parentType === 'project' && { linked_project_id: parent.parentId }),
              ...(isParent && parent?.parentType === 'task' && { linked_task_id: parent.parentId }),
              ...((item.assignedAssetIds?.length ?? 0) > 0 && { linked_asset_ids: item.assignedAssetIds }),
            }
          }))
        } catch {
          // Non-blocking: signal push failure is ignored
        }
        fetchRadar()
      }
      const meetingIdForRecognition = (extractResult as { meeting_id?: string } | null)?.meeting_id ?? null
      try {
        await postMeetingExtractionRecognition(apiPost, {
          meetingId: meetingIdForRecognition,
          createdRefs: result.createdRefs,
          signalsCreated: approvedSignals.length,
          userId: recognitionUserId ?? null,
        })
      } catch {
        /* non-blocking: provenance decision failure must not block commit */
      }
      if (result.errors.length === 0 || anyCreated) {
        const mt = lastMeetingExtractTraceRef.current
        if (mt) {
          recordMeetingExtractionTraceOutcome(mt, 'applied')
          lastMeetingExtractTraceRef.current = null
        }
        setMeetingNotes('')
        setExtractResult(null)
        setStagingArea(null)
        setShowReviewExtraction(false)
        setChunkModeChunks(null)
        setChunkModeResults([])
      }
    } catch (e) {
      setCommitError(e instanceof Error ? e.message : 'Commit failed')
    } finally {
      setCommitLoading(false)
    }
  }

  const isStagingAreaEmpty = useCallback((s: StagingArea) => {
    return (
      !s.summary &&
      s.insights.length === 0 &&
      s.ideas.length === 0 &&
      s.initiatives.length === 0 &&
      s.projects.length === 0 &&
      s.tasks.length === 0 &&
      s.assets.length === 0 &&
      s.people.length === 0 &&
      (s.signals?.length ?? 0) === 0
    )
  }, [])

  /** Clears meeting extract UI state when the last staged row is gone (no nested setStagingArea). */
  const runReviewCloseCleanup = useCallback(() => {
    const mt = lastMeetingExtractTraceRef.current
    if (mt) {
      recordMeetingExtractionTraceOutcome(mt, 'applied')
      lastMeetingExtractTraceRef.current = null
    }
    setMeetingNotes('')
    setExtractResult(null)
    setShowReviewExtraction(false)
    setChunkModeChunks(null)
    setChunkModeResults([])
  }, [])

  const removeStagedItemById = useCallback((staging: StagingArea, sectionKey: StagingArraySectionKey, itemId: string): StagingArea => {
    const arr = staging[sectionKey]
    if (!Array.isArray(arr)) return staging
    const filtered = arr.filter((row) => row.id !== itemId)
    return { ...staging, [sectionKey]: filtered }
  }, [])

  const handleDismissReviewItem = useCallback(
    (sectionKey: StagingArraySectionKey, index: number) => {
      setStagingArea((prev) => {
        if (!prev) return prev
        const arr = prev[sectionKey]
        if (!Array.isArray(arr) || index < 0 || index >= arr.length) return prev
        const nextArr = arr.slice()
        nextArr.splice(index, 1)
        const next = { ...prev, [sectionKey]: nextArr } as StagingArea
        if (isStagingAreaEmpty(next)) {
          runReviewCloseCleanup()
          return null
        }
        return next
      })
    },
    [isStagingAreaEmpty, runReviewCloseCleanup]
  )

  const handleDismissReviewSummary = useCallback(() => {
    setStagingArea((prev) => {
      if (!prev) return prev
      const next = { ...prev, summary: null }
      if (isStagingAreaEmpty(next)) {
        runReviewCloseCleanup()
        return null
      }
      return next
    })
  }, [isStagingAreaEmpty, runReviewCloseCleanup])

  const handleCommitSingleReviewItem = useCallback(
    async (sectionKey: StagingArraySectionKey, itemId: string): Promise<boolean> => {
      if (!stagingArea) return false
      const arr = stagingArea[sectionKey]
      if (!Array.isArray(arr)) return false
      const row = arr.find((r) => r.id === itemId)
      if (!row) return false

      if (sectionKey === 'insights') return false

      setCommitError(null)

      if (row.acceptedExistingId) {
        setStagingArea((prev) => {
          if (!prev) return prev
          const next = removeStagedItemById(prev, sectionKey, itemId)
          if (isStagingAreaEmpty(next)) {
            runReviewCloseCleanup()
            return null
          }
          return next
        })
        return true
      }

      const signalKinds = ['attention', 'risk', 'opportunity', 'blocker'] as const
      if (sectionKey === 'signals') {
        const sig = row.data as ExtractedSignal
        const kind = sig.kind
        if (!kind || !signalKinds.includes(kind as (typeof signalKinds)[number])) {
          setCommitError('This signal row cannot be committed (invalid kind).')
          return false
        }
        setCommittingItemId(itemId)
        try {
          const parent = row.parentLink
          const isParent = !parent?.relationshipType || parent.relationshipType === 'parent'
          await apiPost('/signals', [
            {
              kind: sig.kind,
              title: sig.label || sig.kind,
              detail: sig.detail ?? '',
              source: 'meeting-extraction',
              source_excerpt: sig.sourceExcerpt ?? null,
              source_ref: { type: 'meeting', id: (extractResult as { meeting_id?: string } | null)?.meeting_id ?? '' },
              confidence: sig.confidence ?? null,
              status: 'new',
              ...(isParent && parent?.parentType === 'initiative' && { linked_initiative_id: parent.parentId }),
              ...(isParent && parent?.parentType === 'project' && { linked_project_id: parent.parentId }),
              ...(isParent && parent?.parentType === 'task' && { linked_task_id: parent.parentId }),
              ...((row.assignedAssetIds?.length ?? 0) > 0 && { linked_asset_ids: row.assignedAssetIds }),
            },
          ])
          fetchRadar()
          try {
            await postMeetingExtractionRecognition(apiPost, {
              meetingId: (extractResult as { meeting_id?: string } | null)?.meeting_id ?? null,
              createdRefs: [],
              signalsCreated: 1,
              userId: recognitionUserId ?? null,
            })
          } catch {
            /* non-blocking */
          }
          setStagingArea((prev) => {
            if (!prev) return prev
            const next = removeStagedItemById(prev, sectionKey, itemId)
            if (isStagingAreaEmpty(next)) {
              runReviewCloseCleanup()
              return null
            }
            return next
          })
          return true
        } catch (e) {
          setCommitError(e instanceof Error ? e.message : 'Signal commit failed')
          return false
        } finally {
          setCommittingItemId(null)
        }
      }

      setCommittingItemId(itemId)
      try {
        const slice = stagingForSingleItemCommit(stagingArea, sectionKey, itemId)
        const result = await commitStagedItems(slice, {
          apiPost: apiPost as (path: string, body: unknown) => Promise<{ id: string; title?: string }>,
          existingInitiatives: initiatives,
          existingProjects: projects,
        })
        if (result.errors.length > 0) {
          setCommitError(result.errors.join('; '))
          return false
        }
        const anyCreated =
          result.created.ideas > 0 ||
          result.created.initiatives > 0 ||
          result.created.projects > 0 ||
          result.created.tasks > 0 ||
          result.created.assets > 0 ||
          result.created.persons > 0
        if (anyCreated) {
          fetchIdeas()
          fetchInitiatives()
          fetchProjects()
          fetchTasks()
          fetchAssets()
          fetchPersons()
        }
        try {
          await postMeetingExtractionRecognition(apiPost, {
            meetingId: (extractResult as { meeting_id?: string } | null)?.meeting_id ?? null,
            createdRefs: result.createdRefs,
            signalsCreated: 0,
            userId: recognitionUserId ?? null,
          })
        } catch {
          /* non-blocking */
        }
        setStagingArea((prev) => {
          if (!prev) return prev
          const next = removeStagedItemById(prev, sectionKey, itemId)
          if (isStagingAreaEmpty(next)) {
            runReviewCloseCleanup()
            return null
          }
          return next
        })
        return true
      } catch (e) {
        setCommitError(e instanceof Error ? e.message : 'Commit failed')
        return false
      } finally {
        setCommittingItemId(null)
      }
    },
    [
      stagingArea,
      extractResult,
      initiatives,
      projects,
      removeStagedItemById,
      isStagingAreaEmpty,
      runReviewCloseCleanup,
      fetchIdeas,
      fetchInitiatives,
      fetchProjects,
      fetchTasks,
      fetchAssets,
      fetchPersons,
      recognitionUserId,
      apiPost,
    ]
  )

  const refreshWorkspaceMailbox = useCallback(async () => {
    try {
      const [msgs, uc] = await Promise.all([
        apiGet<WorkspaceMessageRow[]>(`/workspace-messages?box=${workspaceMessageBox}`),
        apiGet<{ count: number }>('/workspace-messages/unread-count'),
      ])
      setWorkspaceMessages(Array.isArray(msgs) ? msgs : [])
      setWorkspaceUnreadCount(typeof uc?.count === 'number' ? uc.count : 0)
    } catch {
      /* optional */
    }
  }, [workspaceMessageBox])

  useEffect(() => {
    if (tab !== 'matching_internal') return
    let cancelled = false
    setWorkspaceMessagesLoading(true)
    refreshWorkspaceMailbox().finally(() => {
      if (!cancelled) setWorkspaceMessagesLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [tab, refreshWorkspaceMailbox])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const uc = await apiGet<{ count: number }>('/workspace-messages/unread-count')
        if (!cancelled) setWorkspaceUnreadCount(typeof uc?.count === 'number' ? uc.count : 0)
      } catch {
        /* not authenticated or API down */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const openSendToModal = useCallback(
    (sectionKey: StagingArraySectionKey, item: StagedItem) => {
      setSendToError(null)
      setSendToRecipientId('')
      setSendToNote('')
      setSendToSeatRequestId('')
      setSendToCapabilityOfferId('')
      setSendToModal({ sectionKey, item })
      void (async () => {
        try {
          const users = await apiGet<WorkspaceDirectoryUser[]>('/workspace-users')
          setWorkspaceUsers(Array.isArray(users) ? users : [])
        } catch {
          setWorkspaceUsers([])
        }
        void fetchSeatRequests()
        void fetchCapabilityOffers()
      })()
    },
    [fetchSeatRequests, fetchCapabilityOffers]
  )

  const appendNoteExistingEntities: ExistingEntities = useMemo(
    () => ({
      initiatives: initiatives.map((i) => ({
        id: i.id,
        title: i.title || '',
        brief: i.brief,
        status: i.status,
      })),
      projects: projects.map((p) => ({
        id: p.id,
        title: p.title || '',
        initiative_id: p.initiative_id,
        brief: p.brief,
        status: p.status,
      })),
      tasks: tasks.map((t) => ({
        id: t.id,
        title: t.title || '',
        project_id: t.project_id,
        description: t.description,
        status: t.status,
      })),
      ideas: ideas.map((i) => ({
        id: i.id,
        title: i.title || '',
        summary: i.summary ?? i.description,
        description: i.description,
      })),
      assets: assets.map((a) => ({ id: a.id, name: a.name || '' })),
      people: persons.map((p) => ({ id: p.id, name: p.name || '' })),
    }),
    [initiatives, projects, tasks, ideas, assets, persons],
  )

  const openAppendNoteModal = useCallback((sectionKey: StagingArraySectionKey, item: StagedItem) => {
    setAppendNoteError(null)
    setAppendNoteModal({ sectionKey, item })
  }, [])

  const handleAppendNotePick = useCallback(
    async (entityType: NoteTargetEntityType, id: string) => {
      if (!appendNoteModal) return
      setAppendNoteSaving(true)
      setAppendNoteError(null)
      const { sectionKey, item } = appendNoteModal
      const path =
        entityType === 'idea'
          ? `/ideas/${id}`
          : entityType === 'initiative'
            ? `/initiatives/${id}`
            : entityType === 'project'
              ? `/projects/${id}`
              : `/tasks/${id}`
      try {
        const block = formatStagedItemForTaskNotes(item)
        const cur = await apiGet<{ notes?: string | null }>(path)
        const prev = (cur.notes ?? '').trim()
        const nextNotes = prev ? `${prev}\n\n${block}` : block
        await apiPatch(path, { notes: nextNotes })
        if (entityType === 'idea') void fetchIdeas()
        else if (entityType === 'initiative') void fetchInitiatives()
        else if (entityType === 'project') void fetchProjects()
        else void fetchTasks()
        setStagingArea((prev) => {
          if (!prev) return prev
          const next = removeStagedItemById(prev, sectionKey, item.id)
          if (isStagingAreaEmpty(next)) {
            runReviewCloseCleanup()
            return null
          }
          return next
        })
      } catch (e) {
        setAppendNoteError(e instanceof Error ? e.message : 'Failed to update notes')
        throw e
      } finally {
        setAppendNoteSaving(false)
      }
    },
    [
      appendNoteModal,
      removeStagedItemById,
      isStagingAreaEmpty,
      runReviewCloseCleanup,
      fetchIdeas,
      fetchInitiatives,
      fetchProjects,
      fetchTasks,
    ],
  )

  const handleConfirmSendTo = useCallback(async () => {
    if (!sendToModal || !sendToRecipientId.trim()) {
      setSendToError('Choose a recipient.')
      return
    }
    setSendToLoading(true)
    setSendToError(null)
    const d = sendToModal.item.data as unknown as Record<string, unknown>
    const title =
      (typeof d.title === 'string' && d.title) ||
      (typeof d.name === 'string' && d.name) ||
      (typeof d.label === 'string' && d.label) ||
      `${sendToModal.sectionKey} candidate`
    try {
      await apiPost('/workspace-messages', {
        to_user_id: sendToRecipientId.trim(),
        title,
        body: {
          kind: 'extraction_candidate',
          section_key: sendToModal.sectionKey,
          item: sendToModal.item,
          ...(sendToNote.trim() ? { note: sendToNote.trim() } : {}),
          ...(sendToSeatRequestId.trim() ? { related_seat_request_id: sendToSeatRequestId.trim() } : {}),
          ...(sendToCapabilityOfferId.trim() ? { related_capability_offer_id: sendToCapabilityOfferId.trim() } : {}),
        },
      })
      setSendToModal(null)
    } catch (e) {
      setSendToError(e instanceof Error ? e.message : 'Send failed')
    } finally {
      setSendToLoading(false)
    }
  }, [sendToModal, sendToRecipientId, sendToNote, sendToSeatRequestId, sendToCapabilityOfferId])

  const applyInboxExtractionMessage = useCallback(async (msg: WorkspaceMessageRow) => {
    const b = msg.body
    if (b.kind !== 'extraction_candidate') {
      setError('This message is not an extraction handoff.')
      return
    }
    const sk = typeof b.section_key === 'string' ? b.section_key : ''
    const item = b.item as StagedItem | undefined
    if (!WORKSPACE_FORWARDABLE_SECTIONS.has(sk) || !item || typeof item !== 'object') {
      setError('Invalid extraction payload in message.')
      return
    }
    try {
      await apiPatch<unknown>('/workspace-messages/' + msg.id + '/read', {})
    } catch {
      /* best-effort */
    }
    try {
      const uc = await apiGet<{ count: number }>('/workspace-messages/unread-count')
      setWorkspaceUnreadCount(typeof uc?.count === 'number' ? uc.count : 0)
    } catch {
      /* ignore */
    }
    setStagingArea((prev) =>
      mergeForwardedCandidateIntoStaging(prev, sk as ForwardableStagingSectionKey, item as StagedItem)
    )
    setWorkspaceMessages((prev) =>
      prev.map((m) => (m.id === msg.id ? { ...m, read_at: m.read_at ?? new Date().toISOString() } : m))
    )
    setTab('meeting_capture')
    setMeetingCaptureView('structured')
    setShowReviewExtraction(true)
    setExpandedWorkspaceMessageId(null)
  }, [])

  const truncateText = (text: unknown, maxChars: number) => {
    const t = veEntityDisplayStr(text).trim()
    if (!t) return ''
    if (t.length <= maxChars) return t
    return `${t.slice(0, maxChars)}…`
  }

  const handleCreateSeatRequest = async () => {
    setError(null)
    try {
      await apiPost<SeatRequestRecord>('/seat-requests', {
        title: seatForm.title || 'Untitled seat request',
        summary: seatForm.summary,
        context_type: seatForm.context_type,
        role_tags: parseTagCsv(seatForm.role_tags_csv),
        capability_tags: parseTagCsv(seatForm.capability_tags_csv),
        availability_window: seatForm.availability_window || null,
        commitment_type: seatForm.commitment_type,
        collaboration_mode: seatForm.collaboration_mode,
        timezone_pref: seatForm.timezone_pref,
      })
      await fetchSeatRequests()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create seat request failed')
    }
  }

  const handleUpdateSeatRequest = async () => {
    if (!selectedSeatRequestId) return
    setError(null)
    try {
      await apiPatch<SeatRequestRecord>(`/seat-requests/${selectedSeatRequestId}`, {
        title: seatForm.title || 'Untitled seat request',
        summary: seatForm.summary,
        context_type: seatForm.context_type,
        role_tags: parseTagCsv(seatForm.role_tags_csv),
        capability_tags: parseTagCsv(seatForm.capability_tags_csv),
        availability_window: seatForm.availability_window || null,
        commitment_type: seatForm.commitment_type,
        collaboration_mode: seatForm.collaboration_mode,
        timezone_pref: seatForm.timezone_pref,
        is_active: seatForm.is_active,
      })
      await fetchSeatRequests()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update seat request failed')
    }
  }

  const handleSeatLifecycle = async (visibility: ShareVisibilityState, index_state: ShareIndexState) => {
    if (!selectedSeatRequestId) return
    if ((visibility === 'shared_unindexed' || visibility === 'shared_indexed') && !seatConsentVersion.trim()) {
      setError('Consent version is required for shared states')
      return
    }
    setError(null)
    try {
      await apiPost<SeatRequestRecord>(`/seat-requests/${selectedSeatRequestId}/share`, {
        visibility,
        index_state,
        consent_version: seatConsentVersion.trim(),
        share_until: seatShareUntil.trim() ? seatShareUntil.trim() : null,
      })
      await fetchSeatRequests()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Seat lifecycle update failed')
    }
  }

  const handleSeatCandidates = async () => {
    if (!selectedSeatRequestId) return
    setError(null)
    try {
      const out = await apiGet<{ seat_request_id: string; candidates: CandidateOffer[] }>(`/seat-requests/${selectedSeatRequestId}/candidate-offers?limit=25`)
      setSeatCandidates(Array.isArray(out?.candidates) ? out.candidates : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Load seat candidates failed')
    }
  }

  const handleCreateCapabilityOffer = async () => {
    setError(null)
    try {
      await apiPost<CapabilityOfferRecord>('/capability-offers', {
        title: offerForm.title || 'Untitled capability offer',
        summary: offerForm.summary,
        role_tags: parseTagCsv(offerForm.role_tags_csv),
        capability_tags: parseTagCsv(offerForm.capability_tags_csv),
        availability_window: offerForm.availability_window || null,
        commitment_type: offerForm.commitment_type,
        collaboration_mode: offerForm.collaboration_mode,
        timezone_pref: offerForm.timezone_pref,
      })
      await fetchCapabilityOffers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create capability offer failed')
    }
  }

  const handleUpdateCapabilityOffer = async () => {
    if (!selectedCapabilityOfferId) return
    setError(null)
    try {
      await apiPatch<CapabilityOfferRecord>(`/capability-offers/${selectedCapabilityOfferId}`, {
        title: offerForm.title || 'Untitled capability offer',
        summary: offerForm.summary,
        role_tags: parseTagCsv(offerForm.role_tags_csv),
        capability_tags: parseTagCsv(offerForm.capability_tags_csv),
        availability_window: offerForm.availability_window || null,
        commitment_type: offerForm.commitment_type,
        collaboration_mode: offerForm.collaboration_mode,
        timezone_pref: offerForm.timezone_pref,
        is_active: offerForm.is_active,
      })
      await fetchCapabilityOffers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update capability offer failed')
    }
  }

  const handleOfferLifecycle = async (visibility: ShareVisibilityState, index_state: ShareIndexState) => {
    if (!selectedCapabilityOfferId) return
    if ((visibility === 'shared_unindexed' || visibility === 'shared_indexed') && !offerConsentVersion.trim()) {
      setError('Consent version is required for shared states')
      return
    }
    setError(null)
    try {
      await apiPost<CapabilityOfferRecord>(`/capability-offers/${selectedCapabilityOfferId}/share`, {
        visibility,
        index_state,
        consent_version: offerConsentVersion.trim(),
        share_until: offerShareUntil.trim() ? offerShareUntil.trim() : null,
      })
      await fetchCapabilityOffers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Offer lifecycle update failed')
    }
  }

  const handleOfferCandidates = async () => {
    if (!selectedCapabilityOfferId) return
    setError(null)
    try {
      const out = await apiGet<{ capability_offer_id: string; candidates: CandidateRequest[] }>(`/capability-offers/${selectedCapabilityOfferId}/candidate-requests?limit=25`)
      setOfferCandidates(Array.isArray(out?.candidates) ? out.candidates : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Load offer candidates failed')
    }
  }

  const handleCreateMaterialRequest = async () => {
    setError(null)
    try {
      await apiPost<MaterialRequestRecord>('/material-requests', {
        title: materialRequestForm.title || 'Untitled material request',
        material_type: materialRequestForm.material_type,
        resource_nature: materialRequestForm.resource_nature,
        category_tags: parseTagCsv(materialRequestForm.category_tags_csv),
        quantity_needed: Number(materialRequestForm.quantity_needed),
        quantity_unit: materialRequestForm.quantity_unit,
        availability_start: materialRequestForm.availability_start || null,
        availability_end: materialRequestForm.availability_end || null,
        condition_min: materialRequestForm.condition_min,
        access_mode: materialRequestForm.access_mode,
        location_region: materialRequestForm.location_region,
        cost_band_max: materialRequestForm.cost_band_max,
      })
      await fetchMaterialRequests()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create material request failed')
    }
  }

  const handleUpdateMaterialRequest = async () => {
    if (!selectedMaterialRequestId) return
    setError(null)
    try {
      await apiPatch<MaterialRequestRecord>(`/material-requests/${selectedMaterialRequestId}`, {
        title: materialRequestForm.title || 'Untitled material request',
        material_type: materialRequestForm.material_type,
        resource_nature: materialRequestForm.resource_nature,
        category_tags: parseTagCsv(materialRequestForm.category_tags_csv),
        quantity_needed: Number(materialRequestForm.quantity_needed),
        quantity_unit: materialRequestForm.quantity_unit,
        availability_start: materialRequestForm.availability_start || null,
        availability_end: materialRequestForm.availability_end || null,
        condition_min: materialRequestForm.condition_min,
        access_mode: materialRequestForm.access_mode,
        location_region: materialRequestForm.location_region,
        cost_band_max: materialRequestForm.cost_band_max,
      })
      await fetchMaterialRequests()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update material request failed')
    }
  }

  const handleMaterialRequestLifecycle = async (visibility: ShareVisibilityState, index_state: ShareIndexState) => {
    if (!selectedMaterialRequestId) return
    if ((visibility === 'shared_unindexed' || visibility === 'shared_indexed') && !materialRequestConsentVersion.trim()) {
      setError('Consent version is required for shared states')
      return
    }
    setError(null)
    try {
      await apiPost<MaterialRequestRecord>(`/material-requests/${selectedMaterialRequestId}/share`, {
        visibility,
        index_state,
        consent_version: materialRequestConsentVersion.trim(),
        share_until: materialRequestShareUntil.trim() ? materialRequestShareUntil.trim() : null,
      })
      await fetchMaterialRequests()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Material request lifecycle update failed')
    }
  }

  const handleMaterialRequestCandidates = async () => {
    if (!selectedMaterialRequestId) return
    setError(null)
    try {
      const out = await apiGet<{ material_request_id: string; candidates: MaterialCandidateOffer[] }>(`/material-requests/${selectedMaterialRequestId}/candidate-offers?limit=25`)
      setMaterialRequestCandidates(Array.isArray(out?.candidates) ? out.candidates : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Load material request candidates failed')
    }
  }

  const handleCreateMaterialOffer = async () => {
    setError(null)
    try {
      await apiPost<MaterialOfferRecord>('/material-offers', {
        title: materialOfferForm.title || 'Untitled material offer',
        material_type: materialOfferForm.material_type,
        resource_nature: materialOfferForm.resource_nature,
        category_tags: parseTagCsv(materialOfferForm.category_tags_csv),
        quantity_available: Number(materialOfferForm.quantity_available),
        quantity_unit: materialOfferForm.quantity_unit,
        availability_start: materialOfferForm.availability_start || null,
        availability_end: materialOfferForm.availability_end || null,
        condition_state: materialOfferForm.condition_state,
        access_mode: materialOfferForm.access_mode,
        location_region: materialOfferForm.location_region,
        cost_band: materialOfferForm.cost_band,
      })
      await fetchMaterialOffers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create material offer failed')
    }
  }

  const handleUpdateMaterialOffer = async () => {
    if (!selectedMaterialOfferId) return
    setError(null)
    try {
      await apiPatch<MaterialOfferRecord>(`/material-offers/${selectedMaterialOfferId}`, {
        title: materialOfferForm.title || 'Untitled material offer',
        material_type: materialOfferForm.material_type,
        resource_nature: materialOfferForm.resource_nature,
        category_tags: parseTagCsv(materialOfferForm.category_tags_csv),
        quantity_available: Number(materialOfferForm.quantity_available),
        quantity_unit: materialOfferForm.quantity_unit,
        availability_start: materialOfferForm.availability_start || null,
        availability_end: materialOfferForm.availability_end || null,
        condition_state: materialOfferForm.condition_state,
        access_mode: materialOfferForm.access_mode,
        location_region: materialOfferForm.location_region,
        cost_band: materialOfferForm.cost_band,
      })
      await fetchMaterialOffers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Update material offer failed')
    }
  }

  const handleMaterialOfferLifecycle = async (visibility: ShareVisibilityState, index_state: ShareIndexState) => {
    if (!selectedMaterialOfferId) return
    if ((visibility === 'shared_unindexed' || visibility === 'shared_indexed') && !materialOfferConsentVersion.trim()) {
      setError('Consent version is required for shared states')
      return
    }
    setError(null)
    try {
      await apiPost<MaterialOfferRecord>(`/material-offers/${selectedMaterialOfferId}/share`, {
        visibility,
        index_state,
        consent_version: materialOfferConsentVersion.trim(),
        share_until: materialOfferShareUntil.trim() ? materialOfferShareUntil.trim() : null,
      })
      await fetchMaterialOffers()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Material offer lifecycle update failed')
    }
  }

  const handleMaterialOfferCandidates = async () => {
    if (!selectedMaterialOfferId) return
    setError(null)
    try {
      const out = await apiGet<{ material_offer_id: string; candidates: MaterialCandidateRequest[] }>(`/material-offers/${selectedMaterialOfferId}/candidate-requests?limit=25`)
      setMaterialOfferCandidates(Array.isArray(out?.candidates) ? out.candidates : [])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Load material offer candidates failed')
    }
  }

  const canTransition = (current: ShareVisibilityState | undefined, next: ShareVisibilityState): boolean => {
    if (!current) return false
    return (UI_ALLOWED_LIFECYCLE_TRANSITIONS[current] || []).includes(next)
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 p-6 max-w-4xl mx-auto w-full">
      <h2 className="text-xl font-semibold text-slate-100 mb-1">Vision → Execution Engine</h2>
      <p className="text-slate-400 text-sm mb-4">
        Capture ideas, evaluate initiatives, run projects and tasks; people, capacity, and assets. Separate backend (no Airtable).
      </p>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 border-b border-slate-700 pb-2 mb-4">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              setTab(t.id)
              setSelectedId(null)
              setShowCreate(false)
              setShowCreateProject(false)
              setShowCreateTask(false)
              setDetailInitiativeId(null)
              setDetailIdeaId(null)
              setDetailProjectId(null)
              setDetailTaskId(null)
              setDetailPersonId(null)
              setDetailAssetId(null)
            }}
            className={`min-h-[44px] px-3 py-1.5 rounded-lg text-sm font-medium ${
              tab === t.id ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-300'
            }`}
          >
            {t.label}
            {t.id === 'matching_internal' && workspaceUnreadCount > 0 ? (
              <span className="ml-1.5 text-sky-300 tabular-nums">({workspaceUnreadCount})</span>
            ) : null}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg bg-red-900/30 border border-red-700 text-red-200 text-sm p-3 mb-4 flex flex-wrap items-center justify-between gap-2">
          <span>
            {error === 'Failed to fetch' || error.toLowerCase().includes('failed to fetch')
              ? 'Cannot reach the API. Is the backend running? Start it with open-cockpit.bat or run from repo root: python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8010'
              : /JSON|parse|"ideas"|"initiatives"|SyntaxError|Unexpected token/i.test(error)
                ? 'Extraction failed: the response was invalid. Try again or use shorter notes.'
                : error}
          </span>
          <button
            type="button"
            onClick={() => {
              setError(null)
              if (tab === 'ideas') fetchIdeas()
              else if (tab === 'execution') { fetchInitiatives(); fetchProjects(); fetchTasks(); fetchPersons(); fetchIdeas() }
              else if (tab === 'people') { fetchPersons(); fetchCapacity() }
              else if (tab === 'assets') fetchAssets()
              else if (tab === 'radar') fetchRadar()
              else if (tab === 'matching_internal') { fetchSeatRequests(); fetchCapabilityOffers(); fetchMaterialRequests(); fetchMaterialOffers() }
              else if (tab === 'meeting_capture') setExtractResult(null)
            }}
            className="px-2 py-1 rounded bg-red-700 hover:bg-red-600 text-white text-xs whitespace-nowrap"
          >
            Retry
          </button>
        </div>
      )}

      {/* Meeting Capture: paste → extract → review → save */}
      {tab === 'meeting_capture' && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">View:</span>
            <button
              type="button"
              onClick={() => setMeetingCaptureView('structured')}
              className={`px-2 py-1 rounded text-xs border ${meetingCaptureView === 'structured' ? 'bg-amber-600 border-amber-500 text-white' : 'bg-slate-800 border-slate-600 text-slate-300'}`}
            >
              Structured view
            </button>
            <button
              type="button"
              onClick={() => setMeetingCaptureView('harvest')}
              className={`px-2 py-1 rounded text-xs border ${meetingCaptureView === 'harvest' ? 'bg-amber-600 border-amber-500 text-white' : 'bg-slate-800 border-slate-600 text-slate-300'}`}
            >
              Harvest view
            </button>
          </div>
          <div className="rounded-lg border border-slate-600 bg-slate-900/50 p-3 text-xs space-y-3">
            <p className="text-slate-500 leading-snug">
              Identity is built from these folders only. Custom roots are saved in this browser (localStorage). Browse
              folder opens the system picker on the computer running the Zenaf API (the same machine the scan reads
              from), not a web-only file dialog.
            </p>
            <div className="space-y-1.5">
              <div className="text-slate-400 font-medium">Effective scan roots (next run)</div>
              <ul className="space-y-1">
                {effectiveWorkspaceScanRoots.length === 0 ? (
                  <li className="rounded border border-slate-700 bg-slate-950/50 px-2 py-1.5 font-mono text-[11px] text-slate-500 break-all">
                    Load status to resolve the default repository path, or add a folder below.
                  </li>
                ) : (
                  effectiveWorkspaceScanRoots.map((r) => (
                    <li
                      key={r}
                      className="flex items-start justify-between gap-2 rounded border border-slate-700 bg-slate-950/50 px-2 py-1 font-mono text-[11px] text-slate-300"
                    >
                      <span className="break-all flex-1">
                        {workspaceScanRootsUser.length === 0 && (
                          <span className="text-amber-400/90 mr-2">Default ·</span>
                        )}
                        {r}
                      </span>
                      {workspaceScanRootsUser.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setWorkspaceScanRootsUser((prev) => prev.filter((x) => x !== r))}
                          className="shrink-0 text-rose-400 hover:text-rose-300"
                          aria-label={`Remove ${r}`}
                        >
                          Remove
                        </button>
                      )}
                    </li>
                  ))
                )}
              </ul>
              {workspaceScanRootsUser.length === 0 && effectiveWorkspaceScanRoots.length > 0 && (
                <p className="text-slate-500 text-[10px] leading-snug">
                  Using the Zenaf repository root. Add absolute paths above to scan your real project folders instead.
                </p>
              )}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <input
                  type="text"
                  value={workspaceScanRootDraft}
                  onChange={(e) => setWorkspaceScanRootDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      commitWorkspaceScanRootDraft()
                    }
                  }}
                  placeholder="Absolute folder path (e.g. C:\Projects\MyWorkspace)"
                  className="flex-1 min-w-[12rem] px-2 py-1 rounded bg-slate-950 border border-slate-600 text-slate-200 text-[11px] font-mono"
                />
                <button
                  type="button"
                  onClick={() => commitWorkspaceScanRootDraft()}
                  className="px-2 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-800"
                >
                  Add root
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void pickWorkspaceFolderFromOs()
                  }}
                  disabled={workspacePickFolderBusy || workspaceScanBusy || workspaceIdentityLoading}
                  className="px-2 py-1 rounded border border-sky-600 text-sky-200 hover:bg-sky-950/40 disabled:opacity-50"
                  title="Native folder dialog on the API host (Windows: Explorer; requires local API)"
                >
                  {workspacePickFolderBusy ? 'Picker open…' : 'Browse folder…'}
                </button>
                {workspaceScanRootsUser.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setWorkspaceScanRootsUser([])}
                    className="px-2 py-1 rounded border border-slate-600 text-slate-400 hover:text-slate-200"
                  >
                    Clear custom roots
                  </button>
                )}
              </div>
            </div>
            {workspaceIdentity?.lastScanSourceRoots && workspaceIdentity.lastScanSourceRoots.length > 0 && (
              <div className="space-y-1">
                <div className="text-slate-400 font-medium">Last snapshot scanned</div>
                <ul className="font-mono text-[11px] text-slate-500 space-y-0.5 break-all">
                  {workspaceIdentity.lastScanSourceRoots.map((p) => (
                    <li key={p}>· {p}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-slate-700/80">
              <span className="text-slate-300 font-medium">Workspace identity</span>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => {
                    void refreshWorkspaceIdentityFromServer()
                  }}
                  disabled={workspaceIdentityLoading || workspaceScanBusy}
                  className="px-2 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                >
                  {workspaceIdentityLoading ? 'Loading…' : 'Reload status'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void runWorkspaceIdentityScan('light_refresh')
                  }}
                  disabled={workspaceScanBusy}
                  className="px-2 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                  title={
                    workspaceScanRootsUser.length > 0
                      ? 'Re-scan your custom roots (no file contents)'
                      : 'Re-scan default repository root (no file contents)'
                  }
                >
                  {workspaceScanBusy ? 'Scanning…' : 'Refresh identity'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void runWorkspaceIdentityScan('deep_initial')
                  }}
                  disabled={workspaceScanBusy}
                  className="px-2 py-1 rounded border border-violet-700 text-violet-200 hover:bg-violet-950/40 disabled:opacity-50"
                  title={
                    workspaceScanRootsUser.length > 0
                      ? 'Deep scan of your custom roots; writes .zenaf/workspace-identity/ (gitignored)'
                      : 'Deep scan of default repository root; writes .zenaf/workspace-identity/ (gitignored)'
                  }
                >
                  Deep rescan
                </button>
              </div>
            </div>
            {workspaceIdentity && (
              <div className="text-slate-500 space-y-1 font-mono leading-relaxed">
                <div>
                  Status:{' '}
                  <span
                    className={
                      veEntityDisplayStr(workspaceIdentity.status) === 'ok'
                        ? 'text-emerald-400'
                        : veEntityDisplayStr(workspaceIdentity.status) === 'branch_mismatch'
                          ? 'text-amber-400'
                          : 'text-slate-400'
                    }
                  >
                    {veEntityDisplayStr(workspaceIdentity.status) || '—'}
                  </span>
                  {veEntityDisplayStr(workspaceIdentity.status) === 'branch_mismatch' && (
                    <span className="text-amber-500/90 ml-2">
                      (snapshot branch {workspaceIdentity.branchKeySnapshot ?? '—'} ≠ current {workspaceIdentity.branchKeyCurrent})
                    </span>
                  )}
                </div>
                {veEntityDisplayStr(workspaceIdentity.status) === 'ok' && workspaceIdentity.snapshotSummary && (
                  <div>
                    Packet v{workspaceIdentity.workspacePacket?.schemaVersion ?? '—'}: literal {workspaceIdentity.workspacePacket?.domainHints?.length ?? 0} · snapshot phrases{' '}
                    {typeof workspaceIdentity.snapshotSummary.domainHintCount === 'number'
                      ? workspaceIdentity.snapshotSummary.domainHintCount
                      : '—'}{' '}
                    · roots{' '}
                    {typeof workspaceIdentity.snapshotSummary.sourceRootCount === 'number'
                      ? workspaceIdentity.snapshotSummary.sourceRootCount
                      : '—'}
                    {typeof workspaceIdentity.snapshotSummary.reasoningThemeCount === 'number'
                      ? ` · reasoning themes ${workspaceIdentity.snapshotSummary.reasoningThemeCount}`
                      : ''}
                    {typeof workspaceIdentity.snapshotSummary.clusterCount === 'number'
                      ? ` · clusters ${workspaceIdentity.snapshotSummary.clusterCount}`
                      : ''}
                    {workspaceIdentity.snapshotSummary.nodeCapReached ? ' · cap hit' : ''}
                  </div>
                )}
                {workspaceIdentity.suggestRefreshDueToAge && veEntityDisplayStr(workspaceIdentity.status) === 'ok' && (
                  <div className="text-amber-400/90">Snapshot older than 7 days — consider Refresh identity.</div>
                )}
                {veEntityDisplayStr(workspaceIdentity.status) === 'ok' &&
                  typeof workspaceIdentity.identityQualityWarning === 'string' &&
                  workspaceIdentity.identityQualityWarning.trim() && (
                  <div className="rounded border border-amber-600/50 bg-amber-950/25 text-amber-100/95 px-2 py-1.5 text-[11px] leading-snug">
                    {workspaceIdentity.identityQualityWarning}
                  </div>
                )}
                {veEntityDisplayStr(workspaceIdentity.status) === 'missing' && (
                  <div className="text-slate-500">No snapshot yet. Run Deep rescan once to populate local mirror (gitignored).</div>
                )}
              </div>
            )}
          </div>
          <div className="rounded-lg border border-slate-600 bg-slate-800/70 px-3 py-2 text-xs space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-slate-200">Workspace mirror (from scan)</span>
              {extractLoading && (
                <span className="text-[11px] text-slate-400">
                  Extraction running — this is the hint surface sent with extract
                </span>
              )}
            </div>
            <p className="text-slate-500 text-[11px] leading-snug">
              Identity is built from these phrases only (folder and file names under your scan roots, bounded scan). Not inferred from meeting text.
            </p>
            {workspaceIdentityLoading ? (
              <p className="text-slate-500">Loading workspace identity…</p>
            ) : !workspaceIdentity ? (
              <p className="text-slate-500">Workspace identity status not loaded.</p>
            ) : veEntityDisplayStr(workspaceIdentity.status) === 'ok' && workspaceMirrorLines.length > 0 ? (
              <ul className="list-disc list-inside space-y-0.5 text-slate-300 text-[11px]">
                {workspaceMirrorLines.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            ) : veEntityDisplayStr(workspaceIdentity.status) === 'missing' ? (
              <p className="text-slate-500">No snapshot yet. Run Deep rescan in Workspace identity above to populate this list.</p>
            ) : veEntityDisplayStr(workspaceIdentity.status) === 'ok' ? (
              <p className="text-slate-500">Snapshot OK but the packet has no phrases yet. Try Deep rescan.</p>
            ) : (
              <p className="text-amber-400/90">
                Mirror not used for extract while status is “{veEntityDisplayStr(workspaceIdentity.status) || '—'}”. Fix branch alignment or rescan from Workspace identity
                above.
              </p>
            )}
          </div>
          {meetingCaptureView === 'harvest' && (
            <div className="rounded-xl border border-slate-600 bg-slate-900/60 p-3">
              <div className="text-xs text-slate-300 mb-2">
                Ordered requirement ledger (recall-first). Items remain visible even when speculative.
              </div>
              {extractResult?.harvest_ledger?.items?.length ? (
                <div className="max-h-72 overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="text-slate-400">
                      <tr>
                        <th className="text-left p-1">#</th>
                        <th className="text-left p-1">Label</th>
                        <th className="text-left p-1">Raw text</th>
                        <th className="text-left p-1">Category</th>
                        <th className="text-left p-1">Spec</th>
                        <th className="text-left p-1">Conf</th>
                      </tr>
                    </thead>
                    <tbody>
                      {extractResult.harvest_ledger.items
                        .slice()
                        .sort((a, b) => (a.ordinal ?? 0) - (b.ordinal ?? 0))
                        .map((it) => (
                          <tr key={it.id} className="border-t border-slate-800 text-slate-200 align-top">
                            <td className="p-1">{it.ordinal}</td>
                            <td className="p-1">{it.label}</td>
                            <td className="p-1 text-slate-300">{it.raw_text}</td>
                            <td className="p-1 text-slate-400">{it.category_hint ?? 'other'}</td>
                            <td className="p-1">{it.speculative ? 'yes' : 'no'}</td>
                            <td className="p-1">{typeof it.confidence === 'number' ? it.confidence.toFixed(2) : '—'}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-xs text-slate-500">No harvest ledger yet. Run extraction to populate it.</div>
              )}
            </div>
          )}
          {extractLoading && !globalExtractionContext && (
            <div className="mt-4 rounded-lg border border-amber-600/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-200">
              Understanding conversation…
            </div>
          )}
          {chunkModeChunks?.length ? (
            <ChunkProgressSimple
              chunkModeChunks={chunkModeChunks}
              chunkModeResults={chunkModeResults}
              extractLoading={extractLoading}
              chunkRunFocus={chunkRunFocus}
              chunkProgressExtractKind={chunkProgressExtractKind}
              onRetryChunk={handleRetryChunk}
              onRetryFailedChunks={handleRetryFailedChunks}
              onStopExtract={stopMeetingExtraction}
            />
          ) : null}
          {meetingExtractPathDiag && !extractLoading ? (
            <p className="text-xs text-slate-500 mt-2 font-mono" title="Last completed extract path">
              extract_path:{' '}
              {meetingExtractPathDiag.engine === 'external'
                ? meetingExtractPathDiag.externalSingleCall
                  ? 'external_single_call'
                  : 'external_chunked'
                : 'local_chunked'}
              {' · '}
              chars={meetingExtractPathDiag.transcriptChars.toLocaleString()}
              {meetingExtractPathDiag.engine === 'external'
                ? ` · threshold=${meetingExtractPathDiag.thresholdChars.toLocaleString()}`
                : ''}
              {' · '}
              calls={meetingExtractPathDiag.extractCalls}
              {meetingExtractPathDiag.documentBudgetApplied ? ' · document_budget=on' : ''}
            </p>
          ) : null}
          <>
            <p className="text-slate-400 text-sm">
              Paste meeting notes or a transcript below, or upload a PDF or text file. Extract structured items, then review and commit only what you approve.
            </p>
            <div
              className={`rounded-xl border p-4 space-y-3 transition-colors ${dragOver ? 'border-amber-500 bg-slate-800/80' : 'border-slate-600 bg-slate-800/50'}`}
              onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setDragOver(true) }}
              onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); setDragOver(false) }}
              onDrop={(e) => {
                e.preventDefault()
                e.stopPropagation()
                setDragOver(false)
                handleMeetingFileSelect(e.dataTransfer.files)
              }}
            >
              <label className="block text-sm font-medium text-slate-300">Meeting notes / transcript</label>
              <input
                ref={meetingFileInputRef}
                type="file"
                accept={ACCEPT_UPLOAD}
                className="hidden"
                onChange={(e) => { handleMeetingFileSelect(e.target.files); e.target.value = '' }}
              />
              <textarea
                value={meetingNotes}
                onChange={(e) => setMeetingNotes(e.target.value)}
                placeholder="Paste notes here or drag a PDF/text file…"
                rows={8}
                className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm resize-y font-mono"
              />
              <p className="text-slate-500 text-xs">
                Local extraction uses sequential chunks for long transcripts. With external AI on, the full transcript is sent in{' '}
                <strong className="text-slate-400 font-medium">one call</strong> when under ~{Math.round(EXTERNAL_EXTRACT_SINGLE_CALL_MAX_CHARS / 1000)}k characters; larger transcripts fall back to chunked calls (then a document-level cap after merge).
              </p>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-slate-700/50 pt-3">
                <label className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    checked={useExternalAiExtraction}
                    onChange={(e) => setUseExternalAiExtraction(e.target.checked)}
                    className="rounded border-slate-500 text-amber-600 focus:ring-amber-500"
                  />
                  <span className="text-slate-300">Use external AI extraction</span>
                </label>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-slate-500 text-sm">AI engine</span>
                  <select
                    value={externalAiEngine}
                    onChange={(e) => setExternalAiEngine(e.target.value)}
                    disabled={!useExternalAiExtraction}
                    aria-label="External AI engine"
                    className="rounded-lg bg-slate-900 border border-slate-600 text-slate-200 text-sm px-2 py-1.5 min-w-[12rem] max-w-[20rem] disabled:opacity-45 disabled:cursor-not-allowed"
                  >
                    <option value="">—</option>
                    {meetingExternalEngineSelectOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                <label
                  className={`flex items-center gap-2 text-sm ${useExternalAiExtraction ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}`}
                  title={
                    useExternalAiExtraction
                      ? 'When on, content is washed before the model call when policy requires safe cloud payloads.'
                      : 'Only applies when external AI extraction is on.'
                  }
                >
                  <input
                    type="checkbox"
                    checked={washDataForCall}
                    onChange={(e) => setWashDataForCall(e.target.checked)}
                    disabled={!useExternalAiExtraction}
                    className="rounded border-slate-500 text-amber-600 focus:ring-amber-500 disabled:cursor-not-allowed"
                  />
                  <span className="text-slate-300">Wash data for this call</span>
                </label>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => meetingFileInputRef.current?.click()}
                  disabled={uploadLoading}
                  className="px-3 py-1.5 rounded-lg border border-slate-500 text-slate-300 hover:bg-slate-700 disabled:opacity-50 text-sm"
                >
                  {uploadLoading ? 'Reading…' : 'Upload PDF or text file'}
                </button>
                <button
                  type="button"
                  onClick={handleExtractMeeting}
                  disabled={
                    extractLoading ||
                    uploadLoading ||
                    !meetingNotes.trim() ||
                    (useExternalAiExtraction && !externalAiEngine.trim())
                  }
                  className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-medium"
                >
                  {extractLoading ? 'Extracting…' : 'Extract items'}
                </button>
                {extractLoading && (
                  <button
                    type="button"
                    onClick={stopMeetingExtraction}
                    className="px-4 py-2 rounded-lg border border-red-500/70 text-red-200 hover:bg-red-950/40 text-sm font-medium"
                  >
                    Stop
                  </button>
                )}
              </div>
            </div>
            {extractResult?.error && !error && (
              <div className="rounded-lg bg-amber-900/30 border border-amber-700 text-amber-200 text-sm p-3">
                <p>{extractResult.message ?? extractResult.error}</p>
                {extractResult.sample && (
                  <p className="mt-2 text-amber-300/80 text-xs font-mono whitespace-pre-wrap break-all">
                    Model output sample: {extractResult.sample}
                  </p>
                )}
              </div>
            )}
          </>
          {meetingCaptureView === 'structured' && showReviewExtraction && stagingArea && (
            <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 mt-4">
              <ReviewExtractionScreen
                staging={stagingArea}
                onStagingChange={setStagingArea}
                onCommit={handleCommitReview}
                onClose={() => {
                  dismissMeetingExtractTraceIfPending()
                  setShowReviewExtraction(false)
                  setCommitError(null)
                }}
                commitLoading={commitLoading}
                commitError={commitError}
                perCardActions
                onCommitOneItem={handleCommitSingleReviewItem}
                onDismissOneItem={handleDismissReviewItem}
                onDismissSummary={handleDismissReviewSummary}
                committingItemId={committingItemId}
                onOpenSendTo={openSendToModal}
                onOpenAppendNote={openAppendNoteModal}
                existingEntities={{
                  initiatives: initiatives.map((i) => ({
                    id: i.id,
                    title: veEntityDisplayStr(i.title),
                    brief: veEntityDisplayStr(i.brief),
                    status: veEntityDisplayStr(i.status),
                  })),
                  projects: projects.map((p) => ({
                    id: p.id,
                    title: veEntityDisplayStr(p.title),
                    initiative_id: p.initiative_id,
                    brief: veEntityDisplayStr(p.brief),
                    status: veEntityDisplayStr(p.status),
                  })),
                  tasks: tasks.map((t) => ({
                    id: t.id,
                    title: veEntityDisplayStr(t.title),
                    project_id: t.project_id,
                    description: veEntityDisplayStr(t.description),
                    status: veEntityDisplayStr(t.status),
                  })),
                  ideas: ideas.map((i) => ({
                    id: i.id,
                    title: veEntityDisplayStr(i.title),
                    summary: veEntityDisplayStr(i.summary ?? i.description),
                    description: veEntityDisplayStr(i.description),
                  })),
                  assets: assets.map((a) => ({ id: a.id, name: veEntityDisplayStr(a.name) })),
                  people: persons.map((p) => ({ id: p.id, name: veEntityDisplayStr(p.name) })),
                }}
                onLinkToExisting={(entityType, id) => {
                  dismissMeetingExtractTraceIfPending()
                  if (entityType === 'initiative') { setTab('execution'); setDetailInitiativeId(id); setDetailProjectId(null); setDetailTaskId(null); setSelectedId(id) }
                  else if (entityType === 'project') { setTab('execution'); setDetailProjectId(id); setDetailInitiativeId(null); setDetailTaskId(null); setSelectedId(id) }
                  else if (entityType === 'task') { setTab('execution'); setDetailTaskId(id); setDetailInitiativeId(null); setSelectedId(id) }
                  else if (entityType === 'idea') { setTab('ideas'); setDetailIdeaId(id); setSelectedId(id) }
                  else if (entityType === 'asset') { setTab('assets'); setDetailAssetId(id); setSelectedId(id) }
                  else if (entityType === 'person') { setTab('people'); setDetailPersonId(id); setSelectedId(id) }
                  setShowReviewExtraction(false)
                }}
                fetchCandidatePlacementSuggestion={async (input) => {
                  const out = await apiPost<CandidatePlacementResponse>('/suggest-candidate-placement', {
                    candidate: input.candidate,
                    existing_entities: input.existingEntities,
                    context: input.context,
                    profileId: input.profileId,
                    client_correlation_id: input.clientCorrelationId,
                    routingContext: meetingExtractionRoutingContext('candidate_placement_suggest'),
                  })
                  traceCandidatePlacementSuggest(
                    (extractResult as { meeting_id?: string } | null)?.meeting_id,
                    input.clientCorrelationId,
                    out,
                  )
                  return out
                }}
                fetchCandidatePresortTriage={async (input) => {
                  const out = await apiPost<CandidatePresortTriageApiResponse>('/presort-candidate-triage', {
                    candidate: input.candidate,
                    existing_entities: input.existingEntities,
                    context: input.context,
                    staged_section: input.stagedSection,
                    client_correlation_id: input.clientCorrelationId,
                    routingContext: meetingExtractionRoutingContext('candidate_presort_triage'),
                  })
                  traceCandidatePresortTriage(
                    (extractResult as { meeting_id?: string } | null)?.meeting_id,
                    input.clientCorrelationId,
                    out,
                  )
                  return out
                }}
                suggestPlacementContext={meetingNotes}
                suggestPlacementProfileId={veCanonicalCoreProfileId}
                placementBulkReady={!extractLoading && !uploadLoading}
              />
            </div>
          )}

        </div>
      )}

      {tab === 'matching_internal' && (
        <div className="space-y-4 flex-1 min-h-0 overflow-auto">
          <p className="text-slate-400 text-sm">
            Internal-only matching surface for testing seat requests, capability offers, lifecycle state, and deterministic candidates.
          </p>

          <div className="rounded-xl border border-sky-800/50 bg-slate-800/50 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-slate-200">Message center</h3>
              <button
                type="button"
                onClick={() => void refreshWorkspaceMailbox()}
                className="text-xs text-sky-400 hover:text-sky-200"
              >
                Refresh
              </button>
            </div>
            <p className="text-xs text-slate-500">
              Use <strong className="text-slate-400">Send to…</strong> on Meeting Capture review cards to hand off an extraction row to another workspace user. Optional links below attach a seat request or capability offer id for context alongside matching.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setWorkspaceMessageBox('inbox')}
                className={`px-2 py-1 rounded text-xs border ${
                  workspaceMessageBox === 'inbox' ? 'bg-sky-900/50 border-sky-600 text-sky-100' : 'border-slate-600 text-slate-300'
                }`}
              >
                Inbox
              </button>
              <button
                type="button"
                onClick={() => setWorkspaceMessageBox('sent')}
                className={`px-2 py-1 rounded text-xs border ${
                  workspaceMessageBox === 'sent' ? 'bg-sky-900/50 border-sky-600 text-sky-100' : 'border-slate-600 text-slate-300'
                }`}
              >
                Sent
              </button>
            </div>
            {workspaceMessagesLoading ? (
              <p className="text-xs text-slate-500">Loading messages…</p>
            ) : workspaceMessages.length === 0 ? (
              <p className="text-xs text-slate-500">No messages.</p>
            ) : (
              <ul className="space-y-2 max-h-72 overflow-y-auto">
                {workspaceMessages.map((m) => {
                  const expanded = expandedWorkspaceMessageId === m.id
                  const isExtraction = m.body?.kind === 'extraction_candidate'
                  const note = typeof m.body?.note === 'string' ? m.body.note : ''
                  const seatRef = typeof m.body?.related_seat_request_id === 'string' ? m.body.related_seat_request_id : ''
                  const offerRef = typeof m.body?.related_capability_offer_id === 'string' ? m.body.related_capability_offer_id : ''
                  const counterpart =
                    workspaceMessageBox === 'inbox' ? m.from_display_name : m.to_display_name
                  return (
                    <li
                      key={m.id}
                      className={`rounded-lg border p-2 text-xs ${
                        m.read_at ? 'border-slate-600 bg-slate-900/30' : 'border-sky-700/60 bg-sky-950/20'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => setExpandedWorkspaceMessageId(expanded ? null : m.id)}
                        className="w-full text-left"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-medium text-slate-200 truncate">{m.title || 'Message'}</span>
                          <span className="text-slate-500 shrink-0">{counterpart}</span>
                        </div>
                        <div className="text-slate-500 mt-0.5">
                          {new Date(m.created_at).toLocaleString()}
                          {!m.read_at && workspaceMessageBox === 'inbox' ? ' · unread' : ''}
                          {isExtraction ? ' · extraction handoff' : ''}
                        </div>
                      </button>
                      {expanded && (
                        <div className="mt-2 pt-2 border-t border-slate-700 space-y-2">
                          {note && <p className="text-slate-400 whitespace-pre-wrap">{note}</p>}
                          {seatRef && (
                            <p className="text-slate-500">
                              Related seat request:{' '}
                              <code className="text-sky-300/90">{seatRef}</code>
                              <button
                                type="button"
                                className="ml-2 text-sky-400 hover:text-sky-200"
                                onClick={() => {
                                  const row = seatRequests.find((r) => r.id === seatRef)
                                  if (row) {
                                    setSelectedSeatRequestId(seatRef)
                                    hydrateSeatForm(row)
                                    setSeatConsentVersion(row.consent_version || '')
                                    setSeatShareUntil(row.share_until || '')
                                    setSeatCandidates([])
                                  }
                                }}
                              >
                                Select in list
                              </button>
                            </p>
                          )}
                          {offerRef && (
                            <p className="text-slate-500">
                              Related capability offer: <code className="text-sky-300/90">{offerRef}</code>
                              <button
                                type="button"
                                className="ml-2 text-sky-400 hover:text-sky-200"
                                onClick={() => {
                                  const row = capabilityOffers.find((r) => r.id === offerRef)
                                  if (row) {
                                    setSelectedCapabilityOfferId(offerRef)
                                    hydrateOfferForm(row)
                                    setOfferConsentVersion(row.consent_version || '')
                                    setOfferShareUntil(row.share_until || '')
                                    setOfferCandidates([])
                                  }
                                }}
                              >
                                Select in list
                              </button>
                            </p>
                          )}
                          {isExtraction && workspaceMessageBox === 'inbox' && (
                            <button
                              type="button"
                              onClick={() => void applyInboxExtractionMessage(m)}
                              className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium"
                            >
                              Add to review extraction
                            </button>
                          )}
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-slate-200">Seat requests</h3>
                <button type="button" onClick={fetchSeatRequests} className="text-xs text-slate-400 hover:text-slate-200">Refresh</button>
              </div>
              <ul className="space-y-2 max-h-44 overflow-y-auto">
                {seatRequests.map((item) => (
                  <li
                    key={item.id}
                    className={`rounded border p-2 text-xs cursor-pointer ${selectedSeatRequestId === item.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-900/40'}`}
                    onClick={() => {
                      setSelectedSeatRequestId(item.id)
                      hydrateSeatForm(item)
                      setSeatConsentVersion(item.consent_version || '')
                      setSeatShareUntil(item.share_until || '')
                      setSeatCandidates([])
                    }}
                  >
                    <div className="font-medium text-slate-200 truncate">{item.title || 'Untitled'}</div>
                    <div className="text-slate-500 mt-0.5">
                      {item.visibility} / {item.index_state}
                    </div>
                  </li>
                ))}
              </ul>
              <div className="grid grid-cols-1 gap-2">
                <input value={seatForm.title} onChange={(e) => setSeatForm((p) => ({ ...p, title: e.target.value }))} placeholder="Title" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <input value={seatForm.context_type} onChange={(e) => setSeatForm((p) => ({ ...p, context_type: e.target.value }))} placeholder="Context type" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <input value={seatForm.role_tags_csv} onChange={(e) => setSeatForm((p) => ({ ...p, role_tags_csv: e.target.value }))} placeholder="Role tags (comma-separated)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <input value={seatForm.capability_tags_csv} onChange={(e) => setSeatForm((p) => ({ ...p, capability_tags_csv: e.target.value }))} placeholder="Capability tags (comma-separated)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <input value={seatForm.availability_window} onChange={(e) => setSeatForm((p) => ({ ...p, availability_window: e.target.value }))} placeholder="Availability window" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <div className="grid grid-cols-3 gap-2">
                  <input value={seatForm.commitment_type} onChange={(e) => setSeatForm((p) => ({ ...p, commitment_type: e.target.value }))} placeholder="Commitment" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <input value={seatForm.collaboration_mode} onChange={(e) => setSeatForm((p) => ({ ...p, collaboration_mode: e.target.value }))} placeholder="Collab mode" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <input value={seatForm.timezone_pref} onChange={(e) => setSeatForm((p) => ({ ...p, timezone_pref: e.target.value }))} placeholder="Timezone" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                </div>
                <textarea value={seatForm.summary} onChange={(e) => setSeatForm((p) => ({ ...p, summary: e.target.value }))} placeholder="Summary (internal)" rows={2} className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs resize-y" />
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={handleCreateSeatRequest} className="px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 text-white text-xs">Create</button>
                <button type="button" disabled={!selectedSeatRequestId} onClick={handleUpdateSeatRequest} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Save</button>
                <button type="button" disabled={!selectedSeatRequestId} onClick={handleSeatCandidates} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Get candidates</button>
              </div>
              <div className="pt-2 border-t border-slate-700 space-y-2">
                <div className="text-xs font-medium text-slate-300">Lifecycle actions</div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                  <input value={seatConsentVersion} onChange={(e) => setSeatConsentVersion(e.target.value)} placeholder="consent_version (required for shared*)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <input value={seatShareUntil} onChange={(e) => setSeatShareUntil(e.target.value)} placeholder="share_until (authoritative for lifecycle actions)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!selectedSeatRequestId || !selectedSeatRequest || !canTransition(selectedSeatRequest.visibility, 'shared_unindexed') || !seatConsentVersion.trim()}
                    onClick={() => handleSeatLifecycle('shared_unindexed', 'shared_unindexed')}
                    className="px-2 py-1 rounded bg-emerald-700 text-white text-xs disabled:opacity-50"
                  >
                    Share
                  </button>
                  <button
                    type="button"
                    disabled={!selectedSeatRequestId || !selectedSeatRequest || !canTransition(selectedSeatRequest.visibility, 'shared_indexed') || !seatConsentVersion.trim()}
                    onClick={() => handleSeatLifecycle('shared_indexed', 'shared_indexed')}
                    className="px-2 py-1 rounded bg-emerald-600 text-white text-xs disabled:opacity-50"
                  >
                    Enable matching / index on
                  </button>
                  <button
                    type="button"
                    disabled={!selectedSeatRequestId || !selectedSeatRequest || selectedSeatRequest.visibility !== 'shared_indexed' || !canTransition(selectedSeatRequest.visibility, 'shared_unindexed') || !seatConsentVersion.trim()}
                    onClick={() => handleSeatLifecycle('shared_unindexed', 'shared_unindexed')}
                    className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50"
                  >
                    Disable matching / index off
                  </button>
                  <button
                    type="button"
                    disabled={!selectedSeatRequestId || !selectedSeatRequest || !canTransition(selectedSeatRequest.visibility, 'revoked')}
                    onClick={() => handleSeatLifecycle('revoked', 'revoked')}
                    className="px-2 py-1 rounded bg-red-700 text-white text-xs disabled:opacity-50"
                  >
                    Revoke
                  </button>
                </div>
              </div>
              <div className="space-y-2 pt-2 border-t border-slate-700">
                <div className="text-xs font-medium text-slate-300">Candidate offers</div>
                {matchingLoading ? <p className="text-xs text-slate-500">Loading…</p> : seatCandidates.length === 0 ? <p className="text-xs text-slate-500">No candidates loaded.</p> : (
                  <ul className="space-y-2 max-h-56 overflow-y-auto">
                    {seatCandidates.map((c) => (
                      <li key={c.capability_offer_id} className="rounded border border-slate-600 bg-slate-900/40 p-2 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-slate-200 truncate">{c.offer.title || 'Untitled offer'}</span>
                          <span className="text-emerald-300">score {c.score.toFixed(4)}</span>
                        </div>
                        <p className="text-slate-400 mt-1">roles: {(c.offer.role_tags || []).join(', ') || '—'} | capabilities: {(c.offer.capability_tags || []).join(', ') || '—'}</p>
                        <p className="text-slate-500">availability: {c.offer.availability_window || '—'} | commitment: {c.offer.commitment_type || '—'} | mode: {c.offer.collaboration_mode || '—'}</p>
                        <pre className="mt-1 text-[10px] text-slate-500 whitespace-pre-wrap">{JSON.stringify(c.rationale, null, 2)}</pre>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-slate-200">Capability offers</h3>
                <button type="button" onClick={fetchCapabilityOffers} className="text-xs text-slate-400 hover:text-slate-200">Refresh</button>
              </div>
              <ul className="space-y-2 max-h-44 overflow-y-auto">
                {capabilityOffers.map((item) => (
                  <li
                    key={item.id}
                    className={`rounded border p-2 text-xs cursor-pointer ${selectedCapabilityOfferId === item.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-900/40'}`}
                    onClick={() => {
                      setSelectedCapabilityOfferId(item.id)
                      hydrateOfferForm(item)
                      setOfferConsentVersion(item.consent_version || '')
                      setOfferShareUntil(item.share_until || '')
                      setOfferCandidates([])
                    }}
                  >
                    <div className="font-medium text-slate-200 truncate">{item.title || 'Untitled'}</div>
                    <div className="text-slate-500 mt-0.5">
                      {item.visibility} / {item.index_state}
                    </div>
                  </li>
                ))}
              </ul>
              <div className="grid grid-cols-1 gap-2">
                <input value={offerForm.title} onChange={(e) => setOfferForm((p) => ({ ...p, title: e.target.value }))} placeholder="Title" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <input value={offerForm.role_tags_csv} onChange={(e) => setOfferForm((p) => ({ ...p, role_tags_csv: e.target.value }))} placeholder="Role tags (comma-separated)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <input value={offerForm.capability_tags_csv} onChange={(e) => setOfferForm((p) => ({ ...p, capability_tags_csv: e.target.value }))} placeholder="Capability tags (comma-separated)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <input value={offerForm.availability_window} onChange={(e) => setOfferForm((p) => ({ ...p, availability_window: e.target.value }))} placeholder="Availability window" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                <div className="grid grid-cols-3 gap-2">
                  <input value={offerForm.commitment_type} onChange={(e) => setOfferForm((p) => ({ ...p, commitment_type: e.target.value }))} placeholder="Commitment" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <input value={offerForm.collaboration_mode} onChange={(e) => setOfferForm((p) => ({ ...p, collaboration_mode: e.target.value }))} placeholder="Collab mode" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <input value={offerForm.timezone_pref} onChange={(e) => setOfferForm((p) => ({ ...p, timezone_pref: e.target.value }))} placeholder="Timezone" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                </div>
                <textarea value={offerForm.summary} onChange={(e) => setOfferForm((p) => ({ ...p, summary: e.target.value }))} placeholder="Summary (internal)" rows={2} className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs resize-y" />
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={handleCreateCapabilityOffer} className="px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 text-white text-xs">Create</button>
                <button type="button" disabled={!selectedCapabilityOfferId} onClick={handleUpdateCapabilityOffer} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Save</button>
                <button type="button" disabled={!selectedCapabilityOfferId} onClick={handleOfferCandidates} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Get candidates</button>
              </div>
              <div className="pt-2 border-t border-slate-700 space-y-2">
                <div className="text-xs font-medium text-slate-300">Lifecycle actions</div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                  <input value={offerConsentVersion} onChange={(e) => setOfferConsentVersion(e.target.value)} placeholder="consent_version (required for shared*)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <input value={offerShareUntil} onChange={(e) => setOfferShareUntil(e.target.value)} placeholder="share_until (authoritative for lifecycle actions)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!selectedCapabilityOfferId || !selectedCapabilityOffer || !canTransition(selectedCapabilityOffer.visibility, 'shared_unindexed') || !offerConsentVersion.trim()}
                    onClick={() => handleOfferLifecycle('shared_unindexed', 'shared_unindexed')}
                    className="px-2 py-1 rounded bg-emerald-700 text-white text-xs disabled:opacity-50"
                  >
                    Share
                  </button>
                  <button
                    type="button"
                    disabled={!selectedCapabilityOfferId || !selectedCapabilityOffer || !canTransition(selectedCapabilityOffer.visibility, 'shared_indexed') || !offerConsentVersion.trim()}
                    onClick={() => handleOfferLifecycle('shared_indexed', 'shared_indexed')}
                    className="px-2 py-1 rounded bg-emerald-600 text-white text-xs disabled:opacity-50"
                  >
                    Enable matching / index on
                  </button>
                  <button
                    type="button"
                    disabled={!selectedCapabilityOfferId || !selectedCapabilityOffer || selectedCapabilityOffer.visibility !== 'shared_indexed' || !canTransition(selectedCapabilityOffer.visibility, 'shared_unindexed') || !offerConsentVersion.trim()}
                    onClick={() => handleOfferLifecycle('shared_unindexed', 'shared_unindexed')}
                    className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50"
                  >
                    Disable matching / index off
                  </button>
                  <button
                    type="button"
                    disabled={!selectedCapabilityOfferId || !selectedCapabilityOffer || !canTransition(selectedCapabilityOffer.visibility, 'revoked')}
                    onClick={() => handleOfferLifecycle('revoked', 'revoked')}
                    className="px-2 py-1 rounded bg-red-700 text-white text-xs disabled:opacity-50"
                  >
                    Revoke
                  </button>
                </div>
              </div>
              <div className="space-y-2 pt-2 border-t border-slate-700">
                <div className="text-xs font-medium text-slate-300">Candidate requests</div>
                {matchingLoading ? <p className="text-xs text-slate-500">Loading…</p> : offerCandidates.length === 0 ? <p className="text-xs text-slate-500">No candidates loaded.</p> : (
                  <ul className="space-y-2 max-h-56 overflow-y-auto">
                    {offerCandidates.map((c) => (
                      <li key={c.seat_request_id} className="rounded border border-slate-600 bg-slate-900/40 p-2 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-slate-200 truncate">{c.seat_request.title || 'Untitled request'}</span>
                          <span className="text-emerald-300">score {c.score.toFixed(4)}</span>
                        </div>
                        <p className="text-slate-400 mt-1">roles: {(c.seat_request.role_tags || []).join(', ') || '—'} | capabilities: {(c.seat_request.capability_tags || []).join(', ') || '—'}</p>
                        <p className="text-slate-500">availability: {c.seat_request.availability_window || '—'} | commitment: {c.seat_request.commitment_type || '—'} | mode: {c.seat_request.collaboration_mode || '—'}</p>
                        <pre className="mt-1 text-[10px] text-slate-500 whitespace-pre-wrap">{JSON.stringify(c.rationale, null, 2)}</pre>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
          <div className="pt-2 border-t border-slate-700">
            <p className="text-slate-400 text-xs mb-3">Material sharing/matching (internal): deterministic fit only, bounded preview data.</p>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-slate-200">Material requests</h3>
                  <button type="button" onClick={fetchMaterialRequests} className="text-xs text-slate-400 hover:text-slate-200">Refresh</button>
                </div>
                <ul className="space-y-2 max-h-44 overflow-y-auto">
                  {materialRequests.map((item) => (
                    <li
                      key={item.id}
                      className={`rounded border p-2 text-xs cursor-pointer ${selectedMaterialRequestId === item.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-900/40'}`}
                      onClick={() => {
                        setSelectedMaterialRequestId(item.id)
                        hydrateMaterialRequestForm(item)
                        setMaterialRequestConsentVersion(item.consent_version || '')
                        setMaterialRequestShareUntil(item.share_until || '')
                        setMaterialRequestCandidates([])
                      }}
                    >
                      <div className="font-medium text-slate-200 truncate">{item.title || 'Untitled'}</div>
                      <div className="text-slate-500 mt-0.5">{item.visibility} / {item.index_state}</div>
                    </li>
                  ))}
                </ul>
                <div className="grid grid-cols-1 gap-2">
                  <input value={materialRequestForm.title} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, title: e.target.value }))} placeholder="Title" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    <input value={materialRequestForm.material_type} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, material_type: e.target.value }))} placeholder="Material type" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialRequestForm.resource_nature} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, resource_nature: e.target.value }))} placeholder="Resource nature" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <input value={materialRequestForm.category_tags_csv} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, category_tags_csv: e.target.value }))} placeholder="Category tags (comma-separated)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    <input value={materialRequestForm.quantity_needed} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, quantity_needed: e.target.value }))} placeholder="Quantity needed" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialRequestForm.quantity_unit} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, quantity_unit: e.target.value }))} placeholder="Quantity unit" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    <input value={materialRequestForm.availability_start} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, availability_start: e.target.value }))} placeholder="Availability start (ISO)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialRequestForm.availability_end} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, availability_end: e.target.value }))} placeholder="Availability end (ISO)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <input value={materialRequestForm.condition_min} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, condition_min: e.target.value }))} placeholder="Condition min" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialRequestForm.access_mode} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, access_mode: e.target.value }))} placeholder="Access mode" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialRequestForm.location_region} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, location_region: e.target.value }))} placeholder="Location region" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <input value={materialRequestForm.cost_band_max} onChange={(e) => setMaterialRequestForm((p) => ({ ...p, cost_band_max: e.target.value }))} placeholder="Cost band max" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={handleCreateMaterialRequest} className="px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 text-white text-xs">Create</button>
                  <button type="button" disabled={!selectedMaterialRequestId} onClick={handleUpdateMaterialRequest} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Save</button>
                  <button type="button" disabled={!selectedMaterialRequestId} onClick={handleMaterialRequestCandidates} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Get candidates</button>
                </div>
                <div className="pt-2 border-t border-slate-700 space-y-2">
                  <div className="text-xs font-medium text-slate-300">Lifecycle actions</div>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    <input value={materialRequestConsentVersion} onChange={(e) => setMaterialRequestConsentVersion(e.target.value)} placeholder="consent_version (required for shared*)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialRequestShareUntil} onChange={(e) => setMaterialRequestShareUntil(e.target.value)} placeholder="share_until (authoritative for lifecycle actions)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={!selectedMaterialRequestId || !selectedMaterialRequest || !canTransition(selectedMaterialRequest.visibility, 'shared_unindexed') || !materialRequestConsentVersion.trim()} onClick={() => handleMaterialRequestLifecycle('shared_unindexed', 'shared_unindexed')} className="px-2 py-1 rounded bg-emerald-700 text-white text-xs disabled:opacity-50">Share</button>
                    <button type="button" disabled={!selectedMaterialRequestId || !selectedMaterialRequest || !canTransition(selectedMaterialRequest.visibility, 'shared_indexed') || !materialRequestConsentVersion.trim()} onClick={() => handleMaterialRequestLifecycle('shared_indexed', 'shared_indexed')} className="px-2 py-1 rounded bg-emerald-600 text-white text-xs disabled:opacity-50">Enable matching / index on</button>
                    <button type="button" disabled={!selectedMaterialRequestId || !selectedMaterialRequest || selectedMaterialRequest.visibility !== 'shared_indexed' || !canTransition(selectedMaterialRequest.visibility, 'shared_unindexed') || !materialRequestConsentVersion.trim()} onClick={() => handleMaterialRequestLifecycle('shared_unindexed', 'shared_unindexed')} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Disable matching / index off</button>
                    <button type="button" disabled={!selectedMaterialRequestId || !selectedMaterialRequest || !canTransition(selectedMaterialRequest.visibility, 'revoked')} onClick={() => handleMaterialRequestLifecycle('revoked', 'revoked')} className="px-2 py-1 rounded bg-red-700 text-white text-xs disabled:opacity-50">Revoke</button>
                  </div>
                </div>
                <div className="space-y-2 pt-2 border-t border-slate-700">
                  <div className="text-xs font-medium text-slate-300">Candidate offers</div>
                  {matchingLoading ? <p className="text-xs text-slate-500">Loading…</p> : materialRequestCandidates.length === 0 ? <p className="text-xs text-slate-500">No candidates loaded.</p> : (
                    <ul className="space-y-2 max-h-56 overflow-y-auto">
                      {materialRequestCandidates.map((c) => (
                        <li key={c.material_offer_id} className="rounded border border-slate-600 bg-slate-900/40 p-2 text-xs">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-slate-200 truncate">{c.offer.title || 'Untitled offer'}</span>
                            <span className="text-emerald-300">score {c.score.toFixed(4)}</span>
                          </div>
                          <p className="text-slate-400 mt-1">{c.offer.material_type || '—'} ({c.offer.resource_nature || '—'}) | tags: {(c.offer.category_tags || []).join(', ') || '—'}</p>
                          <p className="text-slate-500">qty: {c.offer.quantity_available ?? '—'} {c.offer.quantity_unit || ''} | availability: {c.offer.availability_start || '—'} → {c.offer.availability_end || '—'}</p>
                          <p className="text-slate-500">condition: {c.offer.condition_state || '—'} | access: {c.offer.access_mode || '—'} | region: {c.offer.location_region || '—'}</p>
                          <pre className="mt-1 text-[10px] text-slate-500 whitespace-pre-wrap">{JSON.stringify(c.rationale, null, 2)}</pre>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-slate-200">Material offers</h3>
                  <button type="button" onClick={fetchMaterialOffers} className="text-xs text-slate-400 hover:text-slate-200">Refresh</button>
                </div>
                <ul className="space-y-2 max-h-44 overflow-y-auto">
                  {materialOffers.map((item) => (
                    <li
                      key={item.id}
                      className={`rounded border p-2 text-xs cursor-pointer ${selectedMaterialOfferId === item.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-900/40'}`}
                      onClick={() => {
                        setSelectedMaterialOfferId(item.id)
                        hydrateMaterialOfferForm(item)
                        setMaterialOfferConsentVersion(item.consent_version || '')
                        setMaterialOfferShareUntil(item.share_until || '')
                        setMaterialOfferCandidates([])
                      }}
                    >
                      <div className="font-medium text-slate-200 truncate">{item.title || 'Untitled'}</div>
                      <div className="text-slate-500 mt-0.5">{item.visibility} / {item.index_state}</div>
                    </li>
                  ))}
                </ul>
                <div className="grid grid-cols-1 gap-2">
                  <input value={materialOfferForm.title} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, title: e.target.value }))} placeholder="Title" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    <input value={materialOfferForm.material_type} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, material_type: e.target.value }))} placeholder="Material type" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialOfferForm.resource_nature} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, resource_nature: e.target.value }))} placeholder="Resource nature" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <input value={materialOfferForm.category_tags_csv} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, category_tags_csv: e.target.value }))} placeholder="Category tags (comma-separated)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    <input value={materialOfferForm.quantity_available} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, quantity_available: e.target.value }))} placeholder="Quantity available" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialOfferForm.quantity_unit} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, quantity_unit: e.target.value }))} placeholder="Quantity unit" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    <input value={materialOfferForm.availability_start} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, availability_start: e.target.value }))} placeholder="Availability start (ISO)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialOfferForm.availability_end} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, availability_end: e.target.value }))} placeholder="Availability end (ISO)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    <input value={materialOfferForm.condition_state} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, condition_state: e.target.value }))} placeholder="Condition state" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialOfferForm.access_mode} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, access_mode: e.target.value }))} placeholder="Access mode" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialOfferForm.location_region} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, location_region: e.target.value }))} placeholder="Location region" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <input value={materialOfferForm.cost_band} onChange={(e) => setMaterialOfferForm((p) => ({ ...p, cost_band: e.target.value }))} placeholder="Cost band" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={handleCreateMaterialOffer} className="px-2 py-1 rounded bg-amber-600 hover:bg-amber-500 text-white text-xs">Create</button>
                  <button type="button" disabled={!selectedMaterialOfferId} onClick={handleUpdateMaterialOffer} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Save</button>
                  <button type="button" disabled={!selectedMaterialOfferId} onClick={handleMaterialOfferCandidates} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Get candidates</button>
                </div>
                <div className="pt-2 border-t border-slate-700 space-y-2">
                  <div className="text-xs font-medium text-slate-300">Lifecycle actions</div>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
                    <input value={materialOfferConsentVersion} onChange={(e) => setMaterialOfferConsentVersion(e.target.value)} placeholder="consent_version (required for shared*)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                    <input value={materialOfferShareUntil} onChange={(e) => setMaterialOfferShareUntil(e.target.value)} placeholder="share_until (authoritative for lifecycle actions)" className="px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs" />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={!selectedMaterialOfferId || !selectedMaterialOffer || !canTransition(selectedMaterialOffer.visibility, 'shared_unindexed') || !materialOfferConsentVersion.trim()} onClick={() => handleMaterialOfferLifecycle('shared_unindexed', 'shared_unindexed')} className="px-2 py-1 rounded bg-emerald-700 text-white text-xs disabled:opacity-50">Share</button>
                    <button type="button" disabled={!selectedMaterialOfferId || !selectedMaterialOffer || !canTransition(selectedMaterialOffer.visibility, 'shared_indexed') || !materialOfferConsentVersion.trim()} onClick={() => handleMaterialOfferLifecycle('shared_indexed', 'shared_indexed')} className="px-2 py-1 rounded bg-emerald-600 text-white text-xs disabled:opacity-50">Enable matching / index on</button>
                    <button type="button" disabled={!selectedMaterialOfferId || !selectedMaterialOffer || selectedMaterialOffer.visibility !== 'shared_indexed' || !canTransition(selectedMaterialOffer.visibility, 'shared_unindexed') || !materialOfferConsentVersion.trim()} onClick={() => handleMaterialOfferLifecycle('shared_unindexed', 'shared_unindexed')} className="px-2 py-1 rounded border border-slate-500 text-slate-200 text-xs disabled:opacity-50">Disable matching / index off</button>
                    <button type="button" disabled={!selectedMaterialOfferId || !selectedMaterialOffer || !canTransition(selectedMaterialOffer.visibility, 'revoked')} onClick={() => handleMaterialOfferLifecycle('revoked', 'revoked')} className="px-2 py-1 rounded bg-red-700 text-white text-xs disabled:opacity-50">Revoke</button>
                  </div>
                </div>
                <div className="space-y-2 pt-2 border-t border-slate-700">
                  <div className="text-xs font-medium text-slate-300">Candidate requests</div>
                  {matchingLoading ? <p className="text-xs text-slate-500">Loading…</p> : materialOfferCandidates.length === 0 ? <p className="text-xs text-slate-500">No candidates loaded.</p> : (
                    <ul className="space-y-2 max-h-56 overflow-y-auto">
                      {materialOfferCandidates.map((c) => (
                        <li key={c.material_request_id} className="rounded border border-slate-600 bg-slate-900/40 p-2 text-xs">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-slate-200 truncate">{c.request.title || 'Untitled request'}</span>
                            <span className="text-emerald-300">score {c.score.toFixed(4)}</span>
                          </div>
                          <p className="text-slate-400 mt-1">{c.request.material_type || '—'} ({c.request.resource_nature || '—'}) | tags: {(c.request.category_tags || []).join(', ') || '—'}</p>
                          <p className="text-slate-500">qty: {c.request.quantity_needed ?? '—'} {c.request.quantity_unit || ''} | availability: {c.request.availability_start || '—'} → {c.request.availability_end || '—'}</p>
                          <p className="text-slate-500">condition: {c.request.condition_min || '—'} | access: {c.request.access_mode || '—'} | region: {c.request.location_region || '—'}</p>
                          <pre className="mt-1 text-[10px] text-slate-500 whitespace-pre-wrap">{JSON.stringify(c.rationale, null, 2)}</pre>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {sendToModal && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/65 p-4"
          onClick={() => {
            if (!sendToLoading) setSendToModal(null)
          }}
        >
          <div
            className="w-full max-w-md rounded-xl border border-slate-600 bg-slate-900 p-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold text-slate-100 mb-1">Send extraction row</h3>
            <p className="text-xs text-slate-500 mb-3">
              Delivers this card to the recipient’s inbox (Message center on Matching). They can add it to their own review queue.
            </p>
            <label className="block text-xs text-slate-400 mb-1">Recipient</label>
            <select
              value={sendToRecipientId}
              onChange={(e) => setSendToRecipientId(e.target.value)}
              className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-600 text-slate-100 text-sm mb-3"
            >
              <option value="">Choose user…</option>
              {workspaceUsers.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name} ({u.email})
                </option>
              ))}
            </select>
            {workspaceUsers.length === 0 && (
              <p className="text-[11px] text-amber-400/90 mb-2">
                No other workspace users — add another account (e.g. auth admin) to send handoffs.
              </p>
            )}
            <label className="block text-xs text-slate-400 mb-1">Note (optional)</label>
            <textarea
              value={sendToNote}
              onChange={(e) => setSendToNote(e.target.value)}
              rows={2}
              className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-600 text-slate-100 text-sm mb-3 resize-y"
              placeholder="Context for the recipient…"
            />
            <label className="block text-xs text-slate-400 mb-1">Tie to seat request (optional)</label>
            <select
              value={sendToSeatRequestId}
              onChange={(e) => setSendToSeatRequestId(e.target.value)}
              className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-600 text-slate-100 text-sm mb-3"
            >
              <option value="">None</option>
              {seatRequests.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title || r.id}
                </option>
              ))}
            </select>
            <label className="block text-xs text-slate-400 mb-1">Tie to capability offer (optional)</label>
            <select
              value={sendToCapabilityOfferId}
              onChange={(e) => setSendToCapabilityOfferId(e.target.value)}
              className="w-full px-2 py-1.5 rounded bg-slate-800 border border-slate-600 text-slate-100 text-sm mb-3"
            >
              <option value="">None</option>
              {capabilityOffers.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title || r.id}
                </option>
              ))}
            </select>
            {sendToError && <p className="text-xs text-red-300 mb-2">{sendToError}</p>}
            <div className="flex justify-end gap-2 mt-2">
              <button
                type="button"
                disabled={sendToLoading}
                onClick={() => setSendToModal(null)}
                className="px-3 py-1.5 rounded-lg border border-slate-500 text-slate-300 text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={sendToLoading || !sendToRecipientId}
                onClick={() => void handleConfirmSendTo()}
                className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-medium"
              >
                {sendToLoading ? 'Sending…' : 'Send'}
              </button>
            </div>
          </div>
        </div>
      )}

      {appendNoteModal && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/65 p-4"
          onClick={() => {
            if (!appendNoteSaving) {
              setAppendNoteModal(null)
              setAppendNoteError(null)
            }
          }}
        >
          <div className="max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            {appendNoteError && (
              <p className="text-xs text-red-300 mb-2 max-w-[28rem] rounded-lg border border-red-500/40 bg-red-950/30 px-3 py-2">
                {appendNoteError}
              </p>
            )}
            <LinkChooser
              mode="pick_note_target"
              existingEntities={appendNoteExistingEntities}
              onPickNoteTarget={(entityType, eid) => handleAppendNotePick(entityType, eid)}
              onClose={() => {
                setAppendNoteModal(null)
                setAppendNoteError(null)
              }}
            />
          </div>
        </div>
      )}

      {/* Placeholder views for Roadmap and Executive */}
      {tab === 'roadmap' && (
        <RoadmapView initiatives={initiatives} projects={projects} tasks={tasks} persons={persons} />
      )}
      {tab === 'executive' && (
        <ExecutiveView initiatives={initiatives} projects={projects} tasks={tasks} persons={persons} capacityProfiles={capacityProfiles} />
      )}

      {/* Ideas */}
      {tab === 'ideas' && (
        <div className="flex gap-4 flex-1 min-h-0">
          <div className="space-y-4 flex-shrink-0 w-80">
            <div>
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-slate-300">Ideas</h3>
                <div className="flex gap-2">
                  <button type="button" onClick={refetch} className="text-slate-500 hover:text-slate-300 text-xs">Refresh</button>
                  <button type="button" onClick={() => setShowCreate(true)} className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm">Add idea</button>
                </div>
              </div>
              <p className="text-[11px] text-slate-500 mt-1.5">
                Idea Lab — capture, clarify, evaluate, and decide. Your <strong className="text-slate-400">Brand core</strong>{' '}
                and actor lenses live on <strong className="text-slate-400">Foundation</strong> (top nav).
              </p>
            </div>
            {showCreate && <CreateIdeaForm onSave={handleCreateIdea} onCancel={() => setShowCreate(false)} />}
            {loading ? <p className="text-slate-500 text-sm">Loading…</p> : ideas.length === 0 ? <p className="text-slate-500 text-sm">No ideas yet.</p> : (
              <>
              <ul className="space-y-2 max-h-[260px] overflow-y-auto">
                {ideas.filter((i) => !['Parked', 'Advanced'].includes(i.status)).map((i) => {
                  const summaryText = truncateText(i.summary || i.description || '', 88) || 'No details yet'
                  const stage = statusToStage(i.status)
                  const nextStep =
                    stage === 'capture' ? 'Clarify' :
                    stage === 'clarify' ? 'Evaluate' :
                    stage === 'evaluate' ? 'Decide' :
                    'Promote / shelve / reject'
                  const metaParts: string[] = [`Next: ${nextStep}`]
                  if (i.created_by) metaParts.push(`By: ${truncateText(i.created_by, 28)}`)
                  if (i.desired_outcome) metaParts.push(`Outcome: ${truncateText(i.desired_outcome, 44)}`)
                  const metaLine = metaParts.join(' • ')
                  return (
                    <li
                      key={i.id}
                      className={`rounded-lg border p-3 text-sm cursor-pointer ${detailIdeaId === i.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-800/50'}`}
                      onClick={() => { setDetailIdeaId(i.id); setSelectedId(i.id) }}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-medium text-slate-200 truncate">{veEntityDisplayStr(i.title)}</span>
                        <span className="text-slate-500 text-[11px] whitespace-nowrap">{veEntityDisplayStr(i.status)}</span>
                      </div>
                      <p className="text-slate-400 text-xs mt-1 truncate">{summaryText}</p>
                      <div className="mt-1 text-[11px] text-slate-500 truncate">{metaLine}</div>
                    </li>
                  )
                })}
              </ul>
              {ideas.some((i) => i.status === 'Parked') && (
                <div className="mt-3 border-t border-slate-700 pt-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-slate-400">Shelved ideas</span>
                  </div>
                  <ul className="space-y-1 max-h-40 overflow-y-auto">
                    {ideas.filter((i) => i.status === 'Parked').map((i) => {
                      const summaryText = truncateText(i.summary || i.description || '', 82) || 'No details yet'
                      const metaLine = `Next: Re-open • By: ${truncateText(i.created_by || '—', 28)}`
                      return (
                        <li
                          key={i.id}
                          className={`rounded border p-2 text-xs cursor-pointer ${detailIdeaId === i.id ? 'border-amber-500 bg-amber-900/10' : 'border-slate-700 bg-slate-900/40'}`}
                          onClick={() => { setDetailIdeaId(i.id); setSelectedId(i.id) }}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <span className="font-medium text-slate-200 truncate">{veEntityDisplayStr(i.title)}</span>
                            <span className="text-slate-500 text-[10px] whitespace-nowrap">{veEntityDisplayStr(i.status)}</span>
                          </div>
                          <p className="text-slate-400 text-[11px] mt-1 truncate">{summaryText}</p>
                          <div className="mt-1 text-[10px] text-slate-500 truncate">{metaLine}</div>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
              </>
            )}
          </div>
          {detailIdeaId && (
            <IdeaDetailPanel
              ideaId={detailIdeaId}
              ideas={ideas}
              persons={persons}
              assets={assets}
              initiatives={initiatives}
              projects={projects}
              tasks={tasks}
              councilIdeaLabelsRef={councilIdeaLabelsRef}
              onCouncilIdeaLiveLabelsUpdated={onCouncilIdeaLiveLabelsUpdated}
              onClose={() => {
                setDetailIdeaId(null)
                setSelectedId(null)
              }}
              onSaved={() => {
                fetchIdeas()
                fetchInitiatives()
                fetchProjects()
                fetchTasks()
              }}
              apiGet={apiGet}
              apiPatch={apiPatch}
              apiPost={apiPost}
              apiDelete={apiDelete}
            />
          )}
        </div>
      )}

      {/* Execution: unified hierarchy (initiatives → projects → tasks), timeline default */}
      {tab === 'execution' && (
        <div className="flex gap-4 flex-1 min-h-0">
          <div className={`flex flex-col gap-4 min-h-0 ${executionViewMode === 'list' ? 'flex-shrink-0 w-80' : 'flex-1 min-w-0'}`}>
            <div className="flex items-center justify-between flex-wrap gap-2">
              <h3 className="text-sm font-medium text-slate-300">Execution</h3>
              <div className="flex items-center gap-2">
                <ProjectsViewModeToggle value={executionViewMode} onChange={setExecutionViewMode} />
                <button type="button" onClick={() => setShowCreate(true)} className="px-2 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-xs">Add initiative</button>
                <button type="button" onClick={() => setShowCreateProject(true)} className="px-2 py-1.5 rounded-lg border border-slate-500 text-slate-300 hover:bg-slate-700 text-xs">Add project</button>
                <button type="button" onClick={() => setShowCreateTask(true)} className="px-2 py-1.5 rounded-lg border border-slate-500 text-slate-300 hover:bg-slate-700 text-xs">Add task</button>
              </div>
            </div>
            {showCreate && <CreateInitiativeForm onSave={handleCreateInitiative} onCancel={() => setShowCreate(false)} />}
            {showCreateProject && <CreateProjectForm onSave={handleCreateProject} onCancel={() => setShowCreateProject(false)} />}
            {showCreateTask && <CreateTaskForm projects={projects} onSave={handleCreateTask} onCancel={() => setShowCreateTask(false)} />}
            {executionViewMode === 'list' && (
              <>
                {loading ? (
                  <p className="text-slate-500 text-sm">Loading…</p>
                ) : initiatives.length === 0 &&
                  projects.filter((p) => !p.initiative_id).length === 0 &&
                  tasks.filter((t) => !t.project_id).length === 0 ? (
                  <p className="text-slate-500 text-sm">No initiatives, projects, or standalone tasks yet.</p>
                ) : (
                  <div className="space-y-1 max-h-[480px] overflow-y-auto">
                    {initiatives.map((init) => {
                      const initProjects = projects.filter((p) => p.initiative_id === init.id)
                      const initExpanded = executionListExpandedInitiatives.includes(init.id)
                      const summaryText = truncateText(init.brief, 72) || 'No brief'
                      return (
                        <div key={init.id}>
                          <div
                            className={`rounded-lg border p-2.5 text-sm cursor-pointer flex items-start gap-2 ${
                              detailInitiativeId === init.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-800/50'
                            }`}
                            onClick={() => { setDetailInitiativeId(init.id); setDetailProjectId(null); setDetailTaskId(null); setSelectedId(init.id) }}
                          >
                            <span className="text-slate-400 select-none shrink-0" onClick={(e) => { e.stopPropagation(); toggleExecutionListInitiative(init.id) }}>
                              {initProjects.length > 0 ? (initExpanded ? '▼' : '▶') : '·'}
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-medium text-slate-200 truncate">{veEntityDisplayStr(init.title)}</span>
                                <span className="text-slate-500 text-[11px] shrink-0">
                                  Initiative · {veEntityDisplayStr(init.status) || '—'}
                                </span>
                              </div>
                              <p className="text-slate-400 text-xs mt-0.5 truncate">{summaryText}</p>
                            </div>
                          </div>
                          {initExpanded && initProjects.length > 0 && (
                            <div className="ml-4 mt-1 space-y-1 border-l border-slate-600 pl-2">
                              {initProjects.map((p) => {
                                const projTasks = tasks.filter((t) => t.project_id === p.id)
                                const projExpanded = executionListExpandedProjects.includes(p.id)
                                const pSummary = truncateText(p.brief, 60) || 'No brief'
                                return (
                                  <div key={p.id}>
                                    <div
                                      className={`rounded border p-2 text-sm cursor-pointer flex items-start gap-2 ${
                                        detailProjectId === p.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-700/30'
                                      }`}
                                      onClick={(e) => { e.stopPropagation(); setDetailProjectId(p.id); setDetailInitiativeId(null); setDetailTaskId(null); setSelectedId(p.id) }}
                                    >
                                      <span className="text-slate-500 select-none shrink-0" onClick={(e) => { e.stopPropagation(); toggleExecutionListProject(p.id) }}>
                                        {projTasks.length > 0 ? (projExpanded ? '▼' : '▶') : '·'}
                                      </span>
                                      <div className="min-w-0 flex-1">
                                        <div className="flex items-center justify-between gap-2">
                                          <span className="font-medium text-slate-200 truncate">{veEntityDisplayStr(p.title)}</span>
                                          <span className="text-slate-500 text-[11px] shrink-0">
                                            Project · {veEntityDisplayStr(p.status) || '—'}
                                          </span>
                                        </div>
                                        <p className="text-slate-400 text-xs mt-0.5 truncate">{pSummary}</p>
                                      </div>
                                    </div>
                                    {projExpanded && projTasks.length > 0 && (
                                      <div className="ml-4 mt-1 space-y-1 border-l border-slate-600 pl-2">
                                        {projTasks.map((t) => (
                                          <div
                                            key={t.id}
                                            className={`rounded border p-2 text-sm cursor-pointer ${
                                              detailTaskId === t.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-700/20'
                                            }`}
                                            onClick={(e) => { e.stopPropagation(); setDetailTaskId(t.id); setDetailProjectId(p.id); setDetailInitiativeId(null); setSelectedId(t.id) }}
                                          >
                                            <div className="flex items-center justify-between gap-2">
                                              <span className="font-medium text-slate-200 truncate">{veEntityDisplayStr(t.title)}</span>
                                              <span className="text-slate-500 text-[11px] shrink-0">
                                                Task · {veEntityDisplayStr(t.status) || '—'}
                                              </span>
                                            </div>
                                            <p className="text-slate-400 text-xs mt-0.5 truncate">{truncateText(t.description || t.title, 56) || 'No description'}</p>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    })}
                    {projects.filter((p) => !p.initiative_id).length > 0 && (
                      <div className="mt-2 pt-2 border-t border-slate-600">
                        <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">Unanchored projects</div>
                        {projects.filter((p) => !p.initiative_id).map((p) => {
                          const projTasks = tasks.filter((t) => t.project_id === p.id)
                          const projExpanded = executionListExpandedProjects.includes(p.id)
                          const pSummary = truncateText(p.brief, 60) || 'No brief'
                          return (
                            <div key={p.id} className="mb-1">
                              <div
                                className={`rounded border p-2 text-sm cursor-pointer flex items-start gap-2 ${
                                  detailProjectId === p.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-700/30'
                                }`}
                                onClick={(e) => { e.stopPropagation(); setDetailProjectId(p.id); setDetailInitiativeId(null); setDetailTaskId(null); setSelectedId(p.id) }}
                              >
                                <span className="text-slate-500 select-none shrink-0" onClick={(e) => { e.stopPropagation(); toggleExecutionListProject(p.id) }}>
                                  {projTasks.length > 0 ? (projExpanded ? '▼' : '▶') : '·'}
                                </span>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between gap-2">
                                    <span className="font-medium text-slate-200 truncate">{veEntityDisplayStr(p.title)}</span>
                                    <span className="text-slate-500 text-[11px] shrink-0">
                                      Project · {veEntityDisplayStr(p.status) || '—'}
                                    </span>
                                  </div>
                                  <p className="text-slate-400 text-xs mt-0.5 truncate">{pSummary}</p>
                                </div>
                              </div>
                              {projExpanded && projTasks.length > 0 && (
                                <div className="ml-4 mt-1 space-y-1 border-l border-slate-600 pl-2">
                                  {projTasks.map((t) => (
                                    <div
                                      key={t.id}
                                      className={`rounded border p-2 text-sm cursor-pointer ${
                                        detailTaskId === t.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-700/20'
                                      }`}
                                      onClick={(e) => { e.stopPropagation(); setDetailTaskId(t.id); setDetailProjectId(p.id); setDetailInitiativeId(null); setSelectedId(t.id) }}
                                    >
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="font-medium text-slate-200 truncate">{veEntityDisplayStr(t.title)}</span>
                                        <span className="text-slate-500 text-[11px] shrink-0">
                                          Task · {veEntityDisplayStr(t.status) || '—'}
                                        </span>
                                      </div>
                                      <p className="text-slate-400 text-xs mt-0.5 truncate">{truncateText(t.description || t.title, 56) || 'No description'}</p>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                    {tasks.filter((t) => !t.project_id).length > 0 && (
                      <div className="mt-2 pt-2 border-t border-slate-600">
                        <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">Tasks without project</div>
                        <div className="space-y-1">
                          {tasks
                            .filter((t) => !t.project_id)
                            .map((t) => (
                              <div
                                key={t.id}
                                className={`rounded border p-2 text-sm cursor-pointer ${
                                  detailTaskId === t.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-700/20'
                                }`}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setDetailTaskId(t.id)
                                  setDetailProjectId(null)
                                  setDetailInitiativeId(null)
                                  setSelectedId(t.id)
                                }}
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-medium text-slate-200 truncate">{veEntityDisplayStr(t.title)}</span>
                                  <span className="text-slate-500 text-[11px] shrink-0">
                                    Task · {veEntityDisplayStr(t.status) || '—'}
                                  </span>
                                </div>
                                <p className="text-slate-400 text-xs mt-0.5 truncate">
                                  {truncateText(t.description || t.title, 56) || 'No description'}
                                </p>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
            {executionViewMode === 'timeline' && (
              <ProjectsTimelineView
                initiatives={initiatives}
                projects={projects}
                tasks={tasks}
                selectedProjectId={detailProjectId}
                selectedTaskId={detailTaskId}
                onSelectInitiative={(id) => { setDetailInitiativeId(id); setDetailProjectId(null); setDetailTaskId(null); setSelectedId(id ?? null) }}
                onSelectProject={(id) => { setDetailProjectId(id ?? null); setDetailTaskId(null); setSelectedId(id ?? null) }}
                onSelectTask={(id) => { setDetailTaskId(id ?? null); setSelectedId(id ?? null) }}
              />
            )}
          </div>
          {detailTaskId && (
            <TaskDetailPanel
              taskId={detailTaskId}
              projects={projects}
              tasks={tasks}
              persons={persons}
              onClose={() => {
                setDetailTaskId(null)
                setSelectedId(null)
              }}
              onSaved={() => {
                fetchTasks()
              }}
              apiGet={apiGet}
              apiPatch={apiPatch}
              apiPost={apiPost}
              apiDelete={apiDelete}
              serverWriteNonce={councilServerWriteNonce}
            />
          )}
          {!detailTaskId && detailProjectId && (
            <ProjectDetailPanel
              projectId={detailProjectId}
              initiatives={initiatives}
              persons={persons}
              onClose={() => { setDetailProjectId(null); setSelectedId(null) }}
              onSaved={() => { fetchProjects(); fetchTasks() }}
              apiGet={apiGet}
              apiPatch={apiPatch}
              apiPost={apiPost}
              apiDelete={apiDelete}
              serverWriteNonce={councilServerWriteNonce}
            />
          )}
          {!detailTaskId && !detailProjectId && detailInitiativeId && (
            <InitiativeDetailPanel
              initiativeId={detailInitiativeId}
              persons={persons}
              ideas={ideas}
              projects={projects}
              assets={assets}
              onClose={() => { setDetailInitiativeId(null); setSelectedId(null) }}
              onSaved={() => { fetchInitiatives(); fetchProjects() }}
              apiGet={apiGet}
              apiPatch={apiPatch}
              apiPost={apiPost}
              apiDelete={apiDelete}
              serverWriteNonce={councilServerWriteNonce}
            />
          )}
        </div>
      )}

      {/* Team: execution / capacity (single-operator today; collaborators later) */}
      {tab === 'people' && (
        <div className="flex gap-4 flex-1 min-h-0">
          <div className="space-y-4 flex-shrink-0 w-80">
            <div>
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-slate-300">Team</h3>
                <button type="button" onClick={() => setShowCreate(true)} className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm">Add person</button>
              </div>
              <p className="text-[11px] text-slate-500 mt-1.5">
                Today you are typically the only operator. Later: collaborators, clearer assignment, and routing — separate from identity and lenses (see <strong className="text-slate-400">Foundation</strong> in the top nav).
              </p>
            </div>
            {showCreate && <CreatePersonForm onSave={handleCreatePerson} onCancel={() => setShowCreate(false)} />}
            {loading ? (
              <p className="text-slate-500 text-sm">Loading…</p>
            ) : persons.length === 0 ? (
              <p className="text-slate-500 text-sm">
                No people yet — add yourself or placeholders for future collaborators. Capacity and assignments stay here;
                link your <strong className="text-slate-400">Brand core</strong> and lenses under{' '}
                <strong className="text-slate-400">Foundation</strong>.
              </p>
            ) : (
              <ul className="space-y-2 max-h-[400px] overflow-y-auto">
                {persons.map((p) => {
                  const cap = capacityProfiles.find((c) => c.person_id === p.id)
                  const status = getCapacityStatus(cap)
                  const statusClass = status === 'Over capacity' ? 'bg-amber-500/20 text-amber-300 border-amber-500/50' : status === 'Near capacity' ? 'bg-slate-500/20 text-slate-300 border-slate-500/50' : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50'
                  const capLine = cap && (cap.weekly_capacity_hours != null || cap.activeWeeklyHours != null)
                    ? `${cap.activeWeeklyHours ?? 0}h active / ${cap.weekly_capacity_hours ?? 0}h`
                    : null
                  return (
                    <li key={p.id} className={`rounded-lg border p-3 text-sm cursor-pointer ${detailPersonId === p.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-800/50'}`} onClick={() => { setDetailPersonId(p.id); setSelectedId(p.id) }}>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-slate-200">{veEntityDisplayStr(p.name)}</span>
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide border ${statusClass}`}>{status === 'Over capacity' ? 'Over' : status === 'Near capacity' ? 'Near' : 'Available'}</span>
                      </div>
                      {(p.role || p.relationship_type) && <p className="text-slate-500 text-xs mt-0.5">{[p.role, p.relationship_type].filter(Boolean).join(' · ')}</p>}
                      {capLine && <p className="text-slate-400 text-xs mt-0.5">{capLine}</p>}
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
          {detailPersonId && (
            <PersonDetailPanel
              personId={detailPersonId}
              capacityProfiles={capacityProfiles}
              initiatives={initiatives}
              projects={projects}
              tasks={tasks}
              assets={assets}
              onClose={() => { setDetailPersonId(null); setSelectedId(null) }}
              onSaved={() => { fetchPersons(); fetchCapacity() }}
              onAssignmentChange={() => { fetchInitiatives(); fetchProjects(); fetchTasks(); fetchCapacity() }}
              apiGet={apiGet}
              apiPatch={apiPatch}
              apiPut={apiPut}
              apiDelete={apiDelete}
              influenceLinkLists={influenceListBundles}
              canonicalCoreProfileId={veCanonicalCoreProfileId}
            />
          )}
        </div>
      )}

      {/* Assets */}
      {tab === 'assets' && (
        <div className="flex gap-4 flex-1 min-h-0">
          <div className="space-y-4 flex-shrink-0 w-80">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-slate-300">Assets</h3>
              <button type="button" onClick={() => setShowCreate(true)} className="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm">Add asset</button>
            </div>
            {showCreate && <CreateAssetForm onSave={handleCreateAsset} onCancel={() => setShowCreate(false)} />}
            {loading ? <p className="text-slate-500 text-sm">Loading…</p> : assets.length === 0 ? <p className="text-slate-500 text-sm">No assets yet.</p> : (
              <ul className="space-y-2 max-h-[400px] overflow-y-auto">
                {assets.map((a) => (
                  <li key={a.id} className={`rounded-lg border p-3 text-sm cursor-pointer ${detailAssetId === a.id ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-800/50'}`} onClick={() => { setDetailAssetId(a.id); setSelectedId(a.id) }}>
                    <span className="font-medium text-slate-200">{veEntityDisplayStr(a.name)}</span>
                    {veEntityDisplayStr(a.asset_type) ? (
                      <span className="ml-2 text-slate-500 text-xs">{veEntityDisplayStr(a.asset_type)}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {detailAssetId && <AssetDetailPanel assetId={detailAssetId} ideas={ideas} initiatives={initiatives} projects={projects} persons={persons} onClose={() => { setDetailAssetId(null); setSelectedId(null) }} onSaved={() => fetchAssets()} apiGet={apiGet} apiPatch={apiPatch} apiDelete={apiDelete} />}
        </div>
      )}

      {/* Radar — emerging issues, drift, risk: unanchored, stalled, kill candidates, overcapacity, meeting signals */}
      {tab === 'radar' && (
        <div className="space-y-4 flex-1 min-h-0 overflow-auto">
          <p className="text-slate-400 text-sm">What is forming, drifting, or at risk. Domain-derived buckets plus meeting-extraction signals.</p>
          {radarLoading ? (
            <p className="text-slate-500 text-sm">Loading radar…</p>
          ) : !radarData ? (
            <p className="text-slate-500 text-sm">No radar data.</p>
          ) : (
            <>
              <div
                id="ve-radar-bucket-act_now"
                className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 scroll-mt-4"
              >
                <h3 className="text-sm font-medium text-slate-200 mb-1">Attention</h3>
                <p className="text-xs text-slate-500 mb-3">
                  Initiatives approved or active but missing owner, next step, or linked projects
                </p>
                {radarData.act_now.length === 0 ? (
                  <p className="text-slate-500 text-xs">None</p>
                ) : (
                  <ul className="space-y-1.5">
                    {radarData.act_now.map((item) => (
                      <li key={`${item.type}-${item.id}`} className="text-xs text-slate-300 flex flex-wrap gap-x-2 gap-y-0.5">
                        <span className="font-medium">
                          {veEntityDisplayStr(item.title) || veEntityDisplayStr(item.name) || item.id}
                        </span>
                        <span className="text-slate-500">{veEntityDisplayStr(item.type)}</span>
                        {veEntityDisplayStr(item.status) ? (
                          <span className="text-slate-500">{veEntityDisplayStr(item.status)}</span>
                        ) : null}
                        {veEntityDisplayStr(item.reason) ? (
                          <span className="text-amber-400/80">{veEntityDisplayStr(item.reason)}</span>
                        ) : null}
                        {item.weighted_score != null && <span className="text-slate-500">score {item.weighted_score}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div
                id="ve-radar-bucket-blocked"
                className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 scroll-mt-4"
              >
                <h3 className="text-sm font-medium text-slate-200 mb-1">Blocked</h3>
                <p className="text-xs text-slate-500 mb-3">Projects or tasks marked blocked</p>
                {radarData.blocked.length === 0 ? (
                  <p className="text-slate-500 text-xs">None</p>
                ) : (
                  <ul className="space-y-1.5">
                    {radarData.blocked.map((item) => (
                      <li key={`${item.type}-${item.id}`} className="text-xs text-slate-300 flex flex-wrap gap-x-2 gap-y-0.5">
                        <span className="font-medium">
                          {veEntityDisplayStr(item.title) || veEntityDisplayStr(item.name) || item.id}
                        </span>
                        <span className="text-slate-500">{veEntityDisplayStr(item.type)}</span>
                        {veEntityDisplayStr(item.status) ? (
                          <span className="text-slate-500">{veEntityDisplayStr(item.status)}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {([
                  { key: 'unanchored' as const, label: 'Unanchored', desc: 'Projects not linked to an initiative' },
                  { key: 'high_value_stalled' as const, label: 'High-value stalled', desc: 'Score ≥ 70 but not Active' },
                  { key: 'kill_candidates' as const, label: 'Watch / kill candidates', desc: 'Score < 45, not Complete/Killed' },
                  { key: 'overcapacity' as const, label: 'Overcapacity', desc: 'People over their weekly capacity' },
                ]).map(({ key, label, desc }) => (
                  <div
                    key={key}
                    id={`ve-radar-bucket-${key}`}
                    className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 scroll-mt-4"
                  >
                    <h3 className="text-sm font-medium text-slate-200 mb-1">{label}</h3>
                    <p className="text-xs text-slate-500 mb-3">{desc}</p>
                    {radarData[key].length === 0 ? (
                      <p className="text-slate-500 text-xs">None</p>
                    ) : (
                      <ul className="space-y-1.5">
                        {(radarData[key] as RadarItem[]).map((item) => (
                          <li key={`${item.type}-${item.id}`} className="text-xs text-slate-300 flex flex-wrap gap-x-2 gap-y-0.5">
                            <span className="font-medium">
                              {veEntityDisplayStr(item.title) || veEntityDisplayStr(item.name) || item.id}
                            </span>
                            <span className="text-slate-500">{veEntityDisplayStr(item.type)}</span>
                            {veEntityDisplayStr(item.status) ? (
                              <span className="text-slate-500">{veEntityDisplayStr(item.status)}</span>
                            ) : null}
                            {veEntityDisplayStr(item.reason) ? (
                              <span className="text-amber-400/80">{veEntityDisplayStr(item.reason)}</span>
                            ) : null}
                            {item.weighted_score != null && <span className="text-slate-500">score {item.weighted_score}</span>}
                            {item.active_weekly_hours != null && item.weekly_capacity_hours != null && (
                              <span className="text-slate-500">{item.active_weekly_hours}h / {item.weekly_capacity_hours}h</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
              {(radarData.signals?.length ?? 0) > 0 && (
                <div
                  id="ve-radar-bucket-signals"
                  className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 scroll-mt-4"
                >
                  <h3 className="text-sm font-medium text-slate-200 mb-1">Meeting signals</h3>
                  <p className="text-xs text-slate-500 mb-3">From meeting extraction (attention, risk, opportunity, blocker). Source: meeting-extraction.</p>
                  <ul className="space-y-2">
                    {(radarData.signals as RadarSignalItem[]).map((item) => (
                      <li key={item.id} className="text-xs border-l-2 border-slate-600 pl-2">
                        <span className="font-medium text-slate-200">{veEntityDisplayStr(item.title)}</span>
                        <span
                          className={`ml-1.5 px-1.5 py-0.5 rounded text-[10px] ${
                            item.kind === 'risk'
                              ? 'bg-red-900/50'
                              : item.kind === 'blocker'
                                ? 'bg-amber-900/50'
                                : item.kind === 'opportunity'
                                  ? 'bg-emerald-900/50'
                                  : 'bg-slate-600'
                          }`}
                        >
                          {veEntityDisplayStr(item.kind)}
                        </span>
                        {veEntityDisplayStr(item.severity) ? (
                          <span className="text-slate-500 ml-1">· {veEntityDisplayStr(item.severity)}</span>
                        ) : null}
                        {veEntityDisplayStr(item.status) ? (
                          <span className="ml-2 inline-flex items-center rounded-full border border-slate-600 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
                            {veEntityDisplayStr(item.status)}
                          </span>
                        ) : null}
                        {veClip(item.detail, 200) ? (
                          <p className="text-slate-500 mt-0.5">{veClip(item.detail, 200)}</p>
                        ) : null}
                        {veClip(item.source_excerpt, 150) ? (
                          <p className="text-slate-500 mt-0.5 italic">&ldquo;{veClip(item.source_excerpt, 150)}&rdquo;</p>
                        ) : null}
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          {(!veEntityDisplayStr(item.status) || item.status === 'new') && (
                            <>
                              <button
                                type="button"
                                className="px-2 py-0.5 rounded bg-slate-700 text-slate-100 hover:bg-slate-600 transition text-[10px]"
                                onClick={async () => {
                                  try {
                                    await apiPatch(`/signals/${item.id}`, { status: 'acknowledged' })
                                    fetchRadar()
                                  } catch {
                                    // ignore error; radar will stay unchanged
                                  }
                                }}
                              >
                                Acknowledge
                              </button>
                              <button
                                type="button"
                                className="px-2 py-0.5 rounded bg-emerald-700 text-slate-100 hover:bg-emerald-600 transition text-[10px]"
                                onClick={async () => {
                                  try {
                                    await apiPatch(`/signals/${item.id}`, { status: 'resolved' })
                                    fetchRadar()
                                  } catch {
                                    // ignore error
                                  }
                                }}
                              >
                                Resolve
                              </button>
                              <button
                                type="button"
                                className="px-2 py-0.5 rounded bg-slate-800 text-slate-200 hover:bg-slate-700 transition text-[10px]"
                                onClick={async () => {
                                  try {
                                    await apiPatch(`/signals/${item.id}`, { status: 'dismissed' })
                                    fetchRadar()
                                  } catch {
                                    // ignore error
                                  }
                                }}
                              >
                                Dismiss
                              </button>
                            </>
                          )}
                          {(item.status === 'acknowledged' || item.status === 'linked') && (
                            <>
                              <button
                                type="button"
                                className="px-2 py-0.5 rounded bg-emerald-700 text-slate-100 hover:bg-emerald-600 transition text-[10px]"
                                onClick={async () => {
                                  try {
                                    await apiPatch(`/signals/${item.id}`, { status: 'resolved' })
                                    fetchRadar()
                                  } catch {
                                    // ignore error
                                  }
                                }}
                              >
                                Resolve
                              </button>
                              <button
                                type="button"
                                className="px-2 py-0.5 rounded bg-slate-800 text-slate-200 hover:bg-slate-700 transition text-[10px]"
                                onClick={async () => {
                                  try {
                                    await apiPatch(`/signals/${item.id}`, { status: 'dismissed' })
                                    fetchRadar()
                                  } catch {
                                    // ignore error
                                  }
                                }}
                              >
                                Dismiss
                              </button>
                            </>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// --- Inline create forms (minimal for Phase 1) ---

/** Stable synthetic ids so focus bar + voice/rewrite events route to inline create forms before save. */
const VE_NEW_IDEA_FOCUS_ID = '__ve_new_idea__'
const VE_NEW_INITIATIVE_FOCUS_ID = '__ve_new_initiative__'
const VE_NEW_PROJECT_FOCUS_ID = '__ve_new_project__'
const VE_NEW_TASK_FOCUS_ID = '__ve_new_task__'

function CreateIdeaForm({
  onSave,
  onCancel,
}: {
  onSave: (v: { title: string; summary?: string; description?: string }) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState('')
  const [note, setNote] = useState('')

  useEffect(() => {
    const onRewrite = (e: Event) => {
      const d = (e as CustomEvent<VeFocusApplyRewriteDetail>).detail
      if (!d || d.entity_type !== 'idea' || d.entity_id !== VE_NEW_IDEA_FOCUS_ID || !d.text) return
      if (d.field_key === 'title') setTitle(d.text)
      if (d.field_key === 'summary') setNote(d.text)
    }
    const onInsert = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d || d.entity_type !== 'idea' || d.entity_id !== VE_NEW_IDEA_FOCUS_ID || !d.text) return
      if (d.field_key === 'title') {
        setTitle((prev) => insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd))
      }
      if (d.field_key === 'summary') {
        setNote((prev) => insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd))
      }
    }
    window.addEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    return () => {
      window.removeEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
      window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    }
  }, [])

  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
      <p className="text-slate-500 text-xs">Capture the idea. Refine later in Clarify.</p>
      <VeFocusRegion
        entity_type="idea"
        entity_id={VE_NEW_IDEA_FOCUS_ID}
        field_key="title"
        field_label="Title"
        field_kind="idea_body"
        getCurrentText={() => title}
      >
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
        />
      </VeFocusRegion>
      <VeFocusRegion
        entity_type="idea"
        entity_id={VE_NEW_IDEA_FOCUS_ID}
        field_key="summary"
        field_label="Short note"
        field_kind="idea_body"
        getCurrentText={() => note}
      >
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Quick note (optional)"
          rows={2}
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm resize-none"
        />
      </VeFocusRegion>
      <div className="flex gap-2">
        <button type="button" onClick={() => onSave({ title, summary: note || undefined, description: undefined })} className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm">
          Save
        </button>
        <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}

function CreateInitiativeForm({
  onSave,
  onCancel,
}: {
  onSave: (v: { title: string; brief?: string }) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState('')
  const [brief, setBrief] = useState('')

  useEffect(() => {
    const onRewrite = (e: Event) => {
      const d = (e as CustomEvent<VeFocusApplyRewriteDetail>).detail
      if (!d || d.entity_type !== 'initiative' || d.entity_id !== VE_NEW_INITIATIVE_FOCUS_ID || !d.text) return
      if (d.field_key === 'title') setTitle(d.text)
      if (d.field_key === 'brief') setBrief(d.text)
    }
    const onInsert = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d || d.entity_type !== 'initiative' || d.entity_id !== VE_NEW_INITIATIVE_FOCUS_ID || !d.text) return
      if (d.field_key === 'title') {
        setTitle((prev) => insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd))
      }
      if (d.field_key === 'brief') {
        setBrief((prev) => insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd))
      }
    }
    window.addEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    return () => {
      window.removeEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
      window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    }
  }, [])

  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
      <VeFocusRegion
        entity_type="initiative"
        entity_id={VE_NEW_INITIATIVE_FOCUS_ID}
        field_key="title"
        field_label="Title"
        field_kind="idea_body"
        getCurrentText={() => title}
      >
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
        />
      </VeFocusRegion>
      <VeFocusRegion
        entity_type="initiative"
        entity_id={VE_NEW_INITIATIVE_FOCUS_ID}
        field_key="brief"
        field_label="Brief"
        field_kind="long_form_strategy"
        getCurrentText={() => brief}
      >
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="Brief (optional)"
          rows={2}
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm resize-none"
        />
      </VeFocusRegion>
      <div className="flex gap-2">
        <button type="button" onClick={() => onSave({ title, brief })} className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm">
          Save
        </button>
        <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}

function CreateProjectForm({
  onSave,
  onCancel,
}: {
  onSave: (v: { title: string; brief?: string }) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState('')
  const [brief, setBrief] = useState('')

  useEffect(() => {
    const onRewrite = (e: Event) => {
      const d = (e as CustomEvent<VeFocusApplyRewriteDetail>).detail
      if (!d || d.entity_type !== 'project' || d.entity_id !== VE_NEW_PROJECT_FOCUS_ID || !d.text) return
      if (d.field_key === 'title') setTitle(d.text)
      if (d.field_key === 'brief') setBrief(d.text)
    }
    const onInsert = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d || d.entity_type !== 'project' || d.entity_id !== VE_NEW_PROJECT_FOCUS_ID || !d.text) return
      if (d.field_key === 'title') {
        setTitle((prev) => insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd))
      }
      if (d.field_key === 'brief') {
        setBrief((prev) => insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd))
      }
    }
    window.addEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    return () => {
      window.removeEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
      window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    }
  }, [])

  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
      <VeFocusRegion
        entity_type="project"
        entity_id={VE_NEW_PROJECT_FOCUS_ID}
        field_key="title"
        field_label="Title"
        field_kind="idea_body"
        getCurrentText={() => title}
      >
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
        />
      </VeFocusRegion>
      <VeFocusRegion
        entity_type="project"
        entity_id={VE_NEW_PROJECT_FOCUS_ID}
        field_key="brief"
        field_label="Brief"
        field_kind="long_form_strategy"
        getCurrentText={() => brief}
      >
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="Brief (optional)"
          rows={2}
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm resize-none"
        />
      </VeFocusRegion>
      <div className="flex gap-2">
        <button type="button" onClick={() => onSave({ title, brief })} className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm">
          Save
        </button>
        <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}

function CreateTaskForm({
  projects,
  onSave,
  onCancel,
}: {
  projects: Project[]
  onSave: (v: { project_id: string | null; title: string }) => void
  onCancel: () => void
}) {
  const [projectId, setProjectId] = useState('')
  const [title, setTitle] = useState('')

  useEffect(() => {
    const onRewrite = (e: Event) => {
      const d = (e as CustomEvent<VeFocusApplyRewriteDetail>).detail
      if (!d || d.entity_type !== 'task' || d.entity_id !== VE_NEW_TASK_FOCUS_ID || !d.text) return
      if (d.field_key === 'title') setTitle(d.text)
    }
    const onInsert = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d || d.entity_type !== 'task' || d.entity_id !== VE_NEW_TASK_FOCUS_ID || !d.text) return
      if (d.field_key === 'title') {
        setTitle((prev) => insertTextAtSelection(prev, d.text, d.selectionStart, d.selectionEnd))
      }
    }
    window.addEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    return () => {
      window.removeEventListener(ZENAF_VE_FOCUS_APPLY_REWRITE, onRewrite)
      window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    }
  }, [])

  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
      <select
        value={projectId}
        onChange={(e) => setProjectId(e.target.value)}
        className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
        aria-label="Project (optional)"
      >
        <option value="">No project (standalone task)</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {veEntityDisplayStr(p.title) || p.id}
          </option>
        ))}
      </select>
      <VeFocusRegion
        entity_type="task"
        entity_id={VE_NEW_TASK_FOCUS_ID}
        field_key="title"
        field_label="Task title"
        field_kind="idea_body"
        getCurrentText={() => title}
      >
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Task title"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
        />
      </VeFocusRegion>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onSave({ project_id: projectId.trim() ? projectId : null, title })}
          className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm"
        >
          Save
        </button>
        <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}

function CreatePersonForm({
  onSave,
  onCancel,
}: {
  onSave: (v: { name: string; role?: string }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [role, setRole] = useState('')
  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name"
        className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
      />
      <input
        type="text"
        value={role}
        onChange={(e) => setRole(e.target.value)}
        placeholder="Role (optional)"
        className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
      />
      <div className="flex gap-2">
        <button type="button" onClick={() => onSave({ name, role })} className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm">
          Save
        </button>
        <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}

function CreateAssetForm({
  onSave,
  onCancel,
}: {
  onSave: (v: { name: string; asset_type?: string }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [assetType, setAssetType] = useState('')
  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/50 p-4 space-y-3">
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Asset name"
        className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
      />
      <input
        type="text"
        value={assetType}
        onChange={(e) => setAssetType(e.target.value)}
        placeholder="Type (optional)"
        className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
      />
      <div className="flex gap-2">
        <button type="button" onClick={() => onSave({ name, asset_type: assetType })} className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm">
          Save
        </button>
        <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg bg-slate-600 text-slate-200 text-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}
