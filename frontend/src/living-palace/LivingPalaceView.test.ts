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
    vi.fn(async (input: unknown) => {
      const url = String(input)
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

async function render() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => {
    root.render(React.createElement(LivingPalaceView))
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
