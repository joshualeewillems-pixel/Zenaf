/**
 * Parse API or raw extraction output into typed MeetingExtraction.
 * Normalizes existing ExtractMeetingResponse (ideas, initiatives, tasks) and
 * supports future fields (summary, insights, projects, assets, people, signals).
 * Supports merging per-segment extractions with segment metadata.
 */

import { consolidateMeetingExtraction, normalizeCandidateText } from './consolidation'
import type {
  ExtractedConfidence,
  ExtractedInsight,
  ExtractedIdea,
  ExtractedInitiative,
  ExtractedProject,
  ExtractedSignal,
  ExtractedSignalKind,
  ExtractedTask,
  GraphInterpretation,
  GraphInterpretationAction,
  GraphInterpretationPayload,
  GraphInterpretationType,
  MeetingExtraction,
  TranscriptSegment,
} from './types'
import type {
  ExtractedCandidateProposedType,
  ExtractMeetingResponse,
} from '../vision-execution/types'

const nanoid = () => `ext-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`

const GRAPH_INTERP_TYPES = new Set<GraphInterpretationType>([
  'existing_enrichment',
  'existing_amendment',
  'child_of_existing',
  'genuinely_new',
  'signal_only',
])

const GRAPH_INTERP_ACTIONS = new Set<GraphInterpretationAction>([
  'update',
  'patch',
  'create_child',
  'create_new',
  'ignore',
])

function defaultActionForInterpretType(t: GraphInterpretationType): GraphInterpretationAction {
  switch (t) {
    case 'existing_enrichment':
      return 'update'
    case 'existing_amendment':
      return 'patch'
    case 'child_of_existing':
      return 'create_child'
    case 'genuinely_new':
      return 'create_new'
    case 'signal_only':
      return 'ignore'
    default:
      return 'ignore'
  }
}

function pickInterpretationPayload(raw: unknown): GraphInterpretationPayload | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const p = raw as Record<string, unknown>
  const o: GraphInterpretationPayload = {}
  if (typeof p.title === 'string') o.title = p.title
  if (typeof p.description === 'string') o.description = p.description
  if (typeof p.notes === 'string') o.notes = p.notes
  const pid =
    typeof p.parentId === 'string' ? p.parentId : typeof p.parent_id === 'string' ? p.parent_id : undefined
  if (pid) o.parentId = pid
  const ftp = p.fieldsToPatch ?? p.fields_to_patch
  if (ftp && typeof ftp === 'object' && !Array.isArray(ftp)) {
    o.fieldsToPatch = { ...(ftp as Record<string, unknown>) }
  }
  return Object.keys(o).length > 0 ? o : undefined
}

/** Validate server `interpretation` (camelCase or snake_case keys). */
function pickGraphInterpretationFromRow(row: unknown): GraphInterpretation | undefined {
  if (!row || typeof row !== 'object') return undefined
  const o = row as Record<string, unknown>
  const raw = o.interpretation
  if (!raw || typeof raw !== 'object') return undefined
  const ri = raw as Record<string, unknown>
  const t = typeof ri.type === 'string' ? ri.type : ''
  if (!GRAPH_INTERP_TYPES.has(t as GraphInterpretationType)) return undefined
  const targetId =
    typeof ri.targetId === 'string'
      ? ri.targetId
      : typeof ri.target_id === 'string'
        ? ri.target_id
        : undefined
  const conf = ri.confidence
  const confidence = typeof conf === 'number' && Number.isFinite(conf) ? conf : undefined
  const actionRaw = ri.action
  let action: GraphInterpretationAction | undefined
  if (typeof actionRaw === 'string' && GRAPH_INTERP_ACTIONS.has(actionRaw as GraphInterpretationAction)) {
    action = actionRaw as GraphInterpretationAction
  }
  if (!action) {
    action = defaultActionForInterpretType(t as GraphInterpretationType)
  }
  const payload = pickInterpretationPayload(ri.payload)
  return {
    type: t as GraphInterpretationType,
    ...(targetId ? { targetId } : {}),
    ...(confidence !== undefined ? { confidence } : {}),
    action,
    ...(payload ? { payload } : {}),
  }
}

