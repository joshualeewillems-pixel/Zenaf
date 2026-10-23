import { describe, expect, it } from 'vitest'
import { markerTitle, meetingDoorState } from './LivingTree'

/**
 * Attention-marker wording (2026-10-23): the "meet" reason means "a later
 * keystone is pending", and after the Conductor's first meeting it lit
 * for every seat — including ones already met, where "wants to meet you"
 * was simply false. A met seat (face_revealed, the honest signal from
 * archetype status) gets the discovery wording instead.
 */
describe('markerTitle', () => {
  it('an unmet seat still wants to meet you', () => {
    expect(markerTitle('mentor', 'meet')).toBe('The Gardener wants to meet you.')
    expect(markerTitle('conductor', 'meet', false)).toBe('The Weaver wants to meet you.')
  })

  it('a met seat has more to discover with you', () => {
    expect(markerTitle('conductor', 'meet', true)).toBe(
      'The Weaver has more to discover with you.',
    )
    expect(markerTitle('maverick', 'meet', true)).toBe(
      'The Fox has more to discover with you.',
    )
  })

  it('intro and recognition titles are unchanged by the met flag', () => {
    expect(markerTitle('conductor', 'intro', true)).toBe(
      'The Weaver wants to talk about something.',
    )
    expect(markerTitle('conductor', 'intro')).toBe('The Weaver wants to talk about something.')
    expect(markerTitle('skeptic', 'recognition', true)).toBe(
      'The Neighbor wants to talk about what it has discovered.',
    )
  })

  it('falls back to the meet wording for unknown reasons and seats', () => {
    expect(markerTitle('mentor', null)).toBe('The Gardener wants to meet you.')
    expect(markerTitle('unknown-seat', 'meet')).toBe('A seat wants to meet you.')
  })
})

/**
 * Meeting-door visibility (2026-10-23): the "Begin the first meeting"
 * button was the meeting overlay's only door, and it rendered only for
 * the 'intro' marker — which disappears the moment the first meeting
 * completes. The completed meeting (transcript + "Meet again") became
 * unreachable. The door now follows the seat's state: intro → begin,
 * already met (face_revealed) → revisit, otherwise no door at all.
 */
describe('meetingDoorState', () => {
  it('an intro marker gets the begin door, met or not', () => {
    expect(meetingDoorState('intro')).toBe('begin')
    expect(meetingDoorState('intro', false)).toBe('begin')
    expect(meetingDoorState('intro', true)).toBe('begin')
  })

  it('a met seat keeps a revisit door after the intro marker moves on', () => {
    expect(meetingDoorState('meet', true)).toBe('revisit')
    expect(meetingDoorState('recognition', true)).toBe('revisit')
    expect(meetingDoorState(null, true)).toBe('revisit')
    expect(meetingDoorState(undefined, true)).toBe('revisit')
  })

  it('an unmet seat without the intro marker gets no door', () => {
    expect(meetingDoorState('meet')).toBeNull()
    expect(meetingDoorState('meet', false)).toBeNull()
    expect(meetingDoorState('recognition', false)).toBeNull()
    expect(meetingDoorState(null)).toBeNull()
    expect(meetingDoorState(undefined)).toBeNull()
  })
})
