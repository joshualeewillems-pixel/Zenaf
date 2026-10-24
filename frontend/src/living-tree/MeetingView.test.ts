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

function state(status: string, messages: Msg[]): St {
  return {
    archetype_id: 'conductor',
    keystone_index: 1,
    conversation_id: 'meeting-conductor-1',
    status,
    stage: status === 'complete' ? 'complete' : 'encounter',
    has_script: true,
    character: 'Weaver',
    demeanor: status === 'complete' ? 'Hears how parts fit; cannot leave a loose thread.' : null,
    messages,
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

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
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

    const input = container.querySelector('input') as HTMLInputElement
    expect(input).toBeTruthy()
    await act(async () => setInputValue(input, 'Well, they could all be right at different times.'))
    const sendBtn = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Send')
    await act(async () => {
      sendBtn!.dispatchEvent(new window.MouseEvent('click', { bubbles: true }))
    })
    await flush(30000)
    expect(container.textContent).toContain('My first impression of you')

    const input2 = container.querySelector('input') as HTMLInputElement
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
