// @vitest-environment jsdom
/**
 * Durable Tree Talk Slice A — TreeTalkSheet resolution tests.
 *
 * Seat sheet: auto-resumes the most recent talk involving that seat,
 * else holds a fresh talk- id; "+" is always visible and runs the
 * disposition flow (archive / delete / keep open + save-as logo).
 * The seat's conversation strip sits beside "+": the seat's talks
 * in one continuum, the open one marked, the first meeting pinned.
 * You-node: the recent-talks list plus "Start new" and the archived
 * section; picking a talk opens it. List failure: error state,
 * never a client-history fallback.
 *
 * No JSX (vitest includes *.test.ts only): createElement throughout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import TreeTalkSheet, { newTalkId } from './TreeTalkSheet'
import { getTalkIdentity, TALK_IDENTITY_STORAGE_KEY, TALK_PALETTE } from './talkIdentity'

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
  archived?: boolean
  symbol?: number | null
  color?: string | null
}

const TALK_MENTOR = 'talk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const TALK_MENTOR_OLDER = 'talk-dddddddddddddddddddddddddddddddd'
const TALK_CHAMPION = 'talk-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
const CONV_OVERRIDE = 'talk-cccccccccccccccccccccccccccccccc'
const TALK_ARCHIVED = 'talk-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
const MEETING_MENTOR = 'meeting-mentor-1'
/** Server identity carried by TALK_MENTOR_OLDER in the fixtures. */
const OLDER_COLOR = '#b5533c'

function meeting(id: string, seats: string[], preview: string, count = 4): Talk {
  return { ...talk(id, seats, preview, count), kind: 'meeting' }
}

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
let requests: Array<{ url: string; method: string; body: string | null }>
let listBehavior: 'ok' | 'fail' | 'fail-seat'

const KNOWN_IDS = new Set([
  TALK_MENTOR,
  TALK_MENTOR_OLDER,
  TALK_CHAMPION,
  CONV_OVERRIDE,
  TALK_ARCHIVED,
  MEETING_MENTOR,
])

