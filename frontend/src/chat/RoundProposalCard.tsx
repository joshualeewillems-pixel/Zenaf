/**
 * Round card for the one item Firebrand presented in a lightning round.
 *
 * Contract (Firebrand S1): the round item arrives from the server —
 * the turn response carries the proposal, hydration refetches it by
 * id — and card STATE comes from the server record, never client
 * memory. On mount the card reads GET /conversation/round/item-state
 * (proposal + parked/reserved state — the parked/reserved state
 * lives in the round tables, not on the proposal record, so the
 * bare proposal read cannot show it) and renders each record's
 * state: pending → Approve / Edit / Decline + "I need to check"
 * (park) + "Don't remind me" (reserve); approved → Created;
 * declined → Declined; parked → the parked line above the pending
 * card (a park suppresses re-presentation, not the decision);
 * reserved → the reserved line + Undo, no decide buttons (the user
 * said "don't remind me" — the card must not keep reminding them).
 * Prose assent never writes — only a tap posts, and approval is
 * the only path from proposal to task. The tap itself sends no
 * turn: the next user message advances the round.
 */
import { useEffect, useState } from 'react'
import type { ServerProposal } from './TaskProposalCards'

export type RoundItem = {
  kind: string
  proposal_id: string
  proposal?: ServerProposal
}

type Props = {
  base: string
  conversationId: string
  messageId: string
  roundItem: RoundItem
}

type TaskOption = { id: string; title: string }

type ReservedMarker = { snooze_until: string | null }

// W1: display-only terminal check for the parent line (same word
// list as the server's parent-availability check). The server
// remains authoritative — approval still returns 409 for a terminal
// parent even if this display ever disagrees.
const TERMINAL_STATUS_RE = /\b(done|complete|completed|shipped|closed|won)\b/i
function isTerminalStatus(status: string | null | undefined): boolean {
  if (!status) return false
  return TERMINAL_STATUS_RE.test(status) || status.trim().toLowerCase() === 'dropped'
}

