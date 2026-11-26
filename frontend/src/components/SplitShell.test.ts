// @vitest-environment jsdom
/**
 * SplitShell — the seat-interface split: world left, conversation
 * right, a draggable divider between them on wide screens; stacked
 * on narrow ones. Verified here: both panes render, the divider
 * drags (and arrow-keys) the conversation width within its clamps,
 * and the width persists per storage key.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import SplitShell from './SplitShell'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/* A controllable matchMedia fake: a virtual viewport (width +
 * orientation) evaluated against the split rule's two queries,
 * with real change listeners so rotation can be simulated. */
type Orientation = 'landscape' | 'portrait'
let viewport: { width: number; orientation: Orientation } = {
  width: 1280,
  orientation: 'portrait',
}
type ChangeListener = (e: { matches: boolean; media: string }) => void
class FakeMQL {
  media: string
  matches: boolean
  listeners = new Set<ChangeListener>()
  constructor(query: string) {
    this.media = query
    this.matches = evaluateQuery(query)
  }
  addEventListener(_type: string, cb: ChangeListener) {
    this.listeners.add(cb)
  }
  removeEventListener(_type: string, cb: ChangeListener) {
    this.listeners.delete(cb)
  }
}
let mqlRegistry = new Set<FakeMQL>()
function evaluateQuery(query: string): boolean {
  if (query === '(min-width: 1024px)') return viewport.width >= 1024
  if (query === '(orientation: landscape) and (min-width: 640px)') {
    return viewport.orientation === 'landscape' && viewport.width >= 640
  }
  return false
}
function stubViewport(width: number, orientation: Orientation) {
  viewport = { width, orientation }
  mqlRegistry = new Set()
  vi.stubGlobal('matchMedia', (query: string) => {
    const mql = new FakeMQL(query)
    mqlRegistry.add(mql)
    return mql
  })
}
/** Move the virtual viewport and fire `change` on every MQL whose
 *  matches flipped — what a device rotation does. */
function setViewport(width: number, orientation: Orientation) {
  viewport = { width, orientation }
  for (const mql of mqlRegistry) {
    const next = evaluateQuery(mql.media)
    if (next !== mql.matches) {
      mql.matches = next
      for (const cb of mql.listeners) cb({ matches: next, media: mql.media })
    }
  }
}
function stubWide() {
  stubViewport(1280, 'portrait')
}

describe('SplitShell', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    stubWide()
    window.localStorage.clear()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  function render() {
    act(() => {
      root.render(
        React.createElement(SplitShell, {
          storageKey: 'test-shell',
          left: React.createElement('div', null, 'the world'),
          right: React.createElement('div', null, 'the conversation'),
        }),
      )
    })
  }

  function rightPane(): HTMLElement {
    return container.querySelector('[data-testid="split-right"]') as HTMLElement
  }
  function divider(): HTMLElement {
    return container.querySelector('[data-testid="split-divider"]') as HTMLElement
  }
  function pointer(type: string, x: number): MouseEvent {
    return new window.MouseEvent(type, { bubbles: true, clientX: x, clientY: 0 })
  }

  it('renders both panes with the conversation at its default width on wide screens', () => {
    render()
    expect(container.textContent).toContain('the world')
    expect(container.textContent).toContain('the conversation')
    expect(rightPane().style.width).toBe('380px')
    expect(divider().getAttribute('role')).toBe('separator')
  })

  it('drags the divider to widen and narrow the conversation, clamped', () => {
    render()
    act(() => divider().dispatchEvent(pointer('pointerdown', 500)))
    act(() => divider().dispatchEvent(pointer('pointermove', 420)))
    // Dragging left by 80 widens the right pane by 80.
    expect(rightPane().style.width).toBe('460px')
    act(() => divider().dispatchEvent(pointer('pointermove', 900)))
    expect(rightPane().style.width).toBe('300px') // min clamp
    act(() => divider().dispatchEvent(pointer('pointerup', 900)))
    expect(window.localStorage.getItem('zenaf:split-chat-width:test-shell')).toBe('300')
  })

  it('arrow keys resize the conversation pane', () => {
    render()
    act(() => {
      divider().dispatchEvent(
        new window.KeyboardEvent('keydown', { bubbles: true, key: 'ArrowLeft' }),
      )
    })
    expect(rightPane().style.width).toBe('396px')
    act(() => {
      divider().dispatchEvent(
        new window.KeyboardEvent('keydown', { bubbles: true, key: 'ArrowRight' }),
      )
    })
    expect(rightPane().style.width).toBe('380px')
  })

  /* The engagement quadrants (founder, 2026-11-25): wide OR
   * landscape splits; portrait and sub-640 landscape stack. */
  function shellRoot(): HTMLElement {
    return container.firstElementChild as HTMLElement
  }

  it('(a) ≥1024px portrait → split', () => {
    stubViewport(1280, 'portrait')
    render()
    expect(shellRoot().getAttribute('data-split')).toBe('true')
    expect(divider()).not.toBeNull()
    expect(rightPane().style.width).toBe('380px')
  })

  it('(b) landscape 800×400 → split — divider present, right pane at its width', () => {
    stubViewport(800, 'landscape')
    render()
    expect(shellRoot().getAttribute('data-split')).toBe('true')
    expect(divider()).not.toBeNull()
    expect(rightPane().style.width).toBe('380px')
  })

  it('(c) portrait 800×1000 → stacked — no divider, no pane width', () => {
    stubViewport(800, 'portrait')
    render()
    expect(shellRoot().getAttribute('data-split')).toBe('false')
    expect(container.querySelector('[data-testid="split-divider"]')).toBeNull()
    expect(rightPane().style.width).toBe('')
    expect(container.textContent).toContain('the world')
    expect(container.textContent).toContain('the conversation')
  })

  it('(d) landscape 500×300 → stacked (below the 640 floor)', () => {
    stubViewport(500, 'landscape')
    render()
    expect(shellRoot().getAttribute('data-split')).toBe('false')
    expect(container.querySelector('[data-testid="split-divider"]')).toBeNull()
    expect(rightPane().style.width).toBe('')
  })

  it('(e) rotating at 800px wide flips the layout live, without remounting', () => {
    stubViewport(800, 'portrait')
    render()
    expect(shellRoot().getAttribute('data-split')).toBe('false')
    const worldNode = container.querySelector('[data-testid="split-right"]')
    act(() => setViewport(800, 'landscape'))
    expect(shellRoot().getAttribute('data-split')).toBe('true')
    expect(divider()).not.toBeNull()
    expect(rightPane().style.width).toBe('380px')
    // Same mounted tree — the panes were never remounted.
    expect(container.querySelector('[data-testid="split-right"]')).toBe(worldNode)
    act(() => setViewport(800, 'portrait'))
    expect(shellRoot().getAttribute('data-split')).toBe('false')
    expect(container.querySelector('[data-testid="split-divider"]')).toBeNull()
  })
})