/** Legacy API response from POST /extract-meeting or POST /extract-meeting-synthesis */
export interface LegacyExtractMeetingResponse {
  ideas?: (ExtractedIdea & { segmentId?: string | null; segmentTitle?: string | null })[]
  initiatives?: (ExtractedInitiative & { segmentId?: string | null; segmentTitle?: string | null })[]
  tasks?: (ExtractedTask & { segmentId?: string | null; segmentTitle?: string | null })[]
  // Optional richer fields the backend may return; all are best-effort and may be absent.
  summary?: {
    text?: string
    confidence?: ExtractedIdea['confidence'] | null
    interpretation?: GraphInterpretation
  } | null
  insights?: Array<{
    statement?: string
    sourceQuote?: string
    confidence?: ExtractedIdea['confidence'] | null
    segmentId?: string | null
    segmentTitle?: string | null
  }>
  projects?: Array<{
    title?: string
    initiativeTitle?: string
    brief?: string
    status?: string
    confidence?: ExtractedIdea['confidence'] | null
    sourceExcerpt?: string | null
    segmentId?: string | null
    segmentTitle?: string | null
  }>
  assets?: Array<{
    name: string
    kind?: string
    description?: string
    confidence?: ExtractedIdea['confidence'] | null
    sourceExcerpt?: string | null
    segmentId?: string | null
    segmentTitle?: string | null
  }>
  peopleReferences?: Array<{
    name: string
    role?: string
    context?: string
    confidence?: ExtractedIdea['confidence'] | null
    sourceExcerpt?: string | null
    segmentId?: string | null
    segmentTitle?: string | null
  }>
  people?: LegacyExtractMeetingResponse['peopleReferences']
  signals?: Array<{
    kind: string
    label?: string
    detail?: string
    confidence?: ExtractedIdea['confidence'] | null
    sourceExcerpt?: string | null
    segmentId?: string | null
    segmentTitle?: string | null
  }>
  /** Observation-only extract: flat rows for review typing in UI. */
  candidates?: Array<{
    id?: string
    text?: string
    /** Paraphrase / body text when ``text`` is a normalized title (e.g. promoted literals). */
    summary?: string | null
    kind?: string
    confidence?: number | null
    confidenceLabel?: ExtractedIdea['confidence'] | null
    sourceStage?: string | null
    segmentId?: string | null
    segmentTitle?: string | null
    sourceExcerpt?: string | null
    possibleMatches?: Array<{ id: string; type: string; similarity: number }>
    anchorRole?: string | null
    proposedType?: string | null
    interpretation?: GraphInterpretation
  }>
  error?: string
}

type LegacyCandidateRow = NonNullable<LegacyExtractMeetingResponse['candidates']>[number]

/** Fields shared across routed buckets (no id). */
type CandidateIdeaFields = Omit<ExtractedIdea, 'id'>

const PROPOSED_TYPES = new Set<string>([
  'project',
  'task',
  'initiative',
  'decision',
  'research',
  'signal',
  'observation',
])

function normalizeProposedType(c: LegacyCandidateRow): ExtractedCandidateProposedType | undefined {
  const ptRaw = (c as { proposedType?: string | null }).proposedType
  const s = typeof ptRaw === 'string' ? ptRaw.trim().toLowerCase() : ''
  return s && PROPOSED_TYPES.has(s) ? (s as ExtractedCandidateProposedType) : undefined
}

function mapCandidateRowToInitiative(m: CandidateIdeaFields): Omit<ExtractedInitiative, 'id'> {
  return {
    title: m.title,
    brief: m.summary,
    description: m.description,
    status: m.status ?? 'Captured',
    ownerName: null,
    notes: undefined,
    confidence: m.confidence ?? null,
    sourceExcerpt: m.sourceExcerpt ?? null,
    existingInitiativeMatchId: null,
    matchConfidence: null,
    segmentId: m.segmentId,
    segmentTitle: m.segmentTitle,
    consolidationMeta: undefined,
    anchorRole: m.anchorRole ?? null,
    ...(m.interpretation ? { interpretation: m.interpretation } : {}),
  }
}

function mapCandidateRowToProject(m: CandidateIdeaFields): Omit<ExtractedProject, 'id'> {
  return {
    title: m.title,
    initiativeTitle: undefined,
    initiativeId: null,
    brief: m.summary,
    status: m.status ?? 'Captured',
    confidence: m.confidence ?? null,
    sourceExcerpt: m.sourceExcerpt ?? null,
    existingInitiativeMatchId: null,
    existingProjectMatchId: null,
    matchConfidence: null,
    segmentId: m.segmentId,
    segmentTitle: m.segmentTitle,
    consolidationMeta: undefined,
    anchorRole: m.anchorRole ?? null,
    ...(m.interpretation ? { interpretation: m.interpretation } : {}),
  }
}