function installFetch() {
  calls = []
  requests = []
  const fetchMock = vi.fn((url: string, init?: { method?: string; body?: string }) => {
    calls.push(url)
    requests.push({
      url,
      method: init?.method ?? 'GET',
      body: typeof init?.body === 'string' ? init.body : null,
    })
    if (url.includes('/council/archetypes/status')) {
      return Promise.resolve(ok({ archetypes: [] }))
    }
    if (url.includes('/conversation/list')) {
      const params = new URL(url, 'http://x').searchParams
      const seat = params.get('seat')
      if (listBehavior === 'fail' || (listBehavior === 'fail-seat' && seat)) {
        return Promise.reject(new Error('list down'))
      }
      // The server applies the seat filter before the limit: a
      // seat-scoped fetch returns only that seat's threads. Meeting
      // conversations are listed only when the caller opts in
      // (include_meetings=true) — the seat resume lookup never does.
      // Archived conversations are excluded unless the caller opts
      // in (include_archived=true).
      const includeMeetings = params.get('include_meetings') === 'true'
      const includeArchived = params.get('include_archived') === 'true'
      const older: Talk = {
        ...talk(TALK_MENTOR_OLDER, ['mentor'], 'mentor older preview'),
        symbol: 2,
        color: OLDER_COLOR,
      }
      const archived: Talk = {
        ...talk(TALK_ARCHIVED, ['mentor'], 'archived preview'),
        archived: true,
        symbol: 5,
        color: '#4a7fb5',
      }
      const all = [
        meeting(MEETING_MENTOR, ['mentor'], 'meeting preview'),
        talk(TALK_CHAMPION, ['champion'], 'champion preview'),
        talk(TALK_MENTOR, ['mentor'], 'mentor preview'),
        older,
        archived,
      ]
      const conversations = all.filter(
        (t) =>
          (includeMeetings || !t.conversation_id.startsWith('meeting-')) &&
          (includeArchived || !t.archived) &&
          (!seat || t.seats.includes(seat)),
      )
      return Promise.resolve(ok({ conversations }))
    }
    if (url.includes('/conversation/invitations')) {
      return Promise.resolve(ok({ conversation_id: CONV_OVERRIDE, invitations: [] }))
    }
    if (url.includes('/conversation?')) {
      const id = new URL(url, 'http://x').searchParams.get('conversation_id') ?? ''
      if (!KNOWN_IDS.has(id)) {
        // A never-sent thread: no messages, total 0.
        return Promise.resolve(ok({ conversation_id: id, messages: [], total: 0 }))
      }
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

function plusButton(): HTMLButtonElement {
  const btn = container.querySelector('[aria-label="New conversation"]')
  if (!btn) throw new Error('plus button not found')
  return btn as HTMLButtonElement
}

/** A badge button in the seat conversation strip, by aria-label. */
function railButton(label: string): HTMLButtonElement {
  const group = container.querySelector('[aria-label="Conversations with this seat"]')
  if (!group) throw new Error('conversation strip not found')
  const btn = Array.from(group.querySelectorAll('button')).find(
    (b) => b.getAttribute('aria-label') === label,
  )
  if (!btn) throw new Error(`strip button "${label}" not found`)
  return btn as HTMLButtonElement
}

function dispositionRequests(): Array<{ url: string; method: string; body: string | null }> {
  return requests.filter((r) => r.url.includes('/conversation/disposition'))
}

async function click(el: Element) {
  await act(async () => {
    ;(el as HTMLElement).click()
  })
  await flush()
}

beforeEach(() => {
  listBehavior = 'ok'
  localStorage.clear()
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
    expect(container.querySelector('[aria-label="New conversation"]')).not.toBeNull()
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

  it('+ asks the disposition first when the open conversation has messages', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    await click(plusButton())
    // The founder's three labels, verbatim.
    expect(container.textContent).toContain('Archive for data')
    expect(container.textContent).toContain('Delete all system references')
    expect(container.textContent).toContain('Keep open')
    // Nothing written yet, and we are still in the same conversation.
    expect(dispositionRequests()).toEqual([])
    expect(container.textContent).toContain('thread talk-aaaa')
  })

  it('+ on an empty thread resets immediately, no prompt', async () => {
    renderSheet({ seatKey: 'skeptic', displayName: 'Raven' })
    await flush()
    const before = calls.filter((u) => u.includes('/conversation?conversation_id=')).length
    await click(plusButton())
    expect(container.textContent).not.toContain('Archive for data')
    const hyds = calls.filter((u) => u.includes('/conversation?conversation_id='))
    expect(hyds.length).toBeGreaterThan(before)
    const id = new URL(hyds[hyds.length - 1], 'http://x').searchParams.get(
      'conversation_id',
    )
    expect(id).toMatch(/^talk-[0-9a-f]{32}$/)
    expect(dispositionRequests()).toEqual([])
  })

  it('cancelling the disposition prompt stays and writes nothing', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    await click(plusButton())
    await click(buttonByText('Cancel'))
    expect(container.textContent).not.toContain('Archive for data')
    expect(container.textContent).toContain('thread talk-aaaa')
    expect(dispositionRequests()).toEqual([])
    expect(
      requests.some((r) => r.method === 'DELETE' && r.url.includes('/conversation/')),
    ).toBe(false)
  })
})

describe('seat conversation strip (the rail)', () => {
  it('the header carries + and the strip — no New conversation button, no History, no badge button', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    expect(plusButton().textContent?.trim()).toBe('+')
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => (b.textContent ?? '').trim() === 'History',
      ),
    ).toBe(false)
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => (b.textContent ?? '').trim() === 'New conversation',
      ),
    ).toBe(false)
    expect(
      container.querySelector(
        '[aria-label="Choose a color and symbol for this conversation"]',
      ),
    ).toBeNull()
    expect(container.textContent).not.toContain('History')
  })

  it('the strip holds the seat’s conversations in one continuum, the open one marked', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    // Seat-scoped list opting into meetings — the same endpoint as
    // the seat lookup, a generous bound (not the old panel's 10).
    expect(
      calls.some(
        (u) =>
          u.includes('/conversation/list') &&
          u.includes('seat=mentor') &&
          u.includes('limit=100') &&
          u.includes('include_meetings=true'),
      ),
    ).toBe(true)
    // The open conversation is IN the strip (not excluded), marked.
    const open = railButton('mentor preview')
    expect(open.getAttribute('aria-current')).toBe('true')
    // And the seat's other kept conversation is there too.
    expect(railButton('mentor older preview')).toBeDefined()
    // The archived talk never enters the strip.
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => b.getAttribute('aria-label') === 'archived preview',
      ),
    ).toBe(false)
  })

  it('tapping a strip badge populates that conversation in place', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    await click(railButton('mentor older preview'))
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR_OLDER}`)),
    ).toBe(true)
    expect(container.textContent).toContain('thread talk-dddd')
    // Now the tapped badge is the marked (open) one.
    expect(railButton('mentor older preview').getAttribute('aria-current')).toBe('true')
  })

  it('a badge with a server identity renders its glyph tinted with its color', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    const badge = railButton('mentor older preview')
    const disc = badge.querySelector('span')
    if (!disc) throw new Error('badge disc not found')
    // #b5533c as jsdom serializes it.
    expect(disc.style.background).toContain('rgb(181, 83, 60)')
    const img = badge.querySelector('img')
    if (!img) throw new Error('badge glyph not found')
    expect(img.getAttribute('src')).toContain('symbol-02')
    expect((img as HTMLImageElement).style.mixBlendMode).toBe('multiply')
  })
})

describe('the + flow: save-as identity at disposition time', () => {
  it('keep open → pick color + symbol → the identity persists server-side and a fresh thread opens', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    await click(plusButton())
    await click(buttonByText('Keep open'))
    // Pick a palette swatch — the palette is built from the current
    // seat/strand colors, so the test must not hard-code which entry
    // (the old Mentor gold #c9a86a left the palette when the logo
    // sheet's measured colors landed in #357).
    const picked = TALK_PALETTE[0]
    const color = Array.from(container.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === `Color ${picked}`,
    )
    if (!color) throw new Error('color swatch not found')
    await click(color)
    const symbol = Array.from(container.querySelectorAll('button')).find(
      (b) => b.getAttribute('aria-label') === 'Symbol 2',
    )
    if (!symbol) throw new Error('symbol button not found')
    await click(symbol)
    await click(buttonByText('Save & start new'))
    const posts = dispositionRequests()
    expect(posts.length).toBe(1)
    const body = JSON.parse(posts[0].body ?? '{}') as Record<string, unknown>
    expect(body.conversation_id).toBe(TALK_MENTOR)
    expect(body.action).toBe('keep_open')
    expect(body.color).toBe(picked)
    expect(body.symbol).toBe(2)
    // The local fallback mirror agrees.
    const stored = getTalkIdentity(TALK_MENTOR)
    expect(stored.color).toBe(picked)
    expect(stored.symbol).toBe(2)
    // A fresh thread opened in the same screen.
    const hyds = calls.filter((u) => u.includes('/conversation?conversation_id='))
    const id = new URL(hyds[hyds.length - 1], 'http://x').searchParams.get(
      'conversation_id',
    )
    expect(id).toMatch(/^talk-[0-9a-f]{32}$/)
    expect(id).not.toBe(TALK_MENTOR)
  })

  it('archive → save-as → the disposition posts action=archive and a fresh thread opens', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    await click(plusButton())
    await click(buttonByText('Archive for data'))
    // The save-as step preselects a color + symbol: accepting as-is
    // is one tap.
    await click(buttonByText('Save & start new'))
    const posts = dispositionRequests()
    expect(posts.length).toBe(1)
    const body = JSON.parse(posts[0].body ?? '{}') as Record<string, unknown>
    expect(body.conversation_id).toBe(TALK_MENTOR)
    expect(body.action).toBe('archive')
    expect(typeof body.color).toBe('string')
    expect(typeof body.symbol).toBe('number')
    const hyds = calls.filter((u) => u.includes('/conversation?conversation_id='))
    const id = new URL(hyds[hyds.length - 1], 'http://x').searchParams.get(
      'conversation_id',
    )
    expect(id).toMatch(/^talk-[0-9a-f]{32}$/)
    expect(id).not.toBe(TALK_MENTOR)
  })

  it('delete asks one explicit confirmation, then deletes and opens fresh', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    await click(plusButton())
    await click(buttonByText('Delete all system references'))
    // The confirmation step is explicit about irreversibility, and
    // nothing has been deleted yet.
    expect(container.textContent).toContain('cannot be undone')
    expect(requests.some((r) => r.method === 'DELETE')).toBe(false)
    await click(buttonByText('Delete all system references'))
    const deletes = requests.filter(
      (r) => r.method === 'DELETE' && r.url.includes(`/conversation/${TALK_MENTOR}`),
    )
    expect(deletes.length).toBe(1)
    const hyds = calls.filter((u) => u.includes('/conversation?conversation_id='))
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

  it('archived conversations live in the archived section and re-open from it', async () => {
    renderSheet({ seatKey: null })
    await flush()
    // The rediscovery list fetches without the archived opt-in for
    // its main rows, and with it for the archive section.
    expect(
      calls.some((u) => u.includes('/conversation/list') && u.includes('include_archived=true')),
    ).toBe(true)
    expect(container.textContent).toContain('Archived')
    const row = Array.from(container.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('archived preview'),
    )
    if (!row) throw new Error('archived row not found')
    expect(row.textContent).toContain('Archived · ')
    await click(row)
    // Opening an archived conversation just opens it — no
    // disposition call unarchives it.
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_ARCHIVED}`)),
    ).toBe(true)
    expect(dispositionRequests()).toEqual([])
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
    // No resolveSeat: the seat LOOKUP (limit=1) and the general
    // talks fetch never ran, so the list's mentor talk (TALK_MENTOR)
    // is never the hydration target. (The conversation strip does
    // fetch its own seat list — limit=100 — for its badges; that is
    // display data, never resolution.)
    expect(
      calls.some((u) => {
        if (!u.includes('/conversation/list')) return false
        const p = new URL(u, 'http://x').searchParams
        return p.get('limit') === '1' || !p.has('seat')
      }),
    ).toBe(false)
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

  it('override is cleared by the + flow', async () => {
    renderSheet(overrideProps)
    await flush()
    expect(container.textContent).toContain('thread talk-cccc')
    await click(plusButton())
    await click(buttonByText('Keep open'))
    await click(buttonByText('Save & start new'))
    const posts = dispositionRequests()
    expect(posts.length).toBe(1)
    expect(JSON.parse(posts[0].body ?? '{}').conversation_id).toBe(CONV_OVERRIDE)
    const hyds = calls.filter((u) => u.includes('/conversation?conversation_id='))
    const id = new URL(hyds[hyds.length - 1], 'http://x').searchParams.get(
      'conversation_id',
    )
    expect(id).toMatch(/^talk-[0-9a-f]{32}$/)
    expect(id).not.toBe(CONV_OVERRIDE)
  })
})

