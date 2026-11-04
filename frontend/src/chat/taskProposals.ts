/**
 * Parsing for fenced ```task-proposal blocks in seat replies.
 * Pure: no fetch, no React. Mirrors the server's validation so invalid
 * blocks render error cards instead of actions — but the server is
 * always authoritative (it re-validates and provenance-checks).
 */

export type ParsedProposal = {
  title: string
  parent_task_id: string | null
  timeframe_commitment: 'tentative' | null
  due_date: string | null
  notes: string
}

export type ProposalEntry = {
  blockIndex: number
  proposalIndex: number
  /** Stable triple key: <server message id>#<block index>:<proposal index>. */
  key: string
  valid: boolean
  proposal: ParsedProposal | null
}

const FENCE_RE = /```task-proposal\s*\n(.*?)```/gs
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

function isRealDate(s: string): boolean {
  if (!DATE_RE.test(s)) return false
  const [y, m, d] = s.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d
}

function validateProposal(raw: unknown): ParsedProposal | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const title = typeof r.title === 'string' ? r.title.trim() : ''
  if (!title) return null
  const timeframe = r.timeframe_commitment ?? null
  if (timeframe !== null && timeframe !== 'tentative') return null
  const dueRaw = r.due_date ?? null
  let due: string | null = null
  if (dueRaw !== null) {
    if (typeof dueRaw !== 'string') return null
    const s = dueRaw.trim()
    if (s !== '' && !isRealDate(s)) return null
    due = s === '' ? null : s
  }
  const parentRaw = r.parent_task_id ?? null
  const parent =
    parentRaw === null || parentRaw === undefined
      ? null
      : typeof parentRaw === 'string'
        ? parentRaw.trim() || null
        : null
  if (parentRaw !== null && parentRaw !== undefined && typeof parentRaw !== 'string') return null
  return {
    title,
    parent_task_id: parent,
    timeframe_commitment: timeframe,
    due_date: due,
    notes: typeof r.notes === 'string' ? r.notes : '',
  }
}

/** Display-only: remove fenced proposal blocks from chat text. The
 * stored reply keeps the block as the carrier; only the rendered
 * bubble hides the raw JSON (cards render below it). */
export function stripTaskProposalBlocks(text: string): string {
  return text.replace(FENCE_RE, '').replace(/\n{3,}/g, '\n\n').trim()
}

/**
 * Parse every fenced block in reply text. A malformed block yields one
 * invalid entry (blockIndex, proposalIndex -1) so the UI can show the
 * error card; a well-formed block yields one entry per proposal, valid
 * or invalid per field validation. Unknown fields are ignored.
 */
export function parseTaskProposalBlocks(text: string, messageId: string): ProposalEntry[] {
  const out: ProposalEntry[] = []
  let blockIndex = 0
  for (const m of text.matchAll(FENCE_RE)) {
    let proposals: unknown = null
    try {
      const data = JSON.parse(m[1]) as Record<string, unknown>
      proposals = data && typeof data === 'object' ? data.proposals : null
    } catch {
      proposals = null
    }
    if (!Array.isArray(proposals)) {
      out.push({
        blockIndex,
        proposalIndex: -1,
        key: `${messageId}#${blockIndex}:-1`,
        valid: false,
        proposal: null,
      })
    } else {
      proposals.forEach((raw, proposalIndex) => {
        const valid = validateProposal(raw)
        out.push({
          blockIndex,
          proposalIndex,
          key: `${messageId}#${blockIndex}:${proposalIndex}`,
          valid: valid !== null,
          proposal: valid,
        })
      })
    }
    blockIndex += 1
  }
  return out
}
