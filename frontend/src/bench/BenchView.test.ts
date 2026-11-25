// @vitest-environment jsdom
/**
 * Bench view — jsdom render verification against a stubbed Vision
 * Execution API (the same routes the product uses).
 *
 * The stubbed record holds one project with three twigs (tasks —
 * the corrected grammar: a project standing as its own tree carries
 * its tasks as twigs off the trunk): one whose record carries
 * cross-seat discussion evidence (origin provenance from a
 * conversation with Maeve), one carrying a pending recorded
 * proposal from Valen (wire), and one dropped (jin). The
 * suite asserts: the shelf captions true kinds; foliage is marked
 * ONLY on the evidenced twig; the wire tap opens the proposal;
 * "Let this stand" takes the governed approve endpoint and lands in
 * the verdict log; the footing opens the notebook quoting the
 * record. CouncilChat is stubbed — the chat seam is covered by its
 * own suite; canvas painting is covered by paint.test.ts (jsdom has
 * no 2D rasteriser, so BenchCanvas paints nothing here and its tap
 * targets carry the surface).
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
        'data-testid': 'severine-chat',
        'data-conversation-id': props.conversationId ?? '',
      }),
  }
})

import BenchView from './BenchView'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const PROJECT = {
  id: 'p1', initiative_id: null, title: 'Winter client season', brief: 'The winter round.',
  status: 'Active', owner_id: null, supporting_owner_ids: [], priority: '',
  start_date: null, end_date: null, estimated_weekly_hours: null, next_step_ai: '',
  notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
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
  taskRow({
    id: 't-timber', title: 'Order timber',
    origin_seat: 'guardian', origin_conversation_id: 'talk-123', origin_message_id: 'm-9',
  }),
  taskRow({ id: 't-bookings', title: 'Confirm Saturday bookings', status: 'In Progress' }),
  taskRow({ id: 't-old', title: 'Old price list', status: 'Dropped' }),
]

const IDEA = {
  id: 'idea-1', title: 'Take on an apprentice', summary: '', description: '',
  status: 'Captured', tags: [], created_by: 'user',
  created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
}

const PROPOSAL = {
  id: 'prop-1', seat: 'champion', title: 'Book the scaffolding early',
  parent_task_id: 't-bookings', state: 'pending', notes: '',
  evidence_quote: 'the yard gets busy in November', conversation_id: 'talk-77',
  created_at: '2026-05-02T00:00:00',
}

const calls: Array<{ method: string; url: string }> = []

function stubFetch() {
  return vi.fn(async (input: unknown, init?: { method?: string }) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    calls.push({ method, url })
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    if (url.includes('/vision-execution/projects')) return json([PROJECT])
    if (url.includes('/vision-execution/tasks')) return json(TASKS)
    if (url.includes('/vision-execution/ideas')) return json([IDEA])
    if (url.includes('/vision-execution/initiatives')) return json([])
    if (url.includes('/vision-execution/persons')) return json([])
    if (url.includes('/vision-execution/assets')) return json([])
    if (url.includes('/task-proposals/by-parent/t-bookings')) return json({ proposals: [PROPOSAL] })
    if (url.includes('/task-proposals/by-parent/')) return json({ proposals: [] })
    if (url.includes(`/task-proposals/${PROPOSAL.id}/approve`)) {
      return json({ task: { id: 't-new' }, proposal: { ...PROPOSAL, state: 'approved' } })
    }
    if (url.includes(`/task-proposals/${PROPOSAL.id}/decline`)) {
      return json({ ...PROPOSAL, state: 'declined' })
    }
    return json({})
  })
}

let root: Root | null = null
let container: HTMLDivElement | null = null

async function renderBench() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => {
    root!.render(React.createElement(BenchView))
  })
  // let the entity + proposal fetches settle
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20))
  })
}

function findButton(textOrLabel: string, attr?: [string, string]): HTMLButtonElement {
  const buttons = [...container!.querySelectorAll('button')]
  const found = buttons.find((b) =>
    attr
      ? b.getAttribute(attr[0]) === attr[1]
      : (b.textContent ?? '').includes(textOrLabel) || b.getAttribute('aria-label') === textOrLabel,
  )
  if (!found) throw new Error(`button not found: ${textOrLabel} ${attr?.join('=') ?? ''}`)
  return found as HTMLButtonElement
}

async function click(el: HTMLElement) {
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20))
  })
}

beforeEach(() => {
  calls.length = 0
  vi.stubGlobal('fetch', stubFetch())
})

afterEach(() => {
  if (root) act(() => root!.unmount())
  root = null
  container?.remove()
  container = null
  vi.unstubAllGlobals()
})

describe("Severine's Bench — render verification", () => {
  it('the shelf captions true kinds and registers', async () => {
    await renderBench()
    const text = container!.textContent ?? ''
    expect(text).toContain('The Shelf')
    expect(text).toContain('Winter client season')
    expect(text).toContain('Take on an apprentice')
    // kinds are captioned, not flattened
    const kinds = [...container!.querySelectorAll('span')].map((s) => s.textContent)
    expect(kinds).toContain('Project')
    expect(kinds).toContain('Idea')
    const projectTile = container!.querySelector('[data-shelf-item="p1"]')
    expect(projectTile?.getAttribute('data-register')).toBe('wood')
    const ideaTile = container!.querySelector('[data-shelf-item="idea-1"]')
    expect(ideaTile?.getAttribute('data-register')).toBe('sumi')
  })

  it('foliage is marked ONLY on the twig with discussion evidence', async () => {
    await renderBench()
    await click(findButton('', ['data-shelf-item', 'p1']))
    // the project's tasks stand as twig rows — there are no task branches
    expect(container!.querySelectorAll('[data-branch-row]')).toHaveLength(0)
    const rows = [...container!.querySelectorAll('[data-twig-row]')]
    expect(rows.map((r) => r.getAttribute('data-twig-row'))).toEqual(
      expect.arrayContaining(['t-timber', 't-bookings', 't-old']),
    )
    const foliage = rows.map((r) => [r.getAttribute('data-twig-row'), r.getAttribute('data-foliage-seat')])
    expect(foliage).toContainEqual(['t-timber', 'guardian'])
    expect(foliage).toContainEqual(['t-bookings', ''])
    expect(foliage).toContainEqual(['t-old', ''])
    // selecting the evidenced twig states the evidence in words
    await click(findButton('', ['data-twig-row', 't-timber']))
    const detail = container!.querySelector('[data-twig-detail="t-timber"]')
    expect(detail?.textContent).toContain('foliage in Maeve’s colour')
    expect(detail?.textContent).toContain('discussed with Maeve')
    // selecting a bare twig says so honestly
    await click(findButton('', ['data-twig-row', 't-bookings']))
    const bare = container!.querySelector('[data-twig-detail="t-bookings"]')
    expect(bare?.textContent).toContain('It is bare')
  })

  it('the wire tap opens the proposal and "Let this stand" takes the governed approve path', async () => {
    await renderBench()
    await click(findButton('', ['data-shelf-item', 'p1']))
    const wire = container!.querySelector('[data-tap="wire"][data-twig="t-bookings"]')
    expect(wire).not.toBeNull()
    await click(wire as HTMLElement)
    const card = container!.querySelector('[data-proposal-card="prop-1"]')
    expect(card).not.toBeNull()
    expect(card!.textContent).toContain('Book the scaffolding early')
    expect(card!.textContent).toContain('Valen')
    expect(card!.textContent).toContain('the yard gets busy in November')
    await click(findButton('Let this stand'))
    expect(
      calls.some(
        (c) => c.method === 'POST' && c.url.includes('/task-proposals/prop-1/approve'),
      ),
    ).toBe(true)
    // the card closes and the ruling lands in the verdict log
    expect(container!.querySelector('[data-proposal-card="prop-1"]')).toBeNull()
    await click(findButton('Verdict log'))
    expect(container!.textContent).toContain('Let stand — “Book the scaffolding early”')
  })

  it('"Cut this back" takes the governed decline path', async () => {
    await renderBench()
    await click(findButton('', ['data-shelf-item', 'p1']))
    const wire = container!.querySelector('[data-tap="wire"][data-twig="t-bookings"]')
    await click(wire as HTMLElement)
    await click(findButton('Cut this back'))
    expect(
      calls.some(
        (c) => c.method === 'POST' && c.url.includes('/task-proposals/prop-1/decline'),
      ),
    ).toBe(true)
    await click(findButton('Verdict log'))
    expect(container!.textContent).toContain('Cut back — “Book the scaffolding early”')
  })

  it('the footing opens the notebook quoting the record', async () => {
    await renderBench()
    await click(findButton('', ['data-shelf-item', 'p1']))
    const footing = container!.querySelector('[data-tap="footing"]')
    expect(footing).not.toBeNull()
    await click(footing as HTMLElement)
    const dialog = container!.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog!.textContent).toContain('Notebook — Winter client season')
    expect(dialog!.textContent).toContain('Documented footing')
    expect(dialog!.textContent).toContain('Discussed with Maeve — Order timber')
    expect(dialog!.textContent).toContain('The winter round.')
  })

  it('the shelf holds parents + loose only — an initiative-owned project reaches the bench through its tree', async () => {
    const OWNED = { ...PROJECT, id: 'p-owned', initiative_id: 'i1', title: 'Depot refit' }
    const INI = {
      id: 'i1', source_idea_id: null, title: 'Rebuild the workshop', brief: '',
      status: 'Active', owner_id: null, evaluation_priority: null, estimated_cost_ai: '',
      estimated_timeframe_ai: '', philosophical_alignment_ai: '', next_step_ai: '',
      required_assets: [], dependencies: '', risks: '', recommendation: '',
      kill_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const OWNED_TASKS = [
      taskRow({
        id: 't-owned-1', project_id: 'p-owned', title: 'Survey the depot',
        origin_seat: 'guardian', origin_conversation_id: 'talk-9', origin_message_id: 'm-3',
      }),
      taskRow({ id: 't-owned-2', project_id: 'p-owned', title: 'Price the steel' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: unknown, init?: { method?: string }) => {
        const url = String(input)
        void init
        const json = (body: unknown) =>
          new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
        if (url.includes('/vision-execution/projects')) return json([PROJECT, OWNED])
        if (url.includes('/vision-execution/tasks')) return json([...TASKS, ...OWNED_TASKS])
        if (url.includes('/vision-execution/ideas')) return json([IDEA])
        if (url.includes('/vision-execution/initiatives')) return json([INI])
        if (url.includes('/vision-execution/persons')) return json([])
        if (url.includes('/vision-execution/assets')) return json([])
        if (url.includes('/task-proposals/by-parent/')) return json({ proposals: [] })
        return json({})
      }),
    )
    await renderBench()
    // Shelf roots: the initiative, the loose project, the idea —
    // NOT the initiative-owned project.
    expect(container!.querySelector('[data-shelf-item="i1"]')).not.toBeNull()
    expect(container!.querySelector('[data-shelf-item="p1"]')).not.toBeNull()
    expect(container!.querySelector('[data-shelf-item="p-owned"]')).toBeNull()
    // Open the initiative's tree: the owned project stands as a
    // BRANCH, its tasks as TWIGS on the branch — the discussed twig
    // carrying Maeve's foliage mark, the branch itself none.
    await click(findButton('', ['data-shelf-item', 'i1']))
    const row = container!.querySelector('[data-branch-row="p-owned"]')
    expect(row).not.toBeNull()
    expect(row!.getAttribute('data-foliage-seat')).toBe('')
    const twigRow = container!.querySelector('[data-twig-row="t-owned-1"]')
    expect(twigRow).not.toBeNull()
    expect(twigRow!.getAttribute('data-foliage-seat')).toBe('guardian')
    expect(container!.querySelector('[data-twig-row="t-owned-2"]')).not.toBeNull()
    // The branch's detail carries the door that brings the BRANCH
    // forward — at working size, with its twigs on it.
    await click(row as HTMLElement)
    const detail = container!.querySelector('[data-branch-detail="p-owned"]')
    expect(detail).not.toBeNull()
    expect(detail!.textContent).toContain('stand as twigs on this branch')
    await click(findButton('Bring this branch forward'))
    const benchChat = container!.querySelector('[data-testid="severine-chat"]')
    expect(benchChat?.getAttribute('data-conversation-id')).toBe('bench:project:p-owned')
    // Forward, the same tasks stand as twigs off the trunk.
    expect(container!.querySelector('[data-twig-row="t-owned-1"]')).not.toBeNull()
    expect(container!.querySelector('[data-branch-row]')).toBeNull()
  })

  it("the conversation beside the bench is Severine's, following the open tree", async () => {
    await renderBench()
    const shelfChat = container!.querySelector('[data-testid="severine-chat"]')
    expect(shelfChat?.getAttribute('data-conversation-id')).toBe('bench:shelf')
    await click(findButton('', ['data-shelf-item', 'p1']))
    const benchChat = container!.querySelector('[data-testid="severine-chat"]')
    expect(benchChat?.getAttribute('data-conversation-id')).toBe('bench:project:p1')
    // the split shell is the layout: divider present
    expect(container!.querySelector('[data-testid="split-divider"]')).not.toBeNull()
    expect(container!.querySelector('[data-testid="split-right"]')).not.toBeNull()
  })
})
