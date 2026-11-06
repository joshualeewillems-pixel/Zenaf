// @vitest-environment jsdom
/**
 * CouncilChat draft-store behavior (navigation correction §3 + C3 + C4).
 *
 * Mount-time init from the store (never effect/prefill), write-through
 * on every keystroke, synchronous chip/council swaps, the C3 send
 * boundary (key captured at Send press; clear only on accepted
 * persistence and only when the store still holds the sent text;
 * failed sends clear nothing; in-flight typing and switch-while-
 * pending drafts survive), and the C4 adoption move. All sends are
 * MOCKED — no live model calls, no staging turns.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 * Interactive harness follows CouncilChat.test.ts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import CouncilChat from './CouncilChat'
import {
  DraftStoreProvider,
  DraftStoreContext,
  type DraftStoreContextValue,
  COUNCIL_DRAFT_SEAT,
  UNSELECTED_DRAFT_SEAT,
} from './draftStore'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Deferred = {
  promise: Promise<unknown>
  resolve: (value: unknown) => void
  reject: (err: unknown) => void
}

function deferred(): Deferred {
  let resolve!: (value: unknown) => void
  let reject!: (err: unknown) => void
  const promise = new Promise<unknown>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

function fail(status: number) {
  return { ok: false, status, json: async () => ({}) } as Response
}

const USER = 'user-1'
const A = 'talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const B = 'talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

let container: HTMLDivElement
let root: Root
let calls: Array<{ url: string; init?: RequestInit }>
let turnBodies: Array<Record<string, unknown>>
let turnMode: 'ok' | 'fail' | 'deferred'
let turnDeferred: Deferred | null
let probe: DraftStoreContextValue | null

function Probe() {
  probe = React.useContext(DraftStoreContext)
  return null
}

function installFetch() {
  calls = []
  turnBodies = []
  turnMode = 'ok'
  turnDeferred = null
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init })
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(ok({ archetypes: [] }))
    }
    if (url.includes('/conversation/turn')) {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
      turnBodies.push(body)
      if (turnMode === 'fail') return Promise.resolve(fail(500))
      if (turnMode === 'deferred') {
        turnDeferred = deferred()
        return turnDeferred.promise as Promise<Response>
      }
      return Promise.resolve(
        ok({
          reply: 'turn reply',
          conversation_id: body.conversation_id,
          message_id: 'm-reply',
          archetype_id: body.archetype_id,
          display_name: 'Mentor',
          voice_color: '#888888',
          mode_used: 'trained',
          has_training: false,
        }),
      )
    }
    if (url.includes('/conversation?')) {
      const id = new URL(url, 'http://x').searchParams.get('conversation_id') ?? ''
      return Promise.resolve(ok({ conversation_id: id, messages: [], total: 0 }))
    }
    return Promise.resolve(ok({}))
  })
  vi.stubGlobal('fetch', fetchMock)
}

async function flush(times = 6) {
  for (let i = 0; i < times; i++) {
    await act(async () => {})
  }
}

function renderWithStore(props: Record<string, unknown>, key = 'c1') {
  act(() => {
    root.render(
      React.createElement(
        DraftStoreProvider,
        { userId: USER } as never,
        React.createElement(Probe),
        React.createElement(CouncilChat, { ...props, key } as never),
      ),
    )
  })
}

function renderWithoutStore(props: Record<string, unknown>) {
  act(() => {
    root.render(React.createElement(CouncilChat, props as never))
  })
}

function renderProviderOnly() {
  act(() => {
    root.render(
      React.createElement(
        DraftStoreProvider,
        { userId: USER } as never,
        React.createElement(Probe),
      ),
    )
  })
}

function composer(): HTMLTextAreaElement {
  const input = container.querySelector('textarea')
  if (!input) throw new Error('composer input not found')
  return input
}

function setInputValue(input: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    'value',
  )?.set
  setter?.call(input, value)
  input.dispatchEvent(new window.Event('input', { bubbles: true }))
}

function typeText(text: string) {
  act(() => setInputValue(composer(), text))
}

async function click(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
  await flush()
}

function sendButton(): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll('button')).find(
    (b) => b.textContent === 'Send',
  )
  if (!btn) throw new Error('Send button not found')
  return btn as HTMLButtonElement
}

function chip(seat: string): HTMLButtonElement {
  const group = container.querySelector('[aria-label="Choose a voice"]')
  if (!group) throw new Error('chip group not found')
  const btn = Array.from(group.querySelectorAll('button')).find(
    (b) => b.textContent === seat,
  )
  if (!btn) throw new Error(`chip for ${seat} not found`)
  return btn as HTMLButtonElement
}

function councilButton(): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll('button')).find(
    (b) => b.textContent === 'Ask the council',
  )
  if (!btn) throw new Error('council button not found')
  return btn as HTMLButtonElement
}

function storeGet(conversationId: string, seat: string): string | undefined {
  if (!probe) throw new Error('draft store probe not mounted')
  return probe.store.get({ userId: USER, conversationId, seat })
}

function storeSet(conversationId: string, seat: string, text: string) {
  if (!probe) throw new Error('draft store probe not mounted')
  probe.store.set({ userId: USER, conversationId, seat }, text)
}

beforeEach(() => {
  installFetch()
  probe = null
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

const sheet = (conversationId: string, initialArchetypeId: string | null) => ({
  environment: 'sheet',
  conversationId,
  initialArchetypeId,
})

describe('mount init + write-through + swaps', () => {
  it('restores a pre-seeded draft verbatim at mount and sends nothing on restore (T15)', async () => {
    renderProviderOnly()
    await flush()
    storeSet(A, 'mentor', 'restored draft')
    renderWithStore(sheet(A, 'mentor'))
    await flush()
    expect(composer().value).toBe('restored draft')
    expect(turnBodies).toHaveLength(0)
    expect(calls.some((c) => c.url.includes('/conversation/turn'))).toBe(false)
  })

  it('write-through + chip swaps keep each seat draft separate (T9a/T12)', async () => {
    renderWithStore(sheet(A, 'mentor'))
    await flush()
    typeText('mentor draft')
    expect(storeGet(A, 'mentor')).toBe('mentor draft')
    await click(chip('champion'))
    expect(composer().value).toBe('')
    typeText('champion draft')
    expect(storeGet(A, 'champion')).toBe('champion draft')
    await click(chip('mentor'))
    expect(composer().value).toBe('mentor draft')
    expect(storeGet(A, 'mentor')).toBe('mentor draft')
  })

  it('council drafts are distinct from seat drafts, both survive toggling (T8)', async () => {
    renderWithStore(sheet(A, 'mentor'))
    await flush()
    typeText('seat draft')
    await click(councilButton())
    expect(composer().value).toBe('')
    typeText('council draft')
    expect(storeGet(A, COUNCIL_DRAFT_SEAT)).toBe('council draft')
    await click(councilButton())
    expect(composer().value).toBe('seat draft')
    await click(councilButton())
    expect(composer().value).toBe('council draft')
    expect(storeGet(A, 'mentor')).toBe('seat draft')
  })

  it('remounting on another conversation preserves the first draft, and returning restores it (T1)', async () => {
    renderWithStore(sheet(A, 'mentor'), 'k1')
    await flush()
    typeText('draft in A')
    renderWithStore(sheet(B, 'champion'), 'k2')
    await flush()
    expect(composer().value).toBe('')
    typeText('draft in B')
    renderWithStore(sheet(A, 'mentor'), 'k3')
    await flush()
    expect(composer().value).toBe('draft in A')
    renderWithStore(sheet(B, 'champion'), 'k4')
    await flush()
    expect(composer().value).toBe('draft in B')
  })
})

describe('adoption is a move (C4)', () => {
  // NOTE on reachability: with no seat selected the composer block is
  // gated on (activeId || councilMode), so a user cannot type under
  // 'unselected' in the shipped UI — the design's "type before picking"
  // scenario does not occur there. Adoption is still implemented
  // exactly as specified (first selection moves the text; a saved
  // destination draft wins and both are preserved), and these tests
  // exercise it via a pre-existing unselected entry + first chip pick.
  // No pre-selection composer was added: that would be a new UI
  // surface outside this correction's scope.
  it('first seat pick adopts a pre-existing unselected draft and clears unselected', async () => {
    renderProviderOnly()
    await flush()
    storeSet(A, UNSELECTED_DRAFT_SEAT, 'typed before picking')
    renderWithStore(sheet(A, null))
    await flush()
    // No composer until a seat is picked; chips are always visible.
    expect(container.querySelector('textarea')).toBeNull()
    await click(chip('mentor'))
    expect(composer().value).toBe('typed before picking')
    expect(storeGet(A, 'mentor')).toBe('typed before picking')
    expect(storeGet(A, UNSELECTED_DRAFT_SEAT)).toBe(undefined)
    // Returning to an unselected mount shows no composer and the moved
    // text never reappears under unselected.
    renderWithStore(sheet(A, null), 'k2')
    await flush()
    expect(storeGet(A, UNSELECTED_DRAFT_SEAT)).toBe(undefined)
  })

  it('when the destination already has a draft, the saved draft wins and unselected is preserved', async () => {
    renderProviderOnly()
    await flush()
    storeSet(A, 'mentor', 'saved seat text')
    storeSet(A, UNSELECTED_DRAFT_SEAT, 'unselected text')
    renderWithStore(sheet(A, null))
    await flush()
    await click(chip('mentor'))
    expect(composer().value).toBe('saved seat text')
    expect(storeGet(A, UNSELECTED_DRAFT_SEAT)).toBe('unselected text')
    expect(storeGet(A, 'mentor')).toBe('saved seat text')
  })
})

describe('send boundary (C3, mocked sends)', () => {
  it('successful send clears exactly its own key and nothing else (T10)', async () => {
    renderProviderOnly()
    await flush()
    storeSet(A, 'mentor', 'mentor draft A')
    storeSet(A, 'champion', 'champion draft A')
    storeSet(B, 'mentor', 'mentor draft B')
    renderWithStore(sheet(A, 'mentor'))
    await flush()
    expect(composer().value).toBe('mentor draft A')
    await click(sendButton())
    expect(storeGet(A, 'mentor')).toBe(undefined)
    expect(composer().value).toBe('')
    expect(storeGet(A, 'champion')).toBe('champion draft A')
    expect(storeGet(B, 'mentor')).toBe('mentor draft B')
    await click(chip('champion'))
    expect(composer().value).toBe('champion draft A')
    renderWithStore(sheet(B, 'mentor'), 'k2')
    await flush()
    expect(composer().value).toBe('mentor draft B')
  })

  it('successful council send clears only the council key', async () => {
    renderProviderOnly()
    await flush()
    storeSet(A, 'mentor', 'seat draft')
    renderWithStore(sheet(A, 'mentor'))
    await flush()
    await click(councilButton())
    typeText('council draft')
    await click(sendButton())
    expect(storeGet(A, COUNCIL_DRAFT_SEAT)).toBe(undefined)
    expect(storeGet(A, 'mentor')).toBe('seat draft')
  })

  it('failed send clears nothing and restores the draft into the composer', async () => {
    turnMode = 'fail'
    renderWithStore(sheet(A, 'mentor'))
    await flush()
    typeText('doomed draft')
    await click(sendButton())
    expect(container.textContent).toContain("couldn't reach my voice")
    expect(storeGet(A, 'mentor')).toBe('doomed draft')
    expect(composer().value).toBe('doomed draft')
  })

  it('typing while a send is in flight survives completion', async () => {
    turnMode = 'deferred'
    renderWithStore(sheet(A, 'mentor'))
    await flush()
    typeText('sent text')
    await click(sendButton())
    expect(turnDeferred).not.toBeNull()
    // The composer accepts new typing during the flight; it lands
    // under the same key via write-through.
    typeText('newer typing')
    turnDeferred!.resolve(
      ok({
        reply: 'late reply',
        conversation_id: A,
        message_id: 'm-late',
        archetype_id: 'mentor',
        display_name: 'Mentor',
        voice_color: '#888888',
        mode_used: 'trained',
        has_training: false,
      }),
    )
    await flush()
    expect(composer().value).toBe('newer typing')
    expect(storeGet(A, 'mentor')).toBe('newer typing')
    expect(container.textContent).toContain('late reply')
  })

  it('switching seats while a send is pending leaves the new draft intact and clears only the captured key', async () => {
    turnMode = 'deferred'
    renderWithStore(sheet(A, 'mentor'))
    await flush()
    typeText('mentor sent text')
    await click(sendButton())
    expect(turnDeferred).not.toBeNull()
    await click(chip('champion'))
    expect(composer().value).toBe('')
    typeText('champion draft')
    turnDeferred!.resolve(
      ok({
        reply: 'late mentor reply',
        conversation_id: A,
        message_id: 'm-late',
        archetype_id: 'mentor',
        display_name: 'Mentor',
        voice_color: '#888888',
        mode_used: 'trained',
        has_training: false,
      }),
    )
    await flush()
    // The captured mentor key cleared (its stored text was unchanged);
    // the champion draft typed mid-flight is untouched.
    expect(storeGet(A, 'mentor')).toBe(undefined)
    expect(storeGet(A, 'champion')).toBe('champion draft')
    expect(composer().value).toBe('champion draft')
  })
})

describe('no-store mounts keep today\'s behavior', () => {
  it('without a provider, chip switches share one input and nothing is stored', async () => {
    renderWithoutStore(sheet(A, 'mentor'))
    await flush()
    typeText('shared text')
    await click(chip('champion'))
    expect(composer().value).toBe('shared text')
    await click(chip('mentor'))
    expect(composer().value).toBe('shared text')
  })

  it('a null conversationId (local fallback) never reads or writes the store', async () => {
    renderProviderOnly()
    await flush()
    storeSet(A, 'mentor', 'must not appear')
    renderWithStore({ environment: 'sheet', conversationId: null, initialArchetypeId: 'mentor' })
    await flush()
    expect(composer().value).toBe('')
    typeText('local only')
    expect(storeGet(A, 'mentor')).toBe('must not appear')
  })
})
