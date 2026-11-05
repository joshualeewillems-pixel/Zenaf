import { useEffect, useRef, useState } from 'react'
import { apiBase } from '../apiBase'
import { useSeatMeta } from './SeatChips'

/** Cross-component signal: a refetch dropped a previously present
    invitation row (joined via a completed turn, or expired/cleared —
    absence is absence; the signal carries no claim about which). The
    Tree listens and refetches attention so its indicator stays fresh.
    Its only effect is a data refresh: never navigation, never a state
    transition. Follows the OPEN_SEAT_REVIEW_EVENT precedent. */
export const INVITATIONS_CHANGED_EVENT = 'zenaf:invitations-changed'

/**
 * Conversation-scoped invitation list (Capability C visible-UX slice).
 *
 * Backend truth only: rows come from GET /conversation/invitations for
 * this conversation, pending + unexpired. Opening an invitation NEVER
 * consumes it — expand/collapse is UI-local display state, never
 * persisted, never sent, and there is no accept endpoint to call.
 * Joining happens only when the user sends a turn to the invited seat;
 * the list observes that by refetching (the accepted row disappears).
 *
 * No mutation, no timer, no polling. Refetch happens on mount, on
 * conversation change, on refreshKey bump (after a completed turn),
 * and on explicit Retry — nothing else.
 *
 * Evidence is verbatim or absent: stored strings render as-is, never
 * paraphrased or completed. Reason + attribution travel together in
 * the detail view (Q5: an interpretation is never presented as fact).
 */

/** Stock fellowship names for evidence attribution (the backend join
    block's convention). The INVITING seat uses useSeatMeta names
    (honors renames); the RESPONDING seat inside evidence uses these
    stock names, or the raw id — never confuse the two. */
const STOCK_NAMES: Record<string, string> = {
  mentor: 'The Gardener',
  champion: 'The Firebrand',
  guardian: 'The Bear',
  maverick: 'The Fox',
  ambassador: 'The Crane',
  conductor: 'The Weaver',
  skeptic: 'The Raven',
}

export type InvitationItem = {
  id: string
  conversation_id: string
  seat: string
  reason: string
  reason_attribution?: string
  evidence?: Record<string, unknown>
  status: string
  created_at: string
  expires_at: string
}

function asText(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 ? v : null
}

/** Row snippet: first ~200 chars of the user message, else the
    assistant reply, else none — never invented. */
function snippet(ev: Record<string, unknown> | undefined): string | null {
  if (!ev) return null
  const user = asText(ev.user_message)
  if (user) return user.slice(0, 200)
  const reply = asText(ev.assistant_reply)
  if (reply) return reply.slice(0, 200)
  return null
}

/** Context entries render as `role: content` lines. Strings render
    as-is; {role, content} dicts render with their role; unreadable
    entries are skipped, never stringified. */
function contextLines(ev: Record<string, unknown> | undefined): string[] {
  if (!ev || !Array.isArray(ev.context)) return []
  const lines: string[] = []
  for (const entry of ev.context as unknown[]) {
    if (typeof entry === 'string') {
      if (entry) lines.push(entry)
      continue
    }
    if (entry && typeof entry === 'object') {
      const content = asText((entry as Record<string, unknown>).content)
      if (!content) continue
      const role = asText((entry as Record<string, unknown>).role)
      lines.push(role ? `${role}: ${content}` : content)
    }
  }
  return lines
}

function formatWhen(iso: string | null | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return ''
  }
}

