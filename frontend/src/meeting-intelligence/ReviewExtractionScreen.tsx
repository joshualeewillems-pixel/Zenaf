/**
 * Review Extraction screen: human-judgment editor for extracted candidates before commit.
 *
 * System law: AI surfaces neutral candidates; humans commit structure. Meeting extraction
 * outputs observations with confidence and provenance—not final entity types. Staging is the
 * commit gate. Typed rows and default “idea” staging are transitional compatibility, not
 * source truth from the extractor.
 *
 * Editable title/summary, user-chosen type, hierarchy placement, people/assets, evidence.
 * Link = attach to existing (use as same or place under as child).
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import type { StagingArea, StagedItem, StagedItemBase, StagedSummary, CommitableStagedKind } from './stagingTypes'
import { findBestMatch, titleSimilarity } from './duplicateDetection'
import { sortStagedItems, getSectionSummary, type SectionSummaryCounts } from './reviewPriority'
import {
  acceptHighConfidence,
  acceptExtractorMatches,
  rejectLowConfidence,
  acceptSegment,
  acceptSection,
  getSegmentIdsFromItems,
  useExtractorMatches,
  useHeuristicMatches,
  useSegmentMatches,
  clearAcceptedExisting,
} from './reviewBatchActions'
import type { ExtractedConfidence } from './types'
import { LinkChooser } from './LinkChooser'
import { EntityChipSelect } from './EntityChipSelect'
import { buildCommitPreview } from './commitStaged'
import type { StagingArraySectionKey } from './commitStaged'
import {
  buildStagingPatchFromPlacementSuggestion,
  type CandidatePlacementResponse,
} from './candidatePlacementSuggest'
import {
  buildPresortTriageCandidate,
  mapPresortTriageApiToStagingPatch,
  type CandidatePresortTriageApiResponse,
  type PresortTriageCandidatePayload,
} from './candidatePresortTriage'
import type { PresortBucket } from './stagingTypes'

/** Lightweight confirmation for bulk review shortcuts (accept / reject / match many at once). */
function confirmBulkAction(message: string, run: () => void) {
  if (typeof window !== 'undefined' && window.confirm(message)) run()
}

function presortBucketDisplayLabel(b: PresortBucket): string {
  if (b === 'existing') return 'Existing'
  if (b === 'new') return 'New'
  return 'Unsure'
}

function PresortTriageBadge({ item, compact = false }: { item: StagedItem; compact?: boolean }) {
  const b = item.presortBucket
  if (!b) return null
  const cls =
    b === 'existing'
      ? 'bg-emerald-950/60 text-emerald-200 border-emerald-700/50'
      : b === 'new'
        ? 'bg-sky-950/50 text-sky-200 border-sky-700/45'
        : 'bg-amber-950/45 text-amber-200 border-amber-700/45'
  const reason = item.presortReason?.trim()
  const hint =
    b === 'existing' && item.presortExistingTitle
      ? `Likely: ${item.presortExistingTitle}`
      : item.presortConfidence != null
        ? `Confidence ${Math.round(item.presortConfidence * 100)}%`
        : undefined
  const typeSuffix = item.presortType && b !== 'existing' ? ` · ${item.presortType}` : ''
  const titleParts = [presortBucketDisplayLabel(b) + typeSuffix, reason, hint].filter(Boolean)
  return (
    <span
      className={`inline-flex items-center gap-0.5 font-medium border rounded-md ${cls} ${
        compact ? 'text-[10px] px-1.5 py-0.5 uppercase tracking-wide' : 'text-xs px-2 py-0.5'
      }`}
      title={titleParts.join(' · ')}
    >
      {presortBucketDisplayLabel(b)}
      {item.presortType && b !== 'existing' ? (
        <span className="font-normal opacity-90 normal-case">({item.presortType})</span>
      ) : null}
    </span>
  )
}

function formatSectionSummary(c: SectionSummaryCounts): string {
  const parts: string[] = []
  if (c.lowConfidence > 0) parts.push(`${c.lowConfidence} low-confidence`)
  if (c.blockers > 0) parts.push(`${c.blockers} blocker${c.blockers !== 1 ? 's' : ''}`)
  if (c.possibleDuplicates > 0) parts.push(`${c.possibleDuplicates} possible duplicate${c.possibleDuplicates !== 1 ? 's' : ''}`)
  return parts.join(' · ')
}

/** Existing domain entities for duplicate detection (by title or name). */
export interface ExistingEntities {
  initiatives?: {
    id: string
    title: string
    brief?: string | null
    status?: string | null
  }[]
  projects?: {
    id: string
    title: string
    initiative_id?: string | null
    brief?: string | null
    status?: string | null
  }[]
  tasks?: {
    id: string
    title: string
    project_id?: string | null
    description?: string | null
    status?: string | null
  }[]
  ideas?: { id: string; title: string; summary?: string | null; description?: string | null }[]
  assets?: { id: string; name: string }[]
  people?: { id: string; name: string }[]
}

export interface ReviewExtractionScreenProps {
  staging: StagingArea
  onStagingChange: (next: StagingArea) => void
  onCommit: () => void
  onClose: () => void
  commitLoading?: boolean
  commitError?: string | null
  /** Pass to enable "Possible match" suggestions during review. */
  existingEntities?: ExistingEntities | null
  /** Called when user clicks "View existing" on a possible match (e.g. open that entity in parent). */
  onLinkToExisting?: (entityType: 'initiative' | 'project' | 'task' | 'idea' | 'asset' | 'person', id: string) => void
  /** Called when user clicks "Use existing" to accept extractor/heuristic match (commit will skip creating duplicate). */
  onUseExisting?: (entityType: 'initiative' | 'project' | 'task' | 'idea' | 'asset' | 'person', index: number, existingId: string) => void
  /** Per-card Create / Dismiss instead of checkboxes + global commit (Vision Execution review). */
  perCardActions?: boolean
  /** Return `true` when the item was committed (or removed as “use existing”) so the UI can close the detail modal. */
  onCommitOneItem?: (sectionKey: StagingArraySectionKey, itemId: string) => boolean | Promise<boolean | void> | void
  onDismissOneItem?: (sectionKey: StagingArraySectionKey, index: number) => void
  /** When per-card mode: remove meeting summary row from staging. */
  onDismissSummary?: () => void
  committingItemId?: string | null
  /** Open modal to send this staged row to another workspace user (inbox). */
  onOpenSendTo?: (sectionKey: StagingArraySectionKey, item: StagedItem) => void
  /** Open picker (execution tree + ideas) to append this row as a dated block on an existing record’s notes (no new entity). */
  onOpenAppendNote?: (sectionKey: StagingArraySectionKey, item: StagedItem) => void
  /** When set, shows “Suggest placement” per card; calls POST suggest-candidate-placement (no auto-save). */
  fetchCandidatePlacementSuggestion?: (input: {
    candidate: { title: string; summary: string; evidence_quote?: string }
    existingEntities: ExistingEntities
    context?: string
    profileId?: string | null
    clientCorrelationId?: string
  }) => Promise<CandidatePlacementResponse>
  /** Optional meeting/transcript context for placement model (bounded server-side). */
  suggestPlacementContext?: string | null
  /** When set, server loads this core profile for profile-aware placement (omit for semantic-only). */
  suggestPlacementProfileId?: string | null
  /**
   * Coarse batch triage only (existing / new / unsure). When set, “Presort all” uses this instead of detailed placement.
   */
  fetchCandidatePresortTriage?: (input: {
    candidate: PresortTriageCandidatePayload
    existingEntities: ExistingEntities
    context?: string
    /** Staging section key (ideas, initiatives, …) so the server can apply section-specific extractor heuristics. */
    stagedSection?: string
    /** Echoed as client_correlation_id on the response for bulk correlation. */
    clientCorrelationId?: string
  }) => Promise<CandidatePresortTriageApiResponse>
  /**
   * When false, top-level “Presort all” stays disabled
   * (e.g. while extraction or file upload is still running). Defaults to true.
   */
  placementBulkReady?: boolean
}

/** Shallow clone staging so bulk placement can merge row-by-row without mutating props. */
function cloneStagingArea(s: StagingArea): StagingArea {
  return {
    summary: s.summary,
    insights: s.insights.slice(),
    ideas: s.ideas.slice(),
    initiatives: s.initiatives.slice(),
    projects: s.projects.slice(),
    tasks: s.tasks.slice(),
    assets: s.assets.slice(),
    people: s.people.slice(),
    signals: (s.signals ?? []).slice(),
  }
}

/** Rows that participate in placement presort (same order as batch iteration). */
function countStagedPlacementCandidates(s: StagingArea): number {
  return (
    s.ideas.length +
    s.initiatives.length +
    s.projects.length +
    s.tasks.length +
    s.assets.length +
    s.people.length +
    (s.signals ?? []).length +
    s.insights.length
  )
}

function Section({
  title,
  summary,
  actions,
  children,
}: {
  title: string
  summary?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div>
      <h4 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">{title}</h4>
      {summary && <p className="text-slate-500 text-xs mb-1.5">{summary}</p>}
      {actions && <div className="flex flex-wrap gap-1 mb-1.5">{actions}</div>}
      {children}
    </div>
  )
}

type SectionArrayKey = 'insights' | 'ideas' | 'initiatives' | 'projects' | 'tasks' | 'assets' | 'people' | 'signals'

const LINKING_SECTIONS: SectionArrayKey[] = ['ideas', 'initiatives', 'projects', 'tasks', 'assets', 'people', 'signals']

function placementItemKey(sectionKey: SectionArrayKey, itemId: string): string {
  return `${sectionKey}:${itemId}`
}

function cloneStagedItem(item: StagedItem): StagedItem {
  try {
    if (typeof structuredClone === 'function') {
      return structuredClone(item)
    }
  } catch {
    /* fall through */
  }
  return JSON.parse(JSON.stringify(item)) as StagedItem
}

function titleCaseFit(v: string | null | undefined): string {
  if (!v) return ''
  const t = v.toLowerCase()
  return t.charAt(0).toUpperCase() + t.slice(1)
}

function describePlacementSummary(hint: CandidatePlacementResponse): string {
  const m = hint.placement_mode
  if ((m === 'attach' || m === 'amend') && hint.target?.title) {
    return m === 'amend'
      ? `Amend / attach to “${hint.target.title}” (${hint.target.type})`
      : `Attach to “${hint.target.title}” (${hint.target.type})`
  }
  if (m === 'new' && hint.suggested_parent?.title) {
    return `New under “${hint.suggested_parent.title}” (${hint.suggested_parent.type})`
  }
  return 'New (no parent link)'
}

function combinePlacementWhy(hint: CandidatePlacementResponse): string {
  const pr = (hint.profile_reason || '').trim()
  const r = (hint.reason || '').trim()
  const s = pr && r && pr !== r ? `${pr} · ${r}` : pr || r
  return s.length > 420 ? `${s.slice(0, 417)}…` : s
}

/** Set to true to log Link flow (sectionKey, kind, title/id) for debugging onCloseLinkChooser. */
const DEBUG_LINK_FLOW = false

