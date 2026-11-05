// @vitest-environment jsdom
/**
 * Capability C visible-UX slice — InvitationList tests.
 *
 * Conversation-scoped pending list + expandable detail. Opening never
 * consumes (expand performs no mutation; rows stay listed across
 * refetches until a turn is sent). Error is never silent empty;
 * 401 is signed-out copy; evidence {} is honest empty-evidence copy.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout,
 * following TreeTalkSheet.test.ts.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import InvitationList from './InvitationList'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const CONV = 'talk-cccccccccccccccccccccccccccccccc'

function invitation(
  id: string,
  seat: string,
  reason: string,
  evidence: Record<string, unknown>,
) {
  return {
    id,
    conversation_id: CONV,
    seat,
    reason,
    reason_attribution:
      "The inviting selection's reading of the exchange — an interpretation, not an established fact.",
    evidence,
    status: 'pending',
    created_at: '2026-11-04T00:00:00.000Z',
    expires_at: '2026-11-11T00:00:00.000Z',
  }
}

const FULL_EVIDENCE = {
  user_message: 'We keep missing each other on this plan.',
  assistant_reply: 'Let me hold the line here.',
  responding_seat: 'champion',
  context: ['earlier thread line', { role: 'user', content: 'context user line' }],
}

let container: HTMLDivElement
let root: Root
let calls: { url: string; method: string | undefined }[]
let listBehavior: 'ok' | 'empty' | 'fail' | 'auth' | 'noevidence'
let invitationPayload: unknown[]

function ok(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response
}

function installFetch() {
  calls = []
  const fetchMock = vi.fn((url: string, opts?: { method?: string }) => {
    calls.push({ url, method: opts?.method })
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(
        ok({ archetypes: [{ id: 'guardian', display_name: 'The Bear', depth: 0 }] }),
      )
    }
    if (url.includes('/conversation/invitations')) {
      if (listBehavior === 'fail') {
        return Promise.resolve({ ok: false, status: 500, json: async () => ({}) } as Response)
      }
      if (listBehavior === 'auth') {
        return Promise.resolve({ ok: false, status: 401, json: async () => ({}) } as Response)
      }
      if (listBehavior === 'empty') {
        return Promise.resolve(ok({ conversation_id: CONV, invitations: [] }))
      }
      if (listBehavior === 'noevidence') {
        return Promise.resolve(
          ok({
            conversation_id: CONV,
            invitations: [invitation('inv-ne', 'guardian', 'a quiet reason', {})],
          }),
        )
      }
      return Promise.resolve(ok({ conversation_id: CONV, invitations: invitationPayload }))
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

function renderList(refreshKey = 0) {
  act(() => {
    root.render(
      React.createElement(InvitationList, {
        conversationId: CONV,
        onInviteSelected: () => {},
        refreshKey,
      } as never),
    )
  })
}

function buttonContaining(text: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll('button')).find((b) =>
    (b.textContent ?? '').includes(text),
  )
  if (!btn) throw new Error(`button containing "${text}" not found`)
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
  invitationPayload = [
    invitation('inv-1', 'guardian', 'a quiet reason', FULL_EVIDENCE),
    invitation('inv-2', 'mentor', 'a second reason', {
      user_message: 'Second user message here.',
      assistant_reply: 'Second reply.',
      responding_seat: 'mentor',
      context: [],
    }),
  ]
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

describe('rows', () => {
  it('renders seat, reason, and snippet per row', async () => {
    renderList()
    await flush()
    expect(container.textContent).toContain('The Bear')
    expect(container.textContent).toContain('a quiet reason')
    expect(container.textContent).toContain('We keep missing each other on this plan.')
    expect(container.textContent).toContain('a second reason')
  })

  it('expand shows full evidence + attribution verbatim, with no mutation', async () => {
    renderList()
    await flush()
    await click(buttonContaining('a quiet reason'))
    expect(container.textContent).toContain(
      "The inviting selection's reading of the exchange — an interpretation, not an established fact.",
    )
    expect(container.textContent).toContain('Let me hold the line here.')
    expect(container.textContent).toContain('earlier thread line')
    expect(container.textContent).toContain('user: context user line')
    expect(container.textContent).toContain('does not consume it')
    // Expand is UI-local display state: every fetch is a GET.
    expect(calls.length).toBeGreaterThan(0)
    for (const c of calls) {
      expect(c.method === undefined || c.method === 'GET').toBe(true)
    }
    expect(calls.some((c) => c.url.includes('/conversation/invitations'))).toBe(true)
  })

  it('rows stay listed across refetches until a turn is sent', async () => {
    renderList()
    await flush()
    await click(buttonContaining('a quiet reason'))
    expect(container.textContent).toContain('Let me hold the line here.')
    // Same payload, bumped refreshKey (the post-turn refetch shape):
    // opening never consumed anything, so the row and detail remain.
    renderList(1)
    await flush()
    expect(container.textContent).toContain('a quiet reason')
    expect(container.textContent).toContain('Let me hold the line here.')
  })

  it('refetch drops vanished rows and collapses open detail silently', async () => {
    renderList()
    await flush()
    await click(buttonContaining('a quiet reason'))
    expect(container.textContent).toContain('Let me hold the line here.')
    invitationPayload = [invitationPayload[1]]
    renderList(1)
    await flush()
    expect(container.textContent).not.toContain('a quiet reason')
    expect(container.textContent).not.toContain('Let me hold the line here.')
    expect(container.textContent).toContain('a second reason')
  })
})

describe('empty / error / signed-out / no-evidence', () => {
  it('empty state on []', async () => {
    listBehavior = 'empty'
    renderList()
    await flush()
    expect(container.textContent).toContain('No pending invitations in this conversation.')
  })

  it('error state on non-OK, never silent empty', async () => {
    listBehavior = 'fail'
    renderList()
    await flush()
    expect(container.textContent).toContain("Couldn't load invitations.")
    expect(container.textContent).not.toContain('No pending invitations')
  })

  it('401 renders signed-out copy', async () => {
    listBehavior = 'auth'
    renderList()
    await flush()
    expect(container.textContent).toContain('Please sign in to see invitations.')
  })

  it('evidence {} renders honest empty-evidence copy', async () => {
    listBehavior = 'noevidence'
    renderList()
    await flush()
    await click(buttonContaining('a quiet reason'))
    expect(container.textContent).toContain(
      'No justifying exchange was stored with this invitation.',
    )
  })
})
