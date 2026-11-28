// @vitest-environment jsdom
/**
 * Campaign Board view — jsdom render verification.
 *
 * The board mounts against a stubbed Vision Execution API (the same
 * routes the product uses) and must render the overview from the
 * data under the standing display rule — parents and loose only:
 * initiative grounds stand closed (name + project count) and loose
 * camps stand open; a project's route, the scale key, and the
 * obstacle count derived from the blocked task appear once its
 * ground is opened. Clicking the route must open the focus board
 * with its two speculative plans, the declared mountain (largest
 * recorded effort), and the waypoint for the step. CouncilChat is
 * stubbed — the chat seam itself is covered by its own suite; here
 * only the board's rendering is under test.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'

/** The latest props the board handed CouncilChat — the staging pins
 *  read the conversation context and the staging chip from here. */
const chatProps = vi.hoisted(() => ({
  current: null as null | {
    context?: Record<string, unknown>
    stagedLabel?: string | null
    onStagedClear?: () => void
  },
}))

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: {
      context?: Record<string, unknown>
      stagedLabel?: string | null
      onStagedClear?: () => void
    }) => {
      chatProps.current = props
      // The stub renders the chat seam's staging chip to
      // CouncilChat's contract (the real component is pinned by
      // its own suite): the staged thing's name inside the chat,
      // with its dismissal, while it stands staged.
      return ReactMod.createElement(
        'div',
        { 'data-testid': 'valen-chat' },
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

/** Every fetch the board makes, in order — the write pins read it. */
const fetchLog: { url: string; method: string }[] = []

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
    '/vision-execution/decisions?entity_type=project&limit=500': [],
    ...overrides,
  }
  return vi.fn(async (url: string, options?: { method?: string; body?: string }) => {
    const method = options?.method ?? 'GET'
    fetchLog.push({ url, method })
    if (method === 'PATCH') {
      const body = JSON.parse(options?.body ?? '{}') as { due_date?: string }
      const task = TASKS.find((t) => url.endsWith(`/${t.id}`))
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
    fetchLog.length = 0
    chatProps.current = null
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

  /** Tap an initiative's ground open. */
  async function openGround(id: string) {
    const rect = container.querySelector(`[data-initiative-ground="${id}"]`)
    expect(rect, `ground ${id}`).toBeTruthy()
    await act(async () => {
      rect!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
  }

  /** The first lane tap target (route rows — not a ground). */
  function routeHit(): Element {
    const hit = [...container.querySelectorAll('svg rect')].find(
      (r) => r.getAttribute('fill-opacity') === '0' && !r.hasAttribute('data-initiative-ground'),
    )
    expect(hit).toBeTruthy()
    return hit!
  }

  async function clickRoute() {
    await act(async () => {
      routeHit().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
  }

  it('renders the overview from VE data, then the focus board on click', async () => {
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()

    // Parents + loose only: the initiative's ground stands closed
    // — its name and count, but NOT its project.
    expect(container.textContent).toContain('SPRING LINE')
    expect(container.textContent).toContain('1 project')
    expect(container.textContent).not.toContain('Spring collection launch')
    expect(container.textContent).toContain('= 1 day')
    expect(container.querySelector('[data-testid="valen-chat"]')).not.toBeNull()

    // Open the ground: the project, its window, the obstacle count.
    await openGround('i1')
    expect(container.textContent).toContain('Spring collection launch')
    expect(container.textContent).toContain('◆ ×1')

    // Click the project's route row → focus board.
    await clickRoute()

    expect(container.textContent).toContain('Plan A · by date')
    expect(container.textContent).toContain('Plan B · dependencies first')
    expect(container.textContent).toContain('Confirm the print run')
    // 28 recorded hours = 3.5 workdays massed in one step → The Mountain.
    expect(container.textContent).toContain('The Mountain · 3.5d')
    expect(container.textContent).toContain('Confirmed blockage')
    expect(container.textContent).toContain('← All projects')
  })

  it('the scale key is a toggle: day, then week, then month, then day again — the line is the setting’s period count in dots', async () => {
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()

    const keyGroup = () => container.querySelector('[data-testid="scale-key"]')
    const keyTap = () => keyGroup()!.querySelector('rect')!
    const keyLines = () =>
      [...keyGroup()!.querySelectorAll('line')].filter((l) => l.getAttribute('stroke-dasharray') === '0.1 8')
    const keyLen = () =>
      keyLines().reduce((sum, l) => sum + Math.abs(Number(l.getAttribute('x2')) - Number(l.getAttribute('x1'))), 0)

    // Standing look: one dotted line of three periods — three
    // periods make a day (founder, 2026-11-27). The key's dots
    // stand at the key's fixed pitch, 8.1.
    expect(container.textContent).toContain('[-----] = 1 day')
    const dayLen = keyLen()
    expect(dayLen).toBeCloseTo(3 * 8.1, 5)
    expect(keyLines()).toHaveLength(1)

    // Tap → a week: five periods.
    await act(async () => {
      keyTap().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).toContain('[-----] = 1 week')
    expect(container.textContent).not.toContain('[-----] = 1 day')
    expect(keyLines()).toHaveLength(1)
    expect(keyLen()).toBeCloseTo(5 * 8.1, 5)

    // Tap → a month: seven periods — never thirty.
    await act(async () => {
      keyTap().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).toContain('[-----] = 1 month')
    expect(keyLines()).toHaveLength(1)
    expect(keyLen()).toBeCloseTo(7 * 8.1, 5)

    // Tap → back to a day.
    await act(async () => {
      keyTap().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).toContain('[-----] = 1 day')
    expect(keyLen()).toBeCloseTo(dayLen, 5)
  })

  it('draws the linked blocker signal + overcapacity; declarations render from the record, never from surface forms', async () => {
    const decisions = [
      {
        id: 'dec-hold-1', entity_type: 'project', entity_id: 'p1',
        decision_type: 'hold_placed',
        final_values_snapshot: { at: isoDaysFromNow(5) },
        created_at: '2026-05-02T00:00:00Z',
      },
      {
        id: 'dec-river-1', entity_type: 'project', entity_id: 'p1',
        decision_type: 'river_declaration',
        final_values_snapshot: { start: isoDaysFromNow(-2), end: isoDaysFromNow(3) },
        created_at: '2026-05-01T00:00:00Z',
      },
    ]
    vi.stubGlobal(
      'fetch',
      stubFetch({
        '/vision-execution/projects': [{ ...PROJECT, owner_id: 'per1', estimated_weekly_hours: 14 }],
        '/vision-execution/persons': [PERSON],
        '/vision-execution/capacity-profiles': [
          { person_id: 'per1', weekly_capacity_hours: 10, created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00' },
        ],
        '/vision-execution/signals?status_not=resolved,dismissed': [SIGNAL],
        '/vision-execution/decisions?entity_type=project&limit=500': decisions,
      }),
    )
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()

    // Overview → open the ground → focus via the route row's hit rect.
    await openGround('i1')
    await clickRoute()

    // The signal stands on the map as reported material, never confirmed.
    expect(container.textContent).toContain('Reported blocker')
    expect(container.textContent).toContain('Venue closed for repair')
    expect(container.textContent).not.toContain('Confirmed blockage — Venue')

    // The capacity picture is drawn: Pat is committed 14h against 10h — over.
    expect(container.textContent).toContain('Pat · 14/10h')
    expect(container.textContent).toContain('over')

    // The recorded declarations stand on the board from load: the
    // River band and the Hold, folded from the decision records.
    expect(container.textContent).toContain('The River')
    expect(container.textContent).toContain('Hold')

    // Tapping the signal stages it tentatively — and summons NO
    // card: no standing prose, no detail text, no declare form.
    // Explanation is Valen's, in the chat.
    const marker = [...container.querySelectorAll('g')].find((g) =>
      g.textContent?.includes('Venue closed for repair'),
    )
    expect(marker).toBeTruthy()
    await act(async () => {
      marker!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).not.toContain('standing: reported')
    expect(container.textContent).not.toContain('The hall is shut until the roof is fixed.')
    expect(container.textContent).not.toContain('Declare a River')
    // The tap wrote nothing.
    expect(fetchLog.filter((f) => f.method !== 'GET')).toHaveLength(0)
    // The staged signal SHOWS in the chat, under its recorded title.
    expect(chatProps.current?.stagedLabel).toBe('Venue closed for repairs')
    expect(
      container.querySelector('[data-testid="staged-chip"]')!.textContent,
    ).toContain('Venue closed for repairs')

    // Tapping the River stages it under the board's own name for it.
    const river = [...container.querySelectorAll('g')].find(
      (g) => g.textContent?.trim() === 'The River',
    )
    expect(river).toBeTruthy()
    await act(async () => {
      river!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(chatProps.current?.stagedLabel).toBe('The River')

    // Tapping the Hold stages it as a Hold and its day.
    const hold = [...container.querySelectorAll('g')].find((g) =>
      (g.textContent ?? '').startsWith('Hold'),
    )
    expect(hold).toBeTruthy()
    await act(async () => {
      hold!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(chatProps.current?.stagedLabel).toMatch(/^Hold · /)
    expect(fetchLog.filter((f) => f.method !== 'GET')).toHaveLength(0)

    // No declaration forms or header declaration controls exist.
    for (const banned of ['＋ River', '＋ Hold', 'Set window', 'Withdraw declaration', 'Remove hold', 'Set date']) {
      expect(container.textContent).not.toContain(banned)
    }
    expect(
      [...container.querySelectorAll('button')].some((b) => b.textContent?.includes('River')),
    ).toBe(false)
  })

  it('a waypoint drag reschedules and stages nothing; a tap stages tentatively and writes nothing', async () => {
    // jsdom has no pointer capture; the board's handlers call it.
    ;(Element.prototype as unknown as { setPointerCapture: () => void }).setPointerCapture = () => {}
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()
    await openGround('i1')
    await clickRoute()

    const waypoint = () =>
      [...container.querySelectorAll('g')].find((g) =>
        g.textContent?.includes('Confirm the print run'),
      )
    expect(waypoint()).toBeTruthy()
    const pointer = (type: string, clientX: number) =>
      new MouseEvent(type, { bubbles: true, clientX })

    // DRAG: press, move well past the threshold, release. The due
    // date PATCH fires; the conversation context still names the
    // PROJECT — nothing was staged, no card summoned. Each event
    // dispatches in its own act so drag state settles between them.
    const g1 = waypoint()!
    await act(async () => { g1.dispatchEvent(pointer('pointerdown', 100)) })
    await act(async () => { g1.dispatchEvent(pointer('pointermove', 320)) })
    await act(async () => { g1.dispatchEvent(pointer('pointerup', 320)) })
    await flush()
    const patches = fetchLog.filter((f) => f.method === 'PATCH')
    expect(patches).toHaveLength(1)
    expect(patches[0].url).toContain('/vision-execution/tasks/t1')
    expect(chatProps.current?.context).toMatchObject({ entity_type: 'project', entity_id: 'p1' })
    // A drag stages nothing: no chip stands in the chat either.
    expect(chatProps.current?.stagedLabel).toBeNull()
    expect(container.querySelector('[data-testid="staged-chip"]')).toBeNull()

    // TAP: press and release without moving. The waypoint stages —
    // the context now names the TASK — and the fetch log gains no
    // write of any kind.
    fetchLog.length = 0
    const g2 = waypoint()!
    await act(async () => { g2.dispatchEvent(pointer('pointerdown', 100)) })
    await act(async () => { g2.dispatchEvent(pointer('pointerup', 100)) })
    await flush()
    expect(chatProps.current?.context).toMatchObject({ entity_type: 'task', entity_id: 't1' })
    expect(fetchLog.filter((f) => f.method !== 'GET')).toHaveLength(0)
    // The staging SHOWS in the chat: the chip stands inside the
    // chat pane carrying the record's own title.
    expect(chatProps.current?.stagedLabel).toBe('Confirm the print run')
    const chip = container.querySelector('[data-testid="valen-chat"] [data-testid="staged-chip"]')
    expect(chip).not.toBeNull()
    expect(chip!.textContent).toContain('Confirm the print run')

    // Setting it down FROM THE CHAT clears the staging exactly as
    // clearing it in the view does: context back to the project,
    // chip gone, still no writes.
    const clear = container.querySelector('[data-testid="staged-chip-clear"]')
    expect(clear).not.toBeNull()
    await act(async () => { (clear as HTMLElement).click() })
    await flush()
    expect(chatProps.current?.context).toMatchObject({ entity_type: 'project', entity_id: 'p1' })
    expect(chatProps.current?.stagedLabel).toBeNull()
    expect(container.querySelector('[data-testid="staged-chip"]')).toBeNull()
    expect(fetchLog.filter((f) => f.method !== 'GET')).toHaveLength(0)
  })

  it('board sources carry no session-local declaration state, no popup forms, no project-date write', () => {
    // (jsdom env: import.meta.url is not a file URL here, so the
    // sources are read relative to the frontend root vitest runs in.)
    const view = readFileSync('src/campaign-board/CampaignBoardView.tsx', 'utf8')
    const logic = readFileSync('src/campaign-board/boardLogic.ts', 'utf8')
    const api = readFileSync('src/campaign-board/boardApi.ts', 'utf8')
    for (const banned of [
      'FocusPopup',
      'createRiverFromSignal',
      'createRiverWindow',
      'createHold',
      'setRiverWindow',
      'withdrawRiver',
      'moveHold',
      'removeHold',
      'useState<RiverDeclaration',
      'useState<HoldDeclaration',
      'patchProjectDates',
      'session-local',
    ]) {
      expect(view + logic + api, banned).not.toContain(banned)
    }
  })

  it('renders ONE shared map with projects nested under their initiatives, undated projects unspanned', async () => {
    // Shaped like the founder's real board: several initiatives with
    // nested projects, one unanchored project, most projects undated,
    // one dated.
    const base = {
      brief: '', owner_id: null, supporting_owner_ids: [], priority: '',
      start_date: null, end_date: null, estimated_weekly_hours: null,
      next_step_ai: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const tbase = {
      parent_task_id: null, description: '', assignee_id: null, priority: '',
      estimated_hours: null, due_date: null, dependency_ids: [],
      completion_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const projects = [
      { ...base, id: 'pb', initiative_id: 'i1', title: 'Meet the Bear', status: 'Ready' },
      { ...base, id: 'pc', initiative_id: 'i1', title: 'Meet the Crane', status: 'Ready' },
      { ...base, id: 'pd', initiative_id: 'i2', title: 'Ship the thing', status: 'Active', start_date: isoDaysFromNow(-5), end_date: isoDaysFromNow(7) },
      { ...base, id: 'pu', initiative_id: null, title: 'Fix the gate latch', status: 'Draft' },
    ]
    const tasks = [
      { ...tbase, id: 'b1', project_id: 'pb', title: 'Bear step one', status: 'Blocked' },
      { ...tbase, id: 'b2', project_id: 'pb', title: 'Bear step two', status: 'Blocked' },
      { ...tbase, id: 'b3', project_id: 'pb', title: 'Bear step three', status: 'Todo' },
      { ...tbase, id: 'b4', project_id: 'pb', title: 'Bear step done', status: 'Done' },
      { ...tbase, id: 'c1', project_id: 'pc', title: 'Crane step', status: 'Todo' },
      { ...tbase, id: 'd1', project_id: 'pd', title: 'Ship step', status: 'Todo', due_date: isoDaysFromNow(3) },
    ]
    vi.stubGlobal(
      'fetch',
      stubFetch({
        '/vision-execution/initiatives': [
          { id: 'i1', title: 'Council fellowship' },
          { id: 'i2', title: 'Zenaf core' },
        ],
        '/vision-execution/projects': projects,
        '/vision-execution/tasks': tasks,
      }),
    )
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()

    // ONE map surface — not a stack of per-project rows.
    expect(container.querySelectorAll('svg')).toHaveLength(1)
    let text = container.textContent ?? ''

    // Parents + loose only by default: both initiatives lettered
    // on their grounds with their counts; the loose project's camp
    // stands; NO initiative-owned project is on the map yet.
    const idx0 = (s: string) => text.indexOf(s)
    expect(idx0('ZENAF CORE')).toBeGreaterThanOrEqual(0)
    expect(idx0('COUNCIL FELLOWSHIP')).toBeGreaterThanOrEqual(0)
    expect(idx0('ZENAF CORE')).toBeLessThan(idx0('COUNCIL FELLOWSHIP'))
    expect(idx0('COUNCIL FELLOWSHIP')).toBeLessThan(idx0('Fix the gate latch'))
    expect(text).toContain('1 project')
    expect(text).toContain('2 projects')
    expect(text).not.toContain('Ship the thing')
    expect(text).not.toContain('Meet the Bear')
    expect(text).not.toContain('Meet the Crane')
    // No routes are drawn while the grounds are closed.
    expect(container.querySelectorAll('[data-testid="route-line"]')).toHaveLength(0)

    // Open the Zenaf core ground: its dated project stands as a
    // route counted in periods (founder, 2026-11-27). At the
    // day setting three periods make a day, so the 12-day span
    // is 36 periods; the shared dot pitch is the key's 8.1 (the
    // fit cap, 326/36 ≈ 9.1, does not bind).
    await openGround('i2')
    text = container.textContent ?? ''
    const idx = (s: string) => text.indexOf(s)
    expect(idx('ZENAF CORE')).toBeLessThan(idx('Ship the thing'))
    expect(idx('Ship the thing')).toBeLessThan(idx('COUNCIL FELLOWSHIP'))
    expect(text).not.toContain('Meet the Bear')
    const routeLines = [...container.querySelectorAll('[data-testid="route-line"]')]
    expect(routeLines).toHaveLength(1)
    const routeLen = () =>
      Number(routeLines[0].getAttribute('x2')) - Number(routeLines[0].getAttribute('x1'))
    expect(routeLen()).toBeCloseTo(36 * 8.1, 5)
    // Toggling the key re-divides the route: at the week
    // setting (five periods to a week) the same span is 9
    // periods and the timeline pulls in; at the month setting
    // (seven to a month) it is 3 periods; the next tap
    // restores the day and the timeline stretches back out.
    const keyTap = () => container.querySelector('[data-testid="scale-key"] rect')!
    const pitch = () => {
      const d = routeLines[0].getAttribute('stroke-dasharray')!.split(' ').map(Number)
      return d[0] + d[1]
    }
    expect(pitch()).toBeCloseTo(8.1, 5)
    await act(async () => {
      keyTap().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).toContain('[-----] = 1 week')
    expect(routeLen()).toBeCloseTo(9 * 8.1, 5)
    await act(async () => {
      keyTap().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).toContain('[-----] = 1 month')
    expect(routeLen()).toBeCloseTo(3 * 8.1, 5)
    await act(async () => {
      keyTap().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).toContain('[-----] = 1 day')
    expect(routeLen()).toBeCloseTo(36 * 8.1, 5)

    // Open the fellowship's ground instead (one ground open at a
    // time): the Ready pair stands at their camps, undated and
    // unspanned — no route line at all — and the core's project
    // is hidden again.
    await openGround('i1')
    text = container.textContent ?? ''
    expect(idx('COUNCIL FELLOWSHIP')).toBeLessThan(idx('Meet the Bear'))
    expect(idx('Meet the Bear')).toBeLessThan(idx('Meet the Crane'))
    expect(idx('Meet the Crane')).toBeLessThan(idx('Fix the gate latch'))
    expect(text).not.toContain('Ship the thing')
    expect(container.querySelectorAll('[data-testid="route-line"]')).toHaveLength(0)

    // The undated fact is never printed on the surface.
    expect(text).not.toContain('No dates recorded')
    expect(text).not.toContain('no dates recorded')

    // Obstacle ticks still counted on the map; scale key present.
    expect(text).toContain('◆ ×2')
    expect(text).toContain('= 1 day')

    // The camp popup carries the undated fact. Camps are the r=15
    // invisible circles, in lane order: Bear, Crane, latch.
    const camps = [...container.querySelectorAll('circle')].filter(
      (c) => c.getAttribute('fill-opacity') === '0' && c.getAttribute('r') === '15',
    )
    expect(camps).toHaveLength(3)
    await act(async () => {
      camps[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(container.textContent).toContain('No dates recorded')
    expect(container.textContent).toContain('Ready · 3 open · 1 done')

    // The popup's Focus row opens the focus board.
    const focusRow = [...container.querySelectorAll('g')].find((g) => g.textContent === 'Focus →')
    expect(focusRow).toBeTruthy()
    await act(async () => {
      focusRow!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).toContain('← All projects')
    expect(container.textContent).toContain('Meet the Bear')
  })

  it('an undated project wears a red !; tapping it stages Valen’s provisional-timeframe ask in the chat', async () => {
    const base = {
      brief: '', owner_id: null, supporting_owner_ids: [], priority: '',
      start_date: null, end_date: null, estimated_weekly_hours: null,
      next_step_ai: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const projects = [
      { ...base, id: 'pb', initiative_id: 'i1', title: 'Meet the Bear', status: 'Ready' },
      { ...base, id: 'pc', initiative_id: 'i1', title: 'Meet the Crane', status: 'Ready' },
      { ...base, id: 'pd', initiative_id: 'i2', title: 'Ship the thing', status: 'Active', start_date: isoDaysFromNow(-5), end_date: isoDaysFromNow(7) },
      { ...base, id: 'pu', initiative_id: null, title: 'Fix the gate latch', status: 'Draft' },
    ]
    vi.stubGlobal(
      'fetch',
      stubFetch({
        '/vision-execution/initiatives': [
          { id: 'i1', title: 'Council fellowship' },
          { id: 'i2', title: 'Zenaf core' },
        ],
        '/vision-execution/projects': projects,
        '/vision-execution/tasks': [],
      }),
    )
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()

    const bangs = () => [...container.querySelectorAll('[data-testid="no-timeframe-bang"]')]
    // Only the loose undated project's lane stands while the
    // grounds are closed: one bang.
    expect(bangs()).toHaveLength(1)

    // Open the fellowship ground: both undated projects join —
    // three bangs. The dated project (ground still closed)
    // wears none.
    const ground = container.querySelector('[data-initiative-ground="i1"]')!
    await act(async () => {
      ground.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(bangs()).toHaveLength(3)
    const bangText = bangs()[0].querySelector('text')!
    expect(bangText.textContent).toBe('!')
    expect(bangText.getAttribute('fill')).toBe('#b3261e')

    // Tap the Bear's bang: the board stays on the overview, and
    // the project stages in the chat — its name on the chip,
    // the conversation grounded on the project under the
    // provisional-timeframe intent.
    await act(async () => {
      bangs()[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
    expect(container.textContent).not.toContain('← All projects')
    expect(chatProps.current?.stagedLabel).toBe('Meet the Bear — no timeframe yet')
    expect(chatProps.current?.context).toMatchObject({
      sheet_type: 'campaign_board',
      entity_type: 'project',
      entity_id: 'pb',
      intent: 'provisional_timeframe',
    })
  })

  it('a project lane is a painted scene: stronghold and camp at its start, its terrain and obstacles along the route, the banner at its finish', async () => {
    const base = {
      brief: '', owner_id: null, supporting_owner_ids: [], priority: '',
      start_date: null, end_date: null, estimated_weekly_hours: null,
      next_step_ai: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const tbase = {
      parent_task_id: null, description: '', assignee_id: null, priority: '',
      estimated_hours: null, due_date: null, dependency_ids: [],
      completion_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const projects = [
      { ...base, id: 'px', initiative_id: 'i1', title: 'Storm the pass', status: 'Active', start_date: isoDaysFromNow(-5), end_date: isoDaysFromNow(7) },
      { ...base, id: 'py', initiative_id: 'i1', title: 'Untimed errand', status: 'Ready' },
    ]
    const tasks = [
      // 24 recorded hours = 3 workdays in one step: The Mountain.
      { ...tbase, id: 'x1', project_id: 'px', title: 'The big push', status: 'Todo', estimated_hours: 24 },
      // A parent with three children: The Grove.
      { ...tbase, id: 'x2', project_id: 'px', title: 'Branch work', status: 'Todo' },
      { ...tbase, id: 'x3', project_id: 'px', title: 'Branch one', status: 'Todo', parent_task_id: 'x2' },
      { ...tbase, id: 'x4', project_id: 'px', title: 'Branch two', status: 'Todo', parent_task_id: 'x2' },
      { ...tbase, id: 'x5', project_id: 'px', title: 'Branch three', status: 'Todo', parent_task_id: 'x2' },
      // A blocked step: an obstacle on the route.
      { ...tbase, id: 'x6', project_id: 'px', title: 'Stuck step', status: 'Blocked' },
    ]
    vi.stubGlobal(
      'fetch',
      stubFetch({
        '/vision-execution/initiatives': [{ id: 'i1', title: 'Council fellowship' }],
        '/vision-execution/projects': projects,
        '/vision-execution/tasks': tasks,
      }),
    )
    await act(async () => {
      root.render(React.createElement(CampaignBoardView))
    })
    await flush()
    await flush()

    const ground = container.querySelector('[data-initiative-ground="i1"]')!
    await act(async () => {
      ground.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()

    const sprites = [...container.querySelectorAll('[data-testid="lane-sprite"]')].map((s) =>
      s.getAttribute('data-sprite'),
    )
    // Both projects stand as strongholds with their camps; only
    // the dated one's route is painted — its mountain, its
    // grove, its obstacle crag, and the finish banner.
    expect(sprites.filter((s) => s === 'stronghold')).toHaveLength(2)
    expect(sprites.filter((s) => s === 'camp')).toHaveLength(2)
    expect(sprites.filter((s) => s === 'finish-banner')).toHaveLength(1)
    expect(sprites).toContain('mountain')
    expect(sprites).toContain('grove')
    expect(sprites).toContain('obstacle-crag')
    expect(container.querySelectorAll('[data-testid="route-line"]')).toHaveLength(1)
  })
})