function mapCandidateRowToTaskRow(m: CandidateIdeaFields): Omit<ExtractedTask, 'id'> {
  return {
    title: m.title,
    projectTitle: undefined,
    projectId: null,
    initiativeTitle: undefined,
    initiativeId: null,
    description: m.description,
    status: m.status ?? 'Captured',
    suggestedOwner: null,
    assigneeName: null,
    notes: undefined,
    confidence: m.confidence ?? null,
    sourceExcerpt: m.sourceExcerpt ?? null,
    existingProjectMatchId: null,
    existingTaskMatchId: null,
    existingPersonMatchId: null,
    matchConfidence: null,
    segmentId: m.segmentId,
    segmentTitle: m.segmentTitle,
    consolidationMeta: undefined,
    anchorRole: m.anchorRole ?? null,
    ...(m.interpretation ? { interpretation: m.interpretation } : {}),
  }
}

function mapCandidateRowToInsight(m: CandidateIdeaFields): Omit<ExtractedInsight, 'id'> {
  const statement = (m.summary || m.title || '').trim() || m.title
  return {
    statement,
    sourceQuote: m.sourceExcerpt || undefined,
    confidence: m.confidence ?? null,
    segmentId: m.segmentId,
    segmentTitle: m.segmentTitle,
    ...(m.interpretation ? { interpretation: m.interpretation } : {}),
  }
}

function mapCandidateRowToSignalRow(c: LegacyCandidateRow, m: CandidateIdeaFields): Omit<ExtractedSignal, 'id'> {
  const kindStr = String(c.kind ?? '').toLowerCase()
  const kind: ExtractedSignalKind =
    kindStr === 'risk' || kindStr === 'opportunity' || kindStr === 'blocker' || kindStr === 'attention'
      ? kindStr
      : 'attention'
  const interpretation = pickGraphInterpretationFromRow(c) ?? m.interpretation
  return {
    kind,
    label: m.title,
    detail: m.description && m.description !== m.title ? m.description : undefined,
    confidence: m.confidence ?? null,
    sourceExcerpt: m.sourceExcerpt ?? null,
    segmentId: m.segmentId,
    segmentTitle: m.segmentTitle,
    consolidationMeta: undefined,
    anchorRole: m.anchorRole ?? null,
    ...(interpretation ? { interpretation } : {}),
  }
}

/** Split external extractor candidates by proposedType (no ids). */
function routeFilteredCandidates(filtered: LegacyCandidateRow[]): {
  ideas: CandidateIdeaFields[]
  initiatives: Omit<ExtractedInitiative, 'id'>[]
  projects: Omit<ExtractedProject, 'id'>[]
  tasks: Omit<ExtractedTask, 'id'>[]
  insights: Omit<ExtractedInsight, 'id'>[]
  signals: Omit<ExtractedSignal, 'id'>[]
} {
  const ideas: CandidateIdeaFields[] = []
  const initiatives: Omit<ExtractedInitiative, 'id'>[] = []
  const projects: Omit<ExtractedProject, 'id'>[] = []
  const tasks: Omit<ExtractedTask, 'id'>[] = []
  const insights: Omit<ExtractedInsight, 'id'>[] = []
  const signals: Omit<ExtractedSignal, 'id'>[] = []
  for (const c of filtered) {
    const m = mapCandidateRowToIdea(c)
    const pt = normalizeProposedType(c)
    switch (pt) {
      case 'signal':
        signals.push(mapCandidateRowToSignalRow(c, m))
        break
      case 'observation':
      case 'decision':
      case 'research':
        insights.push(mapCandidateRowToInsight(m))
        break
      case 'initiative':
        initiatives.push(mapCandidateRowToInitiative(m))
        break
      case 'project':
        projects.push(mapCandidateRowToProject(m))
        break
      case 'task':
        tasks.push(mapCandidateRowToTaskRow(m))
        break
      default:
        ideas.push(m)
        break
    }
  }
  return { ideas, initiatives, projects, tasks, insights, signals }
}

function normProjectLoose(it: unknown): NonNullable<LegacyExtractMeetingResponse['projects']>[number] {
  const o = it as Record<string, unknown>
  const interpretation = pickGraphInterpretationFromRow(o)
  return {
    title: typeof o.title === 'string' ? o.title : undefined,
    initiativeTitle: typeof o.initiativeTitle === 'string' ? o.initiativeTitle : undefined,
    brief: typeof o.brief === 'string' ? o.brief : undefined,
    status: typeof o.status === 'string' ? o.status : undefined,
    confidence: (o.confidence ?? null) as ExtractedIdea['confidence'] | null,
    sourceExcerpt:
      typeof o.sourceExcerpt === 'string' || o.sourceExcerpt === null
        ? (o.sourceExcerpt as string | null)
        : null,
    segmentId: typeof o.segmentId === 'string' || o.segmentId === null ? (o.segmentId as string | null) : null,
    segmentTitle:
      typeof o.segmentTitle === 'string' || o.segmentTitle === null ? (o.segmentTitle as string | null) : null,
    ...(interpretation ? { interpretation } : {}),
  }
}

