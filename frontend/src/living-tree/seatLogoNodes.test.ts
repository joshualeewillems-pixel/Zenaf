// @vitest-environment jsdom
/**
 * Seat logos + you-node photo on the Living Tree (2026-11-12 founder
 * refinements): a met seat's node shows its logo instead of its letters,
 * an unmet seat keeps its letters, and the center you-node wears the
 * user's profile photo (the same avatar_data_url the header uses) instead
 * of the "YOU" text — falling back to the letters when no photo is set.
 * (The "YOU · TAP FOR OPTIONS" pill under the node and the footer text
 * were removed by the founder later the same day — strandLogoNodes.test.ts
 * covers those removals and the strand logos that landed with them.)
 *
 * RE-SCOPED for the Living Sky (2026-11-16, port plan §9; founder
 * ruling 2026-11-16 08:53 PT): the painted scene replaces the
 * computational nodes. The painted emblems are the seats' symbolic
 * identities — always visible in the painting — so the
 * logo-vs-initials rule LEAVES the tree surface (it still governs
 * faces and panels inside the sheets, untouched). What survives on
 * this surface, and what this file now asserts, is the YOU-photo
 * overlay contract: the photo renders over the painted YOU disc when
 * `userAvatarUrl` is set, and is absent otherwise (the painting's own
 * YOU is the fallback — there are no DOM letters anymore). The
 * retired assertions (met-seat logo hrefs, unmet-seat initials, the
 * YOU-letters fallback) tested presentation the founder's ruling
 * replaced; they are retired here, not re-expressed.
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

/** The hrefs of every <image> inside a hit group (the overlay's only
 *  image is the YOU photo — emblems and logos are painted, not DOM). */
function nodeImageHrefs(): string[] {
  return Array.from(container.querySelectorAll('g.lnode image')).map(
    (el) => el.getAttribute('href') ?? '',
  )
}

function youGroup(): Element {
  const g = container.querySelector('g.lnode[data-node-id="you"]')
  if (!g) throw new Error('you hit group not found')
  return g
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

describe('the YOU-photo overlay on the painted scene', () => {
  it('the you hit group wears the profile photo when one is set', async () => {
    renderTree(YOU_PHOTO)
    await flush()
    const img = youGroup().querySelector('image')
    expect(img?.getAttribute('href')).toBe(YOU_PHOTO)
    // The overlay carries no initials text anywhere — the emblems and
    // letters are the painting's now.
    expect(container.querySelectorAll('g.lnode text.nm')).toHaveLength(0)
    // The pill below the node is gone (founder, 2026-11-12).
    expect(container.textContent).not.toContain('TAP FOR OPTIONS')
  })

  it('without a photo the overlay carries no image — the painted YOU disc is the fallback', async () => {
    renderTree()
    await flush()
    expect(youGroup().querySelector('image')).toBeNull()
    expect(nodeImageHrefs()).toEqual([])
    expect(container.textContent).not.toContain('TAP FOR OPTIONS')
  })
})
