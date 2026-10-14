import { describe, expect, it } from 'vitest'
import {
  allClaimsResolved,
  canFinishReview,
  miningStateOf,
  miningStatusLabel,
  openClaimsCount,
  reviewedList,
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