function normAssetLoose(it: unknown): NonNullable<LegacyExtractMeetingResponse['assets']>[number] {
  const o = it as Record<string, unknown>
  const interpretation = pickGraphInterpretationFromRow(o)
  return {
    name: String(o.name ?? o.title ?? o.label ?? 'Unnamed'),
    kind: typeof o.kind === 'string' ? o.kind : undefined,
    description: typeof o.description === 'string' ? o.description : undefined,
    confidence: (o.confidence ?? null) as ExtractedIdea['confidence'] | null,
    sourceExcerpt:
      typeof o.sourceExcerpt === 'string' || o.sourceExcerpt === null
        ? (o.sourceExcerpt as string | null)
        : null,
    segmentId: typeof o.segmentId === 'string' || o.segmentId === null ? (o.segmentId as string | null) : null,
    segmentTitle:
      typeof o.segmentTitle === 'string' || o.segmentTitle === null ? (o.segmentTitle as string | null) : null,
    ...(interpretation ? { interpretation } : {}),
  }
}

function normPeopleLoose(it: unknown): NonNullable<LegacyExtractMeetingResponse['peopleReferences']>[number] {
  const o = it as Record<string, unknown>
  const interpretation = pickGraphInterpretationFromRow(o)
  return {
    name: String(o.name ?? 'Unnamed'),
    role: typeof o.role === 'string' ? o.role : undefined,
    context: typeof o.context === 'string' ? o.context : undefined,
    confidence: (o.confidence ?? null) as ExtractedIdea['confidence'] | null,
    sourceExcerpt:
      typeof o.sourceExcerpt === 'string' || o.sourceExcerpt === null
        ? (o.sourceExcerpt as string | null)
        : null,
    segmentId: typeof o.segmentId === 'string' || o.segmentId === null ? (o.segmentId as string | null) : null,
    segmentTitle:
      typeof o.segmentTitle === 'string' || o.segmentTitle === null ? (o.segmentTitle as string | null) : null,
    ...(interpretation ? { interpretation } : {}),
  }
}

function normSignalLoose(it: unknown): NonNullable<LegacyExtractMeetingResponse['signals']>[number] {
  const o = it as Record<string, unknown>
  const interpretation = pickGraphInterpretationFromRow(o)
  return {
    kind: String(o.kind ?? o.label ?? 'attention'),
    label: typeof o.label === 'string' ? o.label : undefined,
    detail: typeof o.detail === 'string' ? o.detail : undefined,
    confidence: (o.confidence ?? null) as ExtractedIdea['confidence'] | null,
    sourceExcerpt:
      typeof o.sourceExcerpt === 'string' || o.sourceExcerpt === null
        ? (o.sourceExcerpt as string | null)
        : null,
    segmentId: typeof o.segmentId === 'string' || o.segmentId === null ? (o.segmentId as string | null) : null,
    segmentTitle:
      typeof o.segmentTitle === 'string' || o.segmentTitle === null ? (o.segmentTitle as string | null) : null,
    ...(interpretation ? { interpretation } : {}),
  }
}

/**
 * Coerce typed API responses (loose `Record` rows) into the stricter legacy shape used by merge/parse.
 */
export function toLegacyExtractMeetingResponse(
  raw: LegacyExtractMeetingResponse | ExtractMeetingResponse,
): LegacyExtractMeetingResponse {
  const r = raw as LegacyExtractMeetingResponse & ExtractMeetingResponse
  return {
    ideas: r.ideas,
    initiatives: r.initiatives,
    tasks: r.tasks,
    summary: r.summary,
    insights: r.insights,
    projects: r.projects?.map((p) => normProjectLoose(p)),
    assets: r.assets?.map((a) => normAssetLoose(a)),
    peopleReferences: r.peopleReferences?.map((p) => normPeopleLoose(p)),
    people: r.people,
    signals: r.signals?.map((s) => normSignalLoose(s)),
    candidates: r.candidates,
    error: r.error,
  }
}

