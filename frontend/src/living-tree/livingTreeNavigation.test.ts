// @vitest-environment jsdom
/**
 * Living Tree navigation correction at component level (T2/T5/T6/T7
 * + C1/C2 wiring): seat taps open the conversation directly (no menu
 * interstitial), the compact head carries the "Other actions" menu,
 * the invitation shortcut fires an override + navigation nonce, the
 * you-node keeps its Talk entry and menu-back, and a long press opens
 * no menu.
 *
 * The sheet content is a stub provider (not the real TreeTalkSheet):
 * it records every (node, item, opts) call and renders a stub chat
 * that reports a fixed conversation id back through onChatIdChange.
 * The App-side key remount on nonce bump is covered by
 * TreeTalkSheet.test.ts (fresh mount consumes the new override).
 *
 * Sheet header actions (2026-11-12): the seat sheet's header carries
 * the full-character open next to the seat name and Viability at the
 * top right; the compact head keeps only the quote, the meeting door
 * and the Other-actions button, which sits left of the avatar.
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

const TALK_A = 'talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const TALK_B = 'talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

type ProviderCall = {
  nodeKind: string
  seatKey?: string
  item: string
  opts: Record<string, unknown>
}

let container: HTMLDivElement
let root: Root
let providerCalls: ProviderCall[]
let stubReportId: string | null
let navigations: string[]

function StubChat({
  reportId,
  onChatIdChange,
}: {
  reportId: string | null
  onChatIdChange?: (id: string | null) => void
}) {
  React.useEffect(() => {
    onChatIdChange?.(reportId)
  }, [reportId, onChatIdChange])
  return React.createElement('div', null, 'stub chat')
}

function stubProvider(node: unknown, item: string, opts?: Record<string, unknown>) {
  const n = node as { kind: string; seatKey?: string }
  providerCalls.push({ nodeKind: n.kind, seatKey: n.seatKey, item, opts: opts ?? {} })
  if (item === 'talk' && n.kind === 'seat') {
    return React.createElement(StubChat, {
      reportId: stubReportId,
      onChatIdChange: opts?.onChatIdChange as ((id: string | null) => void) | undefined,
    })
  }
  return React.createElement('div', null, `stub-${item}`)
}

function installFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes('/council/archetypes/status')) {
      // Empty list: the honest seed fallback renders (7 seats).
      return Promise.resolve(ok({ archetypes: [] }))
    }
    if (url.includes('/vision-execution/keystone-attention')) {
      return Promise.resolve(
        ok({
          seeded: true,
          markers: {
            mentor: {
              attention: false,
              reason: null,
              invitation_count: 1,
              invitation_conversation_ids: [TALK_A],
            },
          },
        }),
      )
    }
    return Promise.resolve(ok({}))
  })
  vi.stubGlobal('fetch', fetchMock)
}

async function flush(times = 8) {
  for (let i = 0; i < times; i++) {
    await act(async () => {})
  }
}

function renderTree() {
  act(() => {
    root.render(
      React.createElement(LivingTreeView, {
        onNavigate: (view: string) => {
          navigations.push(view)
        },
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

function rowByTitle(title: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll('button.lrow')).find(
    (b) => b.querySelector('.lrow-t')?.textContent === title,
  )
  if (!btn) throw new Error(`menu row "${title}" not found`)
  return btn as HTMLButtonElement
}

function dialog(): Element | null {
  return container.querySelector('[role="dialog"]')
}

function talkCalls(seatKey?: string): ProviderCall[] {
  return providerCalls.filter(
    (c) => c.item === 'talk' && (seatKey === undefined || c.seatKey === seatKey),
  )
}

beforeEach(() => {
  providerCalls = []
  navigations = []
  stubReportId = TALK_B
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

describe('direct seat tap (T2)', () => {
  it('a seat tap opens its conversation directly: no menu, head + Other actions present', async () => {
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    expect(dialog()).not.toBeNull()
    expect(dialog()?.textContent).toContain('The Gardener')
    // The compact head's Other actions button is always visible.
    expect(buttonByLabel('Other actions')).toBeDefined()
    // Direct navigation: the provider was called for 'talk' (the menu
    // path never calls the provider), and the old Talk menu copy is gone.
    expect(talkCalls('mentor').length).toBeGreaterThan(0)
    expect(dialog()?.textContent).not.toContain('Meet the seat, then talk it through.')
  })

  it('a long press opens no menu and the following tap navigates exactly once to the conversation', async () => {
    renderTree()
    await flush()
    const node = nodeByInitials('ME')
    // 600ms-style hold, then a longer hold: mousedown + mouseup with
    // no click must never open anything (no long-press handler exists).
    act(() => {
      node.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true }))
    })
    await flush()
    expect(dialog()).toBeNull()
    act(() => {
      node.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true }))
    })
    await flush()
    expect(dialog()).toBeNull()
    expect(talkCalls('mentor')).toHaveLength(0)
    clickNode('ME')
    await flush()
    expect(dialog()).not.toBeNull()
    expect(talkCalls('mentor').length).toBeGreaterThan(0)
  })
})

describe('compact-head menu (T6 + C1/C2)', () => {
  it('the head menu lists Today/Review/Upload, no Talk, and routes a sheet item', async () => {
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    await click(buttonByLabel('Other actions'))
    expect(rowByTitle('Today')).toBeDefined()
    expect(rowByTitle('Review')).toBeDefined()
    expect(rowByTitle('Upload')).toBeDefined()
    expect(
      Array.from(container.querySelectorAll('button.lrow')).some(
        (b) => b.querySelector('.lrow-t')?.textContent === 'Talk',
      ),
    ).toBe(false)
    await click(rowByTitle('Today'))
    expect(providerCalls.some((c) => c.item === 'today' && c.seatKey === 'mentor')).toBe(true)
    // Seat sheets have no menu-back: X is the only way back to the Tree.
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => b.getAttribute('aria-label') === 'Back to menu',
      ),
    ).toBe(false)
  })

  it('the mentor head menu carries its seat-owned destinations', async () => {
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    await click(buttonByLabel('Other actions'))
    expect(rowByTitle('Vision map')).toBeDefined()
    expect(rowByTitle('Vision (tables)')).toBeDefined()
    await click(rowByTitle('Vision map'))
    expect(navigations).toContain('vision_map')
  })

  it('the invitation shortcut fires an override + nonce bump (C1) from an open conversation', async () => {
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    // Stub chat reports TALK_B as the open conversation; the mentor
    // invitation lives in TALK_A, so the shortcut must show.
    await click(buttonByLabel('Other actions'))
    await click(rowByTitle('View invitation in another conversation'))
    const shortcutCalls = providerCalls.filter(
      (c) =>
        c.item === 'talk' &&
        c.seatKey === 'mentor' &&
        (c.opts.conversationOverride as { conversationId?: string } | undefined)?.conversationId ===
          TALK_A,
    )
    expect(shortcutCalls.length).toBeGreaterThan(0)
    expect(shortcutCalls.some((c) => typeof c.opts.navNonce === 'number' && (c.opts.navNonce as number) > 0)).toBe(true)
  })

  it('the shortcut hides when the invitation target IS the open conversation (C2 visibility)', async () => {
    stubReportId = TALK_A
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    await click(buttonByLabel('Other actions'))
    expect(
      Array.from(container.querySelectorAll('button.lrow')).some(
        (b) => b.querySelector('.lrow-t')?.textContent === 'View invitation in another conversation',
      ),
    ).toBe(false)
  })
})

describe('you-node menu preserved', () => {
  it('the you-node keeps its Talk entry and its menu-back', async () => {
    renderTree()
    await flush()
    clickNode('YOU')
    await flush()
    expect(dialog()).not.toBeNull()
    // Menu first: the provider is never called for a menu.
    expect(providerCalls).toHaveLength(0)
    expect(container.textContent).toContain('Think something through with your whole council.')
    const talkRow = Array.from(container.querySelectorAll('button.lrow')).find(
      (b) => b.querySelector('.lrow-t')?.textContent === 'Talk',
    )
    if (!talkRow) throw new Error('you-node Talk row not found')
    await click(talkRow)
    expect(providerCalls.some((c) => c.item === 'talk' && c.nodeKind === 'you')).toBe(true)
    const back = Array.from(container.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'Back to menu',
    )
    expect(back).toBeDefined()
    await click(back as Element)
    expect(container.textContent).toContain('Think something through with your whole council.')
  })
})

describe('sheet header actions (2026-11-12)', () => {
  it('the seat header carries Full character next to the name and Viability at the top right', async () => {
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    const dlg = dialog()
    expect(dlg).not.toBeNull()
    const head = dlg?.querySelector('.nsh-head')
    const kids = Array.from(head?.children ?? []).map((c) => (c as Element).className)
    const actionsIdx = kids.indexOf('nsh-actions')
    const closeIdx = kids.indexOf('nsh-close')
    expect(actionsIdx).toBeGreaterThan(-1)
    expect(closeIdx).toBeGreaterThan(-1)
    // Actions sit between the titles and the close control.
    expect(actionsIdx).toBeGreaterThan(kids.indexOf('nsh-titles'))
    expect(actionsIdx).toBeLessThan(closeIdx)
    const actions = dlg?.querySelector('.nsh-actions')
    expect(actions?.textContent).toContain('Full character →')
    expect(actions?.textContent).toContain('Viability')
    // Seed fallback: 0% with the training note, same value as before.
    expect(actions?.textContent).toContain('0%')
    expect(actions?.textContent).toContain('training comes first')
    // Collapsed: exactly one Viability and one Full character control
    // in the whole sheet — the compact head no longer carries either.
    expect((dlg?.textContent?.match(/Viability/g) ?? []).length).toBe(1)
    expect(
      Array.from(dlg?.querySelectorAll('button') ?? []).filter(
        (b) => (b.textContent ?? '').trim() === 'Full character →',
      ),
    ).toHaveLength(1)
  })

  it('the header Full character open drives the same disclosure', async () => {
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    const btn = Array.from(dialog()?.querySelectorAll('button') ?? []).find(
      (b) => (b.textContent ?? '').trim() === 'Full character →',
    )
    if (!btn) throw new Error('header Full character button not found')
    expect(btn.getAttribute('aria-expanded')).toBe('false')
    await click(btn)
    expect(btn.getAttribute('aria-expanded')).toBe('true')
    // The expanded character body renders (Marketplace section).
    expect(dialog()?.textContent).toContain('Marketplace')
  })

  it('Other actions sits left of the avatar in the compact head', async () => {
    renderTree()
    await flush()
    clickNode('ME')
    await flush()
    const head = dialog()?.querySelector('.lavatar-head')
    expect(head).not.toBeNull()
    const first = head?.firstElementChild as Element | null
    expect(first?.getAttribute('aria-label')).toBe('Other actions')
    expect(first?.textContent).toContain('···')
    // The moved button still opens the menu.
    await click(buttonByLabel('Other actions'))
    expect(rowByTitle('Today')).toBeDefined()
  })
})
