/**
 * Weaver rapid fire S1 — pure helpers for the round claim card.
 *
 * No fetch, no React. The confirmation copy is the brief §5.2
 * wording AS WRITTEN (SQ1: the founder accepted the copy as
 * written — he did not choose the shortening — so the amendment-4
 * sentence keeps its full second half, including the deferral).
 * Each sentence is computed from the action + the claim's
 * readback_visitor_response + claim_type, using the same predicate
 * the server-side amendment-4 gate uses, so the client copy and the
 * server behavior cannot disagree about which case applies.
 *
 * The correction-draft fence and the [[round-offer]] marker follow
 * the task-proposal fence precedent (taskProposals.ts): the model
 * puts a proposed correction in a fenced block at the end of her
 * reply; the frontend parses the fence, strips it from display, and
 * pre-fills the note field. The draft is editable; only the user's
 * tap on Submit + Confirm writes anything.
 */
import type { Claim } from '../agent-intake/ClaimCard'

export type WeaverRoundItem = {
  kind: 'meeting_impression'
  agent_id: string
  claim_id: string
  claim_type: string
  rendering?: {
    agent_id: string
    claim_id: string
    claim_type: string
    seat_name: string
    seat_role: string
    impression: string
    evidence: string
    outcome_line: string
    visitor_response: string
    seat_outcome: string
    original_claim: string
    status: string
  }
}

export type RoundAction = 'accept' | 'correct' | 'explain' | 'reject' | 'unresolve'

export const ACTION_LABEL: Record<RoundAction, string> = {
  accept: 'Keep it',
  correct: 'Fix the wording',
  explain: "Say why it's right",
  reject: "It's wrong",
  unresolve: 'Leave it open',
}

export const ACTION_VERB: Record<RoundAction, string> = {
  accept: 'accepted',
  correct: 'corrected',
  explain: 'explained',
  reject: 'rejected',
  unresolve: 'unresolved',
}

/** The decided-state label for a claim status (brief §12.5: the
 *  decided card shows "Ruled. [Verdict label.] Weaver will bring
 *  the next one when you reply."). */
export const STATUS_LABEL: Record<string, string> = {
  accepted: 'Kept',
  corrected: 'Fixed',
  explained: 'Explained',
  rejected: 'Rejected',
  unresolved: 'Left open',
}

/** The amendment-4 gate predicate, client-side (brief §5.3): a
 *  meeting_impression claim accepted while its visitor response was
 *  disputed or unresolved writes observed/guidance, never
 *  affirmative training. An empty visitor response (legacy row) does
 *  not trigger the gate. */
export function isAmendment4Gated(claim: Claim): boolean {
  return (
    claim.claim_type === 'meeting_impression' &&
    (claim.readback_visitor_response === 'disputed' ||
      claim.readback_visitor_response === 'unresolved')
  )
}

/** The training-consequence sentence for one action on one claim
 *  (brief §5.2, as written). The consequence sentence is the
 *  requirement; the wording below is the accepted draft. */
export function confirmationCopy(action: RoundAction, claim: Claim): string {
  if (action === 'accept') {
    if (isAmendment4Gated(claim)) {
      const clause =
        claim.readback_visitor_response === 'disputed'
          ? 'because you disputed it in the meeting'
          : "because you didn't settle it in the meeting"
      return (
        'This does NOT train the impression as true about you. It is kept as a record of ' +
        `what the seat said — observed, not affirmed — ${clause}. Only a later explicit ` +
        "affirmation could change that, and that question is separate — we're not deciding it here."
      )
    }
    return "This trains Weaver's picture of you: the impression becomes approved evidence about you."
  }
  if (action === 'correct') {
    return (
      'Your correction becomes the training signal — the revised wording is the approved version. ' +
      'The original stays on the record beside it.'
    )
  }
  if (action === 'explain') {
    return 'Your explanation is recorded with the impression — it teaches why, not that the impression was right.'
  }
  if (action === 'reject') {
    return 'The impression is marked wrong and will not be used as evidence about you. The record is kept, with your verdict on it.'
  }
  return 'Left open — recorded as undecided, with no training weight. This is a verdict, not a park: it will not come back next round.'
}

/** The spoken amendment-4 sentence (brief §5.2): Weaver says the
 *  gate outcome in words on her next turn after a gated accept. */
export const GATE_SPOKEN_SENTENCE =
  'Kept as a record of what was said — not as training that the read was right.'

const CORRECTION_FENCE_RE = /```correction-draft\s*\n(.*?)```/gs
const ROUND_OFFER_RE = /^ *\[\[round-offer\]\] *$/gm

/** The proposed correction from a ```correction-draft fenced block,
 *  or null when the fence is absent or malformed. A malformed fence
 *  (unclosed, empty) yields null — the note field starts empty and
 *  the user types. The draft alone writes nothing. */
export function parseCorrectionDraft(content: string): string | null {
  if (!content) return null
  const m = CORRECTION_FENCE_RE.exec(content)
  if (!m) return null
  const draft = (m[1] ?? '').trim()
  return draft ? draft : null
}

/** Strip ```correction-draft fenced blocks from display text. The
 *  fence is a carrier for the draft, not part of the reply. */
export function stripCorrectionDraft(content: string): string {
  return content.replace(CORRECTION_FENCE_RE, '').replace(/\n{3,}/g, '\n\n').trim()
}

/** Strip the [[round-offer]] marker line from display text. The
 *  marker records the offer server-side; it is not part of the
 *  reply the user reads. */
export function stripRoundOfferMarker(content: string): string {
  return content.replace(ROUND_OFFER_RE, '').replace(/\n{3,}/g, '\n\n').trim()
}
