// @vitest-environment jsdom
/**
 * isCoarsePointer — the phone/desktop split for the composer Enter key.
 * On a phone there is no Shift key, so Enter must insert a newline and
 * only the Send button sends (2026-11-05, Joshua). On desktop Enter sends.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { isCoarsePointer } from './isCoarsePointer'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubMatchMedia(coarse: boolean) {
  vi.stubGlobal(
    'matchMedia',
    (query: string) =>
      ({
        matches: coarse && query === '(pointer: coarse)',
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
        onchange: null,
      }) as MediaQueryList,
  )
}

describe('isCoarsePointer', () => {
  it('returns true on a coarse-pointer (touch) device', () => {
    stubMatchMedia(true)
    expect(isCoarsePointer()).toBe(true)
  })

  it('returns false on a fine-pointer (desktop) device', () => {
    stubMatchMedia(false)
    expect(isCoarsePointer()).toBe(false)
  })

  it('returns false when matchMedia is missing (no crash)', () => {
    vi.stubGlobal('matchMedia', undefined)
    expect(isCoarsePointer()).toBe(false)
  })
})