export default function InvitationList({
  conversationId,
  onInviteSelected,
  refreshKey,
  onRowDisappeared,
}: {
  conversationId: string
  /** The user tapped "talk to this seat": make that seat active. This
      does NOT accept anything — acceptance happens only when a turn
      to that seat is sent. */
  onInviteSelected: (seat: string) => void
  /** Bump to refetch (TreeTalkSheet bumps this after a completed turn). */
  refreshKey: number
  /** Invoked when a refetch drops a row that was present before
      (joined, expired, or cleared — absence is absence). The sheet
      uses it to signal the Tree to refetch attention. */
  onRowDisappeared?: () => void
}) {
  const base = apiBase()
  const { names } = useSeatMeta()
  const [mode, setMode] = useState<'loading' | 'ready' | 'error' | 'signedout'>('loading')
  const [items, setItems] = useState<InvitationItem[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const prevIdsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    setMode('loading')
    fetch(
      `${base}/conversation/invitations?conversation_id=${encodeURIComponent(conversationId)}`,
      { credentials: 'include' },
    )
      .then(async (r) => {
        if (r.status === 401) return { auth: true as const }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return (await r.json()) as { invitations?: unknown }
      })
      .then((data) => {
        if (cancelled) return
        if ((data as { auth?: boolean }).auth) {
          setMode('signedout')
          return
        }
        const list = (data as { invitations?: unknown }).invitations
        if (!Array.isArray(list)) throw new Error('malformed invitations payload')
        // A row that was present and is now gone was joined, expired,
        // or cleared — ordinary, not failure. Signal the disappearance
        // (the Tree refetches attention) and collapse its detail.
        const nextIds = new Set((list as InvitationItem[]).map((i) => i.id))
        const prevIds = prevIdsRef.current
        if (prevIds.size > 0 && [...prevIds].some((id) => !nextIds.has(id))) {
          onRowDisappeared?.()
        }
        prevIdsRef.current = nextIds
        setItems(list as InvitationItem[])
        // An open detail collapses silently when its row disappears
        // (accepted, expired, or cleared) — expiry is ordinary, not
        // a failure, so there is no error surface for it.
        setExpandedId((prev) =>
          prev && (list as InvitationItem[]).some((i) => i.id === prev) ? prev : null,
        )
        setMode('ready')
      })
      .catch(() => {
        if (!cancelled) setMode('error')
      })
    return () => {
      cancelled = true
    }
  }, [base, conversationId, refreshKey, nonce, onRowDisappeared])

  if (!conversationId) return null

  if (mode === 'loading') {
    return <p className="text-sm text-stone-400 px-1 py-2">Loading invitations…</p>
  }

  if (mode === 'signedout') {
    return <p className="text-sm text-stone-400 px-1 py-2">Please sign in to see invitations.</p>
  }

  if (mode === 'error') {
    return (
      <div className="rounded-2xl border border-red-800/60 bg-red-950/30 px-3 py-2 text-sm text-red-200">
        Couldn&apos;t load invitations.
        <button
          type="button"
          onClick={() => setNonce((n) => n + 1)}
          className="ml-2 underline font-medium"
        >
          Retry
        </button>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <p className="text-sm text-stone-400 px-1 py-2">
        No pending invitations in this conversation.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      {items.map((item) => {
        const seatName = names[item.seat] ?? item.seat
        const expanded = expandedId === item.id
        const ev = item.evidence
        const userMessage = ev ? asText(ev.user_message) : null
        const assistantReply = ev ? asText(ev.assistant_reply) : null
        const respondingSeat = ev ? asText(ev.responding_seat) : null
        const respondingName = respondingSeat
          ? (STOCK_NAMES[respondingSeat] ?? respondingSeat)
          : 'Voice'
        const ctx = contextLines(ev)
        const hasEvidence =
          userMessage !== null || assistantReply !== null || ctx.length > 0
        const rowSnippet = snippet(ev)
        return (
          <div
            key={item.id}
            className="rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2"
          >
            <button
              type="button"
              onClick={() => setExpandedId(expanded ? null : item.id)}
              aria-expanded={expanded}
              className="text-left w-full"
            >
              <span className="block text-sm text-stone-200">{seatName}</span>
              <span className="block text-xs text-stone-400">{item.reason}</span>
              {rowSnippet && (
                <span className="block text-xs text-stone-500 truncate">{rowSnippet}</span>
              )}
            </button>
            {expanded && (
              <div className="mt-2 flex flex-col gap-2 border-t border-stone-700/60 pt-2">
                <p className="text-sm text-stone-200">{item.reason}</p>
                {item.reason_attribution && (
                  <p className="text-xs text-stone-500">{item.reason_attribution}</p>
                )}
                {hasEvidence ? (
                  <div className="flex flex-col gap-1 text-sm">
                    {userMessage && (
                      <p className="text-stone-300">
                        <span className="text-stone-500">You: </span>
                        {userMessage}
                      </p>
                    )}
                    {assistantReply && (
                      <p className="text-stone-300">
                        <span className="text-stone-500">{respondingName}: </span>
                        {assistantReply}
                      </p>
                    )}
                    {ctx.map((line, i) => (
                      <p key={i} className="text-xs text-stone-400">
                        {line}
                      </p>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-stone-500">
                    No justifying exchange was stored with this invitation.
                  </p>
                )}
                <p className="text-[11px] text-stone-500">
                  {formatWhen(item.created_at)
                    ? `Invited ${formatWhen(item.created_at)}`
                    : ''}
                  {formatWhen(item.expires_at)
                    ? ` · Expires ${formatWhen(item.expires_at)}`
                    : ''}
                </p>
                <p className="text-xs text-stone-500">
                  Opening this invitation does not consume it — it stays here until you
                  send a turn to this seat.
                </p>
                <button
                  type="button"
                  onClick={() => onInviteSelected(item.seat)}
                  className="self-start min-h-[44px] px-4 rounded-full border border-stone-700 text-sm text-stone-300"
                >
                  Talk to {seatName}
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