describe('meetings in the chat list (founder, 2026-11-12)', () => {
  it('you-node list labels the meeting as the seat’s first meeting and routes its tap to the meeting overlay', async () => {
    const opened: string[] = []
    renderSheet({ seatKey: null, onOpenMeeting: (seat: string) => opened.push(seat) })
    await flush()
    // The general list opted into meetings; the row names the meeting.
    expect(
      calls.some((u) => u.includes('/conversation/list') && u.includes('include_meetings=true')),
    ).toBe(true)
    const row = Array.from(container.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('First meeting'),
    )
    if (!row) throw new Error('first-meeting list row not found')
    expect(row.textContent).toContain('meeting preview')
    await click(row)
    expect(opened).toEqual(['mentor'])
    // It never opened as a talk thread: no hydration of the meeting id.
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${MEETING_MENTOR}`)),
    ).toBe(false)
  })

  it('the seat strip pins the first meeting at its head and routes its tap to the meeting overlay', async () => {
    const opened: string[] = []
    renderSheet({
      seatKey: 'mentor',
      displayName: 'Gardener',
      onOpenMeeting: (seat: string) => opened.push(seat),
    })
    await flush()
    // The strip opted into meetings; the resume lookup did not
    // (parse params properly — 'limit=100' contains 'limit=1').
    expect(
      calls.some(
        (u) =>
          u.includes('/conversation/list') &&
          u.includes('seat=mentor') &&
          u.includes('include_meetings=true'),
      ),
    ).toBe(true)
    expect(
      calls.some((u) => {
        if (!u.includes('/conversation/list')) return false
        const p = new URL(u, 'http://x').searchParams
        return (
          p.get('seat') === 'mentor' && p.get('limit') === '1' && !p.has('include_meetings')
        )
      }),
    ).toBe(true)
    // The meeting badge is the strip's FIRST badge (pinned head).
    const group = container.querySelector('[aria-label="Conversations with this seat"]')
    if (!group) throw new Error('conversation strip not found')
    const first = group.querySelector('button')
    if (!first) throw new Error('strip is empty')
    expect(first.getAttribute('aria-label')).toBe('First meeting')
    await click(railButton('First meeting'))
    expect(opened).toEqual(['mentor'])
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${MEETING_MENTOR}`)),
    ).toBe(false)
  })

  it('the seat still auto-resumes its newest TALK even though a newer meeting exists', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    // The lookup never opted into meetings, so the resume target is
    // the talk — the meeting (listed first in History) is not it.
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR}`)),
    ).toBe(true)
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${MEETING_MENTOR}`)),
    ).toBe(false)
  })
})

