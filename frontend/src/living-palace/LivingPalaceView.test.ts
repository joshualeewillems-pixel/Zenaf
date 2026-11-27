// @vitest-environment jsdom
/**
 * The Living Palace — jsdom render verification against a stubbed
 * API (the same routes the product uses: the Vision Execution
 * entity lists, capacity profiles, core profiles, and the shared
 * attributed read).
 *
 * The fixture body of work: one initiative with two floors, one
 * loose project, one loose task, one undeveloped idea. The suite
 * asserts the descent compound → building → task level → room
 * (the dome serves both levels since the floor-plan frame
 * retired, founder 2026-11-26); that the
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
 * down discards it silently), that the staging SHOWS as a chip in
 * the chat — never as a banner in the world, and the mechanism
 * copy that once explained the loading is gone — and that a
 * landed chat turn re-reads the subject. CouncilChat is stubbed —
 * the chat seam is covered by its own suite.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

const chatProps: {
  conversationId?: string | null
  context?: Record<string, unknown>
  onTurnSent?: () => void
  stagedLabel?: string | null
  onStagedClear?: () => void
}[] = []
vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: {
      conversationId?: string | null
      context?: Record<string, unknown>
      onTurnSent?: () => void
      stagedLabel?: string | null
      onStagedClear?: () => void
    }) => {
      chatProps.push(props)
      // The stub renders the chat seam's staging chip to
      // CouncilChat's contract (the real component is pinned by
      // its own suite): the staged thing's name inside the chat,
      // with its dismissal, while it stands staged.
      return ReactMod.createElement(
        'div',
        {
          'data-testid': 'maeve-chat',
          'data-conversation-id': props.conversationId ?? '',
        },
        props.stagedLabel
          ? ReactMod.createElement(
              'span',
              { 'data-testid': 'staged-chip' },
              props.stagedLabel,
              props.onStagedClear
                ? ReactMod.createElement(
                    'button',
                    {
                      type: 'button',
                      'data-testid': 'staged-chip-clear',
                      onClick: props.onStagedClear,
                    },
                    'Set it down',
                  )
                : null,
            )
          : null,
      )
    },
  }
})

import LivingPalaceView from './LivingPalaceView'
import { FOOTPRINT_SQUASH, PALACE_GEOMETRY, masterAspect } from './palaceSceneLogic'

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
  taskRow({ id: 'lpt', project_id: 'lp', title: 'Loose project task' }),
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

/** The subject-interactions payload the stub serves — the ivy /
 *  glass read. Empty by default; the task-glass test replaces it. */
let interactionsPayload: unknown = { subjects: [] }

/** Entity-list overrides — null serves the fixture body of work;
 *  the compound-completion tests replace the projects or tasks
 *  list (a released project; a world with no loose tasks). */
let projectsPayload: Record<string, unknown>[] | null = null
let tasksPayload: Record<string, unknown>[] | null = null

/** Every non-GET the view makes, recorded by the fetch stub: the
 *  Palace pass surface must make NONE, ever — staging included.
 *  One exception, tracked separately below: the overhead plan's
 *  layout record (derived geometry, written only when a layout
 *  is computed or changes — never a visitor-work write, and
 *  never on a tap). */
const writes: { url: string; method: string }[] = []
/** Overhead layout record PUTs, by project key, and the records
 *  the stub then serves back — the standing-record path is
 *  exercised against what the client itself wrote. */
const layoutWrites: { key: string }[] = []
const layoutRecords = new Map<string, unknown>()
/** Attributed-read GETs, counted: a landed chat turn re-reads. */
let attributedGets = 0

