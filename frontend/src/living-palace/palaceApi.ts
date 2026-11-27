/**
 * The Living Palace — reads.
 *
 * The Palace renders the visitor's real body of work or it does not
 * ship: every read goes through an endpoint that already exists.
 * The world itself reads the Vision Map's entity fetch (the same
 * routes the Board and the Bench read) plus the capacity profiles
 * and core profiles the VE workspace already serves.
 *
 * Reads (Palace pass, chat-is-the-work). The verdict-door callers
 * and the weighing settle writes that lived here (#432/#433) are
 * superseded as forms — rulings and weighings happen in Maeve's
 * conversation now, through the chat's own carriage. There is NO
 * per-subject boundary store and this module invents none.
 *
 * One write stands, added with the overhead plan (2026-11-27):
 * the per-project layout record (fetchPalaceLayout /
 * savePalaceLayout below) — derived geometry, persisted only
 * when a layout is computed or changes, in the chalk store's
 * owner-scoped pattern. It carries no visitor work and no words.
 */
import { apiBase } from '../apiBase'
import {
  VISION_EXECUTION_API,
  type CapacityProfile,
  type CoreProfile,
} from '../vision-execution/types'
import { fetchVisionMapEntities } from '../vision-map/veMapApi'
import type { AttributedRead, PalaceData } from './palaceLogic'
import type { PalaceLayoutRecord } from './palaceOverheadLogic'
import type { SubjectInteraction } from './palaceSceneLogic'

export interface PalaceEntities extends PalaceData {
  /** The canonical core profile (its declared non-negotiables are
   *  boundary material the Palace may hold), or null when none. */
  coreProfile: CoreProfile | null
}

/** Circumstance reads degrade to empty rather than failing the
 *  world (the boardApi idiom). */
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

export async function fetchPalaceEntities(): Promise<PalaceEntities> {
  const [all, capacityProfiles, coreProfiles] = await Promise.all([
    fetchVisionMapEntities(),
    fetchArrayOrEmpty<CapacityProfile>('/capacity-profiles'),
    fetchArrayOrEmpty<CoreProfile>('/core-profiles'),
  ])
  const coreProfile =
    coreProfiles.find((p) => p.is_canonical) ??
    coreProfiles.find((p) => p.is_primary) ??
    coreProfiles[0] ??
    null
  return {
    ideas: all.ideas,
    initiatives: all.initiatives,
    projects: all.projects,
    tasks: all.tasks,
    persons: all.persons,
    assets: all.assets,
    capacityProfiles,
    coreProfile,
  }
}

/** The shared attributed subject read (Thresholds-1 / Kintsugi-1 /
 *  Guests-1): boundary states, Kintsugi material, and attending
 *  seats for ONE subject. Fetched per subject as the visitor walks —
 *  on entering a floor or room — never for the whole Palace at once.
 *  Degrades to null on any failure: the world then stands exactly
 *  as it did without the read (plain vessel, no guest objects, the
 *  general boundaries panel unchanged). */
/** Per-subject seat-interaction counts (GET
 *  /conversation/subject-interactions) — the ivy read for Scene 1:
 *  how much the visitor has talked about each subject, and with
 *  which seats. Served owner-scoped by the conversation routes
 *  from the messages' own live-context snapshots. Degrades to an
 *  empty list on any failure: the Palace then stands with resting
 *  ivy (stage 1, natural green) rather than failing. */
/** The stored overhead layout record for one project (or the
 *  loose-tasks grouping, under its reserved key) — null when
 *  none stands, on any failure: a missing record means a cold
 *  layout, never a broken world. The record's shape is checked
 *  lightly here so a malformed stored record degrades to a cold
 *  layout instead of corrupting the scene; the store validates
 *  strictly at write time. */
export async function fetchPalaceLayout(projectKey: string): Promise<PalaceLayoutRecord | null> {
  try {
    const res = await fetch(
      `${apiBase()}/conversation/palace-layout/${encodeURIComponent(projectKey)}`,
      { credentials: 'include' },
    )
    if (!res.ok) return null
    const data = (await res.json()) as { layout?: unknown }
    return isLayoutRecord(data.layout) ? data.layout : null
  } catch {
    return null
  }
}

function isLayoutRecord(value: unknown): value is PalaceLayoutRecord {
  if (typeof value !== 'object' || value === null) return false
  const r = value as Record<string, unknown>
  return (
    typeof r.version === 'number' &&
    typeof r.scale === 'number' &&
    typeof r.positions === 'object' &&
    r.positions !== null &&
    typeof r.weights === 'object' &&
    r.weights !== null &&
    typeof r.lastTransition === 'object' &&
    r.lastTransition !== null &&
    Array.isArray(r.unplaced)
  )
}

/** Persist one project's overhead layout record — called only
 *  when a layout is computed or changes. Failures are swallowed:
 *  the plan on screen stands either way, and the next open
 *  recomputes from whatever record survived. */
export async function savePalaceLayout(
  projectKey: string,
  record: PalaceLayoutRecord,
): Promise<void> {
  try {
    await fetch(`${apiBase()}/conversation/palace-layout/${encodeURIComponent(projectKey)}`, {
      method: 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ record }),
    })
  } catch {
    /* the world stands; the next open recomputes */
  }
}

export async function fetchSubjectInteractions(): Promise<SubjectInteraction[]> {
  try {
    const res = await fetch(`${apiBase()}/conversation/subject-interactions`, {
      credentials: 'include',
    })
    if (!res.ok) return []
    const data: unknown = await res.json()
    if (!data || typeof data !== 'object') return []
    const subjects = (data as { subjects?: unknown }).subjects
    if (!Array.isArray(subjects)) return []
    const out: SubjectInteraction[] = []
    for (const s of subjects) {
      if (!s || typeof s !== 'object') continue
      const row = s as { entity_type?: unknown; entity_id?: unknown; total?: unknown; per_seat?: unknown }
      if (typeof row.entity_type !== 'string' || typeof row.entity_id !== 'string') continue
      if (typeof row.total !== 'number' || !Number.isFinite(row.total)) continue
      const perSeat: Record<string, number> = {}
      if (row.per_seat && typeof row.per_seat === 'object') {
        for (const [seat, count] of Object.entries(row.per_seat as Record<string, unknown>)) {
          if (typeof count === 'number' && Number.isFinite(count)) perSeat[seat] = count
        }
      }
      out.push({ entity_type: row.entity_type, entity_id: row.entity_id, total: row.total, per_seat: perSeat })
    }
    return out
  } catch {
    return []
  }
}

export async function fetchAttributedRead(
  entityType: 'project' | 'task',
  entityId: string,
): Promise<AttributedRead | null> {
  try {
    const res = await fetch(
      `${VISION_EXECUTION_API}/attributed-read/${entityType}/${entityId}`,
      { credentials: 'include' },
    )
    if (!res.ok) return null
    const data: unknown = await res.json()
    if (!data || typeof data !== 'object') return null
    return data as AttributedRead
  } catch {
    return null
  }
}
