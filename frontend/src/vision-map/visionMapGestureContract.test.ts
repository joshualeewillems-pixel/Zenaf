import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CAIRN_HOLD_TOGGLE_MS,
  CAIRN_LONG_PRESS_MS,
  doubleTapTargetFor,
  longPressTargetFor,
} from './cairn'
import { createHoldLadderMachine } from './holdLadderMachine'
import { fitZoomForBounds, graphBounds, populatedBounds, type PopulatedNode } from './mapFitView'
import { touchGestureGate } from './touchGestureGate'

/**
 * Founder gesture contract + object-aware fit (2026-11-12, revised
 * 2026-11-13 — the revision restores the drag the first contract
 * forgot):
 *
 * - The fit control must frame what is POPULATED — rendered entities
 *   only, never nest-group scaffolding — so a big empty container parked
 *   past the garden can't zoom the view out to no man's land.
 * - Touch: exactly one finger rakes only; two or more move the map.
 * - The hold is a two-tier ladder: hold still to arm drag (tier 1),
 *   keep holding to toggle the cairn/stack (tier 2). Tier 2 is
 *   cancelled the moment the drag actually starts.
 * - Double-tap opens: a cairn fans out, a stack unstacks, a stone
 *   opens its data. The old hold-opens-data behavior is gone.
 */

const node = (over: Partial<PopulatedNode> & { position: PopulatedNode['position'] }): PopulatedNode => ({
  width: 120,
  height: 90,
  ...over,
})

describe('populatedBounds', () => {
  it('encloses entities and cairns, excluding nest-group scaffolding', () => {
    const nodes: PopulatedNode[] = [
      node({ position: { x: 100, y: 100 }, type: 'entityMap' }),
      node({ position: { x: 400, y: 300 }, type: 'cairn' }),
      node({ position: { x: -5000, y: -5000 }, width: 4000, height: 4000, type: 'nestGroup' }),
    ]
    expect(populatedBounds(nodes)).toEqual({ x: 100, y: 100, width: 420, height: 290 })
    // The all-nodes variant IS dragged out by the scaffolding — the
    // contrast is the bug the fit control shipped with.
    expect(graphBounds(nodes)!.width).toBeGreaterThan(4000)
  })

  it('ignores an empty outlying region: hidden nodes do not count as populated', () => {
    const nodes: PopulatedNode[] = [
      node({ position: { x: 0, y: 0 }, type: 'entityMap' }),
      node({ position: { x: 9000, y: 9000 }, type: 'entityMap', hidden: true }),
    ]
    expect(populatedBounds(nodes)).toEqual({ x: 0, y: 0, width: 120, height: 90 })
  })

  it('is null when nothing is populated', () => {
    expect(populatedBounds([])).toBeNull()
    expect(
      populatedBounds([node({ position: { x: 0, y: 0 }, type: 'nestGroup' })]),
    ).toBeNull()
  })

  it('fit zoom over populated bounds respects the 0.9 cap for a small garden', () => {
    const bounds = populatedBounds([
      node({ position: { x: 0, y: 0 }, type: 'entityMap' }),
      node({ position: { x: 280, y: 210 }, type: 'cairn' }),
    ])! // 400 × 300 of garden
    const zoom = fitZoomForBounds(bounds, { width: 1000, height: 800 }, { padding: 0.15, minZoom: 0.15, maxZoom: 0.9 })
    expect(zoom).toBe(0.9)
  })
})