function SectionBatchActions({
  sectionKey,
  items,
  staging,
  onStagingChange,
  existingEntities,
}: {
  sectionKey: SectionArrayKey
  items: StagedItem[]
  staging: StagingArea
  onStagingChange: (next: StagingArea) => void
  existingEntities?: ExistingEntities | null
}) {
  const apply = (next: StagedItem[]) => {
    onStagingChange({ ...staging, [sectionKey]: next })
  }
  const segments = getSegmentIdsFromItems(items)
  const hasHigh = items.some((i) => (i.data as unknown as Record<string, unknown>).confidence === 'high')
  const hasExtractor = items.some((i) => {
    const d = i.data as unknown as Record<string, unknown>
    return !!(d.existingInitiativeMatchId || d.existingProjectMatchId || d.existingTaskMatchId || d.existingAssetMatchId || d.existingPersonMatchId)
  })
  const hasLow = items.some((i) => {
    const c = (i.data as unknown as Record<string, unknown>).confidence
    return c === 'low' || c == null || c === ''
  })
  const hasAcceptedExisting = items.some((i) => i.acceptedExistingId)
  const canLink = LINKING_SECTIONS.includes(sectionKey) && existingEntities
  const btn = 'px-1.5 py-0.5 rounded text-xs border border-slate-500 text-slate-300 hover:bg-slate-700'
  const n = items.length
  return (
    <>
      <button
        type="button"
        className={btn}
        onClick={() =>
          confirmBulkAction(`Accept all ${n} item(s) in this section? You can still edit before commit.`, () => apply(acceptSection(items)))
        }
        title="Accept all in this section"
      >
        Accept all
      </button>
      {hasHigh && (
        <button
          type="button"
          className={btn}
          onClick={() =>
            confirmBulkAction('Accept every item marked high confidence in this section?', () => apply(acceptHighConfidence(items)))
          }
          title="Accept items with high confidence"
        >
          Accept high confidence
        </button>
      )}
      {hasExtractor && (
        <button
          type="button"
          className={btn}
          onClick={() =>
            confirmBulkAction('Accept all items that have an extractor-suggested entity match?', () => apply(acceptExtractorMatches(items)))
          }
          title="Accept items with extractor-suggested match"
        >
          Accept extractor matches
        </button>
      )}
      {hasLow && (
        <button
          type="button"
          className={btn}
          onClick={() =>
            confirmBulkAction('Reject (unapprove) all low-confidence items in this section?', () => apply(rejectLowConfidence(items)))
          }
          title="Reject low-confidence items"
        >
          Reject low confidence
        </button>
      )}
      {hasAcceptedExisting && (
        <button
          type="button"
          className={btn}
          onClick={() =>
            confirmBulkAction('Clear linked “use existing” choices for all items in this section?', () => apply(clearAcceptedExisting(items)))
          }
          title="Clear all linked existing entity"
        >
          Clear linked existing
        </button>
      )}
      {canLink && hasExtractor && (
        <button
          type="button"
          className={btn}
          onClick={() =>
            confirmBulkAction('Apply extractor-suggested links to all matching items in this section?', () => apply(useExtractorMatches(items)))
          }
          title="Set linked entity from extractor match for all"
        >
          Use extractor matches
        </button>
      )}
      {canLink && (
        <button
          type="button"
          className={btn}
          onClick={() =>
            confirmBulkAction('Run duplicate detection and set links for likely matches across this section?', () =>
              apply(useHeuristicMatches(items, sectionKey, existingEntities!, DUPLICATE_THRESHOLD)),
            )
          }
          title="Find likely existing matches for these items"
        >
          Find likely matches
        </button>
      )}
      {segments.map(({ segmentId, segmentTitle }, idx) => (
        <button
          key={segmentId}
          type="button"
          className={btn}
          onClick={() =>
            confirmBulkAction(`Accept every item from chunk ${idx + 1}?`, () => apply(acceptSegment(items, segmentId)))
          }
          title={`Accept items from chunk ${idx + 1}`}
        >
          Accept evidence from Chunk {idx + 1}
        </button>
      ))}
      {canLink && segments.map(({ segmentId, segmentTitle }, idx) => (
        <button
          key={`link-${segmentId}`}
          type="button"
          className={btn}
          onClick={() =>
            confirmBulkAction(`Apply heuristic matches for items from chunk ${idx + 1}?`, () =>
              apply(useSegmentMatches(items, segmentId, sectionKey, existingEntities!, DUPLICATE_THRESHOLD)),
            )
          }
          title={`Use matches from chunk ${idx + 1}`}
        >
          Use matches from Chunk {idx + 1}
        </button>
      ))}
    </>
  )
}

/** Distinguish Pass 0 literal anchors from model observations in the ideas / candidates list. */
function ObservationKindBadge({
  sourceStage,
  candidateKind,
}: {
  sourceStage: string | null | undefined
  candidateKind?: string | null | undefined
}) {
  const k = (candidateKind ?? '').trim().toLowerCase()
  if (k === 'workspace_hint') {
    return (
      <span
        className="inline-block text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-violet-900/45 text-violet-100 border border-violet-700/45"
        title="Matched a prebuilt workspace domain hint (folder / file name mirror — not stored in VE until you commit)"
      >
        Workspace reference
      </span>
    )
  }
  if (k === 'promoted_literal') {
    return (
      <span
        className="inline-block text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-teal-900/40 text-teal-100 border border-teal-700/40"
        title="Observation built from transcript context around a workspace or entity anchor (literal-grounded proposition)"
      >
        Grounded observation
      </span>
    )
  }
  const s = (sourceStage ?? '').trim().toLowerCase()
  if (s === 'literal') {
    return (
      <span
        className="inline-block text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-sky-900/45 text-sky-100 border border-sky-700/45"
        title="Matched a known entity from your workspace context (verbatim or near-verbatim in notes)"
      >
        Existing reference
      </span>
    )
  }
  if (s === 'model') {
    return (
      <span
        className="inline-block text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-900/35 text-amber-100 border border-amber-800/40"
        title="Surfaced by the extraction model from this excerpt"
      >
        New observation
      </span>
    )
  }
  return null
}

/** Confidence / match score and optional extractor source stage (model | clause | lexical). */
function ConfidenceBadge({
  data,
}: {
  data: { confidence?: ExtractedConfidence | null; matchConfidence?: number | null; sourceStage?: string | null }
}) {
  const num = data.matchConfidence != null && typeof data.matchConfidence === 'number'
  const cat = data.confidence && ['high', 'medium', 'low'].includes(data.confidence)
  const src = (data.sourceStage ?? '').trim()
  if (!num && !cat && !src) return null
  const confPart = num ? `match score: ${Number(data.matchConfidence).toFixed(2)}` : cat ? `confidence: ${data.confidence}` : ''
  const srcPart = src ? `source: ${src}` : ''
  const label = [confPart, srcPart].filter(Boolean).join(' · ')
  return <span className="text-slate-500 text-xs ml-1">({label})</span>
}

const DUPLICATE_THRESHOLD = 0.5

type EntityType = 'initiative' | 'project' | 'task' | 'idea' | 'asset' | 'person'

/** Optgroup labels for the commit-type dropdown (internal value stays `signal`). */
const COMMITABLE_TYPE_GROUPS: { heading: string; options: { value: CommitableStagedKind; label: string }[] }[] = [
  {
    heading: 'Ideas & radar',
    options: [
      { value: 'idea', label: 'Idea' },
      { value: 'signal', label: 'Radar signal' },
    ],
  },
  {
    heading: 'Execution',
    options: [
      { value: 'initiative', label: 'Initiative' },
      { value: 'project', label: 'Project' },
      { value: 'task', label: 'Task' },
    ],
  },
  {
    heading: 'People & assets',
    options: [
      { value: 'person', label: 'Person' },
      { value: 'asset', label: 'Asset' },
    ],
  },
]

function getDisplayTitle(data: Record<string, unknown>, kind: string): string {
  if (kind === 'insight') return (data.statement as string) ?? ''
  if (kind === 'asset') return (data.name as string) ?? ''
  if (kind === 'person') return (data.name as string) ?? ''
  if (kind === 'signal') return (data.label as string) ?? ''
  return (data.title as string) ?? ''
}

/** Priority: structured summary → rationale/notes/description → source evidence → minimal placeholder. Never return blank. */
function getDisplaySummary(data: Record<string, unknown>, kind: string): string {
  let summary = ''
  // 1) Structured summary / rationale / description
  if (kind === 'insight') {
    summary = (data.sourceQuote as string) ?? ''
  } else if (kind === 'idea') {
    summary = (data.summary as string) ?? (data.description as string) ?? ''
  } else if (kind === 'initiative' || kind === 'project') {
    summary = (data.brief as string) ?? (data.description as string) ?? (data.notes as string) ?? ''
  } else if (kind === 'task') {
    summary = (data.description as string) ?? (data.notes as string) ?? ''
  } else if (kind === 'asset') {
    summary = (data.description as string) ?? ''
  } else if (kind === 'person') {
    summary = (data.role as string) ?? (data.context as string) ?? ''
  } else if (kind === 'signal') {
    summary = (data.detail as string) ?? ''
  }

  const hasStructured = !!summary && !!String(summary).trim()

  // 2) Cleaned sentence from sourceExcerpt (first sentence)
  if (!hasStructured) {
    const rawExcerpt = (data.sourceExcerpt as string | null | undefined) ?? ''
    const excerpt = rawExcerpt.replace(/[\r\n]+/g, ' ').trim()
    if (excerpt) {
      // Heuristic: take up to the first sentence terminator, otherwise cap length.
      const sentenceMatch = excerpt.match(/[^.!?]*[.!?]/)
      const sentence = (sentenceMatch ? sentenceMatch[0] : excerpt).trim()
      const cleaned = sentence.replace(/\s+/g, ' ')
      summary = cleaned.slice(0, 200)
    }
  }

  // 3) Final fallback
  if (!summary || !String(summary).trim()) {
    summary = 'Needs summary'
  }
  return summary
}

function normTitleKey(s: string): string {
  return s.toLowerCase().trim().replace(/\s+/g, ' ')
}

/**
 * After a full staging rebuild (e.g. merged chunk extract), row ids often change while title/segment/excerpt stay stable.
 * Finds the same logical row so the detail modal can reattach without staying in read-only snapshot mode.
 */
function findRebindStagedItem(reference: StagedItem, candidates: StagedItem[]): StagedItem | null {
  if (candidates.length === 0) return null
  const refData = reference.data as unknown as Record<string, unknown>
  const refTitle = getDisplayTitle(refData, reference.kind)
  const nref = normTitleKey(refTitle)
  const refSeg = String(refData.segmentId ?? '').trim()
  const refEx = String(refData.sourceExcerpt ?? '').trim().toLowerCase()

  const exact: StagedItem[] = []
  for (const c of candidates) {
    const d = c.data as unknown as Record<string, unknown>
    const t = getDisplayTitle(d, c.kind)
    if (nref.length >= 3 && normTitleKey(t) === nref) {
      exact.push(c)
    }
  }
  if (exact.length === 1) return exact[0]!
  if (exact.length > 1 && refSeg) {
    const segHit = exact.filter(
      (c) => String((c.data as unknown as Record<string, unknown>).segmentId ?? '').trim() === refSeg,
    )
    if (segHit.length === 1) return segHit[0]!
  }
  if (exact.length > 1 && refEx.length >= 35) {
    const exHit = exact.filter((c) => {
      const ex = String((c.data as unknown as Record<string, unknown>).sourceExcerpt ?? '').trim().toLowerCase()
      if (ex.length < 35) return false
      const a = refEx.slice(0, 45)
      const b = ex.slice(0, 45)
      return refEx.includes(b.slice(0, 35)) || ex.includes(a.slice(0, 35))
    })
    if (exHit.length === 1) return exHit[0]!
  }
  if (exact.length > 1) return null

  let best: { item: StagedItem; score: number } | null = null
  const shortTitle = nref.length < 10
  const minFuzzy = shortTitle ? 0.93 : 0.82
  for (const c of candidates) {
    const d = c.data as unknown as Record<string, unknown>
    const t = getDisplayTitle(d, c.kind)
    let score = titleSimilarity(refTitle, t)
    const cSeg = String(d.segmentId ?? '').trim()
    if (refSeg && cSeg && refSeg === cSeg) {
      score = Math.min(1, score + 0.12)
    }
    const cEx = String(d.sourceExcerpt ?? '').trim().toLowerCase()
    if (refEx.length >= 40 && cEx.length >= 40) {
      const a = refEx.slice(0, 50)
      const b = cEx.slice(0, 50)
      if (refEx.includes(b.slice(0, 35)) || cEx.includes(a.slice(0, 35))) {
        score = Math.min(1, score + 0.08)
      }
    }
    if (score >= minFuzzy && (!best || score > best.score)) {
      best = { item: c, score }
    }
  }
  return best?.item ?? null
}

/** Plain-text block to append to an existing task’s `notes` (meeting extraction review). */
export function formatStagedItemForTaskNotes(item: StagedItem): string {
  const data = item.data as unknown as Record<string, unknown>
  const kind = item.kind
  const title = getDisplayTitle(data, kind).trim() || '(no title)'
  const summary = getDisplaySummary(data, kind).trim()
  const rawExcerpt = String(data.sourceExcerpt ?? '').trim()
  const excerpt = rawExcerpt.length > 600 ? `${rawExcerpt.slice(0, 600)}…` : rawExcerpt
  const seg = getSegmentLabel(data as { segmentId?: string; segmentTitle?: string })
  const typeLine = item.overrideType ?? kind
  const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ')
  const lines: string[] = []
  lines.push('---')
  lines.push(`[Meeting extraction → task note] ${stamp}`)
  lines.push(`Type (as reviewed): ${typeLine}`)
  lines.push(`Title: ${title}`)
  if (summary && summary !== 'Needs summary') lines.push(`Summary: ${summary}`)
  if (seg) lines.push(`Chunk: ${seg}`)
  if (excerpt) lines.push(`Evidence: "${excerpt}"`)
  lines.push('---')
  return lines.join('\n')
}

function setDisplayTitle(data: Record<string, unknown>, kind: string, value: string): void {
  if (kind === 'insight') { data.statement = value; return }
  if (kind === 'asset') { data.name = value; return }
  if (kind === 'person') { data.name = value; return }
  if (kind === 'signal') { data.label = value; return }
  data.title = value
}

