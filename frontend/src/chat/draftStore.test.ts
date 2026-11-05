// @vitest-environment jsdom
/**
 * Draft store pure-logic tests (navigation correction §3 + C4).
 *
 * Keys are (userId, conversationId, seat); 'council' and 'unselected'
 * are reserved seat identities that collide with no archetype_id.
 * Adoption is a MOVE: after a successful move the unselected entry
 * is gone; when the destination already has a draft, both are
 * preserved independently.
 */
import { describe, it, expect } from 'vitest'
import {
  DraftStore,
  COUNCIL_DRAFT_SEAT,
  UNSELECTED_DRAFT_SEAT,
} from './draftStore'

const U1 = 'user-1'
const U2 = 'user-2'
const A = 'talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const B = 'talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

function seeded(): DraftStore {
  const s = new DraftStore()
  s.currentUserId = U1
  return s
}

describe('draft keys', () => {
  it('isolates drafts by conversation and by seat', () => {
    const s = seeded()
    s.set({ userId: U1, conversationId: A, seat: 'mentor' }, 'mentor draft A')
    s.set({ userId: U1, conversationId: A, seat: 'champion' }, 'champion draft A')
    s.set({ userId: U1, conversationId: B, seat: 'mentor' }, 'mentor draft B')
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe('mentor draft A')
    expect(s.get({ userId: U1, conversationId: A, seat: 'champion' })).toBe('champion draft A')
    expect(s.get({ userId: U1, conversationId: B, seat: 'mentor' })).toBe('mentor draft B')
    expect(s.get({ userId: U1, conversationId: B, seat: 'champion' })).toBe(undefined)
  })

  it('keeps council drafts distinct from every seat draft', () => {
    const s = seeded()
    s.set({ userId: U1, conversationId: A, seat: 'mentor' }, 'seat text')
    s.set({ userId: U1, conversationId: A, seat: COUNCIL_DRAFT_SEAT }, 'council text')
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe('seat text')
    expect(s.get({ userId: U1, conversationId: A, seat: COUNCIL_DRAFT_SEAT })).toBe('council text')
  })

  it('clear removes only its own key', () => {
    const s = seeded()
    s.set({ userId: U1, conversationId: A, seat: 'mentor' }, 'x')
    s.set({ userId: U1, conversationId: A, seat: 'champion' }, 'y')
    s.clear({ userId: U1, conversationId: A, seat: 'mentor' })
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe(undefined)
    expect(s.get({ userId: U1, conversationId: A, seat: 'champion' })).toBe('y')
  })
})

describe('user isolation', () => {
  it('a key for another user is a miss, and writes for another user are no-ops', () => {
    const s = seeded()
    s.set({ userId: U1, conversationId: A, seat: 'mentor' }, 'u1 text')
    expect(s.get({ userId: U2, conversationId: A, seat: 'mentor' })).toBe(undefined)
    s.set({ userId: U2, conversationId: A, seat: 'mentor' }, 'u2 text')
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe('u1 text')
    s.clear({ userId: U2, conversationId: A, seat: 'mentor' })
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe('u1 text')
  })

  it('purgeAll removes every draft (auth change is not a suspend)', () => {
    const s = seeded()
    s.set({ userId: U1, conversationId: A, seat: 'mentor' }, 'x')
    s.set({ userId: U1, conversationId: B, seat: 'champion' }, 'y')
    s.purgeAll()
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe(undefined)
    expect(s.get({ userId: U1, conversationId: B, seat: 'champion' })).toBe(undefined)
  })
})

describe('adoption is a move (C4)', () => {
  it('moves an unselected draft into an empty seat draft and clears the unselected entry', () => {
    const s = seeded()
    s.set({ userId: U1, conversationId: A, seat: UNSELECTED_DRAFT_SEAT }, 'typed before picking')
    const adopted = s.adopt(U1, A, 'mentor')
    expect(adopted).toBe('typed before picking')
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe('typed before picking')
    expect(s.get({ userId: U1, conversationId: A, seat: UNSELECTED_DRAFT_SEAT })).toBe(undefined)
  })

  it('when the destination already has a draft, the saved draft wins and both are preserved', () => {
    const s = seeded()
    s.set({ userId: U1, conversationId: A, seat: UNSELECTED_DRAFT_SEAT }, 'unselected text')
    s.set({ userId: U1, conversationId: A, seat: 'mentor' }, 'saved seat text')
    const adopted = s.adopt(U1, A, 'mentor')
    expect(adopted).toBe('saved seat text')
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe('saved seat text')
    expect(s.get({ userId: U1, conversationId: A, seat: UNSELECTED_DRAFT_SEAT })).toBe('unselected text')
  })

  it('adopting into unselected is a plain read, not a move', () => {
    const s = seeded()
    s.set({ userId: U1, conversationId: A, seat: UNSELECTED_DRAFT_SEAT }, 'still here')
    expect(s.adopt(U1, A, UNSELECTED_DRAFT_SEAT)).toBe('still here')
    expect(s.get({ userId: U1, conversationId: A, seat: UNSELECTED_DRAFT_SEAT })).toBe('still here')
  })

  it('no unselected draft means no adoption and an empty composer', () => {
    const s = seeded()
    expect(s.adopt(U1, A, 'mentor')).toBe(undefined)
    expect(s.get({ userId: U1, conversationId: A, seat: 'mentor' })).toBe(undefined)
  })
})
