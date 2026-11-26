// @vitest-environment jsdom
/**
 * The Living Palace — jsdom render verification against a stubbed
 * API (the same routes the product uses: the Vision Execution
 * entity lists, capacity profiles, core profiles, and the shared
 * attributed read).
 *
 * The fixture body of work: one initiative with two floors, one
 * loose project, one loose task, one undeveloped idea. The suite
 * asserts the descent compound → building → floor → room; that the
 * chat's subject follows each selection through the living_palace
 * carriage; that a room's furniture is earned (the dependency
 * window's reading, the mandala only at convergence) while the
 * affordance instruments stand unpopulated (empty scales, plain
 * vessel); and — the Palace pass (chat-is-the-work, founder rulings
 * 2026-11-25 13:44/13:56 PT) — that the panel/button forms are
 * GONE (no boundaries panel, no pending section, no weighing
 * panel, no review acts anywhere), that a furniture tap STAGES its
 * object in the chat context tentatively (palace_focus rides the
 * context; staging performs zero writes; navigation or setting it
 * down discards it silently), and that a landed chat turn re-reads
 * the subject. CouncilChat is stubbed — the chat seam is covered
 * by its own suite.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

const chatProps: {
  conversationId?: string | null
  context?: Record<string, unknown>
  onTurnSent?: () => void
}[] = []
vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: {
      conversationId?: string | null
      context?: Record<string, unknown>
      onTurnSent?: () => void
    }) => {
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

/** Every non-GET the view makes, recorded by the fetch stub: the
 *  Palace pass surface must make NONE, ever — staging included. */
