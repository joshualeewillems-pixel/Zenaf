// @vitest-environment jsdom
/**
 * Slice 2 — FrameworkPermissionsSurface render tests.
 * C3-T1 (one record, shown twice — a write through the strand display
 * updates the general display), C4 pause control, R.1–R.4 retained
 * choice, and per-capability stance availability.
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 * The mocked fetch is a tiny in-memory server holding one framework
 * state, so the test exercises the same write-then-reread loop as the
 * real API.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { FrameworkPermissionsSurface } from './FrameworkPermissionsSurface'
import type { FrameworkCapability, FrameworkState } from './api'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root
let calls: { url: string; method: string | undefined; body: unknown }[]
let serverState: FrameworkState

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

function row(key: string, label: string, kind: string, stance: 'ask_me' | 'just_do_it' | 'dont_do_it') {
  return { key, label, kind, stance, stance_source: 'default' as const, granted_at: null, last_changed_at: null, surface: null }
}

function capability(id: string, rows: ReturnType<typeof row>[], extra: Partial<FrameworkCapability> = {}): FrameworkCapability {
  return {
    id,
    covers: `${id} covers`,
    does_not_allow: `${id} does not allow`,
    default_stance: 'dont_do_it',
    supported_stances: ['ask_me', 'just_do_it', 'dont_do_it'],
    exception_classes: [],
    retained_count: 0,
    quieted: false,
    paused: false,
    rows,
    ...extra,
  }
}

function fixtureState(): FrameworkState {
  return {
    paused: false,
    pause: { paused: false, paused_at: null, surface: null },
    capabilities: [
      capability(
        'R1',
        [
          row('heart', 'Heart', 'strand', 'ask_me'),
          row('hands', 'Hands', 'strand', 'ask_me'),
          row('logic', 'Logic', 'strand', 'ask_me'),
          row('voice', 'Voice', 'strand', 'ask_me'),
          row('ear', 'Ear', 'strand', 'ask_me'),
          row('compass', 'Compass', 'strand', 'ask_me'),
          row('eye', 'Eye', 'strand', 'ask_me'),
          row('intake', 'Source materials (intake)', 'source', 'ask_me'),
          row('user_upload', 'Source materials (upload)', 'source', 'ask_me'),
        ],
        { default_stance: 'ask_me', retained_count: 2 },
      ),
      capability('R2', [row('narrative_interpretation', 'Narrative interpretation', 'default', 'dont_do_it')]),
      capability('R3', [row('cross_branch_coordination', 'Cross-branch coordination', 'default', 'dont_do_it')]),
      capability(
        'R4',
        ['mentor', 'champion', 'guardian', 'maverick', 'ambassador', 'conductor', 'skeptic'].map(
          (seat) => row(seat, seat, 'seat', 'just_do_it'),
        ),
        { default_stance: 'just_do_it', supported_stances: ['just_do_it', 'dont_do_it'] },
      ),
      capability('R5', [row('task_proposals', 'Task proposals', 'default', 'just_do_it')], {
        default_stance: 'just_do_it',
        supported_stances: ['just_do_it', 'dont_do_it'],
      }),
      capability('R6', [row('watering', 'Watering', 'commitment', 'ask_me')], { retained_count: 3 }),
    ],
  }
}

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
    if (url.includes('/permissions/framework/stance') && opts?.method === 'PUT') {
      const b = body as { capability: string; row_key: string; stance: 'ask_me' | 'just_do_it' | 'dont_do_it' }
      const cap = serverState.capabilities.find((c) => c.id === b.capability)
      const target = cap?.rows.find((r) => r.key === b.row_key)
      if (target) {
        target.stance = b.stance
        target.stance_source = 'user'
      }
      return Promise.resolve(
        ok({
          record: {},
          retained_count: cap?.retained_count ?? 0,
          retained_choice_offered: b.stance === 'dont_do_it' && (cap?.retained_count ?? 0) > 0,
          state: serverState,
        }),
      )
    }
    if (url.includes('/permissions/framework/pause') && opts?.method === 'PUT') {
      const paused = Boolean((body as { paused?: unknown } | undefined)?.paused)
      serverState.paused = paused
      serverState.pause = { paused, paused_at: paused ? '2026-11-06T20:00:00Z' : null, surface: 'settings' }
      for (const cap of serverState.capabilities) cap.paused = paused
      return Promise.resolve(ok({ pause: serverState.pause, canceled_operations: [], state: serverState }))
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

function renderSurface(onOpenToday?: () => void) {
  act(() => {
    root.render(
      React.createElement(FrameworkPermissionsSurface, { onOpenToday } as never),
    )
  })
}

async function click(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
  await flush()
}

function stanceGroups(label: string): Element[] {
  return Array.from(container.querySelectorAll(`[aria-label="${label} stance"]`))
}

function activeStance(group: Element): string | null {
  const active = group.querySelector('button[aria-pressed="true"]')
  return active ? (active.textContent ?? '').trim() : null
}

function buttonIn(group: Element, text: string): HTMLButtonElement {
  const btn = Array.from(group.querySelectorAll('button')).find(
    (b) => (b.textContent ?? '').trim() === text,
  )
  if (!btn) throw new Error(`button "${text}" not found in stance group`)
  return btn as HTMLButtonElement
}

beforeEach(() => {
  serverState = fixtureState()
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

describe('FrameworkPermissionsSurface', () => {
  it('S2-F1 renders all five groups; the strand row appears in both noting displays', async () => {
    renderSurface()
    await flush()
    for (const title of ['Noting — general', 'Strand interviews', 'Steward', 'Fellowship', 'Vision Execution']) {
      expect(container.textContent).toContain(title)
    }
    expect(stanceGroups('Heart')).toHaveLength(2)
    expect(container.textContent).toContain('Source materials (intake)')
  })

  it('S2-F2 C3-T1: a write through the strand display updates the general display (one record)', async () => {
    renderSurface()
    await flush()
    const hearts = stanceGroups('Heart')
    expect(hearts).toHaveLength(2)
    expect(activeStance(hearts[0])).toBe('Ask me')
    expect(activeStance(hearts[1])).toBe('Ask me')
    // The second Heart group is the strand display (it renders after the general group).
    await click(buttonIn(hearts[1], "Don't do it"))
    const stanceCalls = calls.filter((c) => c.url.includes('/permissions/framework/stance'))
    expect(stanceCalls).toHaveLength(1)
    expect(stanceCalls[0].body).toEqual({ capability: 'R1', row_key: 'heart', stance: 'dont_do_it' })
    const after = stanceGroups('Heart')
    expect(after).toHaveLength(2)
    expect(activeStance(after[0])).toBe("Don't do it")
    expect(activeStance(after[1])).toBe("Don't do it")
  })

  it('S2-F3 pause control: pausing shows the banner and Paused badges; resuming clears them', async () => {
    renderSurface()
    await flush()
    expect(container.textContent).not.toContain('Standing behavior is paused')
    const checkbox = container.querySelector('input[type="checkbox"]')
    if (!checkbox) throw new Error('pause checkbox missing')
    await click(checkbox)
    const pauseCalls = calls.filter((c) => c.url.includes('/permissions/framework/pause'))
    expect(pauseCalls).toHaveLength(1)
    expect(pauseCalls[0].body).toEqual({ paused: true })
    expect(container.textContent).toContain('Standing behavior is paused')
    expect(container.textContent).toContain('Paused')
    const bannerResume = Array.from(container.querySelectorAll('button')).find(
      (b) => (b.textContent ?? '').includes('Resume standing behavior'),
    )
    if (!bannerResume) throw new Error('banner Resume button missing')
    await click(bannerResume)
    expect(container.textContent).not.toContain('Standing behavior is paused')
  })

  it('S2-F4 retained choice: revoking R6 with items behind opens the line; Review goes to Today', async () => {
    const onOpenToday = vi.fn()
    renderSurface(onOpenToday)
    await flush()
    expect(container.textContent).toContain('3 live reminders retained.')
    const watering = stanceGroups('Watering')
    expect(watering).toHaveLength(1)
    await click(buttonIn(watering[0], "Don't do it"))
    expect(container.textContent).toContain('Your 3 live reminders are still here.')
    const reviewButton = Array.from(container.querySelectorAll('button')).find(
      (b) => (b.textContent ?? '').trim() === 'Review in Today',
    )
    if (!reviewButton) throw new Error('Review in Today button missing')
    await click(reviewButton)
    expect(onOpenToday).toHaveBeenCalledTimes(1)
  })

  it('S2-F5 R4/R5 offer only Just do it / Don\u2019t do it — no Ask me anywhere in those groups', async () => {
    renderSurface()
    await flush()
    const groupDiv = (title: string): Element => {
      const p = Array.from(container.querySelectorAll('p')).find(
        (el) => (el.textContent ?? '').trim() === title,
      )
      if (!p) throw new Error(`group title "${title}" not found`)
      const div = p.closest('div')
      if (!div) throw new Error(`group div for "${title}" not found`)
      return div
    }
    const countButtons = (group: Element, text: string): number =>
      Array.from(group.querySelectorAll('button')).filter(
        (b) => (b.textContent ?? '').trim() === text,
      ).length
    const fellowship = groupDiv('Fellowship')
    expect(countButtons(fellowship, 'Ask me')).toBe(0)
    expect(countButtons(fellowship, 'Just do it')).toBe(7)
    expect(countButtons(fellowship, "Don't do it")).toBe(7)
    // Vision Execution: R5 offers two stances; R6 (Watering) offers all three.
    const ve = groupDiv('Vision Execution')
    expect(countButtons(ve, 'Ask me')).toBe(1)
    expect(countButtons(ve, 'Just do it')).toBe(2)
    expect(countButtons(ve, "Don't do it")).toBe(2)
  })
})