function mapCandidateRowToIdea(c: LegacyCandidateRow): CandidateIdeaFields {
  const title = (c.text ?? '').trim()
  const paraphrase = typeof c.summary === 'string' ? c.summary.trim() : ''
  const excerptRaw = typeof c.sourceExcerpt === 'string' ? c.sourceExcerpt.trim() : ''
  const excerpt = excerptRaw || title
  const body = paraphrase || title
  const ar =
    typeof (c as { anchorRole?: string | null }).anchorRole === 'string'
      ? (c as { anchorRole?: string | null }).anchorRole!.trim() || undefined
      : undefined
  const proposedType = normalizeProposedType(c)
  const interpretation = pickGraphInterpretationFromRow(c)
  return {
    title,
    description: body,
    summary: paraphrase || title,
    status: 'Captured' as const,
    confidence:
      c.confidenceLabel === 'high' || c.confidenceLabel === 'medium' || c.confidenceLabel === 'low'
        ? c.confidenceLabel
        : null,
    sourceExcerpt: excerpt,
    segmentId: c.segmentId ?? undefined,
    segmentTitle: c.segmentTitle ?? undefined,
    sourceStage: typeof c.sourceStage === 'string' ? c.sourceStage : undefined,
    candidateKind: typeof c.kind === 'string' && c.kind !== 'candidate' ? c.kind : undefined,
    anchorRole: ar ?? undefined,
    ...(proposedType ? { proposedType } : {}),
    ...(interpretation ? { interpretation } : {}),
  }
}

/** Normalize legacy response into MeetingExtraction with stable temp ids. */
export function parseLegacyExtractResponse(
  raw: LegacyExtractMeetingResponse | ExtractMeetingResponse,
): MeetingExtraction {
  const response = toLegacyExtractMeetingResponse(raw)
  const seg = (it: { segmentId?: string | null; segmentTitle?: string | null }) => ({
    segmentId: it.segmentId ?? undefined,
    segmentTitle: it.segmentTitle ?? undefined,
  })
  const filteredCandidates = (response.candidates ?? []).filter((c) => (c.text ?? '').trim())
  const routed = routeFilteredCandidates(filteredCandidates)
  const hasCandidateRows = filteredCandidates.length > 0

  const legacyIdeas = (response.ideas ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return {
      id: nanoid(),
      title: it.title ?? '',
      description: it.description,
      summary: it.summary,
      status: it.status,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      ...seg(it),
      ...(interpretation ? { interpretation } : {}),
    }
  })
  const ideas = hasCandidateRows
    ? [...legacyIdeas, ...routed.ideas.map((it) => ({ id: nanoid(), ...it }))]
    : legacyIdeas
  const initiativesBase = (response.initiatives ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return {
      id: nanoid(),
      title: it.title ?? '',
      brief: it.brief,
      description: it.brief,
      status: it.status,
      ownerName: it.ownerName ?? null,
      notes: it.notes,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      existingInitiativeMatchId: (it as { existingInitiativeMatchId?: string | null }).existingInitiativeMatchId ?? null,
      matchConfidence: (it as { matchConfidence?: number | null }).matchConfidence ?? null,
      ...seg(it),
      ...(interpretation ? { interpretation } : {}),
    }
  })
  const initiatives = hasCandidateRows
    ? [...initiativesBase, ...routed.initiatives.map((it) => ({ id: nanoid(), ...it }))]
    : initiativesBase
  const tasksBase = (response.tasks ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return {
      id: nanoid(),
      title: it.title ?? '',
      description: it.description,
      status: it.status,
      suggestedOwner: it.assigneeName ?? null,
      assigneeName: it.assigneeName ?? null,
      notes: it.notes,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      existingProjectMatchId: (it as { existingProjectMatchId?: string | null }).existingProjectMatchId ?? null,
      existingTaskMatchId: (it as { existingTaskMatchId?: string | null }).existingTaskMatchId ?? null,
      existingPersonMatchId: (it as { existingPersonMatchId?: string | null }).existingPersonMatchId ?? null,
      matchConfidence: (it as { matchConfidence?: number | null }).matchConfidence ?? null,
      ...seg(it),
      ...(interpretation ? { interpretation } : {}),
    }
  })
  const tasks = hasCandidateRows ? [...tasksBase, ...routed.tasks.map((it) => ({ id: nanoid(), ...it }))] : tasksBase
  const rawSummary = response.summary
  const summaryInterp = rawSummary ? pickGraphInterpretationFromRow(rawSummary) : undefined
  const summary =
    rawSummary && (rawSummary.text ?? '').trim()
      ? {
          id: nanoid(),
          text: rawSummary.text ?? '',
          confidence: rawSummary.confidence ?? null,
          ...(summaryInterp ? { interpretation: summaryInterp } : {}),
        }
      : null

  const insightsBase = (response.insights ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return {
      id: nanoid(),
      statement: it.statement ?? '',
      sourceQuote: it.sourceQuote,
      confidence: it.confidence ?? null,
      segmentId: it.segmentId ?? undefined,
      segmentTitle: it.segmentTitle ?? undefined,
      ...(interpretation ? { interpretation } : {}),
    }
  })
  const insights = hasCandidateRows
    ? [...insightsBase, ...routed.insights.map((it) => ({ id: nanoid(), ...it }))]
    : insightsBase

  const projectsBase = (response.projects ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return {
      id: nanoid(),
      title: it.title ?? '',
      initiativeTitle: it.initiativeTitle,
      brief: it.brief,
      status: it.status,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      segmentId: it.segmentId ?? undefined,
      segmentTitle: it.segmentTitle ?? undefined,
      ...(interpretation ? { interpretation } : {}),
    }
  })
  const projects = hasCandidateRows
    ? [...projectsBase, ...routed.projects.map((it) => ({ id: nanoid(), ...it }))]
    : projectsBase

  const rawPeople = response.peopleReferences ?? response.people ?? []
  const peopleReferences = rawPeople.map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return {
      id: nanoid(),
      name: it.name,
      role: it.role,
      context: it.context,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      segmentId: it.segmentId ?? undefined,
      segmentTitle: it.segmentTitle ?? undefined,
      ...(interpretation ? { interpretation } : {}),
    }
  })

  const assets = (response.assets ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return {
      id: nanoid(),
      name: it.name,
      kind: (it.kind as any) ?? 'other',
      description: it.description,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      segmentId: it.segmentId ?? undefined,
      segmentTitle: it.segmentTitle ?? undefined,
      ...(interpretation ? { interpretation } : {}),
    }
  })

  const signalsBase = (response.signals ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return {
      id: nanoid(),
      kind: (it.kind as any) ?? 'attention',
      label: it.label ?? (it.kind || ''),
      detail: it.detail,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      segmentId: it.segmentId ?? undefined,
      segmentTitle: it.segmentTitle ?? undefined,
      ...(interpretation ? { interpretation } : {}),
    }
  })
  const signals = hasCandidateRows
    ? [...signalsBase, ...routed.signals.map((it) => ({ id: nanoid(), ...it }))]
    : signalsBase

  return {
    summary,
    insights: dedupeIdenticalLabelExcerpt(insights, (i) => i.statement),
    ideas: dedupeIdenticalLabelExcerpt(ideas, (i) => i.title),
    initiatives: dedupeIdenticalLabelExcerpt(initiatives, (i) => i.title),
    projects: dedupeIdenticalLabelExcerpt(projects, (i) => i.title),
    tasks: dedupeIdenticalLabelExcerpt(tasks, (i) => i.title),
    assets: dedupeIdenticalLabelExcerpt(assets, (i) => i.name),
    peopleReferences: dedupeIdenticalLabelExcerpt(peopleReferences, (i) => i.name),
    signals: dedupeIdenticalLabelExcerpt(signals, (i) => i.label, (i) => i.kind),
    error: response.error,
  }
}

