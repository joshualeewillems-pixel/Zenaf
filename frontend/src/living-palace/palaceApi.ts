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
import type {
  AttributedRead,
  PalaceData,
  StrandBoundarySet,
  WeighingChanges,
  WeighingDecisionPayload,
} from './palaceLogic'

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

/* ------------------------------------------------------------------ */
/* Verdict Slice 1 — the review acts.                                  */
/*                                                                     */
/* The Palace is the FIRST frontend client of the steward review     */
/* routes (api/routes/steward_review_routes.py): one mechanism,      */
/* already built — verdicts transition the proposal and append to    */
/* the verdict log; endorsement annotates and transitions nothing;   */
/* explore carries an item into a strand thread with Aria and        */
/* changes no state; the reconsideration request opens a candidacy   */
/* over an accepted reading, the visitor's cause preserved verbatim. */
/* These callers only report whether the act reached the record;     */
/* the view re-reads the attributed read to see the new state.       */
/* ------------------------------------------------------------------ */

const REVIEW_API = '/steward/review'

/** Split a review item id ("reading:rdg-…") into its route parts. */
export function parseReviewItemId(itemId: string): { kind: string; rowId: string } | null {
  const idx = itemId.indexOf(':')
  if (idx <= 0 || idx === itemId.length - 1) return null
  return { kind: itemId.slice(0, idx), rowId: itemId.slice(idx + 1) }
}

async function postReview(path: string, body?: unknown): Promise<boolean> {
  try {
    const res = await fetch(`${apiBase()}${REVIEW_API}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    return res.ok
  } catch {
    return false
  }
}

function verdictCaller(verb: 'accept' | 'reject' | 'unresolve') {
  return async (itemId: string): Promise<boolean> => {
    const ref = parseReviewItemId(itemId)
    if (!ref) return false
    return postReview(`/${ref.kind}/${ref.rowId}/${verb}`)
  }
}

/** Accept: the interpretation gains confirmed standing. */
export const acceptReviewItem = verdictCaller('accept')
/** Reject: the interpretation is dismissed, durably, and logged. */
export const rejectReviewItem = verdictCaller('reject')
/** Unresolve: explicit not-deciding, recorded as a verdict in its
 *  own right; the item stays pending. */
export const unresolveReviewItem = verdictCaller('unresolve')

/** Endorse a reading as it stands — an annotation, never a verdict:
 *  it supersedes nothing and transitions nothing. */
export async function endorseReviewReading(itemId: string): Promise<boolean> {
  const ref = parseReviewItemId(itemId)
  if (!ref || ref.kind !== 'reading') return false
  return postReview(`/reading/${ref.rowId}/endorse`, { stance: 'endorsed', note: '' })
}

/** Explore with Aria: carry the item into the chosen strand thread
 *  as a source. No verdict, no state change on the proposal. */
export async function exploreReviewItem(itemId: string, strandKey: string): Promise<boolean> {
  const ref = parseReviewItemId(itemId)
  if (!ref) return false
  return postReview(`/${ref.kind}/${ref.rowId}/explore`, { strand_key: strandKey })
}

/** Ask for an accepted reading to be looked at again. The cause is
 *  the visitor's own words, sent verbatim — the route preserves
 *  them as the candidacy's reason. Opens a candidacy; it does not
 *  un-accept the reading, and the candidacy itself awaits his
 *  verdict like any other proposal. */
export async function requestReconsideration(readingId: string, reason: string): Promise<boolean> {
  return postReview(`/reading/${readingId}/reconsider`, { reason })
}

/* ------------------------------------------------------------------ */
/* Scales-1 — the settle act's writes.                                 */
/*                                                                     */
/* Exploration never calls any of this: these functions run ONLY     */
/* from the weighing panel's settle act, the visitor's explicit      */
/* confirmation. Every write goes through a route that already       */
/* exists, with the payload shape that route already takes — the     */
/* same PATCH /projects and PATCH /tasks the Campaign Board writes   */
/* through, the VE workspace's own PUT /capacity-profiles body, and  */
/* POST /decisions in DecisionCreateRequest's shape. No new route,   */
/* no new record family, no model call.                              */
/* ------------------------------------------------------------------ */

async function veWriteOk(method: 'PATCH' | 'PUT' | 'POST', path: string, body: unknown): Promise<boolean> {
  try {
    const res = await fetch(`${VISION_EXECUTION_API}${path}`, {
      method,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return res.ok
  } catch {
    return false
  }
}

export interface WeighingSettleOutcome {
  /** The figure writes that reached the record, in the order they
   *  were made. */
  landed: string[]
  /** The first figure write that failed, if any. Settling stops
   *  there, and the decision is NOT recorded — a decision claiming
   *  figures that never landed would misrecord the weighing. */
  failed: string | null
  decisionAttempted: boolean
  /** The decision write is separately fallible: POST /decisions
   *  stands behind the profile-learning permission, which the
   *  Palace cannot open from here. Figures that landed stand
   *  regardless; the caller reports the keeping honestly. */
  decisionRecorded: boolean
}

/** Settle a weighing: write the changed figures through their
 *  existing routes (floor figures, then the room's estimate, then
 *  the keeper's capacity), and — only when every figure landed —
 *  record the weighing itself as a decision carrying its
 *  provenance. */
export async function settleWeighing(input: {
  projectId: string | null
  taskId: string | null
  changes: WeighingChanges
  decision: WeighingDecisionPayload | null
}): Promise<WeighingSettleOutcome> {
  const landed: string[] = []
  const { changes } = input
  if (changes.projectPatch && input.projectId) {
    const ok = await veWriteOk('PATCH', `/projects/${input.projectId}`, changes.projectPatch)
    if (!ok) return { landed, failed: 'the floor’s figures', decisionAttempted: false, decisionRecorded: false }
    landed.push('the floor’s figures')
  }
  if (changes.taskPatch && input.taskId) {
    const ok = await veWriteOk('PATCH', `/tasks/${input.taskId}`, changes.taskPatch)
    if (!ok) return { landed, failed: 'the room’s estimate', decisionAttempted: false, decisionRecorded: false }
    landed.push('the room’s estimate')
  }
  if (changes.capacityPut) {
    const ok = await veWriteOk('PUT', '/capacity-profiles', changes.capacityPut)
    if (!ok) return { landed, failed: 'the keeper’s capacity', decisionAttempted: false, decisionRecorded: false }
    landed.push('the keeper’s capacity')
  }
  let decisionRecorded = false
  if (input.decision) {
    decisionRecorded = await veWriteOk('POST', '/decisions', input.decision)
  }
  return { landed, failed: null, decisionAttempted: input.decision != null, decisionRecorded }
}