function setDisplaySummary(data: Record<string, unknown>, kind: string, value: string): void {
  if (kind === 'insight') { data.sourceQuote = value; return }
  if (kind === 'idea') { data.summary = value; data.description = value; return }
  if (kind === 'initiative' || kind === 'project') { data.brief = value; if (kind === 'initiative') data.description = value; return }
  if (kind === 'task') { data.description = value; return }
  if (kind === 'asset') { data.description = value; return }
  if (kind === 'person') { data.role = value; data.context = value; return }
  if (kind === 'signal') { data.detail = value; return }
}

/** Resolve extractor-suggested match id from item.data to { id, title } using existingEntities. */
function getExtractorSuggestedMatch(
  data: { existingInitiativeMatchId?: string | null; existingProjectMatchId?: string | null; existingTaskMatchId?: string | null; existingAssetMatchId?: string | null; existingPersonMatchId?: string | null },
  kind: EntityType,
  existingEntities: ExistingEntities | null
): { id: string; title: string; entityType: EntityType } | null {
  const raw =
    kind === 'initiative' ? (data as { existingInitiativeMatchId?: string | null }).existingInitiativeMatchId
    : kind === 'project' ? (data as { existingProjectMatchId?: string | null }).existingProjectMatchId
    : kind === 'task' ? (data as { existingTaskMatchId?: string | null }).existingTaskMatchId
    : kind === 'asset' ? (data as { existingAssetMatchId?: string | null }).existingAssetMatchId
    : kind === 'person' ? (data as { existingPersonMatchId?: string | null }).existingPersonMatchId
    : null
  const id = raw && String(raw).trim() ? String(raw).trim() : null
  if (!id || !existingEntities) return null
  const list =
    kind === 'initiative' ? existingEntities.initiatives
    : kind === 'project' ? existingEntities.projects
    : kind === 'task' ? existingEntities.tasks
    : kind === 'idea' ? existingEntities.ideas
    : kind === 'asset' ? existingEntities.assets
    : existingEntities.people
  const found = list?.find((e) => e.id === id)
  const title = found && 'title' in found ? found.title : (found && 'name' in found ? found.name : id)
  return found ? { id, title, entityType: kind } : null
}

/** Segment metadata on extracted item data (optional). */
function getSegmentLabel(data: { segmentId?: string; segmentTitle?: string } | undefined): string | null {
  if (!data) return null
  const title = data.segmentTitle?.trim()
  const id = data.segmentId?.trim()
  if (title) return title
  if (id) return id
  return null
}