/** Ensure `action` / `payload` when loading stored or partial extractions (backward compatible). */
function coerceInterpretationFields<T extends { interpretation?: GraphInterpretation }>(item: T): T {
  const interp = item.interpretation
  if (!interp || typeof interp !== 'object') return item
  const next = pickGraphInterpretationFromRow({ interpretation: interp })
  if (!next) {
    return { ...item, interpretation: undefined }
  }
  return { ...item, interpretation: next }
}

/** Parse a full MeetingExtraction (e.g. from a future API). Ensures all arrays exist and items have ids. */
export function parseMeetingExtraction(raw: Partial<MeetingExtraction>): MeetingExtraction {
  const ensureId = <T extends { id?: string }>(item: T, index: number): T & { id: string } => ({
    ...item,
    id: item.id ?? nanoid(),
  })
  return {
    summary: raw.summary ? coerceInterpretationFields(ensureId(raw.summary, 0)) : null,
    insights: (raw.insights ?? []).map((it, i) => coerceInterpretationFields(ensureId(it, i))),
    ideas: (raw.ideas ?? []).map((it, i) => coerceInterpretationFields(ensureId(it, i))),
    initiatives: (raw.initiatives ?? []).map((it, i) => coerceInterpretationFields(ensureId(it, i))),
    projects: (raw.projects ?? []).map((it, i) => coerceInterpretationFields(ensureId(it, i))),
    tasks: (raw.tasks ?? []).map((it, i) => coerceInterpretationFields(ensureId(it, i))),
    assets: (raw.assets ?? []).map((it, i) => coerceInterpretationFields(ensureId(it, i))),
    peopleReferences: (raw.peopleReferences ?? []).map((it, i) => coerceInterpretationFields(ensureId(it, i))),
    signals: (raw.signals ?? []).map((it, i) => coerceInterpretationFields(ensureId(it, i))),
    error: raw.error,
  }
}

