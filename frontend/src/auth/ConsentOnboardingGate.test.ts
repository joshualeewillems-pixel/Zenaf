// @vitest-environment jsdom
/**
 * Slice 2 corrections — ConsentOnboardingGate copy checks (founder
 * verdict, 2026-11-06). The gate must state plainly that stance
 * selections save immediately, separately from the consent submit —
 * and, because it renders the shared framework surface, it must also
 * carry the enforcement-honesty line (saved, not yet enforced).
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { ConsentOnboardingGate } from './ConsentOnboardingGate'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

async function flush(times = 8) {
  for (let i = 0; i < times; i++) {
    await act(async () => {})
  }
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(
        ok({
          paused: false,
          pause: { paused: false, paused_at: null, surface: null },
          capabilities: [],
        }),
      ),
    ),
  )
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('ConsentOnboardingGate', () => {
  it('S2-G1 stance selections save immediately, separately from the consent submit', async () => {
    act(() => {
      root.render(
        React.createElement(ConsentOnboardingGate, { onSubmit: async () => {} } as never),
      )
    })
    await flush()
    expect(container.textContent).toContain('saved immediately as you set them')
    expect(container.textContent).toContain('separately from the consent above')
  })

  it('S2-G2 the gate carries the shared enforcement-honesty line (saved, not yet enforced)', async () => {
    act(() => {
      root.render(
        React.createElement(ConsentOnboardingGate, { onSubmit: async () => {} } as never),
      )
    })
    await flush()
    expect(container.textContent).toContain('Saved choices, not yet enforced')
    expect(container.textContent).toContain('no part of Zenaf follows them yet')
  })
})
