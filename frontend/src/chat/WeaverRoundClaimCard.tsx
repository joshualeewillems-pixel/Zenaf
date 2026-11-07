/**
 * Round card for the one impression Weaver presented in a rapid
 * fire round.
 *
 * Contract (Weaver S1, brief §§5, 7, 12): the round item arrives
 * from the server — the turn response carries the claim + its
 * deterministic rendering, hydration refetches the claim by id —
 * and card STATE comes from the server record, never client memory.
 * On mount the card reads GET /agents/{agent_id}/claims and renders
 * the claim's state: pending → the five verdict actions + "I need
 * to check" (park); decided → the verdict label + "Ruled. Weaver
 * will bring the next one when you reply."
 *
 * Confirmation is a distinct step (brief §5.1): tapping an action
 * never posts. For Keep it / It's wrong / Leave it open the tap
 * opens a confirmation panel stating the action, the verbatim
 * original (attributed — never the gloss), and the
 * training-consequence sentence; Confirm posts to the existing
 * verdict endpoint, Cancel writes nothing. For Fix the wording /
 * Say why it's right the tap first opens the note field (the
 * existing ClaimCard tap-then-text pattern, pre-filled from a
 * ```correction-draft fence when Weaver drafted one); the
 * confirmation panel appears when the user taps Submit on the note.
 * Prose assent never writes — only a tap posts. The tap itself
 * sends no turn: the next user message advances the round.
 *
 * Park is visibly distinct from Leave it open: a park leaves the
 * claim pending and returns it next round; Leave it open is a
 * verdict (recorded, no training weight) that never returns it.
 */
import { useEffect, useState } from 'react'
import type { Claim } from '../agent-intake/ClaimCard'
import {
  ACTION_LABEL,
  confirmationCopy,
  parseCorrectionDraft,
  STATUS_LABEL,
  type RoundAction,
  type WeaverRoundItem,
} from './weaverRound'

type Props = {
  base: string
  conversationId: string
  messageId: string
  roundItem: WeaverRoundItem
  /** The raw reply text this card rides on — the correction-draft
   *  fence is parsed from it, not from the rendering. */
  messageContent: string
}

const CONFLICT_COPY =
  "This one was already decided elsewhere — in your Review, for example — so nothing was written here. It's no longer pending."

function outcomeLineFromClaim(claim: Claim): string | null {
  for (const line of (claim.detail || '').split('\n')) {
    if (line.trim().startsWith('Read-back outcome:')) return line.trim()
  }
  return null
}