/** Per-card review (Vision Execution): compact title/summary table; row opens full card in modal. */
function StagingCompactTable({
  sorted,
  stagingArray,
  sectionKey,
  onOpenRow,
  onDismissOneItem,
  committingItemId,
  triageEnabled = false,
}: {
  sorted: StagedItem[]
  stagingArray: StagedItem[]
  sectionKey: SectionArrayKey
  onOpenRow: (itemId: string) => void
  onDismissOneItem?: (sectionKey: SectionArrayKey, index: number) => void
  committingItemId?: string | null
  triageEnabled?: boolean
}) {
  const showDismiss = Boolean(onDismissOneItem)
  return (
    <div className="rounded-lg border border-slate-600 overflow-hidden w-full min-w-0">
      <table className="w-full min-w-0 text-sm table-auto">
        <colgroup>
          <col className="min-w-[12rem] sm:min-w-[16rem]" style={{ width: showDismiss ? '32%' : '34%' }} />
          {triageEnabled ? <col style={{ width: '6.5rem' }} /> : null}
          <col />
          {showDismiss ? <col style={{ width: '5.5rem' }} /> : null}
        </colgroup>
        <thead>
          <tr className="border-b border-slate-600 bg-slate-900/90 text-left text-[10px] uppercase tracking-wide text-slate-500">
            <th className="px-3 py-2 font-medium align-top">Title</th>
            {triageEnabled ? (
              <th className="px-2 py-2 font-medium align-top whitespace-nowrap w-0">Triage</th>
            ) : null}
            <th className="px-3 py-2 font-medium align-top min-w-0">Summary</th>
            {showDismiss ? (
              <th className="px-2 py-2 font-medium align-top text-right whitespace-nowrap w-0"> </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {sorted.map((item) => {
            const originalIndex = stagingArray.findIndex((x) => x.id === item.id)
            const data = item.data as unknown as Record<string, unknown>
            const title = getDisplayTitle(data, item.kind)
            const summary = getDisplaySummary(data, item.kind)
            const summaryOneLine = summary.replace(/\s+/g, ' ').trim()
            const rowBusy = committingItemId === item.id
            return (
              <tr
                key={item.id}
                className="border-b border-slate-700/80 last:border-0 hover:bg-slate-800/70 cursor-pointer transition-colors"
                onClick={() => onOpenRow(item.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onOpenRow(item.id)
                  }
                }}
                tabIndex={0}
                role="button"
                aria-label={`Open candidate: ${title || 'untitled'}`}
              >
                <td className="px-3 py-2 text-slate-200 font-medium align-top min-w-0">
                  <div className="whitespace-normal break-words">{title || '—'}</div>
                </td>
                {triageEnabled ? (
                  <td className="px-2 py-2 align-top w-0 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                    {item.presortBucket ? <PresortTriageBadge item={item} compact /> : <span className="text-slate-600 text-xs">—</span>}
                  </td>
                ) : null}
                <td className="px-3 py-2 text-slate-400 align-top min-w-0">
                  <div className="line-clamp-3 break-words" title={summaryOneLine || undefined}>
                    {summaryOneLine || '—'}
                  </div>
                </td>
                {showDismiss ? (
                  <td className="px-2 py-2 align-top text-right whitespace-nowrap w-0">
                    <button
                      type="button"
                      disabled={rowBusy || originalIndex < 0}
                      onClick={(e) => {
                        e.stopPropagation()
                        if (originalIndex >= 0) onDismissOneItem!(sectionKey, originalIndex)
                      }}
                      className="px-2 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-700 disabled:opacity-40 text-xs"
                      aria-label={`Dismiss ${title || 'candidate'}`}
                    >
                      Dismiss
                    </button>
                  </td>
                ) : null}
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="px-3 py-2 text-[11px] text-slate-500 border-t border-slate-700/80 bg-slate-900/50">
        Click a row for the full editor, placement, linking, and actions.
        {triageEnabled ? ' Triage column shows coarse Presort all results (Existing / New / Unsure).' : ''}
        {showDismiss ? ' Use Dismiss to remove a row without opening it.' : ''}
      </p>
    </div>
  )
}

/** Sections that support the full judgment editor (type, parent, people, assets, Link). */
const EDITABLE_SECTIONS: SectionArrayKey[] = ['ideas', 'initiatives', 'projects', 'tasks', 'assets', 'people', 'signals']

function SummaryRow({
  item,
  onToggle,
  perCardActions,
  onDismissSummary,
}: {
  item: StagedSummary
  onToggle: () => void
  perCardActions?: boolean
  onDismissSummary?: () => void
}) {
  return (
    <li
      className={`rounded-lg border p-3 text-sm flex items-start gap-3 ${
        !perCardActions && item.approved ? 'border-emerald-600 bg-emerald-900/20' : 'border-slate-600 bg-slate-800/30'
      }`}
    >
      {perCardActions ? (
        <button
          type="button"
          onClick={() => onDismissSummary?.()}
          className="shrink-0 px-2 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-700 text-xs"
        >
          Dismiss
        </button>
      ) : (
        <input type="checkbox" checked={item.approved} onChange={onToggle} className="mt-1 rounded border-slate-500" aria-label={item.approved ? 'Reject' : 'Accept'} />
      )}
      <p className="text-slate-200 flex-1">{(item.data as { text: string }).text}</p>
    </li>
  )
}

function StagedCard<T extends StagedItem>({
  item,
  sectionKey,
  index,
  onToggle,
  onUpdate,
  possibleMatch,
  extractorSuggestedMatch,
  entityType,
  onLinkToExisting,
  onUseExisting,
  existingEntities,
  linkChooserOpen,
  onOpenLinkChooser,
  onCloseLinkChooser,
  onLinkChoose,
  perCardActions = false,
  onCommitOneItem,
  onDismissOneItem,
  committingItemId = null,
  sectionSupportsEntityCommit = true,
  onOpenSendTo,
  onOpenAppendNote,
  onSuggestPlacement,
  placementLoading = false,
  placementHint = null,
  onDismissPlacementHint,
}: {
  item: T
  sectionKey: SectionArrayKey
  index: number
  onToggle: () => void
  onUpdate: (patch: Partial<StagedItemBase> & { data?: Record<string, unknown> }) => void
  possibleMatch?: { id: string; title: string; entityType: EntityType } | null
  extractorSuggestedMatch?: { id: string; title: string; entityType: EntityType } | null
  entityType?: EntityType
  onLinkToExisting?: (entityType: EntityType, id: string) => void
  onUseExisting?: (entityType: EntityType, index: number, existingId: string) => void
  existingEntities: ExistingEntities | null
  linkChooserOpen: boolean
  onOpenLinkChooser: () => void
  onCloseLinkChooser: () => void
  onLinkChoose: (action: 'use_existing' | 'child_of', entityType: 'idea' | 'initiative' | 'project' | 'task', id: string) => void
  perCardActions?: boolean
  onCommitOneItem?: (sectionKey: SectionArrayKey, itemId: string) => boolean | Promise<boolean | void> | void
  onDismissOneItem?: (sectionKey: SectionArrayKey, index: number) => void
  committingItemId?: string | null
  /** False for insights (not persisted via entity commit). */
  sectionSupportsEntityCommit?: boolean
  onOpenSendTo?: (sectionKey: SectionArrayKey, item: StagedItem) => void
  onOpenAppendNote?: (sectionKey: SectionArrayKey, item: StagedItem) => void
  /** Presort: POST suggest-candidate-placement; applies suggestions to staging only (no API save). */
  onSuggestPlacement?: () => void | Promise<void>
  placementLoading?: boolean
  placementHint?: CandidatePlacementResponse | null
  onDismissPlacementHint?: () => void
}) {
  const kind = item.kind
  const data = (item as StagedItem).data as unknown as Record<string, unknown>
  const title = getDisplayTitle(data, kind)
  const summary = getDisplaySummary(data, kind)
  const suggested = extractorSuggestedMatch ?? possibleMatch
  const isExtractor = !!extractorSuggestedMatch
  const segmentLabel = getSegmentLabel(data as { segmentId?: string; segmentTitle?: string })
  const sourceExcerpt = (data.sourceExcerpt as string | null | undefined) ?? ''
  const confidence = (data.confidence as ExtractedConfidence | null | undefined) ?? null
  const matchConfidence = data.matchConfidence as number | null | undefined
  const observationSourceStage = (data.sourceStage as string | null | undefined)?.trim() || null
  const observationCandidateKind = (data.candidateKind as string | null | undefined)?.trim() || null
  const isEditableSection = EDITABLE_SECTIONS.includes(sectionKey)
  const showTitleSummaryInputs = isEditableSection || sectionKey === 'insights'
  const canLink = LINKING_SECTIONS.includes(sectionKey) && existingEntities != null

  const handleTitleChange = (value: string) => {
    setDisplayTitle(data, kind, value)
    onUpdate({ data: { ...data } })
  }
  const handleSummaryChange = (value: string) => {
    setDisplaySummary(data, kind, value)
    onUpdate({ data: { ...data } })
  }

  const effectiveType = item.overrideType ?? kind
  const parentLink = item.parentLink

  const cardBusy = committingItemId === item.id
  const placementWhyLine = placementHint ? combinePlacementWhy(placementHint) : ''

  return (
    <li
      className={`rounded-lg border p-3 text-sm flex flex-col gap-2 ${
        !perCardActions && item.approved ? 'border-emerald-600 bg-emerald-900/20' : 'border-slate-600 bg-slate-800/30'
      }`}
    >
      <div className="flex items-start gap-2">
        {!perCardActions && (
          <input
            type="checkbox"
            checked={item.approved}
            onChange={onToggle}
            className="mt-1 rounded border-slate-500 shrink-0"
            aria-label={item.approved ? 'Ignore' : 'Accept'}
            title={item.approved ? 'Ignore' : 'Accept'}
          />
        )}
        <div className="flex-1 min-w-0 space-y-1.5">
          {showTitleSummaryInputs ? (
            <>
              <input
                type="text"
                value={title}
                onChange={(e) => handleTitleChange(e.target.value)}
                placeholder="Title"
                className="w-full px-2 py-1 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm font-medium"
              />
              <div className="space-y-1">
                <label className="block text-xs font-medium text-slate-400">Summary / description</label>
                <textarea
                  value={summary}
                  onChange={(e) => handleSummaryChange(e.target.value)}
                  placeholder="Short human-readable summary (or evidence snippet)"
                  rows={2}
                  className="w-full px-2 py-1 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm resize-y"
                />
              </div>
            </>
          ) : (
            <span className="font-medium text-slate-200">{title}</span>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {sectionKey === 'ideas' && (
              <ObservationKindBadge sourceStage={observationSourceStage} candidateKind={observationCandidateKind} />
            )}
            {(confidence || matchConfidence != null || observationSourceStage) && (
              <ConfidenceBadge data={{ confidence, matchConfidence, sourceStage: observationSourceStage }} />
            )}
            <PresortTriageBadge item={item as StagedItem} />
          </div>
        </div>
      </div>

      {isEditableSection && (
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <div className="flex-1 min-w-0 max-w-xs">
            <label htmlFor={`commit-type-${item.id}`} className="block text-slate-500 mb-1 text-xs">
              Choose type
            </label>
            <select
              id={`commit-type-${item.id}`}
              value={effectiveType}
              onChange={(e) => onUpdate({ overrideType: e.target.value as CommitableStagedKind })}
              title="Choose how this row should be created in the workspace. Radar signals are short items that show up on your radar view."
              className="w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm"
            >
              {COMMITABLE_TYPE_GROUPS.map((group) => (
                <optgroup key={group.heading} label={group.heading}>
                  {group.options.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
          {(canLink || onSuggestPlacement) && (
            <div className="flex flex-col gap-1 shrink-0">
              <div className="flex flex-wrap gap-1 items-end">
                {canLink && (
                  <button
                    type="button"
                    onClick={() => {
                      if (DEBUG_LINK_FLOW) console.log('[Link] click', { sectionKey, kind, title, id: item.id })
                      onOpenLinkChooser()
                    }}
                    className="px-2 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-700"
                    title="Attach to existing entity (use as same or place under as child)"
                  >
                    Link
                  </button>
                )}
                {onSuggestPlacement && (
                  <button
                    type="button"
                    onClick={() => void onSuggestPlacement()}
                    disabled={placementLoading}
                    className="px-2 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-700 disabled:opacity-50"
                    title="Suggest type and link from your workspace graph (you can override)"
                  >
                    {placementLoading ? '…' : 'Suggest placement'}
                  </button>
                )}
              </div>
              {canLink && !existingEntities && (
                <span className="text-slate-500" title="Load existing entities to enable Link">Link (no data)</span>
              )}
            </div>
          )}
        </div>
      )}

      {isEditableSection && placementHint != null && onDismissPlacementHint && (
        <div className="rounded border border-amber-700/40 bg-amber-950/25 px-2 py-2 text-xs space-y-1.5">
          <div className="flex justify-between items-start gap-2">
            <span className="text-amber-200/95 font-medium">Suggested placement</span>
            <button type="button" onClick={onDismissPlacementHint} className="text-slate-400 hover:text-slate-200 shrink-0">
              Dismiss
            </button>
          </div>
          {placementHint.execution_blocked ? (
            <p className="text-red-300">{placementHint.error ?? 'Execution blocked by policy.'}</p>
          ) : (
            <>
              {placementHint.profile_name ? (
                <p className="text-[11px] text-slate-500">
                  Brand core (placement): <span className="text-slate-300">{placementHint.profile_name}</span>
                </p>
              ) : null}
              <p className="text-slate-200">
                <span className="text-slate-500">Suggested as: </span>
                {titleCaseFit(placementHint.proposed_type) || placementHint.proposed_type || '—'}
                {placementHint.confidence != null && (
                  <span className="text-slate-500">
                    {' '}
                    · {Math.round(placementHint.confidence * 100)}% confidence
                  </span>
                )}
              </p>
              <p className="text-slate-200">
                <span className="text-slate-500">Placement: </span>
                {describePlacementSummary(placementHint)}
              </p>
              {(placementHint.strategic_fit != null || placementHint.profile_alignment != null) && (
                <p className="text-slate-200">
                  <span className="text-slate-500">Profile fit: </span>
                  {placementHint.strategic_fit ? titleCaseFit(placementHint.strategic_fit) : '—'}
                  {placementHint.profile_alignment != null && (
                    <span className="text-slate-500">
                      {' '}
                      ({Math.round(placementHint.profile_alignment * 100)}% alignment)
                    </span>
                  )}
                </p>
              )}
              {placementHint.capacity_risk && placementHint.capacity_risk !== 'low' ? (
                <p className="text-slate-200">
                  <span className="text-slate-500">Capacity risk: </span>
                  {titleCaseFit(placementHint.capacity_risk)}
                </p>
              ) : null}
              {placementWhyLine ? (
                <p className="text-slate-400 border-t border-slate-700/50 pt-1.5 mt-1">
                  <span className="text-slate-500">Why: </span>
                  {placementWhyLine}
                </p>
              ) : null}
              {(placementHint.alternatives?.length ?? 0) > 0 && (
                <p className="text-slate-500 text-[11px]">
                  Alternatives:{' '}
                  {placementHint
                    .alternatives!.slice(0, 2)
                    .map((a) => `${a.type} (${Math.round((a.confidence ?? 0) * 100)}%)`)
                    .join(' · ')}
                </p>
              )}
              {placementHint._fallback ? (
                <p className="text-amber-600/90 text-[11px]">Heuristic or fallback — verify before commit.</p>
              ) : null}
            </>
          )}
        </div>
      )}

      {(() => {
        const hasLink = !!item.acceptedExistingId || !!parentLink
        if (!hasLink) return null
        const linkedTitle = item.acceptedExistingId
          ? (existingEntities?.ideas?.find((e) => e.id === item.acceptedExistingId)?.title
            ?? existingEntities?.initiatives?.find((e) => e.id === item.acceptedExistingId)?.title
            ?? existingEntities?.projects?.find((e) => e.id === item.acceptedExistingId)?.title
            ?? existingEntities?.tasks?.find((e) => e.id === item.acceptedExistingId)?.title
            ?? existingEntities?.assets?.find((e) => e.id === item.acceptedExistingId)?.name
            ?? existingEntities?.people?.find((e) => e.id === item.acceptedExistingId)?.name
            ?? item.acceptedExistingId)
          : parentLink
            ? ((existingEntities?.ideas?.find((e) => e.id === parentLink.parentId)?.title)
              ?? existingEntities?.initiatives?.find((e) => e.id === parentLink.parentId)?.title
              ?? existingEntities?.projects?.find((e) => e.id === parentLink.parentId)?.title
              ?? existingEntities?.tasks?.find((e) => e.id === parentLink.parentId)?.title
              ?? `${parentLink.parentType}: ${parentLink.parentId}`)
            : ''
        return (
          <div className="rounded border border-slate-600 bg-slate-800/50 px-2 py-1.5 text-xs space-y-1">
            <div className="text-slate-300">
              {item.acceptedExistingId ? (
                <span className="text-emerald-400/90">Use existing: <strong>{linkedTitle}</strong></span>
              ) : (
                <span className="text-slate-400">Place under: <strong className="text-slate-200">{linkedTitle}</strong> (create as child)</span>
              )}
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={onOpenLinkChooser} className="text-amber-400 hover:text-amber-300">Change</button>
              <button
                type="button"
                onClick={() => onUpdate({ acceptedExistingId: null, parentLink: null })}
                className="text-slate-500 hover:text-red-400"
              >
                Clear
              </button>
            </div>
          </div>
        )
      })()}
      {suggested && !item.acceptedExistingId && !parentLink && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={isExtractor ? 'text-emerald-400/90' : 'text-amber-400/90'}>
            {isExtractor ? 'Suggested link:' : 'Possible match:'}
          </span>
          <span className="text-slate-400">{suggested.title}</span>
          {onUseExisting && entityType !== undefined && (
            <button type="button" onClick={() => onUseExisting(entityType, index, suggested.id)} className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium">Accept</button>
          )}
          {onLinkToExisting && (
            <button type="button" onClick={() => onLinkToExisting(suggested.entityType, suggested.id)} className="px-1.5 py-0.5 rounded border border-slate-500 text-slate-300 hover:bg-slate-700">View existing</button>
          )}
          <span className="text-slate-500">
            {perCardActions ? '· Create new with Create on this card' : '· Create new (accept checkbox to add)'}
          </span>
        </div>
      )}

      {isEditableSection && existingEntities && (existingEntities.people?.length || existingEntities.assets?.length) && (
        <div className="flex flex-wrap gap-4 text-xs">
          {existingEntities.people && existingEntities.people.length > 0 && (
            <div className="min-w-0 flex-1 max-w-[280px]">
              <EntityChipSelect
                label="People"
                options={existingEntities.people.map((p) => ({ id: p.id, name: p.name }))}
                selectedIds={item.assignedPersonIds ?? []}
                onChange={(ids) => onUpdate({ assignedPersonIds: ids })}
                placeholder="Search people…"
              />
            </div>
          )}
          {existingEntities.assets && existingEntities.assets.length > 0 && (
            <div className="min-w-0 flex-1 max-w-[280px]">
              <EntityChipSelect
                label="Assets"
                options={existingEntities.assets.map((a) => ({ id: a.id, name: a.name }))}
                selectedIds={item.assignedAssetIds ?? []}
                onChange={(ids) => onUpdate({ assignedAssetIds: ids })}
                placeholder="Search assets…"
              />
            </div>
          )}
        </div>
      )}

      {segmentLabel && <p className="text-xs text-slate-500">From chunk: {segmentLabel}</p>}
      {sourceExcerpt && (
        <div className="mt-1">
          <p className="text-xs font-medium text-slate-400">Evidence</p>
          <p className="text-slate-500 text-xs italic border-l-2 border-slate-600 pl-2">
            &ldquo;{sourceExcerpt.slice(0, 200)}{sourceExcerpt.length > 200 ? '…' : ''}&rdquo;
          </p>
        </div>
      )}

      {linkChooserOpen && existingEntities && LINKING_SECTIONS.includes(sectionKey) && (() => {
        if (DEBUG_LINK_FLOW) console.log('[Link] LinkChooser render', { sectionKey, kind, title, id: item.id, hasOnClose: typeof onCloseLinkChooser === 'function' })
        return (
          <div className="pt-2 border-t border-slate-600">
            <LinkChooser
              existingEntities={existingEntities}
              currentSectionKey={sectionKey as import('./LinkChooser').LinkableSectionKey}
              onChoose={onLinkChoose}
              onClose={onCloseLinkChooser}
            />
          </div>
        )
      })()}

      {perCardActions &&
        (onDismissOneItem ||
          (sectionSupportsEntityCommit && onCommitOneItem) ||
          onOpenSendTo ||
          onOpenAppendNote) && (
        <div className="flex flex-wrap gap-2 pt-2 border-t border-slate-600 mt-1">
          {sectionSupportsEntityCommit && onCommitOneItem && (
            <button
              type="button"
              disabled={cardBusy}
              onClick={() => void onCommitOneItem(sectionKey, item.id)}
              className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-medium"
            >
              {cardBusy ? 'Creating…' : 'Create'}
            </button>
          )}
          {perCardActions && onOpenSendTo && (
            <button
              type="button"
              disabled={cardBusy}
              onClick={() => onOpenSendTo(sectionKey, item as StagedItem)}
              className="px-3 py-1.5 rounded-lg border border-sky-600/80 text-sky-200 hover:bg-sky-900/40 disabled:opacity-50 text-sm"
            >
              Send to…
            </button>
          )}
          {perCardActions && onOpenAppendNote && (
            <button
              type="button"
              disabled={cardBusy}
              onClick={() => onOpenAppendNote(sectionKey, item as StagedItem)}
              className="px-3 py-1.5 rounded-lg border border-violet-600/80 text-violet-200 hover:bg-violet-900/40 disabled:opacity-50 text-sm"
              title="Append this card as a dated block on an idea, initiative, project, or task (execution tree + ideas)"
            >
              Add note…
            </button>
          )}
          {onDismissOneItem && (
            <button
              type="button"
              disabled={cardBusy}
              onClick={() => onDismissOneItem(sectionKey, index)}
              className="px-3 py-1.5 rounded-lg border border-slate-500 text-slate-300 hover:bg-slate-700 disabled:opacity-50 text-sm"
            >
              Dismiss
            </button>
          )}
        </div>
      )}
    </li>
  )
}

const stagedCardPerItemProps = (opts: {
  perCardActions?: boolean
  onCommitOneItem?: ReviewExtractionScreenProps['onCommitOneItem']
  onDismissOneItem?: ReviewExtractionScreenProps['onDismissOneItem']
  committingItemId?: string | null
  sectionSupportsEntityCommit?: boolean
  onOpenSendTo?: ReviewExtractionScreenProps['onOpenSendTo']
  onOpenAppendNote?: ReviewExtractionScreenProps['onOpenAppendNote']
}) => ({
  perCardActions: opts.perCardActions,
  onCommitOneItem: opts.onCommitOneItem,
  onDismissOneItem: opts.onDismissOneItem,
  committingItemId: opts.committingItemId,
  sectionSupportsEntityCommit: opts.sectionSupportsEntityCommit ?? true,
  onOpenSendTo: opts.onOpenSendTo,
  onOpenAppendNote: opts.onOpenAppendNote,
})

export function ReviewExtractionScreen({
  staging,
  onStagingChange,
  onCommit,
  onClose,
  commitLoading = false,
  commitError = null,
  existingEntities = null,
  onLinkToExisting,
  onUseExisting,
  perCardActions = false,
  onCommitOneItem,
  onDismissOneItem,
  onDismissSummary,
  committingItemId = null,
  onOpenSendTo,
  onOpenAppendNote,
  fetchCandidatePlacementSuggestion,
  fetchCandidatePresortTriage,
  suggestPlacementContext = null,
  suggestPlacementProfileId = null,
  placementBulkReady = true,
}: ReviewExtractionScreenProps) {
  const toggle = <K extends keyof StagingArea>(
    key: K,
    index: number
  ) => {
    const arr = staging[key]
    if (!Array.isArray(arr)) {
      if (key === 'summary' && staging.summary) {
        onStagingChange({
          ...staging,
          summary: { ...staging.summary, approved: !staging.summary.approved },
        })
      }
      return
    }
    const next = arr.slice() as StagedItem[]
    const item = next[index] as StagedItem
    next[index] = { ...item, approved: !item.approved } as StagedItem
    onStagingChange({ ...staging, [key]: next })
  }

  const setUseExisting = (entityType: EntityType, index: number, existingId: string) => {
    const key =
      entityType === 'initiative' ? 'initiatives'
      : entityType === 'project' ? 'projects'
      : entityType === 'task' ? 'tasks'
      : entityType === 'idea' ? 'ideas'
      : entityType === 'asset' ? 'assets'
      : 'people'
    const arr = staging[key]
    if (!Array.isArray(arr) || index < 0 || index >= arr.length) return
    const next = arr.slice() as StagedItem[]
    const item = next[index] as StagedItem
    next[index] = { ...item, acceptedExistingId: existingId } as StagedItem
    onStagingChange({ ...staging, [key]: next })
  }

  const [linkChooserFor, setLinkChooserFor] = useState<{ sectionKey: SectionArrayKey; index: number } | null>(null)
  const [placementLoadingKey, setPlacementLoadingKey] = useState<string | null>(null)
  const [placementHints, setPlacementHints] = useState<Record<string, CandidatePlacementResponse>>({})
  /** Per-card mode: compact table + modal detail (itemId survives list reorder). */
  const [stagingDetailOpen, setStagingDetailOpen] = useState<{ sectionKey: SectionArrayKey; itemId: string } | null>(
    null,
  )
  /** Last known row copy so the modal can stay open across staging rebuilds (e.g. chunk extraction refresh). */
  const [detailItemSnapshot, setDetailItemSnapshot] = useState<StagedItem | null>(null)
  const [placementBulkLoading, setPlacementBulkLoading] = useState(false)
  const [placementBulkProgress, setPlacementBulkProgress] = useState<{ cur: number; total: number } | null>(null)
  const stagingRef = useRef(staging)
  stagingRef.current = staging
  const detailItemSnapshotRef = useRef<StagedItem | null>(null)
  detailItemSnapshotRef.current = detailItemSnapshot

  const openStagingDetail = useCallback((sectionKey: SectionArrayKey, itemId: string) => {
    setStagingDetailOpen({ sectionKey, itemId })
    const arr = stagingRef.current[sectionKey]
    const found = Array.isArray(arr) ? arr.find((x) => x.id === itemId) : undefined
    setDetailItemSnapshot(found ? cloneStagedItem(found) : null)
  }, [])

  const closeStagingDetail = useCallback(() => {
    setStagingDetailOpen(null)
    setDetailItemSnapshot(null)
  }, [])

  const onCommitOneItemAndCloseDetail = useCallback(
    async (sectionKey: StagingArraySectionKey, itemId: string) => {
      if (!onCommitOneItem) return
      const ret = await Promise.resolve(onCommitOneItem(sectionKey, itemId))
      if (ret === true) closeStagingDetail()
    },
    [onCommitOneItem, closeStagingDetail],
  )

  useEffect(() => {
    if (!stagingDetailOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeStagingDetail()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [stagingDetailOpen, closeStagingDetail])

  /**
   * Keep modal bound to live staging: same id → refresh snapshot.
   * If ids rotated after merge, reattach by title / segment / evidence so the modal is not stuck read-only.
   */
  useEffect(() => {
    if (!stagingDetailOpen) return
    const { sectionKey, itemId } = stagingDetailOpen
    const arr = staging[sectionKey]
    if (!Array.isArray(arr)) return

    const found = arr.find((x) => x.id === itemId)
    if (found) {
      setDetailItemSnapshot(cloneStagedItem(found))
      return
    }

    const snap = detailItemSnapshotRef.current
    if (!snap || snap.id !== itemId) return

    const match = findRebindStagedItem(snap, arr)
    if (match && match.id !== itemId) {
      setStagingDetailOpen({ sectionKey, itemId: match.id })
      setDetailItemSnapshot(cloneStagedItem(match))
    }
  }, [staging, stagingDetailOpen])

  const updateItem = (sectionKey: SectionArrayKey, index: number, patch: Partial<StagedItemBase> & { data?: Record<string, unknown> }) => {
    const arr = staging[sectionKey]
    if (!Array.isArray(arr) || index < 0 || index >= arr.length) return
    const next = arr.slice() as StagedItem[]
    const item = next[index] as StagedItem
    const { data: patchData, ...basePatch } = patch
    const newItem = { ...item, ...basePatch } as StagedItem
    if (patchData != null) {
      ;(newItem as StagedItem).data = {
        ...(item.data as unknown as Record<string, unknown>),
        ...patchData,
      } as unknown as StagedItem['data']
    }
    next[index] = newItem
    onStagingChange({ ...staging, [sectionKey]: next })
  }

  const applyLink = (sectionKey: SectionArrayKey, index: number, action: 'use_existing' | 'child_of', entityType: 'idea' | 'initiative' | 'project' | 'task', id: string) => {
    const arr = staging[sectionKey]
    if (!Array.isArray(arr) || index < 0 || index >= arr.length) return
    const next = arr.slice() as StagedItem[]
    const item = next[index] as StagedItem
    if (action === 'use_existing') {
      next[index] = { ...item, acceptedExistingId: id, parentLink: null } as StagedItem
    } else {
      next[index] = {
        ...item,
        parentLink: { parentType: entityType, parentId: id },
        acceptedExistingId: null,
      } as StagedItem
    }
    onStagingChange({ ...staging, [sectionKey]: next })
    setLinkChooserFor(null)
  }

  const handleSuggestPlacement = async (sectionKey: SectionArrayKey, index: number, item: StagedItem) => {
    if (!fetchCandidatePlacementSuggestion || !existingEntities) return
    const key = placementItemKey(sectionKey, item.id)
    setPlacementLoadingKey(key)
    try {
      const data = item.data as unknown as Record<string, unknown>
      const candidate = {
        title: getDisplayTitle(data, item.kind),
        summary: getDisplaySummary(data, item.kind),
        evidence_quote: typeof data.sourceExcerpt === 'string' ? data.sourceExcerpt : undefined,
      }
      const res = await fetchCandidatePlacementSuggestion({
        candidate,
        existingEntities,
        context: suggestPlacementContext?.trim() || undefined,
        profileId: suggestPlacementProfileId?.trim() || undefined,
        clientCorrelationId: key,
      })
      setPlacementHints((h) => ({ ...h, [key]: res }))
      if (!res.execution_blocked) {
        const patch = buildStagingPatchFromPlacementSuggestion(res)
        updateItem(sectionKey, index, {
          overrideType: patch.overrideType,
          acceptedExistingId: patch.acceptedExistingId,
          parentLink: patch.parentLink,
        })
      }
    } catch (e) {
      setPlacementHints((h) => ({
        ...h,
        [key]: {
          proposed_type: 'idea',
          confidence: 0,
          placement_mode: 'new',
          target: null,
          suggested_parent: null,
          reason: e instanceof Error ? e.message : 'Request failed',
          alternatives: [],
          error: 'request_failed',
        },
      }))
    } finally {
      setPlacementLoadingKey(null)
    }
  }

  /** Batch presort: POST presort-candidate-triage; sets presort* fields and, when bucket is existing, acceptedExistingId + overrideType. */
  const handleSuggestPlacementAll = async () => {
    if (!fetchCandidatePresortTriage || !existingEntities || placementBulkLoading) return
    const total = countStagedPlacementCandidates(stagingRef.current)
    if (total === 0) return
    setPlacementBulkLoading(true)
    setPlacementBulkProgress({ cur: 0, total })
    const sectionOrder: SectionArrayKey[] = [
      'ideas',
      'initiatives',
      'projects',
      'tasks',
      'assets',
      'people',
      'signals',
      'insights',
    ]
    let working = cloneStagingArea(stagingRef.current)
    let done = 0
    try {
      for (const sectionKey of sectionOrder) {
        const arr = working[sectionKey]
        if (!Array.isArray(arr) || arr.length === 0) continue
        for (let index = 0; index < arr.length; index++) {
          const item = arr[index]!
          try {
            const data = item.data as unknown as Record<string, unknown>
            const candidate = buildPresortTriageCandidate(data, {
              title: getDisplayTitle(data, item.kind),
              summary: getDisplaySummary(data, item.kind),
              evidence_quote: typeof data.sourceExcerpt === 'string' ? data.sourceExcerpt : undefined,
            })
            const res = await fetchCandidatePresortTriage({
              candidate,
              existingEntities,
              context: suggestPlacementContext?.trim() || undefined,
              stagedSection: sectionKey,
              clientCorrelationId: `${sectionKey}:${item.id}`,
            })
            const patch = mapPresortTriageApiToStagingPatch(res, { stagedItemKind: item.kind })
            const nextArr = (working[sectionKey] as StagedItem[]).slice()
            const it = nextArr[index]!
            nextArr[index] = { ...it, ...patch } as StagedItem
            working = { ...working, [sectionKey]: nextArr }
            onStagingChange(working)
            stagingRef.current = working
          } catch (e) {
            const patch = mapPresortTriageApiToStagingPatch({
              presort_bucket: 'new',
              presort_type: 'idea',
              presort_confidence: 0.45,
              presort_reason: e instanceof Error ? e.message : 'Triage request failed — lean new',
            })
            const nextArr = (working[sectionKey] as StagedItem[]).slice()
            const it = nextArr[index]!
            nextArr[index] = { ...it, ...patch } as StagedItem
            working = { ...working, [sectionKey]: nextArr }
            onStagingChange(working)
            stagingRef.current = working
          } finally {
            done += 1
            setPlacementBulkProgress({ cur: done, total })
          }
        }
      }
    } finally {
      setPlacementBulkLoading(false)
      setPlacementBulkProgress(null)
    }
  }

  const presortAllCandidateCount = countStagedPlacementCandidates(staging)
  const canPresortAll =
    Boolean(fetchCandidatePresortTriage && existingEntities) &&
    presortAllCandidateCount > 0 &&
    placementBulkReady

  const placementPropsFor = (sectionKey: SectionArrayKey, item: StagedItem, originalIndex: number) => ({
    onSuggestPlacement:
      fetchCandidatePlacementSuggestion && existingEntities
        ? () => {
            void handleSuggestPlacement(sectionKey, originalIndex, item)
          }
        : undefined,
    placementLoading: placementLoadingKey === placementItemKey(sectionKey, item.id),
    placementHint: placementHints[placementItemKey(sectionKey, item.id)] ?? null,
    onDismissPlacementHint: () => {
      const k = placementItemKey(sectionKey, item.id)
      setPlacementHints((h) => {
        if (!(k in h)) return h
        const next = { ...h }
        delete next[k]
        return next
      })
    },
  })

  const hasApproved =
    staging.summary?.approved ||
    staging.insights.some((i) => i.approved) ||
    staging.ideas.some((i) => i.approved) ||
    staging.initiatives.some((i) => i.approved) ||
    staging.projects.some((i) => i.approved) ||
    staging.tasks.some((i) => i.approved) ||
    staging.assets.some((i) => i.approved) ||
    staging.people.some((i) => i.approved) ||
    (staging.signals?.length ?? 0) > 0 && staging.signals.some((s) => s.approved)

  const commitPreview = !perCardActions && hasApproved ? buildCommitPreview(staging) : []
  const pc = stagedCardPerItemProps({
    perCardActions,
    onCommitOneItem: perCardActions ? onCommitOneItemAndCloseDetail : onCommitOneItem,
    onDismissOneItem,
    committingItemId,
    onOpenSendTo,
    onOpenAppendNote,
  })

  const renderStagingDetailCard = (): JSX.Element | null => {
    if (!stagingDetailOpen) return null
    const { sectionKey, itemId } = stagingDetailOpen
    const arr = staging[sectionKey]
    const liveIdx = Array.isArray(arr) ? arr.findIndex((x) => x.id === itemId) : -1
    const liveItem = liveIdx >= 0 && arr ? (arr[liveIdx] as StagedItem) : null
    const item =
      liveItem ??
      (detailItemSnapshot && detailItemSnapshot.id === itemId ? detailItemSnapshot : null)
    if (!item) {
      return (
        <li className="text-slate-400 text-sm p-2">
          Candidate data is unavailable. Close and open the row again, or wait for extraction to finish.
        </li>
      )
    }
    const modalIdx = liveIdx >= 0 ? liveIdx : -1
    const freeze = modalIdx < 0
    const chooserOpen = (sk: SectionArrayKey) =>
      !freeze && linkChooserFor?.sectionKey === sk && linkChooserFor?.index === modalIdx

    const dtoggle = (sk: SectionArrayKey, idx: number) => () => {
      if (freeze) return
      toggle(sk, idx)
    }
    const dupdate =
      (sk: SectionArrayKey, idx: number) => (patch: Partial<StagedItemBase> & { data?: Record<string, unknown> }) => {
        if (freeze) return
        updateItem(sk, idx, patch)
      }
    const dapply =
      (sk: SectionArrayKey, idx: number) =>
      (action: 'use_existing' | 'child_of', entityType: 'idea' | 'initiative' | 'project' | 'task', id: string) => {
        if (freeze) return
        applyLink(sk, idx, action, entityType, id)
      }
    const dlinkOpen = (sk: SectionArrayKey, idx: number) => () => {
      if (freeze) return
      setLinkChooserFor({ sectionKey: sk, index: idx })
    }

    const pp = freeze
      ? {
          onSuggestPlacement: undefined,
          placementLoading: false,
          placementHint: placementHints[placementItemKey(sectionKey, item.id)] ?? null,
          onDismissPlacementHint: () => {
            const k = placementItemKey(sectionKey, item.id)
            setPlacementHints((h) => {
              if (!(k in h)) return h
              const next = { ...h }
              delete next[k]
              return next
            })
          },
        }
      : placementPropsFor(sectionKey, item, modalIdx)

    const pcModal = freeze
      ? stagedCardPerItemProps({
          perCardActions,
          onCommitOneItem: undefined,
          onDismissOneItem: undefined,
          committingItemId,
          onOpenSendTo: undefined,
          onOpenAppendNote: undefined,
        })
      : pc

    if (sectionKey === 'insights') {
      return (
        <StagedCard
          item={item}
          sectionKey="insights"
          index={modalIdx}
          onToggle={dtoggle('insights', modalIdx)}
          onUpdate={dupdate('insights', modalIdx)}
          existingEntities={existingEntities}
          linkChooserOpen={chooserOpen('insights')}
          onOpenLinkChooser={dlinkOpen('insights', modalIdx)}
          onCloseLinkChooser={() => setLinkChooserFor(null)}
          onLinkChoose={dapply('insights', modalIdx)}
          {...pcModal}
          {...pp}
          sectionSupportsEntityCommit={false}
        />
      )
    }
    if (sectionKey === 'ideas') {
      const ideaMatch = existingEntities?.ideas
        ? findBestMatch(
            (item.data as { title?: string }).title || '',
            existingEntities.ideas.map((e) => ({ id: e.id, title: e.title })),
            DUPLICATE_THRESHOLD,
          )
        : null
      return (
        <StagedCard
          item={item}
          sectionKey="ideas"
          index={modalIdx}
          onToggle={dtoggle('ideas', modalIdx)}
          onUpdate={dupdate('ideas', modalIdx)}
          possibleMatch={ideaMatch ? { id: ideaMatch.id, title: ideaMatch.title, entityType: 'idea' } : null}
          entityType="idea"
          onLinkToExisting={onLinkToExisting}
          onUseExisting={setUseExisting}
          existingEntities={existingEntities}
          linkChooserOpen={chooserOpen('ideas')}
          onOpenLinkChooser={dlinkOpen('ideas', modalIdx)}
          onCloseLinkChooser={() => setLinkChooserFor(null)}
          onLinkChoose={dapply('ideas', modalIdx)}
          {...pcModal}
          {...pp}
        />
      )
    }
    if (sectionKey === 'initiatives') {
      const initMatch = existingEntities?.initiatives
        ? findBestMatch(
            (item.data as { title?: string }).title || '',
            existingEntities.initiatives.map((e) => ({ id: e.id, title: e.title })),
            DUPLICATE_THRESHOLD,
          )
        : null
      const extractorMatch = getExtractorSuggestedMatch(
        item.data as Parameters<typeof getExtractorSuggestedMatch>[0],
        'initiative',
        existingEntities,
      )
      return (
        <StagedCard
          item={item}
          sectionKey="initiatives"
          index={modalIdx}
          onToggle={dtoggle('initiatives', modalIdx)}
          onUpdate={dupdate('initiatives', modalIdx)}
          possibleMatch={initMatch ? { id: initMatch.id, title: initMatch.title, entityType: 'initiative' } : null}
          extractorSuggestedMatch={extractorMatch}
          entityType="initiative"
          onLinkToExisting={onLinkToExisting}
          onUseExisting={setUseExisting}
          existingEntities={existingEntities}
          linkChooserOpen={chooserOpen('initiatives')}
          onOpenLinkChooser={dlinkOpen('initiatives', modalIdx)}
          onCloseLinkChooser={() => setLinkChooserFor(null)}
          onLinkChoose={dapply('initiatives', modalIdx)}
          {...pcModal}
          {...pp}
        />
      )
    }
    if (sectionKey === 'projects') {
      const projMatch = existingEntities?.projects
        ? findBestMatch(
            (item.data as { title?: string }).title || '',
            existingEntities.projects.map((e) => ({ id: e.id, title: e.title })),
            DUPLICATE_THRESHOLD,
          )
        : null
      const extractorMatch = getExtractorSuggestedMatch(
        item.data as Parameters<typeof getExtractorSuggestedMatch>[0],
        'project',
        existingEntities,
      )
      return (
        <StagedCard
          item={item}
          sectionKey="projects"
          index={modalIdx}
          onToggle={dtoggle('projects', modalIdx)}
          onUpdate={dupdate('projects', modalIdx)}
          possibleMatch={projMatch ? { id: projMatch.id, title: projMatch.title, entityType: 'project' } : null}
          extractorSuggestedMatch={extractorMatch}
          entityType="project"
          onLinkToExisting={onLinkToExisting}
          onUseExisting={setUseExisting}
          existingEntities={existingEntities}
          linkChooserOpen={chooserOpen('projects')}
          onOpenLinkChooser={dlinkOpen('projects', modalIdx)}
          onCloseLinkChooser={() => setLinkChooserFor(null)}
          onLinkChoose={dapply('projects', modalIdx)}
          {...pcModal}
          {...pp}
        />
      )
    }
    if (sectionKey === 'tasks') {
      const taskMatch = existingEntities?.tasks
        ? findBestMatch(
            (item.data as { title?: string }).title || '',
            existingEntities.tasks.map((e) => ({ id: e.id, title: e.title })),
            DUPLICATE_THRESHOLD,
          )
        : null
      const extractorMatch = getExtractorSuggestedMatch(
        item.data as Parameters<typeof getExtractorSuggestedMatch>[0],
        'task',
        existingEntities,
      )
      return (
        <StagedCard
          item={item}
          sectionKey="tasks"
          index={modalIdx}
          onToggle={dtoggle('tasks', modalIdx)}
          onUpdate={dupdate('tasks', modalIdx)}
          possibleMatch={taskMatch ? { id: taskMatch.id, title: taskMatch.title, entityType: 'task' } : null}
          extractorSuggestedMatch={extractorMatch}
          entityType="task"
          onLinkToExisting={onLinkToExisting}
          onUseExisting={setUseExisting}
          existingEntities={existingEntities}
          linkChooserOpen={chooserOpen('tasks')}
          onOpenLinkChooser={dlinkOpen('tasks', modalIdx)}
          onCloseLinkChooser={() => setLinkChooserFor(null)}
          onLinkChoose={dapply('tasks', modalIdx)}
          {...pcModal}
          {...pp}
        />
      )
    }
    if (sectionKey === 'assets') {
      const assetMatch = existingEntities?.assets
        ? findBestMatch(
            (item.data as { name?: string }).name || '',
            existingEntities.assets.map((e) => ({ id: e.id, title: e.name })),
            DUPLICATE_THRESHOLD,
          )
        : null
      const extractorMatch = getExtractorSuggestedMatch(
        item.data as Parameters<typeof getExtractorSuggestedMatch>[0],
        'asset',
        existingEntities,
      )
      return (
        <StagedCard
          item={item}
          sectionKey="assets"
          index={modalIdx}
          onToggle={dtoggle('assets', modalIdx)}
          onUpdate={dupdate('assets', modalIdx)}
          possibleMatch={assetMatch ? { id: assetMatch.id, title: assetMatch.title, entityType: 'asset' } : null}
          extractorSuggestedMatch={extractorMatch}
          entityType="asset"
          onLinkToExisting={onLinkToExisting}
          onUseExisting={setUseExisting}
          existingEntities={existingEntities}
          linkChooserOpen={chooserOpen('assets')}
          onOpenLinkChooser={dlinkOpen('assets', modalIdx)}
          onCloseLinkChooser={() => setLinkChooserFor(null)}
          onLinkChoose={dapply('assets', modalIdx)}
          {...pcModal}
          {...pp}
        />
      )
    }
    if (sectionKey === 'people') {
      const personMatch = existingEntities?.people
        ? findBestMatch(
            (item.data as { name?: string }).name || '',
            existingEntities.people.map((e) => ({ id: e.id, title: e.name })),
            DUPLICATE_THRESHOLD,
          )
        : null
      const extractorMatch = getExtractorSuggestedMatch(
        item.data as Parameters<typeof getExtractorSuggestedMatch>[0],
        'person',
        existingEntities,
      )
      return (
        <StagedCard
          item={item}
          sectionKey="people"
          index={modalIdx}
          onToggle={dtoggle('people', modalIdx)}
          onUpdate={dupdate('people', modalIdx)}
          possibleMatch={personMatch ? { id: personMatch.id, title: personMatch.title, entityType: 'person' } : null}
          extractorSuggestedMatch={extractorMatch}
          entityType="person"
          onLinkToExisting={onLinkToExisting}
          onUseExisting={setUseExisting}
          existingEntities={existingEntities}
          linkChooserOpen={chooserOpen('people')}
          onOpenLinkChooser={dlinkOpen('people', modalIdx)}
          onCloseLinkChooser={() => setLinkChooserFor(null)}
          onLinkChoose={dapply('people', modalIdx)}
          {...pcModal}
          {...pp}
        />
      )
    }
    if (sectionKey === 'signals') {
      return (
        <StagedCard
          item={item}
          sectionKey="signals"
          index={modalIdx}
          onToggle={dtoggle('signals', modalIdx)}
          onUpdate={dupdate('signals', modalIdx)}
          existingEntities={existingEntities}
          linkChooserOpen={chooserOpen('signals')}
          onOpenLinkChooser={dlinkOpen('signals', modalIdx)}
          onCloseLinkChooser={() => setLinkChooserFor(null)}
          onLinkChoose={dapply('signals', modalIdx)}
          {...pcModal}
          {...pp}
        />
      )
    }
    return null
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-lg font-semibold text-slate-200">Review extraction</h3>
        <div className="flex gap-2 flex-wrap items-center">
          {fetchCandidatePresortTriage && existingEntities && presortAllCandidateCount > 0 && (
            <button
              type="button"
              disabled={
                !canPresortAll ||
                placementBulkLoading ||
                commitLoading ||
                Boolean(committingItemId)
              }
              onClick={() => void handleSuggestPlacementAll()}
              title={
                !placementBulkReady
                  ? 'Finish extraction or file read before presorting the full list.'
                  : 'Quick triage: mark each row Existing / New / Unsure (use Suggest placement on a card for full placement).'
              }
              className="px-3 py-1.5 rounded-lg border border-amber-600/80 text-amber-100 hover:bg-amber-900/35 disabled:opacity-40 disabled:cursor-not-allowed text-sm whitespace-nowrap"
            >
              {placementBulkLoading && placementBulkProgress
                ? `Presort all (${placementBulkProgress.cur}/${placementBulkProgress.total})`
                : placementBulkLoading
                  ? 'Presorting…'
                  : 'Presort all'}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg bg-slate-600 hover:bg-slate-500 text-slate-200 text-sm"
          >
            Close
          </button>
          {!perCardActions && (
            <button
              type="button"
              onClick={onCommit}
              disabled={!hasApproved || commitLoading}
              className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-medium"
            >
              {commitLoading ? 'Creating…' : 'Create selected items'}
            </button>
          )}
        </div>
      </div>

      {!perCardActions && commitPreview.length > 0 && (
        <div className="rounded-lg border border-slate-600 bg-slate-800/50 p-3">
          <h4 className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-2">Commit summary</h4>
          <p className="text-slate-500 text-xs mb-2">What will happen when you commit:</p>
          <ul className="space-y-1 text-sm">
            {commitPreview.map((line, i) => (
              <li key={i} className="text-slate-300 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                {line.kind === 'use_existing' ? (
                  <span className="text-emerald-400/90">Use existing</span>
                ) : (
                  <span className="text-slate-200">Create as {line.effectiveType}</span>
                )}
                <span className="font-medium truncate max-w-[200px]" title={line.title}>{line.title}</span>
                {line.parent && <span className="text-slate-500 text-xs">→ under {line.parent.parentType}</span>}
                {(line.personCount > 0 || line.assetCount > 0) && (
                  <span className="text-slate-500 text-xs">
                    {line.personCount > 0 && `${line.personCount} person${line.personCount !== 1 ? 's' : ''}`}
                    {line.personCount > 0 && line.assetCount > 0 && ' · '}
                    {line.assetCount > 0 && `${line.assetCount} asset${line.assetCount !== 1 ? 's' : ''}`}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {commitError && (
        <div className="rounded-lg bg-red-900/30 border border-red-700 text-red-200 text-sm p-3">
          {commitError}
        </div>
      )}

      <div
        className={
          perCardActions
            ? 'grid gap-6 grid-cols-1 w-full min-w-0'
            : 'grid gap-6 md:grid-cols-2 w-full min-w-0'
        }
      >
        {staging.summary && (
          <Section title="Meeting summary">
            <ul className="space-y-2">
              <SummaryRow
                item={staging.summary}
                onToggle={() => toggle('summary', 0)}
                perCardActions={perCardActions}
                onDismissSummary={onDismissSummary}
              />
            </ul>
          </Section>
        )}

        {staging.ideas.length > 0 && (() => {
          const arr = staging.ideas
          const sorted = sortStagedItems(arr, 'idea')
          const summaryCounts = getSectionSummary(arr, 'idea')
          const summaryLine = summaryCounts.lowConfidence || summaryCounts.possibleDuplicates ? formatSectionSummary(summaryCounts) : undefined
          return (
            <Section
              title="Ideas"
              summary={summaryLine}
              actions={
                !perCardActions ? (
                  <SectionBatchActions sectionKey="ideas" items={arr} staging={staging} onStagingChange={onStagingChange} existingEntities={existingEntities} />
                ) : undefined
              }
            >
              {perCardActions ? (
                <StagingCompactTable
                  sorted={sorted}
                  stagingArray={arr}
                  sectionKey="ideas"
                  onOpenRow={(id) => openStagingDetail('ideas', id)}
                  onDismissOneItem={onDismissOneItem}
                  committingItemId={committingItemId}
                  triageEnabled={Boolean(fetchCandidatePresortTriage)}
                />
              ) : (
                <ul className="space-y-2">
                  {sorted.map((item) => {
                    const originalIndex = arr.findIndex((x) => x.id === item.id)
                    const ideaMatch = existingEntities?.ideas
                      ? findBestMatch((item.data as { title?: string }).title || '', existingEntities.ideas.map((e) => ({ id: e.id, title: e.title })), DUPLICATE_THRESHOLD)
                      : null
                    return (
                      <StagedCard
                        key={item.id}
                        item={item}
                        sectionKey="ideas"
                        index={originalIndex}
                        onToggle={() => toggle('ideas', originalIndex)}
                        onUpdate={(patch) => updateItem('ideas', originalIndex, patch)}
                        possibleMatch={ideaMatch ? { id: ideaMatch.id, title: ideaMatch.title, entityType: 'idea' } : null}
                        entityType="idea"
                        onLinkToExisting={onLinkToExisting}
                        onUseExisting={setUseExisting}
                        existingEntities={existingEntities}
                        linkChooserOpen={linkChooserFor?.sectionKey === 'ideas' && linkChooserFor?.index === originalIndex}
                        onOpenLinkChooser={() => setLinkChooserFor({ sectionKey: 'ideas', index: originalIndex })}
                        onCloseLinkChooser={() => setLinkChooserFor(null)}
                        onLinkChoose={(action, entityType, id) => applyLink('ideas', originalIndex, action, entityType, id)}
                        {...pc}
                        {...placementPropsFor('ideas', item, originalIndex)}
                      />
                    )
                  })}
                </ul>
              )}
            </Section>
          )
        })()}

        {staging.initiatives.length > 0 && (() => {
          const arr = staging.initiatives
          const sorted = sortStagedItems(arr, 'initiative')
          const summaryCounts = getSectionSummary(arr, 'initiative')
          const summaryLine = summaryCounts.lowConfidence || summaryCounts.possibleDuplicates ? formatSectionSummary(summaryCounts) : undefined
          return (
            <Section
              title="Proposed initiatives"
              summary={summaryLine}
              actions={
                !perCardActions ? (
                  <SectionBatchActions sectionKey="initiatives" items={arr} staging={staging} onStagingChange={onStagingChange} existingEntities={existingEntities} />
                ) : undefined
              }
            >
              {perCardActions ? (
                <StagingCompactTable
                  sorted={sorted}
                  stagingArray={arr}
                  sectionKey="initiatives"
                  onOpenRow={(id) => openStagingDetail('initiatives', id)}
                  onDismissOneItem={onDismissOneItem}
                  committingItemId={committingItemId}
                  triageEnabled={Boolean(fetchCandidatePresortTriage)}
                />
              ) : (
                <ul className="space-y-2">
                  {sorted.map((item) => {
                    const originalIndex = arr.findIndex((x) => x.id === item.id)
                    const initMatch = existingEntities?.initiatives
                      ? findBestMatch((item.data as { title?: string }).title || '', existingEntities.initiatives.map((e) => ({ id: e.id, title: e.title })), DUPLICATE_THRESHOLD)
                      : null
                    const extractorMatch = getExtractorSuggestedMatch(item.data as Parameters<typeof getExtractorSuggestedMatch>[0], 'initiative', existingEntities)
                    return (
                      <StagedCard
                        key={item.id}
                        item={item}
                        sectionKey="initiatives"
                        index={originalIndex}
                        onToggle={() => toggle('initiatives', originalIndex)}
                        onUpdate={(patch) => updateItem('initiatives', originalIndex, patch)}
                        possibleMatch={initMatch ? { id: initMatch.id, title: initMatch.title, entityType: 'initiative' } : null}
                        extractorSuggestedMatch={extractorMatch}
                        entityType="initiative"
                        onLinkToExisting={onLinkToExisting}
                        onUseExisting={setUseExisting}
                        existingEntities={existingEntities}
                        linkChooserOpen={linkChooserFor?.sectionKey === 'initiatives' && linkChooserFor?.index === originalIndex}
                        onOpenLinkChooser={() => setLinkChooserFor({ sectionKey: 'initiatives', index: originalIndex })}
                        onCloseLinkChooser={() => setLinkChooserFor(null)}
                        onLinkChoose={(action, entityType, id) => applyLink('initiatives', originalIndex, action, entityType, id)}
                        {...pc}
                        {...placementPropsFor('initiatives', item, originalIndex)}
                      />
                    )
                  })}
                </ul>
              )}
            </Section>
          )
        })()}

        {staging.projects.length > 0 && (() => {
          const arr = staging.projects
          const sorted = sortStagedItems(arr, 'project')
          const summaryCounts = getSectionSummary(arr, 'project')
          const summaryLine = summaryCounts.lowConfidence || summaryCounts.possibleDuplicates ? formatSectionSummary(summaryCounts) : undefined
          return (
            <Section
              title="Proposed projects"
              summary={summaryLine}
              actions={
                !perCardActions ? (
                  <SectionBatchActions sectionKey="projects" items={arr} staging={staging} onStagingChange={onStagingChange} existingEntities={existingEntities} />
                ) : undefined
              }
            >
              {perCardActions ? (
                <StagingCompactTable
                  sorted={sorted}
                  stagingArray={arr}
                  sectionKey="projects"
                  onOpenRow={(id) => openStagingDetail('projects', id)}
                  onDismissOneItem={onDismissOneItem}
                  committingItemId={committingItemId}
                  triageEnabled={Boolean(fetchCandidatePresortTriage)}
                />
              ) : (
                <ul className="space-y-2">
                  {sorted.map((item) => {
                    const originalIndex = arr.findIndex((x) => x.id === item.id)
                    const projMatch = existingEntities?.projects
                      ? findBestMatch((item.data as { title?: string }).title || '', existingEntities.projects.map((e) => ({ id: e.id, title: e.title })), DUPLICATE_THRESHOLD)
                      : null
                    const extractorMatch = getExtractorSuggestedMatch(item.data as Parameters<typeof getExtractorSuggestedMatch>[0], 'project', existingEntities)
                    return (
                      <StagedCard
                        key={item.id}
                        item={item}
                        sectionKey="projects"
                        index={originalIndex}
                        onToggle={() => toggle('projects', originalIndex)}
                        onUpdate={(patch) => updateItem('projects', originalIndex, patch)}
                        possibleMatch={projMatch ? { id: projMatch.id, title: projMatch.title, entityType: 'project' } : null}
                        extractorSuggestedMatch={extractorMatch}
                        entityType="project"
                        onLinkToExisting={onLinkToExisting}
                        onUseExisting={setUseExisting}
                        existingEntities={existingEntities}
                        linkChooserOpen={linkChooserFor?.sectionKey === 'projects' && linkChooserFor?.index === originalIndex}
                        onOpenLinkChooser={() => setLinkChooserFor({ sectionKey: 'projects', index: originalIndex })}
                        onCloseLinkChooser={() => setLinkChooserFor(null)}
                        onLinkChoose={(action, entityType, id) => applyLink('projects', originalIndex, action, entityType, id)}
                        {...pc}
                        {...placementPropsFor('projects', item, originalIndex)}
                      />
                    )
                  })}
                </ul>
              )}
            </Section>
          )
        })()}

        {staging.tasks.length > 0 && (() => {
          const arr = staging.tasks
          const sorted = sortStagedItems(arr, 'task')
          const summaryCounts = getSectionSummary(arr, 'task')
          const summaryLine = summaryCounts.lowConfidence || summaryCounts.possibleDuplicates ? formatSectionSummary(summaryCounts) : undefined
          return (
            <Section
              title="Proposed tasks"
              summary={summaryLine}
              actions={
                !perCardActions ? (
                  <SectionBatchActions sectionKey="tasks" items={arr} staging={staging} onStagingChange={onStagingChange} existingEntities={existingEntities} />
                ) : undefined
              }
            >
              {perCardActions ? (
                <StagingCompactTable
                  sorted={sorted}
                  stagingArray={arr}
                  sectionKey="tasks"
                  onOpenRow={(id) => openStagingDetail('tasks', id)}
                  onDismissOneItem={onDismissOneItem}
                  committingItemId={committingItemId}
                  triageEnabled={Boolean(fetchCandidatePresortTriage)}
                />
              ) : (
                <ul className="space-y-2">
                  {sorted.map((item) => {
                    const originalIndex = arr.findIndex((x) => x.id === item.id)
                    const taskMatch = existingEntities?.tasks
                      ? findBestMatch((item.data as { title?: string }).title || '', existingEntities.tasks.map((e) => ({ id: e.id, title: e.title })), DUPLICATE_THRESHOLD)
                      : null
                    const extractorMatch = getExtractorSuggestedMatch(item.data as Parameters<typeof getExtractorSuggestedMatch>[0], 'task', existingEntities)
                    return (
                      <StagedCard
                        key={item.id}
                        item={item}
                        sectionKey="tasks"
                        index={originalIndex}
                        onToggle={() => toggle('tasks', originalIndex)}
                        onUpdate={(patch) => updateItem('tasks', originalIndex, patch)}
                        possibleMatch={taskMatch ? { id: taskMatch.id, title: taskMatch.title, entityType: 'task' } : null}
                        extractorSuggestedMatch={extractorMatch}
                        entityType="task"
                        onLinkToExisting={onLinkToExisting}
                        onUseExisting={setUseExisting}
                        existingEntities={existingEntities}
                        linkChooserOpen={linkChooserFor?.sectionKey === 'tasks' && linkChooserFor?.index === originalIndex}
                        onOpenLinkChooser={() => setLinkChooserFor({ sectionKey: 'tasks', index: originalIndex })}
                        onCloseLinkChooser={() => setLinkChooserFor(null)}
                        onLinkChoose={(action, entityType, id) => applyLink('tasks', originalIndex, action, entityType, id)}
                        {...pc}
                        {...placementPropsFor('tasks', item, originalIndex)}
                      />
                    )
                  })}
                </ul>
              )}
            </Section>
          )
        })()}

        {staging.assets.length > 0 && (() => {
          const arr = staging.assets
          const sorted = sortStagedItems(arr, 'asset')
          const summaryCounts = getSectionSummary(arr, 'asset')
          const summaryLine = summaryCounts.lowConfidence || summaryCounts.possibleDuplicates ? formatSectionSummary(summaryCounts) : undefined
          return (
            <Section
              title="Proposed assets"
              summary={summaryLine}
              actions={
                !perCardActions ? (
                  <SectionBatchActions sectionKey="assets" items={arr} staging={staging} onStagingChange={onStagingChange} existingEntities={existingEntities} />
                ) : undefined
              }
            >
              {perCardActions ? (
                <StagingCompactTable
                  sorted={sorted}
                  stagingArray={arr}
                  sectionKey="assets"
                  onOpenRow={(id) => openStagingDetail('assets', id)}
                  onDismissOneItem={onDismissOneItem}
                  committingItemId={committingItemId}
                  triageEnabled={Boolean(fetchCandidatePresortTriage)}
                />
              ) : (
                <ul className="space-y-2">
                  {sorted.map((item) => {
                    const originalIndex = arr.findIndex((x) => x.id === item.id)
                    const assetMatch = existingEntities?.assets
                      ? findBestMatch((item.data as { name?: string }).name || '', existingEntities.assets.map((e) => ({ id: e.id, title: e.name })), DUPLICATE_THRESHOLD)
                      : null
                    const extractorMatch = getExtractorSuggestedMatch(item.data as Parameters<typeof getExtractorSuggestedMatch>[0], 'asset', existingEntities)
                    return (
                      <StagedCard
                        key={item.id}
                        item={item}
                        sectionKey="assets"
                        index={originalIndex}
                        onToggle={() => toggle('assets', originalIndex)}
                        onUpdate={(patch) => updateItem('assets', originalIndex, patch)}
                        possibleMatch={assetMatch ? { id: assetMatch.id, title: assetMatch.title, entityType: 'asset' } : null}
                        extractorSuggestedMatch={extractorMatch}
                        entityType="asset"
                        onLinkToExisting={onLinkToExisting}
                        onUseExisting={setUseExisting}
                        existingEntities={existingEntities}
                        linkChooserOpen={linkChooserFor?.sectionKey === 'assets' && linkChooserFor?.index === originalIndex}
                        onOpenLinkChooser={() => setLinkChooserFor({ sectionKey: 'assets', index: originalIndex })}
                        onCloseLinkChooser={() => setLinkChooserFor(null)}
                        onLinkChoose={(action, entityType, id) => applyLink('assets', originalIndex, action, entityType, id)}
                        {...pc}
                        {...placementPropsFor('assets', item, originalIndex)}
                      />
                    )
                  })}
                </ul>
              )}
            </Section>
          )
        })()}

        {staging.signals.length > 0 && (() => {
          const arr = staging.signals
          const sorted = sortStagedItems(arr, 'signal')
          const summaryCounts = getSectionSummary(arr, 'signal')
          const summaryLine = summaryCounts.blockers || summaryCounts.lowConfidence || summaryCounts.possibleDuplicates ? formatSectionSummary(summaryCounts) : undefined
          return (
            <Section
              title="Signals"
              summary={summaryLine}
              actions={
                !perCardActions ? (
                  <SectionBatchActions sectionKey="signals" items={arr} staging={staging} onStagingChange={onStagingChange} existingEntities={existingEntities} />
                ) : undefined
              }
            >
              {perCardActions ? (
                <StagingCompactTable
                  sorted={sorted}
                  stagingArray={arr}
                  sectionKey="signals"
                  onOpenRow={(id) => openStagingDetail('signals', id)}
                  onDismissOneItem={onDismissOneItem}
                  committingItemId={committingItemId}
                  triageEnabled={Boolean(fetchCandidatePresortTriage)}
                />
              ) : (
                <ul className="space-y-2">
                  {sorted.map((item) => {
                    const originalIndex = arr.findIndex((x) => x.id === item.id)
                    return (
                      <StagedCard
                        key={item.id}
                        item={item}
                        sectionKey="signals"
                        index={originalIndex}
                        onToggle={() => toggle('signals', originalIndex)}
                        onUpdate={(patch) => updateItem('signals', originalIndex, patch)}
                        existingEntities={existingEntities}
                        linkChooserOpen={linkChooserFor?.sectionKey === 'signals' && linkChooserFor?.index === originalIndex}
                        onOpenLinkChooser={() => setLinkChooserFor({ sectionKey: 'signals', index: originalIndex })}
                        onCloseLinkChooser={() => setLinkChooserFor(null)}
                        onLinkChoose={(action, entityType, id) => applyLink('signals', originalIndex, action, entityType, id)}
                        {...pc}
                        {...placementPropsFor('signals', item, originalIndex)}
                      />
                    )
                  })}
                </ul>
              )}
            </Section>
          )
        })()}

        {staging.insights.length > 0 && (() => {
          const arr = staging.insights
          const sorted = sortStagedItems(arr, 'insight')
          const summaryCounts = getSectionSummary(arr, 'insight')
          const summaryLine = summaryCounts.lowConfidence || summaryCounts.possibleDuplicates ? formatSectionSummary(summaryCounts) : undefined
          return (
            <Section
              title="Notes / observations"
              summary={summaryLine}
              actions={
                !perCardActions ? (
                  <SectionBatchActions sectionKey="insights" items={arr} staging={staging} onStagingChange={onStagingChange} existingEntities={existingEntities} />
                ) : undefined
              }
            >
              {perCardActions ? (
                <StagingCompactTable
                  sorted={sorted}
                  stagingArray={arr}
                  sectionKey="insights"
                  onOpenRow={(id) => openStagingDetail('insights', id)}
                  onDismissOneItem={onDismissOneItem}
                  committingItemId={committingItemId}
                  triageEnabled={Boolean(fetchCandidatePresortTriage)}
                />
              ) : (
                <ul className="space-y-2">
                  {sorted.map((item) => {
                    const originalIndex = arr.findIndex((x) => x.id === item.id)
                    return (
                      <StagedCard
                        key={item.id}
                        item={item}
                        sectionKey="insights"
                        index={originalIndex}
                        onToggle={() => toggle('insights', originalIndex)}
                        onUpdate={(patch) => updateItem('insights', originalIndex, patch)}
                        existingEntities={existingEntities}
                        linkChooserOpen={linkChooserFor?.sectionKey === 'insights' && linkChooserFor?.index === originalIndex}
                        onOpenLinkChooser={() => setLinkChooserFor({ sectionKey: 'insights', index: originalIndex })}
                        onCloseLinkChooser={() => setLinkChooserFor(null)}
                        onLinkChoose={(action, entityType, id) => applyLink('insights', originalIndex, action, entityType, id)}
                        {...pc}
                        {...placementPropsFor('insights', item, originalIndex)}
                        sectionSupportsEntityCommit={false}
                      />
                    )
                  })}
                </ul>
              )}
            </Section>
          )
        })()}

        {staging.people.length > 0 && (() => {
          const arr = staging.people
          const sorted = sortStagedItems(arr, 'person')
          const summaryCounts = getSectionSummary(arr, 'person')
          const summaryLine = summaryCounts.lowConfidence || summaryCounts.possibleDuplicates ? formatSectionSummary(summaryCounts) : undefined
          return (
            <Section
              title="People references"
              summary={summaryLine}
              actions={
                !perCardActions ? (
                  <SectionBatchActions sectionKey="people" items={arr} staging={staging} onStagingChange={onStagingChange} existingEntities={existingEntities} />
                ) : undefined
              }
            >
              {perCardActions ? (
                <StagingCompactTable
                  sorted={sorted}
                  stagingArray={arr}
                  sectionKey="people"
                  onOpenRow={(id) => openStagingDetail('people', id)}
                  onDismissOneItem={onDismissOneItem}
                  committingItemId={committingItemId}
                  triageEnabled={Boolean(fetchCandidatePresortTriage)}
                />
              ) : (
                <ul className="space-y-2">
                  {sorted.map((item) => {
                    const originalIndex = arr.findIndex((x) => x.id === item.id)
                    const personMatch = existingEntities?.people
                      ? findBestMatch((item.data as { name?: string }).name || '', existingEntities.people.map((e) => ({ id: e.id, title: e.name })), DUPLICATE_THRESHOLD)
                      : null
                    const extractorMatch = getExtractorSuggestedMatch(item.data as Parameters<typeof getExtractorSuggestedMatch>[0], 'person', existingEntities)
                    return (
                      <StagedCard
                        key={item.id}
                        item={item}
                        sectionKey="people"
                        index={originalIndex}
                        onToggle={() => toggle('people', originalIndex)}
                        onUpdate={(patch) => updateItem('people', originalIndex, patch)}
                        possibleMatch={personMatch ? { id: personMatch.id, title: personMatch.title, entityType: 'person' } : null}
                        extractorSuggestedMatch={extractorMatch}
                        entityType="person"
                        onLinkToExisting={onLinkToExisting}
                        onUseExisting={setUseExisting}
                        existingEntities={existingEntities}
                        linkChooserOpen={linkChooserFor?.sectionKey === 'people' && linkChooserFor?.index === originalIndex}
                        onOpenLinkChooser={() => setLinkChooserFor({ sectionKey: 'people', index: originalIndex })}
                        onCloseLinkChooser={() => setLinkChooserFor(null)}
                        onLinkChoose={(action, entityType, id) => applyLink('people', originalIndex, action, entityType, id)}
                        {...pc}
                        {...placementPropsFor('people', item, originalIndex)}
                      />
                    )
                  })}
                </ul>
              )}
            </Section>
          )
        })()}
      </div>

      {stagingDetailOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/65"
          onClick={() => closeStagingDetail()}
          role="presentation"
        >
          <div
            className="bg-slate-900 border border-slate-600 rounded-xl shadow-xl w-full max-w-2xl max-h-[92vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="staging-detail-title"
          >
            <div className="shrink-0 flex flex-wrap items-center gap-2 px-4 py-3 border-b border-slate-700 bg-slate-900">
              <span id="staging-detail-title" className="text-sm font-medium text-slate-200 mr-auto min-w-0">
                Candidate detail
              </span>
              <button
                type="button"
                onClick={() => closeStagingDetail()}
                className="px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800 text-sm shrink-0"
              >
                Close
              </button>
            </div>
            {(() => {
              const sk = stagingDetailOpen.sectionKey
              const iid = stagingDetailOpen.itemId
              const a = staging[sk]
              const stillThere = Array.isArray(a) && a.some((x) => x.id === iid)
              return !stillThere ? (
                <div className="shrink-0 px-4 py-2 bg-amber-950/35 border-b border-amber-800/45 text-amber-100/90 text-xs">
                  This row is not in the current extraction list (results may have refreshed). Showing the last opened
                  copy—edits and actions are disabled until the row appears again.
                </div>
              ) : null
            })()}
            <div className="flex-1 min-h-0 overflow-y-auto p-4">
              {/* StagedCard roots in <li> — valid inside a single-item list */}
              <ul className="list-none p-0 m-0 space-y-0">{renderStagingDetailCard()}</ul>
            </div>
          </div>
        </div>
      )}

      {!staging.summary &&
        staging.insights.length === 0 &&
        staging.ideas.length === 0 &&
        staging.initiatives.length === 0 &&
        staging.projects.length === 0 &&
        staging.tasks.length === 0 &&
        staging.assets.length === 0 &&
        staging.people.length === 0 &&
        staging.signals.length === 0 && (
          <p className="text-slate-500 text-sm">
            No durable candidates were extracted for review. In chunk mode, open Technical details on the progress card to see per-chunk notes. Try a section with explicit decisions, owners, or next steps.
          </p>
        )}
    </div>
  )
}
