// @vitest-environment jsdom
/**
 * Durable Tree Talk Slice A — TreeTalkSheet resolution tests.
 *
 * Seat sheet: auto-resumes the most recent talk involving that seat,
 * else holds a fresh talk- id; "New conversation" is always visible.
 * You-node: the recent-talks list plus "Start new"; picking a talk
 * opens it. List failure: error state, never a client-history fallback.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import TreeTalkSheet, { newTalkId } from './TreeTalkSheet'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Talk = {
  conversation_id: string
  kind: string | null
  created_at: string | null
  updated_at: string | null
  message_count: number
  seats: string[]
  last_message_at: string | null
  last_message_preview: string | null
}

const TALK_MENTOR = 'talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const TALK_CHAMPION = 'talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
const CONV_OVERRIDE = 'talk-cccccccccccccccccccccccccccccccc'

function talk(
  id: string,
  seats: string[],
  preview: string,
  count = 2,
): Talk {
  return {
    conversation_id: id,
    kind: 'skeleton',
    created_at: '2026-11-03T00:00:00.000Z',
    updated_at: '2026-11-03T00:00:00.000Z',
    message_count: count,
    seats,
    last_message_at: '2026-11-03T01:00:00.000Z',
    last_message_preview: preview,
  }
}

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

let container: HTMLDivElement
let root: Root
let calls: string[]
let listBehavior: 'ok' | 'fail'

function installFetch() {
  calls = []
  const fetchMock = vi.fn((url: string) => {
    calls.push(url)
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(ok({ archetypes: [] }))
    }
    if (url.includes('/conversation/list')) {
      if (listBehavior === 'fail') {
        return Promise.reject(new Error('list down'))
      }
      return Promise.resolve(
        ok({
          conversations: [
            talk(TALK_CHAMPION, ['champion'], 'champion preview'),
            talk(TALK_MENTOR, ['mentor'], 'mentor preview'),
          ],
        }),
      )
    }
    if (url.includes('/conversation/invitations')) {
      return Promise.resolve(ok({ conversation_id: CONV_OVERRIDE, invitations: [] }))
    }
    if (url.includes('/conversation?')) {
      const id = new URL(url, 'http://x').searchParams.get('conversation_id') ?? ''
      return Promise.resolve(
        ok({
          conversation_id: id,
          messages: [
            { id: 'm1', role: 'user', body: `thread ${id.slice(0, 10)}` },
            { id: 'm2', role: 'voice', body: 'thread reply', archetype_id: 'mentor' },
          ],
          total: 2,
        }),
      )
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

function renderSheet(props: Record<string, unknown>) {
  act(() => {
    root.render(React.createElement(TreeTalkSheet, props as never))
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
  listBehavior = 'ok'
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

describe('newTalkId', () => {
  it('is talk- plus 32 lowercase hex chars', () => {
    expect(newTalkId()).toMatch(/^talk-[0-9a-f]{32}$/)
  })
})

describe('seat sheet resolution', () => {
  it('auto-resumes the most recent talk involving that seat', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    expect(calls.some((u) => u.includes('/conversation/list'))).toBe(true)
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR}`)),
    ).toBe(true)
    expect(container.textContent).toContain('thread talk-aaaa')
    expect(container.textContent).toContain('New conversation')
  })

  it('holds a fresh talk- id when the seat has no prior talk', async () => {
    renderSheet({ seatKey: 'skeptic', displayName: 'Raven' })
    await flush()
    const hyd = calls.find((u) => u.includes('/conversation?conversation_id=talk-'))
    expect(hyd).toBeDefined()
    const id = new URL(hyd as string, 'http://x').searchParams.get('conversation_id') ?? ''
    expect(id).toMatch(/^talk-[0-9a-f]{32}$/)
    expect(id).not.toBe(TALK_MENTOR)
    expect(id).not.toBe(TALK_CHAMPION)
  })

  it('New conversation generates a fresh id and an empty thread', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    const before = calls.filter((u) => u.includes('/conversation?conversation_id=')).length
    await click(buttonByText('New conversation'))
    const hyds = calls.filter((u) => u.includes('/conversation?conversation_id='))
    expect(hyds.length).toBeGreaterThan(before)
    const id = new URL(hyds[hyds.length - 1], 'http://x').searchParams.get(
      'conversation_id',
    )
    expect(id).toMatch(/^talk-[0-9a-f]{32}$/)
    expect(id).not.toBe(TALK_MENTOR)
  })
})

describe('you-node rediscovery', () => {
  it('lists recent talks and opens one on tap', async () => {
    renderSheet({ seatKey: null })
    await flush()
    expect(container.textContent).toContain('mentor preview')
    expect(container.textContent).toContain('champion preview')
    expect(container.textContent).toContain('Start new')
    const item = Array.from(container.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('mentor preview'),
    )
    if (!item) throw new Error('talk list item not found')
    await click(item)
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR}`)),
    ).toBe(true)
    expect(container.textContent).toContain('thread talk-aaaa')
    expect(container.textContent).toContain('← Conversations')
  })

  it('Start new offers seat chips, then follows seat resolution', async () => {
    renderSheet({ seatKey: null })
    await flush()
    await click(buttonByText('Start new'))
    // Seat chips render (mentor chip by its id label).
    const chip = Array.from(container.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('mentor'),
    )
    if (!chip) throw new Error('mentor chip not found')
    await click(chip)
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR}`)),
    ).toBe(true)
  })
})

describe('conversation override (invitation navigation)', () => {
  const overrideProps = {
    seatKey: 'mentor',
    displayName: 'Gardener',
    conversationOverride: { conversationId: CONV_OVERRIDE, seat: 'guardian' },
  }

  it('mounts the given conversation + seat without the talks fetch', async () => {
    renderSheet(overrideProps)
    await flush()
    // No resolveSeat: the talks fetch never ran, so the list's mentor
    // talk (TALK_MENTOR) is never the hydration target.
    expect(calls.some((u) => u.includes('/conversation/list'))).toBe(false)
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${CONV_OVERRIDE}`)),
    ).toBe(true)
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR}`)),
    ).toBe(false)
    expect(container.textContent).toContain('thread talk-cccc')
    // The in-chat invitation list mounts for the override conversation.
    expect(
      calls.some(
        (u) =>
          u.includes('/conversation/invitations') &&
          u.includes(`conversation_id=${CONV_OVERRIDE}`),
      ),
    ).toBe(true)
    expect(container.textContent).toContain('No pending invitations in this conversation.')
  })

  it('override is cleared on New conversation', async () => {
    renderSheet(overrideProps)
    await flush()
    expect(container.textContent).toContain('thread talk-cccc')
    await click(buttonByText('New conversation'))
    const hyds = calls.filter((u) => u.includes('/conversation?conversation_id='))
    const id = new URL(hyds[hyds.length - 1], 'http://x').searchParams.get(
      'conversation_id',
    )
    expect(id).toMatch(/^talk-[0-9a-f]{32}$/)
    expect(id).not.toBe(CONV_OVERRIDE)
  })
})

describe('list failure', () => {
  it('shows an error state and never falls back to client-history chat', async () => {
    listBehavior = 'fail'
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    expect(container.textContent).toContain("Couldn't load your conversations")
    expect(container.querySelector('input')).toBeNull()
    expect(calls.some((u) => u.includes('/voice/chat'))).toBe(false)
  })
})
