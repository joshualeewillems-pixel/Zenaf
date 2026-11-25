// @vitest-environment jsdom
/**
 * Jynx's Scroll view — jsdom render verification.
 *
 * The view mounts against a stubbed Vision Execution API (the same
 * routes the product uses) and must render the shelf under the
 * standing display rule — parents and loose items only: the
 * initiative in the lattice, the unanchored project, the loose
 * task and the idea in the bin; the initiative's project and the
 * project's task are NOT on the shelf face. Choosing a scroll
 * opens its own screen: the scroll unrolls large (the founder's
 * ground) with NO text on the sheet, its children stand beneath
 * it as scrolls of their own, and the conversation keys to the
 * open scroll at every level. With no drawing feed, the unrolled
 * scroll is honestly blank; with stubbed pencil-shaped drawings
 * (ordered stamp/stroke marks), the marks render in order and
 * tapping the drawing keys the conversation to it. CouncilChat
 * is stubbed and records its props — the chat seam itself is
 * covered by its own suite.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import type { ScrollDrawing } from './scrollLogic'

const stubDrawings = vi.hoisted(() => ({
  current: [] as ScrollDrawing[],
  calls: 0,
  fail: false,
}))

/** The chat stub's latest props — the turn-landing tests fire the
 *  view's onTurnSent exactly as CouncilChat does after a reply. */
const chatStub = vi.hoisted(() => ({
  latest: null as null | { onTurnSent?: () => void },
}))

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: {
      conversationId?: string
      context?: Record<string, unknown>
      initialArchetypeId?: string
      onTurnSent?: () => void
    }) => {
      chatStub.latest = props
      return ReactMod.createElement('div', {
        'data-testid': 'jynx-chat',
        'data-conversation-id': props.conversationId ?? '',
        'data-context': JSON.stringify(props.context ?? {}),
        'data-archetype': props.initialArchetypeId ?? '',
      })
    },
  }
})

