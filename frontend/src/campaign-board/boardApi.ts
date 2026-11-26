/**
 * Campaign Board — Vision Execution reads/writes.
 *
 * Reads reuse the Vision Map's entity fetch (same routes as
 * VisionExecutionView), plus the routes the VE workspace itself
 * reads for circumstance material: GET /signals (the Layer-1
 * circumstance entity, open rows only — the Radar's own filter) and
 * GET /capacity-profiles (weekly capacity; committed hours are
 * derived in boardLogic by the Radar's rule). Writes go ONLY
 * through the existing VE PATCH endpoints: a task's due_date. No
 * route storage, no new endpoints, no new records. River/Hold
 * declarations are READ here, never written: they are recorded as
 * VE decisions in conversation with Valen (Board interaction pass,
 * 2026-11-25) and folded from the owner's decision records by
 * boardLogic.deriveDeclarations.
 */
import {
  VISION_EXECUTION_API,
  type CapacityProfile,
  type Person,
  type Project,
  type Task,
} from '../vision-execution/types'
import { fetchVisionMapEntities } from '../vision-map/veMapApi'
import type { BoardDecisionRow, BoardSignal } from './boardLogic'

export interface BoardEntities {
  initiatives: { id: string; title: string }[]
  projects: Project[]
  tasks: Task[]
  persons: Person[]
  signals: BoardSignal[]
  capacityProfiles: CapacityProfile[]
  /** The owner's decision records for projects — the declaration
   *  fold's input (Rivers and Holds ride among them). */
  decisions: BoardDecisionRow[]
}

/** Circumstance reads degrade to empty rather than failing the board:
 *  the signals route answers 503 when signals are disabled, and its
 *  own semantics then are an empty bucket — never another pool. */
async function fetchArrayOrEmpty<T>(path: string): Promise<T[]> {
  try {
    const res = await fetch(`${VISION_EXECUTION_API}${path}`, { credentials: 'include' })
    if (!res.ok) return []
    const data: unknown = await res.json()
    return Array.isArray(data) ? (data as T[]) : []
  } catch {
    return []
  }
}

export async function fetchBoardEntities(): Promise<BoardEntities> {
  const [all, signals, capacityProfiles, decisions] = await Promise.all([
    fetchVisionMapEntities(),
    fetchArrayOrEmpty<BoardSignal>('/signals?status_not=resolved,dismissed'),
    fetchArrayOrEmpty<CapacityProfile>('/capacity-profiles'),
    fetchArrayOrEmpty<BoardDecisionRow>('/decisions?entity_type=project&limit=500'),
  ])
  return {
    initiatives: all.initiatives.map((i) => ({ id: i.id, title: i.title })),
    projects: all.projects,
    tasks: all.tasks,
    persons: all.persons,
    signals,
    capacityProfiles,
    decisions,
  }
}

async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${VISION_EXECUTION_API}${path}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text.trim() || `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

/** Set a task's due date — the one write a dragged/clicked waypoint makes. */
export function patchTaskDueDate(taskId: string, dueDateLocal: string): Promise<Task> {
  return apiPatch<Task>(`/tasks/${taskId}`, { due_date: dueDateLocal })
}

