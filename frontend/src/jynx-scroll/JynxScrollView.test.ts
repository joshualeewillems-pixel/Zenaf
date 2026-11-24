// @vitest-environment jsdom
/**
 * Jynx's Scroll view — jsdom render verification.
 *
 * The view mounts against a stubbed Vision Execution API (the same
 * routes the product uses) and must render the shelf from the data:
 * one rolled scroll per recorded item — initiatives heading their
 * bays, projects and tasks nested under them, unanchored items and
 * ideas in the base bin — with distinctions from recorded fields
 * only (a Blocked project's binding wears Jynx's violet). Choosing
 * a scroll unrolls it on the stand (the founder's ground) and keys
 * the conversation to it; with no drawing feed, the unrolled scroll
 * is honestly blank; with stubbed pencil-shaped drawings (ordered
 * stamp/stroke marks), the marks render in order and tapping the
 * drawing keys the conversation to it. CouncilChat is stubbed and
 * records its props — the chat seam itself is covered by its own
 * suite.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import type { ScrollDrawing } from './scrollLogic'

const stubDrawings = vi.hoisted(() => ({ current: [] as ScrollDrawing[] }))

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: {
      conversationId?: string
      context?: Record<string, unknown>
      initialArchetypeId?: string
    }) =>
      ReactMod.createElement('div', {
        'data-testid': 'jynx-chat',
        'data-conversation-id': props.conversationId ?? '',
        'data-context': JSON.stringify(props.context ?? {}),
        'data-archetype': props.initialArchetypeId ?? '',
      }),
  }
})

vi.mock('./scrollApi', async (importOriginal) => {
  const orig = await importOriginal<typeof import('./scrollApi')>()
  return { ...orig, fetchScrollDrawings: async () => stubDrawings.current }
})

import JynxScrollView from './JynxScrollView'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const base = {
  brief: '', owner_id: null, supporting_owner_ids: [], priority: '',
  start_date: null, end_date: null, estimated_weekly_hours: null,
  next_step_ai: '', notes: '', created_at: '2026-02-01T00:00:00', updated_at: '2026-02-01T00:00:00',
}
const tbase = {
  parent_task_id: null, description: '', assignee_id: null, priority: '',
  estimated_hours: null, due_date: null, dependency_ids: [],
  completion_criteria: '', notes: '', created_at: '2026-03-01T00:00:00', updated_at: '2026-03-01T00:00:00',
}

function stubFetch() {
  const data: Record<string, unknown> = {
    '/vision-execution/ideas': [
      { id: 'idea1', title: 'A loose idea', summary: '', description: '', status: 'Captured', tags: [], created_by: '', notes: '', created_at: '2025-12-01T00:00:00', updated_at: '2025-12-01T00:00:00' },
    ],
    '/vision-execution/initiatives': [
      { id: 'i1', title: 'Council fellowship', status: 'Active', source_idea_id: null, created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00' },
    ],
    '/vision-execution/projects': [
      { ...base, id: 'p1', initiative_id: 'i1', title: 'Meet the Bear', status: 'Blocked' },
      { ...base, id: 'p2', initiative_id: null, title: 'Fix the gate latch', status: 'Ready' },
    ],
    '/vision-execution/tasks': [
      { ...tbase, id: 't1', project_id: 'p1', title: 'Bear step one', status: 'Todo' },
      { ...tbase, id: 't2', project_id: null, title: 'Loose thought', status: 'Todo' },
    ],
    '/vision-execution/persons': [],
    '/vision-execution/assets': [],
  }
  return vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => data[url] ?? [],
    text: async () => '',
  }))
}

const DRAWING: ScrollDrawing = {
  id: 'd1',
  title: 'Icarus, again',
  space: { w: 600, h: 800 },
  marks: [
    { type: 'stamp', stamp: 'ring', cx: 300, cy: 300, w: 400, tier: 0.6 },
    { type: 'stamp', stamp: 'slash', cx: 220, cy: 480, w: 200, angle: 52, tier: 0.95 },
    { type: 'stroke', d: 'M100 600 Q300 560 500 620', width: 3, tier: 0.32 },
  ],
}

describe('JynxScrollView', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    stubDrawings.current = []
    vi.stubGlobal('fetch', stubFetch())
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  async function flush() {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
  }

  async function render() {
    await act(async () => {
      root.render(React.createElement(JynxScrollView))
    })
    await flush()
    await flush()
  }

  function chat() {
    return container.querySelector('[data-testid="jynx-chat"]')
  }

  function scrollEl(kind: string, id: string) {
    return container.querySelector(`[data-scroll="${kind}:${id}"]`)
  }

  async function choose(kind: string, id: string) {
    const g = scrollEl(kind, id)
    expect(g).not.toBeNull()
    const hit = [...g!.querySelectorAll('rect')].find((r) => r.getAttribute('fill-opacity') === '0')
    expect(hit).toBeTruthy()
    await act(async () => {
      hit!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
  }

  it('renders the shelf of scrolls from VE data — every item, nested, ideas in the bin', async () => {
    await render()
    expect(container.textContent).toContain('The Shelf of Scrolls')
    // One scroll per recorded item: initiative, its project + task,
    // the unanchored project, the loose task, the idea.
    for (const [kind, id] of [
      ['initiative', 'i1'],
      ['project', 'p1'],
      ['task', 't1'],
      ['project', 'p2'],
      ['task', 't2'],
      ['idea', 'idea1'],
    ] as const) {
      expect(scrollEl(kind, id), `${kind}:${id}`).not.toBeNull()
    }
    expect(container.textContent).toContain('Council fellowship')
    expect(container.textContent).toContain('Meet the Bear')
    expect(container.textContent).toContain('Bear step one')
    // The stand stands empty; the conversation is Jynx's, keyed to the shelf.
    expect(container.querySelector('[data-open-scroll]')).toBeNull()
    expect(chat()?.getAttribute('data-archetype')).toBe('maverick')
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:shelf')
    expect(JSON.parse(chat()?.getAttribute('data-context') ?? '{}')).toEqual({
      sheet_type: 'jynx_scroll',
    })
  })

  it('distinguishes scrolls from recorded fields only — the Blocked binding wears violet', async () => {
    await render()
    const violetCords = [...container.querySelectorAll('rect')].filter(
      (r) => r.getAttribute('fill') === '#a55cce',
    )
    // Exactly the Blocked project's two binding cords — nothing
    // else on the shelf is violet.
    expect(violetCords).toHaveLength(2)
    const blocked = scrollEl('project', 'p1')
    expect([...blocked!.querySelectorAll('rect')].some((r) => r.getAttribute('fill') === '#a55cce')).toBe(true)
    const ready = scrollEl('project', 'p2')
    expect([...ready!.querySelectorAll('rect')].some((r) => r.getAttribute('fill') === '#a55cce')).toBe(false)
  })

  it('choosing a scroll unrolls it on the stand and keys the conversation to it', async () => {
    await render()
    await choose('project', 'p1')
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open).not.toBeNull()
    // The unrolled scroll is the founder's ground asset.
    const img = open!.querySelector('image')
    expect(img?.getAttribute('href')).toContain('scroll-ground')
    expect(container.textContent).toContain('← The shelf')
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:project:p1')
    expect(JSON.parse(chat()?.getAttribute('data-context') ?? '{}')).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'project',
      entity_id: 'p1',
    })
    // Choosing it again puts it back on the shelf.
    await choose('project', 'p1')
    expect(container.querySelector('[data-open-scroll]')).toBeNull()
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:shelf')
  })

  it('empty-pencil honesty: an opened scroll with no drawing feed is blank — no marks, no invented art', async () => {
    await render()
    await choose('task', 't1')
    const open = container.querySelector('[data-open-scroll="task:t1"]')
    expect(open).not.toBeNull()
    expect(open!.querySelectorAll('[data-drawing-id]')).toHaveLength(0)
    expect(open!.querySelectorAll('[data-mark]')).toHaveLength(0)
    // The only image on the sheet is the ground itself.
    expect(open!.querySelectorAll('image')).toHaveLength(1)
  })

  it('renders a drawing’s marks in order on the sheet, and tapping it keys the conversation to the drawing', async () => {
    stubDrawings.current = [DRAWING]
    await render()
    await choose('project', 'p1')
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    const drawingEl = open!.querySelector('[data-drawing-id="d1"]')
    expect(drawingEl).not.toBeNull()
    const marks = [...drawingEl!.querySelectorAll('[data-mark]')]
    // Arrival order is list order: stamp, stamp, stroke.
    expect(marks.map((m) => m.getAttribute('data-mark'))).toEqual(['stamp', 'stamp', 'stroke'])
    expect(marks[0].getAttribute('data-stamp')).toBe('ring')
    expect(marks[1].getAttribute('data-stamp')).toBe('slash')
    // The stamp is the kit's own PNG, not a redrawn shape.
    expect(marks[0].querySelector('image')?.getAttribute('href')).toContain('ring')

    const hit = [...open!.querySelectorAll('rect')].find((r) => r.getAttribute('fill-opacity') === '0')
    expect(hit).toBeTruthy()
    await act(async () => {
      hit!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:drawing:d1')
    expect(JSON.parse(chat()?.getAttribute('data-context') ?? '{}')).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'drawing',
      entity_id: 'd1',
    })
  })

  it('multiple drawings stand as sections — the rollers roll between them', async () => {
    const second: ScrollDrawing = {
      id: 'd2',
      title: null,
      space: { w: 600, h: 800 },
      marks: [{ type: 'stamp', stamp: 'wave', cx: 300, cy: 400, w: 380, tier: 0.6 }],
    }
    stubDrawings.current = [DRAWING, second]
    await render()
    await choose('project', 'p1')
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    expect(container.querySelector('[data-drawing-id="d2"]')).toBeNull()
    const controls = container.querySelector('[data-testid="section-controls"]')
    expect(controls).not.toBeNull()
    const forward = [...controls!.querySelectorAll('rect')].find((r) =>
      r.querySelector('title')?.textContent === 'Roll forward',
    )
    expect(forward).toBeTruthy()
    await act(async () => {
      forward!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.querySelector('[data-drawing-id="d2"]')).not.toBeNull()
    expect(container.querySelector('[data-drawing-id="d1"]')).toBeNull()
  })
})
