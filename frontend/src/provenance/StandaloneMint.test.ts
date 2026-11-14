// @vitest-environment jsdom
/**
 * StandaloneMint (moved verbatim from JournalTab, 2026-11-12): the
 * mint → anchoring question → anchor/skip flow, with the journal
 * entries either passed in (journal tab) or loaded by the component
 * itself (Maverick sheet).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import StandaloneMint from './StandaloneMint'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

let container: HTMLDivElement
let root: Root
let calls: Array<{ url: string; init?: RequestInit }>

function installFetch() {
  calls = []
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init })
    if (url.includes('/mint-standalone/art-1/anchor')) {
      return Promise.resolve(ok({ anchored: false }))
    }
    if (url.includes('/pipeline/mint-standalone') && init?.method === 'POST') {
      return Promise.resolve(
        ok({
          artifact: { artifact_id: 'art-1' },
          anchoring_question: 'What moment does this hold?',
        }),
      )
    }
    if (url.includes('/pipeline/journal')) {
      return Promise.resolve(ok({ entries: [] }))
    }
    return Promise.resolve(ok({}))
  })
  vi.stubGlobal('fetch', fetchMock)
}

async function flush(times = 10) {
  for (let i = 0; i < times; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
  }
}

function renderMint(props?: { entries?: Array<{ entry_id: string; text: string; created_at: string }> }) {
  act(() => {
    root.render(React.createElement(StandaloneMint, props ?? {}))
  })
}

function buttonByText(text: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll('button')).find(
    (b) => (b.textContent ?? '').trim() === text,
  )
  if (!btn) throw new Error(`button "${text}" not found`)
  return btn as HTMLButtonElement
}

async function click(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
  await flush()
}

beforeEach(() => {
  installFetch()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('standalone mint flow', () => {
  it('mint → anchoring question → Skip → minted standalone (entries passed in)', async () => {
    renderMint({
      entries: [
        {
          entry_id: 'e1',
          text: 'A walk at dawn along the cliffs',
          created_at: '2026-11-01T10:00:00Z',
        },
      ],
    })
    await flush()
    expect(container.textContent).toContain('Mint something standalone')
    expect(container.querySelector('input[type="text"]')).not.toBeNull()
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    expect(fileInput).not.toBeNull()
    // No Mint button until a file is chosen.
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => (b.textContent ?? '').trim() === 'Mint it',
      ),
    ).toBe(false)

    const file = new File(['fake-bytes'], 'photo.png', { type: 'image/png' })
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true })
    await act(async () => {
      fileInput.dispatchEvent(new window.Event('change', { bubbles: true }))
    })
    await flush()
    await click(buttonByText('Mint it'))
    expect(container.textContent).toContain('What moment does this hold?')
    // The passed-in entry is offered as an anchor target.
    const select = container.querySelector('select')
    expect(select).not.toBeNull()
    expect(select?.textContent).toContain('A walk at dawn along the cliffs')
    expect(
      calls.some((c) => c.url.includes('/pipeline/mint-standalone') && c.init?.method === 'POST'),
    ).toBe(true)

    await click(buttonByText('Skip'))
    expect(
      calls.some((c) => c.url.includes('/mint-standalone/art-1/anchor')),
    ).toBe(true)
    expect(container.textContent).toContain('Minted standalone — no journal link.')
    // Mint another resets the flow.
    await click(buttonByText('Mint another'))
    expect(container.textContent).toContain('Mint something standalone')
  })

  it('without entries it loads the journal itself and still mints', async () => {
    renderMint()
    await flush()
    expect(calls.some((c) => c.url.includes('/pipeline/journal'))).toBe(true)
    expect(container.textContent).toContain('Mint something standalone')
  })
})
