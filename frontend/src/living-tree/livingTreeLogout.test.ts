// @vitest-environment jsdom
/**
 * YOU sheet logout wiring (founder bug report, 2026-11-24): the YOU
 * directory's "Log in / out" row used to be an info row — tapping it
 * only expanded "You are signed in on this device." and never signed
 * out, because LivingTreeView had no logout handler at all. These
 * tests pin the fix at component level:
 *
 *   - the row is an action: clicking it calls the shell's onLogout
 *     (App's handleLogout → POST /auth/logout → signed-out state);
 *   - the YOU sheet opens on OPEN_YOU_SHEET_EVENT — the ask the app
 *     header's profile picture sends (through App) — landing on the
 *     same directory the trunk photo opens;
 *   - the trunk photo (the you-node) still opens that same sheet.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 * Harness mirrors livingTreeNavigation.test.ts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { LivingTreeView, OPEN_YOU_SHEET_EVENT } from './LivingTree'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

let container: HTMLDivElement
let root: Root
let onLogout: ReturnType<typeof vi.fn>

function installFetch() {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(ok({ archetypes: [] }))
    }
    if (url.includes('/vision-execution/keystone-attention')) {
      return Promise.resolve(ok({ seeded: true, markers: {} }))
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
        onNavigate: () => {},
        renderSheetContent: () => React.createElement('div', null, 'stub'),
        currentUserId: 'user-1',
        onLogout,
      } as never),
    )
  })
}

function loginRow(): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll('button')).find((b) =>
    b.textContent?.includes('Log in / out'),
  ) as HTMLButtonElement | undefined
}

async function click(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
  await flush()
}

/** SVG node groups have no .click() in jsdom — same fallback the
    navigation tests use. */
async function clickNode(el: Element) {
  const withClick = el as unknown as { click?: () => void }
  await act(async () => {
    if (typeof withClick.click === 'function') withClick.click()
    else el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
  })
  await flush()
}

beforeEach(() => {
  installFetch()
  onLogout = vi.fn(async () => {})
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('YOU sheet Log in / out', () => {
  it('the header-picture ask (OPEN_YOU_SHEET_EVENT) opens the YOU sheet, and its Log in / out row calls the shell logout', async () => {
    renderTree()
    await flush()
    // Sheet closed: no directory rows yet.
    expect(loginRow()).toBeUndefined()

    await act(async () => {
      window.dispatchEvent(new Event(OPEN_YOU_SHEET_EVENT))
    })
    await flush()

    const row = loginRow()
    expect(row).toBeTruthy()
    expect(row!.textContent).toContain('You are signed in on this device.')
    expect(onLogout).not.toHaveBeenCalled()

    await click(row!)
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('the trunk photo (you-node) opens the same sheet, and the row logs out from there too', async () => {
    renderTree()
    await flush()
    expect(loginRow()).toBeUndefined()

    const youNode = container.querySelector('g.lnode[data-node-id="you"]')
    expect(youNode).toBeTruthy()
    await clickNode(youNode as Element)

    const row = loginRow()
    expect(row).toBeTruthy()
    await click(row!)
    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})
