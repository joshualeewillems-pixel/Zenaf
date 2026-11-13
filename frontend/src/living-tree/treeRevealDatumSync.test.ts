// @vitest-environment jsdom
/**
 * Regression (2026-11-12): met seats kept their fallback letters on the
 * Living Tree forever. The tree seeds `nodes` from the fallback layout
 * (all face_revealed: false); when the live status fetch resolves with
 * DATA-only changes — a completed first meeting flips face_revealed,
 * depths still 0 — the layout is position-identical to the fallback's,
 * so the transition effect's position check concluded "nothing moved"
 * and returned without syncing the node data. The server reported all
 * seven seats revealed (verified live on the owner account) while the
 * tree rendered the fallback datums: no logos, ever, in any session.
 *
 * This test reproduces that exact shape: the status payload is the
 * fallback itself with only face_revealed flipped — same seats, same
 * depths (0), same twigs (none) — so not one node moves, and only a
 * datum sync can put the logos on the tree.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { LivingTreeView } from './LivingTree'
import { STOCK_ARCHETYPE_FALLBACK } from './archetypes'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

const SEAT_LOGO_MARKS = [
  'mentor-logo',
  'champion-logo',
  'guardian-logo',
  'maverick-logo',
  'ambassador-logo',
  'conductor-logo',
  'skeptic-logo',
]

const SEAT_INITIALS = ['ME', 'CH', 'GU', 'MA', 'AM', 'CO', 'SK']

let container: HTMLDivElement
let root: Root

function installFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes('/council/archetypes/status')) {
      // The zero-depth, all-met account: identical to the fallback in
      // every layout-relevant field; only the reveal flag differs.
      return Promise.resolve(
        ok({
          archetypes: STOCK_ARCHETYPE_FALLBACK.map((a) => ({ ...a, face_revealed: true })),
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
 * (Same flush as seatLogoNodes.test.ts.)
 */
async function flush() {
  for (let i = 0; i < 8; i++) {
    await act(async () => {})
  }
  await act(async () => {
    await new Promise((r) => setTimeout(r, 200))
  })
}

function renderTree() {
  act(() => {
    root.render(
      React.createElement(LivingTreeView, {
        onNavigate: () => {},
        currentUserId: 'user-1',
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

describe('tree datum sync on a data-only status update', () => {
  it('met seats show their logos even though no node moved', async () => {
    renderTree()
    await flush()
    const hrefs = nodeImageHrefs()
    for (const mark of SEAT_LOGO_MARKS) {
      expect(hrefs.some((h) => h.includes(mark))).toBe(true)
    }
    // 7 seat logos + the 7 always-on strand logos; nothing else.
    expect(hrefs).toHaveLength(14)
    const initials = nodeInitials()
    for (const letters of SEAT_INITIALS) {
      expect(initials).not.toContain(letters)
    }
    // The render itself is alive: the photo-less you-node keeps YOU.
    expect(initials).toContain('YOU')
  })
})
