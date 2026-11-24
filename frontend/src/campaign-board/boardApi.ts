/**
 * Campaign Board — Vision Execution reads/writes.
 *
 * Reads reuse the Vision Map's entity fetch (same routes as
 * VisionExecutionView). Writes go ONLY through the existing VE
 * PATCH endpoints: a task's due_date, a project's start/end date.
 * No route storage, no new endpoints, no new records.
 */
import { VISION_EXECUTION_API, type Project, type Task } from '../vision-execution/types'
import { fetchVisionMapEntities } from '../vision-map/veMapApi'

export interface BoardEntities {
  initiatives: { id: string; title: string }[]
  projects: Project[]
  tasks: Task[]
}

export async function fetchBoardEntities(): Promise<BoardEntities> {
  const all = await fetchVisionMapEntities()
  return {
    initiatives: all.initiatives.map((i) => ({ id: i.id, title: i.title })),
    projects: all.projects,
    tasks: all.tasks,
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

/** Set the project's recorded start or finish date (FINISH may be dated
 *  first, so the rest of the timeline has context). */
export function patchProjectDates(
  projectId: string,
  patch: { start_date?: string; end_date?: string },
): Promise<Project> {
  return apiPatch<Project>(`/projects/${projectId}`, patch)
}
