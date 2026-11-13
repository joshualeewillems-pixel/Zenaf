import { describe, expect, it } from 'vitest'
import { longPressTargetFor } from './cairn'
import { fitZoomForBounds, graphBounds, populatedBounds, type PopulatedNode } from './mapFitView'
import { touchGestureGate } from './touchGestureGate'

/**
 * Founder gesture contract + object-aware fit (2026-11-12):
 *
 * - The fit control must frame what is POPULATED — rendered entities
 *   only, never nest-group scaffolding — so a big empty container parked
 *   past the garden can't zoom the view out to no man's land.
 * - Touch: exactly one finger rakes only; two or more move the map.
 * - A hold on a member of an already-fanned cairn opens that stone's
 *   data; it no longer collapses the cairn.
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

describe('longPressTargetFor — fanned member opens its data', () => {
  it('a member of a fanned cairn resolves to openStoneData, not collapse', () => {
    expect(longPressTargetFor('branch', 'cairn-1', 'stone-9')).toEqual({
      action: 'openStoneData',
      cairnId: 'cairn-1',
    })
  })

  it('the fanned-member rule wins even for a tree-kind member', () => {
    expect(longPressTargetFor('tree', 'cairn-1', 'tree-2')).toEqual({
      action: 'openStoneData',
      cairnId: 'cairn-1',
    })
  })

  it('a free initiative stone still toggles its garden stack', () => {
    expect(longPressTargetFor('tree', null, 'tree-1')).toEqual({
      action: 'toggleGardenStack',
      treeId: 'tree-1',
    })
  })

  it('a plain stone has no long-press action', () => {
    expect(longPressTargetFor('branch', null, 'stone-1')).toEqual({ action: 'none' })
  })
})
