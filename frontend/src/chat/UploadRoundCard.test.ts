// @vitest-environment jsdom
/**
 * Upload rapid fire S1 — upload round card tests (brief §16: T34–T41
 * card half, T38 panels, T40 mount-fetch guard, T45 chooser).
 *
 * jsdom + createRoot + act with a mocked fetch, following the
 * RoundProposalCard.test.ts harness. Server state drives the card:
 * hydration reads the item, a tap opens a confirmation panel
 * (never posts), Confirm posts to the upload outcome endpoint,
 * Back writes nothing, "Not now" parks, Remind-me-later / Archive-it
 * reserve without inviting, and a 409 surfaces the server's
 * conflict copy. The tap itself sends no turn: no POST to
 * /conversation/turn ever leaves the card. The mount fetch is
 * guarded to the turn's interpretation id.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import UploadRoundCard, {
  consequenceCopy,
  type UploadRoundItem,
  type UploadRendering,
} from './UploadRoundCard'
import { stripRoundOfferMarker } from './weaverRound'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const RENDERING: UploadRendering = {
  interpretation_id: 'interp-1',
  document_id: 'doc-1',
  document_version: 1,
  lens: 'heart',
  lens_kind: 'strand',
  text: 'Reading 1: the day moved.',
  attribution: 'Heart strand, word for word',
  is_transformation: false,
  proposed_outcome: 'task',
  origin: 'extraction',
  ungrounded: false,
  spans: [
    {
      span_id: 'span-1',
      text: 'The morning light fell across the kitchen table',
      location: 'seg-0000:0-49',
      role: 'primary',
    },
  ],
  observations: [],
  coverage: 'first 1 of 1 chunks',
  uncertain_match: null,
  parentage_options: [
    { id: 'proj-1', title: 'Garden' },
    { id: 'proj-2', title: 'Kitchen' },
  ],
  parentage_suggestion: { project_id: 'proj-1', reason: 'The reading is about the garden.' },
}

const ROUND_ITEM: UploadRoundItem = {
  kind: 'interpretation',
  interpretation_id: 'interp-1',
  document_id: 'doc-1',
  document_version: 1,
  lens: 'heart',
  rendering: RENDERING,
}

describe('UploadRoundCard', () => {
  let container: HTMLDivElement
  let root: Root
  let calls: Array<{ url: string; init?: RequestInit }>
  let outcomeBehavior: 'ok' | 'conflict'
  let hydratedRendering: UploadRendering | null
  let outcomeState: Record<string, unknown> | null
  let onNextVoice: ReturnType<typeof vi.fn>

  const ok = (payload: unknown) =>
    ({ ok: true, status: 200, json: async () => payload }) as Response
  const fail = (status: number, detail?: string) =>
    ({ ok: false, status, json: async () => ({ detail }) }) as Response

  function installFetch() {
    calls = []
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init })
      if (url.includes('/conversation/upload/item-state')) {
        return Promise.resolve(
          ok({
            item: {
              kind: 'interpretation',
              interpretation_id:
                hydratedRendering?.interpretation_id ?? 'interp-1',
              document_id: 'doc-1',
              rendering: hydratedRendering ?? RENDERING,
            },
            outcome: outcomeState,
            parked: false,
            reserved: null,
          }),
        )
      }
      const outcome = url.match(/\/upload\/outcomes\/[^/]+\/(keep|talk|artifact|undertaking|train)$/)
      if (outcome && init?.method === 'POST') {
        if (outcomeBehavior === 'conflict') {
          return Promise.resolve(
            fail(409, 'Already decided — refresh to see its state.'),
          )
        }
        const next: Record<string, string> = {
          talk: 'ambassador',
          artifact: 'maverick',
          undertaking: 'champion',
          train: 'conductor',
        }
        outcomeState = {
          outcome_id: 'out-1',
          interpretation_id: 'interp-1',
          kind: outcome[1] === 'talk' ? 'explore' : outcome[1],
          status: 'created',
          ve_kind: null,
          ve_id: null,
          created_at: '2026-11-07T00:00:00Z',
        }
        return Promise.resolve(
          ok({
            outcome: outcomeState,
            next_voice: next[outcome[1]]
              ? { archetype_id: next[outcome[1]], display_name: next[outcome[1]] }
              : null,
          }),
        )
      }
      if (url.includes('/conversation/upload/round/skip')) {
        return Promise.resolve(ok({ parked: true }))
      }
      if (url.includes('/conversation/upload/round/reserve')) {
        return Promise.resolve(ok({ marker: { snooze_until: null } }))
      }
      if (url.includes('/conversation/upload/round/unreserve')) {
        return Promise.resolve(ok({}))
      }
      return Promise.resolve(ok({}))
    })
    vi.stubGlobal('fetch', fetchMock)
  }

  async function renderCard(item: UploadRoundItem = ROUND_ITEM) {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await act(async () => {
      root.render(
        React.createElement(UploadRoundCard, {
          base: '',
          conversationId: 'c1',
          messageId: 'm-round',
          roundItem: item,
          seatId: 'conductor',
          seatNames: { conductor: 'Weaver', ambassador: 'Crane' },
          onNextVoice,
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

  function text(): string {
    return container.textContent ?? ''
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

  function outcomePosts() {
    return calls.filter(
      (c) => c.init?.method === 'POST' && c.url.includes('/upload/outcomes/'),
    )
  }

  function turnPosts() {
    return calls.filter(
      (c) => c.init?.method === 'POST' && c.url.includes('/conversation/turn'),
    )
  }

  beforeEach(() => {
    outcomeBehavior = 'ok'
    hydratedRendering = null
    outcomeState = null
    onNextVoice = vi.fn()
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

  it('renders the verbatim reading with its cited span and the six menu actions', async () => {
    await renderCard()
    expect(text()).toContain('Reading 1: the day moved.')
    expect(text()).toContain('The morning light fell across the kitchen table')
    expect(text()).toContain('first 1 of 1 chunks')
    for (const label of [
      'Keep it',
      'Talk it through — Crane',
      'Make an artifact — Fox',
      'Mine for projects — Firebrand',
      'Train a model — Weaver',
    ]) {
      expect(buttonNamed(label)).toBeDefined()
    }
    expect(buttonNamed('Not now')).toBeDefined()
  })

  it('a tap opens a confirmation panel with the verbatim reading + consequence; Back writes nothing', async () => {
    await renderCard()
    await click('Keep it')
    expect(text()).toContain('The reading, word for word:')
    expect(text()).toContain('Reading 1: the day moved.')
    expect(text()).toContain('This keeps the reading as a record.')
    expect(outcomePosts()).toHaveLength(0)
    await click('Back')
    expect(outcomePosts()).toHaveLength(0)
    expect(buttonNamed('Keep it')).toBeDefined()
  })

  it('Confirm on Keep posts the outcome and shows the ruled line; no turn is sent', async () => {
    await renderCard()
    await click('Keep it')
    await click('Confirm')
    expect(outcomePosts()).toHaveLength(1)
    expect(outcomePosts()[0].url).toContain('/upload/outcomes/interp-1/keep')
    expect(turnPosts()).toHaveLength(0)
    expect(text()).toContain('Ruled. Kept.')
  })

  it('Talk confirms and switches the next voice to Crane', async () => {
    await renderCard()
    await click('Talk it through — Crane')
    expect(text()).toContain('This invites Crane to talk it through with you.')
    await click('Confirm')
    expect(outcomePosts()[0].url).toContain('/upload/outcomes/interp-1/talk')
    expect(onNextVoice).toHaveBeenCalledWith('ambassador')
    expect(turnPosts()).toHaveLength(0)
  })

  it('Mine for projects pre-populates kind + suggestion and posts both', async () => {
    await renderCard()
    await click('Mine for projects — Firebrand')
    const kindSelect = container.querySelector(
      'select[aria-label="Undertaking kind"]',
    ) as HTMLSelectElement | null
    expect(kindSelect?.value).toBe('task')
    const parentSelect = container.querySelector(
      'select[aria-label="Undertaking parent project"]',
    ) as HTMLSelectElement | null
    expect(parentSelect?.value).toBe('proj-1')
    expect(text()).toContain('Suggested: proj-1')
    await click('Confirm')
    const body = JSON.parse(String(outcomePosts()[0].init?.body ?? '{}'))
    expect(body.kind).toBe('task')
    expect(body.parent_id).toBe('proj-1')
    expect(onNextVoice).toHaveBeenCalledWith('champion')
  })

  it('Train defaults the seat chooser to the conversation seat and posts it', async () => {
    await renderCard()
    await click('Train a model — Weaver')
    const seatSelect = container.querySelector(
      'select[aria-label="Train seat"]',
    ) as HTMLSelectElement | null
    expect(seatSelect?.value).toBe('conductor')
    expect(text()).toContain('pending training claim for Weaver')
    await click('Confirm')
    const body = JSON.parse(String(outcomePosts()[0].init?.body ?? '{}'))
    expect(body.seat).toBe('conductor')
    expect(onNextVoice).toHaveBeenCalledWith('conductor')
  })

  it('Make an artifact requires a kind for a transformation', async () => {
    const transformed: UploadRendering = {
      ...RENDERING,
      is_transformation: true,
      proposed_outcome: 'task',
    }
    // The mount fetch returns the same rendering the turn presented.
    hydratedRendering = transformed
    await renderCard({ ...ROUND_ITEM, rendering: transformed })
    await click('Make an artifact — Fox')
    const kindInput = container.querySelector(
      'input[aria-label="Artifact kind"]',
    ) as HTMLInputElement | null
    expect(kindInput).toBeDefined()
    expect(buttonNamed('Confirm')?.disabled).toBe(true)
    await act(async () => {
      kindInput?.focus()
    })
  })

  it('Remind me later posts the snooze picker value; Archive it posts archive=true', async () => {
    await renderCard()
    await click('Remind me later')
    const reserve = calls.filter(
      (c) => c.init?.method === 'POST' && c.url.includes('/upload/round/reserve'),
    )
    expect(reserve).toHaveLength(1)
    expect(JSON.parse(String(reserve[0].init?.body ?? '{}')).snooze_days).toBe(7)
    // Once reserved the card shows the reserved line + Undo; undo
    // first, then the Archive-it tap is available again.
    await click('Undo')
    await click('Archive it')
    const reserve2 = calls.filter(
      (c) => c.init?.method === 'POST' && c.url.includes('/upload/round/reserve'),
    )
    expect(reserve2).toHaveLength(2)
    expect(JSON.parse(String(reserve2[1].init?.body ?? '{}')).archive).toBe(true)
    expect(turnPosts()).toHaveLength(0)
  })

  it('Not now parks the item', async () => {
    await renderCard()
    await click('Not now')
    expect(
      calls.some(
        (c) => c.init?.method === 'POST' && c.url.includes('/upload/round/skip'),
      ),
    ).toBe(true)
    expect(text()).toContain('Parked')
  })

  it('a 409 surfaces the server conflict copy', async () => {
    outcomeBehavior = 'conflict'
    await renderCard()
    await click('Keep it')
    await click('Confirm')
    expect(text()).toContain('Already decided')
  })

  it('the mount fetch cannot clobber the turn’s presented item', async () => {
    hydratedRendering = {
      ...RENDERING,
      interpretation_id: 'interp-OTHER',
      text: 'A different reading entirely.',
    }
    await renderCard()
    // The turn's rendering stands: the foreign hydration is ignored.
    expect(text()).toContain('Reading 1: the day moved.')
    expect(text()).not.toContain('A different reading entirely.')
  })

  it('consequenceCopy covers all five menu actions', () => {
    expect(consequenceCopy('keep', RENDERING)).toContain('creates nothing')
    expect(consequenceCopy('talk', RENDERING)).toContain('Crane')
    expect(consequenceCopy('artifact', RENDERING)).toContain('no task, project, or idea')
    expect(consequenceCopy('undertaking', RENDERING)).toContain('creates a task')
    expect(consequenceCopy('train', RENDERING, { seatName: 'Weaver' })).toContain(
      'Nothing trains until you approve that claim',
    )
  })

  it('the [[round-offer]] marker is stripped from display text', () => {
    expect(
      stripRoundOfferMarker("You've got 3 waiting. Want to go through them?\n[[round-offer]]"),
    ).toBe("You've got 3 waiting. Want to go through them?")
    expect(stripRoundOfferMarker('Hello there.')).toBe('Hello there.')
  })
})
