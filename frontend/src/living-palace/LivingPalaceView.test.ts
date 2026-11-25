// @vitest-environment jsdom
/**
 * The Living Palace — jsdom render verification against a stubbed
 * API (the same routes the product uses: the Vision Execution entity
 * lists, capacity profiles, core profiles; the strand resolve and
 * the permission home for the boundaries panel).
 *
 * The fixture body of work: one initiative with two floors, one
 * loose project, one loose task, one undeveloped idea. The suite
 * asserts the descent compound → building → floor → room; that the
 * chat's subject follows each selection through the living_palace
 * carriage; that a room's furniture is earned (the dependency
 * window's reading, the mandala only at convergence) while the
 * affordance instruments stand unpopulated (empty scales, plain
 * vessel); and that the boundaries panel composes ONLY from records
 * the stubbed API serves — plus its honest statement that no
 * per-subject boundary record exists. CouncilChat is stubbed — the
 * chat seam is covered by its own suite.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

const chatProps: { conversationId?: string | null; context?: Record<string, unknown> }[] = []
vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: { conversationId?: string | null; context?: Record<string, unknown> }) => {
      chatProps.push(props)
      return ReactMod.createElement('div', {
        'data-testid': 'maeve-chat',
        'data-conversation-id': props.conversationId ?? '',
      })
    },
  }
})

import LivingPalaceView from './LivingPalaceView'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const INITIATIVE = {
  id: 'i1', source_idea_id: null, title: 'Rebuild the workshop business', brief: '', status: 'Active',
  owner_id: null, priority: '', target_date: null, notes: '', next_step_ai: '',
  created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
}
const P1 = {
  id: 'p1', initiative_id: 'i1', title: 'Winter client season', brief: '', status: 'Active',
  owner_id: 'per1', supporting_owner_ids: [], priority: '', start_date: null, end_date: null,
  estimated_weekly_hours: 6, next_step_ai: '', notes: '',
  created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
}
const P2 = {
  id: 'p2', initiative_id: 'i1', title: 'Spring commissions', brief: '', status: 'Active',
  owner_id: null, supporting_owner_ids: [], priority: '', start_date: null, end_date: null,
  estimated_weekly_hours: null, next_step_ai: '', notes: '',
  created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
}
const LP = { ...P2, id: 'lp', initiative_id: null, title: 'Loose project' }

function taskRow(partial: Record<string, unknown>): Record<string, unknown> {
  return {
    project_id: 'p1', parent_task_id: null, title: 'Task', description: '',
    assignee_id: null, status: 'Todo', priority: '', estimated_hours: null,
    due_date: null, dependency_ids: [], completion_criteria: '', notes: '',
    created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    seat_ref: '', origin_seat: null, origin_conversation_id: null,
    origin_message_id: null, responsible_seat: null, ...partial,
  }
}

const TASKS = [
  taskRow({ id: 'ta', title: 'Alpha', notes: 'The yard confirmed Tuesday.' }),
  taskRow({ id: 'tb', title: 'Beta', status: 'In Progress' }),
  taskRow({ id: 'tc', title: 'Gamma', dependency_ids: ['tb'] }),
  taskRow({ id: 'tf', project_id: 'p2', title: 'Convergent', dependency_ids: ['ta', 'tb'] }),
  taskRow({ id: 'tg', project_id: 'p2', title: 'After convergent', dependency_ids: ['tf'] }),
  taskRow({ id: 'lt', project_id: null, title: 'Standalone errand' }),
]

const CORE_PROFILE = {
  id: 'cp1', is_canonical: true, name: 'Core', core_definition: '', current_goals: '',
  growth_focus_12_months: '', economic_engine: '', non_negotiables: 'No work on Sundays.',
  strategic_filter: '', current_constraints: '', capacity_limit: '', kill_philosophy: '',
  strength_positioning: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response
}

/** The attributed read the stub serves for any subject — a resolved,
 *  empty read by default; the attributed-read describe replaces it. */
