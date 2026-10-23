import { describe, expect, it } from 'vitest'
import { resolveSeatFace, resolveSeatPanel, type SeatFaceSource } from './seatFaces'

/**
 * The reveal gate (2026-10-23 reconciliation): the assigned fellowship
 * face shows once the seat's first meeting is complete (face_revealed)
 * OR the depth milestone is earned (avatar_unlocked). Before the fix
 * only the depth door existed, so a completed meeting revealed nothing.
 */
function arch(partial: Partial<SeatFaceSource>): SeatFaceSource {
  return { id: 'conductor', avatar_url: null, avatar_unlocked: false, ...partial }
}

describe('resolveSeatFace', () => {
  it('shows the fellowship face after the first meeting', () => {
    expect(resolveSeatFace(arch({ face_revealed: true }))).toBeTruthy()
  })

  it('shows the fellowship face at the depth milestone', () => {
    expect(resolveSeatFace(arch({ avatar_unlocked: true }))).toBeTruthy()
  })

  it('stays ??? before either door opens', () => {
    expect(resolveSeatFace(arch({ face_revealed: false }))).toBeNull()
  })

  it('falls back to the depth door for older payloads without the flag', () => {
    expect(resolveSeatFace(arch({ avatar_unlocked: true, face_revealed: undefined }))).toBeTruthy()
    expect(resolveSeatFace(arch({ face_revealed: undefined }))).toBeNull()
  })

  it('a custom avatar always wins', () => {
    const url = 'https://example.com/custom.png'
    expect(resolveSeatFace(arch({ avatar_url: url, face_revealed: true }))).toBe(url)
    expect(resolveSeatFace(arch({ avatar_url: url }))).toBe(url)
  })
})

describe('resolveSeatPanel', () => {
  it('reveals the panel with the face, by either door', () => {
    expect(resolveSeatPanel(arch({ face_revealed: true }))).toBeTruthy()
    expect(resolveSeatPanel(arch({ avatar_unlocked: true }))).toBeTruthy()
    expect(resolveSeatPanel(arch({}))).toBeNull()
  })
})
