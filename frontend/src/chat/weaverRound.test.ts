/**
 * Weaver rapid fire S1 — pure-helper tests (brief §14: T6, T10
 * copy half, T11 copy half, T13 fence half, T19 copy half).
 *
 * The confirmation copy is the brief §5.2 wording AS WRITTEN
 * (SQ1: accepted as written — the amendment-4 sentence keeps its
 * full second half, including the deferral).
 */
import { describe, it, expect } from 'vitest'
import type { Claim } from '../agent-intake/ClaimCard'
import {
  confirmationCopy,
  isAmendment4Gated,
  parseCorrectionDraft,
  stripCorrectionDraft,
  stripRoundOfferMarker,
  GATE_SPOKEN_SENTENCE,
} from './weaverRound'

function claim(overrides: Partial<Claim> = {}): Claim {
  return {
    id: 'meeting-maverick-1:impression:self:run1',
    claim_type: 'meeting_impression',
    title: 'First impression — Fox',
    evidence: 'Yes, that is me.',
    inference: 'The Fox reads you as steady.',
    detail: '',
    status: 'pending',
    user_note: '',
    question: 'Does that first impression sound right to you?',
    scope: 'moment',
    turn_ref: '',
    readback_visitor_response: 'affirmed',
    readback_seat_outcome: 'retained',
    readback_original_claim: '',
    ...overrides,
  }
}

describe('confirmationCopy (brief §5.2, as written)', () => {
  it('Keep it on an affirmed impression trains the picture', () => {
    expect(confirmationCopy('accept', claim())).toBe(
      "This trains Weaver's picture of you: the impression becomes approved evidence about you.",
    )
  })

  it('Keep it on a disputed impression shows the amendment-4 sentence in full', () => {
    expect(
      confirmationCopy('accept', claim({ readback_visitor_response: 'disputed' })),
    ).toBe(
      'This does NOT train the impression as true about you. It is kept as a record of ' +
        'what the seat said — observed, not affirmed — because you disputed it in the meeting. ' +
        "Only a later explicit affirmation could change that, and that question is separate — we're not deciding it here.",
    )
  })

  it('Keep it on an unresolved impression names the unsettled response', () => {
    const copy = confirmationCopy(
      'accept',
      claim({ readback_visitor_response: 'unresolved' }),
    )
    expect(copy).toContain("because you didn't settle it in the meeting")
    expect(copy).toContain("that question is separate — we're not deciding it here")
  })

  it('Keep it on a legacy row (empty response) does not claim a dispute', () => {
    expect(
      confirmationCopy('accept', claim({ readback_visitor_response: '' })),
    ).toBe(
      "This trains Weaver's picture of you: the impression becomes approved evidence about you.",
    )
  })

  it('Keep it on a non-impression claim is never gated', () => {
    expect(
      confirmationCopy(
        'accept',
        claim({ claim_type: 'value_inference', readback_visitor_response: 'disputed' }),
      ),
    ).toBe(
      "This trains Weaver's picture of you: the impression becomes approved evidence about you.",
    )
  })

  it('Fix the wording, Say why, It is wrong, Leave it open', () => {
    expect(confirmationCopy('correct', claim())).toBe(
      'Your correction becomes the training signal — the revised wording is the approved version. ' +
        'The original stays on the record beside it.',
    )
    expect(confirmationCopy('explain', claim())).toBe(
      'Your explanation is recorded with the impression — it teaches why, not that the impression was right.',
    )
    expect(confirmationCopy('reject', claim())).toBe(
      'The impression is marked wrong and will not be used as evidence about you. The record is kept, with your verdict on it.',
    )
    expect(confirmationCopy('unresolve', claim())).toBe(
      'Left open — recorded as undecided, with no training weight. This is a verdict, not a park: it will not come back next round.',
    )
  })

  it('the gate predicate matches the server gate', () => {
    expect(isAmendment4Gated(claim({ readback_visitor_response: 'disputed' }))).toBe(true)
    expect(isAmendment4Gated(claim({ readback_visitor_response: 'unresolved' }))).toBe(true)
    expect(isAmendment4Gated(claim({ readback_visitor_response: 'affirmed' }))).toBe(false)
    expect(isAmendment4Gated(claim({ readback_visitor_response: '' }))).toBe(false)
    expect(
      isAmendment4Gated(
        claim({ claim_type: 'value_inference', readback_visitor_response: 'disputed' }),
      ),
    ).toBe(false)
  })

  it('the spoken amendment-4 sentence is the §5.2 sentence', () => {
    expect(GATE_SPOKEN_SENTENCE).toBe(
      'Kept as a record of what was said — not as training that the read was right.',
    )
  })
})

describe('correction-draft fence', () => {
  const REPLY =
    'Here is the Fox read in plain words.\n```correction-draft\nMore precisely, steady under pressure.\n```'

  it('parses the draft from a well-formed fence', () => {
    expect(parseCorrectionDraft(REPLY)).toBe('More precisely, steady under pressure.')
  })

  it('returns null when the fence is absent', () => {
    expect(parseCorrectionDraft('No fence here.')).toBe(null)
  })

  it('returns null when the fence is malformed (unclosed, empty)', () => {
    expect(parseCorrectionDraft('```correction-draft\nno closing fence')).toBe(null)
    expect(parseCorrectionDraft('```correction-draft\n   \n```')).toBe(null)
  })

  it('strips the fence from display, keeping the prose', () => {
    const stripped = stripCorrectionDraft(REPLY)
    expect(stripped).toBe('Here is the Fox read in plain words.')
    expect(stripped).not.toContain('correction-draft')
    expect(stripped).not.toContain('More precisely')
  })
})

describe('round-offer marker', () => {
  it('strips the marker line from display', () => {
    const text = "You've got up to 5 waiting. Want to go through them?\n[[round-offer]]"
    expect(stripRoundOfferMarker(text)).toBe("You've got up to 5 waiting. Want to go through them?")
  })

  it('leaves ordinary text untouched', () => {
    expect(stripRoundOfferMarker('Hello there.')).toBe('Hello there.')
  })
})
