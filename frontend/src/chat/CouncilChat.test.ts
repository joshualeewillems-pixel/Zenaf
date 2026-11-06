// @vitest-environment jsdom
/**
 * Durable Tree Talk Slice A — CouncilChat hydration tests (T8 + T10).
 *
 * T8: fetch is called with the conversation id; messages render from the
 * mocked GET /conversation response; send is disabled until hydration
 * settles; a failed fetch renders the error state (never an empty
 * thread); remounting with the same id re-hydrates identically.
 * T10: switching conversations while A's hydration is pending must
 * never let A's late response overwrite B, and a send must never
 * target the stale id.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 * Interactive harness follows MeetingView.test.ts (createRoot + act).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import CouncilChat from './CouncilChat'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Row = {
  id: string
  role: 'user' | 'voice'
  body: string
  archetype_id?: string | null
}

const u = (id: string, body: string): Row => ({ id, role: 'user', body })
const v = (id: string, body: string, seat = 'mentor'): Row => ({
  id,
  role: 'voice',
  body,
  archetype_id: seat,
})

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

let container: HTMLDivElement
let root: Root
let calls: Array<{ url: string; init?: RequestInit }>
let hydrations: Record<string, Deferred>
let turnBodies: Array<Record<string, unknown>>

function installFetch() {
  calls = []
  hydrations = {}
  turnBodies = []
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, init })
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(ok({ archetypes: [] }))
    }
    if (url.includes('/conversation/turn')) {
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
      turnBodies.push(body)
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
      const d = deferred()
      hydrations[id] = d
      return d.promise as Promise<Response>
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

function renderChat(props: Record<string, unknown>) {
  act(() => {
    root.render(React.createElement(CouncilChat, props as never))
  })
}

function sendButton(): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll('button')).find(
    (b) => b.textContent === 'Send',
  )
  if (!btn) throw new Error('Send button not found')
  return btn as HTMLButtonElement
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
  const input = container.querySelector('textarea')
  if (!input) throw new Error('composer input not found')
  act(() => setInputValue(input, text))
}

async function click(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
  await flush()
}

beforeEach(() => {
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

const A = 'talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const B = 'talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

describe('T8 hydration', () => {
  it('hydrates from the server id with limit=200 and enables send after success', async () => {
    renderChat({ environment: 'sheet', conversationId: A, initialArchetypeId: 'mentor' })
    await flush()
    expect(calls.some((c) => c.url.includes(`/conversation?conversation_id=${A}`))).toBe(true)
    expect(calls.some((c) => c.url.includes('limit=200'))).toBe(true)
    hydrations[A].resolve(ok({
      conversation_id: A,
      messages: [u('m1', 'hello A'), v('m2', 'reply A')],
      total: 2,
    }))
    await flush()
    expect(container.textContent).toContain('hello A')
    expect(container.textContent).toContain('reply A')
    typeText('follow up')
    expect(sendButton().disabled).toBe(false)
  })

  it('keeps send disabled while hydrating', async () => {
    renderChat({ environment: 'sheet', conversationId: A, initialArchetypeId: 'mentor' })
    await flush()
    typeText('too early')
    expect(sendButton().disabled).toBe(true)
    hydrations[A].resolve(ok({ conversation_id: A, messages: [], total: 0 }))
    await flush()
    expect(sendButton().disabled).toBe(false)
  })

  it('renders an error banner (not an empty thread) on failure, and send stays disabled until a successful retry', async () => {
    renderChat({ environment: 'sheet', conversationId: A, initialArchetypeId: 'mentor' })
    await flush()
    hydrations[A].reject(new Error('network down'))
    await flush()
    expect(container.textContent).toContain("Couldn't load this conversation")
    typeText('still cannot send')
    expect(sendButton().disabled).toBe(true)
    // Acknowledgement alone must not enable send: only a retry success does.
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'Retry',
    )
    if (!retry) throw new Error('Retry button not found')
    await click(retry)
    // The retry fetch is pending: still disabled, still error-free loading state.
    expect(sendButton().disabled).toBe(true)
    hydrations[A].resolve(ok({
      conversation_id: A,
      messages: [u('m1', 'recovered thread')],
      total: 1,
    }))
    await flush()
    expect(container.textContent).not.toContain("Couldn't load this conversation")
    expect(container.textContent).toContain('recovered thread')
    expect(sendButton().disabled).toBe(false)
  })

  it('re-hydrates identically on remount with the same id', async () => {
    renderChat({ environment: 'sheet', conversationId: A, initialArchetypeId: 'mentor' })
    await flush()
    hydrations[A].resolve(ok({
      conversation_id: A,
      messages: [u('m1', 'same thread')],
      total: 1,
    }))
    await flush()
    expect(container.textContent).toContain('same thread')
    act(() => root.unmount())
    container.remove()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    renderChat({ environment: 'sheet', conversationId: A, initialArchetypeId: 'mentor' })
    await flush()
    hydrations[A].resolve(ok({
      conversation_id: A,
      messages: [u('m1', 'same thread')],
      total: 1,
    }))
    await flush()
    expect(container.textContent).toContain('same thread')
    expect(calls.filter((c) => c.url.includes(`/conversation?conversation_id=${A}`))).toHaveLength(2)
  })
})

describe('T10 conversation switching', () => {
  it('a late response for A never overwrites B, and a send targets B', async () => {
    renderChat({ environment: 'sheet', conversationId: A, initialArchetypeId: 'mentor' })
    await flush()
    // Switch to B while A's hydration is still pending.
    renderChat({ environment: 'sheet', conversationId: B, initialArchetypeId: 'mentor' })
    await flush()
    expect(calls.some((c) => c.url.includes(`/conversation?conversation_id=${B}`))).toBe(true)
    // A's late response arrives: it must be ignored entirely.
    hydrations[A].resolve(ok({
      conversation_id: A,
      messages: [u('m1', 'A secret thread')],
      total: 1,
    }))
    await flush()
    expect(container.textContent).not.toContain('A secret thread')
    // B hydrates normally.
    hydrations[B].resolve(ok({
      conversation_id: B,
      messages: [u('m9', 'B thread')],
      total: 1,
    }))
    await flush()
    expect(container.textContent).toContain('B thread')
    expect(container.textContent).not.toContain('A secret thread')
    // A send now targets B, never the stale A id.
    typeText('hello B')
    await click(sendButton())
    expect(turnBodies).toHaveLength(1)
    expect(turnBodies[0].conversation_id).toBe(B)
    expect(container.textContent).toContain('turn reply')
  })
})
