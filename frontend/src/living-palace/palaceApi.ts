/**
 * The Living Palace — reads.
 *
 * The Palace renders the visitor's real body of work or it does not
 * ship: every read goes through an endpoint that already exists.
 * The world itself reads the Vision Map's entity fetch (the same
 * routes the Board and the Bench read) plus the capacity profiles
 * and core profiles the VE workspace already serves.
 *
 * Reads only (Palace pass, chat-is-the-work): this surface writes
 * nothing. The verdict-door callers and the weighing settle writes
 * that lived here (#432/#433) are superseded as forms — rulings and
 * weighings happen in Maeve's conversation now, through the chat's
 * own carriage. There is NO per-subject boundary store and this
 * module invents none.
 */
import {
  VISION_EXECUTION_API,
  type CapacityProfile,
  type CoreProfile,
} from '../vision-execution/types'
import { fetchVisionMapEntities } from '../vision-map/veMapApi'
import type { AttributedRead, PalaceData } from './palaceLogic'

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
