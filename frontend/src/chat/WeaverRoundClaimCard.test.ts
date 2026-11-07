// @vitest-environment jsdom
/**
 * Weaver rapid fire S1 — round claim card tests (brief §14: T6
 * card half, T10, T13, T19 copy half, T27).
 *
 * jsdom + createRoot + act with a mocked fetch, following the
 * RoundProposalCard.test.ts harness. Server state drives the card:
 * hydration reads the claim, a tap opens a confirmation panel
 * (never posts), Confirm posts to the existing verdict endpoint,
 * Cancel writes nothing, "I need to check" parks, and a 409
 * surfaces the server's conflict copy. The tap itself sends no
 * turn: no POST to /conversation/turn ever leaves the card.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import WeaverRoundClaimCard from './WeaverRoundClaimCard'
import type { WeaverRoundItem } from './weaverRound'
import type { Claim } from '../agent-intake/ClaimCard'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const CLAIM: Claim = {
  id: 'meeting-maverick-1:impression:self:run1',
  claim_type: 'meeting_impression',
  title: 'First impression — Fox',
  evidence: 'Yes, that is me.',
  inference: 'The Fox reads you as steady.',
  detail:
    "The read-back, word for word:\nThe Fox reads you as steady.\n\nYour answer, word for word:\nYes, that is me.\n\nRead-back outcome: the seat retained the impression; the visitor's response was affirmed.",
  status: 'pending',
  user_note: '',
  question: 'Does that first impression sound right to you?',
  scope: 'moment',
  turn_ref: '',
  readback_visitor_response: 'affirmed',
  readback_seat_outcome: 'retained',
  readback_original_claim: '',
}

const ROUND_ITEM: WeaverRoundItem = {
  kind: 'meeting_impression',
  agent_id: 'meeting-maverick-1',
  claim_id: CLAIM.id,
  claim_type: 'meeting_impression',
  rendering: {
    agent_id: 'meeting-maverick-1',
    claim_id: CLAIM.id,
    claim_type: 'meeting_impression',
    seat_name: 'Fox',
    seat_role: 'Maverick',
    impression: 'The Fox reads you as steady.',
    evidence: 'Yes, that is me.',
    outcome_line:
      "Read-back outcome: the seat retained the impression; the visitor's response was affirmed.",
    visitor_response: 'affirmed',
    seat_outcome: 'retained',
    original_claim: '',
    status: 'pending',
  },
}

describe('WeaverRoundClaimCard', () => {
  let container: HTMLDivElement
  let root: Root
  let calls: Array<{ url: string; init?: RequestInit }>
  let claimsState: Claim[]
  let verdictBehavior: 'ok' | 'conflict'
  let messageContent: string

  const ok = (payload: unknown) => ({ ok: true, status: 200, json: async () => payload }) as Response
  const fail = (status: number, detail?: string) =>
    ({ ok: false, status, json: async () => ({ detail }) }) as Response

  function installFetch() {
    calls = []
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init })
      if (url.includes('/agents/') && url.includes('/claims') && init?.method !== 'POST') {
        return Promise.resolve(ok(claimsState))
      }
      if (url.includes('/conversation/round/skip')) {
        return Promise.resolve(ok({ parked: true, claim: claimsState[0] }))
      }
      const verdict = url.match(/\/claims\/[^/]+\/(accept|correct|explain|reject|unresolve)$/)
      if (verdict && init?.method === 'POST') {
        if (verdictBehavior === 'conflict') {
          return Promise.resolve(
            fail(
              409,
              "This one was already decided elsewhere — in your Review, for example — so nothing was written here. It's no longer pending.",
            ),
          )
        }
        const action = verdict[1] as 'accept' | 'correct' | 'explain' | 'reject' | 'unresolve'
        const statusMap = {
          accept: 'accepted',
          correct: 'corrected',
          explain: 'explained',
          reject: 'rejected',
          unresolve: 'unresolved',
        } as const
        let note = ''
        try {
          note = (JSON.parse(String(init?.body ?? '{}')) as { note?: string }).note ?? ''
        } catch {
          note = ''
        }
        const updated = { ...claimsState[0], status: statusMap[action], user_note: note }
        claimsState = [updated]
        return Promise.resolve(ok(updated))
      }
      return Promise.resolve(ok({}))
    })
    vi.stubGlobal('fetch', fetchMock)
  }

  async function renderCard(item: WeaverRoundItem = ROUND_ITEM, content = '') {
    messageContent = content
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await act(async () => {
      root.render(
        React.createElement(WeaverRoundClaimCard, {
          base: '',
          conversationId: 'talk-1',
          messageId: 'm-round',
          roundItem: item,
          messageContent: content,
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

  function verdictPosts() {
    return calls.filter(
      (c) => c.init?.method === 'POST' && c.url.includes('/claims/'),
    )
  }

  beforeEach(() => {
    claimsState = [{ ...CLAIM }]
    verdictBehavior = 'ok'
    messageContent = ''
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

  it('renders the verbatim original with the five actions and the timing copy', async () => {
    await renderCard()
    expect(container.textContent).toContain('Rapid fire')
    expect(container.textContent).toContain("The Fox's first impression of you")
    expect(container.textContent).toContain('The Fox reads you as steady.')
    expect(container.textContent).toContain('Yes, that is me.')
    expect(container.textContent).toContain(
      "Read-back outcome: the seat retained the impression; the visitor's response was affirmed.",
    )
    expect(buttonNamed('Keep it')).toBeDefined()
    expect(buttonNamed('Fix the wording')).toBeDefined()
    expect(buttonNamed("Say why it's right")).toBeDefined()
    expect(buttonNamed("It's wrong")).toBeDefined()
    expect(buttonNamed('Leave it open')).toBeDefined()
    expect(buttonNamed('I need to check')).toBeDefined()
    expect(container.textContent).toContain(
      'Tap to rule on this one. Weaver will bring the next one when you reply',
    )
  })

  it('tap opens confirmation and posts nothing; Cancel writes nothing', async () => {
    await renderCard()
    await click('Keep it')
    expect(container.textContent).toContain('Keep it — are you sure?')
    expect(container.textContent).toContain(
      "This trains Weaver's picture of you: the impression becomes approved evidence about you.",
    )
    expect(verdictPosts()).toHaveLength(0)
    await click('Cancel')
    expect(verdictPosts()).toHaveLength(0)
    expect(buttonNamed('Keep it')).toBeDefined()
  })

  it('Confirm posts to the existing endpoint and shows the decided state; no turn is sent (T27)', async () => {
    await renderCard()
    await click('Keep it')
    await click('Confirm')
    expect(verdictPosts()).toHaveLength(1)
    expect(verdictPosts()[0].url).toContain('/accept')
    expect(container.textContent).toContain('Ruled. Kept.')
    expect(container.textContent).toContain('Weaver will bring the next one when you reply.')
    expect(calls.some((c) => c.url.includes('/conversation/turn'))).toBe(false)
  })

  it('a 409 shows the conflict copy and re-fetches the claim', async () => {
    verdictBehavior = 'conflict'
    await renderCard()
    await click('Keep it')
    await click('Confirm')
    expect(container.textContent).toContain('already decided elsewhere')
    expect(buttonNamed('Keep it')).toBeDefined()
  })

  it('Keep it on a disputed impression shows the amendment-4 sentence', async () => {
    claimsState = [
      { ...CLAIM, readback_visitor_response: 'disputed', detail: CLAIM.detail.replace('affirmed', 'disputed') },
    ]
    const disputedItem: WeaverRoundItem = {
      ...ROUND_ITEM,
      rendering: { ...ROUND_ITEM.rendering!, visitor_response: 'disputed' },
    }
    await renderCard(disputedItem)
    await click('Keep it')
    expect(container.textContent).toContain(
      'This does NOT train the impression as true about you.',
    )
    expect(container.textContent).toContain('because you disputed it in the meeting')
    expect(container.textContent).toContain("we're not deciding it here")
  })

  it('Fix the wording pre-fills the note from the correction-draft fence; Submit confirms, Confirm posts the note', async () => {
    const content =
      'Here is the read in plain words.\n```correction-draft\nMore precisely, steady under pressure.\n```'
    await renderCard(ROUND_ITEM, content)
    await click('Fix the wording')
    const textarea = container.querySelector('textarea') as HTMLTextAreaElement
    expect(textarea).toBeDefined()
    expect(textarea.value).toBe('More precisely, steady under pressure.')
    await click('Submit qualification')
    expect(container.textContent).toContain('Fix the wording — are you sure?')
    expect(verdictPosts()).toHaveLength(0)
    await click('Confirm')
    expect(verdictPosts()).toHaveLength(1)
    expect(verdictPosts()[0].url).toContain('/correct')
    expect(JSON.parse(String(verdictPosts()[0].init?.body ?? '{}')).note).toBe(
      'More precisely, steady under pressure.',
    )
    expect(container.textContent).toContain('Ruled. Fixed.')
  })

  it('a malformed fence leaves the note empty (T13 degradation)', async () => {
    await renderCard(ROUND_ITEM, '```correction-draft\nno closing fence')
    await click('Fix the wording')
    const textarea = container.querySelector('textarea') as HTMLTextAreaElement
    expect(textarea).toBeDefined()
    expect(textarea.value).toBe('')
  })

  it('I need to check parks with claim_id and shows the parked line', async () => {
    await renderCard()
    await click('I need to check')
    const skips = calls.filter((c) => c.url.includes('/conversation/round/skip'))
    expect(skips).toHaveLength(1)
    expect(JSON.parse(String(skips[0].init?.body ?? '{}')).claim_id).toBe(CLAIM.id)
    expect(container.textContent).toContain("Parked — still pending, it'll come back next round.")
    expect(buttonNamed('Keep it')).toBeDefined()
  })

  it('visitor-unresolved is labeled distinctly from a left-open verdict (T7)', async () => {
    claimsState = [{ ...CLAIM, readback_visitor_response: 'unresolved' }]
    const item: WeaverRoundItem = {
      ...ROUND_ITEM,
      rendering: { ...ROUND_ITEM.rendering!, visitor_response: 'unresolved' },
    }
    await renderCard(item)
    expect(container.textContent).toContain('you neither agreed nor disputed it')
    await click('Leave it open')
    await click('Confirm')
    expect(container.textContent).toContain('Ruled. Left open.')
    expect(container.textContent).toContain('You left it open')
  })

  it('Leave it open says it will not come back; park says it will (T19)', async () => {
    await renderCard()
    await click('Leave it open')
    expect(container.textContent).toContain('will not come back next round')
    await click('Cancel')
    await click('I need to check')
    expect(container.textContent).toContain("it'll come back next round")
  })
})
