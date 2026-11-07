// @vitest-environment jsdom
/**
 * Firebrand lightning round S1 — round card tests.
 *
 * jsdom + createRoot + act with a mocked fetch, following the
 * TaskProposalCards.test.ts harness. Server state drives the card:
 * hydration reads item-state, approve/decline mutate server state,
 * "I need to check" parks, "Don't remind me" reserves (snooze or
 * never) with Undo, and a 409 surfaces the server's detail.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import RoundProposalCard, { type RoundItem } from './RoundProposalCard'
import type { ServerProposal } from './TaskProposalCards'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const PROPOSAL: ServerProposal = {
  id: 'p1',
  conversation_id: 'talk-2',
  source_message_id: 'm-src',
  block_index: 0,
  proposal_index: 0,
  seat: 'champion',
  title: 'Call the clinic',
  parent_task_id: null,
  timeframe_commitment: 'tentative',
  due_date: null,
  notes: 'Ask',
  state: 'pending',
  created_task_id: null,
  evidence_quote: 'Prose for Call the clinic here.',
  original_title: 'Call the clinic',
  original_parent_task_id: null,
  original_timeframe_commitment: 'tentative',
  original_due_date: null,
  original_notes: 'Ask',
  grounding_flag: 'words_matched',
}

describe('RoundProposalCard', () => {
  let container: HTMLDivElement
  let root: Root
  let calls: Array<{ url: string; init?: RequestInit }>
  let itemState: { proposal: ServerProposal; parked: boolean; reserved: { snooze_until: string | null } | null }
  let approveBehavior: 'ok' | 'conflict'

  const ok = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response
  const fail = (status: number, detail?: string) =>
    ({ ok: false, status, json: async () => ({ detail }) }) as Response

  function installFetch() {
    calls = []
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init })
      if (url.includes('/conversation/round/item-state')) {
        return Promise.resolve(ok(itemState))
      }
      if (url.includes('/conversation/round/skip')) {
        return Promise.resolve(ok({ parked: true, proposal: itemState.proposal }))
      }
      if (url.includes('/conversation/round/reserve')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as { snooze_days?: number | null }
        const snoozeUntil =
          body.snooze_days == null ? null : '2026-11-13T00:00:00+00:00'
        return Promise.resolve(
          ok({ reserved: true, marker: { snooze_until: snoozeUntil } }),
        )
      }
      if (url.includes('/conversation/round/unreserve')) {
        return Promise.resolve(ok({ reserved: false, proposal: itemState.proposal }))
      }
      if (url.includes('/approve')) {
        if (approveBehavior === 'conflict') {
          return Promise.resolve(fail(409, 'Already decided — refresh to see its state.'))
        }
        return Promise.resolve(
          ok({
            task: { id: 't1', title: 'Call the clinic' },
            proposal: { ...itemState.proposal, state: 'approved', created_task_id: 't1' },
          }),
        )
      }
      if (url.includes('/decline')) {
        return Promise.resolve(
          ok({ ...itemState.proposal, state: 'declined', created_task_id: null }),
        )
      }
      if (url.includes('/vision-execution/tasks')) {
        return Promise.resolve(ok([]))
      }
      return Promise.resolve(ok({}))
    })
    vi.stubGlobal('fetch', fetchMock)
  }

  async function renderCard(roundItem: RoundItem = { kind: 'task_proposal', proposal_id: 'p1', proposal: PROPOSAL }) {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await act(async () => {
      root.render(
        React.createElement(RoundProposalCard, {
          base: '',
          conversationId: 'talk-1',
          messageId: 'm-round',
          roundItem,
        }),
      )
    })
    for (let i = 0; i < 4; i += 1) {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
      })
    }
  }

  function buttonNamed(name: string): HTMLButtonElement | undefined {
    return Array.from(container.querySelectorAll('button')).find(
      (b) => (b.textContent ?? '').trim() === name,
    ) as HTMLButtonElement | undefined
  }

  async function click(name: string) {
    await act(async () => {
      buttonNamed(name)?.click()
      await new Promise((r) => setTimeout(r, 0))
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
  }

  function setReserveDays(value: '1' | '7' | 'never') {
    const select = container.querySelector(
      'select[aria-label="Don\'t remind me for"]',
    ) as HTMLSelectElement
    expect(select).toBeDefined()
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLSelectElement.prototype,
      'value',
    )!.set!
    act(() => {
      setter.call(select, value)
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
  }

  beforeEach(() => {
    itemState = { proposal: PROPOSAL, parked: false, reserved: null }
    approveBehavior = 'ok'
    installFetch()
  })

  afterEach(() => {
    act(() => {
      root?.unmount()
    })
    container?.remove()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the turn proposal with the round actions', async () => {
    await renderCard()
    expect(container.textContent).toContain('Lightning round')
    expect(container.textContent).toContain('Call the clinic')
    expect(container.textContent).toContain('Tentative timeframe')
    expect(container.textContent).toContain('Prose for Call the clinic here.')
    expect(buttonNamed('Approve')).toBeDefined()
    expect(buttonNamed('Edit')).toBeDefined()
    expect(buttonNamed('Decline')).toBeDefined()
    expect(buttonNamed('I need to check')).toBeDefined()
    expect(buttonNamed("Don't remind me")).toBeDefined()
    expect(calls.some((c) => c.url.includes('/round/item-state'))).toBe(true)
  })

  it('hydrates from item-state when the turn carried no proposal', async () => {
    await renderCard({ kind: 'task_proposal', proposal_id: 'p1' })
    expect(container.textContent).toContain('Call the clinic')
    expect(buttonNamed('Approve')).toBeDefined()
  })

  it('hydration shows a parked item as parked, buttons intact', async () => {
    itemState = { proposal: PROPOSAL, parked: true, reserved: null }
    await renderCard()
    expect(container.textContent).toContain("Parked — it'll come back next round.")
    expect(buttonNamed('Approve')).toBeDefined()
  })

  it('hydration shows a reserved item with no decide buttons', async () => {
    itemState = {
      proposal: PROPOSAL,
      parked: false,
      reserved: { snooze_until: '2026-11-13T00:00:00+00:00' },
    }
    await renderCard()
    expect(container.textContent).toContain("Won't remind you about this one")
    expect(container.textContent).toContain('2026-11-13')
    expect(buttonNamed('Approve')).toBeUndefined()
    expect(buttonNamed('Undo')).toBeDefined()
  })

  it('approve posts and shows Created', async () => {
    await renderCard()
    await click('Approve')
    expect(container.textContent).toContain('Created: Call the clinic')
    expect(calls.some((c) => c.url.includes('/approve'))).toBe(true)
  })

  it('decline posts and shows Declined', async () => {
    await renderCard()
    await click('Decline')
    expect(container.textContent).toContain('Declined: Call the clinic')
  })

  it('approve conflict surfaces the server detail', async () => {
    approveBehavior = 'conflict'
    await renderCard()
    await click('Approve')
    expect(container.textContent).toContain('Already decided — refresh to see its state.')
    expect(container.textContent).toContain('Call the clinic')
  })

  it('I need to check parks and shows the parked line', async () => {
    await renderCard()
    await click('I need to check')
    expect(container.textContent).toContain("Parked — it'll come back next round.")
    expect(buttonNamed('Approve')).toBeDefined()
    const skip = calls.find((c) => c.url.includes('/round/skip'))
    expect(skip).toBeDefined()
    expect(JSON.parse(String(skip?.init?.body ?? '{}'))).toEqual({
      conversation_id: 'talk-1',
      message_id: 'm-round',
      proposal_id: 'p1',
    })
  })

  it("Don't remind me reserves for a week by default, Undo lifts it", async () => {
    await renderCard()
    await click("Don't remind me")
    expect(container.textContent).toContain("Won't remind you about this one")
    expect(container.textContent).toContain('2026-11-13')
    const reserve = calls.find((c) => c.url.includes('/round/reserve'))
    expect(JSON.parse(String(reserve?.init?.body ?? '{}')).snooze_days).toBe(7)
    await click('Undo')
    expect(container.textContent).not.toContain("Won't remind you about this one")
    expect(buttonNamed('Approve')).toBeDefined()
    expect(calls.some((c) => c.url.includes('/round/unreserve'))).toBe(true)
  })

  it("Don't remind me with Never posts a null snooze", async () => {
    await renderCard()
    setReserveDays('never')
    await click("Don't remind me")
    const reserve = calls.find((c) => c.url.includes('/round/reserve'))
    expect(JSON.parse(String(reserve?.init?.body ?? '{}')).snooze_days).toBeNull()
    expect(container.textContent).toContain('never.')
  })
})
