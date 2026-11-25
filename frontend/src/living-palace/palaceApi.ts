/**
 * The Living Palace — reads.
 *
 * The Palace renders the visitor's real body of work or it does not
 * ship: every read goes through an endpoint that already exists.
 * The world itself reads the Vision Map's entity fetch (the same
 * routes the Board and the Bench read) plus the capacity profiles
 * and core profiles the VE workspace already serves.
 *
 * The boundaries panel composes ONLY from records that exist today:
 * the visitor's strand topic boundaries (GET /conversation/strand/
 * {key}, the same resolve the chat's own StrandPanel reads — it is
 * resolve-or-create on the server, so the panel fetches it lazily,
 * only when a doorway is actually tapped, never on Palace load),
 * the core profile's declared non-negotiables, and the permission
 * home's consent state. There is NO per-subject boundary store and
 * this module invents none.
 */
import {
  VISION_EXECUTION_API,
  type CapacityProfile,
  type CoreProfile,
} from '../vision-execution/types'
import { fetchVisionMapEntities } from '../vision-map/veMapApi'
import { apiBase } from '../apiBase'
import { fetchPermissionHome } from '../settings/api'
import type { AttributedRead, PalaceData, StrandBoundarySet } from './palaceLogic'

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

/** The seven strands, in the canonical order the strand system
 *  itself keeps (Voice, Logic, Eye, Ear, Hands, Heart, Compass). */
export const PALACE_STRAND_KEYS = ['voice', 'logic', 'eye', 'ear', 'hands', 'heart', 'compass']

export interface BoundaryMaterial {
  strandBoundaries: StrandBoundarySet[]
  permissionGroups: { id: string; state: string }[]
}

interface StrandResolvePayload {
  strand_name?: string
  boundaries?: { id?: string; topic?: string; created_at?: string }[]
}

/** Fetch the boundary material the existing API honestly serves.
 *  Called only when a threshold is tapped. Every source degrades to
 *  empty on failure — the panel then says plainly what exists. */
export async function fetchBoundaryMaterial(): Promise<BoundaryMaterial> {
  const strandBoundaries: StrandBoundarySet[] = []
  await Promise.all(
    PALACE_STRAND_KEYS.map(async (key) => {
      try {
        const res = await fetch(`${apiBase()}/conversation/strand/${key}`, {
          credentials: 'include',
        })
        if (!res.ok) return
        const payload = (await res.json()) as StrandResolvePayload
        strandBoundaries.push({
          strandKey: key,
          strandName: payload.strand_name ?? key,
          topics: (payload.boundaries ?? [])
            .map((b) => (typeof b.topic === 'string' ? b.topic : ''))
            .filter(Boolean),
        })
      } catch {
        /* a strand that cannot be read contributes nothing */
      }
    }),
  )
  // Keep the canonical strand order regardless of fetch completion.
  strandBoundaries.sort(
    (a, b) => PALACE_STRAND_KEYS.indexOf(a.strandKey) - PALACE_STRAND_KEYS.indexOf(b.strandKey),
  )
  let permissionGroups: { id: string; state: string }[] = []
  try {
    const home = await fetchPermissionHome()
    permissionGroups = home.intents.flatMap((intent) =>
      intent.groups.map((g) => ({ id: g.id, state: String(g.state) })),
    )
  } catch {
    permissionGroups = []
  }
  return { strandBoundaries, permissionGroups }
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
