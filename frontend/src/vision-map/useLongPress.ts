import { useEffect, useMemo, useRef } from 'react'
import { createLongPressMachine } from './longPressMachine'
import { createHoldLadderMachine } from './holdLadderMachine'
import { CAIRN_HOLD_TOGGLE_MS, CAIRN_LONG_PRESS_MS } from './cairn'

export type NodeHoldGestureCallbacks = {
  /**
   * Tier 1 (touch only): the still hold armed drag for this node.
   * Carries the press's pointer identity and start point so the view
   * can track the drag on the window from here.
   */
  onDragArm?: (info: { pointerId: number; clientX: number; clientY: number }) => void
  /**
   * The node's toggle action. Touch: tier 2 of the hold ladder, fired
   * mid-press at CAIRN_HOLD_TOGGLE_MS. Mouse: the long-standing hold,
   * committed on release after the CAIRN_LONG_PRESS_MS dwell.
   */
  onToggle?: () => void
  /**
   * Touch tier 2 only: fired just before `onToggle` so the view can
   * mark the press spent — the release that follows must not also land
   * as a click. Mouse commits never call this; mouse behavior is
   * unchanged from before the ladder existed.
   */
  onPressSpent?: () => void
}

const ARM_CLASS = 'map-cairn-armed'
const TOGGLE_CLASS = 'map-cairn-toggle-armed'

type PressEvent = {
  clientX: number
  clientY: number
  pointerId: number
  pointerType: string
  currentTarget: unknown
}

/**
 * Pointer props for a map node's hold gestures. Two pointer families,
 * routed per press by `pointerType` at pointerdown:
 *
 * - Touch runs the two-tier hold ladder (holdLadderMachine): hold still
 *   to CAIRN_LONG_PRESS_MS and drag arms for this node; keep holding to
 *   CAIRN_HOLD_TOGGLE_MS and the toggle fires mid-press. Tier paints are
 *   classList-only (`.map-cairn-armed`, then `.map-cairn-toggle-armed`)
 *   — no re-render while a gesture is in flight.
 * - Mouse and pen keep the pre-ladder behavior exactly: the dwell paints
 *   the same armed ring, and the toggle commits on release
 *   (longPressMachine's arming contract — committing on release keeps
 *   node swaps out of the middle of a mouse drag).
 *
 * When `callbacks` is null the hook stays inert and attaches nothing.
 * A press is tracked by pointer id; a second pointer landing on the
 * same node mid-press is ignored.
 */
export function useNodeHoldGestures(callbacks: NodeHoldGestureCallbacks | null) {
  const cbRef = useRef(callbacks)
  cbRef.current = callbacks
  const elRef = useRef<HTMLElement | null>(null)
  const downRef = useRef<{ pointerId: number; clientX: number; clientY: number } | null>(null)
  const activeRef = useRef<'ladder' | 'legacy' | null>(null)

  const legacyRef = useRef<ReturnType<typeof createLongPressMachine> | null>(null)
  if (!legacyRef.current) {
    legacyRef.current = createLongPressMachine({
      delayMs: CAIRN_LONG_PRESS_MS,
      onLongPress: () => elRef.current?.classList.add(ARM_CLASS),
    })
  }
  const ladderRef = useRef<ReturnType<typeof createHoldLadderMachine> | null>(null)
  if (!ladderRef.current) {
    ladderRef.current = createHoldLadderMachine({
      armDelayMs: CAIRN_LONG_PRESS_MS,
      toggleDelayMs: CAIRN_HOLD_TOGGLE_MS,
      onArm: () => {
        elRef.current?.classList.add(ARM_CLASS)
        const d = downRef.current
        if (d) cbRef.current?.onDragArm?.({ ...d })
      },
      onToggle: () => {
        elRef.current?.classList.add(TOGGLE_CLASS)
        cbRef.current?.onPressSpent?.()
        cbRef.current?.onToggle?.()
      },
    })
  }
  const legacy = legacyRef.current
  const ladder = ladderRef.current

  useEffect(
    () => () => {
      legacy.dispose()
      ladder.dispose()
      elRef.current?.classList.remove(ARM_CLASS)
      elRef.current?.classList.remove(TOGGLE_CLASS)
    },
    [legacy, ladder],
  )

  const hasCallbacks = callbacks !== null
  return useMemo(() => {
    if (!hasCallbacks) return {}
    const clearPaint = () => {
      elRef.current?.classList.remove(ARM_CLASS)
      elRef.current?.classList.remove(TOGGLE_CLASS)
    }
    const owns = (e: PressEvent) => !!downRef.current && e.pointerId === downRef.current.pointerId
    return {
      onPointerDown: (e: PressEvent) => {
        if (activeRef.current !== null) return
        elRef.current = e.currentTarget as HTMLElement | null
        downRef.current = { pointerId: e.pointerId, clientX: e.clientX, clientY: e.clientY }
        if (e.pointerType === 'touch') {
          activeRef.current = 'ladder'
          ladder.pointerDown(e.clientX, e.clientY)
        } else {
          activeRef.current = 'legacy'
          legacy.pointerDown(e.clientX, e.clientY)
        }
      },
      onPointerMove: (e: PressEvent) => {
        if (!owns(e)) return
        if (activeRef.current === 'ladder') ladder.pointerMove(e.clientX, e.clientY)
        else if (activeRef.current === 'legacy') legacy.pointerMove(e.clientX, e.clientY)
      },
      onPointerUp: (e: PressEvent) => {
        if (!owns(e)) return
        const which = activeRef.current
        activeRef.current = null
        downRef.current = null
        if (which === 'ladder') {
          // Tier 2 already fired if it was reached; a release between
          // the tiers just disarms. Nothing commits on a touch release.
          ladder.pointerUp()
        } else if (which === 'legacy') {
          if (legacy.pointerUp()) cbRef.current?.onToggle?.()
        }
        clearPaint()
      },
      onPointerCancel: (e: PressEvent) => {
        if (!owns(e)) return
        const which = activeRef.current
        activeRef.current = null
        downRef.current = null
        if (which === 'ladder') ladder.pointerCancel()
        else if (which === 'legacy') legacy.pointerCancel()
        clearPaint()
      },
      onContextMenu: (e: { preventDefault: () => void }) => e.preventDefault(),
    }
  }, [hasCallbacks, legacy, ladder])
}
