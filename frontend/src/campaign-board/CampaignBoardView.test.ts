// @vitest-environment jsdom
/**
 * Campaign Board view — jsdom render verification.
 *
 * The board mounts against a stubbed Vision Execution API (the same
 * routes the product uses) and must render the overview from the data:
 * the project as a route, the scale key on the map, and the obstacle
 * count derived from the blocked task. Clicking the route must open
 * the focus board with its two speculative plans, the declared
 * mountain (largest recorded effort), and the waypoint for the step.
 * CouncilChat is stubbed — the chat seam itself is covered by its own
 * suite; here only the board's rendering is under test.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: () => ReactMod.createElement('div', { 'data-testid': 'valen-chat' }),
  }
})

import CampaignBoardView from './CampaignBoardView'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function isoDaysFromNow(days: number): string {
  const d = new Date(Date.now() + days * 86_400_000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

const PROJECT = {
  id: 'p1',
  initiative_id: 'i1',
  title: 'Spring collection launch',
  brief: '',
  status: 'Active',
  owner_id: null,
  supporting_owner_ids: [],
  priority: '',
  start_date: isoDaysFromNow(-10),
  end_date: isoDaysFromNow(20),
  estimated_weekly_hours: null,
  next_step_ai: '',
  notes: '',
  created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
}

const TASKS = [
  {
    id: 't1', project_id: 'p1', parent_task_id: null, title: 'Confirm the print run',
    description: '', assignee_id: null, status: 'Todo', priority: '',
    estimated_hours: 28, due_date: isoDaysFromNow(15), dependency_ids: [],
    completion_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
  },
  {
    id: 't2', project_id: 'p1', parent_task_id: null, title: 'Book the photographer',
    description: '', assignee_id: null, status: 'Blocked', priority: '',
    estimated_hours: 4, due_date: isoDaysFromNow(5), dependency_ids: [],
    completion_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
  },
]

function stubFetch(overrides: Record<string, unknown> = {}) {
  const data: Record<string, unknown> = {
    '/vision-execution/ideas': [],
    '/vision-execution/initiatives': [{ id: 'i1', title: 'Spring line' }],
    '/vision-execution/projects': [PROJECT],
    '/vision-execution/tasks': TASKS,
    '/vision-execution/persons': [],
    '/vision-execution/assets': [],
    '/vision-execution/signals?status_not=resolved,dismissed': [],
    '/vision-execution/capacity-profiles': [],
    ...overrides,
  }
  return vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => data[url] ?? [],
    text: async () => '',
  }))
}

const PERSON = {
  id: 'per1', name: 'Pat Printer', role: '', relationship_type: '', contact_info: '',
  strengths: '', needs: '', wants: '', availability: '', notes: '',
  created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
}

const SIGNAL = {
  id: 's1', kind: 'blocker', title: 'Venue closed for repairs',
  detail: 'The hall is shut until the roof is fixed.', source: 'meeting extraction',
  source_excerpt: 'venue is closed for repairs', confidence: null,
  linked_initiative_id: null, linked_project_id: 'p1', linked_task_id: null,
  status: 'new', created_at: `${isoDaysFromNow(2)}T09:00:00`,
}

describe('CampaignBoardView', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
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

  it('renders the overview from VE data, then the focus board on click', async () => {
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()

    // Overview: the project, its window, the scale key, the obstacle count.
    expect(container.textContent).toContain('Spring collection launch')
    expect(container.textContent).toContain('= 1 day')
    expect(container.textContent).toContain('◆ ×1')
    expect(container.querySelector('[data-testid="valen-chat"]')).not.toBeNull()

    // Click the project's route row → focus board.
    const rects = [...container.querySelectorAll('svg rect')]
    const hit = rects.find((r) => r.getAttribute('fill-opacity') === '0')
    expect(hit).toBeTruthy()
    await act(async () => {
      hit!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()

    expect(container.textContent).toContain('Plan A · by date')
    expect(container.textContent).toContain('Plan B · dependencies first')
    expect(container.textContent).toContain('Confirm the print run')
    // 28 recorded hours = 3.5 workdays massed in one step → The Mountain.
    expect(container.textContent).toContain('The Mountain · 3.5d')
    expect(container.textContent).toContain('Confirmed blockage')
    expect(container.textContent).toContain('← All projects')
  })

  it('draws the linked blocker signal + overcapacity, and declares River and Hold from the map', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch({
        '/vision-execution/projects': [{ ...PROJECT, owner_id: 'per1', estimated_weekly_hours: 14 }],
        '/vision-execution/persons': [PERSON],
        '/vision-execution/capacity-profiles': [
          { person_id: 'per1', weekly_capacity_hours: 10, created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
        ],
        '/vision-execution/signals?status_not=resolved,dismissed': [SIGNAL],
      }),
    )
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()

    // Overview → focus via the route row's hit rect.
    const rects = [...container.querySelectorAll('svg rect')]
    const hit = rects.find((r) => r.getAttribute('fill-opacity') === '0')
    expect(hit).toBeTruthy()
    await act(async () => {
      hit!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()

    // The signal stands on the map as reported material, never confirmed.
    expect(container.textContent).toContain('Reported blocker')
    expect(container.textContent).toContain('Venue closed for repair')
    expect(container.textContent).not.toContain('Confirmed blockage — Venue')

    // The capacity picture is drawn: Pat is committed 14h against 10h — over.
    expect(container.textContent).toContain('Pat · 14/10h')
    expect(container.textContent).toContain('over')

    // Open the signal: standing is reported, and the River can be declared from it.
    const marker = [...container.querySelectorAll('g')].find((g) =>
      g.textContent?.includes('Venue closed for repair'),
    )
    expect(marker).toBeTruthy()
    await act(async () => {
      marker!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(container.textContent).toContain('standing: reported')
    expect(container.textContent).toContain('The hall is shut until the roof is fixed.')
    const declareBtn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Declare a River'),
    )
    expect(declareBtn).toBeTruthy()
    await act(async () => {
      declareBtn!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    // The declared River crosses the map and its popup names its source.
    expect(container.textContent).toContain('The River')
    expect(container.textContent).toContain('Declared from signal: “Venue closed for repairs”')

    // Withdrawing the declaration removes the River.
    const withdrawBtn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Withdraw declaration'),
    )
    expect(withdrawBtn).toBeTruthy()
    await act(async () => {
      withdrawBtn!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(container.textContent).not.toContain('The River')

    // Place a Hold from the header control: it renders on the line and
    // its popup names it as user-placed.
    const holdBtn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('＋ Hold'),
    )
    expect(holdBtn).toBeTruthy()
    await act(async () => {
      holdBtn!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(container.textContent).toContain('placed by you')
    const removeBtn = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('Remove hold'),
    )
    expect(removeBtn).toBeTruthy()
  })
})
