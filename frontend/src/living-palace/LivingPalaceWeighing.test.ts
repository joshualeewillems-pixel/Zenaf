// @vitest-environment jsdom
/**
 * Scales-1 — the weighing, at the view level.
 *
 * The fixture body: Jo Keeper (recorded capacity 20h) keeps floor
 * P1 (Active, asks 6h a week, Sam Support recorded as supporting);
 * Sam (capacity 10h) also keeps P3 (Ready, 8h) — so as recorded,
 * Sam is committed 14h against 10h and stands over. Room T1
 * carries a recorded estimate (4h); room T2 carries none.
 *
 * The suite pins the founder's shape end to end: exploration
 * performs ZERO writes across the whole flow (every fetch the view
 * makes is recorded; only GETs may occur until the settle act);
 * the derived consequences move as the figures move; alternative
 * arrangements are kept and restored session-locally; and the
 * settle act — the visitor's explicit act, and only that act —
 * writes exactly the settled figures through the existing routes
 * (PATCH /projects, PATCH /tasks, PUT /capacity-profiles) plus the
 * weighing's provenance as a POST /decisions record. A room with
 * no recorded estimate exposes no weighing surface at all.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: { conversationId?: string | null }) =>
      ReactMod.createElement('div', {
        'data-testid': 'maeve-chat',
        'data-conversation-id': props.conversationId ?? '',
      }),
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
  owner_id: 'per1', supporting_owner_ids: ['per2'], priority: '', start_date: null, end_date: null,
  estimated_weekly_hours: 6, next_step_ai: '', notes: '',
  created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
}
const P3 = {
  id: 'p3', initiative_id: 'i1', title: 'Spring commissions', brief: '', status: 'Ready',
  owner_id: 'per2', supporting_owner_ids: [], priority: '', start_date: null, end_date: null,
  estimated_weekly_hours: 8, next_step_ai: '', notes: '',
  created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
}

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
  taskRow({ id: 't1', title: 'Alpha', estimated_hours: 4 }),
  taskRow({ id: 't2', title: 'Beta', estimated_hours: null }),
]

const EMPTY_READ = {
  resolved: true,
  subject: { entity_type: 'project', entity_id: 'p1', title: 'Winter client season' },
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

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response
}

/** EVERY fetch the view makes, in order — the exploration pin is
 *  that only GETs appear until the settle act. */
const calls: { method: string; url: string; body: unknown }[] = []
let decisionsFail = false

function installFetchStub() {
  const routes: Record<string, unknown> = {
    '/vision-execution/ideas': [],
    '/vision-execution/initiatives': [INITIATIVE],
    '/vision-execution/projects': [P1, P3],
    '/vision-execution/tasks': TASKS,
    '/vision-execution/persons': [
      { id: 'per1', name: 'Jo Keeper', role: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
      { id: 'per2', name: 'Sam Support', role: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
    ],
    '/vision-execution/assets': [],
    '/vision-execution/capacity-profiles': [
      { person_id: 'per1', weekly_capacity_hours: 20, created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
      { person_id: 'per2', weekly_capacity_hours: 10, created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
    ],
    '/vision-execution/core-profiles': [],
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown, init?: { method?: string; body?: string }) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(init.body) : undefined
      calls.push({ method, url, body })
      if (method !== 'GET') {
        if (url.endsWith('/vision-execution/decisions') && decisionsFail) {
          return jsonResponse({ detail: 'Permission required: profile learning from usage.' }, false, 403)
        }
        return jsonResponse({})
      }
      if (url.includes('/attributed-read/')) return jsonResponse(EMPTY_READ)
      for (const [path, payload] of Object.entries(routes)) {
        if (url.endsWith(path)) return jsonResponse(payload)
      }
      return jsonResponse([])
    }),
  )
}

function writes(): { method: string; url: string; body: unknown }[] {
  return calls.filter((c) => c.method !== 'GET')
}

let container: HTMLDivElement
let root: Root

async function render() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => {
    root.render(React.createElement(LivingPalaceView))
  })
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

async function tick() {
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
  await tick()
}

