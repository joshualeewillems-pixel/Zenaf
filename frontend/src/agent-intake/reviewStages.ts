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
  return claims.filter((c) => c.status === 'pending').length
}

export function allClaimsResolved(claims: StageClaim[]): boolean {
  return claims.length > 0 && claims.every((c) => c.status !== 'pending')
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
  if (claims.length === 0) {
    left.push('claims still loading')
  } else {
    const n = openClaimsCount(claims)
    if (n > 0) left.push(`${n} claim${n === 1 ? '' : 's'} still open`)
  }
  if (mining === 'pending') left.push('project mining not done — mine or skip')
  return left
}

export function miningStatusLabel(mining: MiningState): string {
  return mining === 'mined' ? 'projects mined' : mining === 'skipped' ? 'mining skipped' : 'not mined yet'
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