/** Attach segment metadata to a single response and parse to partial extraction (with ids). */
function parseSegmentResponse(
  response: LegacyExtractMeetingResponse,
  segment: TranscriptSegment
): {
  ideas: MeetingExtraction['ideas']
  initiatives: MeetingExtraction['initiatives']
  tasks: MeetingExtraction['tasks']
  projects: MeetingExtraction['projects']
  assets: MeetingExtraction['assets']
  peopleReferences: MeetingExtraction['peopleReferences']
  signals: MeetingExtraction['signals']
  insights: MeetingExtraction['insights']
  error?: string
} {
  const segId = segment.id
  const segTitle = segment.title ?? segment.id
  const addMeta = <T>(item: T): T & { id: string; segmentId: string; segmentTitle: string } => ({
    ...item,
    id: nanoid(),
    segmentId: segId,
    segmentTitle: segTitle,
  } as T & { id: string; segmentId: string; segmentTitle: string })
  const nc = (v: unknown): ExtractedConfidence | null =>
    v === 'high' || v === 'medium' || v === 'low' ? v : null

  const filteredCandidates = (response.candidates ?? []).filter((c) => (c.text ?? '').trim())
  const routed = routeFilteredCandidates(filteredCandidates)
  const hasCandidateRows = filteredCandidates.length > 0

  const legacyIdeas = (response.ideas ?? []).map((it) => addMeta({
    ...it,
    title: it.title ?? '',
    description: it.description,
    summary: it.summary,
    status: it.status,
    confidence: it.confidence ?? null,
    sourceExcerpt: it.sourceExcerpt ?? null,
  }))
  const ideas = hasCandidateRows
    ? [...legacyIdeas, ...routed.ideas.map((it) => addMeta(it))]
    : legacyIdeas

  const initiativesBase = (response.initiatives ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return addMeta({
      title: it.title ?? '',
      brief: it.brief,
      description: it.brief,
      status: it.status,
      ownerName: it.ownerName ?? null,
      notes: it.notes,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      existingInitiativeMatchId: (it as { existingInitiativeMatchId?: string | null }).existingInitiativeMatchId ?? null,
      matchConfidence: (it as { matchConfidence?: number | null }).matchConfidence ?? null,
      ...(interpretation ? { interpretation } : {}),
    })
  })
  const initiatives = hasCandidateRows
    ? [...initiativesBase, ...routed.initiatives.map((it) => addMeta(it))]
    : initiativesBase

  const tasksBase = (response.tasks ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return addMeta({
      title: it.title ?? '',
      description: it.description,
      status: it.status,
      suggestedOwner: it.assigneeName ?? null,
      assigneeName: it.assigneeName ?? null,
      notes: it.notes,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      existingProjectMatchId: (it as { existingProjectMatchId?: string | null }).existingProjectMatchId ?? null,
      existingTaskMatchId: (it as { existingTaskMatchId?: string | null }).existingTaskMatchId ?? null,
      existingPersonMatchId: (it as { existingPersonMatchId?: string | null }).existingPersonMatchId ?? null,
      matchConfidence: (it as { matchConfidence?: number | null }).matchConfidence ?? null,
      ...(interpretation ? { interpretation } : {}),
    })
  })
  const tasks = hasCandidateRows ? [...tasksBase, ...routed.tasks.map((it) => addMeta(it))] : tasksBase

  const projectsBase = (response.projects ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return addMeta({
      title: (it as { title?: string }).title ?? '',
      initiativeTitle: (it as { initiativeTitle?: string }).initiativeTitle,
      brief: (it as { brief?: string }).brief,
      status: (it as { status?: string }).status,
      confidence: ((it as { confidence?: unknown }).confidence ?? null) as ExtractedConfidence | null,
      sourceExcerpt: (it as { sourceExcerpt?: string | null }).sourceExcerpt ?? null,
      ...(interpretation ? { interpretation } : {}),
    })
  })
  const projects = hasCandidateRows
    ? [...projectsBase, ...routed.projects.map((it) => addMeta(it))]
    : projectsBase

  const rawPeople = response.peopleReferences ?? (response as { people?: typeof response.peopleReferences }).people ?? []
  const peopleReferences = rawPeople.map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return addMeta({
      name: it.name,
      role: it.role,
      context: it.context,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      ...(interpretation ? { interpretation } : {}),
    })
  })
  const assets = (response.assets ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return addMeta({
      name: it.name,
      kind: (it.kind as 'tool' | 'system' | 'document' | 'inventory' | 'other') ?? 'other',
      description: it.description,
      confidence: it.confidence ?? null,
      sourceExcerpt: it.sourceExcerpt ?? null,
      ...(interpretation ? { interpretation } : {}),
    })
  })

  const insightsBase = (response.insights ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return addMeta({
      statement: it.statement ?? '',
      sourceQuote: it.sourceQuote,
      confidence: nc(it.confidence),
      ...(interpretation ? { interpretation } : {}),
    })
  })
  const insights = hasCandidateRows
    ? [...insightsBase, ...routed.insights.map((it) => addMeta(it))]
    : insightsBase

  const signalsBase = (response.signals ?? []).map((it) => {
    const interpretation = pickGraphInterpretationFromRow(it)
    return addMeta({
      kind: (it.kind as 'attention' | 'risk' | 'opportunity' | 'blocker') ?? 'attention',
      label: it.label ?? (it.kind || ''),
      detail: it.detail,
      confidence: it.confidence ?? null,
      sourceExcerpt: (it as { sourceExcerpt?: string | null }).sourceExcerpt ?? null,
      ...(interpretation ? { interpretation } : {}),
    })
  })
  const signals = hasCandidateRows
    ? [...signalsBase, ...routed.signals.map((it) => addMeta(it))]
    : signalsBase

  return {
    ideas: dedupeIdenticalLabelExcerpt(ideas, (i) => i.title),
    initiatives: dedupeIdenticalLabelExcerpt(initiatives, (i) => i.title),
    tasks: dedupeIdenticalLabelExcerpt(tasks, (i) => i.title),
    projects: dedupeIdenticalLabelExcerpt(projects, (i) => i.title),
    assets: dedupeIdenticalLabelExcerpt(assets, (i) => i.name),
    peopleReferences: dedupeIdenticalLabelExcerpt(peopleReferences, (i) => i.name),
    signals: dedupeIdenticalLabelExcerpt(signals, (i) => i.label, (i) => String(i.kind)),
    insights: dedupeIdenticalLabelExcerpt(insights, (i) => i.statement),
    error: response.error,
  }
}

