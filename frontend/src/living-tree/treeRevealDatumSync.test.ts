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
 * RE-SCOPED for the Living Sky (2026-11-16, port plan §9 pattern;
 * founder ruling 2026-11-16 08:53 PT): the painted scene replaces the
 * computational nodes, so the original observable — seat/strand logo
 * <image>s and initials text inside g.lnode — no longer exists on this
 * surface (emblems are painted; reveal semantics live in the sheets
 * and panels). The BEHAVIOUR under guard is unchanged: a data-only
 * status update must propagate the reveal to every surface that shows
 * it, even though nothing moves. Its surviving observable is the
 * revealed seat's sheet identity: open each seat's sheet after the
 * same data-only update and the identity circle must carry that
 * seat's logo — not the ??? placeholder the fallback datum would
 * show. (The sheet resolves its archetype from the view's
 * fetch-applied archetypes state; if that datum flow breaks, every
 * sheet below keeps ??? and this test fails — see the mutation check
 * recorded in the Increment 1 verification report.)
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

/** The seven seats: archetype id, hit-group datum id, sheet logo mark. */
const SEATS = [
  { id: 'mentor', nodeId: 'arch-mentor', logoMark: 'mentor-logo' },
  { id: 'champion', nodeId: 'arch-champion', logoMark: 'champion-logo' },
  { id: 'guardian', nodeId: 'arch-guardian', logoMark: 'guardian-logo' },
  { id: 'maverick', nodeId: 'arch-maverick', logoMark: 'maverick-logo' },
  { id: 'ambassador', nodeId: 'arch-ambassador', logoMark: 'ambassador-logo' },
  { id: 'conductor', nodeId: 'arch-conductor', logoMark: 'conductor-logo' },
  { id: 'skeptic', nodeId: 'arch-skeptic', logoMark: 'skeptic-logo' },
] as const

let container: HTMLDivElement
let root: Root
let navigations: string[]

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
        onNavigate: (view: string) => {
          navigations.push(view)
        },
        currentUserId: 'user-1',
      } as never),
    )
  })
}

/** A painted medallion's hit group, by its production datum id. */
function hitGroup(nodeId: string): Element {
  const g = container.querySelector(`g.lnode[data-node-id="${nodeId}"]`)
  if (!g) throw new Error(`hit group "${nodeId}" not found`)
  return g
}

function clickHitGroup(nodeId: string) {
  const el = hitGroup(nodeId) as unknown as { click?: () => void }
  act(() => {
    if (typeof el.click === 'function') el.click()
    else hitGroup(nodeId).dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  })
}

async function clickEl(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
  await flush()
}

function dialog(): Element | null {
  return container.querySelector('[role="dialog"]')
}

function head(): Element | null {
  return dialog()?.querySelector('.nsh-head') ?? null
}

beforeEach(() => {
  navigations = []
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
  it('met seats show their logos in their sheets even though no node moved', async () => {
    renderTree()
    await flush()
    // Every seat's sheet identity carries its logo — the reveal in the
    // data-only payload reached the sheets. Under the fallback datum
    // each identity circle would keep the ??? placeholder instead.
    for (const seat of SEATS) {
      if (seat.id === 'skeptic') {
        // Seat landing (founder, 2026-11-24): the skeptic's tap lands
        // on the Bench — no sheet opens for her anymore.
        clickHitGroup(seat.nodeId)
        await flush()
        expect(navigations).toContain('bench')
        expect(dialog()).toBeNull()
        continue
      }
      clickHitGroup(seat.nodeId)
      await flush()
      const row = head()?.querySelector('.lavatar-head')
      expect(row, `identity row for ${seat.id}`).not.toBeNull()
      const img = row?.querySelector('img.lavatar-img')
      expect(img?.getAttribute('src') ?? '').toContain(seat.logoMark)
      expect(row?.querySelector('.lavatar-qqq')).toBeNull()
      const close = head()?.querySelector('.nsh-close') as HTMLElement | null
      if (!close) throw new Error('close control not found')
      await clickEl(close)
    }
    // Control: the render itself is alive — the photo-less you-node's
    // hit group is present and carries no photo image (the painting's
    // own YOU is the fallback now; there are no DOM letters anymore).
    expect(hitGroup('you').querySelector('image')).toBeNull()
  }, 30_000)
})