export default function RoundProposalCard({ base, conversationId, messageId, roundItem }: Props) {
  const proposalId = roundItem.proposal_id
  const [rec, setRec] = useState<ServerProposal | null>(roundItem.proposal ?? null)
  const [parked, setParked] = useState(false)
  const [reserved, setReserved] = useState<ReservedMarker | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editTimeframe, setEditTimeframe] = useState('')
  const [editDue, setEditDue] = useState('')
  const [editParent, setEditParent] = useState('')
  const [parentOptions, setParentOptions] = useState<TaskOption[] | null>(null)
  const [tasksById, setTasksById] = useState<Record<
    string,
    { title: string; status: string }
  > | null>(null)
  // OQ7: the duration is the user's pick — 1 day, 1 week, or never.
  const [reserveDays, setReserveDays] = useState<'1' | '7' | 'never'>('7')

  const stateUrl =
    `${base}/conversation/round/item-state?conversation_id=${encodeURIComponent(conversationId)}` +
    `&message_id=${encodeURIComponent(messageId)}&proposal_id=${encodeURIComponent(proposalId)}`

  const refresh = async () => {
    try {
      const r = await fetch(stateUrl, { credentials: 'include' })
      if (!r.ok) return
      const data = (await r.json()) as {
        proposal: ServerProposal
        parked: boolean
        reserved: ReservedMarker | null
      }
      if (!data.proposal) return
      setRec(data.proposal)
      setParked(data.parked)
      setReserved(data.reserved)
    } catch {
      /* refresh failure is non-fatal: the card keeps its last state */
    }
  }

  useEffect(() => {
    let cancelled = false
    // Hydration: server state first, so reload never reverts a
    // decision — and never reverts a park or a reserve either.
    void fetch(stateUrl, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data || !data.proposal) return
        setRec(data.proposal as ServerProposal)
        setParked(Boolean(data.parked))
        setReserved((data.reserved as ReservedMarker | null) ?? null)
      })
      .catch(() => {
        /* item-state failure is non-fatal: the turn's proposal stands */
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
    return () => {
      cancelled = true
    }
    // Intentionally not depending on rec: the mount fetch covers
    // hydration; actions refresh explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, conversationId, messageId, proposalId])

  const readDetail = async (r: Response): Promise<string | null> => {
    try {
      const body = (await r.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string' && body.detail) return body.detail
    } catch {
      /* fall through to the generic message */
    }
    return null
  }

  const act = async (kind: 'approve' | 'decline') => {
    if (!rec || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${base}/vision-execution/task-proposals/${rec.id}/${kind}`, {
        method: 'POST',
        credentials: 'include',
      })
      if (r.ok) {
        if (kind === 'approve') {
          const data = (await r.json()) as { task: unknown; proposal: ServerProposal }
          setRec(data.proposal)
        } else {
          setRec((await r.json()) as ServerProposal)
        }
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? 'Already decided — refresh to see its state.')
        await refresh()
      } else {
        setError(`Couldn’t ${kind} — try again.`)
      }
    } catch {
      setError(`Couldn’t ${kind} — try again.`)
    } finally {
      setBusy(false)
    }
  }

  const openEdit = () => {
    if (!rec) return
    setEditing(true)
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

  const saveEdit = async () => {
    if (!rec || busy) return
    setBusy(true)
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
        setRec((await r.json()) as ServerProposal)
        setEditing(false)
      } else if (r.status === 409) {
        setError('Already decided — refresh to see its state.')
        setEditing(false)
        await refresh()
      } else {
        setError('Couldn’t save the edit — try again.')
      }
    } catch {
      setError('Couldn’t save the edit — try again.')
    } finally {
      setBusy(false)
    }
  }

  const skip = async () => {
    if (!rec || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${base}/conversation/round/skip`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          message_id: messageId,
          proposal_id: proposalId,
        }),
      })
      if (r.ok) {
        setParked(true)
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? 'Already decided — refresh to see its state.')
        await refresh()
      } else {
        setError('Couldn’t park this one — try again.')
      }
    } catch {
      setError('Couldn’t park this one — try again.')
    } finally {
      setBusy(false)
    }
  }

  const reserve = async () => {
    if (!rec || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${base}/conversation/round/reserve`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          message_id: messageId,
          proposal_id: proposalId,
          snooze_days: reserveDays === 'never' ? null : Number(reserveDays),
        }),
      })
      if (r.ok) {
        const data = (await r.json()) as { marker: ReservedMarker }
        setReserved(data.marker)
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? 'Already decided — refresh to see its state.')
        await refresh()
      } else {
        setError('Couldn’t set that — try again.')
      }
    } catch {
      setError('Couldn’t set that — try again.')
    } finally {
      setBusy(false)
    }
  }

  const unreserve = async () => {
    if (!rec || busy) return
    setBusy(true)
    setError(null)
    try {
      const r = await fetch(`${base}/conversation/round/unreserve`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          message_id: messageId,
          proposal_id: proposalId,
        }),
      })
      if (r.ok) {
        setReserved(null)
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? 'Already decided — refresh to see its state.')
        await refresh()
      } else {
        setError('Couldn’t undo that — try again.')
      }
    } catch {
      setError('Couldn’t undo that — try again.')
    } finally {
      setBusy(false)
    }
  }

  const title = rec?.title ?? 'Proposed task'
  const timeframe = rec?.timeframe_commitment ?? null
  const due = rec?.due_date ?? null

  return (
    <div className="max-w-[88%] w-full space-y-2">
      <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2 text-sm">
        <p className="text-[11px] uppercase tracking-wide text-stone-500">Lightning round</p>
        {!rec ? (
          <p className="text-stone-400">Loading this item…</p>
        ) : rec.state === 'approved' ? (
          <div className="space-y-1">
            <p className="text-emerald-200">
              Created: {title}
              {rec.created_task_id ? <span className="text-stone-400"> ({rec.created_task_id})</span> : null}
            </p>
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
        ) : rec.state === 'declined' ? (
          <p className="text-stone-400">Declined: {title}</p>
        ) : reserved ? (
          <div className="space-y-2">
            <p className="text-stone-300">
              Won&apos;t remind you about this one
              {reserved.snooze_until
                ? ` — back after ${reserved.snooze_until.slice(0, 10)}.`
                : ' — never.'}
            </p>
            <p className="text-xs text-stone-400">{title}</p>
            <button
              type="button"
              disabled={busy}
              onClick={() => void unreserve()}
              className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
            >
              Undo
            </button>
            {error && <p className="text-xs text-red-300">{error}</p>}
          </div>
        ) : editing ? (
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
                onClick={() => void saveEdit()}
                className="px-2 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {parked && (
              <p className="text-xs text-amber-300">
                Parked — it&apos;ll come back next round.
              </p>
            )}
            <p className="text-stone-100 font-medium">{title}</p>
            <p className="text-xs text-stone-400">
              {timeframe === 'tentative' ? 'Tentative timeframe' : 'Unspecified timeframe'}
              {due ? ` · due ${due}` : ' · no date yet'}
            </p>
            {rec.evidence_quote ? (
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
            {rec.parent_task_id && tasksById ? (
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
            {error && <p className="text-xs text-red-300">{error}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void act('approve')}
                className="px-2 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-medium"
              >
                Approve
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => openEdit()}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
              >
                Edit
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void act('decline')}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
              >
                Decline
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void skip()}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
              >
                I need to check
              </button>
              <label className="text-xs text-stone-400">
                Don&apos;t remind me for{' '}
                <select
                  aria-label="Don't remind me for"
                  className="rounded-lg bg-stone-800 border border-stone-700 px-2 py-1 text-stone-100"
                  value={reserveDays}
                  onChange={(ev) =>
                    setReserveDays(ev.target.value as '1' | '7' | 'never')
                  }
                >
                  <option value="1">1 day</option>
                  <option value="7">1 week</option>
                  <option value="never">Never</option>
                </select>
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() => void reserve()}
                className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
              >
                Don&apos;t remind me
              </button>
            </div>
            <p className="text-[11px] text-stone-500">
              Tap to rule on this one. Firebrand brings the next one when you reply — nothing
              happens until then.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