const EMPTY_READ = {
  resolved: true,
  subject: { entity_type: 'task', entity_id: 'tc', title: 'Gamma' },
  steward_gate_open: false,
  boundaries: {
    expressed: [],
    proposed: [],
    established: [],
    enforceable: {
      permission_home_enabled: false,
      permission_consent_given: false,
      steward_derivation: false,
      steward_coordination: false,
    },
  },
  kintsugi: null,
  guests: { attending: [] },
  pending: [],
}
let attributedPayload: unknown = EMPTY_READ

/** Every POST the view makes, recorded by the fetch stub: the
 *  verdict door's acts are asserted against the real routes. */
const posts: { url: string; body: unknown }[] = []

function installFetchStub() {
  const routes: Record<string, unknown> = {
    '/vision-execution/ideas': [
      { id: 'id1', title: 'Take on an apprentice', summary: 'A penciled possibility.', description: '', status: 'New', tags: [], created_by: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
    ],
    '/vision-execution/initiatives': [INITIATIVE],
    '/vision-execution/projects': [P1, P2, LP],
    '/vision-execution/tasks': TASKS,
    '/vision-execution/persons': [
      { id: 'per1', name: 'Jo Keeper', role: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
    ],
    '/vision-execution/assets': [],
    '/vision-execution/capacity-profiles': [
      { person_id: 'per1', weekly_capacity_hours: 20, created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
    ],
    '/vision-execution/core-profiles': [CORE_PROFILE],
    '/settings/permissions/home': {
      enabled: true,
      consent: { given: true, version: '1', at: null },
      intents: [
        {
          id: 'remember',
          groups: [
            { id: 'memory', state: 'ask_me', sync: 'synced', writable_states: ['on', 'off', 'ask_me'], has_rows: true, controls: [], diagnostics: null },
          ],
          granular: [],
        },
      ],
      learn: { kind: 'none' },
      outside_zenaf: { always_asks: [], never_coverable_classes: [], standing_consents: [] },
    },
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input)
      if (init?.method === 'POST') {
        posts.push({ url, body: init.body ? JSON.parse(init.body) : undefined })
        return jsonResponse({})
      }
      if (url.includes('/attributed-read/')) return jsonResponse(attributedPayload)
      for (const [path, body] of Object.entries(routes)) {
        if (url.endsWith(path)) return jsonResponse(body)
      }
      const strand = url.match(/\/conversation\/strand\/(\w+)/)
      if (strand) {
        return jsonResponse({
          strand_key: strand[1],
          strand_name: strand[1] === 'hands' ? 'Hands' : strand[1],
          boundaries: strand[1] === 'hands' ? [{ id: 'b1', topic: 'pricing', created_at: '2026-05-01T00:00:00' }] : [],
          sources: [],
        })
      }
      return jsonResponse([])
    }),
  )
}

let container: HTMLDivElement
let root: Root

async function render(props: Record<string, unknown> = {}) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => {
    root.render(React.createElement(LivingPalaceView, props))
  })
  // Let the entity fetch land.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