vi.mock('./scrollApi', async (importOriginal) => {
  const orig = await importOriginal<typeof import('./scrollApi')>()
  return {
    ...orig,
    fetchScrollDrawings: async () => {
      stubDrawings.calls += 1
      if (stubDrawings.fail) throw new Error('the feed is unavailable')
      return stubDrawings.current
    },
  }
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
      { ...base, id: 'p2', initiative_id: null, title: 'Fix the gate latch', status: 'Blocked' },
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
    stubDrawings.calls = 0
    stubDrawings.fail = false
    chatStub.latest = null
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

  async function clickEl(el: Element) {
    await act(async () => {
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
  }

  /** Choose a scroll on the shelf face. */
  async function choose(kind: string, id: string) {
    const g = scrollEl(kind, id)
    expect(g, `${kind}:${id} on the shelf`).not.toBeNull()
    const hit = [...g!.querySelectorAll('rect')].find((r) => r.getAttribute('fill-opacity') === '0')
    expect(hit).toBeTruthy()
    await clickEl(hit!)
  }

  /** Open a child scroll from the open scroll's screen. */
  async function openChild(kind: string, id: string) {
    const btn = container.querySelector(`[data-child-scroll="${kind}:${id}"]`)
    expect(btn, `child ${kind}:${id}`).not.toBeNull()
    await clickEl(btn!)
  }

  async function goBack() {
    const btn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.startsWith('←'),
    )
    expect(btn, 'back button').toBeTruthy()
    await clickEl(btn!)
  }

  /** Fire the chat's turn-landed callback, as CouncilChat does on
   *  its success arms after a reply lands. */
  async function turnLanded() {
    const cb = chatStub.latest?.onTurnSent
    expect(cb, 'the view wires CouncilChat’s onTurnSent').toBeTypeOf('function')
    await act(async () => {
      cb!()
    })
    await flush()
    await flush()
  }

  function roller(testId: string) {
    return container.querySelector(`[data-testid="${testId}"]`)
  }

  it('renders the shelf face — parents and loose only, children absent', async () => {
    await render()
    expect(container.textContent).toContain('The Shelf of Scrolls')
    // On the face: the initiative, the unanchored project, the
    // loose task, the idea.
    for (const [kind, id] of [
      ['initiative', 'i1'],
      ['project', 'p2'],
      ['task', 't2'],
      ['idea', 'idea1'],
    ] as const) {
      expect(scrollEl(kind, id), `${kind}:${id}`).not.toBeNull()
    }
    // NOT on the face: the initiative's project and its task.
    expect(scrollEl('project', 'p1')).toBeNull()
    expect(scrollEl('task', 't1')).toBeNull()
    expect(container.textContent).not.toContain('Meet the Bear')
    expect(container.textContent).not.toContain('Bear step one')
    // No scroll is open; the conversation is Jynx's, keyed to the shelf.
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
    // Exactly the Blocked loose project's two binding cords —
    // nothing else on the shelf face is violet.
    expect(violetCords).toHaveLength(2)
    const blocked = scrollEl('project', 'p2')
    expect([...blocked!.querySelectorAll('rect')].some((r) => r.getAttribute('fill') === '#a55cce')).toBe(true)
    const active = scrollEl('initiative', 'i1')
    expect([...active!.querySelectorAll('rect')].some((r) => r.getAttribute('fill') === '#a55cce')).toBe(false)
  })

  it('choosing a scroll opens its own screen — children beneath, back by levels, chat keyed throughout', async () => {
    await render()
    await choose('initiative', 'i1')
    // The initiative's own screen: its scroll unrolled, its project
    // standing beneath as a child scroll.
    expect(container.querySelector('[data-open-scroll="initiative:i1"]')).not.toBeNull()
    expect(container.querySelector('[data-scroll]')).toBeNull() // the shelf is replaced
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:initiative:i1')

    await openChild('project', 'p1')
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open).not.toBeNull()
    // The unrolled scroll is the founder's ground asset.
    const img = open!.querySelector('image')
    expect(img?.getAttribute('href')).toContain('scroll-ground')
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:project:p1')
    expect(JSON.parse(chat()?.getAttribute('data-context') ?? '{}')).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'project',
      entity_id: 'p1',
    })
    // The project's task stands beneath as a child scroll.
    expect(container.querySelector('[data-child-scroll="task:t1"]')).not.toBeNull()

    // Back steps land on the parent first, then the shelf.
    await goBack()
    expect(container.querySelector('[data-open-scroll="initiative:i1"]')).not.toBeNull()
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:initiative:i1')
    await goBack()
    expect(container.querySelector('[data-open-scroll]')).toBeNull()
    expect(container.textContent).toContain('The Shelf of Scrolls')
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:shelf')
  })

  it('the drawing scroll carries no text — no title on the sheet, no text elements at all', async () => {
    await render()
    await choose('initiative', 'i1')
    await openChild('project', 'p1')
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open).not.toBeNull()
    expect(open!.querySelectorAll('text')).toHaveLength(0)
    expect(open!.textContent ?? '').not.toContain('Meet the Bear')
  })

  it('empty-pencil honesty: an opened scroll with no drawing feed is blank — no marks, no invented art', async () => {
    await render()
    await choose('initiative', 'i1')
    await openChild('project', 'p1')
    await openChild('task', 't1')
    const open = container.querySelector('[data-open-scroll="task:t1"]')
    expect(open).not.toBeNull()
    expect(open!.querySelectorAll('[data-drawing-id]')).toHaveLength(0)
    expect(open!.querySelectorAll('[data-mark]')).toHaveLength(0)
    // The only image on the sheet is the ground itself.
    expect(open!.querySelectorAll('image')).toHaveLength(1)
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:task:t1')
  })

  it('renders a drawing’s marks in order on the sheet, and tapping it keys the conversation to the drawing', async () => {
    stubDrawings.current = [DRAWING]
    await render()
    await choose('initiative', 'i1')
    await openChild('project', 'p1')
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
    await clickEl(hit!)
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:drawing:d1')
    expect(JSON.parse(chat()?.getAttribute('data-context') ?? '{}')).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'drawing',
      entity_id: 'd1',
    })
  })

  it('multiple drawings stand as sections — the screen’s chrome rolls between them', async () => {
    const second: ScrollDrawing = {
      id: 'd2',
      title: null,
      space: { w: 600, h: 800 },
      marks: [{ type: 'stamp', stamp: 'wave', cx: 300, cy: 400, w: 380, tier: 0.6 }],
    }
    stubDrawings.current = [DRAWING, second]
    await render()
    await choose('initiative', 'i1')
    await openChild('project', 'p1')
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    expect(container.querySelector('[data-drawing-id="d2"]')).toBeNull()
    const controls = container.querySelector('[data-testid="section-controls"]')
    expect(controls).not.toBeNull()
    const forward = controls!.querySelector('[data-testid="section-forward"]')
    expect(forward).not.toBeNull()
    await clickEl(forward!)
    expect(container.querySelector('[data-drawing-id="d2"]')).not.toBeNull()
    expect(container.querySelector('[data-drawing-id="d1"]')).toBeNull()
    // The controls live in the chrome — the sheet itself stays text-free.
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open!.querySelectorAll('text')).toHaveLength(0)
  })

  it('choosing a scroll re-reads the feed — a drawing that arrived after mount renders', async () => {
    await render()
    const callsAfterMount = stubDrawings.calls
    expect(callsAfterMount).toBeGreaterThan(0)
    // Jynx draws (in a conversation, elsewhere) after this pane mounted.
    stubDrawings.current = [DRAWING]
    await choose('initiative', 'i1')
    expect(stubDrawings.calls).toBeGreaterThan(callsAfterMount)
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
  })

  it('a turn landing beside an open scroll re-reads the feed — the founder’s blank scroll fills in place', async () => {
    await render()
    await choose('initiative', 'i1')
    await openChild('project', 'p1')
    // The pane was open while Jynx drew: honestly blank until the
    // turn that made the drawing lands and the feed re-reads.
    expect(container.querySelector('[data-drawing-id]')).toBeNull()
    stubDrawings.current = [DRAWING]
    await turnLanded()
    expect(container.querySelector('[data-open-scroll="project:p1"]')).not.toBeNull()
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
  })

  it('the window waking re-reads the feed', async () => {
    await render()
    await choose('initiative', 'i1')
    stubDrawings.current = [DRAWING]
    await act(async () => {
      window.dispatchEvent(new Event('focus'))
    })
    await flush()
    await flush()
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
  })

  it('a failed re-read keeps the drawings already on the surface — never a false blank, never the error screen', async () => {
    stubDrawings.current = [DRAWING]
    await render()
    await choose('initiative', 'i1')
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    stubDrawings.fail = true
    await turnLanded()
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    expect(container.textContent).not.toContain('Could not load your scrolls.')
  })

  it('a re-read with the same list — or a grown one — never moves the visitor’s section', async () => {
    const second: ScrollDrawing = {
      id: 'd2',
      title: null,
      space: { w: 600, h: 800 },
      marks: [{ type: 'stamp', stamp: 'wave', cx: 300, cy: 400, w: 380, tier: 0.6 }],
    }
    const third: ScrollDrawing = {
      id: 'd3',
      title: null,
      space: { w: 600, h: 800 },
      marks: [{ type: 'stamp', stamp: 'leaf', cx: 300, cy: 400, w: 300, tier: 0.6 }],
    }
    stubDrawings.current = [DRAWING, second]
    await render()
    await choose('initiative', 'i1')
    await openChild('project', 'p1')
    // Roll to the second (newest) drawing.
    const forward = container.querySelector('[data-testid="section-forward"]') as HTMLButtonElement
    await clickEl(forward)
    expect(container.querySelector('[data-drawing-id="d2"]')).not.toBeNull()
    expect(forward.disabled).toBe(true)

    // Same list back from a re-read: the visitor stays on d2.
    await turnLanded()
    expect(container.querySelector('[data-drawing-id="d2"]')).not.toBeNull()
    expect(
      (container.querySelector('[data-testid="section-forward"]') as HTMLButtonElement).disabled,
    ).toBe(true)

    // A grown list: still on d2, and the new drawing waits one
    // roll forward — reachable, not thrust into view.
    stubDrawings.current = [DRAWING, second, third]
    await turnLanded()
    expect(container.querySelector('[data-drawing-id="d2"]')).not.toBeNull()
    const forwardNow = container.querySelector('[data-testid="section-forward"]') as HTMLButtonElement
    expect(forwardNow.disabled).toBe(false)
    await clickEl(forwardNow)
    expect(container.querySelector('[data-drawing-id="d3"]')).not.toBeNull()
  })

  it('the open scroll’s rollers page its drawings — top toward the older, bottom toward the newer, inert at the ends', async () => {
    const second: ScrollDrawing = {
      id: 'd2',
      title: null,
      space: { w: 600, h: 800 },
      marks: [{ type: 'stamp', stamp: 'wave', cx: 300, cy: 400, w: 380, tier: 0.6 }],
    }
    stubDrawings.current = [DRAWING, second]
    await render()
    await choose('initiative', 'i1')
    await openChild('project', 'p1')
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()

    const back = roller('roller-back')
    const fwd = roller('roller-forward')
    expect(back, 'top roller control').not.toBeNull()
    expect(fwd, 'bottom roller control').not.toBeNull()
    expect(back!.getAttribute('aria-label')).toBe('Previous drawing')
    expect(fwd!.getAttribute('aria-label')).toBe('Next drawing')
    // At the oldest drawing the top roller is inert; the bottom rolls.
    expect(back!.getAttribute('aria-disabled')).toBe('true')
    expect(fwd!.getAttribute('aria-disabled')).toBe('false')
    await clickEl(back!)
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()

    // The bottom roller rolls forward to the newer drawing, and
    // the chrome pager — the same section state — agrees.
    await clickEl(fwd!)
    expect(container.querySelector('[data-drawing-id="d2"]')).not.toBeNull()
    expect(
      (container.querySelector('[data-testid="section-forward"]') as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(
      (container.querySelector('[data-testid="section-back"]') as HTMLButtonElement).disabled,
    ).toBe(false)
    expect(roller('roller-forward')!.getAttribute('aria-disabled')).toBe('true')
    expect(roller('roller-back')!.getAttribute('aria-disabled')).toBe('false')

    // The top roller rolls back into the history.
    await clickEl(roller('roller-back')!)
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()

    // The rollers put no text on the sheet.
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open!.querySelectorAll('text')).toHaveLength(0)
  })

  it('a single drawing has no rollers — nothing to page', async () => {
    stubDrawings.current = [DRAWING]
    await render()
    await choose('initiative', 'i1')
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    expect(roller('roller-back')).toBeNull()
    expect(roller('roller-forward')).toBeNull()
  })
})
