// @vitest-environment jsdom
/**
 * Campaign Board — drag stability (founder report 2026-11-25:
 * "you move something and everything else goes all over the place").
 *
 * The contract these tests pin: during a waypoint drag the world
 * holds still — every non-dragged node's rendered position (dot AND
 * label), the header date range, and the timeline strip are
 * byte-identical from pointer-down to pointer-up; only the dragged
 * node follows the pointer, against the frozen pre-drag scale; no
 * write fires mid-drag. On release, exactly one commit fires, for
 * the dragged task only, and the board re-derives exactly as a
 * fresh render of the updated record does (today's semantics).
 *
 * The fixture is shaped like the founder's Tier 0 board: the
 * project carries no dates of its own, so the span is recovered
 * from the tasks' due dates — the extent itself is a function of
 * the dates being dragged.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import {
  dateAtFraction,
  fullDate,
  projectSpan,
  shortDate,
  toLocalDateTimeString,
} from './boardLogic'

const chatProps = vi.hoisted(() => ({
  current: null as null | { context?: Record<string, unknown> },
}))

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: { context?: Record<string, unknown> }) => {
      chatProps.current = props
      return ReactMod.createElement('div', { 'data-testid': 'valen-chat' })
    },
  }
})

const fetchLog: { url: string; method: string; body?: string }[] = []

import CampaignBoardView from './CampaignBoardView'

/** The board door: warm by default in this suite (the gate
 *  itself is pinned in CampaignBoardView.test.ts). */
vi.mock('./boardPreload', () => ({
  BOARD_ASSET_URLS: [] as string[],
  boardPreloader: {
    urls: [] as string[],
    preload: () => Promise.resolve(),
    ready: () => true,
  },
}))