describe('touchGestureGate', () => {
  it('no touch down: mouse behavior untouched (pan on [0,2], stones draggable)', () => {
    const g = touchGestureGate(0)
    expect(g.panOnDrag).toEqual([0, 2])
    expect(g.nodesDraggable).toBe(true)
    expect(g.rakeOnlyPhase).toBe(false)
    expect(g.navPhase).toBe(false)
  })

  it('exactly one finger: rake only — pane pan off, stones not draggable', () => {
    const g = touchGestureGate(1)
    expect(g.panOnDrag).toBe(false)
    expect(g.nodesDraggable).toBe(false)
    expect(g.rakeOnlyPhase).toBe(true)
    expect(g.navPhase).toBe(false)
  })

  it('two or more fingers: pan restored for the pinch gesture, stones still not draggable', () => {
    for (const count of [2, 3]) {
      const g = touchGestureGate(count)
      expect(g.panOnDrag).toEqual([0, 2])
      expect(g.nodesDraggable).toBe(false)
      expect(g.rakeOnlyPhase).toBe(false)
      expect(g.navPhase).toBe(true)
    }
  })
})

describe('longPressTargetFor — the longer hold (tier 2) toggles', () => {
  it('a member of a fanned cairn stacks its cairn back', () => {
    expect(longPressTargetFor('branch', 'cairn-1', 'stone-9')).toEqual({
      action: 'collapseCairn',
      cairnId: 'cairn-1',
    })
  })

  it('the member rule wins even for a tree-kind member', () => {
    expect(longPressTargetFor('tree', 'cairn-1', 'tree-2')).toEqual({
      action: 'collapseCairn',
      cairnId: 'cairn-1',
    })
  })

  it('a free initiative stone toggles its garden stack', () => {
    expect(longPressTargetFor('tree', null, 'tree-1')).toEqual({
      action: 'toggleGardenStack',
      treeId: 'tree-1',
    })
  })

  it('a plain stone toggles nothing — its hold only arms drag', () => {
    expect(longPressTargetFor('branch', null, 'stone-1')).toEqual({ action: 'none' })
  })
})

describe('doubleTapTargetFor — double-tap opens', () => {
  it('a closed cairn fans out', () => {
    expect(doubleTapTargetFor('cairn-p1', 'cairn', { kind: 'cairn' })).toEqual({
      action: 'fanOutCairn',
      cairnId: 'cairn-p1',
    })
  })

  it('a garden stack (the pile on its initiative stone) unstacks', () => {
    expect(doubleTapTargetFor('tree-1', 'cairn', { kind: 'cairn', gardenStack: true })).toEqual({
      action: 'unstackGardenStack',
      treeId: 'tree-1',
    })
  })

  it('a stone opens its data sheet', () => {
    expect(doubleTapTargetFor('stone-1', 'entityMap', { kind: 'branch' })).toEqual({
      action: 'openStoneData',
      nodeId: 'stone-1',
    })
  })

  it('a fanned member opens its data — it renders as an entityMap node', () => {
    expect(
      doubleTapTargetFor('stone-9', 'entityMap', { kind: 'flower', expandedFromCairn: 'cairn-1' }),
    ).toEqual({ action: 'openStoneData', nodeId: 'stone-9' })
  })

  it('a free initiative stone opens its data (stacking belongs to the pile, not the stone)', () => {
    expect(doubleTapTargetFor('tree-1', 'entityMap', { kind: 'tree' })).toEqual({
      action: 'openStoneData',
      nodeId: 'tree-1',
    })
  })

  it('containers and unknown types have no double-tap action', () => {
    expect(doubleTapTargetFor('nest-1', 'nestGroup', {})).toEqual({ action: 'none' })
    expect(doubleTapTargetFor('x', undefined, {})).toEqual({ action: 'none' })
  })
})

