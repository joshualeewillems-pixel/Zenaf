// @vitest-environment jsdom
/**
 * Seat talk sheet header cleanup (founder, 2026-11-12):
 *
 * - The sheet chrome no longer shows the fellowship title/subtitle
 *   ("The Gardener" / "Mentor") on seat TALK sheets — the seat's
 *   identity row (Other actions, emblem, name/tag) renders in the
 *   header where the title block sat, alongside Viability and the
 *   close control. Other sheets (the you-node menu, a seat's
 *   non-talk items) keep their chrome titles.
 * - The "training comes first" caption under Viability is gone;
 *   the Viability label and value stay.
 * - The identity row's circle shows the seat's LOGO (the emblem,
 *   like the tree node), not its portrait face; an unrevealed seat
 *   keeps the ??? placeholder. The circle is a button with the same
 *   action as the name: it toggles the character-body disclosure.
 * - The meeting door renders only for a genuine first meeting
 *   ('begin'): a met seat shows no door button — its completed
 *   meeting joined the chat list (founder, 2026-11-12) — and sheet
 *   content receives onOpenMeeting so a chat-list meeting row can
 *   open the meeting overlay.
 *
 * Two fetch shapes: the honest seed fallback (empty status list —
 * every seat unrevealed) with an 'intro' marker on the Mentor, and a
 * live payload where the Champion is revealed (face_revealed) and
 * everyone else is not.
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

let container: HTMLDivElement
let root: Root
let lastProviderOpts: Record<string, unknown> | undefined

function stubProvider(node: unknown, item: string, opts?: Record<string, unknown>) {
  lastProviderOpts = opts
  const n = node as { kind: string }
  if (item === 'talk' && n.kind === 'seat') {
    return React.createElement('div', null, 'stub chat')
  }
  return React.createElement('div', null, `stub-${item}`)
}

/** Seed fallback: no seat revealed; the Mentor carries an intro marker. */
function installFallbackFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(ok({ archetypes: [] }))
    }
    if (url.includes('/vision-execution/keystone-attention')) {
      return Promise.resolve(
        ok({
          seeded: true,
          markers: {
            mentor: {
              attention: true,
              reason: 'intro',
              invitation_count: 0,
              invitation_conversation_ids: [],
            },
          },
        }),
      )
    }
    return Promise.resolve(ok({}))
  })
  vi.stubGlobal('fetch', fetchMock)
}

/** Live payload: the Champion is met (face_revealed); nobody else is. */
function installRevealedFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(
        ok({
          archetypes: STOCK_ARCHETYPE_FALLBACK.map((a) =>
            a.id === 'champion' ? { ...a, face_revealed: true } : { ...a },
          ),
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

/** The status fetch resolves through a promise chain; drive it with
 *  ticks plus a timer so React commits the update (same flush as
 *  seatLogoNodes.test.ts). */
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
        renderSheetContent: stubProvider,
        currentUserId: 'user-1',
      } as never),
    )
  })
}

function nodeByInitials(initials: string): Element {
  const nodes = Array.from(container.querySelectorAll('g.lnode'))
  const found = nodes.find((g) => g.querySelector('text.nm')?.textContent === initials)
  if (!found) throw new Error(`tree node "${initials}" not found`)
  return found
}

function clickNode(initials: string) {
  const el = nodeByInitials(initials) as unknown as { click?: () => void }
  act(() => {
    if (typeof el.click === 'function') el.click()
    else nodeByInitials(initials).dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  })
}

/** A revealed seat's tree node carries its logo image, not initials. */
function clickNodeByLogo(mark: string) {
  const nodes = Array.from(container.querySelectorAll('g.lnode'))
  const found = nodes.find((g) =>
    Array.from(g.querySelectorAll('image')).some((img) =>
      (img.getAttribute('href') ?? '').includes(mark),
    ),
  )
  if (!found) throw new Error(`tree node with logo "${mark}" not found`)
  const el = found as unknown as { click?: () => void }
  act(() => {
    if (typeof el.click === 'function') el.click()
    else found.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  })
}

async function click(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
  await flush()
}

function buttonByLabel(label: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll('button')).find(
    (b) => b.getAttribute('aria-label') === label,
  )
  if (!btn) throw new Error(`button with aria-label "${label}" not found`)
  return btn as HTMLButtonElement
}

function dialog(): Element | null {
  return container.querySelector('[role="dialog"]')
}

function head(): Element | null {
  return dialog()?.querySelector('.nsh-head') ?? null
}

