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
  onTurnSent?: () => void
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
import { ResonanceField } from './waterEngine'

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
    const scene = container.querySelector('[data-testid="atelier-garden"]') as HTMLElement | null
    expect(scene).not.toBeNull()
    // Screen 1 is the scene: the founder's painting, whole.
    expect(scene?.style.backgroundImage).toContain('garden-scene1')
    // The live well stands over the painting's basin ellipse: a
    // circle of the ellipse's width at its centre, squashed to
    // its perspective.
    const well = container.querySelector('button[aria-label="The well"]') as HTMLElement | null
    expect(well).not.toBeNull()
    expect(well?.style.left).toBe('52.21%')
    expect(well?.style.top).toBe('49.52%')
    expect(well?.style.width).toBe('45.49%')
    expect(well?.style.transform).toContain('scaleY(0.352)')
    // The painting's lotus stands above the expanded water at
    // its measured placement (the inner ring is not carried).
    const lotus1 = scene?.querySelector('img[src*="garden-scene1-lotus"]') as HTMLImageElement | null
    expect(lotus1).not.toBeNull()
    expect(parseFloat(lotus1?.style.left ?? '')).toBeCloseTo((318 / 1086) * 100, 1)
    expect(parseFloat(lotus1?.style.top ?? '')).toBeCloseTo((693 / 1448) * 100, 1)
    expect(parseFloat(lotus1?.style.width ?? '')).toBeCloseTo((160 / 1086) * 100, 1)
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
    // Screen 2 is the cast's scene: the overhead painting, the
    // live water clipped to its well disc, and the painting's own
    // lotus standing above the water. There is no inner ring: the
    // founder ruled the well-within-a-well obstructive (2026-11-27),
    // so the formations run out to the outer rim.
    const castScene = container.querySelector('[data-testid="atelier-cast-scene"]') as HTMLElement | null
    expect(castScene?.style.backgroundImage).toContain('garden-scene2')
    const disc = container.querySelector('[data-testid="atelier-cast-circle"]') as HTMLElement | null
    expect(disc?.style.left).toBe('48.8%')
    expect(disc?.style.top).toBe('49%')
    expect(disc?.style.width).toBe('32.8%')
    expect(castScene?.querySelector('img[src*="garden-scene2-ring"]')).toBeNull()
    const lotus = castScene?.querySelector('img[src*="garden-scene2-lotus"]') as HTMLImageElement | null
    expect(lotus).not.toBeNull()
    expect(parseFloat(lotus?.style.left ?? '')).toBeCloseTo((311 / 1086) * 100, 1)
    expect(parseFloat(lotus?.style.top ?? '')).toBeCloseTo((616 / 1448) * 100, 1)
    expect(parseFloat(lotus?.style.width ?? '')).toBeCloseTo((163 / 1086) * 100, 1)
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

  /* ------------------------- dynamism ------------------------- */
  /* The dynamism pass (founder-reviewed spec, 2026-11-25): the
   * water answers the contracted events and nothing else; the
   * layers ride their voices' phases; one refraction twin stands
   * beneath Lucian's ink; ?still=1 stills all of it. The field is
   * unavailable in jsdom (no canvas), so the pulse contract is
   * observed at the engine's seam — a spy on ResonanceField's
   * pulse — and phases read 0, which makes the buoyancy values
   * deterministic: front layer translate(0px, 0.9px) scale(1.003),
   * the twin at translate(0px, 1.2px). */

  describe('dynamism (spec, 2026-11-25)', () => {
    let pulseSpy: ReturnType<typeof vi.spyOn>

    beforeEach(() => {
      pulseSpy = vi.spyOn(ResonanceField.prototype, 'pulse')
    })

    afterEach(() => {
      pulseSpy.mockRestore()
    })

    const pulseCalls = () =>
      pulseSpy.mock.calls.map((c) => [c[0], c[1]] as [string, number])

    async function waitFor(cond: () => boolean, timeoutMs = 9000): Promise<void> {
      const start = Date.now()
      while (!cond()) {
        if (Date.now() - start > timeoutMs) throw new Error('waitFor timed out')
        await act(async () => {
          await new Promise((r) => setTimeout(r, 100))
        })
      }
    }

    async function castFirstStone() {
      await openProjectFan()
      tap(buttonByLabel('Confirm the print run — from Spring collection launch'))
      await flush()
      act(() => buttonByLabel('The well').click())
      await settleCast()
    }

    it('the water answers the record events — and no non-events', async () => {
      await renderGarden()
      // Non-events first: opening fans, hovering, refocusing.
      await openProjectFan()
      act(() => {
        buttonByLabel('The well').dispatchEvent(
          new window.MouseEvent('pointermove', { bubbles: true, clientX: 30, clientY: 30 }),
        )
        window.dispatchEvent(new window.Event('focus'))
      })
      await flush()
      expect(pulseCalls()).toEqual([])

      // The cast lands (Aria, full strength) and Aria responds —
      // her formation arrives (Aria, full strength).
      tap(buttonByLabel('Confirm the print run — from Spring collection launch'))
      await flush()
      act(() => buttonByLabel('The well').click())
      await settleCast()
      await waitFor(
        () => pulseCalls().filter(([v, s]) => v === 'aria' && s === 1).length >= 2,
      )
      const calls = pulseCalls()
      expect(calls[0]).toEqual(['aria', 1])
      expect(calls[1]).toEqual(['aria', 1])
      // Nothing but Aria, and nothing but the contracted strengths.
      for (const [v, s] of calls) {
        expect(v).toBe('aria')
        expect([1, 0.5]).toContain(s)
      }

      // A seat responding in the conversation answers again.
      const before = pulseCalls().filter(([v, s]) => v === 'aria' && s === 1).length
      act(() => lastChat().onTurnSent?.())
      await flush()
      await flush()
      await waitFor(
        () => pulseCalls().filter(([v, s]) => v === 'aria' && s === 1).length > before,
      )
    })

    it('the fill wash-in completing answers at half strength, once — the milestone', async () => {
      await renderGarden()
      await castFirstStone()
      // Aria's replay runs ~3s, then her fill washes in over ~2s;
      // its completion is the one rendering-milestone response.
      await waitFor(
        () => pulseCalls().some(([v, s]) => v === 'aria' && s === 0.5),
        16000,
      )
      await act(async () => {
        await new Promise((r) => setTimeout(r, 600))
      })
      expect(pulseCalls().filter(([, s]) => s === 0.5)).toEqual([['aria', 0.5]])
    }, 25000)

    it('buoyancy rides the layers; the twin stands beneath Lucian’s ink and hides on error', async () => {
      await renderGarden()
      await castFirstStone()
      const layerOf = (v: string) =>
        container.querySelector(`[data-layer="${v}"]`) as HTMLElement
      await waitFor(() => layerOf('aria').style.transform.includes('translate'))
      // Phase reads 0 on the unavailable field: the front layer
      // (Aria just responded) rides at its full downward drift.
      expect(layerOf('aria').style.transform).toContain('translate(0px, 0.9px)')
      expect(layerOf('aria').style.transform).toContain('scale(1.0030)')
      // The one twin: beneath Lucian's ink, at its phase offset,
      // and nowhere else.
      const twin = layerOf('lucian').querySelector('img.ink-twin') as HTMLImageElement
      expect(twin).not.toBeNull()
      expect(twin.src).toContain('stage-lucian-6-refr')
      expect(twin.style.transform).toBe('translate(0px, 1.2px)')
      for (const v of ['rumi', 'valen', 'maeve', 'aria', 'severine', 'jynx']) {
        expect(layerOf(v).querySelector('img.ink-twin')).toBeNull()
      }
      // A twin that fails to load hides itself — no glyph, ever.
      act(() => {
        twin.dispatchEvent(new window.Event('error', { bubbles: true }))
      })
      expect(twin.style.display).toBe('none')
    })

    it('the still comparison (?still=1) writes no dynamism transform at all', async () => {
      window.history.replaceState(null, '', '?still=1')
      try {
        await renderGarden()
        await castFirstStone()
        await act(async () => {
          await new Promise((r) => setTimeout(r, 500))
        })
        await flush()
        for (const layer of container.querySelectorAll('[data-layer]')) {
          expect((layer as HTMLElement).style.transform).toBe('')
        }
        // The twin still stands (it is §2.3's asset) — at zero
        // offset, unwritten like everything else dynamism adds.
        const twin = container.querySelector(
          '[data-layer="lucian"] img.ink-twin',
        ) as HTMLImageElement
        expect(twin).not.toBeNull()
        expect(twin.style.transform).toBe('')
      } finally {
        window.history.replaceState(null, '', '/')
      }
    })
  })
})
