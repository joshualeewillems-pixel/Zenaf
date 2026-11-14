// @vitest-environment jsdom
/**
 * Compact-head "Other actions" menu rules (navigation correction §2,
 * M3): pure-function tests for buildSeatHeaderMenu — no rendering.
 *
 * The menu never contains Talk (tapping the node IS talk), Full
 * character (already a head disclosure), or the first-meeting door
 * (a direct header button). The invitation shortcut appears only
 * when the seat has a pending invitation AND its most-recent
 * invitation conversation is not the open one, and its label says
 * "View", never "Accept".
 */
import { describe, it, expect } from 'vitest'
import { buildSeatHeaderMenu } from './LivingTree'

const TALK_A = 'talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const TALK_B = 'talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

describe('buildSeatHeaderMenu', () => {
  it('lists Today, Review, Upload and never Talk, Full character, or a meeting door', () => {
    const items = buildSeatHeaderMenu({
      seatKey: 'champion',
      invitationCount: 0,
      currentChatId: null,
    })
    const titles = items.map((i) => i.title)
    expect(titles).toEqual(['Today', 'Review', 'Upload'])
    expect(titles).not.toContain('Talk')
    expect(titles).not.toContain('Full character')
    expect(items.some((i) => i.kind === 'shortcut')).toBe(false)
  })

  it('adds seat-owned destinations where they exist', () => {
    const mentor = buildSeatHeaderMenu({
      seatKey: 'mentor',
      invitationCount: 0,
      currentChatId: null,
    })
    expect(mentor.map((i) => i.title)).toEqual([
      'Today',
      'Review',
      'Upload',
      'Vision map',
      'Vision (tables)',
    ])
    const champion = buildSeatHeaderMenu({
      seatKey: 'champion',
      invitationCount: 0,
      currentChatId: null,
    })
    expect(champion.map((i) => i.title)).toEqual(['Today', 'Review', 'Upload'])
    const guardian = buildSeatHeaderMenu({
      seatKey: 'guardian',
      invitationCount: 0,
      currentChatId: null,
    })
    expect(guardian.map((i) => i.title)).toEqual([
      'Today',
      'Review',
      'Upload',
      'Provenance',
    ])
    const skeptic = buildSeatHeaderMenu({
      seatKey: 'skeptic',
      invitationCount: 0,
      currentChatId: null,
    })
    expect(skeptic.map((i) => i.title)).toEqual([
      'Today',
      'Review',
      'Upload',
      'Signal review',
    ])
    const conductor = buildSeatHeaderMenu({
      seatKey: 'conductor',
      invitationCount: 0,
      currentChatId: null,
    })
    expect(conductor.map((i) => i.title)).toEqual([
      'Today',
      'Review',
      'Upload',
      'Workspace Organizer',
    ])
  })

  it('shows the shortcut when an invitation target differs from the open conversation', () => {
    const items = buildSeatHeaderMenu({
      seatKey: 'mentor',
      invitationCount: 1,
      invitationTarget: TALK_A,
      currentChatId: TALK_B,
    })
    const shortcut = items.find((i) => i.kind === 'shortcut')
    expect(shortcut?.title).toBe('View invitation in another conversation')
    expect(shortcut?.title).not.toContain('Accept')
    expect(shortcut?.title).not.toMatch(/\(\d+\)/)
  })

  it('hides the shortcut when the target IS the open conversation', () => {
    const items = buildSeatHeaderMenu({
      seatKey: 'mentor',
      invitationCount: 1,
      invitationTarget: TALK_A,
      currentChatId: TALK_A,
    })
    expect(items.some((i) => i.kind === 'shortcut')).toBe(false)
  })

  it('hides the shortcut when there is no invitation, even with a stale target', () => {
    const items = buildSeatHeaderMenu({
      seatKey: 'mentor',
      invitationCount: 0,
      invitationTarget: TALK_A,
      currentChatId: TALK_B,
    })
    expect(items.some((i) => i.kind === 'shortcut')).toBe(false)
  })

  it('hides the shortcut when the invitation target is absent', () => {
    const items = buildSeatHeaderMenu({
      seatKey: 'mentor',
      invitationCount: 1,
      invitationTarget: undefined,
      currentChatId: TALK_B,
    })
    expect(items.some((i) => i.kind === 'shortcut')).toBe(false)
  })
})