/**
 * Within a single chunk: drop only rows that are identical on normalized label + excerpt (cheap safety).
 */
function dedupeIdenticalLabelExcerpt<
  T extends { sourceExcerpt?: string | null; sourceQuote?: string | null },
>(
  items: T[],
  labelOf: (t: T) => string,
  extraKey?: (t: T) => string,
): T[] {
  const seen = new Set<string>()
  return items.filter((it) => {
    const label = normalizeCandidateText(labelOf(it))
    const ex = normalizeCandidateText(String(it.sourceExcerpt ?? it.sourceQuote ?? ''))
    const x = extraKey ? String(extraKey(it)) : ''
    const k = `${x}@@${label}@@${ex}`
    if (!label) return true
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

/**
 * Merge per-segment extraction responses into a single MeetingExtraction.
 * Concatenates segments, light identical-row dedupe per chunk, then deterministic cross-chunk consolidation.
 */
export function mergeSegmentExtractionResults(
  segmentResults: Array<{ segment: TranscriptSegment; response: LegacyExtractMeetingResponse | ExtractMeetingResponse }>
): MeetingExtraction {
  const allIdeas: MeetingExtraction['ideas'] = []
  const allInitiatives: MeetingExtraction['initiatives'] = []
  const allTasks: MeetingExtraction['tasks'] = []
  const allProjects: MeetingExtraction['projects'] = []
  const allAssets: MeetingExtraction['assets'] = []
  const allPeople: MeetingExtraction['peopleReferences'] = []
  const allSignals: MeetingExtraction['signals'] = []
  const allInsights: MeetingExtraction['insights'] = []
  let firstError: string | undefined
  for (const { segment, response: rawResponse } of segmentResults) {
    const response = toLegacyExtractMeetingResponse(rawResponse)
    if (response.error) firstError = response.error
    const parsed = parseSegmentResponse(response, segment)
    allIdeas.push(...parsed.ideas)
    allInitiatives.push(...parsed.initiatives)
    allTasks.push(...parsed.tasks)
    allProjects.push(...parsed.projects)
    allAssets.push(...parsed.assets)
    allPeople.push(...parsed.peopleReferences)
    allSignals.push(...parsed.signals)
    allInsights.push(...parsed.insights)
  }
  const merged: MeetingExtraction = {
    summary: null,
    insights: allInsights,
    ideas: allIdeas,
    initiatives: allInitiatives,
    projects: allProjects,
    tasks: allTasks,
    assets: allAssets,
    peopleReferences: allPeople,
    signals: allSignals,
    error: firstError,
  }
  return consolidateMeetingExtraction(merged)
}
