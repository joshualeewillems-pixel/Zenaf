/**
 * Vision Map stewardship → `water_level` (see `docs/02_ACTIVE_DESIGN/VISION_MAP_STEWARDSHIP_WATER.md`).
 *
 * High tier requires **owner/assignee signal** plus **execution shape** (timeframes, hours, seats as applicable).
 */
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import type { MapEntityRef, WaterLevel } from './ontology'
import { getLatestCouncilRunForRef } from './councilCorrelation'
import type { StudioCouncilRunRow } from './studioCouncilTypes'

const RECENT_UPDATE_DAYS = 14
const MEANINGFUL_UPDATE_HOURS = 48
const COUNCIL_PULSE_HOURS = 72

export type VitalInput = {
  ownerPresent: boolean
  entityUpdatedAt?: string | null
  /** True when timeframe / hours / seat assignments (per entity rules) are filled — see design doc. */
  executionShapeComplete?: boolean
}

function daysSinceIso(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return null
  return (Date.now() - t) / 86400000
}

function hoursSinceIso(iso: string | null | undefined): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return null
  return (Date.now() - t) / 3600000
}

/**
 * high — stewarded AND execution shape complete.
 * medium — stewarded OR shape complete OR touched within 14d.
 * low — otherwise.
 */
export function deriveWaterLevel(
  ownerPresent: boolean,
  updatedAt: string | null | undefined,
  executionShapeComplete = false,
): WaterLevel {
  const days = daysSinceIso(updatedAt)
  const recent = days !== null && days <= RECENT_UPDATE_DAYS
  if (ownerPresent && executionShapeComplete) return 'high'
  if (ownerPresent || executionShapeComplete || recent) return 'medium'
  return 'low'
}

export function waterLevelFromVital(v: VitalInput): WaterLevel {
  return deriveWaterLevel(v.ownerPresent, v.entityUpdatedAt ?? null, v.executionShapeComplete ?? false)
}

function initiativeExecutionShapeComplete(ini: Initiative): boolean {
  const timeframeOk = (ini.estimated_timeframe_ai ?? '').trim().length >= 3
  if (!timeframeOk) return false
  const seats = ini.seats ?? []
  if (seats.length === 0) return true
  return seats.every((s) => Boolean(s.assigned_person_id?.trim()))
}

function projectExecutionShapeComplete(proj: Project): boolean {
  const rangeOk = Boolean(proj.start_date?.trim()) && Boolean(proj.end_date?.trim())
  const hoursOk = proj.estimated_weekly_hours != null && proj.estimated_weekly_hours > 0
  return rangeOk && hoursOk
}

function taskExecutionShapeComplete(task: Task): boolean {
  const dueOk = Boolean(task.due_date?.trim())
  const hoursOk = task.estimated_hours != null && task.estimated_hours > 0
  return dueOk || hoursOk
}

function ideaExecutionShapeComplete(idea: Idea): boolean {
  const linked = (idea.linked_people?.length ?? 0) > 0
  const textLen = Math.max((idea.desired_outcome ?? '').trim().length, (idea.summary ?? '').trim().length)
  return linked && textLen >= 20
}

/** Pulse when entity touched in last 48h or a matching council run in last 72h. */
export function deriveFertilizerPulse(
  ref: MapEntityRef,
  entityUpdatedAt: string | null | undefined,
  councilRuns: StudioCouncilRunRow[],
): boolean {
  const uh = hoursSinceIso(entityUpdatedAt)
  if (uh !== null && uh <= MEANINGFUL_UPDATE_HOURS) return true
  const run = getLatestCouncilRunForRef(councilRuns, ref)
  if (!run?.created_at) return false
  const rh = hoursSinceIso(run.created_at)
  return rh !== null && rh <= COUNCIL_PULSE_HOURS
}

export type EdgeWaterTone = 'bright' | 'normal' | 'dry'

export function edgeWaterTone(a?: WaterLevel, b?: WaterLevel): EdgeWaterTone {
  const score = (w?: WaterLevel) => (w === 'high' ? 2 : w === 'medium' ? 1 : 0)
  const s = score(a) + score(b)
  if (s >= 3) return 'bright'
  if (s <= 0) return 'dry'
  return 'normal'
}

export function vitalForIdea(idea: Idea): VitalInput {
  const ownerPresent = (idea.linked_people?.length ?? 0) > 0
  return {
    ownerPresent,
    entityUpdatedAt: idea.updated_at ?? null,
    executionShapeComplete: ideaExecutionShapeComplete(idea),
  }
}

export function vitalForInitiative(ini: Initiative): VitalInput {
  const seatsFilled = (ini.seats ?? []).some((s) => Boolean(s.assigned_person_id?.trim()))
  const ownerPresent = Boolean(ini.owner_id?.trim()) || seatsFilled
  return {
    ownerPresent,
    entityUpdatedAt: ini.updated_at ?? null,
    executionShapeComplete: initiativeExecutionShapeComplete(ini),
  }
}

export function vitalForProject(proj: Project): VitalInput {
  const ownerPresent = Boolean(proj.owner_id?.trim()) || (proj.supporting_owner_ids?.length ?? 0) > 0
  return {
    ownerPresent,
    entityUpdatedAt: proj.updated_at ?? null,
    executionShapeComplete: projectExecutionShapeComplete(proj),
  }
}

export function vitalForTask(task: Task): VitalInput {
  return {
    ownerPresent: Boolean(task.assignee_id?.trim()),
    entityUpdatedAt: task.updated_at ?? null,
    executionShapeComplete: taskExecutionShapeComplete(task),
  }
}

export function vitalBare(updatedAt?: string | null): VitalInput {
  return { ownerPresent: false, entityUpdatedAt: updatedAt ?? null, executionShapeComplete: false }
}
