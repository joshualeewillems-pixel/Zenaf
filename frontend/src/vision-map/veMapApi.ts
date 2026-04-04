import { VISION_EXECUTION_API } from '../vision-execution/types'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'

function formatFetchFailure(res: Response, bodyText: string): string {
  if (res.status === 401 || res.status === 403) {
    return 'Your session expired or you are not signed in. Open Home and sign in again, then tap Refresh data on the Vision map.'
  }
  const raw = (bodyText || '').trim()
  if (raw.startsWith('{')) {
    try {
      const j = JSON.parse(raw) as { detail?: unknown }
      if (typeof j.detail === 'string' && j.detail.trim()) return j.detail.trim()
      if (Array.isArray(j.detail)) {
        const parts = j.detail.map((x) =>
          typeof x === 'object' && x != null && 'msg' in x ? String((x as { msg: string }).msg) : String(x),
        )
        if (parts.length) return parts.join('; ')
      }
    } catch {
      /* fall through */
    }
  }
  return raw || `Request failed (${res.status})`
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(formatFetchFailure(res, t))
  }
  return res.json() as Promise<T>
}

function asArray<T>(x: unknown): T[] {
  return Array.isArray(x) ? (x as T[]) : []
}

/** Live Vision Execution lists (same routes as VisionExecutionView). */
export async function fetchVisionMapEntities(): Promise<{
  ideas: Idea[]
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
}> {
  const [ideasRes, iniRes, projRes, taskRes] = await Promise.all([
    fetch(`${VISION_EXECUTION_API}/ideas`, { credentials: 'include' }),
    fetch(`${VISION_EXECUTION_API}/initiatives`, { credentials: 'include' }),
    fetch(`${VISION_EXECUTION_API}/projects`, { credentials: 'include' }),
    fetch(`${VISION_EXECUTION_API}/tasks`, { credentials: 'include' }),
  ])
  const [ideas, initiatives, projects, tasks] = await Promise.all([
    readJson<unknown>(ideasRes),
    readJson<unknown>(iniRes),
    readJson<unknown>(projRes),
    readJson<unknown>(taskRes),
  ])
  return {
    ideas: asArray<Idea>(ideas),
    initiatives: asArray<Initiative>(initiatives),
    projects: asArray<Project>(projects),
    tasks: asArray<Task>(tasks),
  }
}

/** Keyed `${entity_type}:${entity_id}` for buildLiveVisionMapGraph; failures should be caught by caller. */
export type ServerNodeVitalityMap = Record<string, { water: number; soil: number; fruit: number }>

type NodeVitalityRow = {
  entity_type?: unknown
  entity_id?: unknown
  water?: unknown
  soil?: unknown
  fruit?: unknown
}

export async function fetchNodeVitalityMap(): Promise<ServerNodeVitalityMap> {
  const res = await fetch(`${VISION_EXECUTION_API}/node-vitality`, { credentials: 'include' })
  const j = (await readJson<{ vitality?: unknown }>(res)) as { vitality?: unknown }
  const rows = Array.isArray(j.vitality) ? (j.vitality as NodeVitalityRow[]) : []
  const out: ServerNodeVitalityMap = {}
  for (const r of rows) {
    if (!r || typeof r !== 'object') continue
    const et = String(r.entity_type ?? '').trim()
    const eid = String(r.entity_id ?? '').trim()
    if (!et || !eid) continue
    const water = Number(r.water)
    const soil = Number(r.soil)
    const fruit = Number(r.fruit)
    if (![water, soil, fruit].every((n) => Number.isFinite(n))) continue
    out[`${et}:${eid}`] = { water, soil, fruit }
  }
  return out
}