async function clickText(text: string) {
  const el = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === text)
  expect(el, `missing button "${text}"`).not.toBeUndefined()
  await act(async () => {
    el!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await tick()
}

async function setNumber(testid: string, value: string) {
  const el = container.querySelector(`[data-testid="${testid}"]`) as HTMLInputElement | null
  expect(el, `missing ${testid}`).not.toBeNull()
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    setter.call(el!, value)
    el!.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await tick()
}

async function setSelect(testid: string, value: string) {
  const el = container.querySelector(`[data-testid="${testid}"]`) as HTMLSelectElement | null
  expect(el, `missing ${testid}`).not.toBeNull()
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')!.set!
  await act(async () => {
    setter.call(el!, value)
    el!.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await tick()
}

function panelText(): string {
  return container.querySelector('[data-testid="palace-weighing-panel"]')?.textContent ?? ''
}

async function descendToFloor() {
  await click('palace-building-i1')
  await click('palace-floor-p1')
}

beforeEach(() => {
  calls.length = 0
  decisionsFail = false
  installFetchStub()
})

afterEach(() => {
  act(() => root?.unmount())
  container?.remove()
  vi.unstubAllGlobals()
})

describe('Scales-1 — the weighing at the view', () => {
  it('floor exploration writes nothing, the balance moves, and settling writes exactly the settled figures plus the decision', async () => {
    await render()
    await descendToFloor()
    await click('palace-floor-scales')
    expect(container.querySelector('[data-testid="palace-weighing-panel"]')).not.toBeNull()
    // As recorded: Jo within, Sam over.
    expect(panelText()).toContain('Jo Keeper — 6h a week committed')
    expect(panelText()).toContain('within it, with 14h to spare')
    expect(panelText()).toContain('Sam Support — 14h a week committed')
    expect(panelText()).toContain('over by 4h')
    expect(writes()).toEqual([])

    // Explore: raise the floor's ask to 30 — both keepers go over,
    // and still nothing is written.
    await setNumber('palace-weighing-project-hours', '30')
    expect(panelText()).toContain('Jo Keeper — 30h a week committed')
    expect(panelText()).toContain('over by 10h')
    expect(panelText()).toContain('As recorded: Jo Keeper — 6h a week committed')
    expect(writes()).toEqual([])

    // Keep the arrangement, wander to another, return to the kept one.
    await click('palace-weighing-stash')
    await setNumber('palace-weighing-project-hours', '12')
    expect(panelText()).toContain('Jo Keeper — 12h a week committed')
    await click('palace-weighing-restore-0')
    const hoursInput = container.querySelector('[data-testid="palace-weighing-project-hours"]') as HTMLInputElement
    expect(hoursInput.value).toBe('30')
    expect(writes()).toEqual([])

    // The settle act — and only it — writes.
    await click('palace-weighing-settle')
    const w = writes()
    expect(w.map((x) => `${x.method} ${x.url}`)).toEqual([
      'PATCH /vision-execution/projects/p1',
      'POST /vision-execution/decisions',
    ])
    expect(w[0].body).toEqual({ estimated_weekly_hours: 30 })
    const decision = w[1].body as {
      entity_type: string
      entity_id: string
      decision_type: string
      ai_proposal_snapshot: { explored: Record<string, unknown>; recorded_before: Record<string, unknown> }
      final_values_snapshot: { settled: Record<string, unknown> }
    }
    expect(decision.entity_type).toBe('project')
    expect(decision.entity_id).toBe('p1')
    expect(decision.decision_type).toBe('scales_weighing')
    expect(decision.ai_proposal_snapshot.explored.project_weekly_hours).toBe(30)
    expect(decision.ai_proposal_snapshot.recorded_before.project_weekly_hours).toBe(6)
    expect(decision.final_values_snapshot.settled.project_weekly_hours).toBe(30)
    // The panel closed; the keeping is announced.
    expect(container.querySelector('[data-testid="palace-weighing-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-toast"]')?.textContent).toContain('kept as a decision')
  })

  it('closing the scales discards the arrangement — nothing is kept, nothing written', async () => {
    await render()
    await descendToFloor()
    await click('palace-floor-scales')
    await setNumber('palace-weighing-project-hours', '30')
    await clickText('Close')
    expect(container.querySelector('[data-testid="palace-weighing-panel"]')).toBeNull()
    await click('palace-floor-scales')
    const hoursInput = container.querySelector('[data-testid="palace-weighing-project-hours"]') as HTMLInputElement
    expect(hoursInput.value).toBe('6')
    expect(writes()).toEqual([])
  })

  it('re-seating the keeper re-bases capacity; settling writes the owner, the capacity, and the decision', async () => {
    await render()
    await descendToFloor()
    await click('palace-floor-scales')
    await setSelect('palace-weighing-keeper', 'per2')
    // Sam's recorded capacity replaces Jo's on the capacity pan.
    const capacityInput = container.querySelector('[data-testid="palace-weighing-capacity"]') as HTMLInputElement
    expect(capacityInput.value).toBe('10')
    // Jo's commitment falls to nothing on this floor's work; Sam's stands.
    expect(panelText()).toContain('Jo Keeper — 0h a week committed')
    expect(writes()).toEqual([])

    await setNumber('palace-weighing-capacity', '16')
    await click('palace-weighing-settle')
    const w = writes()
    expect(w.map((x) => `${x.method} ${x.url}`)).toEqual([
      'PATCH /vision-execution/projects/p1',
      'PUT /vision-execution/capacity-profiles',
      'POST /vision-execution/decisions',
    ])
    // The owner patch carries ONLY the owner — no hours were settled.
    expect(w[0].body).toEqual({ owner_id: 'per2' })
    expect(w[1].body).toEqual({ person_id: 'per2', weekly_capacity_hours: 16 })
    const decision = w[2].body as { ai_proposal_snapshot: { explored: Record<string, unknown> } }
    expect(decision.ai_proposal_snapshot.explored.keeper_id).toBe('per2')
    expect(decision.ai_proposal_snapshot.explored.keeper_capacity_hours).toBe(16)
  })

  it('a room’s weighing settles its estimate through the task route, keyed to the room', async () => {
    await render()
    await descendToFloor()
    await click('palace-room-t1')
    await click('palace-room-scales')
    expect(container.querySelector('[data-testid="palace-weighing-panel"]')).not.toBeNull()
    const taskInput = container.querySelector('[data-testid="palace-weighing-task-hours"]') as HTMLInputElement
    expect(taskInput.value).toBe('4')
    expect(writes()).toEqual([])

    await setNumber('palace-weighing-task-hours', '9')
    await click('palace-weighing-settle')
    const w = writes()
    expect(w.map((x) => `${x.method} ${x.url}`)).toEqual([
      'PATCH /vision-execution/tasks/t1',
      'POST /vision-execution/decisions',
    ])
    expect(w[0].body).toEqual({ estimated_hours: 9 })
    const decision = w[1].body as {
      entity_type: string
      entity_id: string
      ai_proposal_snapshot: { explored: Record<string, unknown>; recorded_before: Record<string, unknown> }
    }
    expect(decision.entity_type).toBe('task')
    expect(decision.entity_id).toBe('t1')
    expect(decision.ai_proposal_snapshot.explored.task_estimated_hours).toBe(9)
    expect(decision.ai_proposal_snapshot.recorded_before.task_estimated_hours).toBe(4)
  })

  it('a room with no recorded estimate exposes no weighing surface', async () => {
    await render()
    await descendToFloor()
    await click('palace-room-t2')
    await click('palace-room-scales')
    expect(container.querySelector('[data-testid="palace-weighing-panel"]')).toBeNull()
    expect(container.querySelector('[data-testid="palace-toast"]')?.textContent).toContain(
      'pans are empty for this room',
    )
    expect(writes()).toEqual([])
  })

  it('when the decision’s keeping is refused, the figures still stand and the surface says so', async () => {
    decisionsFail = true
    await render()
    await descendToFloor()
    await click('palace-floor-scales')
    await setNumber('palace-weighing-project-hours', '12')
    await click('palace-weighing-settle')
    const w = writes()
    // The figure landed; the decision was attempted and refused.
    expect(w.map((x) => `${x.method} ${x.url}`)).toEqual([
      'PATCH /vision-execution/projects/p1',
      'POST /vision-execution/decisions',
    ])
    expect(container.querySelector('[data-testid="palace-toast"]')?.textContent).toContain(
      'could not be kept as a decision',
    )
  })
})
