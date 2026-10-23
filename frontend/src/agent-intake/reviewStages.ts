/**
 * Staged review gating: an agent leaves the review queue only when every
 * claim is resolved (accepted / corrected / explained) AND the project-mining
 * step is resolved (mined or explicitly skipped). Pure functions so the gate
 * is unit-testable and the UI can't drift from it.
 */

export type StageClaim = {
  id: string
  claim_type: string
  status: string
}

export type MiningState = 'pending' | 'mined' | 'skipped'

export const MINED_CLAIM_TYPES = ['initiative', 'project', 'task', 'idea']
export const PLACEMENT_CLAIM_TYPES = ['strand', 'kind']
export const INSIGHT_CLAIM_TYPES = ['value_inference', 'decision_pattern', 'stance', 'preference', 'recurrence']
export const ALTERNATIVE_CLAIM_TYPE = 'alternative'

/** Claims that gate finishing the review. Alternatives never block: pending
 *  ones are marked "unresolved" at file time — an explicit left-open, never
 *  a silent approval of an interpretation the user didn't confirm. */
export function primaryClaims(claims: StageClaim[]): StageClaim[] {
  return claims.filter((c) => c.claim_type !== ALTERNATIVE_CLAIM_TYPE)
}

/**
 * Effective mining state. The backend persists mining_state on the agent;
 * mined claims already stored are treated as mined even if the column
 * predates the agent row (migration backfill via evidence, not guesswork).
 */
export function miningStateOf(
  agentMiningState: string | undefined | null,
  claims: StageClaim[],
): MiningState {
  if (agentMiningState === 'mined' || agentMiningState === 'skipped') return agentMiningState
  return claims.some((c) => MINED_CLAIM_TYPES.includes(c.claim_type)) ? 'mined' : 'pending'
}

export function openClaimsCount(claims: StageClaim[]): number {
  return primaryClaims(claims).filter((c) => c.status === 'pending').length
}

export function allClaimsResolved(claims: StageClaim[]): boolean {
  const primary = primaryClaims(claims)
  return primary.length > 0 && primary.every((c) => c.status !== 'pending')
}

export function canFinishReview(claims: StageClaim[], mining: MiningState): boolean {
  return allClaimsResolved(claims) && mining !== 'pending'
}

/**
 * Terse, plain-language list of what blocks finishing. Shown inline under
 * the finish button — never a popup.
 */
export function whatsLeft(claims: StageClaim[], mining: MiningState): string[] {
  const left: string[] = []
  const primary = primaryClaims(claims)
  if (primary.length === 0) {
    left.push('claims still loading')
  } else {
    const n = primary.filter((c) => c.status === 'pending').length
    if (n > 0) left.push(`${n} claim${n === 1 ? '' : 's'} still open`)
  }
  if (mining === 'pending') left.push('project mining not done — mine or skip')
  return left
}

export function miningStatusLabel(mining: MiningState): string {
  return mining === 'mined' ? 'projects mined' : mining === 'skipped' ? 'mining skipped' : 'not mined yet'
}

/** One insight (interpretation) with its individually-respondable alternatives. */
export type InsightGroup<T extends StageClaim = StageClaim> = {
  insight: T
  alternatives: T[]
}

/** Group atomic insight claims with their alternatives by id prefix
 *  ("{agent_id}:insight:3" -> "{agent_id}:insight:3:alt:0"). Alternatives render nested under
 *  their interpretation — never collapsed away, each with its own verdict. */
export function insightGroups<T extends StageClaim>(claims: T[]): InsightGroup<T>[] {
  const insights = claims.filter((c) => INSIGHT_CLAIM_TYPES.includes(c.claim_type))
  return insights.map((insight) => {
    const prefix = `${insight.id}:alt:`
    const alternatives = claims
      .filter((c) => c.claim_type === ALTERNATIVE_CLAIM_TYPE && c.id.startsWith(prefix))
      .sort((a, b) => a.id.localeCompare(b.id))
    return { insight, alternatives }
  })
}

/** Group moment-level strand placement cards with their alternative readings.
 *
 *  Same id-prefix scheme as insightGroups: a parent "…:strand:self:m3" nests
 *  "…:strand:self:m3:alt:0". The ":alt:" separator keeps "m3" from matching
 *  "m30". */
export function strandGroups<T extends StageClaim>(claims: T[]): InsightGroup<T>[] {
  const parents = claims.filter((c) => c.claim_type === 'strand' || c.claim_type === 'strand_placement')
  return parents.map((parent) => {
    const prefix = `${parent.id}:alt:`
    const alternatives = claims
      .filter((c) => c.claim_type === ALTERNATIVE_CLAIM_TYPE && c.id.startsWith(prefix))
      .sort((a, b) => a.id.localeCompare(b.id))
    return { insight: parent, alternatives }
  })
}

export type ReviewedAgent = {
  id: string
  status: string
  created_at: string
}

/** Recently filed agents, newest first — the recovery path for mining after accept. */
export function reviewedList<T extends ReviewedAgent>(agents: T[], limit = 10): T[] {
  return agents
    .filter((a) => a.status === 'active')
    .sort((x, y) => y.created_at.localeCompare(x.created_at))
    .slice(0, limit)
}

/** Accordion default: pending cards start open (action needed); resolved
 *  cards start collapsed to save vertical space. */
export function defaultCardExpanded(status: string): boolean {
  return status === 'pending'
}
