/**
 * Routes short “bounded transform” council messages to POST /vision-execution/suggest-node-transform
 * instead of the streamed council (/run/stream) path.
 */

import { readPrivacyMode } from '../ai-actions'
import type { CouncilIdeaLabelsSnapshot, VESelection } from '../vision-execution'
import { councilAnchorRef } from './mapCouncilActions'
import type { MapNodePayload } from './ontology'

export type BoundedTransformIntent = 'idea_to_task' | 'idea_to_project' | 'project_to_tasks' | 'make_more_concrete'

/** Bounded snapshot for workspace AI trace (no raw user question text). */
export function buildBoundedNodeTransformInputSnapshot(params: {
  questionCharLen: number
  anchorEntityType: string | null
  transformIntent: string
}): string {
  const lines = [
    'POST /vision-execution/suggest-node-transform',
    `question_char_len:${params.questionCharLen}`,
    `anchor_entity_type:${params.anchorEntityType ?? 'none'}`,
    `transform_intent:${params.transformIntent}`,
  ]
  const s = lines.join('\n')
  return s.length > 8000 ? s.slice(0, 8000) : s
}

export type NodeTransformResponse = {
  intent?: string
  suggested_action?: string
  proposed_node?: { type: string; title: string; summary: string }
  reason?: string
  confidence?: number
  error?: string
  message?: string
  execution_blocked?: boolean
  model_used?: string
  provider_used?: string
  client_correlation_id?: string
  _fallback?: boolean
}

export function resolveCouncilAnchorEntityType(
  veSelection: VESelection | null,
  mapPayload: MapNodePayload | null,
): 'idea' | 'initiative' | 'project' | 'task' | null {
  if (mapPayload) {
    const a = councilAnchorRef(mapPayload)
    if (a.veType === 'outcome') return null
    return a.veType
  }
  if (!veSelection) return null
  if (veSelection.ideaId) return 'idea'
  if (veSelection.initiativeId) return 'initiative'
  if (veSelection.projectId) return 'project'
  if (veSelection.taskId) return 'task'
  return null
}

export function inferBoundedTransformIntent(
  question: string,
  sourceType: 'idea' | 'initiative' | 'project' | 'task' | null,
): BoundedTransformIntent | null {
  const t = question.trim().toLowerCase()
  if (t.length < 8 || t.length > 800) return null

  if (
    /\b(break|split|divide)\b[\s\S]{0,48}\binto\b[\s\S]{0,12}\btasks?\b/.test(t) ||
    /\bbreak\b[\s\S]{0,20}\binto\b[\s\S]{0,12}\btasks?\b/.test(t)
  ) {
    if (sourceType === 'project') return 'project_to_tasks'
    if (sourceType === 'idea' || sourceType === 'initiative') return 'idea_to_task'
    return null
  }

  if (
    /\bturn\b[\s\S]{0,40}\binto\b[\s\S]{0,16}\bprojects?\b/.test(t) ||
    /\bmake\b[\s\S]{0,24}\b(a\s+)?projects?\b/.test(t) ||
    /\bconvert\b[\s\S]{0,40}\bto\b[\s\S]{0,16}\bprojects?\b/.test(t)
  ) {
    return 'idea_to_project'
  }

  if (
    /\bmore\s+concrete\b/.test(t) ||
    /\bbe\s+more\s+specific\b/.test(t) ||
    /\bsharpen\b/.test(t) ||
    /\bnarrow\s+down\b/.test(t) ||
    /\bmake\b[\s\S]{0,20}\b(specific|concrete)\b/.test(t)
  ) {
    return 'make_more_concrete'
  }

  if (
    /\bturn\b[\s\S]{0,40}\binto\b[\s\S]{0,16}\btasks?\b/.test(t) ||
    /\bmake\b[\s\S]{0,24}\b(a\s+)?tasks?\b/.test(t) ||
    /\bconvert\b[\s\S]{0,40}\bto\b[\s\S]{0,16}\btasks?\b/.test(t)
  ) {
    return 'idea_to_task'
  }

  return null
}