describe('list failure', () => {  it('shows an error state and never falls back to client-history chat', async () => {
    listBehavior = 'fail'
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    expect(container.textContent).toContain("Couldn't load your conversations")
    expect(container.querySelector('input')).toBeNull()
    expect(calls.some((u) => u.includes('/voice/chat'))).toBe(false)
  })
})

describe('seat-scoped lookup (navigation correction §1)', () => {
  it('seat mounts fetch seat=<seat>&limit=1 and take the first row, never a capped general list', async () => {
    renderSheet({ seatKey: 'mentor', displayName: 'Gardener' })
    await flush()
    const scoped = calls.find(
      (u) => u.includes('/conversation/list') && u.includes('seat=mentor') && u.includes('limit=1'),
    )
    expect(scoped).toBeDefined()
    // The seat fetch must not populate the list-mode cache: no
    // general (unfiltered) list call happens on a seat mount.
    expect(
      calls.some((u) => {
        if (!u.includes('/conversation/list')) return false
        return !new URL(u, 'http://x').searchParams.has('seat')
      }),
    ).toBe(false)
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR}`)),
    ).toBe(true)
  })

  it('pick-mode seat selection uses the same seat-scoped lookup', async () => {
    renderSheet({ seatKey: null })
    await flush()
    await click(buttonByText('Start new'))
    const chip = Array.from(container.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('mentor'),
    )
    if (!chip) throw new Error('mentor chip not found')
    await click(chip)
    expect(
      calls.some((u) => u.includes('/conversation/list') && u.includes('seat=mentor')),
    ).toBe(true)
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR}`)),
    ).toBe(true)
  })

  it('pick-mode lookup failure shows the error state, never a fresh thread', async () => {
    listBehavior = 'fail-seat'
    renderSheet({ seatKey: null })
    await flush()
    await click(buttonByText('Start new'))
    const chip = Array.from(container.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('mentor'),
    )
    if (!chip) throw new Error('mentor chip not found')
    await click(chip)
    expect(container.textContent).toContain("Couldn't load your conversations")
    expect(container.querySelector('input')).toBeNull()
    expect(calls.some((u) => u.includes('/voice/chat'))).toBe(false)
  })
})

