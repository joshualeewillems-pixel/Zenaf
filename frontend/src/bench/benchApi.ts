/**
 * Severine's Bench — Vision Execution reads and the governed
 * proposal verdicts.
 *
 * Reads reuse the Vision Map's entity fetch (the same routes the
 * Campaign Board uses). Wire (§2 of the definitions) reads pending
 * recorded proposals per branch through
 * GET /vision-execution/task-proposals/by-parent/{id} — a read-only
 * route over the existing owner-scoped storage query. Reading
 * foliage (§7's second source) reads
 * GET /vision-execution/bench-foliage/by-parent/{type}/{id} — a
 * read-only, fail-closed route over the steward's narrative store.
 * Verdicts go
 * through the EXISTING governed endpoints the chat proposal cards
 * use: POST /vision-execution/task-proposals/{id}/approve (the
 * proposal becomes a task — wood) and .../decline (the proposed line
 * is removed; the proposal row keeps the decision). The Bench writes
 * nothing anywhere else and invents no store.
 */
import { VISION_EXECUTION_API, type Task } from '../vision-execution/types'
import { fetchVisionMapEntities } from '../vision-map/veMapApi'
import type { BenchEntities, BenchProposal } from './benchLogic'

export async function fetchBenchEntities(): Promise<BenchEntities> {
  const all = await fetchVisionMapEntities()
  return {
    ideas: all.ideas,
    initiatives: all.initiatives,
    projects: all.projects,
    tasks: all.tasks,
  }
}

/** Pending proposals attached under one branch. Degrades to empty
 *  on failure, like the Board's circumstance reads: an unreadable
 *  proposal list must not take the whole Bench down, and a branch
 *  with no reachable proposals simply shows no wire. */
export async function fetchPendingProposals(parentTaskId: string): Promise<BenchProposal[]> {
  try {
    const res = await fetch(
      `${VISION_EXECUTION_API}/task-proposals/by-parent/${encodeURIComponent(parentTaskId)}?state=pending`,
      { credentials: 'include' },
    )
    if (!res.ok) return []
    const data: unknown = await res.json()
    const rows =
      data && typeof data === 'object' && Array.isArray((data as { proposals?: unknown }).proposals)
        ? ((data as { proposals: unknown[] }).proposals as BenchProposal[])
        : []
    return rows.filter((p) => p && typeof p.id === 'string' && p.state === 'pending')
  } catch {
    return []
  }
}

/** Steward-reading foliage evidence for one parent (initiative,
 *  project, or task): task id -> the archetype ids whose steward
 *  readings touch that task (§7's second source). Degrades to
 *  empty on failure, like the proposal read: the endpoint is
 *  fail-closed under the pencil layer's gates, and an unreachable
 *  read must render exactly like a closed gate — provenance
 *  foliage only, never a broken Bench. */
export async function fetchBenchFoliage(
  parentType: 'initiative' | 'project' | 'task',
  parentId: string,
): Promise<Map<string, string[]>> {
  try {
    const res = await fetch(
      `${VISION_EXECUTION_API}/bench-foliage/by-parent/${parentType}/${encodeURIComponent(parentId)}`,
      { credentials: 'include' },
    )
    if (!res.ok) return new Map()
    const data: unknown = await res.json()
    const raw =
      data &&
      typeof data === 'object' &&
      typeof (data as { foliage?: unknown }).foliage === 'object' &&
      (data as { foliage?: unknown }).foliage !== null
        ? (data as { foliage: Record<string, unknown> }).foliage
        : {}
    const out = new Map<string, string[]>()
    for (const [taskId, seats] of Object.entries(raw)) {
      if (Array.isArray(seats)) {
        out.set(
          taskId,
          seats.filter((s): s is string => typeof s === 'string'),
        )
      }
    }
    return out
  } catch {
    return new Map()
  }
}

async function proposalAction(
  proposalId: string,
  kind: 'approve' | 'decline',
): Promise<{ task?: Task; proposal: BenchProposal }> {
  const res = await fetch(
    `${VISION_EXECUTION_API}/task-proposals/${encodeURIComponent(proposalId)}/${kind}`,
    { method: 'POST', credentials: 'include' },
  )
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text.trim() || `Request failed (${res.status})`)
  }
  return res.json() as Promise<{ task?: Task; proposal: BenchProposal }>
}

/** "Let this stand" — the governed approve: the proposal becomes a
 *  real task under the branch, through the same endpoint the chat
 *  proposal cards use. */
export function approveProposal(proposalId: string) {
  return proposalAction(proposalId, 'approve')
}

/** "Cut this back" — the governed decline: the proposed line is
 *  removed; the proposal row keeps the decision on the record. */
export function declineProposal(proposalId: string) {
  return proposalAction(proposalId, 'decline')
}