const writes: { url: string; method: string }[] = []
/** Attributed-read GETs, counted: a landed chat turn re-reads. */
let attributedGets = 0

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
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method !== 'GET') {
        writes.push({ url, method })
        return jsonResponse({})
      }
      if (url.includes('/attributed-read/')) {
        attributedGets += 1
        return jsonResponse(attributedPayload)
      }
      for (const [path, body] of Object.entries(routes)) {
        if (url.endsWith(path)) return jsonResponse(body)
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

async function descendToGamma() {
  await click('palace-building-i1')
  await click('palace-floor-p1')
  await click('palace-room-tc')
}

beforeEach(() => {
  chatProps.length = 0
  writes.length = 0
  attributedGets = 0
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
    await descendToGamma()
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
/* the attributed read — the seam and the guest objects                */
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

describe('Living Palace — the attributed read', () => {
  it('an empty read leaves the room exactly as it stood: plain vessel, no guests', async () => {
    await render()
    await descendToGamma()
    const vessel = container.querySelector('[data-testid="palace-room-vessel"]')
    expect(vessel!.innerHTML).not.toContain('#d4af37')
    expect(container.querySelector('[data-testid="palace-room-guest-ambassador"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-room-guest-champion"]')).toBeNull()
  })

  it('Kintsugi-1: accepted supersession gilds the seam — drawn, not paneled', async () => {
    attributedPayload = READ_WITH_MATERIAL
    await render()
    await descendToGamma()
    const vessel = container.querySelector('[data-testid="palace-room-vessel"]')
    expect(vessel!.innerHTML).toContain('#d4af37')
    // The vessel's substance lives in Maeve's conversation now:
    // no panel opens, and the held questions appear nowhere here.
    await click('palace-room-vessel')
    expect(container.querySelector('[data-testid="palace-vessel-panel"]')).toBeNull()
    expect(container.textContent).not.toContain('Sundays keep colliding with deliveries')
  })

  it('Guests-1: attending seats stand as guest objects; the cup opens its slim doors', async () => {
    attributedPayload = READ_WITH_MATERIAL
    await render()
    await descendToGamma()
    expect(container.querySelector('[data-testid="palace-room-guest-ambassador"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-room-guest-champion"]')).not.toBeNull()
    // A seat that does not attend does not stand.
    expect(container.querySelector('[data-testid="palace-room-guest-skeptic"]')).toBeNull()
    await click('palace-room-guest-ambassador')
    const strip = container.querySelector('[data-testid="palace-guest-strip"]')
    expect(strip).not.toBeNull()
    expect(strip!.textContent).toContain("Lucian's cup")
    // Slim: the two doors and the honest note — no prose panel.
    expect(container.querySelector('[data-testid="palace-guest-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-guest-explore"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-guest-follow"]')).toBeNull()
    expect(strip!.textContent).toContain('Lucian has no world of his own yet')
    expect(strip!.textContent).not.toContain('none of it is copied')
  })

  it('Guests-1: the follow door hands the seat to the seat-landing navigation', async () => {
    attributedPayload = READ_WITH_MATERIAL
    const followed: string[] = []
    await render({ onFollowGuest: (seat: string) => followed.push(seat) })
    await descendToGamma()
    await click('palace-room-guest-champion')
    await click('palace-guest-follow')
    expect(followed).toEqual(['champion'])
  })
})

/* ------------------------------------------------------------------ */
/* the Palace pass — the panels are gone; taps stage                   */
/* ------------------------------------------------------------------ */

const READ_WITH_PENDING = {
  ...READ_WITH_MATERIAL,
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
  ],
}

describe('Living Palace — chat-is-the-work', () => {
  it('no panel forms remain: no boundaries, pending, vessel, weighing, or review acts', async () => {
    attributedPayload = READ_WITH_PENDING
    await render()
    await descendToGamma()
    // The header carries no Boundaries button anymore.
    expect(container.querySelector('[data-testid="palace-boundaries-button"]')).toBeNull()
    // Nothing on this surface renders the pending material or any
    // act upon it — it rests for Maeve's conversation, not here.
    expect(container.textContent).not.toContain('A tension awaiting your word')
    expect(container.querySelector('[data-testid="palace-pending-section"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-boundaries-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-vessel-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-weighing-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-held-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-idea-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid*="palace-review-"]')).toBeNull()
    expect(container.querySelector('[data-testid*="palace-reconsider-"]')).toBeNull()
    expect(container.querySelector('[data-testid*="palace-weighing-"]')).toBeNull()
    expect(container.querySelector('[data-testid*="badge"]')).toBeNull()
    expect(container.querySelector('[data-testid*="count"]')).toBeNull()
  })

  it('a floor scales tap stages the scales in the chat — and writes nothing', async () => {
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p1')
    await click('palace-floor-scales')
    const line = container.querySelector('[data-testid="palace-staged-line"]')
    expect(line).not.toBeNull()
    expect(line!.textContent).toContain('the scales')
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'project',
      entity_id: 'p1',
      palace_focus: 'scales',
    })
    // Tentative: not one write left this surface.
    expect(writes).toEqual([])
  })

  it('staging replaces, sets down, and navigation discards it silently', async () => {
    await render()
    await descendToGamma()
    await click('palace-room-vessel')
    expect(lastChat().context).toMatchObject({ palace_focus: 'vessel' })
    // Another tap replaces the staged object.
    await click('palace-room-chest')
    expect(lastChat().context).toMatchObject({ palace_focus: 'chest' })
    expect(container.querySelector('[data-testid="palace-staged-line"]')!.textContent).toContain('the chest')
    // Setting it down clears the context back to the bare subject.
    await click('palace-staged-clear')
    expect(container.querySelector('[data-testid="palace-staged-line"]')).toBeNull()
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'task',
      entity_id: 'tc',
    })
    // Stage again, then navigate (through the window, to the room
    // Gamma waits on): the staging is discarded.
    await click('palace-room-scales')
    expect(lastChat().context).toMatchObject({ palace_focus: 'scales' })
    await click('palace-room-window')
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'task',
      entity_id: 'tb',
    })
    expect(container.querySelector('[data-testid="palace-staged-line"]')).toBeNull()
    expect(writes).toEqual([])
  })

  it('the hearth stages when the fire is brought; the threshold stages too', async () => {
    await render()
    await descendToGamma()
    await click('palace-room-hearth')
    expect(lastChat().context).toMatchObject({ palace_focus: 'hearth' })
    await click('palace-room-threshold')
    expect(lastChat().context).toMatchObject({ palace_focus: 'threshold' })
    expect(writes).toEqual([])
  })

  it('exploring a guest object stages it as guest:<seat> and closes the strip', async () => {
    attributedPayload = READ_WITH_MATERIAL
    await render()
    await descendToGamma()
    await click('palace-room-guest-ambassador')
    await click('palace-guest-explore')
    expect(container.querySelector('[data-testid="palace-guest-strip"]')).toBeNull()
    expect(lastChat().context).toMatchObject({ palace_focus: 'guest:ambassador' })
    expect(container.querySelector('[data-testid="palace-staged-line"]')!.textContent).toContain("Lucian's cup")
    expect(writes).toEqual([])
  })

  it('a landed chat turn re-reads the subject (the Scroll #431 precedent)', async () => {
    await render()
    await descendToGamma()
    const before = attributedGets
    expect(before).toBeGreaterThan(0)
    const onTurnSent = lastChat().onTurnSent
    expect(onTurnSent).toBeTypeOf('function')
    await act(async () => {
      onTurnSent!()
    })
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    expect(attributedGets).toBeGreaterThan(before)
  })
})
