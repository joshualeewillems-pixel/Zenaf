// @vitest-environment jsdom
/**
 * Seat logos + you-node photo on the Living Tree (2026-11-12 founder
 * refinements): a met seat's node shows its logo instead of its letters,
 * an unmet seat keeps its letters, and the center you-node wears the
 * user's profile photo (the same avatar_data_url the header uses) instead
 * of the "YOU" text — falling back to the letters when no photo is set.
 * The "YOU · TAP FOR OPTIONS" pill is untouched.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { LivingTreeView } from './LivingTree'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

const YOU_PHOTO = 'https://example.com/you.jpg'

function seat(partial: Record<string, unknown>) {
  return {
    id: 'mentor',
    display_name: 'Mentor',
    strand_weights: { self: 0.5, word: 0.5 },
    depth: 40,
    band: 'developing',
    prompt_frame: 'The long view.',
    twigs: [],
    is_skeptic: false,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
    ...partial,
  }
}

let container: HTMLDivElement
let root: Root

function installFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(
        ok({
          archetypes: [
            seat({ face_revealed: true }),
            seat({
              id: 'champion',
              display_name: 'Champion',
              strand_weights: { body: 1 },
              depth: 0,
              band: 'not yet trained',
              prompt_frame: 'Courage, action.',
              face_revealed: false,
            }),
          ],
        }),
      )
    }
    if (url.includes('/vision-execution/keystone-attention')) {
      return Promise.resolve(ok({ seeded: true, markers: {} }))
    }
    return Promise.resolve(ok({}))
  })
  vi.stubGlobal('fetch', fetchMock)
}

/**
 * The archetype fetch resolves through a promise chain; a microtask-only
 * flush does not let it land in this environment (the fallback stays),
 * and a bare timer wait is flaky — the chain needs both: ticks to drive
 * the promise chain, then a timer for React to commit the update.
 */
async function flush() {
  for (let i = 0; i < 8; i++) {
    await act(async () => {})
  }
  await act(async () => {
    await new Promise((r) => setTimeout(r, 200))
  })
}

function renderTree(userAvatarUrl?: string) {
  act(() => {
    root.render(
      React.createElement(LivingTreeView, {
        onNavigate: () => {},
        currentUserId: 'user-1',
        ...(userAvatarUrl ? { userAvatarUrl } : {}),
      } as never),
    )
  })
}

/** The hrefs of every <image> inside a tree node. */
function nodeImageHrefs(): string[] {
  return Array.from(container.querySelectorAll('g.lnode image')).map(
    (el) => el.getAttribute('href') ?? '',
  )
}

/** The initials text of every tree node that shows letters. */
function nodeInitials(): string[] {
  return Array.from(container.querySelectorAll('g.lnode text.nm')).map(
    (el) => el.textContent ?? '',
  )
}

beforeEach(() => {
  installFetch()
  ;(window.Element.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView =
    () => {}
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('seat logos on the tree', () => {
  it('a met seat shows its logo, an unmet seat keeps its letters', async () => {
    renderTree(YOU_PHOTO)
    await flush()
    const hrefs = nodeImageHrefs()
    expect(hrefs.some((h) => h.includes('mentor-logo'))).toBe(true)
    const initials = nodeInitials()
    expect(initials).toContain('CH')
    expect(initials).not.toContain('ME')
  })

  it('the you-node wears the profile photo instead of the YOU text', async () => {
    renderTree(YOU_PHOTO)
    await flush()
    expect(nodeImageHrefs()).toContain(YOU_PHOTO)
    expect(nodeInitials()).not.toContain('YOU')
    // The pill below the node is untouched.
    expect(container.textContent).toContain('YOU · TAP FOR OPTIONS')
  })

  it('without a photo the you-node falls back to the YOU letters', async () => {
    renderTree()
    await flush()
    const hrefs = nodeImageHrefs()
    expect(hrefs).toHaveLength(1)
    expect(hrefs[0]).toContain('mentor-logo')
    expect(nodeInitials()).toContain('YOU')
    expect(container.textContent).toContain('YOU · TAP FOR OPTIONS')
  })
})
