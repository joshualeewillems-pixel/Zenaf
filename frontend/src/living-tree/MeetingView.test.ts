// @vitest-environment jsdom
/**
 * MeetingView closing-batch regression (the Weaver pattern,
 * 2026-10-23): when the closing turn's response carries her reply
 * AND the reveal paragraphs in one state payload (status flips to
 * complete in the same response), every one of those bubbles must
 * still type in and remain visible above the completion card.
 *
 * Root cause pinned here: the backend payload was always sound —
 * the reply and the reveal arrive together, in order. The defect
 * was presentational: the completion title, the reveal card, and
 * the complete footer rendered INSTANTLY on the status flip, while
 * the closing bubbles sat behind the sequential typewriter queue
 * (~110 chars/sec, unbounded under mobile timer throttling) — so
 * the user's closing screen showed the card with neither her reply
 * nor the reveal above it (Joshua's closing screenshot). The fix
 * gates ALL completion presentation on the voice queue being fully
 * drained; the intermediate assertions below are the regression:
 * card ABSENT while her closing words are still queued, PRESENT
 * once they have all been delivered.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { MeetingView } from './MeetingView'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Msg = { id: string; role: 'user' | 'voice'; body: string; archetype_id?: string }
type St = {
  archetype_id: string
  keystone_index: number
  conversation_id: string
  status: string
  stage: string | null
  has_script: boolean
  character: string | null
  demeanor: string | null
  messages: Msg[]
  run_id?: string
  read_only?: boolean
}

const v = (id: string, body: string): Msg => ({ id, role: 'voice', body, archetype_id: 'conductor' })
const u = (id: string, body: string): Msg => ({ id, role: 'user', body })

const OPENING = [
  v('v1', 'Ah! A visitor. Wonderful. Tell me — does this look broken to you, or merely unfinished?'),
  v('v2', 'Seven parts on this bench, and not one of them agrees with the others.'),
]
const TURN1 = [
  ...OPENING,
  u('u1', 'Well, they could all be right at different times.'),
  v('v3', 'Fair enough — an engaged reply from the bench.'),
  v('v4', 'My first impression of you, in her own words.'),
]
const TURN2 = [
  ...TURN1,
  u('u2', "I definitely think you're understanding what I'm saying"),
  v('v5', 'A brief engaged reply to the affirmation.'),
  v('v6', "Well. I think we've actually met now — which is rarer than people think."),
  v('v7', "I'm the Weaver. I hear how parts fit, and I cannot leave a loose thread."),
  v('v8', "Don't wait for the instrument to be finished before you come back."),
]

function state(status: string, messages: Msg[], runId = 'run-1'): St {
  return {
    archetype_id: 'conductor',
    keystone_index: 1,
    conversation_id: `meeting-conductor-1-${runId}`,
    status,
    stage: status === 'complete' ? 'complete' : 'encounter',
    has_script: true,
    character: 'Weaver',
    demeanor: status === 'complete' ? 'Hears how parts fit; cannot leave a loose thread.' : null,
    messages,
    run_id: runId,
    read_only: status === 'complete',
  }
}

let turnCount = 0

function installFetch() {
  turnCount = 0
  const fetchMock = vi.fn(async (url: string, init?: { method?: string }) => {
    const path = String(url)
    let payload: St
    if (path.includes('/meeting/start')) payload = state('active', OPENING)
    else if (path.includes('/meeting/turn')) {
      turnCount += 1
      payload = turnCount === 1 ? state('active', TURN1) : state('complete', TURN2)
    } else if (path.includes('/meeting/pause') || path.includes('/meeting/restart')) {
      payload = state('not_started', [])
    } else payload = state('not_started', [])
    return {
      ok: true,
      status: 200,
      json: async () => payload,
    } as Response
  })
  vi.stubGlobal('fetch', fetchMock)
}

let container: HTMLDivElement
let root: Root

async function flush(ms: number) {
  // Advance fake timers in slices, letting effects chain.
  let remaining = ms
  while (remaining > 0) {
    const step = Math.min(500, remaining)
    await act(async () => {
      vi.advanceTimersByTime(step)
    })
    remaining -= step
  }
}

function setInputValue(input: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    'value',
  )?.set
  setter?.call(input, value)
  input.dispatchEvent(new window.Event('input', { bubbles: true }))
}

beforeEach(() => {
  vi.useFakeTimers()
  installFetch()
  ;(window.Element.prototype as unknown as { scrollIntoView: () => void }).scrollIntoView = () => {}
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('MeetingView closing batch', () => {
  it('renders her reply and the reveal after the closing turn', async () => {
    await act(async () => {
      root.render(React.createElement(MeetingView, { archetypeId: 'conductor', onClose: () => {} }))
    })
    await flush(100)

    const beginBtn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Begin the meeting'),
    )
    expect(beginBtn).toBeTruthy()
    await act(async () => {
      beginBtn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    await flush(30000)
    expect(container.textContent).toContain('Seven parts on this bench')

    const input = container.querySelector('textarea') as HTMLTextAreaElement
    expect(input).toBeTruthy()
    await act(async () => setInputValue(input, 'Well, they could all be right at different times.'))
    const sendBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Send')
    await act(async () => {
      sendBtn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    await flush(30000)
    expect(container.textContent).toContain('My first impression of you')

    const input2 = container.querySelector('textarea') as HTMLTextAreaElement
    await act(async () => setInputValue(input2, "I definitely think you're understanding what I'm saying"))
    const sendBtn2 = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Send')
    await act(async () => {
      sendBtn2!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    // REGRESSION (intermediate state): the closing state has been
    // applied — status is complete in the record — but her closing
    // bubbles are still behind the typewriter queue (fake timers
    // have not advanced). NO completion presentation may show yet:
    // not the card, not the "You've met" title, not the footer.
    // This is exactly the frame Joshua's closing screenshot froze.
    expect(container.textContent).not.toContain('FIRST MEETING — COMPLETE')
    expect(container.textContent).not.toContain("You've met the Weaver")
    expect(container.textContent).not.toContain('Back to the tree')
    expect(container.textContent).not.toContain("I'm the Weaver.")
    await flush(60000)
    // The queue has drained: NOW the completion card is present…
    expect(container.textContent).toContain('FIRST MEETING — COMPLETE')
    expect(container.textContent).toContain("You've met the Weaver")
    // …and so are her closing words: the reply to the affirmation
    // and every reveal paragraph, in the transcript above the card.
    expect(container.textContent).toContain('A brief engaged reply to the affirmation.')
    expect(container.textContent).toContain("we've actually met now")
    expect(container.textContent).toContain("I'm the Weaver.")
    expect(container.textContent).toContain('finished before you come back')
  })
})

describe('MeetingView text selection', () => {
  it('opts the meeting panel back into selectable text under a user-select:none ancestor', async () => {
    // REGRESSION (2026-10-28, Joshua): the meeting transcript was not
    // selectable on iOS, so he had to screen-record instead of copying
    // text. Cause: MeetingView renders inside LivingTree's .ltree div,
    // which sets user-select:none, and nothing opted the panel back
    // in. The panel's own rule must beat the inherited none.
    container.style.userSelect = 'none'
    await act(async () => {
      root.render(React.createElement(MeetingView, { archetypeId: 'conductor', onClose: () => {} }))
    })
    await flush(100)
    const panel = container.querySelector('.mtg-panel') as HTMLElement
    expect(panel).toBeTruthy()
    expect(window.getComputedStyle(panel).getPropertyValue('user-select')).toBe('text')
  })
})

describe('MeetingView user completion', () => {
  it('completes an active meeting at the visitor’s word and shows the card once the closing words drain', async () => {
    const COMPLETE_MSGS = [
      ...OPENING,
      u('u9', 'Just poking around — a friend said to look in.'),
      v('v6', "Well. I think we've actually met now — which is rarer than people think."),
      v('v7', "I'm the Weaver. I hear how parts fit, and I cannot leave a loose thread."),
      v('v8', "Don't wait for the instrument to be finished before you come back."),
    ]
    const fetchMock = vi.fn(async (url: string) => {
      const path = String(url)
      const payload = path.includes('/meeting/complete')
        ? state('complete', COMPLETE_MSGS)
        : state('active', OPENING)
      return {
        ok: true,
        status: 200,
        json: async () => payload,
      } as Response
    })
    vi.stubGlobal('fetch', fetchMock)

    await act(async () => {
      root.render(React.createElement(MeetingView, { archetypeId: 'conductor', onClose: () => {} }))
    })
    await flush(30000)
    // The active footer is showing, so the active meeting state applied.
    // (The opening bubbles themselves only paint on the next render —
    // first-hydration priming marks them seen without a state change to
    // re-render on; a pre-existing quirk, out of this fix's scope.)
    const completeBtn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Complete this meeting'),
    )
    expect(completeBtn).toBeTruthy()
    await act(async () => {
      completeBtn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    // The complete state is applied but her closing words are still
    // behind the typewriter queue: no completion presentation yet.
    expect(container.textContent).not.toContain('FIRST MEETING — COMPLETE')
    expect(container.textContent).not.toContain("You've met the Weaver")
    await flush(60000)
    // The queue has drained: the card, the title, and her closing
    // words are all present — and Meet again is now available.
    expect(container.textContent).toContain('FIRST MEETING — COMPLETE')
    expect(container.textContent).toContain("You've met the Weaver")
    expect(container.textContent).toContain('Seven parts on this bench')
    expect(container.textContent).toContain("we've actually met now")
    expect(container.textContent).toContain('Meet again')
  })
})

describe('MeetingView Meet Again (non-destructive, Slice 5)', () => {
  type Enc = {
    run_id: string
    run_number: number
    status: string
    stage: string | null
    verification_status: string
    message_count: number
    created_at: string
    completed_at: string | null
    predecessor_run_id: string | null
    predecessor_link_kind: string
    identity_kind: string
    lineage_label: string | null
    conversation_id: string
    read_only: boolean
    fence_state: string | null
  }

  const HISTORY: Enc[] = [
    {
      run_id: 'run-2',
      run_number: 2,
      status: 'complete',
      stage: 'complete',
      verification_status: 'read_consistency_verified',
      message_count: 9,
      created_at: '2026-11-09T10:00:00+00:00',
      completed_at: '2026-11-09T10:20:00+00:00',
      predecessor_run_id: 'run-1',
      predecessor_link_kind: 'witnessed',
      identity_kind: 'generated',
      lineage_label: 'follows',
      conversation_id: 'meeting-conductor-1-run-2',
      read_only: true,
      fence_state: 'closed',
    },
    {
      run_id: 'run-1',
      run_number: 1,
      status: 'complete',
      stage: 'complete',
      verification_status: 'legacy-unverified',
      message_count: 5,
      created_at: '2026-10-20T10:00:00+00:00',
      completed_at: '2026-10-20T10:15:00+00:00',
      predecessor_run_id: null,
      predecessor_link_kind: 'witnessed',
      identity_kind: 'legacy-record',
      lineage_label: null,
      conversation_id: 'meeting-conductor-1-run-1',
      read_only: true,
      fence_state: 'closed',
    },
  ]

  // A fetch mock for the Meet Again flow: the mount hydrates a
  // completed run-2 state + the history; /meet-again records its
  // calls (url, headers, body) and answers from `meetAgainNext`.
  function installMeetAgainFetch(opts?: {
    meetAgainFailsFirst?: boolean
  }) {
    const calls: { url: string; init?: { headers?: Record<string, string>; body?: string } }[] = []
    let meetAgainCount = 0
    const fetchMock = vi.fn(async (url: string, init?: { headers?: Record<string, string>; body?: string }) => {
      const path = String(url)
      calls.push({ url: path, init })
      if (path.includes('/meeting/meet-again')) {
        meetAgainCount += 1
        if (opts?.meetAgainFailsFirst && meetAgainCount === 1) {
          return { ok: false, status: 500, json: async () => ({ detail: 'boom' }) } as Response
        }
        const body = JSON.parse(init?.body || '{}') as { predecessor_run_id?: string }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            encounter: { run_id: 'run-3', run_number: 3, status: 'in_progress', predecessor_run_id: body.predecessor_run_id },
            state: state('active', OPENING, 'run-3'),
            resumed: false,
            successor_exists: false,
          }),
        } as Response
      }
      if (path.includes('/meeting/encounters/')) {
        const runId = path.split('/meeting/encounters/')[1].split('?')[0]
        const enc = HISTORY.find((e) => e.run_id === runId)!
        return {
          ok: true,
          status: 200,
          json: async () => ({
            encounter: enc,
            messages: [v('h1', 'A line from the earlier run.'), u('h2', 'And my answer then.')],
            total: 2,
            read_only: true,
            verification_note: 'The read-consistency check note.',
          }),
        } as Response
      }
      if (path.includes('/meeting/encounters')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ encounters: HISTORY }),
        } as Response
      }
      if (path.includes('/meeting?')) {
        return { ok: true, status: 200, json: async () => state('complete', TURN2, 'run-2') } as Response
      }
      return { ok: true, status: 200, json: async () => state('not_started', []) } as Response
    })
    vi.stubGlobal('fetch', fetchMock)
    return { calls, get meetAgainCount() { return meetAgainCount } }
  }

  async function renderComplete() {
    await act(async () => {
      root.render(React.createElement(MeetingView, { archetypeId: 'conductor', onClose: () => {} }))
    })
    await flush(60000)
  }

  function clickMeetAgain() {
    const btn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Meet again'),
    )
    expect(btn).toBeTruthy()
    return act(async () => {
      btn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
  }

  it('T-FE-1: Meet Again calls /meet-again once (not /restart, not /start) with the key + predecessor, and applies the new state', async () => {
    const { calls } = installMeetAgainFetch()
    await renderComplete()
    expect(container.textContent).toContain('FIRST MEETING — COMPLETE')
    await clickMeetAgain()
    await flush(100)

    const meetAgainCalls = calls.filter((c) => c.url.includes('/meeting/meet-again'))
    expect(meetAgainCalls).toHaveLength(1)
    expect(calls.some((c) => c.url.includes('/meeting/restart'))).toBe(false)
    expect(calls.some((c) => c.url.includes('/meeting/start'))).toBe(false)
    const headers = meetAgainCalls[0].init?.headers || {}
    expect(headers['Idempotency-Key']).toMatch(/^[0-9a-f]{32}$/)
    const body = JSON.parse(meetAgainCalls[0].init?.body || '{}') as Record<string, unknown>
    expect(body.predecessor_run_id).toBe('run-2')
    expect(body.archetype_id).toBe('conductor')
    // The new run's state applied: the completion card is gone and
    // the composer is back (the meeting is active again).
    expect(container.textContent).not.toContain('FIRST MEETING — COMPLETE')
    expect(container.querySelector('textarea')).toBeTruthy()
  })

  it('T-FE-2: a retry after a failure reuses the same Idempotency-Key', async () => {
    const { calls } = installMeetAgainFetch({ meetAgainFailsFirst: true })
    await renderComplete()
    await clickMeetAgain()
    await flush(100)
    // The first tap failed; the error shows and the meeting is still
    // the completed run (Meet again is still offered).
    expect(container.textContent).toContain('Meet again')
    await clickMeetAgain()
    await flush(100)
    const meetAgainCalls = calls.filter((c) => c.url.includes('/meeting/meet-again'))
    expect(meetAgainCalls).toHaveLength(2)
    const key1 = meetAgainCalls[0].init?.headers?.['Idempotency-Key']
    const key2 = meetAgainCalls[1].init?.headers?.['Idempotency-Key']
    expect(key1).toMatch(/^[0-9a-f]{32}$/)
    expect(key2).toBe(key1) // the retry reuses the tap's key — never re-minted
    // The retry succeeded: the new run is active.
    expect(container.querySelector('textarea')).toBeTruthy()
  })

  it('T-FE-3: the history renders (badges, lineage) and a tap opens a read-only revisit with the input closed', async () => {
    installMeetAgainFetch()
    await renderComplete()
    // The history section lists both runs, newest first, with the
    // renamed badge wording and the lineage label.
    expect(container.textContent).toContain('EARLIER MEETINGS')
    expect(container.textContent).toContain('Run 2')
    expect(container.textContent).toContain('Run 1')
    expect(container.textContent).toContain('read consistency verified')
    expect(container.textContent).toContain('archive record — completeness not established')
    expect(container.textContent).toContain('follows')

    // Tap the legacy run: its transcript opens read-only.
    const run1Btn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Run 1'),
    )
    expect(run1Btn).toBeTruthy()
    await act(async () => {
      run1Btn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    await flush(100)
    expect(container.textContent).toContain('RUN 1 — READ ONLY')
    expect(container.textContent).toContain('A line from the earlier run.')
    expect(container.textContent).toContain('The read-consistency check note.')
    // The input is closed while reading history.
    expect(container.querySelector('textarea')).toBeNull()
    expect(container.textContent).toContain('Back to the current meeting')

    // Back returns to the live meeting.
    const backBtn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Back to the current meeting'),
    )
    await act(async () => {
      backBtn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    await flush(100)
    expect(container.textContent).not.toContain('RUN 1 — READ ONLY')
    expect(container.textContent).toContain('FIRST MEETING — COMPLETE')
  })
})

describe('MeetingView composer Enter key', () => {
  // REGRESSION (2026-11-05, Joshua): the auto-growing composer sent on
  // any Enter without Shift — and a phone has no Shift key, so the
  // return key sent instead of inserting a newline, making a second
  // paragraph impossible. Rule: on a coarse-pointer (touch) device
  // Enter inserts a newline and only the Send button sends; on desktop
  // Enter sends and Shift+Enter inserts a newline.
  function stubMatchMedia(coarse: boolean) {
    vi.stubGlobal(
      'matchMedia',
      (query: string) =>
        ({
          matches: coarse && query === '(pointer: coarse)',
          media: query,
          addEventListener: () => {},
          removeEventListener: () => {},
          addListener: () => {},
          removeListener: () => {},
          dispatchEvent: () => false,
          onchange: null,
        }) as MediaQueryList,
    )
  }

  async function beginMeeting() {
    await act(async () => {
      root.render(React.createElement(MeetingView, { archetypeId: 'conductor', onClose: () => {} }))
    })
    await flush(100)
    const beginBtn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Begin the meeting'),
    )
    expect(beginBtn).toBeTruthy()
    await act(async () => {
      beginBtn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    await flush(30000)
  }

  function pressEnter(input: HTMLTextAreaElement) {
    input.dispatchEvent(
      new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
    )
  }

  it('on a touch device Enter does not send — only the Send button does', async () => {
    stubMatchMedia(true)
    await beginMeeting()
    const input = container.querySelector('textarea') as HTMLTextAreaElement
    expect(input).toBeTruthy()
    await act(async () => setInputValue(input, 'A first line.'))
    await act(async () => pressEnter(input))
    await flush(100)
    expect(turnCount).toBe(0)
    const sendBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Send')
    await act(async () => {
      sendBtn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    await flush(100)
    expect(turnCount).toBe(1)
  })

  it('on a desktop Enter sends', async () => {
    stubMatchMedia(false)
    await beginMeeting()
    const input = container.querySelector('textarea') as HTMLTextAreaElement
    expect(input).toBeTruthy()
    await act(async () => setInputValue(input, 'A first line.'))
    await act(async () => pressEnter(input))
    await flush(100)
    expect(turnCount).toBe(1)
  })
})
