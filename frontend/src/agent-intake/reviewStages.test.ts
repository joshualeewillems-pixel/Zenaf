import { describe, expect, it } from 'vitest'
import {
  allClaimsResolved,
  canFinishReview,
  defaultCardExpanded,
  insightGroups,
  miningStateOf,
  miningStatusLabel,
  openClaimsCount,
  reviewedList,
  strandGroups,
  whatsLeft,
} from './reviewStages'

const pending = (id: string, type = 'strand') => ({ id, claim_type: type, status: 'pending' })
const done = (id: string, type = 'strand', status = 'accepted') => ({ id, claim_type: type, status })

describe('miningStateOf', () => {
  it('trusts an explicit backend state', () => {
    expect(miningStateOf('mined', [])).toBe('mined')
    expect(miningStateOf('skipped', [])).toBe('skipped')
  })

  it('derives mined from stored mined claims when the column predates the row', () => {
    expect(miningStateOf('pending', [pending('p:0', 'project')])).toBe('mined')
    expect(miningStateOf(undefined, [pending('p:0', 'project')])).toBe('mined')
  })

  it('stays pending with no evidence of mining', () => {
    expect(miningStateOf('pending', [pending('s:0')])).toBe('pending')
    expect(miningStateOf(undefined, [])).toBe('pending')
  })
})

describe('claim resolution', () => {
  it('counts open claims', () => {
    expect(openClaimsCount([pending('a'), done('b'), pending('c')])).toBe(2)
  })

  it('requires at least one claim and all resolved', () => {
    expect(allClaimsResolved([])).toBe(false)
    expect(allClaimsResolved([done('a'), done('b', 'kind', 'corrected')])).toBe(true)
    expect(allClaimsResolved([done('a'), pending('b')])).toBe(false)
  })

  it('treats corrected and explained as resolved', () => {
    expect(allClaimsResolved([done('a', 'strand', 'corrected'), done('b', 'kind', 'explained')])).toBe(true)
  })
})

describe('canFinishReview', () => {
  const resolved = [done('a'), done('b', 'kind')]
  it('needs resolved claims and a resolved mining step', () => {
    expect(canFinishReview(resolved, 'mined')).toBe(true)
    expect(canFinishReview(resolved, 'skipped')).toBe(true)
    expect(canFinishReview(resolved, 'pending')).toBe(false)
    expect(canFinishReview([pending('a')], 'mined')).toBe(false)
    expect(canFinishReview([], 'mined')).toBe(false)
  })

  it('a pending meeting impression gates finishing like any primary claim', () => {
    const impression = {
      id: 'meeting-conductor-1:impression:self+number:20261023T1',
      claim_type: 'meeting_impression',
      status: 'pending',
    }
    expect(canFinishReview([impression], 'skipped')).toBe(false)
    expect(canFinishReview([{ ...impression, status: 'accepted' }], 'skipped')).toBe(true)
  })
})

describe('whatsLeft', () => {
  it('names open claims and unfinished mining', () => {
    expect(whatsLeft([pending('a'), done('b')], 'pending')).toEqual([
      '1 claim still open',
      'project mining not done — mine or skip',
    ])
  })

  it('is empty when everything resolves', () => {
    expect(whatsLeft([done('a')], 'mined')).toEqual([])
    expect(whatsLeft([done('a')], 'skipped')).toEqual([])
  })

  it('is honest while claims load', () => {
    expect(whatsLeft([], 'pending')).toEqual(['claims still loading', 'project mining not done — mine or skip'])
  })
})

describe('miningStatusLabel', () => {
  it('uses plain language', () => {
    expect(miningStatusLabel('mined')).toBe('projects mined')
    expect(miningStatusLabel('skipped')).toBe('mining skipped')
    expect(miningStatusLabel('pending')).toBe('not mined yet')
  })
})

describe('reviewedList', () => {
  const agents = [
    { id: 'a', status: 'pending_review', created_at: '2026-10-14' },
    { id: 'b', status: 'active', created_at: '2026-10-13' },
    { id: 'c', status: 'active', created_at: '2026-10-14' },
    { id: 'd', status: 'archived', created_at: '2026-10-14' },
  ]
  it('lists only active agents, newest first', () => {
    expect(reviewedList(agents).map((a) => a.id)).toEqual(['c', 'b'])
  })

  it('caps the list', () => {
    const many = Array.from({ length: 15 }, (_, i) => ({
      id: `x${i}`,
      status: 'active',
      created_at: `2026-10-${String(i + 1).padStart(2, '0')}`,
    }))
    expect(reviewedList(many)).toHaveLength(10)
  })
})

