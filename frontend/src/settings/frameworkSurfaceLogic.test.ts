/**
 * Slice 2 — framework surface shaping logic.
 * C3-T1 (one record, shown twice), grouping, retained-choice rules
 * (R.1–R.4), and stance availability per capability.
 */
import { describe, it, expect } from 'vitest'
import {
  buildGroups,
  pluralize,
  retainedChoiceText,
  retainedItemNoun,
  reviewDestination,
  rowsForGroup,
  shouldOfferRetainedChoice,
} from './frameworkSurfaceLogic'
import type { FrameworkCapability, FrameworkStance, FrameworkState } from './api'

function row(key: string, label: string, kind: string, stance: FrameworkStance = 'ask_me') {
  return {
    key,
    label,
    kind,
    stance,
    stance_source: 'default' as const,
    granted_at: null,
    last_changed_at: null,
    surface: null,
  }
}

function capability(
  id: string,
  rows: ReturnType<typeof row>[],
  extra: Partial<FrameworkCapability> = {},
): FrameworkCapability {
  return {
    id,
    covers: `${id} covers`,
    does_not_allow: `${id} does not allow`,
    default_stance: 'dont_do_it',
    supported_stances: ['ask_me', 'just_do_it', 'dont_do_it'],
    exception_classes: [],
    retained_count: 0,
    quieted: false,
    paused: false,
    rows,
    ...extra,
  }
}

function fixtureState(): FrameworkState {
  return {
    paused: false,
    pause: { paused: false, paused_at: null, surface: null },
    capabilities: [
      capability(
        'R1',
        [
          row('heart', 'Heart', 'strand'),
          row('hands', 'Hands', 'strand'),
          row('logic', 'Logic', 'strand'),
          row('voice', 'Voice', 'strand'),
          row('ear', 'Ear', 'strand'),
          row('compass', 'Compass', 'strand'),
          row('eye', 'Eye', 'strand'),
          row('intake', 'Source materials (intake)', 'source'),
          row('user_upload', 'Source materials (upload)', 'source'),
        ],
        { default_stance: 'ask_me' },
      ),
      capability('R2', [row('narrative_interpretation', 'Narrative interpretation', 'default', 'dont_do_it')]),
      capability('R3', [row('cross_branch_coordination', 'Cross-branch coordination', 'default', 'dont_do_it')]),
      capability(
        'R4',
        ['mentor', 'champion', 'guardian', 'maverick', 'ambassador', 'conductor', 'skeptic'].map(
          (seat) => row(seat, seat, 'seat', 'just_do_it'),
        ),
        { default_stance: 'just_do_it', supported_stances: ['just_do_it', 'dont_do_it'] },
      ),
      capability('R5', [row('task_proposals', 'Task proposals', 'default', 'just_do_it')], {
        default_stance: 'just_do_it',
        supported_stances: ['just_do_it', 'dont_do_it'],
      }),
      capability('R6', [], { retained_count: 3 }),
    ],
  }
}

describe('buildGroups', () => {
  it('S2-L1 groups one group per registered subsystem in registry order', () => {
    const groups = buildGroups(fixtureState())
    expect(groups.map((g) => g.key)).toEqual([
      'noting-general',
      'strand',
      'steward',
      'fellowship',
      'vision-execution',
    ])
    expect(groups[0].capabilities.map((c) => c.id)).toEqual(['R1'])
    expect(groups[2].capabilities.map((c) => c.id)).toEqual(['R2', 'R3'])
    expect(groups[3].capabilities.map((c) => c.id)).toEqual(['R4'])
    expect(groups[4].capabilities.map((c) => c.id)).toEqual(['R5', 'R6'])
  })

  it('S2-L2 general noting shows all nine R1 rows; strand group shows only strand rows', () => {
    const groups = buildGroups(fixtureState())
    const [general, strand] = groups
    const r1 = fixtureState().capabilities[0]
    expect(rowsForGroup(general, r1).length).toBe(9)
    expect(rowsForGroup(strand, r1).map((r) => r.key)).toEqual([
      'heart',
      'hands',
      'logic',
      'voice',
      'ear',
      'compass',
      'eye',
    ])
  })

  it('C3-T1 one record shown twice: both groups reference the SAME R1 object', () => {
    const state = fixtureState()
    const groups = buildGroups(state)
    const generalR1 = groups[0].capabilities[0]
    const strandR1 = groups[1].capabilities[0]
    expect(strandR1).toBe(generalR1)
    // A stance written through one display is read by the other:
    // there is no second record to diverge.
    const heart = generalR1.rows.find((r) => r.key === 'heart')
    if (!heart) throw new Error('heart row missing')
    heart.stance = 'dont_do_it'
    const strandHeart = rowsForGroup(groups[1], strandR1).find((r) => r.key === 'heart')
    expect(strandHeart?.stance).toBe('dont_do_it')
    expect(rowsForGroup(groups[0], generalR1).find((r) => r.key === 'heart')?.stance).toBe(
      'dont_do_it',
    )
  })

  it('S2-L3 empty capabilities produce no groups', () => {
    expect(buildGroups({ paused: false, pause: { paused: false, paused_at: null, surface: null }, capabilities: [] })).toEqual([])
  })
})

describe('retained choice (R.1–R.4)', () => {
  it('S2-L4 no retained items means no choice line', () => {
    const cap = capability('R1', [])
    expect(retainedChoiceText(cap)).toBeNull()
    expect(shouldOfferRetainedChoice(cap, { capability: 'R1', stance: 'dont_do_it' })).toBe(false)
  })

  it('S2-L5 choice opens only on a revocation that leaves items behind', () => {
    const cap = capability('R6', [], { retained_count: 3 })
    expect(shouldOfferRetainedChoice(cap, { capability: 'R6', stance: 'dont_do_it' })).toBe(true)
    expect(shouldOfferRetainedChoice(cap, { capability: 'R6', stance: 'just_do_it' })).toBe(false)
    expect(shouldOfferRetainedChoice(cap, { capability: 'R5', stance: 'dont_do_it' })).toBe(false)
    expect(shouldOfferRetainedChoice(cap, null)).toBe(false)
  })

  it('S2-L6 choice text names the count and where the items live', () => {
    expect(retainedChoiceText(capability('R6', [], { retained_count: 3 }))).toContain('3 live reminders')
    expect(retainedChoiceText(capability('R1', [], { retained_count: 2 }))).toContain('2 pending notes')
    expect(retainedChoiceText(capability('R4', [], { retained_count: 1 }))).toContain('1 pending invitation')
    expect(retainedChoiceText(capability('R5', [], { retained_count: 5 }))).toContain('5 pending proposals')
  })

  it('S2-L7 Review goes to Today only for R6 (the one real per-item surface in Slice 2)', () => {
    expect(reviewDestination('R6')).toBe('today')
    for (const id of ['R1', 'R2', 'R3', 'R4', 'R5']) {
      expect(reviewDestination(id)).toBeNull()
    }
  })

  it('S2-L8 nouns pluralize correctly', () => {
    expect(retainedItemNoun('R1')).toEqual({ singular: 'pending note', plural: 'pending notes' })
    expect(pluralize(1, 'pending note', 'pending notes')).toBe('pending note')
    expect(pluralize(3, 'pending note', 'pending notes')).toBe('pending notes')
  })
})