async function click(testid: string) {
  const el = container.querySelector(`[data-testid="${testid}"]`)
  expect(el, `missing ${testid}`).not.toBeNull()
  await act(async () => {
    el!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

function lastChat() {
  return chatProps[chatProps.length - 1]
}

beforeEach(() => {
  chatProps.length = 0
  posts.length = 0
  attributedPayload = EMPTY_READ
  installFetchStub()
})

afterEach(() => {
  act(() => root?.unmount())
  container?.remove()
  vi.unstubAllGlobals()
})

describe('Living Palace view', () => {
  it('renders the compound over live records, bonfire at its centre', async () => {
    await render()
    expect(container.querySelector('[data-testid="palace-building-i1"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-bonfire"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-loose-project-lp"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-loose-task-lt"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-idea-id1"]')).not.toBeNull()
    // Standing in the compound, the chat carries the sheet and no subject.
    expect(lastChat().conversationId).toBe('living-palace:compound')
    expect(lastChat().context).toEqual({ sheet_type: 'living_palace' })
  })

  it('un-nests the buildings’ projects onto the grounds on request', async () => {
    await render()
    expect(container.querySelector('[data-testid="palace-standing-project-p1"]')).toBeNull()
    await click('palace-unnest-toggle')
    expect(container.querySelector('[data-testid="palace-standing-project-p1"]')).not.toBeNull()
  })

  it('descends building → floor → room, the chat subject following', async () => {
    await render()
    await click('palace-building-i1')
    expect(container.querySelector('[data-testid="palace-floor-p1"]')).not.toBeNull()
    expect(lastChat().conversationId).toBe('living-palace:initiative:i1')
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'initiative',
      entity_id: 'i1',
    })
    await click('palace-floor-p1')
    expect(container.querySelector('[data-testid="palace-room-ta"]')).not.toBeNull()
    // The floor's scales stand: P1 records weekly hours and its
    // keeper a capacity profile.
    expect(container.querySelector('[data-testid="palace-floor-scales"]')).not.toBeNull()
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'project',
      entity_id: 'p1',
    })
    await click('palace-room-tc')
    expect(lastChat().conversationId).toBe('living-palace:task:tc')
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'task',
      entity_id: 'tc',
    })
  })

  it('a room carries its earned furniture and its unpopulated instruments', async () => {
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p1')
    await click('palace-room-tc')
    // Gamma waits on Beta: the window stands with its reading.
    expect(container.querySelector('[data-testid="palace-room-window"]')).not.toBeNull()
    // Affordance instruments stand unpopulated in every room.
    expect(container.querySelector('[data-testid="palace-room-scales"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-room-vessel"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-room-chest"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-room-table"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-room-hearth"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-room-threshold"]')).not.toBeNull()
    // Gamma has one recorded edge — no mandala is earned.
    expect(container.querySelector('[data-testid="palace-room-mandala"]')).toBeNull()
    // Beta is In Progress but Gamma is Todo — no plant is earned.
    expect(container.querySelector('[data-testid="palace-room-plant"]')).toBeNull()
  })

  it('the mandala stands only where recorded edges converge', async () => {
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p2')
    await click('palace-room-tf')
    expect(container.querySelector('[data-testid="palace-room-mandala"]')).not.toBeNull()
  })

  it('the boundaries panel composes only from served records, and says what does not exist', async () => {
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p1')
    await click('palace-boundaries-button')
    const panel = container.querySelector('[data-testid="palace-boundaries-panel"]')
    expect(panel).not.toBeNull()
    expect(panel!.textContent).toContain('No work on Sundays.')
    expect(panel!.textContent).toContain('pricing')
    expect(panel!.textContent).toContain('No boundary is recorded against this room itself')
  })

  it('an idea on the drawing table becomes the chat’s subject', async () => {
    await render()
    await click('palace-idea-id1')
    expect(lastChat().conversationId).toBe('living-palace:idea:id1')
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'idea',
      entity_id: 'id1',
    })
  })
})

/* ------------------------------------------------------------------ */
/* the attributed read — Thresholds-1 / Kintsugi-1 / Guests-1          */
/* ------------------------------------------------------------------ */