describe('insight groups', () => {
  const insight = (n: number, status = 'pending') => ({
    id: `insight:${n}`,
    claim_type: 'stance',
    status,
  })
  const alt = (n: number, m: number, status = 'pending') => ({
    id: `insight:${n}:alt:${m}`,
    claim_type: 'alternative',
    status,
  })

  it('groups alternatives under their interpretation by id prefix', () => {
    const claims = [insight(0), alt(0, 1), alt(0, 0), insight(1), alt(1, 0)]
    const groups = insightGroups(claims)
    expect(groups).toHaveLength(2)
    expect(groups[0].insight.id).toBe('insight:0')
    expect(groups[0].alternatives.map((a) => a.id)).toEqual(['insight:0:alt:0', 'insight:0:alt:1'])
    expect(groups[1].alternatives.map((a) => a.id)).toEqual(['insight:1:alt:0'])
  })

  it('ignores insight claims of other types and orphaned alternatives', () => {
    const claims = [
      insight(0),
      { id: 'insight:9:alt:0', claim_type: 'alternative', status: 'pending' },
      { id: 'strand:self', claim_type: 'strand', status: 'pending' },
    ]
    const groups = insightGroups(claims)
    expect(groups).toHaveLength(1)
    expect(groups[0].alternatives).toEqual([])
  })

  it('returns empty for no insights', () => {
    expect(insightGroups([])).toEqual([])
    expect(insightGroups([{ id: 'strand:self', claim_type: 'strand', status: 'pending' }])).toEqual([])
  })

  it('a meeting impression renders as an insight group of its own', () => {
    const impression = {
      id: 'meeting-conductor-1:impression:self+number:20261023T1',
      claim_type: 'meeting_impression',
      status: 'pending',
    }
    const groups = insightGroups([impression, insight(0)])
    expect(groups.map((g) => g.insight.id)).toEqual([impression.id, 'insight:0'])
    expect(groups[0].alternatives).toEqual([])
  })
})

describe('strand groups', () => {
  const placement = (turn: number, strand = 'self') => ({
    id: `a1:strand:${strand}:m${turn}`,
    claim_type: 'strand',
    status: 'pending',
  })
  const alt = (turn: number, strand = 'self') => ({
    id: `a1:strand:${strand}:m${turn}:alt:0`,
    claim_type: 'alternative',
    status: 'pending',
  })

  it('nests each moment card with its alternative reading', () => {
    const claims = [placement(3), alt(3), placement(5)]
    const groups = strandGroups(claims)
    expect(groups).toHaveLength(2)
    expect(groups[0].insight.id).toBe('a1:strand:self:m3')
    expect(groups[0].alternatives.map((a) => a.id)).toEqual(['a1:strand:self:m3:alt:0'])
    expect(groups[1].alternatives).toEqual([])
  })

  it('does not confuse m3 with m30', () => {
    const claims = [placement(3), { id: 'a1:strand:self:m30:alt:0', claim_type: 'alternative', status: 'pending' }]
    const groups = strandGroups(claims)
    expect(groups[0].alternatives).toEqual([])
  })

  it('ignores insight parents and orphaned alternatives', () => {
    const claims = [
      placement(3),
      { id: 'insight:0', claim_type: 'stance', status: 'pending' },
      { id: 'a1:strand:self:m9:alt:0', claim_type: 'alternative', status: 'pending' },
    ]
    const groups = strandGroups(claims)
    expect(groups).toHaveLength(1)
    expect(groups[0].alternatives).toEqual([])
  })

  it('returns empty for no placements', () => {
    expect(strandGroups([])).toEqual([])
    expect(strandGroups([{ id: 'insight:0', claim_type: 'stance', status: 'pending' }])).toEqual([])
  })
})

describe('alternatives never block finishing', () => {
  const alt = (m: number, status = 'pending') => ({
    id: `insight:0:alt:${m}`,
    claim_type: 'alternative',
    status,
  })

  it('pending alternatives do not block the finish gate', () => {
    const claims = [
      { id: 'insight:0', claim_type: 'stance', status: 'accepted' },
      alt(0),
      alt(1),
    ]
    expect(allClaimsResolved(claims)).toBe(true)
    expect(canFinishReview(claims, 'mined')).toBe(true)
  })

  it('unresolved primary claims still block', () => {
    const claims = [
      { id: 'insight:0', claim_type: 'stance', status: 'pending' },
      alt(0, 'accepted'),
    ]
    expect(allClaimsResolved(claims)).toBe(false)
    expect(canFinishReview(claims, 'mined')).toBe(false)
  })

  it('rejected and unresolved count as handled', () => {
    const claims = [
      { id: 'insight:0', claim_type: 'stance', status: 'rejected' },
      { id: 'insight:1', claim_type: 'value_inference', status: 'unresolved' },
    ]
    expect(allClaimsResolved(claims)).toBe(true)
  })

  it('whatsLeft does not count alternatives', () => {
    const claims = [
      { id: 'insight:0', claim_type: 'stance', status: 'accepted' },
      alt(0),
    ]
    expect(whatsLeft(claims, 'mined')).toEqual([])
    expect(openClaimsCount(claims)).toBe(0)
  })
})

describe('defaultCardExpanded', () => {
  it('pending cards start open (action needed)', () => {
    expect(defaultCardExpanded('pending')).toBe(true)
  })

  it('resolved cards start collapsed (save vertical space)', () => {
    for (const s of ['accepted', 'corrected', 'explained', 'rejected', 'unresolved']) {
      expect(defaultCardExpanded(s)).toBe(false)
    }
  })
})
