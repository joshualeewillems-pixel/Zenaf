// @vitest-environment jsdom
/**
 * Capability C visible-UX slice — invitation indicator label tests.
 *
 * The helper lives in archetypes.ts (not LivingTree.tsx), so its tests
 * live here, one place only. Copy is neutral presence language only:
 * no urgency words, no countdowns, no pressure phrasing. Absent fields
 * mean "unknown" (no indicator) — distinct from an authoritative count
 * of 0 (also no indicator, but a different case).
 */
import { describe, it, expect } from 'vitest'
import { invitationIndicatorLabel } from './archetypes'
import type { KeystoneAttentionMarker } from './archetypes'

const BASE: KeystoneAttentionMarker = {
  attention: false,
  reason: null,
  keystone_reason: null,
  observation_reason: null,
  observation_ids: [],
  observation_count: 0,
}

const FORBIDDEN = ['waiting', 'needs you', 'unread', 'urgent', "don't miss", 'pending your response']

describe('invitationIndicatorLabel', () => {
  it('singular form for count 1', () => {
    expect(invitationIndicatorLabel('The Bear', { ...BASE, invitation_count: 1 })).toBe(
      'The Bear has an invitation to discuss',
    )
  })

  it('plural form for count > 1', () => {
    expect(invitationIndicatorLabel('The Bear', { ...BASE, invitation_count: 3 })).toBe(
      'The Bear has 3 invitations to discuss',
    )
  })

  it('carries no forbidden urgency words', () => {
    for (const count of [1, 2, 5]) {
      const label = invitationIndicatorLabel('The Bear', { ...BASE, invitation_count: count })
      expect(label).not.toBeNull()
      for (const word of FORBIDDEN) {
        expect(label!.toLowerCase()).not.toContain(word)
      }
      expect(label).not.toMatch(/\d+\s*(h|hr|hrs|min|sec)\b/)
    }
  })

  it('count 0 renders no indicator (authoritative none)', () => {
    expect(
      invitationIndicatorLabel('The Bear', {
        ...BASE,
        invitation_count: 0,
        invitation_conversation_ids: [],
      }),
    ).toBeNull()
  })

  it('absent fields render no indicator (unknown, never "none")', () => {
    expect(invitationIndicatorLabel('The Bear', BASE)).toBeNull()
    expect(
      invitationIndicatorLabel('The Bear', {
        ...BASE,
        invitation_conversation_ids: ['talk-1'],
      }),
    ).toBeNull()
  })

  it('missing or non-numeric count renders no indicator', () => {
    expect(invitationIndicatorLabel('The Bear', null)).toBeNull()
    expect(invitationIndicatorLabel('The Bear', undefined)).toBeNull()
    expect(
      invitationIndicatorLabel('The Bear', {
        ...BASE,
        invitation_count: '2' as unknown as number,
      }),
    ).toBeNull()
  })
})