const READ_WITH_MATERIAL = {
  ...EMPTY_READ,
  steward_gate_open: true,
  boundaries: {
    ...EMPTY_READ.boundaries,
    proposed: [
      {
        thread_id: 'th1',
        thread_title: 'The boundary thread',
        reading_id: 'r1',
        author: 'skeptic',
        author_name: 'Severine',
        status: 'proposed',
        placement: 'current',
        currency_labels: [],
        tensions: ['Sundays keep colliding with deliveries'],
        open_questions: ['Where does the weekend actually sit?'],
      },
    ],
    established: [
      { source: 'commitment', text: 'No Sunday deliveries, ever.', status: 'open', created_at: '2026-11-01T00:00:00Z' },
    ],
  },
  kintsugi: {
    threads: [
      {
        thread_id: 'th1',
        thread_title: 'The boundary thread',
        readings: [
          {
            reading_id: 'r1',
            author: 'skeptic',
            status: 'proposed',
            placement: 'current',
            currency_labels: [],
            tensions: ['Sundays keep colliding with deliveries'],
            open_questions: ['Where does the weekend actually sit?'],
          },
        ],
        reconsiderations: [],
      },
    ],
    restoration_of_understanding: true,
  },
  guests: {
    attending: [
      { seat: 'ambassador', seat_name: 'Lucian', via: ['reading'] },
      { seat: 'champion', seat_name: 'Valen', via: ['conversation'] },
    ],
  },
}

async function descendToGamma() {
  await click('palace-building-i1')
  await click('palace-floor-p1')
  await click('palace-room-tc')
}

describe('Living Palace — the attributed read', () => {
  it('an empty read leaves the room exactly as it stood: plain vessel, no guests', async () => {
    await render()
    await descendToGamma()
    const vessel = container.querySelector('[data-testid="palace-room-vessel"]')
    expect(vessel!.innerHTML).not.toContain('#d4af37')
    expect(container.querySelector('[data-testid="palace-room-guest-ambassador"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-room-guest-champion"]')).toBeNull()
  })

  it('Kintsugi-1: accepted supersession gilds the seam; the vessel opens the held questions', async () => {
    attributedPayload = READ_WITH_MATERIAL
    await render()
    await descendToGamma()
    const vessel = container.querySelector('[data-testid="palace-room-vessel"]')
    expect(vessel!.innerHTML).toContain('#d4af37')
    await click('palace-room-vessel')
    const panel = container.querySelector('[data-testid="palace-vessel-panel"]')
    expect(panel).not.toBeNull()
    // The seam marks a corrected INTERPRETATION — and says so.
    expect(panel!.textContent).toContain('an understanding restored')
    expect(panel!.textContent).toContain('It does not claim the thing itself is mended')
    // The tension is held as an open question, never as damage.
    expect(panel!.textContent).toContain('Sundays keep colliding with deliveries')
    expect(panel!.textContent).toContain('A tension held is not damage done')
    expect(panel!.textContent).toContain('The vessel does not crack for it')
  })

  it('Guests-1: attending seats stand as guest objects; the cup opens its two doors', async () => {
    attributedPayload = READ_WITH_MATERIAL
    await render()
    await descendToGamma()
    expect(container.querySelector('[data-testid="palace-room-guest-ambassador"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-room-guest-champion"]')).not.toBeNull()
    // A seat that does not attend does not stand.
    expect(container.querySelector('[data-testid="palace-room-guest-skeptic"]')).toBeNull()
    await click('palace-room-guest-ambassador')
    const panel = container.querySelector('[data-testid="palace-guest-panel"]')
    expect(panel).not.toBeNull()
    expect(panel!.textContent).toContain("Lucian's cup")
    expect(panel!.textContent).toContain('Lucian has a reading on this room')
    expect(panel!.textContent).toContain('none of it is copied into the Palace')
    // Door (i) stands; Lucian has no world, so door (ii) is honestly absent.
    expect(container.querySelector('[data-testid="palace-guest-explore"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-guest-follow"]')).toBeNull()
    expect(panel!.textContent).toContain('Lucian has no world of his own yet')
  })

  it('Guests-1: the follow door hands the seat to the seat-landing navigation', async () => {
    attributedPayload = READ_WITH_MATERIAL
    const followed: string[] = []
    await render({ onFollowGuest: (seat: string) => followed.push(seat) })
    await descendToGamma()
    await click('palace-room-guest-champion')
    const panel = container.querySelector('[data-testid="palace-guest-panel"]')
    expect(panel!.textContent).toContain('Valen has spoken of this room in conversation')
    await click('palace-guest-follow')
    expect(followed).toEqual(['champion'])
  })

  it('Thresholds-1: the boundaries panel gains the subject’s states, proposed in pencil', async () => {
    attributedPayload = READ_WITH_MATERIAL
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p1')
    await click('palace-room-tc')
    await click('palace-boundaries-button')
    const panel = container.querySelector('[data-testid="palace-boundaries-panel"]')
    expect(panel).not.toBeNull()
    expect(panel!.textContent).toContain("At this room's own threshold")
    expect(panel!.textContent).toContain('Proposed — readings, in pencil')
    expect(panel!.textContent).toContain('Severine')
    expect(panel!.textContent).toContain('Sundays keep colliding with deliveries')
    expect(panel!.textContent).toContain('not a boundary established')
    expect(panel!.textContent).toContain('Established')
    expect(panel!.textContent).toContain('No Sunday deliveries, ever.')
    // The standing honesty remains: no per-subject boundary record exists.
    expect(panel!.textContent).toContain('No boundary is recorded against this room itself')
  })
})

