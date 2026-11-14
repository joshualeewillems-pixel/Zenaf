import { useEffect, useRef, useState, type RefObject } from 'react'

/**
 * Touch gesture contract for the Vision map (founder, 2026-11-12):
 *
 * - Exactly ONE active touch pointer: the finger only rakes the sand.
 *   No view pan, no native node drag. (A one-finger press held still on
 *   a stone arms that stone's drag — the hold ladder in VisionMapView
 *   tracks it — and the rake yields while an armed drag runs.)
 * - TWO OR MORE active touch pointers: the fingers move the map — pan +
 *   pinch-zoom — and never rake (ZenSandCanvas suspends itself on the
 *   same "2+ pointers down" signal it observes on the window).
 * - The mouse is untouched by all of this: with no touch pointer down,
 *   pan/drag are exactly the long-standing mouse settings.
 *
 * The gate is expressed as React Flow props driven by the live count.
 * xyflow's pan filter is consulted at gesture start (each touchstart),
 * and pointerdown is dispatched before touchstart, so the count — and
 * therefore the props — is already correct when a gesture's filter runs:
 * a lone finger's start is rejected (rake only), and when the second
 * finger lands its touchstart starts the pan/pinch gesture with both
 * touches registered.
 */
export type TouchGestureGate = {
  /** Active touch pointers the gate was computed from. */
  touchCount: number
  /**
   * React Flow `panOnDrag`: the mouse buttons [left, right] as always,
   * except while exactly one touch pointer is down, when pane dragging
   * is off entirely so the finger can only rake.
   */
  panOnDrag: boolean | number[]
  /**
   * React Flow `nodesDraggable`: React Flow's native drag runs only
   * when no touch pointer is down. A touch drags a stone a different
   * way — hold it still to arm, and the view tracks the drag itself
   * (the hold ladder) — so native drag stays off under touch and a
   * second finger landing mid-press can't hijack the first finger
   * into a node drag.
   */
  nodesDraggable: boolean
  /** True in the one-finger phase (rake only). */
  rakeOnlyPhase: boolean
  /** True in the two-or-more-finger phase (pan + pinch, no rake). */
  navPhase: boolean
}

export function touchGestureGate(rawCount: number): TouchGestureGate {
  const touchCount = Number.isFinite(rawCount) ? Math.max(0, Math.floor(rawCount)) : 0
  return {
    touchCount,
    panOnDrag: touchCount === 1 ? false : [0, 2],
    nodesDraggable: touchCount === 0,
    rakeOnlyPhase: touchCount === 1,
    navPhase: touchCount >= 2,
  }
}

/**
 * Live count of active touch pointers that landed inside `scopeRef`'s
 * element (the map pane). Window listeners in the capture phase observe
 * every contact before React Flow's own handlers see it; releases are
 * tracked by pointer id wherever they happen, so a finger that slides
 * off the pane still unregisters. Mouse and pen pointers never count.
 */
export function useActiveTouchPointerCount(scopeRef: RefObject<HTMLElement | null>): number {
  const activeRef = useRef<ReadonlySet<number>>(new Set())
  const [count, setCount] = useState(0)

  useEffect(() => {
    const sync = () => setCount(activeRef.current.size)
    const onPointerDown = (e: PointerEvent) => {
      if (e.pointerType !== 'touch') return
      const scope = scopeRef.current
      if (scope && e.target instanceof Node && !scope.contains(e.target)) return
      if (activeRef.current.has(e.pointerId)) return
      const next = new Set(activeRef.current)
      next.add(e.pointerId)
      activeRef.current = next
      sync()
    }
    const onPointerUpOrCancel = (e: PointerEvent) => {
      if (!activeRef.current.has(e.pointerId)) return
      const next = new Set(activeRef.current)
      next.delete(e.pointerId)
      activeRef.current = next
      sync()
    }
    const onBlur = () => {
      if (activeRef.current.size === 0) return
      activeRef.current = new Set()
      sync()
    }
    window.addEventListener('pointerdown', onPointerDown, true)
    window.addEventListener('pointerup', onPointerUpOrCancel, true)
    window.addEventListener('pointercancel', onPointerUpOrCancel, true)
    window.addEventListener('blur', onBlur)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('pointerup', onPointerUpOrCancel, true)
      window.removeEventListener('pointercancel', onPointerUpOrCancel, true)
      window.removeEventListener('blur', onBlur)
    }
  }, [scopeRef])

  return count
}