beforeEach(() => {
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

describe('seat talk sheet header cleanup (founder, 2026-11-12)', () => {
  it('the chrome title is gone; the identity row sits in the header beside Viability', async () => {
    installFallbackFetch()
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    const h = head()
    expect(h).not.toBeNull()
    // No title/subtitle block: no h2, and the fellowship name appears
    // nowhere as chrome text.
    expect(h?.querySelector('h2')).toBeNull()
    expect(dialog()?.textContent).not.toContain('The Gardener')
    // The identity row is in the header, where the title block was.
    expect(h?.querySelector('.lavatar-head')).not.toBeNull()
    expect(buttonByLabel('Other actions')).toBeDefined()
    // Viability (label + value) and the close control stay.
    const actions = h?.querySelector('.nsh-actions')
    expect(actions?.textContent).toContain('Viability')
    expect(actions?.textContent).toContain('0%')
    expect(actions?.textContent).not.toContain('training comes first')
    expect(h?.querySelector('.nsh-close')).not.toBeNull()
  })

  it('other sheets keep their chrome titles', async () => {
    installFallbackFetch()
    renderTree()
    await flush()
    // The you-node menu sheet keeps its title + subtitle.
    clickNode('YOU')
    await flush()
    expect(head()?.querySelector('h2')?.textContent).toBe('You')
    expect(head()?.querySelector('p')?.textContent).toBe('The source')
    expect(head()?.querySelector('.lavatar-head')).toBeNull()
    // Close it, then a seat's NON-talk sheet item keeps its title too.
    const close = head()?.querySelector('.nsh-close') as HTMLElement | null
    if (!close) throw new Error('close control not found')
    await click(close)
    clickNode('ME')
    await flush()
    await click(buttonByLabel('Other actions'))
    const today = Array.from(dialog()?.querySelectorAll('button.lrow') ?? []).find(
      (b) => b.querySelector('.lrow-t')?.textContent === 'Today',
    )
    if (!today) throw new Error('Today menu row not found')
    await click(today)
    expect(head()?.querySelector('h2')?.textContent).toBe('The Gardener')
    expect(head()?.querySelector('p')?.textContent).toBe('Mentor')
    expect(head()?.querySelector('.lavatar-head')).toBeNull()
  })

  it('an unrevealed seat keeps the ??? placeholder in the identity circle', async () => {
    installFallbackFetch()
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    const row = head()?.querySelector('.lavatar-head')
    expect(row?.querySelector('img')).toBeNull()
    expect(row?.querySelector('.lavatar-qqq')?.textContent).toBe('???')
  })

  it('the emblem button toggles the character disclosure, same as the name', async () => {
    installFallbackFetch()
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    const emblem = buttonByLabel('Mentor emblem')
    const name = Array.from(dialog()?.querySelectorAll('button') ?? []).find(
      (b) => (b.textContent ?? '').trim() === 'Mentor',
    )
    if (!name) throw new Error('display-name button not found')
    expect(emblem.getAttribute('aria-expanded')).toBe('false')
    expect(name.getAttribute('aria-expanded')).toBe('false')
    // Emblem click expands, exactly like the name does.
    await click(emblem)
    expect(emblem.getAttribute('aria-expanded')).toBe('true')
    expect(name.getAttribute('aria-expanded')).toBe('true')
    expect(dialog()?.textContent).toContain('Marketplace')
    // Name click collapses for both.
    await click(name)
    expect(emblem.getAttribute('aria-expanded')).toBe('false')
    expect(dialog()?.textContent).not.toContain('Marketplace')
  })

  it('a revealed seat shows its logo in the identity circle', async () => {
    installRevealedFetch()
    renderTree()
    await flush()
    clickNodeByLogo('champion-logo')
    await flush()
    const row = head()?.querySelector('.lavatar-head')
    const img = row?.querySelector('img.lavatar-img')
    expect(img).toBeTruthy()
    expect(img?.getAttribute('src') ?? '').toContain('champion-logo')
    expect(row?.querySelector('.lavatar-qqq')).toBeNull()
  })

  it('the meeting door still renders for an unmet seat with an intro marker', async () => {
    installFallbackFetch()
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    const door = Array.from(dialog()?.querySelectorAll('button') ?? []).find(
      (b) => (b.textContent ?? '').trim() === 'Begin the first meeting →',
    )
    expect(door).toBeDefined()
  })

  it('a met seat renders NO meeting door — its meeting lives in the chat list', async () => {
    installRevealedFetch()
    renderTree()
    await flush()
    clickNodeByLogo('champion-logo')
    await flush()
    const labels = Array.from(dialog()?.querySelectorAll('button') ?? []).map((b) =>
      (b.textContent ?? '').trim(),
    )
    expect(labels).not.toContain('Begin the first meeting →')
    expect(labels).not.toContain('Your first meeting →')
  })

  it('sheet content receives onOpenMeeting so chat-list meeting rows can open the overlay', async () => {
    installFallbackFetch()
    renderTree()
    await flush()
    // Seat talk sheet (the special-cased provider call).
    clickNode('ME')
    await flush()
    expect(typeof lastProviderOpts?.onOpenMeeting).toBe('function')
    // You-node Talk (the generic provider call).
    const close = head()?.querySelector('.nsh-close') as HTMLElement | null
    if (!close) throw new Error('close control not found')
    await click(close)
    clickNode('YOU')
    await flush()
    const talkRow = Array.from(dialog()?.querySelectorAll('button.lrow') ?? []).find(
      (b) => b.querySelector('.lrow-t')?.textContent === 'Talk',
    )
    if (!talkRow) throw new Error('Talk menu row not found')
    await click(talkRow)
    expect(typeof lastProviderOpts?.onOpenMeeting).toBe('function')
  })
})
