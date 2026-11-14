/**
 * Conversation colour — the founder's law (2026-11-14): "conversation
 * within the project with one of the characters shifts the color of
 * the stone towards that characters color", and "if it's the only
 * conversation had in that stone [it is] entirely shifted to that
 * color."
 *
 * The formula, exactly:
 * - Count an entity's linked COMPLETED conversations per seat.
 * - If the total count is > 0, the entity's effective strand weights
 *   are normalize( Σ_seat count_seat × seatBlend(seat) ) — the
 *   conversations determine the colour, proportionally; an exclusive
 *   conversation history is entirely that seat's blend.
 * - If the count is 0, the effective weights are the entity's stated
 *   strand weights, exactly as before this module existed (the
 *   regression guard: zero-conversation entities tint identically to
 *   the pre-conversation-colour build).
 *
 * The seat blends are the seats' own authored strand vectors — the
 * same STOCK_ARCHETYPE_FALLBACK record the Living Tree renders from —
 * imported, never duplicated.
 *
 * Conversation sources (what genuinely links a seat to a project in
 * the data the map already loads):
 * - Keystone chains ("Meet your council"): each seat's four keystone
 *   tasks carry `seat_ref` on the wire, chained 1→2→3→4 by
 *   dependency_ids under the seat's own "Meet the {character}"
 *   project. The chain's conversation is the seat's meeting arc within
 *   that project; it counts ONCE, when keystone 1 ("First meeting")
 *   is Done — the meeting happened. (The seed copy calls the chain
 *   "four meetings, in order", and keystones 2–4 are distinct
 *   encounters in the design, but all four are with the SAME seat, so
 *   under the normalized formula the project's colour is the seat's
 *   blend at any count ≥ 1; counting the arc once at the first
 *   meeting is the founder's met-gate: colour is earned by the first
 *   conversation, not accumulated per checklist step.)
 * - Studio council runs (GET /studio/council/recent-runs): inspected —
 *   they link a run to an entity subject but carry NO seat identity
 *   (the studio council is the build-room model council, not the
 *   seven seats), so they cannot attribute a conversation to a
 *   character and contribute nothing here.
 * - Encounter/conversation records beyond the keystones carry no
 *   project reference the map loads, so ordinary seat conversations
 *   about ordinary projects cannot be counted yet — that gap is
 *   reported, not papered over with invented capture.
 */
import { STOCK_ARCHETYPE_FALLBACK } from '../living-tree/archetypes'
import type { StrandKey } from '../council/colors'
import type { CairnStrandWeights } from './cairnTower'
import type { Task } from '../vision-execution/types'

const STRAND_KEYS: readonly StrandKey[] = [
  'word',
  'number',
  'image',
  'sound',
  'body',
  'people',
  'self',
]

/** The seven seats' authored blends, keyed by seat_ref (the archetype
    ids ARE the seat_refs: conductor/mentor/champion/guardian/
    ambassador/skeptic/maverick). Shape-checked at this boundary like
    every other weights consumer: finite positive numbers only. */
const SEAT_BLENDS: ReadonlyMap<string, CairnStrandWeights> = (() => {
  const map = new Map<string, CairnStrandWeights>()
  for (const a of STOCK_ARCHETYPE_FALLBACK) {
    const out: CairnStrandWeights = {}
    for (const k of STRAND_KEYS) {
      const v = a.strand_weights?.[k]
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) out[k] = v
    }
    if (Object.keys(out).length) map.set(a.id, out)
  }
  return map
})()

/** A seat's own blend (its authored strand vector), or null when the
    seat_ref names no known seat. */
export function seatBlendFor(seatRef: string | null | undefined): CairnStrandWeights | null {
  if (!seatRef) return null
  return SEAT_BLENDS.get(seatRef.trim()) ?? null
}

/** Completed conversations per seat, keyed by seat_ref. */
export type SeatConversationCounts = Partial<Record<string, number>>

