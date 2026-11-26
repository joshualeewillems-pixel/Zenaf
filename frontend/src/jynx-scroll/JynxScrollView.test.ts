// @vitest-environment jsdom
/**
 * Jynx's Scroll view — jsdom render verification.
 *
 * The view mounts against a stubbed Vision Execution API (the same
 * routes the product uses) and must render Scene 1 (founder,
 * 2026-11-25): the room, its Penrose fabric, one cubby per
 * top-level item — the initiative, the unanchored project, the
 * loose task, the idea — with the initiative's project and its
 * task standing IN its cubby as a cluster (the commission's named
 * rule), and NO text anywhere in the room. A tap stages a scroll
 * tentatively (popup + the chat's staged chip, nothing written);
 * the popup's body opens the scroll on the centre sheet, where it
 * unrolls (the founder's ground) with NO text on the sheet, its
 * children stand beneath as scrolls of their own, and the
 * conversation keys to the open scroll at every level. A
 * long-press on a scroll with children opens the worktable; on a
 * leaf, the sheet directly.
 *
 * The founder's 2026-11-25 live-use corrections are pinned here:
 * the conversation NEVER swaps (rolling, selecting a drawing, a
 * refresh — the id stays the open scroll's; a tapped drawing
 * becomes the conversation's SUBJECT in the same talk); a scroll's
 * sheet carries only its own conversation's drawings (the stubbed
 * feed is deliberately mixed — the surface's own keying is what
 * keeps foreign drawings off the sheet); ink is permanent (a
 * presented drawing's marks stand finished across rolls, with no
 * clock restart); and the sheet is ONE continuous sheet (every
 * drawing mounted at once, rolling moves the sheet's focus —
 * an offset — never swaps pages; there are no pager dots).
 * CouncilChat is stubbed and records its props — the chat seam
 * itself is covered by its own suite.
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
  latest: null as null | {
    onTurnSent?: () => void
    stagedLabel?: string | null
    onStagedClear?: () => void
  },
}))

vi.mock('../chat/CouncilChat', async () => {
  const ReactMod = await import('react')
  return {
    default: (props: {
      conversationId?: string
      context?: Record<string, unknown>
      initialArchetypeId?: string
      onTurnSent?: () => void
      stagedLabel?: string | null
      onStagedClear?: () => void
    }) => {
      chatStub.latest = props
      // The stub renders the chat seam's staging chip to
      // CouncilChat's contract (the real component is pinned by
      // its own suite): the staged drawing's name inside the chat,
      // with its dismissal, while it stands staged.
      return ReactMod.createElement(
        'div',
        {
          'data-testid': 'jynx-chat',
          'data-conversation-id': props.conversationId ?? '',
          'data-context': JSON.stringify(props.context ?? {}),
          'data-archetype': props.initialArchetypeId ?? '',
        },
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

vi.mock('./scrollApi', async (importOriginal) => {
  const orig = await importOriginal<typeof import('./scrollApi')>()
  return {
    ...orig,
    // The stub deliberately returns the feed UNFILTERED, whatever
    // conversation the view asks for: the surface's own keying —
    // not the stub's courtesy — is what the sheet tests pin.
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

const P1_CONVO = 'jynx-scroll:project:p1'

const DRAWING: ScrollDrawing = {
  id: 'd1',
  title: 'Icarus, again',
  space: { w: 600, h: 800 },
  marks: [
    { type: 'stamp', stamp: 'ring', cx: 300, cy: 300, w: 400, tier: 0.6 },
    { type: 'stamp', stamp: 'slash', cx: 220, cy: 480, w: 200, angle: 52, tier: 0.95 },
    { type: 'stroke', d: 'M100 600 Q300 560 500 620', width: 3, tier: 0.32 },
  ],
  conversationId: P1_CONVO,
}

const SECOND: ScrollDrawing = {
  id: 'd2',
  title: null,
  space: { w: 600, h: 800 },
  marks: [{ type: 'stamp', stamp: 'wave', cx: 300, cy: 400, w: 380, tier: 0.6 }],
  conversationId: P1_CONVO,
}

const THIRD: ScrollDrawing = {
  id: 'd3',
  title: null,
  space: { w: 600, h: 800 },
  marks: [{ type: 'stamp', stamp: 'leaf', cx: 300, cy: 400, w: 300, tier: 0.6 }],
  conversationId: P1_CONVO,
}

describe('JynxScrollView', () => {
  let container: HTMLDivElement
  let root: Root
  let fetchMock: ReturnType<typeof stubFetch>

  beforeEach(() => {
    stubDrawings.current = []
    stubDrawings.calls = 0
    stubDrawings.fail = false
    chatStub.latest = null
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
    vi.useRealTimers()
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

  function chatContext() {
    return JSON.parse(chat()?.getAttribute('data-context') ?? '{}') as Record<string, unknown>
  }

  function scrollEl(kind: string, id: string) {
    return container.querySelector(`[data-scroll="${kind}:${id}"]`)
  }

  function sheetEl() {
    return container.querySelector('[data-sheet]')
  }

  function sheetFocus() {
    return sheetEl()?.getAttribute('data-sheet-focus')
  }

  async function clickEl(el: Element) {
    await act(async () => {
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await flush()
  }

  /** Tap a scroll standing in the room or on the table: its
   *  popup stands and the scroll is staged — nothing more. */
  async function tap(kind: string, id: string) {
    const g = scrollEl(kind, id)
    expect(g, `${kind}:${id} standing`).not.toBeNull()
    const hit = [...g!.querySelectorAll('rect')].find((r) => r.getAttribute('fill-opacity') === '0')
    expect(hit).toBeTruthy()
    await clickEl(hit!)
    return hit!
  }

  /** Choose a scroll: tap it, then tap the popup's body to open
   *  it on the centre sheet. */
  async function choose(kind: string, id: string) {
    await tap(kind, id)
    const popup = container.querySelector('[data-testid="scroll-popup"]')
    expect(popup, 'the tap’s popup').not.toBeNull()
    await clickEl(popup!)
  }

  /** Open a child scroll from the open scroll's screen. */
  async function openChild(kind: string, id: string) {
    const btn = container.querySelector(`[data-child-scroll="${kind}:${id}"]`)
    expect(btn, `child ${kind}:${id}`).not.toBeNull()
    await clickEl(btn!)
  }

  async function openProject() {
    await choose('initiative', 'i1')
    await openChild('project', 'p1')
  }

  async function goBack() {
    const btn = container.querySelector('[data-testid="scene-back"]')
    expect(btn, 'back chevron').toBeTruthy()
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

  it('renders the Scene 1 room — cubbies for the top level, clusters within, no text anywhere', async () => {
    await render()
    // The room's scenes carry no text at all: no heading, no
    // lettered names — the old shelf title is gone with the case.
    expect(container.textContent).not.toContain('The Shelf of Scrolls')
    expect(container.querySelectorAll('svg text')).toHaveLength(0)
    // The room itself stands: room ground + the fabric's frames.
    const roomImg = [...container.querySelectorAll('image')].find((i) =>
      (i.getAttribute('href') ?? '').includes('scroll-room'),
    )
    expect(roomImg, 'the room ground').toBeTruthy()
    // Top-level cubbies: the initiative, the unanchored project,
    // the loose task, the idea.
    for (const [kind, id] of [
      ['initiative', 'i1'],
      ['project', 'p2'],
      ['task', 't2'],
      ['idea', 'idea1'],
    ] as const) {
      expect(scrollEl(kind, id), `${kind}:${id}`).not.toBeNull()
      expect(scrollEl(kind, id)?.getAttribute('data-cluster')).toBeNull()
    }
    // The commission's named rule: the initiative's cubby holds
    // its nested project and the project's task as a cluster.
    const cubby = container.querySelector('[data-cubby="initiative:i1"]')
    expect(cubby).not.toBeNull()
    expect(cubby!.querySelector('[data-scroll="project:p1"]')?.getAttribute('data-cluster')).toBe('true')
    expect(cubby!.querySelector('[data-scroll="task:t1"]')?.getAttribute('data-cluster')).toBe('true')
    // A leaf cubby holds one scroll alone.
    const leaf = container.querySelector('[data-cubby="project:p2"]')
    expect(leaf!.querySelectorAll('[data-scroll]')).toHaveLength(1)
    // Names stand nowhere on the face — they live in the popup.
    expect(container.textContent).not.toContain('Meet the Bear')
    expect(container.textContent).not.toContain('Council fellowship')
    // No scroll is open; the conversation is Jynx's, keyed to the shelf.
    expect(container.querySelector('[data-open-scroll]')).toBeNull()
    expect(chat()?.getAttribute('data-archetype')).toBe('maverick')
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:shelf')
    expect(chatContext()).toEqual({ sheet_type: 'jynx_scroll' })
  })

  it('distinguishes scrolls from recorded fields only — a Blocked scroll’s ring band wears violet', async () => {
    await render()
    const violetRings = [...container.querySelectorAll('circle')].filter(
      (c) => c.getAttribute('stroke') === '#a55cce',
    )
    // Exactly the two Blocked scrolls wear violet: the loose
    // project and the initiative's clustered project. Nothing
    // else in the room is violet.
    expect(violetRings).toHaveLength(2)
    for (const [kind, id] of [
      ['project', 'p2'],
      ['project', 'p1'],
    ] as const) {
      const ring = scrollEl(kind, id)!.querySelector('[data-status-ring]')
      expect(ring?.getAttribute('data-status-ring')).toBe('#a55cce')
    }
    const active = scrollEl('initiative', 'i1')
    expect(active!.querySelector('[data-status-ring]')?.getAttribute('data-status-ring')).toBe('#4a3826')
  })

  it('a tap stages a scroll tentatively — popup with its name and recorded synopsis, the chat’s chip, nothing written; tapping the room sets it down', async () => {
    await render()
    const traffic = () => ({ fetch: fetchMock.mock.calls.length, feed: stubDrawings.calls })
    const before = traffic()

    await tap('initiative', 'i1')
    const popup = container.querySelector('[data-testid="scroll-popup"]')
    expect(popup).not.toBeNull()
    expect(popup!.textContent).toContain('Council fellowship')
    expect(popup!.textContent).toContain('Initiative · Active')
    expect(popup!.textContent).toContain('1 project · 1 task within')
    // The staging shows in the chat and keys its subject — while
    // the conversation itself stays the shelf's: nothing opened.
    expect(chatStub.latest?.stagedLabel).toBe('Council fellowship')
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'initiative',
      entity_id: 'i1',
    })
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:shelf')
    expect(container.querySelector('[data-open-scroll]')).toBeNull()
    expect(traffic()).toEqual(before)

    // Tapping the room's bare ground dismisses both, silently.
    await clickEl(container.querySelector('[data-testid="scene-background"]')!)
    expect(container.querySelector('[data-testid="scroll-popup"]')).toBeNull()
    expect(chatStub.latest?.stagedLabel).toBeNull()
    expect(chatContext()).toEqual({ sheet_type: 'jynx_scroll' })
    expect(traffic()).toEqual(before)
  })

  it('choosing a scroll opens it on the centre sheet — the room stands around it, children beneath, back by levels, chat keyed throughout', async () => {
    await render()
    await choose('initiative', 'i1')
    // The initiative stands open on the sheet, in the room: the
    // shelf is NOT replaced — Scene 1 holds both at once.
    expect(container.querySelector('[data-open-scroll="initiative:i1"]')).not.toBeNull()
    expect(scrollEl('initiative', 'i1')).not.toBeNull()
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:initiative:i1')

    await openChild('project', 'p1')
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open).not.toBeNull()
    // The unrolled scroll is the founder's ground asset.
    const img = open!.querySelector('image')
    expect(img?.getAttribute('href')).toContain('scroll-ground')
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:project:p1')
    expect(chatContext()).toEqual({
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
    expect(scrollEl('initiative', 'i1')).not.toBeNull()
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:shelf')
  })

  it('a long-press on a bay’s parent opens the worktable; on a leaf, the sheet — and the trailing click is swallowed', async () => {
    vi.useFakeTimers()
    try {
      const flushFake = async (ms = 0) => {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(ms)
        })
      }
      await act(async () => {
        root.render(React.createElement(JynxScrollView))
      })
      await flushFake(0)
      await flushFake(0)

      const press = async (kind: string, id: string) => {
        const g = scrollEl(kind, id)
        expect(g, `${kind}:${id}`).not.toBeNull()
        const hit = [...g!.querySelectorAll('rect')].find(
          (r) => r.getAttribute('fill-opacity') === '0',
        )
        await act(async () => {
          hit!.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }))
        })
        await flushFake(500)
        // The press ends and the browser's trailing click lands —
        // it must not turn the long-press into a tap.
        await act(async () => {
          hit!.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }))
          hit!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        await flushFake(0)
        return hit!
      }

      // The initiative has children: the worktable opens, its
      // project standing on the table with its task clustered.
      await press('initiative', 'i1')
      expect(container.querySelector('[data-testid="worktable"]')).not.toBeNull()
      const row = container.querySelector('[data-table-row="project:p1"]')
      expect(row).not.toBeNull()
      expect(row!.querySelector('[data-scroll="task:t1"]')?.getAttribute('data-cluster')).toBe('true')
      // No popup, no staging — the long-press was not a tap.
      expect(container.querySelector('[data-testid="scroll-popup"]')).toBeNull()
      expect(chatStub.latest?.stagedLabel).toBeNull()

      // From the table, a tap stages the project and its popup
      // opens it on the room's centre sheet, through its parent.
      const rowHit = [...row!.querySelectorAll('rect')].find(
        (r) => r.getAttribute('fill-opacity') === '0' && r.closest('[data-scroll="project:p1"]'),
      )
      await act(async () => {
        rowHit!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      })
      await flushFake(0)
      const popup = container.querySelector('[data-testid="scroll-popup"]')
      expect(popup).not.toBeNull()
      expect(popup!.textContent).toContain('Meet the Bear')
      expect(chatStub.latest?.stagedLabel).toBe('Meet the Bear')
      await act(async () => {
        popup!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      })
      await flushFake(0)
      expect(container.querySelector('[data-testid="worktable"]')).toBeNull()
      expect(container.querySelector('[data-open-scroll="project:p1"]')).not.toBeNull()
      // The trail walked through the parent: back lands on the
      // initiative's sheet, then the shelf.
      const back = container.querySelector('[data-testid="scene-back"]')
      await act(async () => {
        back!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      })
      await flushFake(0)
      expect(container.querySelector('[data-open-scroll="initiative:i1"]')).not.toBeNull()

      // A leaf's long-press opens it on the sheet directly.
      await press('idea', 'idea1')
      expect(container.querySelector('[data-testid="worktable"]')).toBeNull()
      expect(container.querySelector('[data-open-scroll="idea:idea1"]')).not.toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('the drawing scroll carries no text — no title on the sheet, no text elements at all', async () => {
    stubDrawings.current = [DRAWING, SECOND]
    await render()
    await openProject()
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open).not.toBeNull()
    expect(open!.querySelectorAll('text')).toHaveLength(0)
    expect(open!.textContent ?? '').not.toContain('Meet the Bear')
  })

  it('empty-pencil honesty: an opened scroll with no drawings of its own is blank — no marks, no rollers, no invented art', async () => {
    await render()
    await openProject()
    await openChild('task', 't1')
    const open = container.querySelector('[data-open-scroll="task:t1"]')
    expect(open).not.toBeNull()
    expect(open!.querySelectorAll('[data-drawing-id]')).toHaveLength(0)
    expect(open!.querySelectorAll('[data-mark]')).toHaveLength(0)
    // The only image on the sheet is the ground itself.
    expect(open!.querySelectorAll('image')).toHaveLength(1)
    // Nothing to roll through: no rollers, no roll controls.
    expect(roller('roller-back')).toBeNull()
    expect(roller('roller-forward')).toBeNull()
    expect(container.querySelector('[data-testid="sheet-controls"]')).toBeNull()
    expect(chat()?.getAttribute('data-conversation-id')).toBe('jynx-scroll:task:t1')
  })

  it('renders a drawing’s marks in order on the sheet', async () => {
    stubDrawings.current = [DRAWING]
    await render()
    await openProject()
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
  })

  it('tap explains: tapping a drawing makes it the subject of the SAME conversation; tapping again returns the subject to the scroll', async () => {
    stubDrawings.current = [DRAWING]
    await render()
    await openProject()
    expect(chat()?.getAttribute('data-conversation-id')).toBe(P1_CONVO)

    const hit = container.querySelector('[data-drawing-hit="d1"]')
    expect(hit).toBeTruthy()
    await clickEl(hit!)
    // The conversation id does not move — only its subject does.
    expect(chat()?.getAttribute('data-conversation-id')).toBe(P1_CONVO)
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'drawing',
      entity_id: 'd1',
    })
    // The dashed border is the subjecthood sign, on the drawing's band.
    expect(hit!.getAttribute('stroke')).toBe('#a55cce')
    // And the staging SHOWS in the chat: the chip stands inside the
    // chat pane carrying the drawing's title.
    expect(chatStub.latest?.stagedLabel).toBe('Icarus, again')
    const chip = container.querySelector('[data-testid="jynx-chat"] [data-testid="staged-chip"]')
    expect(chip).not.toBeNull()
    expect(chip!.textContent).toContain('Icarus, again')

    // Setting it down FROM THE CHAT discards the staging exactly
    // as tapping the drawing again does: subject back to the
    // scroll, chip gone, subjecthood border gone.
    await clickEl(container.querySelector('[data-testid="staged-chip-clear"]')!)
    expect(chat()?.getAttribute('data-conversation-id')).toBe(P1_CONVO)
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'project',
      entity_id: 'p1',
    })
    expect(container.querySelector('[data-testid="staged-chip"]')).toBeNull()
    expect(hit!.getAttribute('stroke')).toBe('none')

    // Stage once more and unstage by the drawing tap, as before.
    await clickEl(hit!)
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'drawing',
      entity_id: 'd1',
    })
    await clickEl(hit!)
    expect(chat()?.getAttribute('data-conversation-id')).toBe(P1_CONVO)
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'project',
      entity_id: 'p1',
    })
    expect(hit!.getAttribute('stroke')).toBe('none')
  })

  it('a staged drawing is tentative: taps write nothing — no request of any kind — and the staged subject replaces or discards silently', async () => {
    stubDrawings.current = [DRAWING, SECOND]
    await render()
    await openProject()
    // Every network surface this view can touch: the VE reads on
    // the global fetch, and the drawing feed. A tap must move
    // NEITHER — the staged subject is client-side state alone,
    // and it can enter the conversation's record only inside a
    // message the visitor actually sends (whose per-message
    // context snapshot is the commit point — pinned server-side
    // in tests/test_subject_context_carriage.py).
    const traffic = () => ({ fetch: fetchMock.mock.calls.length, feed: stubDrawings.calls })
    const before = traffic()

    await clickEl(container.querySelector('[data-drawing-hit="d1"]')!)
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'drawing',
      entity_id: 'd1',
    })
    expect(chatStub.latest?.stagedLabel).toBe('Icarus, again')
    expect(traffic()).toEqual(before)

    // Clicking another drawing replaces the staged subject silently.
    // The second drawing carries no title in the record, so the
    // chip names it plainly — a drawing — rather than not standing.
    await clickEl(container.querySelector('[data-drawing-hit="d2"]')!)
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'drawing',
      entity_id: 'd2',
    })
    expect(chatStub.latest?.stagedLabel).toBe('a drawing')
    expect(traffic()).toEqual(before)

    // Clicking the scroll's own ground discards it silently.
    const open = container.querySelector('[data-open-scroll="project:p1"]')!
    const ground = [...open.querySelectorAll('rect')].find(
      (r) => r.getAttribute('fill-opacity') === '0' && !r.hasAttribute('data-drawing-hit'),
    )
    expect(ground).toBeTruthy()
    await clickEl(ground!)
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'project',
      entity_id: 'p1',
    })
    expect(chatStub.latest?.stagedLabel).toBeNull()
    expect(container.querySelector('[data-testid="staged-chip"]')).toBeNull()
    expect(traffic()).toEqual(before)
    expect(chat()?.getAttribute('data-conversation-id')).toBe(P1_CONVO)
  })

  it('the conversation never swaps — not for a selection, not for a roll, not for a refresh', async () => {
    stubDrawings.current = [DRAWING, SECOND]
    await render()
    await openProject()
    const id = () => chat()?.getAttribute('data-conversation-id')
    expect(id()).toBe(P1_CONVO)

    await clickEl(container.querySelector('[data-drawing-hit="d1"]')!)
    expect(id()).toBe(P1_CONVO)
    await clickEl(container.querySelector('[data-testid="sheet-back"]')!)
    expect(id()).toBe(P1_CONVO)
    await clickEl(container.querySelector('[data-testid="sheet-forward"]')!)
    expect(id()).toBe(P1_CONVO)
    await turnLanded()
    expect(id()).toBe(P1_CONVO)
    // And the subject the rolls left standing is still the drawing.
    expect(chatContext()).toEqual({
      sheet_type: 'jynx_scroll',
      entity_type: 'drawing',
      entity_id: 'd1',
    })
  })

  it('a scroll shows its own drawings only — a mixed feed never puts a foreign drawing on the sheet', async () => {
    const foreignTask: ScrollDrawing = {
      id: 'dT',
      title: 'Drawn over the bear step',
      space: { w: 600, h: 800 },
      marks: [{ type: 'stamp', stamp: 'fork', cx: 300, cy: 400, w: 300, tier: 0.6 }],
      conversationId: 'jynx-scroll:task:t1',
    }
    const foreignLegacy: ScrollDrawing = {
      id: 'dL',
      title: 'From a per-drawing conversation of the old wiring',
      space: { w: 600, h: 800 },
      marks: [{ type: 'stamp', stamp: 'arc', cx: 300, cy: 400, w: 300, tier: 0.6 }],
      conversationId: 'jynx-scroll:drawing:d1',
    }
    const noProvenance: ScrollDrawing = { ...DRAWING, id: 'dN', conversationId: null }
    stubDrawings.current = [DRAWING, foreignTask, foreignLegacy, noProvenance]
    await render()
    await openProject()
    // Only this conversation's drawing stands on this sheet.
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    expect(container.querySelector('[data-drawing-id="dT"]')).toBeNull()
    expect(container.querySelector('[data-drawing-id="dL"]')).toBeNull()
    expect(container.querySelector('[data-drawing-id="dN"]')).toBeNull()
    // The task's drawing stands on the TASK's scroll — keyed, not lost.
    await openChild('task', 't1')
    expect(container.querySelector('[data-drawing-id="dT"]')).not.toBeNull()
    expect(container.querySelector('[data-drawing-id="d1"]')).toBeNull()
  })

  it('one continuous sheet: every drawing stands mounted at once, and rolling moves the focus — nothing swaps, nothing unmounts', async () => {
    stubDrawings.current = [DRAWING, SECOND]
    await render()
    await openProject()
    const d1 = container.querySelector('[data-drawing-id="d1"]')
    const d2 = container.querySelector('[data-drawing-id="d2"]')
    expect(d1).not.toBeNull()
    expect(d2).not.toBeNull()
    // Resting with the newest drawing; no pager, no dots.
    expect(sheetFocus()).toBe('1')
    expect(container.querySelector('[data-testid="section-controls"]')).toBeNull()
    const controls = container.querySelector('[data-testid="sheet-controls"]')
    expect(controls).not.toBeNull()
    expect(controls!.querySelectorAll('button')).toHaveLength(2)

    const offsetAtRest = sheetEl()!.getAttribute('data-sheet-offset')
    await clickEl(container.querySelector('[data-testid="sheet-back"]')!)
    expect(sheetFocus()).toBe('0')
    expect(sheetEl()!.getAttribute('data-sheet-offset')).not.toBe(offsetAtRest)
    // The very same nodes — the sheet moved, the drawings stand.
    expect(container.querySelector('[data-drawing-id="d1"]')).toBe(d1)
    expect(container.querySelector('[data-drawing-id="d2"]')).toBe(d2)

    // Forward past the newest drawing reaches the blank working band.
    await clickEl(container.querySelector('[data-testid="sheet-forward"]')!)
    await clickEl(container.querySelector('[data-testid="sheet-forward"]')!)
    expect(sheetFocus()).toBe('2')
    expect(container.querySelector('[data-drawing-id="d1"]')).toBe(d1)
    expect(container.querySelector('[data-drawing-id="d2"]')).toBe(d2)
    expect(
      (container.querySelector('[data-testid="sheet-forward"]') as HTMLButtonElement).disabled,
    ).toBe(true)
    // The sheet itself stays text-free throughout.
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open!.querySelectorAll('text')).toHaveLength(0)
  })

  it('the open scroll’s rollers move along the sheet — top toward the older, bottom toward the newer, inert at the ends', async () => {
    stubDrawings.current = [DRAWING, SECOND]
    await render()
    await openProject()
    const back = roller('roller-back')
    const fwd = roller('roller-forward')
    expect(back, 'top roller control').not.toBeNull()
    expect(fwd, 'bottom roller control').not.toBeNull()
    expect(back!.getAttribute('aria-label')).toBe('Roll toward the older drawings')
    expect(fwd!.getAttribute('aria-label')).toBe('Roll toward the newer drawings')
    // Resting on the newest drawing: both ways can still move —
    // back into the history, forward onto the blank working space.
    expect(back!.getAttribute('aria-disabled')).toBe('false')
    expect(fwd!.getAttribute('aria-disabled')).toBe('false')

    // The bottom roller rolls forward onto the blank band, and
    // the chrome control — the same sheet movement — agrees.
    await clickEl(fwd!)
    expect(sheetFocus()).toBe('2')
    expect(roller('roller-forward')!.getAttribute('aria-disabled')).toBe('true')
    expect(
      (container.querySelector('[data-testid="sheet-forward"]') as HTMLButtonElement).disabled,
    ).toBe(true)

    // The top roller rolls back through the history to its end.
    await clickEl(roller('roller-back')!)
    await clickEl(roller('roller-back')!)
    expect(sheetFocus()).toBe('0')
    expect(roller('roller-back')!.getAttribute('aria-disabled')).toBe('true')
    expect(
      (container.querySelector('[data-testid="sheet-back"]') as HTMLButtonElement).disabled,
    ).toBe(true)
    // An inert roller does not move the sheet.
    await clickEl(roller('roller-back')!)
    expect(sheetFocus()).toBe('0')

    // The rollers put no text on the sheet.
    const open = container.querySelector('[data-open-scroll="project:p1"]')
    expect(open!.querySelectorAll('text')).toHaveLength(0)
  })

  it('a single drawing still rolls — forward onto its blank working space and back', async () => {
    stubDrawings.current = [DRAWING]
    await render()
    await openProject()
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    expect(roller('roller-back')).not.toBeNull()
    expect(roller('roller-forward')).not.toBeNull()
    expect(sheetFocus()).toBe('0')
    await clickEl(roller('roller-forward')!)
    expect(sheetFocus()).toBe('1')
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    await clickEl(roller('roller-back')!)
    expect(sheetFocus()).toBe('0')
  })

  it('opening a scroll re-reads its feed — a drawing that arrived after mount renders on its own scroll', async () => {
    await render()
    const callsAfterMount = stubDrawings.calls
    // Jynx draws (in this scroll's conversation) after this pane mounted.
    stubDrawings.current = [DRAWING]
    await choose('initiative', 'i1')
    expect(stubDrawings.calls).toBeGreaterThan(callsAfterMount)
    await openChild('project', 'p1')
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
  })

  it('a turn landing beside an open scroll re-reads the feed — the founder’s blank scroll fills in place', async () => {
    await render()
    await openProject()
    // The pane was open while Jynx drew: honestly blank until the
    // turn that made the drawing lands and the feed re-reads.
    expect(container.querySelector('[data-drawing-id]')).toBeNull()
    stubDrawings.current = [DRAWING]
    await turnLanded()
    expect(container.querySelector('[data-open-scroll="project:p1"]')).not.toBeNull()
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    // The new drawing takes the working place — resting focus
    // follows the sheet's growth to the newest drawing.
    expect(sheetFocus()).toBe('0')
  })

  it('the window waking re-reads the feed', async () => {
    await render()
    await openProject()
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
    await openProject()
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    stubDrawings.fail = true
    await turnLanded()
    expect(container.querySelector('[data-drawing-id="d1"]')).not.toBeNull()
    expect(container.textContent).not.toContain('Could not load your scrolls.')
  })

  it('a re-read with the same list — or a grown one — never moves the visitor’s place along the sheet', async () => {
    stubDrawings.current = [DRAWING, SECOND]
    await render()
    await openProject()
    // The visitor rolls back to the first drawing and stays there.
    await clickEl(container.querySelector('[data-testid="sheet-back"]')!)
    expect(sheetFocus()).toBe('0')

    // Same list back from a re-read: the visitor stays on d1.
    await turnLanded()
    expect(sheetFocus()).toBe('0')

    // A grown list: still on d1 — the new drawing joins the sheet's
    // end, reachable by rolling, not thrust into the working place.
    stubDrawings.current = [DRAWING, SECOND, THIRD]
    await turnLanded()
    expect(sheetFocus()).toBe('0')
    expect(container.querySelector('[data-drawing-id="d3"]')).not.toBeNull()
    await clickEl(container.querySelector('[data-testid="sheet-forward"]')!)
    await clickEl(container.querySelector('[data-testid="sheet-forward"]')!)
    expect(sheetFocus()).toBe('2')
  })

  it('ink is permanent: a drawing draws itself once, and its finished ink stands across rolls with no repaint', async () => {
    vi.useFakeTimers()
    try {
      const flushFake = async (ms = 0) => {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(ms)
        })
      }
      const clickFake = async (el: Element) => {
        await act(async () => {
          el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })
        await flushFake(0)
      }
      stubDrawings.current = [DRAWING]
      await act(async () => {
        root.render(React.createElement(JynxScrollView))
      })
      await flushFake(0)
      await flushFake(0)
      const g1 = scrollEl('initiative', 'i1')
      const hit1 = [...g1!.querySelectorAll('rect')].find(
        (r) => r.getAttribute('fill-opacity') === '0',
      )
      // Tap stages; the popup's body opens — the choose path.
      await clickFake(hit1!)
      await clickFake(container.querySelector('[data-testid="scroll-popup"]')!)
      await clickFake(container.querySelector('[data-child-scroll="project:p1"]')!)

      const drawingEl = container.querySelector('[data-drawing-id="d1"]')
      expect(drawingEl).not.toBeNull()
      const marks = () => [...drawingEl!.querySelectorAll('[data-mark]')]
      // On arrival the drawing is still drawing itself: the first
      // stamp has not reached its tier.
      expect(marks()[0].getAttribute('opacity')).toBe('0')

      // Its one draw-out runs (unroll, then the marks in order)…
      await flushFake(6000)
      // …and the ink stands finished: stamps at their tiers, the
      // stroke fully drawn.
      expect(marks()[0].getAttribute('opacity')).toBe('0.6')
      expect(marks()[1].getAttribute('opacity')).toBe('0.95')
      expect(marks()[2].getAttribute('stroke-dashoffset')).toBe('0')

      // Roll away to the blank working space and back — with NO
      // time passing, the ink is already standing: no draw-out
      // restarts, and the drawing's node never changed hands.
      await clickFake(container.querySelector('[data-testid="sheet-forward"]')!)
      expect(sheetFocus()).toBe('1')
      expect(container.querySelector('[data-drawing-id="d1"]')).toBe(drawingEl)
      expect(marks()[0].getAttribute('opacity')).toBe('0.6')
      await clickFake(container.querySelector('[data-testid="sheet-back"]')!)
      expect(sheetFocus()).toBe('0')
      expect(container.querySelector('[data-drawing-id="d1"]')).toBe(drawingEl)
      expect(marks()[0].getAttribute('opacity')).toBe('0.6')
      expect(marks()[2].getAttribute('stroke-dashoffset')).toBe('0')
    } finally {
      vi.useRealTimers()
    }
  })
})