;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function isoDaysFromNow(days: number): string {
  const d = new Date(Date.now() + days * 86_400_000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

const PROJECT = {
  id: 'p1',
  initiative_id: 'i1',
  title: 'Tier zero project',
  brief: '',
  status: 'Active',
  owner_id: null,
  supporting_owner_ids: [],
  priority: '',
  start_date: null,
  end_date: null,
  estimated_weekly_hours: null,
  next_step_ai: '',
  notes: '',
  created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
}

const TASK_BASE = {
  project_id: 'p1',
  parent_task_id: null,
  description: '',
  assignee_id: null,
  status: 'Todo',
  priority: '',
  estimated_hours: 2,
  dependency_ids: [] as string[],
  completion_criteria: '',
  notes: '',
  created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
}

const TITLES = ['Alpha step', 'Bravo step', 'Charlie step', 'Delta step']

function makeTasks(alphaDue: string) {
  return [
    { ...TASK_BASE, id: 'tA', title: 'Alpha step', due_date: alphaDue },
    { ...TASK_BASE, id: 'tB', title: 'Bravo step', due_date: isoDaysFromNow(12) },
    { ...TASK_BASE, id: 'tC', title: 'Charlie step', due_date: isoDaysFromNow(14) },
    { ...TASK_BASE, id: 'tD', title: 'Delta step', due_date: isoDaysFromNow(16) },
  ]
}

function stubFetch(tasks: ReturnType<typeof makeTasks>) {
  const data: Record<string, unknown> = {
    '/vision-execution/ideas': [],
    '/vision-execution/initiatives': [{ id: 'i1', title: 'Spring line' }],
    '/vision-execution/projects': [PROJECT],
    '/vision-execution/tasks': tasks,
    '/vision-execution/persons': [],
    '/vision-execution/assets': [],
    '/vision-execution/signals?status_not=resolved,dismissed': [],
    '/vision-execution/capacity-profiles': [],
    '/vision-execution/decisions?entity_type=project&limit=500': [],
  }
  return vi.fn(async (url: string, options?: { method?: string; body?: string }) => {
    const method = options?.method ?? 'GET'
    fetchLog.push({ url, method, body: options?.body })
    if (method === 'PATCH') {
      const body = JSON.parse(options?.body ?? '{}') as { due_date?: string }
      const task = tasks.find((t) => url.endsWith(`/${t.id}`))
      return {
        ok: true,
        status: 200,
        json: async () => ({ ...task, due_date: body.due_date }),
        text: async () => '',
      }
    }
    return {
      ok: true,
      status: 200,
      json: async () => data[url] ?? [],
      text: async () => '',
    }
  })
}

/* Board geometry (CampaignBoardView): x = 64 + fraction · 672. */
const clientXForFraction = (f: number) => 64 + f * 672

interface BoardSnapshot {
  /** Per waypoint group (DOM order): transform + child text geometry. */
  waypoints: { transform: string | null; texts: (string | null)[] }[]
  header: string
  strip: string
}

describe('CampaignBoardView — drag stability', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    fetchLog.length = 0
    chatProps.current = null
    ;(Element.prototype as unknown as { setPointerCapture: () => void }).setPointerCapture =
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

  async function flush() {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
  }

  async function renderBoard(tasks: ReturnType<typeof makeTasks>) {
    vi.stubGlobal('fetch', stubFetch(tasks))
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()
    const ground = container.querySelector('[data-initiative-ground="i1"]')
    expect(ground).toBeTruthy()
    await act(async () => {
      ground!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    const hit = [...container.querySelectorAll('svg rect')].find(
      (r) => r.getAttribute('fill-opacity') === '0' && !r.hasAttribute('data-initiative-ground'),
    )
    expect(hit).toBeTruthy()
    await act(async () => {
      hit!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    // jsdom measures nothing; give the focus svg a real box so
    // pointer clientX maps onto board coordinates 1:1.
    const svg = [...container.querySelectorAll('svg')].find(
      (s) => s.getAttribute('viewBox') === '0 0 800 500',
    )
    expect(svg).toBeTruthy()
    ;(svg as SVGSVGElement).getBoundingClientRect = () =>
      ({
        left: 0,
        top: 0,
        width: 800,
        height: 500,
        right: 800,
        bottom: 500,
        x: 0,
        y: 0,
        toJSON: () => {},
      }) as DOMRect
  }

  /** Waypoint groups in DOM order (Plan A copies, then Plan B). */
  function waypointGroups(): Element[] {
    return [...container.querySelectorAll('g')].filter((g) =>
      TITLES.some((t) => g.textContent?.startsWith(t)),
    )
  }

  function snapshot(): BoardSnapshot {
    const waypoints = waypointGroups().map((g) => ({
      transform: g.getAttribute('transform'),
      texts: [...g.querySelectorAll('text')].map(
        (t) => `${t.getAttribute('x')},${t.getAttribute('y')}:${t.textContent}`,
      ),
    }))
    const section = container.querySelector('section')
    const header = section?.querySelector('div')?.textContent ?? ''
    const stripSvg = [...container.querySelectorAll('svg')].find(
      (s) => s.getAttribute('viewBox') === '0 0 800 64',
    )
    return { waypoints, header, strip: stripSvg?.innerHTML ?? '' }
  }

  const pointer = (type: string, clientX: number) =>
    new MouseEvent(type, { bubbles: true, clientX })

  /** Alpha's Plan A group (first of its two copies). */
  function alphaGroup(): Element {
    const g = waypointGroups().find((el) => el.textContent?.startsWith('Alpha step'))
    expect(g).toBeTruthy()
    return g!
  }

  it('during a drag, every non-dragged node, the header range and the ruler are invariant; nothing writes', async () => {
    await renderBoard(makeTasks(isoDaysFromNow(10)))
    const before = snapshot()
    expect(before.waypoints).toHaveLength(8)

    // Press Alpha and sweep it across Bravo and Charlie to
    // fraction 0.75, in steps — no release.
    await act(async () => {
      alphaGroup().dispatchEvent(pointer('pointerdown', clientXForFraction(0.02)))
    })
    for (const f of [0.3, 0.5, 0.75]) {
      await act(async () => {
        alphaGroup().dispatchEvent(pointer('pointermove', clientXForFraction(f)))
      })
      const now = snapshot()
      // Every non-dragged waypoint (both plans) is byte-identical:
      // dot transform and every label text's position and content.
      now.waypoints.forEach((w, i) => {
        const title = TITLES.find((t) => before.waypoints[i].texts.join(' ').includes(t.slice(0, 5)))
        if (title === 'Alpha step') return
        expect(w, `waypoint ${i} moved mid-drag`).toEqual(before.waypoints[i])
      })
      // Header range and the timeline strip are untouched.
      expect(now.header).toBe(before.header)
      expect(now.strip).toBe(before.strip)
      // No write of any kind has fired.
      expect(fetchLog.filter((f2) => f2.method !== 'GET')).toHaveLength(0)
    }

    // The dragged node itself followed the pointer in both plans,
    // and its drag chip reads the provisional date off the FROZEN
    // pre-drag span.
    const after = snapshot()
    const alphaXs = after.waypoints
      .filter((w) => w.texts.join(' ').includes('Alpha'))
      .map((w) => w.transform)
    expect(alphaXs).toHaveLength(2)
    for (const tr of alphaXs) expect(tr).toContain(`translate(${clientXForFraction(0.75)}`)
    const span = projectSpan(PROJECT as never, makeTasks(isoDaysFromNow(10)) as never, Date.now())
    expect(container.textContent).toContain(fullDate(dateAtFraction(span, 0.75)))

    // Release outside this test's concern: no commit assertion here.
    await act(async () => {
      alphaGroup().dispatchEvent(pointer('pointerup', clientXForFraction(0.75)))
    })
  })

  it('a drag crossing other dates re-sorts nothing mid-drag; on release it commits once, for the dragged task only, and the board then matches a fresh render of the new record', async () => {
    const tasks = makeTasks(isoDaysFromNow(10))
    await renderBoard(tasks)
    const span = projectSpan(PROJECT as never, tasks as never, Date.now())

    await act(async () => {
      alphaGroup().dispatchEvent(pointer('pointerdown', clientXForFraction(0.02)))
    })
    // Sweep past Bravo (1/3) and Charlie (2/3) to 0.75.
    for (const f of [0.4, 0.6, 0.75]) {
      await act(async () => {
        alphaGroup().dispatchEvent(pointer('pointermove', clientXForFraction(f)))
      })
    }
    // Mid-drag: no commit, and the strip still lists the recorded
    // order (Alpha's recorded date is still the earliest).
    expect(fetchLog.filter((f2) => f2.method === 'PATCH')).toHaveLength(0)

    await act(async () => {
      alphaGroup().dispatchEvent(pointer('pointerup', clientXForFraction(0.75)))
    })
    await flush()
    await flush()

    // Exactly one write: Alpha's due date, computed against the
    // frozen pre-drag span. Nothing staged in the chat.
    const patches = fetchLog.filter((f2) => f2.method === 'PATCH')
    expect(patches).toHaveLength(1)
    expect(patches[0].url).toContain('/vision-execution/tasks/tA')
    const expectedDue = toLocalDateTimeString(dateAtFraction(span, 0.75))
    expect(JSON.parse(patches[0].body ?? '{}')).toEqual({ due_date: expectedDue })
    expect(chatProps.current?.context).toMatchObject({ entity_type: 'project', entity_id: 'p1' })

    // The extent re-derived at release: Alpha (now day +14.5) no
    // longer bounds the span — Bravo's date does.
    const settled = snapshot()
    expect(settled.header).toContain(
      `${shortDate(new Date(isoDaysFromNow(12)))} – ${shortDate(new Date(isoDaysFromNow(16)))}`,
    )

    // And the settled board is byte-identical to a fresh render of
    // the same record with Alpha's new date — today's semantics,
    // landed once.
    const fresh = makeTasks(expectedDue)
    act(() => root.unmount())
    container.remove()
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    await renderBoard(fresh)
    const freshSnap = snapshot()
    expect(freshSnap.waypoints).toEqual(settled.waypoints)
    expect(freshSnap.header).toBe(settled.header)
    expect(freshSnap.strip).toBe(settled.strip)
  })
})