describe('override mount conversation-list return path (C2)', () => {
  const overrideProps = {
    seatKey: 'mentor',
    displayName: 'Gardener',
    conversationOverride: { conversationId: CONV_OVERRIDE, seat: 'guardian' },
  }

  it('override mounts offer ← Conversations, and it reaches the general list', async () => {
    renderSheet(overrideProps)
    await flush()
    expect(container.textContent).toContain('thread talk-cccc')
    expect(container.textContent).toContain('← Conversations')
    await click(buttonByText('← Conversations'))
    // List entry fetches the GENERAL list lazily (no seat param).
    expect(
      calls.some((u) => {
        if (!u.includes('/conversation/list')) return false
        return !new URL(u, 'http://x').searchParams.has('seat')
      }),
    ).toBe(true)
    expect(container.textContent).toContain('mentor preview')
    expect(container.textContent).toContain('champion preview')
  })

  it('a fresh mount with a different override lands on the new target (C1 remount mechanism)', async () => {
    renderSheet(overrideProps)
    await flush()
    expect(container.textContent).toContain('thread talk-cccc')
    // The App remounts TreeTalkSheet under a new key when the header
    // shortcut fires; a new mount consumes the new override.
    act(() => {
      root.render(
        React.createElement(TreeTalkSheet, {
          ...overrideProps,
          conversationOverride: { conversationId: TALK_MENTOR, seat: 'mentor' },
          key: 'remount-2',
        } as never),
      )
    })
    await flush()
    expect(
      calls.some((u) => u.includes(`/conversation?conversation_id=${TALK_MENTOR}`)),
    ).toBe(true)
    expect(container.textContent).toContain('thread talk-aaaa')
  })

  it('reports the open conversation id to the Tree (shortcut visibility input)', async () => {
    const seen: Array<string | null> = []
    renderSheet({ ...overrideProps, onChatIdChange: (id: string | null) => seen.push(id) })
    await flush()
    expect(seen).toContain(CONV_OVERRIDE)
    const seen2: Array<string | null> = []
    act(() => {
      root.render(
        React.createElement(TreeTalkSheet, {
          seatKey: 'mentor',
          displayName: 'Gardener',
          onChatIdChange: (id: string | null) => seen2.push(id),
          key: 'seat-mount',
        } as never),
      )
    })
    await flush()
    expect(seen2).toContain(TALK_MENTOR)
  })
})