/**
 * normalize( Σ_seat count_seat × seatBlend(seat) ). Null when no
 * conversation contributes — no counts, zero counts, or only seats
 * with no known blend (a conversation we cannot attribute to a
 * character's colour cannot invent one).
 */
export function conversationWeights(counts: SeatConversationCounts | null | undefined): CairnStrandWeights | null {
  if (!counts) return null
  const acc: CairnStrandWeights = {}
  let contributed = false
  for (const [seatRef, count] of Object.entries(counts)) {
    if (typeof count !== 'number' || !Number.isFinite(count) || count <= 0) continue
    const blend = seatBlendFor(seatRef)
    if (!blend) continue
    contributed = true
    for (const k of STRAND_KEYS) {
      const w = blend[k]
      if (typeof w === 'number' && w > 0) acc[k] = (acc[k] ?? 0) + count * w
    }
  }
  if (!contributed) return null
  let sum = 0
  for (const k of STRAND_KEYS) sum += acc[k] ?? 0
  if (!(sum > 0)) return null
  const out: CairnStrandWeights = {}
  for (const k of STRAND_KEYS) {
    const v = acc[k]
    if (typeof v === 'number' && v > 0) out[k] = v / sum
  }
  return Object.keys(out).length ? out : null
}

/**
 * The weights a stone actually wears: the conversation colour when
 * the entity has linked completed conversations, otherwise its stated
 * strand weights untouched (null stays null — unweighed is honest).
 */
export function effectiveStrandWeights(
  stated: CairnStrandWeights | null | undefined,
  counts: SeatConversationCounts | null | undefined,
): CairnStrandWeights | null {
  return conversationWeights(counts) ?? stated ?? null
}

/** Chain depth of one keystone task within its own seat's chain
    (number of in-chain ancestors via dependency_ids) — the frontend
    mirror of keystone_seeding._chain_order: the seed chains each task
    to exactly the previous one, so depth IS the keystone index. */
function chainDepth(task: Task, byId: ReadonlyMap<string, Task>): number {
  let d = 0
  const seen = new Set<string>()
  let cur = task
  for (;;) {
    const deps = (cur.dependency_ids ?? []).filter((x) => byId.has(x))
    if (!deps.length || seen.has(deps[0]!)) return d
    seen.add(deps[0]!)
    d += 1
    cur = byId.get(deps[0]!)!
  }
}

/**
 * Per-project conversation counts from the keystone chains — the one
 * conversation source that genuinely links (seat, project) today.
 * Keyed by project id. A seat contributes {seat: 1} to its "Meet the
 * {character}" project when the chain's first task ("First meeting")
 * is Done; before that the project has no entry at all, so its stones
 * fall back to stated weights (none exist for keystone entities —
 * grey, correct by design until met).
 */
export function keystoneConversationCountsByProject(
  tasks: readonly Task[],
): Map<string, SeatConversationCounts> {
  const byProject = new Map<string, Map<string, Task[]>>()
  for (const t of tasks) {
    const seat = (t.seat_ref ?? '').trim()
    if (!seat || !t.project_id) continue
    let bySeat = byProject.get(t.project_id)
    if (!bySeat) {
      bySeat = new Map()
      byProject.set(t.project_id, bySeat)
    }
    const list = bySeat.get(seat) ?? []
    list.push(t)
    bySeat.set(seat, list)
  }
  const out = new Map<string, SeatConversationCounts>()
  for (const [projectId, bySeat] of byProject) {
    for (const [seat, chain] of bySeat) {
      const byId = new Map(chain.map((t) => [t.id, t]))
      const ordered = chain
        .map((t, i) => ({ t, i, d: chainDepth(t, byId) }))
        .sort((a, b) => a.d - b.d || a.i - b.i)
        .map((x) => x.t)
      const k1 = ordered[0]
      if (k1 && (k1.status ?? '').trim() === 'Done') {
        const counts = out.get(projectId) ?? {}
        counts[seat] = (counts[seat] ?? 0) + 1
        out.set(projectId, counts)
      }
    }
  }
  return out
}
