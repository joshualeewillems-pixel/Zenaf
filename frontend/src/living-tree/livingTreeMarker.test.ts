import { describe, expect, it } from 'vitest'
import { markerTitle } from './LivingTree'

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