describe('hold ladder machine — tier resolution by press duration', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  const setup = () => {
    const events: string[] = []
    const machine = createHoldLadderMachine({
      onArm: () => events.push('arm'),
      onToggle: () => events.push('toggle'),
    })
    return { machine, events }
  }

  it('ships the founder ladder: 450ms arms drag, 1100ms toggles', () => {
    expect(CAIRN_LONG_PRESS_MS).toBe(450)
    expect(CAIRN_HOLD_TOGGLE_MS).toBe(1100)
    expect(CAIRN_HOLD_TOGGLE_MS).toBeGreaterThan(CAIRN_LONG_PRESS_MS)
  })

  it('arms drag at the tier-1 dwell — and not a tick before', () => {
    const { machine, events } = setup()
    machine.pointerDown(100, 100)
    vi.advanceTimersByTime(CAIRN_LONG_PRESS_MS - 1)
    expect(events).toEqual([])
    vi.advanceTimersByTime(1)
    expect(events).toEqual(['arm'])
    expect(machine.currentPhase()).toBe('armed')
  })

  it('a tap (release before tier 1) fires nothing', () => {
    const { machine, events } = setup()
    machine.pointerDown(100, 100)
    vi.advanceTimersByTime(120)
    expect(machine.pointerUp()).toBe('dwelling')
    vi.advanceTimersByTime(3000)
    expect(events).toEqual([])
  })

  it('release between the tiers just disarms — the toggle never fires', () => {
    const { machine, events } = setup()
    machine.pointerDown(100, 100)
    vi.advanceTimersByTime(CAIRN_LONG_PRESS_MS)
    expect(events).toEqual(['arm'])
    expect(machine.pointerUp()).toBe('armed')
    vi.advanceTimersByTime(3000)
    expect(events).toEqual(['arm'])
  })

  it('holding still to tier 2 fires the toggle once, at the threshold — the press is spent', () => {
    const { machine, events } = setup()
    machine.pointerDown(100, 100)
    vi.advanceTimersByTime(CAIRN_HOLD_TOGGLE_MS - 1)
    expect(events).toEqual(['arm'])
    vi.advanceTimersByTime(1)
    expect(events).toEqual(['arm', 'toggle'])
    expect(machine.currentPhase()).toBe('spent')
    // Spent: more time, movement, and the release itself add nothing.
    vi.advanceTimersByTime(3000)
    machine.pointerMove(200, 200)
    expect(machine.pointerUp()).toBe('spent')
    expect(events).toEqual(['arm', 'toggle'])
  })

  it('moving past the slop before tier 1 cancels the ladder (a rake press, not a hold)', () => {
    const { machine, events } = setup()
    machine.pointerDown(100, 100)
    vi.advanceTimersByTime(100)
    machine.pointerMove(140, 100)
    expect(machine.currentPhase()).toBe('idle')
    vi.advanceTimersByTime(3000)
    expect(events).toEqual([])
  })

  it('moving after tier 1 starts the drag and cancels tier 2 for that press', () => {
    const { machine, events } = setup()
    machine.pointerDown(100, 100)
    vi.advanceTimersByTime(CAIRN_LONG_PRESS_MS)
    machine.pointerMove(140, 100)
    expect(machine.currentPhase()).toBe('dragging')
    // Even holding still at the new spot well past tier 2: no toggle.
    vi.advanceTimersByTime(3000)
    expect(machine.pointerUp()).toBe('dragging')
    expect(events).toEqual(['arm'])
  })

  it('jitter inside the slop after arming does not cancel tier 2', () => {
    const { machine, events } = setup()
    machine.pointerDown(100, 100)
    vi.advanceTimersByTime(CAIRN_LONG_PRESS_MS)
    machine.pointerMove(105, 103)
    expect(machine.currentPhase()).toBe('armed')
    vi.advanceTimersByTime(CAIRN_HOLD_TOGGLE_MS - CAIRN_LONG_PRESS_MS)
    expect(events).toEqual(['arm', 'toggle'])
  })

  it('pointerCancel discards an armed press — no toggle, no drag commit from the machine', () => {
    const { machine, events } = setup()
    machine.pointerDown(100, 100)
    vi.advanceTimersByTime(CAIRN_LONG_PRESS_MS)
    machine.pointerCancel()
    expect(machine.currentPhase()).toBe('idle')
    vi.advanceTimersByTime(3000)
    expect(events).toEqual(['arm'])
  })
})