/* ------------------------------------------------------------------ */
/* the verdict door — Slice 1                                          */
/* ------------------------------------------------------------------ */

const READ_WITH_PENDING = {
  ...EMPTY_READ,
  steward_gate_open: true,
  boundaries: {
    ...EMPTY_READ.boundaries,
    proposed: [
      {
        thread_id: 'th1',
        thread_title: 'The boundary thread',
        reading_id: 'ra',
        author: 'steward',
        author_name: 'The Steward',
        status: 'accepted',
        placement: 'current',
        currency_labels: [],
        tensions: ['The old yard reading stands.'],
        open_questions: [],
      },
    ],
  },
  kintsugi: {
    threads: [
      {
        thread_id: 'th1',
        thread_title: 'The boundary thread',
        readings: [
          {
            reading_id: 'ra',
            author: 'steward',
            status: 'accepted',
            placement: 'current',
            currency_labels: [],
            tensions: ['The old yard reading stands.'],
            open_questions: [],
          },
        ],
        reconsiderations: [],
      },
    ],
    restoration_of_understanding: false,
  },
  pending: [
    {
      item_id: 'reading:rp',
      item_kind: 'reading',
      thread_id: 'th1',
      surface: 'queue_card',
      status: 'proposed',
      title: 'The boundary thread',
      payload: {
        reading: { tensions: ['A tension awaiting your word'], open_questions: [] },
        evidence_refs: [{ kind: 'event', ref_id: 'evt-9' }],
        currency: { placement: 'current', labels: [] },
      },
    },
    {
      item_id: 'correspondence:c1',
      item_kind: 'correspondence',
      thread_id: 'th1',
      surface: 'queue_card',
      status: 'proposed',
      title: 'The boundary thread',
      payload: {
        thread_ids: ['th1', 'th2'],
        structural_tension: 'patience vs avoidance',
        proposed_relationship: '',
        limitations: '',
        evidence_refs: [],
      },
    },
  ],
}

