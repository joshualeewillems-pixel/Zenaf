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

function stubWide() {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('min-width'),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
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
})