function installFetchStub() {
  const routes: Record<string, unknown> = {
    '/vision-execution/ideas': [
      { id: 'id1', title: 'Take on an apprentice', summary: 'A penciled possibility.', description: '', status: 'New', tags: [], created_by: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
    ],
    '/vision-execution/initiatives': [INITIATIVE],
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
      if (url.includes('/palace-layout/')) {
        const key = decodeURIComponent(url.split('/palace-layout/')[1])
        if (method === 'PUT') {
          layoutWrites.push({ key })
          layoutRecords.set(key, (JSON.parse(init?.body ?? '{}') as { record?: unknown }).record)
          return jsonResponse({})
        }
        return jsonResponse({ project_id: key, layout: layoutRecords.get(key) ?? null })
      }
      if (method !== 'GET') {
        writes.push({ url, method })
        return jsonResponse({})
      }
      if (url.includes('/attributed-read/')) {
        attributedGets += 1
        return jsonResponse(attributedPayload)
      }
      if (url.includes('/subject-interactions')) {
        return jsonResponse(interactionsPayload)
      }
      // Read at fetch time, not stub-install time: a test sets
      // its override after beforeEach has installed the stub.
      if (url.endsWith('/vision-execution/projects')) {
        return jsonResponse(projectsPayload ?? [P1, P2, LP])
      }
      if (url.endsWith('/vision-execution/tasks')) {
        return jsonResponse(tasksPayload ?? TASKS)
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
  await click('palace-task-tc')
}

async function clickCrumb(label: string) {
  const nav = container.querySelector('nav[aria-label="Palace trail"]')
  const el = [...(nav?.querySelectorAll('button') ?? [])].find((b) => b.textContent === label)
  expect(el, `missing crumb ${label}`).not.toBeUndefined()
  await act(async () => {
    el!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

beforeEach(() => {
  chatProps.length = 0
  writes.length = 0
  layoutWrites.length = 0
  layoutRecords.clear()
  attributedGets = 0
  attributedPayload = EMPTY_READ
  interactionsPayload = { subjects: [] }
  projectsPayload = null
  tasksPayload = null
  installFetchStub()
})

afterEach(() => {
  act(() => root?.unmount())
  container?.remove()
  vi.unstubAllGlobals()
})

describe('Living Palace view', () => {
  it('renders the compound over live records, the founder’s fire at its centre', async () => {
    await render()
    expect(container.querySelector('[data-testid="palace-building-i1"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-fire"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-loose-project-lp"]')).not.toBeNull()
    // The loose task no longer stands as a stone below the plan:
    // it is gathered into the compound's smallest building, and
    // the drawing table stands in the plan with the idea on it.
    // This fixture holds no released project — none stands
    // outside the gate.
    expect(container.querySelector('[data-testid="palace-loose-tasks-building"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-loose-task-lt"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-drawing-table"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-idea-id1"]')).not.toBeNull()
    expect(container.querySelector('[data-testid^="palace-released-project-"]')).toBeNull()
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

  it('descends building → task level → room, the chat subject following', async () => {
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
    // The dome recomposes at task level: P1's tasks as circles,
    // the project staged in the chat exactly as the floor tap
    // staged it. The retired floor frame is gone — no hall
    // hearth, no floor scales, no room tiles from the old plan.
    expect(container.querySelector('[data-testid="palace-task-ta"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-task-tc"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-floor-hearth"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-floor-scales"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-floor-threshold"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-room-ta"]')).toBeNull()
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'project',
      entity_id: 'p1',
    })
    await click('palace-task-tc')
    expect(lastChat().conversationId).toBe('living-palace:task:tc')
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'task',
      entity_id: 'tc',
    })
  })

  it('a loose project opens the dome directly at task level', async () => {
    await render()
    await click('palace-loose-project-lp')
    // No building layer stands between the compound and this
    // project's tasks — its one task stands as a circle at once.
    expect(container.querySelector('[data-testid="palace-task-lpt"]')).not.toBeNull()
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'project',
      entity_id: 'lp',
    })
    await click('palace-task-lpt')
    expect(lastChat().conversationId).toBe('living-palace:task:lpt')
    expect(container.querySelector('[data-testid="palace-room-vessel"]')).not.toBeNull()
  })

  it('back navigation unwinds one level at a time', async () => {
    await render()
    await descendToGamma()
    // room → the task-level dome of its project
    await clickCrumb('Winter client season')
    expect(container.querySelector('[data-testid="palace-task-tc"]')).not.toBeNull()
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'project',
      entity_id: 'p1',
    })
    // task level → the project-level dome of its building
    await clickCrumb('Rebuild the workshop business')
    expect(container.querySelector('[data-testid="palace-floor-p1"]')).not.toBeNull()
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'initiative',
      entity_id: 'i1',
    })
    // building → the compound
    await clickCrumb('Compound')
    expect(container.querySelector('[data-testid="palace-building-i1"]')).not.toBeNull()
    expect(lastChat().conversationId).toBe('living-palace:compound')
  })

  it('a task interaction in the read leaves the task level standing (glass fails soft in jsdom)', async () => {
    interactionsPayload = {
      subjects: [{ entity_type: 'task', entity_id: 'tc', total: 3, per_seat: { champion: 3 } }],
    }
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p1')
    // The read carries a task subject; the circle stands and the
    // descent continues — the tint wiring itself is pinned in
    // the render scan, where the glass hook can be observed.
    expect(container.querySelector('[data-testid="palace-task-tc"]')).not.toBeNull()
    await click('palace-task-tc')
    expect(lastChat().conversationId).toBe('living-palace:task:tc')
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

  it('a room stands in the chamber of its floor', async () => {
    await render()
    // The workshop building's floors, by size: P1 (three rooms)
    // is the largest — its rooms stand in the rose chamber, the
    // plate the building scene shows for that floor.
    await descendToGamma()
    expect(container.querySelector('img[src*="palace-room-rose"]')).not.toBeNull()
    expect(container.querySelector('img[src*="palace-room-spiral"]')).toBeNull()
  })

  it('the second floor’s rooms stand in the spiral chamber', async () => {
    await render()
    // P2 (two rooms) is next by size: the spiral chamber — the
    // same plate assignment the building scene renders, shared
    // through plateForFloor, never re-derived.
    await click('palace-building-i1')
    await click('palace-floor-p2')
    await click('palace-task-tf')
    expect(container.querySelector('img[src*="palace-room-spiral"]')).not.toBeNull()
    expect(container.querySelector('img[src*="palace-room-rose"]')).toBeNull()
  })

  it('the mandala stands only where recorded edges converge', async () => {
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p2')
    await click('palace-task-tf')
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
/* the compound completed — everything stands in the plan              */
/* (founder, 2026-11-26 22:22–22:26 PT)                                */
/* ------------------------------------------------------------------ */

function pointInPolygon(x: number, y: number, poly: [number, number][]): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]
    const [xj, yj] = poly[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

describe('Living Palace — the compound completed', () => {
  it('the strip is gone from the source: no stones, no drawn bench, no strip', () => {
    const canvas = readFileSync('src/living-palace/palaceCanvas.tsx', 'utf8')
    expect(canvas).not.toContain('palace-loose-task-${')
    expect(canvas).not.toContain('function DrawingTable')
    expect(canvas).not.toContain('the grounds strip')
  })

  it('the compound renders no SVG at all — the plan composition is positioned DOM end to end', async () => {
    await render()
    expect(container.querySelector('.living-palace-scene svg')).toBeNull()
  })

  it('the loose-tasks building stands inside a court, seated by the placement law', async () => {
    await render()
    const el = container.querySelector<HTMLElement>('[data-testid="palace-loose-tasks-building"]')
    expect(el).not.toBeNull()
    // A placed building carries a top (the fallback row carries a
    // bottom instead) — read the box back into plan units and
    // check the foundation's centre against the courts' own
    // polygons: the law seats it in a court, or nowhere.
    expect(el!.style.top).not.toBe('')
    const w = (parseFloat(el!.style.width) / 100) * PALACE_GEOMETRY.width
    const h = w * masterAspect('small', 1)
    const bx = (parseFloat(el!.style.left) / 100) * PALACE_GEOMETRY.width + w / 2
    const by = (parseFloat(el!.style.top) / 100) * PALACE_GEOMETRY.height + h
    const fcy = by - 0.5 * PALACE_GEOMETRY.plinths.small * w * FOOTPRINT_SQUASH
    const inCourt = Object.values(PALACE_GEOMETRY.polygons).some((poly) =>
      pointInPolygon(bx, fcy, poly),
    )
    expect(inCourt).toBe(true)
  })

  it('no loose tasks, no loose-tasks building', async () => {
    tasksPayload = TASKS.filter((t) => t.id !== 'lt')
    await render()
    expect(container.querySelector('[data-testid="palace-loose-tasks-building"]')).toBeNull()
  })

  it('the loose-tasks building opens the dome at task level over the loose tasks', async () => {
    await render()
    await click('palace-loose-tasks-building')
    // The dome recomposes at task level: the loose task as a
    // circle under the grouping's own name. The grouping names no
    // record, so the chat keeps the compound's carriage until a
    // task is entered.
    expect(container.querySelector('[data-testid="palace-task-lt"]')).not.toBeNull()
    expect(container.textContent).toContain('Loose tasks')
    expect(lastChat().conversationId).toBe('living-palace:compound')
    expect(lastChat().context).toEqual({ sheet_type: 'living_palace' })
    // A circle opens its chamber — the rose chamber, where a
    // loose task's room has always stood.
    await click('palace-task-lt')
    expect(lastChat().conversationId).toBe('living-palace:task:lt')
    expect(container.querySelector('[data-testid="palace-room-vessel"]')).not.toBeNull()
    expect(container.querySelector('img[src*="palace-room-rose"]')).not.toBeNull()
    // Back unwinds level by level: room → the loose level → the
    // compound.
    await clickCrumb('Loose tasks')
    expect(container.querySelector('[data-testid="palace-task-lt"]')).not.toBeNull()
    await clickCrumb('Compound')
    expect(container.querySelector('[data-testid="palace-loose-tasks-building"]')).not.toBeNull()
  })

  it('the drawing table stands at the founder’s circled seat, the idea resting on it', async () => {
    await render()
    const table = container.querySelector<HTMLElement>('[data-testid="palace-drawing-table"]')
    expect(table).not.toBeNull()
    // The founder's own table art — not the drawn bench.
    expect(table!.querySelector('img')?.getAttribute('src')).toContain('palace-drawing-table')
    // The seat, from the brief's measured numbers: the object
    // (250 wide on its measured bounds) centred on x 620 with
    // its base at y 615 in the 1284×723 frame; the canvas box is
    // derived from the object, so the box's percentages are:
    const side = 250 / (0.9589 - 0.0339)
    expect(parseFloat(table!.style.left)).toBeCloseTo(((620 - 0.4964 * side) / 1284) * 100, 1)
    expect(parseFloat(table!.style.top)).toBeCloseTo(((615 - 0.8446 * side) / 723) * 100, 1)
    expect(parseFloat(table!.style.width)).toBeCloseTo((side / 1284) * 100, 1)
    // The idea's paper rests ON the table: its centre over the
    // table object's span, its top between the object's top edge
    // and its base.
    const chip = container.querySelector<HTMLElement>('[data-testid="palace-idea-id1"]')
    expect(chip).not.toBeNull()
    const chipCx =
      ((parseFloat(chip!.style.left) + parseFloat(chip!.style.width) / 2) / 100) *
      PALACE_GEOMETRY.width
    expect(chipCx).toBeGreaterThan(620 - 125)
    expect(chipCx).toBeLessThan(620 + 125)
    const chipTop = (parseFloat(chip!.style.top) / 100) * PALACE_GEOMETRY.height
    expect(chipTop).toBeGreaterThan(448)
    expect(chipTop).toBeLessThan(615)
  })

  it('a released project stands outside the gate, its base at the art’s bottom edge', async () => {
    projectsPayload = [
      P1,
      P2,
      LP,
      { ...P2, id: 'rp', initiative_id: null, title: 'Old sideline', status: 'Dropped' },
    ]
    await render()
    const el = container.querySelector<HTMLElement>('[data-testid="palace-released-project-rp"]')
    expect(el).not.toBeNull()
    // The base is the plan's bottom edge — beyond every court's
    // southern bound (the courts end near y 555 of 723): outside
    // the wall, on the foreground margin, not in a court.
    expect(el!.style.bottom).toBe('0%')
    const courtSouth = Math.max(
      ...Object.values(PALACE_GEOMETRY.polygons).flatMap((poly) => poly.map((pt) => pt[1])),
    )
    expect(courtSouth).toBeLessThan(PALACE_GEOMETRY.height)
    // No taller than the row's cap: 120 plan units.
    const w = (parseFloat(el!.style.width) / 100) * PALACE_GEOMETRY.width
    expect(w * masterAspect('small', 1)).toBeLessThanOrEqual(120 + 1e-6)
    // And it opens exactly as a project building does — the dome
    // at task level, the project staged in the chat.
    await click('palace-released-project-rp')
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'project',
      entity_id: 'rp',
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
    expect(vessel!.innerHTML).toContain('palace-vessel-plain')
    expect(vessel!.innerHTML).not.toContain('palace-vessel-gold')
    expect(container.querySelector('[data-testid="palace-room-guest-ambassador"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-room-guest-champion"]')).toBeNull()
  })

  it('Kintsugi-1: accepted supersession gilds the seam — the gold vessel stands, not paneled', async () => {
    attributedPayload = READ_WITH_MATERIAL
    await render()
    await descendToGamma()
    const vessel = container.querySelector('[data-testid="palace-room-vessel"]')
    expect(vessel!.innerHTML).toContain('palace-vessel-gold')
    expect(vessel!.innerHTML).not.toContain('palace-vessel-plain')
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
  it('the mechanism copy is gone from the source: no staged banner explaining the loading', () => {
    const view = readFileSync('src/living-palace/LivingPalaceView.tsx', 'utf8')
    expect(view).not.toContain('rides into her conversation')
    expect(view).not.toContain('a tap settles nothing')
    expect(view).not.toContain('Staged with Maeve')
    expect(view).not.toContain('palace-staged-line')
    expect(view).not.toContain('palace-staged-clear')
  })


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

  it('the retired floor frame is gone from the source: no floor scene, no floor testids', () => {
    const canvas = readFileSync('src/living-palace/palaceCanvas.tsx', 'utf8')
    expect(canvas).not.toContain('FloorScene')
    expect(canvas).not.toContain('palace-floor-hearth')
    expect(canvas).not.toContain('palace-floor-scales')
    expect(canvas).not.toContain('palace-floor-threshold')
    expect(canvas).not.toContain('palace-floor-guest')
    const view = readFileSync('src/living-palace/LivingPalaceView.tsx', 'utf8')
    expect(view).not.toContain('FloorScene')
    expect(view).not.toContain('buildFloor')
  })

  it('a room scales tap stages the scales in the chat — and writes nothing', async () => {
    await render()
    await descendToGamma()
    await click('palace-room-scales')
    // The staging manifests IN THE CHAT: the chip stands inside
    // the chat pane carrying the instrument's name. No staged line
    // stands in the world pane, and no mechanism copy with it.
    const chip = container.querySelector('[data-testid="maeve-chat"] [data-testid="staged-chip"]')
    expect(chip).not.toBeNull()
    expect(chip!.textContent).toContain('the scales')
    expect(lastChat().stagedLabel).toBe('the scales')
    expect(container.querySelector('[data-testid="palace-staged-line"]')).toBeNull()
    expect(container.textContent).not.toContain('rides into her conversation')
    expect(container.textContent).not.toContain('a tap settles nothing')
    expect(lastChat().context).toEqual({
      sheet_type: 'living_palace',
      entity_type: 'task',
      entity_id: 'tc',
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
    // Another tap replaces the staged object — chip and context alike.
    await click('palace-room-chest')
    expect(lastChat().context).toMatchObject({ palace_focus: 'chest' })
    expect(container.querySelector('[data-testid="staged-chip"]')!.textContent).toContain('the chest')
    // Setting it down FROM THE CHAT clears the focus: the chip is
    // gone and the context is back to the bare subject.
    await click('staged-chip-clear')
    expect(container.querySelector('[data-testid="staged-chip"]')).toBeNull()
    expect(lastChat().stagedLabel).toBeNull()
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
    expect(container.querySelector('[data-testid="staged-chip"]')).toBeNull()
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
    expect(container.querySelector('[data-testid="staged-chip"]')!.textContent).toContain("Lucian's cup")
    expect(writes).toEqual([])
  })

  it('the overhead plan persists its layout once, then stands on the stored record', async () => {
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p1')
    // The plan stands: the project's task rooms are on the floor.
    expect(container.querySelector('[data-testid="palace-task-tc"]')).not.toBeNull()
    // Entering computed the layout and wrote its record — once.
    expect(layoutWrites.filter((w) => w.key === 'p1')).toHaveLength(1)
    expect(writes).toEqual([])
    // Back to the compound and in again: the stored record
    // stands (the same collection, integrity clean) — the plan
    // is NOT recomputed and NOT rewritten.
    await clickCrumb('Compound')
    await click('palace-building-i1')
    await click('palace-floor-p1')
    expect(container.querySelector('[data-testid="palace-task-tc"]')).not.toBeNull()
    expect(layoutWrites.filter((w) => w.key === 'p1')).toHaveLength(1)
    expect(writes).toEqual([])
  })

  it('the plan’s artifact rooms stage in the chat; the table puts the project on the drawing table', async () => {
    await render()
    await click('palace-building-i1')
    await click('palace-floor-p1')
    // The four standing artifact rooms stand in the plan.
    for (const kind of ['vessel', 'scales', 'table', 'chest']) {
      expect(container.querySelector(`[data-testid="palace-artifact-${kind}"]`)).not.toBeNull()
    }
    // A tap stages the instrument in Maeve's chat — tentatively,
    // writing nothing.
    await click('palace-artifact-scales')
    expect(lastChat().context).toMatchObject({
      entity_type: 'project',
      entity_id: 'p1',
      palace_focus: 'scales',
    })
    expect(writes).toEqual([])
    // The drawing-table room additionally puts the project on
    // the drawing table — the compound's announcement, carried
    // to the plan.
    await click('palace-artifact-table')
    expect(lastChat().context).toMatchObject({ palace_focus: 'table' })
    expect(container.textContent).toContain('On the drawing table:')
    expect(container.textContent).toContain('Winter client season')
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
