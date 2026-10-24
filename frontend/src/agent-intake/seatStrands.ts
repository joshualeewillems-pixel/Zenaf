/**
 * Seat -> strands map for seat-scoped review.
 *
 * Canonical source: local_ai/council/archetypes.py STOCK_ARCHETYPES — each
 * council seat is a weight vector across the 7 strands, not a single strand.
 * A strand belongs to a seat's review scope when its weight is at or above
 * WEIGHT_FLOOR (0.05), the same floor the backend uses to decide which
 * strands get woven into a seat's prompt. This keeps the frontend's notion of
 * "the seat's strands" identical to the backend's own definition of which
 * strands matter for a seat. Plain-spoken names converted via PLAIN_TO_KEY
 * (Voice->word, Logic->number, Eye->image, Ear->sound, Hands->body,
 * Heart->people, Compass->self).
 *
 * The Skeptic's weights are computed dynamically server-side (inverse of the
 * user's dominant strands), so there is no static vector — it maps to null,
 * meaning "no filter" (whole queue), the same as the you-node. An unknown
 * seat key also resolves to null (safe default: show everything).
 */
export const SEAT_STRANDS: Record<string, string[] | null> = {
  mentor: ['self', 'number', 'word', 'people', 'image'],
  champion: ['body', 'self', 'number', 'people', 'word'],
  guardian: ['people', 'body', 'self', 'word', 'image'],
  maverick: ['word', 'image', 'number', 'self', 'sound'],
  ambassador: ['word', 'image', 'people', 'self', 'number'],
  conductor: ['self', 'number', 'word', 'people', 'image', 'body', 'sound'],
  skeptic: null,
}

/**
 * The sorter's multi-frame routing threshold
 * (local_ai/agent_intake/sorter.py _WEIGHT_THRESHOLD): every strand at or
 * above this weight trains on the agent. An agent belongs in a seat's review
 * queue when any of the seat's strands reaches this threshold in the agent's
 * sort weights.
 */
export const SORT_WEIGHT_THRESHOLD = 0.25

/** Resolve a seat key to its review-scope strands, or null for "no filter". */
export function seatStrands(seatKey: string | null | undefined): string[] | null {
  if (!seatKey) return null
  return SEAT_STRANDS[seatKey] ?? null
}

/**
 * Seats as review buckets, in council order (names mirror FELLOWSHIP_NAMES
 * in living-tree/LivingTree.tsx). The Skeptic is deliberately absent: its
 * scope is computed dynamically server-side (the whole queue), so it is
 * not a filing bucket an upload can be attributed to.
 */
export const SEAT_REVIEW_GROUPS: Array<{ key: string; name: string }> = [
  { key: 'mentor', name: 'The Gardener' },
  { key: 'champion', name: 'The Firebrand' },
  { key: 'guardian', name: 'The Bear' },
  { key: 'ambassador', name: 'The Crane' },
  { key: 'conductor', name: 'The Weaver' },
  { key: 'maverick', name: 'The Fox' },
]

/**
 * Which seats' review queues an agent belongs in, from its sort weights —
 * the same reach rule the seat sheets filter by (any of the seat's
 * strands at or above SORT_WEIGHT_THRESHOLD). Unsorted agents (no
 * weights) belong to no seat yet.
 */
export function seatKeysForWeights(
  weights: Record<string, number> | null | undefined,
): string[] {
  if (!weights) return []
  return SEAT_REVIEW_GROUPS.filter(({ key }) => {
    const strands = SEAT_STRANDS[key]
    return !!strands && strands.some((s) => (weights[s] ?? 0) >= SORT_WEIGHT_THRESHOLD)
  }).map(({ key }) => key)
}
