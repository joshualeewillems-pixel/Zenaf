// @vitest-environment jsdom
/**
 * Slice 2 — PauseBanner render tests (C4.2–C4.5).
 * Renders only while paused; Resume is one action; the banner reads
 * the same pause record the Settings surface writes.
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { PauseBanner } from './PauseBanner'
import type { FrameworkState } from './api'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root
let calls: { url: string; method: string | undefined; body: unknown }[]

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

function stateFixture(paused: boolean): FrameworkState {
  return {
    paused,
    pause: { paused, paused_at: paused ? '2026-11-06T20:00:00Z' : null, surface: 'settings' },
    capabilities: [],
  }
}

let serverState: FrameworkState

function installFetch() {
  calls = []
  const fetchMock = vi.fn((url: string, opts?: { method?: string; body?: string }) => {
    let body: unknown = undefined
    try {
      body = opts?.body ? JSON.parse(opts.body) : undefined
    } catch {
      body = undefined
    }
    calls.push({ url, method: opts?.method, body })
    if (url.includes('/permissions/framework/pause')) {
      const paused = Boolean((body as { paused?: unknown } | undefined)?.paused)
      serverState = stateFixture(paused)
      return Promise.resolve(
        ok({ pause: serverState.pause, canceled_operations: [], state: serverState }),
      )
    }
    if (url.includes('/permissions/framework')) {
      return Promise.resolve(ok(serverState))
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

function renderBanner(props: { state?: FrameworkState | null; onResume?: () => void } = {}) {
  act(() => {
    root.render(React.createElement(PauseBanner, props as never))
  })
}

beforeEach(() => {
  serverState = stateFixture(false)
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

describe('PauseBanner', () => {
  it('S2-B1 renders nothing when not paused (fed state)', async () => {
    renderBanner({ state: stateFixture(false) })
    await flush()
    expect(container.textContent).not.toContain('paused')
  })

  it('S2-B2 renders the banner with Resume when paused (fed state)', async () => {
    renderBanner({ state: stateFixture(true) })
    await flush()
    expect(container.textContent).toContain('Standing behavior is paused')
    expect(container.textContent).toContain('Resume standing behavior')
  })

  it('S2-B3 Resume in fed mode calls onResume and does not fetch', async () => {
    const onResume = vi.fn()
    renderBanner({ state: stateFixture(true), onResume })
    await flush()
    const button = container.querySelector('button')
    if (!button) throw new Error('Resume button missing')
    await act(async () => {
      button.click()
    })
    await flush()
    expect(onResume).toHaveBeenCalledTimes(1)
    expect(calls.filter((c) => c.url.includes('/permissions/framework'))).toHaveLength(0)
  })

  it('S2-B4 self-fetching mode: loads state, shows banner when paused, Resume hides it', async () => {
    serverState = stateFixture(true)
    renderBanner()
    await flush()
    expect(container.textContent).toContain('Standing behavior is paused')
    const button = container.querySelector('button')
    if (!button) throw new Error('Resume button missing')
    await act(async () => {
      button.click()
    })
    await flush()
    const pauseCalls = calls.filter((c) => c.url.includes('/permissions/framework/pause'))
    expect(pauseCalls).toHaveLength(1)
    expect(pauseCalls[0].body).toEqual({ paused: false })
    expect(container.textContent).not.toContain('Standing behavior is paused')
  })
})