describe('Living Palace — the verdict door', () => {
  it('pending items rest at the threshold with their evidence — and nowhere else', async () => {
    attributedPayload = READ_WITH_PENDING
    await render()
    await descendToGamma()
    // Not on the world, not in any other panel: only at the door.
    expect(container.textContent).not.toContain('A tension awaiting your word')
    await click('palace-boundaries-button')
    const section = container.querySelector('[data-testid="palace-pending-section"]')
    expect(section).not.toBeNull()
    expect(section!.textContent).toContain('A tension awaiting your word')
    expect(section!.textContent).toContain('Grounded in: event:evt-9')
    expect(section!.textContent).toContain('Currency: current')
    expect(section!.textContent).toContain('patience vs avoidance')
    expect(
      container.querySelector('[data-testid="palace-pending-item-threshold-reading:rp"]'),
    ).not.toBeNull()
    // No counts, no badges — resting material is not a backlog.
    expect(container.querySelector('[data-testid*="badge"]')).toBeNull()
    expect(container.querySelector('[data-testid*="count"]')).toBeNull()
    expect(section!.textContent).not.toMatch(/\d+\s+(undecided|pending|awaiting)/i)
  })

  it('each act posts to its own route of the one mechanism', async () => {
    attributedPayload = READ_WITH_PENDING
    await render()
    await descendToGamma()
    await click('palace-boundaries-button')
    // Endorse is a reading annotation: offered on the reading,
    // never on the correspondence.
    expect(container.querySelector('[data-testid="palace-review-endorse-reading:rp"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-review-endorse-correspondence:c1"]')).toBeNull()
    await click('palace-review-accept-reading:rp')
    await click('palace-review-reject-correspondence:c1')
    await click('palace-review-unresolve-reading:rp')
    await click('palace-review-endorse-reading:rp')
    const urls = posts.map((p) => p.url)
    expect(urls.some((u) => u.endsWith('/steward/review/reading/rp/accept'))).toBe(true)
    expect(urls.some((u) => u.endsWith('/steward/review/correspondence/c1/reject'))).toBe(true)
    expect(urls.some((u) => u.endsWith('/steward/review/reading/rp/unresolve'))).toBe(true)
    const endorse = posts.find((p) => p.url.endsWith('/steward/review/reading/rp/endorse'))
    expect(endorse?.body).toEqual({ stance: 'endorsed', note: '' })
  })

  it('explore carries the item into the strand thread the visitor chooses', async () => {
    attributedPayload = READ_WITH_PENDING
    await render()
    await descendToGamma()
    await click('palace-boundaries-button')
    await click('palace-review-explore-correspondence:c1')
    expect(
      container.querySelector('[data-testid="palace-explore-strands-correspondence:c1"]'),
    ).not.toBeNull()
    await click('palace-explore-strand-correspondence:c1-hands')
    const explore = posts.find((p) => p.url.includes('/explore'))
    expect(explore?.url).toContain('/steward/review/correspondence/c1/explore')
    expect(explore?.body).toEqual({ strand_key: 'hands' })
  })

  it('the vessel holds the readings’ share, and the ask sends his words verbatim', async () => {
    attributedPayload = READ_WITH_PENDING
    await render()
    await descendToGamma()
    await click('palace-room-vessel')
    const vesselPanel = container.querySelector('[data-testid="palace-vessel-panel"]')
    expect(vesselPanel).not.toBeNull()
    const door = container.querySelector('[data-testid="palace-vessel-pending"]')
    expect(door).not.toBeNull()
    expect(
      container.querySelector('[data-testid="palace-pending-item-vessel-reading:rp"]'),
    ).not.toBeNull()
    // The correspondence rests at the threshold, not at the vessel.
    expect(door!.textContent).not.toContain('patience vs avoidance')
    // The ask: his cause, in his own words, sent exactly as written.
    await click('palace-reconsider-open-ra')
    const ta = container.querySelector(
      '[data-testid="palace-reconsider-text-ra"]',
    ) as HTMLTextAreaElement
    expect(ta).not.toBeNull()
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      'value',
    )!.set!
    await act(async () => {
      setter.call(ta, 'The facts moved on Tuesday.')
      ta.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click('palace-reconsider-send-ra')
    const ask = posts.find((p) => p.url.includes('/reconsider'))
    expect(ask?.url).toContain('/steward/review/reading/ra/reconsider')
    expect(ask?.body).toEqual({ reason: 'The facts moved on Tuesday.' })
  })

  it('an empty read opens no door: no pending section, the vessel keeps its toast', async () => {
    await render()
    await descendToGamma()
    await click('palace-boundaries-button')
    expect(container.querySelector('[data-testid="palace-pending-section"]')).toBeNull()
    await click('palace-room-vessel')
    expect(container.querySelector('[data-testid="palace-vessel-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-toast"]')).not.toBeNull()
  })
})
