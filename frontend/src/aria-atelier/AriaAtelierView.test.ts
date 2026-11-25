// @vitest-environment jsdom
/**
 * Aria's Atelier — jsdom render verification.
 *
 * The view mounts against a stubbed Vision Execution API carrying
 * the same shapes the Vision map reads, and must paint the garden
 * from the data under the standing display rule — parents and
 * loose only: the well, and the INITIATIVE standing in the ring as
 * one cairn of two stones (its project is not in the ring).
 * Opening the initiative fans its projects; opening a project
 * fans its stones; casting — tap-tap, the touch grammar — must
 * load the subject's conversation in Aria's chat (CouncilChat is
 * stubbed and records its props; the chat seam itself is covered by
 * its own suite) at each scope the hierarchy carries: the stone,
 * the whole cairn (project), and the whole undertaking (initiative).
 * The cast view must carry all seven layers as transparent fill/ink
 * image pairs — no paper, no video — at the increased formation
 * scale. The ink is a stage of the voice's true-prefix drawing
 * ladder (stageImages); formations at rest stand complete; and
 * the cast view carries NO manual imagery controls — no
 * Discussion slider, no voice chips (founder, 2026-11-25).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

type ChatProps = {
  conversationId?: string
  context?: Record<string, unknown>
  initialArchetypeId?: string
}
let chatProps: ChatProps[] = []

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: ChatProps) => {
      chatProps.push(props)
      return ReactMod.createElement('div', { 'data-testid': 'aria-chat' })
    },
  }
})

import AriaAtelierView from './AriaAtelierView'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const PROJECT = {
  id: 'p1',
  initiative_id: 'i1',
  title: 'Spring collection launch',
  brief: '',
  status: 'Active',
  owner_id: null,
  supporting_owner_ids: [],
  priority: '',
  start_date: '2026-05-01',
  end_date: '2026-06-01',
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
    estimated_hours: 28, due_date: '2026-05-20', dependency_ids: [],
    completion_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
  },
  {
    id: 't2', project_id: 'p1', parent_task_id: null, title: 'Book the photographer',
    description: '', assignee_id: null, status: 'Blocked', priority: '',
    estimated_hours: 4, due_date: '2026-05-10', dependency_ids: [],
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
    '/vision-execution/strand-weightings': { weightings: [] },
    '/vision-execution/node-vitality': { vitality: [] },
    '/studio/council/recent-runs?limit=80': { items: [] },
  }
  return vi.fn(async (url: string) => {
    if (url.includes('/conversation?')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          messages: [
            { id: 'm1', role: 'user', archetype_id: null, body: 'How does this look?' },
            { id: 'm2', role: 'assistant', archetype_id: 'conductor', body: 'It holds together.' },
            { id: 'm3', role: 'assistant', archetype_id: 'conductor', body: 'One stone is loose.' },
          ],
        }),
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

describe('AriaAtelierView', () => {
  let container: HTMLDivElement
  let root: Root
  let fetchMock: ReturnType<typeof stubFetch>

  beforeEach(() => {
    chatProps = []
    fetchMock = stubFetch()
    vi.stubGlobal('fetch', fetchMock)
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

  async function renderGarden() {
    await act(async () => {
      root.render(React.createElement(AriaAtelierView))
    })
    await flush()
    await flush()
    await flush()
  }

  function tap(el: Element) {
    act(() => {
      el.dispatchEvent(new window.MouseEvent('pointerdown', { bubbles: true, clientX: 10, clientY: 10 }))
      el.dispatchEvent(new window.MouseEvent('pointerup', { bubbles: true, clientX: 10, clientY: 10 }))
    })
  }

  function buttonByLabel(label: string): HTMLButtonElement {
    const btn = [...container.querySelectorAll('button')].find(
      (b) => b.getAttribute('aria-label') === label,
    )
    if (!btn) throw new Error(`button "${label}" not found`)
    return btn as HTMLButtonElement
  }

  function lastChat(): ChatProps {
    return chatProps[chatProps.length - 1]
  }

  /** Cast through the ripple beat (~680ms) into the cast view. */
  async function settleCast() {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 750))
    })
    await flush()
    await flush()
  }

  it('paints the garden from the data: the well, the initiative cairn, and Aria’s garden conversation', async () => {
    await renderGarden()
    expect(container.querySelector('[data-testid="atelier-garden"]')).not.toBeNull()
    expect(container.querySelector('button[aria-label="The well"]')).not.toBeNull()
    // Parents + loose only: the initiative stands in the ring as
    // one cairn carrying both stones; its project does NOT.
    expect(container.querySelector('[data-initiative="i1"]')).not.toBeNull()
    expect(container.textContent).toContain('Spring line')
    expect(container.textContent).toContain('2 stones')
    expect(container.textContent).not.toContain('Spring collection launch')
    expect(container.querySelector('[data-cairn]')).toBeNull()
    expect(container.querySelector('[data-testid="aria-chat"]')).not.toBeNull()
    expect(lastChat().conversationId).toBe('aria-atelier:garden')
    expect(lastChat().context).toEqual({ sheet_type: 'aria_atelier' })
    expect(lastChat().initialArchetypeId).toBe('conductor')
  })

  /** Open the initiative's fan, then the project's fan. */
  async function openProjectFan() {
    tap(buttonByLabel('Spring line'))
    await flush()
    tap(buttonByLabel('Spring collection launch'))
    await flush()
  }

  it('casts a stone: fans, tap-tap, and the subject conversation loads with the seven transparent layers', async () => {
    await renderGarden()
    await openProjectFan()
    const fanStone = buttonByLabel('Confirm the print run — from Spring collection launch')
    tap(fanStone)
    await flush()
    act(() => buttonByLabel('The well').click())
    await settleCast()

    expect(container.querySelector('[data-testid="atelier-cast-circle"]')).not.toBeNull()
    expect(container.textContent).toContain('Confirm the print run')
    // The formation stands at the increased scale in the bowl.
    const stack = container.querySelector('.atelier-layer-stack') as HTMLElement | null
    expect(stack?.style.height).toBe('130%')
    expect(lastChat().conversationId).toBe('aria-atelier:task:t1')
    expect(lastChat().context).toEqual({
      sheet_type: 'aria_atelier',
      entity_type: 'task',
      entity_id: 't1',
    })
    // Seven layers, each a transparent fill under a stage of the
    // voice's drawing ladder — no paper, no video. Every formation
    // but the responder's stands complete (the final stage); Aria
    // is mid-replay on a fresh cast, so her ink is some stage of
    // her ladder, or not yet drawn at all.
    const layers = container.querySelectorAll('[data-layer]')
    expect(layers).toHaveLength(7)
    for (const layer of layers) {
      const voice = layer.getAttribute('data-layer')
      const fill = layer.querySelector('img.fill') as HTMLImageElement
      const ink = layer.querySelector('img.ink') as HTMLImageElement | null
      expect(fill?.src).toContain(`layer-${voice}-fill`)
      if (voice === 'aria') {
        if (ink) expect(ink.src).toMatch(/stage-aria-\d+/)
      } else {
        expect(ink?.src).toContain(`stage-${voice}-12`)
      }
    }
    expect(container.querySelector('video')).toBeNull()
    // No manual imagery controls exist (founder, 2026-11-25):
    // no Discussion slider, no voice chips, nothing to press that
    // sets the imagery.
    expect(container.querySelector('input[type="range"]')).toBeNull()
    expect(container.querySelector('[aria-pressed]')).toBeNull()
    expect(container.textContent).not.toContain('Discussion')
    expect(container.textContent).not.toContain('All seven')
    // The view's data inputs are exactly the fetches it already
    // made — the Atelier data path and the subject conversation
    // read. No new endpoint, no writes.
    const paths = fetchMock.mock.calls.map((c) => {
      const raw = String(c[0])
      return raw.startsWith('http') ? new URL(raw).pathname : raw.split('?')[0]
    })
    const known = new Set([
      '/vision-execution/ideas',
      '/vision-execution/initiatives',
      '/vision-execution/projects',
      '/vision-execution/tasks',
      '/vision-execution/persons',
      '/vision-execution/assets',
      '/vision-execution/strand-weightings',
      '/vision-execution/node-vitality',
      '/studio/council/recent-runs',
      '/conversation',
    ])
    for (const p of paths) expect(known.has(p), `unexpected fetch: ${p}`).toBe(true)
  })

  it('casts the whole cairn, then the whole undertaking, each loading its own conversation', async () => {
    await renderGarden()
    // Project: fan the initiative, fan the project, then tap the
    // well with the project's fan open.
    await openProjectFan()
    act(() => buttonByLabel('The well').click())
    await settleCast()
    expect(lastChat().conversationId).toBe('aria-atelier:project:p1')
    expect(lastChat().context).toEqual({
      sheet_type: 'aria_atelier',
      entity_type: 'project',
      entity_id: 'p1',
    })
    expect(container.textContent).toContain('The whole cairn — all 2 stones')

    // Back to the garden by the rim.
    const back = [...container.querySelectorAll('button')].find((b) =>
      b.textContent?.includes('‹ Garden'),
    )
    expect(back).toBeTruthy()
    act(() => (back as HTMLButtonElement).click())
    await flush()
    expect(container.querySelector('[data-testid="atelier-garden"]')).not.toBeNull()

    // Initiative: the initiative's fan carries the undertaking
    // as a stone.
    tap(buttonByLabel('Spring line'))
    await flush()
    tap(buttonByLabel('Spring line — the whole undertaking'))
    await flush()
    act(() => buttonByLabel('The well').click())
    await settleCast()
    expect(lastChat().conversationId).toBe('aria-atelier:initiative:i1')
    expect(lastChat().context).toEqual({
      sheet_type: 'aria_atelier',
      entity_type: 'initiative',
      entity_id: 'i1',
    })
    expect(container.textContent).toContain('Spring line')
  })
})