export default function WeaverRoundClaimCard({
  base,
  conversationId,
  messageId,
  roundItem,
  messageContent,
}: Props) {
  const claimId = roundItem.claim_id
  const agentId = roundItem.agent_id
  const rendering = roundItem.rendering
  const [claim, setClaim] = useState<Claim | null>(null)
  const [parked, setParked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'idle' | 'correct' | 'explain'>('idle')
  const [note, setNote] = useState('')
  const [confirming, setConfirming] = useState<RoundAction | null>(null)

  const claimsUrl = `${base}/agents/${encodeURIComponent(agentId)}/claims`

  const refreshClaim = async () => {
    try {
      const r = await fetch(claimsUrl, { credentials: 'include' })
      if (!r.ok) return
      const data = (await r.json()) as Claim[]
      if (!Array.isArray(data)) return
      const found = data.find((c) => c.id === claimId)
      if (found) setClaim(found)
    } catch {
      /* refresh failure is non-fatal: the card keeps its last state */
    }
  }

  useEffect(() => {
    let cancelled = false
    // Hydration: server state first, so reload never reverts a
    // decision — and never reverts a park either.
    void fetch(claimsUrl, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !Array.isArray(data)) return
        const found = (data as Claim[]).find((c) => c.id === claimId)
        if (found) setClaim(found)
      })
      .catch(() => {
        /* claim-fetch failure is non-fatal: the turn's rendering stands */
      })
    return () => {
      cancelled = true
    }
    // Intentionally not depending on claim: the mount fetch covers
    // hydration; actions refresh explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, agentId, claimId])

  const readDetail = async (r: Response): Promise<string | null> => {
    try {
      const body = (await r.json()) as { detail?: unknown }
      if (typeof body?.detail === 'string' && body.detail) return body.detail
    } catch {
      /* fall through to the generic message */
    }
    return null
  }

  const postVerdict = async (action: RoundAction, noteText: string) => {
    setBusy(true)
    setError(null)
    try {
      const needsNote = action === 'correct' || action === 'explain'
      const r = await fetch(
        `${base}/agents/${encodeURIComponent(agentId)}/claims/${encodeURIComponent(claimId)}/${action}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          ...(needsNote ? { body: JSON.stringify({ note: noteText }) } : {}),
        },
      )
      if (r.ok) {
        const updated = (await r.json()) as Claim
        setClaim(updated)
        setConfirming(null)
        setMode('idle')
        setNote('')
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? CONFLICT_COPY)
        setConfirming(null)
        await refreshClaim()
      } else {
        setError(`Couldn't rule on this one — try again.`)
      }
    } catch {
      setError(`Couldn't rule on this one — try again.`)
    } finally {
      setBusy(false)
    }
  }

  const onAct = (action: RoundAction) => {
    if (action === 'correct' || action === 'explain') {
      // Tap-then-text: open the note field, pre-filled from
      // Weaver's correction draft when she wrote one. Nothing is
      // posted yet — the confirmation panel appears on Submit.
      setMode(action)
      setNote(parseCorrectionDraft(messageContent) ?? '')
      return
    }
    setConfirming(action)
  }

  const submitNote = () => {
    if (mode === 'idle') return
    setConfirming(mode)
  }

  const skip = async () => {
    if (busy) return
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
          claim_id: claimId,
        }),
      })
      if (r.ok) {
        setParked(true)
      } else if (r.status === 409) {
        setError((await readDetail(r)) ?? CONFLICT_COPY)
        await refreshClaim()
      } else {
        setError(`Couldn't park this one — try again.`)
      }
    } catch {
      setError(`Couldn't park this one — try again.`)
    } finally {
      setBusy(false)
    }
  }

  // The verbatim original, from the server's deterministic rendering
  // when the turn carried it; the fetched claim's own fields when
  // the card hydrated from markers. Either way the card shows the
  // record's words, never a gloss, and the verdict targets the
  // claim id.
  const impression = rendering?.impression || claim?.inference || ''
  const evidence = rendering?.evidence || claim?.evidence || ''
  const outcomeLine = rendering?.outcome_line || (claim ? outcomeLineFromClaim(claim) : null)
  const seatName = rendering?.seat_name || ''
  const seatRole = rendering?.seat_role || ''
  const visitorResponse =
    rendering?.visitor_response || claim?.readback_visitor_response || ''
  const originalClaim = rendering?.original_claim || claim?.readback_original_claim || ''
  const status = claim?.status ?? rendering?.status ?? 'pending'
  const resolved = status !== 'pending'
  const verdictLabel = resolved ? (STATUS_LABEL[status] ?? status) : null

  return (
    <div className="max-w-[88%] w-full space-y-2">
      <div className="rounded-2xl border border-stone-700/60 bg-stone-900/70 px-3 py-2 text-sm">
        <p className="text-[11px] uppercase tracking-wide text-stone-500">Rapid fire</p>
        {resolved && claim ? (
          <div className="space-y-1">
            <p className="text-emerald-200">
              Ruled. {verdictLabel}.
            </p>
            <p className="text-xs text-stone-400">
              Weaver will bring the next one when you reply.
            </p>
            {claim.user_note ? (
              <p className="text-xs text-stone-300 italic">&ldquo;{claim.user_note}&rdquo;</p>
            ) : null}
            {status === 'unresolved' ? (
              <p className="text-xs text-stone-400">
                You left it open — recorded as undecided, with no training weight.
              </p>
            ) : null}
          </div>
        ) : (
          <div className="space-y-2">
            {parked && (
              <p className="text-xs text-amber-300">
                Parked — still pending, it&apos;ll come back next round.
              </p>
            )}
            {seatName ? (
              <p className="text-stone-100 font-medium">
                The {seatName}&apos;s first impression of you
                {seatRole ? ` (${seatRole})` : ''}
              </p>
            ) : (
              <p className="text-stone-100 font-medium">First impression</p>
            )}
            {impression ? (
              <p className="text-stone-200 whitespace-pre-wrap">&ldquo;{impression}&rdquo;</p>
            ) : (
              <p className="text-stone-400">Loading this impression…</p>
            )}
            {originalClaim && originalClaim !== impression ? (
              <p className="text-xs text-stone-400">
                As first offered: &ldquo;{originalClaim}&rdquo;
              </p>
            ) : null}
            {evidence ? (
              <div className="space-y-1">
                <p className="text-xs text-stone-400">Your answer, word for word:</p>
                <p className="text-xs text-stone-300 italic whitespace-pre-wrap">
                  &ldquo;{evidence}&rdquo;
                </p>
              </div>
            ) : null}
            {outcomeLine ? <p className="text-xs text-stone-400">{outcomeLine}</p> : null}
            {visitorResponse === 'unresolved' ? (
              <p className="text-xs text-stone-400">
                Your response to the read-back was unresolved — you neither agreed nor
                disputed it.
              </p>
            ) : null}
            {error && <p className="text-xs text-red-300">{error}</p>}
            {confirming && claim ? (
              <div className="space-y-2 rounded-xl border border-yellow-500/40 bg-stone-800/60 px-3 py-2">
                <p className="text-stone-100 font-medium">
                  {ACTION_LABEL[confirming]} — are you sure?
                </p>
                <p className="text-xs text-stone-300 whitespace-pre-wrap">
                  &ldquo;{impression}&rdquo;
                </p>
                <p className="text-xs text-stone-300">{confirmationCopy(confirming, claim)}</p>
                {(confirming === 'correct' || confirming === 'explain') && note ? (
                  <p className="text-xs text-stone-300 italic whitespace-pre-wrap">
                    Your note: &ldquo;{note}&rdquo;
                  </p>
                ) : null}
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void postVerdict(confirming, note.trim())}
                    className="px-2 py-1 rounded-lg bg-yellow-500/90 hover:bg-yellow-500 disabled:opacity-50 text-stone-900 text-xs font-medium"
                  >
                    Confirm
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirming(null)}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : mode !== 'idle' ? (
              <div className="space-y-2">
                <p className="text-xs text-stone-400">
                  {mode === 'correct'
                    ? 'How would you qualify it? Your refinement teaches the system.'
                    : 'Why did you make that call? Your reasoning becomes training signal.'}
                </p>
                <textarea
                  aria-label={mode === 'correct' ? 'Correction note' : 'Explanation note'}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={3}
                  placeholder={mode === 'correct' ? 'More precisely…' : 'I chose this because…'}
                  className="w-full min-h-[44px] px-3 py-2 rounded-xl bg-stone-900 text-stone-100 text-[15px] border border-stone-700 focus:border-yellow-500/60 outline-none resize-y"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={submitNote}
                    disabled={busy || !note.trim()}
                    className="px-2 py-1 rounded-lg bg-yellow-500/90 hover:bg-yellow-500 disabled:opacity-50 text-stone-900 text-xs font-medium"
                  >
                    {mode === 'correct' ? 'Submit qualification' : 'Save explanation'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMode('idle')
                      setNote('')
                    }}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onAct('accept')}
                    className="px-2 py-1 rounded-lg bg-yellow-500/90 hover:bg-yellow-500 disabled:opacity-50 text-stone-900 text-xs font-medium"
                  >
                    Keep it
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onAct('correct')}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
                  >
                    Fix the wording
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onAct('explain')}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
                  >
                    Say why it&apos;s right
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onAct('reject')}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
                  >
                    It&apos;s wrong
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onAct('unresolve')}
                    className="px-2 py-1 rounded-lg border border-stone-600 text-stone-200 text-xs hover:bg-stone-800 disabled:opacity-50"
                  >
                    Leave it open
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
                </div>
                <p className="text-[11px] text-stone-500">
                  Tap to rule on this one. Weaver will bring the next one when you reply —
                  nothing happens until then.
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
