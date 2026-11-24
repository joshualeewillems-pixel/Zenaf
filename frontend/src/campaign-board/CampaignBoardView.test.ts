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

function stubFetch() {
  const data: Record<string, unknown> = {
    '/vision-execution/ideas': [],
    '/vision-execution/initiatives': [{ id: 'i1', title: 'Spring line' }],
    '/vision-execution/projects': [PROJECT],
    '/vision-execution/tasks': TASKS,
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
})
