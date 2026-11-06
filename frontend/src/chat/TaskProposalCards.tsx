/**
 * Proposal cards for fenced ```task-proposal blocks in seat replies.
 *
 * Contract (Firebrand task-context): the stored reply text is the
 * carrier, but card STATE comes from the server record, never client
 * memory. On mount the card lists server proposals for the
 * conversation, records any not-yet-recorded block (POST, deduped by
 * the re-attachment triple), and renders each record's state:
 * pending → Approve / Edit / Decline; approved → Created; declined →
 * Declined. Until recording confirms, actions are disabled. A 400
 * renders the error card (no actions); a transient failure offers
 * retry. Prose assent never writes — only the card's Approve posts,
 * and approval is the only path from proposal to task.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  parseTaskProposalBlocks,
  precedingParagraph,
  type ProposalEntry,
} from './taskProposals'

export type ServerProposal = {
  id: string
  conversation_id: string
  source_message_id: string
  block_index: number
  proposal_index: number
  seat: string
  title: string
  parent_task_id: string | null
  timeframe_commitment: string | null
  due_date: string | null
  notes: string
  state: 'pending' | 'approved' | 'declined'
  created_task_id: string | null
  // W1: evidence quote + originals (null on pre-W1 rows), and the
  // server-computed grounding flag — lexical correspondence only,
  // never verified meaning; null on rows with no quote.
  evidence_quote: string | null
  original_title: string | null
  original_parent_task_id: string | null
  original_timeframe_commitment: string | null
  original_due_date: string | null
  original_notes: string | null
  grounding_flag: 'words_matched' | 'summarized' | null
}

type Props = {
  base: string
  conversationId: string
  messageId: string
  seat: string
  content: string
}

type TaskOption = { id: string; title: string }

function tripleKey(p: ServerProposal): string {
  return `${p.source_message_id}#${p.block_index}:${p.proposal_index}`
}

// W1: display-only terminal check for the parent line (same word
// list as the server's parent-availability check). The server
// remains authoritative — approval still returns 409 for a terminal
// parent even if this display ever disagrees.
const TERMINAL_STATUS_RE = /\b(done|complete|completed|shipped|closed|won)\b/i
function isTerminalStatus(status: string | null | undefined): boolean {
  if (!status) return false
  return TERMINAL_STATUS_RE.test(status) || status.trim().toLowerCase() === 'dropped'
}

export default function TaskProposalCards({ base, conversationId, messageId, seat, content }: Props) {
  const entries = useMemo(() => parseTaskProposalBlocks(content, messageId), [content, messageId])
  const [records, setRecords] = useState<Record<string, ServerProposal>>({})
  const [invalidKeys, setInvalidKeys] = useState<Set<string>>(new Set())
  const [failedKeys, setFailedKeys] = useState<Set<string>>(new Set())
  const [busyKeys, setBusyKeys] = useState<Set<string>>(new Set())
  const [actionError, setActionError] = useState<Record<string, string>>({})
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editTimeframe, setEditTimeframe] = useState('')
  const [editDue, setEditDue] = useState('')
  const [editParent, setEditParent] = useState('')
  const [parentOptions, setParentOptions] = useState<TaskOption[] | null>(null)
  // W1: task id -> { title, status }, for the parent line on pending
  // cards. null = not loaded (or the fetch failed): no parent line
  // renders rather than a wrong "no longer available".
  const [tasksById, setTasksById] = useState<Record<
    string,
    { title: string; status: string }
  > | null>(null)
  const attemptedRef = useRef<Set<string>>(new Set())
  const recordsRef = useRef(records)
  recordsRef.current = records

  useEffect(() => {
    let cancelled = false
    const merge = (list: ServerProposal[]) => {
      if (cancelled) return
      setRecords((prev) => {
        const next = { ...prev }
        for (const p of list) next[tripleKey(p)] = p
        return next
      })
    }
    // Hydration: server state first, so reload never reverts a decision.
    void fetch(
      `${base}/vision-execution/task-proposals?conversation_id=${encodeURIComponent(conversationId)}`,
      { credentials: 'include' },
    )
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && Array.isArray(data.proposals)) merge(data.proposals)
      })
      .catch(() => {
        /* list failure is non-fatal: recording POSTs still populate state */
      })
    // W1: task titles/statuses for the parent line. Non-fatal when it
    // fails — the parent line simply does not render.
    void fetch(`${base}/vision-execution/tasks`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !Array.isArray(data)) return
        const map: Record<string, { title: string; status: string }> = {}
        for (const t of data) {
          if (t && typeof t.id === 'string') {
            map[t.id] = { title: t.title ?? t.id, status: t.status ?? '' }
          }
        }
        setTasksById(map)
      })
      .catch(() => {
        /* tasks failure is non-fatal: no parent line renders */
      })
    // Record any block not yet known to the server. Deduped by triple
    // across renders (StrictMode double-effects included): the server
    // is idempotent too, but we never issue a duplicate POST.
    for (const e of entries) {
      if (!e.valid || !e.proposal) continue
      if (attemptedRef.current.has(e.key)) continue
      if (recordsRef.current[e.key]) continue
      attemptedRef.current.add(e.key)
      void fetch(`${base}/vision-execution/task-proposals`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          source_message_id: messageId,
          block_index: e.blockIndex,
          proposal_index: e.proposalIndex,
          seat,
          title: e.proposal.title,
          parent_task_id: e.proposal.parent_task_id,
          timeframe_commitment: e.proposal.timeframe_commitment,
          due_date: e.proposal.due_date,
          notes: e.proposal.notes,
          // W1 (C-1, Q3): the preceding prose paragraph is the
          // evidence quote; the server verifies it against the
          // source message's actual prose.
          evidence_quote: precedingParagraph(content, e.blockIndex),
        }),
      }).then(async (r) => {
        if (cancelled) return
        if (r.ok) {
          const p = (await r.json()) as ServerProposal
          merge([p])
          setFailedKeys((prev) => {
            const next = new Set(prev)
            next.delete(e.key)
            return next
          })
        } else if (r.status === 400) {
          setInvalidKeys((prev) => new Set(prev).add(e.key))
        } else {
          setFailedKeys((prev) => new Set(prev).add(e.key))
        }
      }).catch(() => {
        if (!cancelled) setFailedKeys((prev) => new Set(prev).add(e.key))
      })
    }
    return () => {
      cancelled = true
    }
    // Intentionally not depending on records: attemptedRef + the list
    // fetch cover hydration; depending on records would re-POST loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, conversationId, messageId, content])

  const retryRecord = (e: ProposalEntry) => {
    if (!e.valid || !e.proposal) return
    attemptedRef.current.delete(e.key)
    setFailedKeys((prev) => {
      const next = new Set(prev)
      next.delete(e.key)
      return next
    })
    // Re-run the record POST for this entry only.
    void fetch(`${base}/vision-execution/task-proposals`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: conversationId,
        source_message_id: messageId,
        block_index: e.blockIndex,
        proposal_index: e.proposalIndex,
        seat,
        title: e.proposal.title,
        parent_task_id: e.proposal.parent_task_id,
        timeframe_commitment: e.proposal.timeframe_commitment,
        due_date: e.proposal.due_date,
        notes: e.proposal.notes,
        // W1 (C-1, Q3): same evidence quote as the mount record.
        evidence_quote: precedingParagraph(content, e.blockIndex),
      }),
    }).then(async (r) => {
      if (r.ok) {
        const p = (await r.json()) as ServerProposal
        setRecords((prev) => ({ ...prev, [tripleKey(p)]: p }))
      } else if (r.status === 400) {
        setInvalidKeys((prev) => new Set(prev).add(e.key))
      } else {
        setFailedKeys((prev) => new Set(prev).add(e.key))
      }
    }).catch(() => setFailedKeys((prev) => new Set(prev).add(e.key)))
  }

  const act = async (e: ProposalEntry, kind: 'approve' | 'decline') => {
    const rec = records[e.key]
    if (!rec || busyKeys.has(e.key)) return
    setBusyKeys((prev) => new Set(prev).add(e.key))
    setActionError((prev) => {
      const next = { ...prev }
      delete next[e.key]
      return next
    })
    try {
      const r = await fetch(`${base}/vision-execution/task-proposals/${rec.id}/${kind}`, {
        method: 'POST',
        credentials: 'include',
      })
      if (r.ok) {
        if (kind === 'approve') {
          const data = (await r.json()) as { task: unknown; proposal: ServerProposal }
          setRecords((prev) => ({ ...prev, [e.key]: data.proposal }))
        } else {
          const p = (await r.json()) as ServerProposal
          setRecords((prev) => ({ ...prev, [e.key]: p }))
        }
      } else if (r.status === 409) {
        // Blocked approval (W1: e.g. the parent is no longer
        // available) or a state changed elsewhere: surface the
        // server's guidance, then refresh server state.
        let detail = 'This proposal can’t be approved right now — refresh to see its state.'
        try {
          const body = (await r.json()) as { detail?: unknown }
          if (typeof body?.detail === 'string' && body.detail) detail = body.detail
        } catch {
          /* keep the fallback */
        }
        setActionError((prev) => ({ ...prev, [e.key]: detail }))
        const list = await fetch(
          `${base}/vision-execution/task-proposals?conversation_id=${encodeURIComponent(conversationId)}`,
          { credentials: 'include' },
        )
        if (list.ok) {
          const data = (await list.json()) as { proposals: ServerProposal[] }
          setRecords((prev) => {
            const next = { ...prev }
            for (const p of data.proposals) next[tripleKey(p)] = p
            return next
          })
        }
      } else {
        setActionError((prev) => ({ ...prev, [e.key]: `Couldn’t ${kind} — try again.` }))
      }
    } catch {
      setActionError((prev) => ({ ...prev, [e.key]: `Couldn’t ${kind} — try again.` }))
    } finally {
      setBusyKeys((prev) => {
        const next = new Set(prev)
        next.delete(e.key)
        return next
      })
    }
  }

  const openEdit = (e: ProposalEntry) => {
    const rec = records[e.key]
    if (!rec) return
    setEditingKey(e.key)
    setEditTitle(rec.title)
    setEditTimeframe(rec.timeframe_commitment ?? '')
    setEditDue(rec.due_date ?? '')
    setEditParent(rec.parent_task_id ?? '')
    setParentOptions(null)
    void fetch(`${base}/vision-execution/tasks`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        if (Array.isArray(data)) {
          setParentOptions(
            data.map((t: { id: string; title: string }) => ({ id: t.id, title: t.title })),
          )
        }
      })
      .catch(() => setParentOptions([]))
  }

  const saveEdit = async (e: ProposalEntry) => {
    const rec = records[e.key]
    if (!rec || busyKeys.has(e.key)) return
    setBusyKeys((prev) => new Set(prev).add(e.key))
    try {
      const r = await fetch(`${base}/vision-execution/task-proposals/${rec.id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: editTitle.trim(),
          timeframe_commitment: editTimeframe || null,
          due_date: editDue.trim() || null,
          parent_task_id: editParent || null,
        }),
      })
      if (r.ok) {
        const p = (await r.json()) as ServerProposal
        setRecords((prev) => ({ ...prev, [e.key]: p }))
        setEditingKey(null)
      } else if (r.status === 409) {
        setActionError((prev) => ({ ...prev, [e.key]: 'Already decided — refresh to see its state.' }))
        setEditingKey(null)
      } else {
        setActionError((prev) => ({ ...prev, [e.key]: 'Couldn’t save the edit — try again.' }))
      }
    } catch {
      setActionError((prev) => ({ ...prev, [e.key]: 'Couldn’t save the edit — try again.' }))
    } finally {
      setBusyKeys((prev) => {
        const next = new Set(prev)
        next.delete(e.key)
        return next
      })
    }
  }

  if (entries.length === 0) return null

  return (
    <div className="max-w-[88%] w-full space-y-2">
      {entries.map((e) => {
        const rec = records[e.key]
        const invalid = !e.valid || invalidKeys.has(e.key)
        const failed = failedKeys.has(e.key) && !rec
        const busy = busyKeys.has(e.key)
        const title = rec?.title ?? e.proposal?.title ?? 'Proposed task'
        const timeframe = rec?.timeframe_commitment ?? e.proposal?.timeframe_commitment ?? null
        const due = rec?.due_date ?? e.proposal?.due_date ?? null
        return (
          <div
            key={e.key}
            className="rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2 text-sm"
          >
            {invalid ? (
              <p className="text-red-300">
                Couldn&apos;t read this proposal — ask Firebrand to restate it.
              </p>
            ) : failed ? (
              <div className="space-y-2">
                <p className="text-stone-300">Couldn&apos;t record this proposal.</p>
                <button
                  type="button"
                  onClick={() => retryRecord(e)}
                  className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800"
                >
                  Retry
                </button>
              </div>
            ) : rec?.state === 'approved' ? (
              <div className="space-y-1">
                <p className="text-emerald-200">
                  Created: {title}
                  {rec.created_task_id ? <span className="text-stone-400"> ({rec.created_task_id})</span> : null}
                </p>
                {/* W1: the original proposal, as recorded — never live
                    values presented as originals. Pre-W1 rows have no
                    snapshot at all. Shown only when the original
                    differs from the created title. */}
                {rec.original_title == null ? (
                  <p className="text-xs text-stone-400">
                    Original proposal not recorded (pre-snapshot)
                  </p>
                ) : rec.original_title !== title ? (
                  <p className="text-xs text-stone-400">
                    Original proposal: {rec.original_title}
                  </p>
                ) : null}
              </div>
            ) : rec?.state === 'declined' ? (
              <p className="text-stone-400">Declined: {title}</p>
            ) : editingKey === e.key ? (
              <div className="space-y-2">
                <input
                  aria-label="Proposal title"
                  className="w-full rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                  value={editTitle}
                  onChange={(ev) => setEditTitle(ev.target.value)}
                />
                <div className="flex flex-wrap gap-2">
                  <label className="text-xs text-stone-400">
                    Timeframe{' '}
                    <select
                      aria-label="Proposal timeframe"
                      className="rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                      value={editTimeframe}
                      onChange={(ev) => setEditTimeframe(ev.target.value)}
                    >
                      <option value="">Unspecified</option>
                      <option value="tentative">Tentative</option>
                    </select>
                  </label>
                  <label className="text-xs text-stone-400">
                    Due date{' '}
                    <input
                      aria-label="Proposal due date"
                      className="rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                      value={editDue}
                      onChange={(ev) => setEditDue(ev.target.value)}
                      placeholder="YYYY-MM-DD"
                    />
                  </label>
                  <label className="text-xs text-stone-400">
                    Under{' '}
                    <select
                      aria-label="Proposal parent task"
                      className="rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                      value={editParent}
                      onChange={(ev) => setEditParent(ev.target.value)}
                    >
                      <option value="">Top-level</option>
                      {(parentOptions ?? []).map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.title || t.id}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy || !editTitle.trim()}
                    onClick={() => void saveEdit(e)}
                    className="px-2 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium"
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingKey(null)}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-stone-100 font-medium">{title}</p>
                <p className="text-xs text-stone-400">
                  {timeframe === 'tentative' ? 'Tentative timeframe' : 'Unspecified timeframe'}
                  {due ? ` · due ${due}` : ' · no date yet'}
                </p>
                {/* W1: the exact quote the card's approval rests on,
                    with its lexical-correspondence label. Never
                    "verified" or "confirmed" — the quote proves the
                    words appeared, not what they mean. */}
                {rec?.evidence_quote ? (
                  <div className="space-y-1">
                    <p className="text-xs text-stone-400">
                      Verbatim words from the proposing turn:
                    </p>
                    <p className="text-xs text-stone-300 italic">
                      &ldquo;{rec.evidence_quote}&rdquo;
                    </p>
                    {rec.grounding_flag === 'words_matched' ? (
                      <p className="text-xs text-stone-400">
                        Words matched — all significant title words appear in the quote
                      </p>
                    ) : rec.grounding_flag === 'summarized' ? (
                      <p className="text-xs text-stone-400">
                        Summarized — the title uses wording beyond the quote
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {/* W1: parent line — title (+ recorded status when
                    terminal), or "no longer available" when the
                    parent id is absent from the fetched task list.
                    The server remains authoritative (approve 409s). */}
                {rec?.parent_task_id && tasksById ? (
                  tasksById[rec.parent_task_id] ? (
                    <p className="text-xs text-stone-400">
                      Under: {tasksById[rec.parent_task_id].title}
                      {isTerminalStatus(tasksById[rec.parent_task_id].status)
                        ? ` — ${tasksById[rec.parent_task_id].status}`
                        : ''}
                    </p>
                  ) : (
                    <p className="text-xs text-amber-300">Parent task no longer available</p>
                  )
                ) : null}
                {actionError[e.key] && <p className="text-xs text-red-300">{actionError[e.key]}</p>}
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={!rec || busy}
                    title={!rec ? 'Recording proposal…' : undefined}
                    onClick={() => void act(e, 'approve')}
                    className="px-2 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={!rec || busy}
                    onClick={() => openEdit(e)}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    disabled={!rec || busy}
                    onClick={() => void act(e, 'decline')}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
                  >
                    Decline
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
