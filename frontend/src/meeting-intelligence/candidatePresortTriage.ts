/**
 * Types + mapping for POST /vision-execution/presort-candidate-triage (coarse list presort only).
 */

import type {
  CommitableStagedKind,
  PresortBucket,
  PresortEntityType,
  PresortExistingEntityType,
  StagedItemBase,
  StagedItemKind,
} from './stagingTypes'

/** Raw API body (snake_case). */
export interface CandidatePresortTriageApiResponse {
  presort_bucket?: string
  presort_type?: string | null
  presort_confidence?: number | null
  presort_existing_id?: string | null
  presort_existing_title?: string | null
  /** Catalog kind for presort_existing_id (server-derived from ENTITY_CATALOG). */
  presort_existing_type?: string | null
  presort_reason?: string | null
  execution_blocked?: boolean
  error?: string
  model_used?: string
  provider_used?: string
  client_correlation_id?: string
  _fallback?: boolean
}

const COARSE: ReadonlySet<string> = new Set(['idea', 'initiative', 'project', 'task'])

const PRESORT_EXISTING_KINDS = new Set<string>(['idea', 'initiative', 'project', 'task', 'asset', 'person'])

function parsePresortExistingType(raw: unknown): PresortExistingEntityType | null {
  if (raw == null) return null
  const t = String(raw).toLowerCase().trim()
  return PRESORT_EXISTING_KINDS.has(t) ? (t as PresortExistingEntityType) : null
}

function commitOverrideFromPresort(
  apiType: PresortExistingEntityType | null,
  stagedKind: StagedItemKind | undefined,
): CommitableStagedKind | undefined {
  if (apiType) return apiType
  if (stagedKind && PRESORT_EXISTING_KINDS.has(stagedKind)) {
    return stagedKind as CommitableStagedKind
  }
  return undefined
}

export interface MapPresortTriageContext {
  /** Staging row kind — used to infer overrideType when API omits presort_existing_type. */
  stagedItemKind?: StagedItemKind
}

/** Pass-through fields from meeting extraction so presort can honor existing*MatchId / graph ids. */
const PRESORT_TRIAGE_FIELD_KEYS = [
  'confidence',
  'matchConfidence',
  'sourceStage',
  'existingIdeaMatchId',
  'existingInitiativeMatchId',
  'existingProjectMatchId',
  'existingTaskMatchId',
  'existingAssetMatchId',
  'existingPersonMatchId',
  'initiativeId',
  'projectId',
] as const

export type PresortTriageCandidatePayload = Record<string, unknown> & {
  title: string
  summary: string
  evidence_quote?: string
}

export function buildPresortTriageCandidate(
  data: Record<string, unknown>,
  parts: { title: string; summary: string; evidence_quote?: string },
): PresortTriageCandidatePayload {
  const out: PresortTriageCandidatePayload = {
    title: parts.title,
    summary: parts.summary,
    ...(parts.evidence_quote !== undefined ? { evidence_quote: parts.evidence_quote } : {}),
  }
  for (const k of PRESORT_TRIAGE_FIELD_KEYS) {
    const v = data[k]
    if (v === undefined || v === null) continue
    if (typeof v === 'string' && !v.trim()) continue
    out[k] = v
  }
  return out
}

function clamp01(n: number): number {
  if (Number.isNaN(n)) return 0
  return Math.max(0, Math.min(1, n))
}

/**
 * Merge API triage into staging. When bucket is existing with a valid id, sets acceptedExistingId
 * and overrideType so commit matches placement-style “use existing” semantics.
 */
export function mapPresortTriageApiToStagingPatch(
  r: CandidatePresortTriageApiResponse,
  ctx?: MapPresortTriageContext,
): Partial<StagedItemBase> {
  const hasBucket =
    r.presort_bucket === 'existing' || r.presort_bucket === 'new' || r.presort_bucket === 'unsure'
  if (r.execution_blocked && !hasBucket) {
    return {
      presortBucket: 'new',
      presortType: 'idea',
      presortConfidence: 0.45,
      presortExistingId: null,
      presortExistingTitle: null,
      presortExistingType: null,
      presortReason: r.presort_reason?.trim() || 'Triage API blocked — lean new',
    }
  }
  const reasonTrim = r.presort_reason != null ? String(r.presort_reason).trim().slice(0, 240) : ''
  let bucket: PresortBucket =
    r.presort_bucket === 'existing' || r.presort_bucket === 'new' || r.presort_bucket === 'unsure'
      ? r.presort_bucket
      : 'new'
  const rawT = r.presort_type != null ? String(r.presort_type).toLowerCase().trim() : ''
  const presortType: PresortEntityType | null = COARSE.has(rawT) ? (rawT as PresortEntityType) : null
  const conf = typeof r.presort_confidence === 'number' ? clamp01(r.presort_confidence) : null

  if (bucket === 'existing') {
    const id = r.presort_existing_id != null ? String(r.presort_existing_id).trim() : ''
    const title = r.presort_existing_title != null ? String(r.presort_existing_title).trim() : ''
    if (!id) {
      return {
        presortBucket: 'new',
        presortType: presortType ?? 'idea',
        presortConfidence: conf != null ? Math.min(conf, 0.55) : 0.5,
        presortExistingId: null,
        presortExistingTitle: null,
        presortExistingType: null,
        presortReason: reasonTrim || 'Stated duplicate but no valid catalog id — lean new',
      }
    }
    const pet = parsePresortExistingType(r.presort_existing_type)
    const override = commitOverrideFromPresort(pet, ctx?.stagedItemKind)
    return {
      presortBucket: 'existing',
      presortType: null,
      presortConfidence: conf,
      presortExistingId: id,
      presortExistingTitle: title || null,
      presortExistingType: pet,
      acceptedExistingId: id,
      ...(override !== undefined ? { overrideType: override } : {}),
      presortReason: reasonTrim || null,
    }
  }

  return {
    presortBucket: bucket,
    presortType,
    presortConfidence: conf,
    presortExistingId: null,
    presortExistingTitle: null,
    presortExistingType: null,
    presortReason: reasonTrim || null,
  }
}