export function intentAllowedForSourceType(
  intent: BoundedTransformIntent,
  sourceType: 'idea' | 'initiative' | 'project' | 'task' | null,
): boolean {
  if (!sourceType) return false
  switch (intent) {
    case 'idea_to_task':
      return sourceType === 'idea' || sourceType === 'initiative' || sourceType === 'project'
    case 'idea_to_project':
      return sourceType === 'idea' || sourceType === 'initiative'
    case 'project_to_tasks':
      return sourceType === 'project' || sourceType === 'initiative'
    case 'make_more_concrete':
      return true
    default:
      return false
  }
}

export function buildNodeTransformApiBody(
  intent: BoundedTransformIntent,
  userMessage: string,
  opts: {
    veSelection: VESelection | null
    mapPayload: MapNodePayload | null
    ideaLabels: CouncilIdeaLabelsSnapshot | null
    profileId?: string | null
  },
): Record<string, unknown> | null {
  const { veSelection, mapPayload, ideaLabels, profileId } = opts

  if (mapPayload) {
    const anchor = councilAnchorRef(mapPayload)
    if (anchor.veType === 'outcome') return null
    const body: Record<string, unknown> = {
      intent,
      nodeId: anchor.id,
      nodeType: anchor.veType,
      title: mapPayload.label,
      summary: mapPayload.summaryLines.filter(Boolean).join('\n'),
      userMessage,
    }
    if (profileId?.trim()) body.profileId = profileId.trim()
    return body
  }

  if (!veSelection) return null
  if (veSelection.ideaId) {
    const body: Record<string, unknown> = {
      intent,
      nodeId: veSelection.ideaId,
      nodeType: 'idea',
      userMessage,
    }
    if (ideaLabels?.entity_id === veSelection.ideaId) {
      if (ideaLabels.ve_focus_title?.trim()) body.title = ideaLabels.ve_focus_title
      if (ideaLabels.ve_focus_brief?.trim()) body.summary = ideaLabels.ve_focus_brief
    }
    if (profileId?.trim()) body.profileId = profileId.trim()
    return body
  }
  if (veSelection.initiativeId) {
    const body: Record<string, unknown> = {
      intent,
      nodeId: veSelection.initiativeId,
      nodeType: 'initiative',
      userMessage,
    }
    if (profileId?.trim()) body.profileId = profileId.trim()
    return body
  }
  if (veSelection.projectId) {
    const body: Record<string, unknown> = {
      intent,
      nodeId: veSelection.projectId,
      nodeType: 'project',
      userMessage,
    }
    if (profileId?.trim()) body.profileId = profileId.trim()
    return body
  }
  if (veSelection.taskId) {
    const body: Record<string, unknown> = {
      intent,
      nodeId: veSelection.taskId,
      nodeType: 'task',
      userMessage,
    }
    if (profileId?.trim()) body.profileId = profileId.trim()
    return body
  }
  return null
}

export function buildNodeTransformRoutingContext(): Record<string, unknown> {
  return {
    surface: 'vision_execution',
    action_kind: 'structured_evaluation',
    action_intent: 'node_transform_suggest',
    streaming: false,
    privacy_mode: readPrivacyMode(),
  }
}

export function formatNodeTransformAgentContent(res: NodeTransformResponse): string {
  if (res.execution_blocked) {
    return `**Transform blocked**\n\n${res.message || res.error || 'Execution blocked by policy.'}`
  }
  if (res.error && !res.proposed_node?.title) {
    return `**Transform failed**\n\n${res.message || res.error}`
  }
  const pn = res.proposed_node
  const lines = [
    `**Suggested transform** (${res.intent ?? '—'})`,
    '',
    `**Action:** ${res.suggested_action ?? '—'}`,
    `**Proposed ${pn?.type ?? 'node'}:** ${pn?.title?.trim() || '—'}`,
  ]
  if (pn?.summary?.trim()) {
    lines.push('', pn.summary.trim())
  }
  lines.push('', `**Why:** ${(res.reason ?? '').trim() || '—'}`)
  if (res.confidence != null && Number.isFinite(res.confidence)) {
    lines.push('', `_Confidence ~${Math.round(res.confidence * 100)}%${res._fallback ? ' (fallback)' : ''}_`)
  }
  lines.push(
    '',
    '_This is a draft. Create or edit the entity in Vision Execution when you are ready._',
  )
  return lines.join('\n')
}
