/**
 * Unified Vision Map condition → single severity 0–3 (cracked-stone visuals).
 * Collapses stale, blocked, council signals, and VE field completeness into one scale.
 */
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { ConditionSeverity, MapEntityRef, MapNodePayload } from './ontology'

function daysSinceUpdated(iso: string | null | undefined): number {
  if (!iso) return 999
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return 999
  return (Date.now() - t) / 86400000
}

function getEntity(
  bundle: VisionMapEntityBundle | null,
  ref: MapEntityRef,
): Idea | Initiative | Project | Task | null {
  if (!bundle) return null
  switch (ref.veType) {
    case 'idea':
      return bundle.ideas.find((x) => x.id === ref.id) ?? null
    case 'initiative':
      return bundle.initiatives.find((x) => x.id === ref.id) ?? null
    case 'project':
      return bundle.projects.find((x) => x.id === ref.id) ?? null
    case 'task':
      return bundle.tasks.find((x) => x.id === ref.id) ?? null
    default:
      return null
  }
}

function scoreToSeverity(score: number): ConditionSeverity {
  if (score >= 68) return 3
  if (score >= 38) return 2
  if (score >= 14) return 1
  return 0
}

/**
 * Map merged `condition` + entity row + bundle context → 0 none, 1 light, 2 fractured, 3 critical.
 */
export function resolveConditionSeverity(
  payload: MapNodePayload,
  bundle: VisionMapEntityBundle | null,
): ConditionSeverity {
  const c = payload.condition
  if (c === 'teacher-vetoed' || payload.councilTeacher?.teacher_vetoed) return 3

  const ref = payload.ref
  const ent = getEntity(bundle, ref)
  /** Missing row: do not treat as infinitely stale (partial payloads / race). */
  const days = ent ? daysSinceUpdated(ent.updated_at) : 0

  let score = 0
  let floor: ConditionSeverity = 0

  if (c === 'blocked') floor = 2
  if (c === 'teacher-warned' || payload.councilTeacher?.teacher_warning) score += 28
  if (c === 'stale') score += 14

  if (days > 52) score += 40
  else if (days > 38) score += 30
  else if (days > 26) score += 20
  else if (days > 17) score += 11
  else if (days > 9) score += 5

  if (ref.veType === 'initiative' && ent) {
    const ini = ent as Initiative
    const kill = (ini.kill_criteria || '').trim()
    if (kill.length >= 14) return 3
    const risks = (ini.risks || '').trim()
    if (risks.length >= 72) score += 22
    else if (risks.length >= 28) score += 12
    if ((ini.dependencies || '').trim().length >= 36) score += 10
    if (!(ini.next_step_ai || '').trim()) score += 12
    if (ini.evaluation_priority == null && (ini.brief || '').trim().length > 24) score += 10
  } else if (ref.veType === 'project' && ent) {
    const p = ent as Project
    if (!(p.next_step_ai || '').trim() && !/\b(done|shipped|complete|closed)\b/i.test(p.status || '')) score += 10
    const blockedKids =
      bundle?.tasks.filter((t) => t.project_id === p.id && /\bblock/i.test(t.status || '')).length ?? 0
    if (blockedKids > 0) floor = 2
  } else if (ref.veType === 'task' && ent) {
    const t = ent as Task
    const cc = (t.completion_criteria || '').trim()
    if (!cc || cc.length < 14) score += 20
    if ((t.description || '').trim().length < 20) score += 8
  } else if (ref.veType === 'idea' && ent) {
    const i = ent as Idea
    if (!(i.desired_outcome || '').trim() && /evaluat|draft/i.test((i.status || '').toLowerCase())) score += 14
  }

  const fromScore = scoreToSeverity(score)
  const merged = Math.max(floor, fromScore)
  return (merged > 3 ? 3 : merged) as ConditionSeverity
}

/** When `condition_severity` was not stored (legacy layout / partial payloads). */
export function conditionSeverityFallback(payload: MapNodePayload): ConditionSeverity {
  switch (payload.condition) {
    case 'teacher-vetoed':
      return 3
    case 'blocked':
      return 2
    case 'teacher-warned':
      return 2
    case 'stale':
      return 1
    default:
      return 0
  }
}

/** Single source for map chrome + layout weighting: prefer stored severity, else legacy `condition` mapping. */
export function effectiveConditionSeverity(payload: MapNodePayload): ConditionSeverity {
  return payload.condition_severity ?? conditionSeverityFallback(payload)
}
