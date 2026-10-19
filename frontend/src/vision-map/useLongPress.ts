import { useEffect, useMemo, useRef } from 'react'
import { createLongPressMachine } from './longPressMachine'
import { CAIRN_LONG_PRESS_MS } from './cairn'

/**
 * React binding for the long-press machine. Returns pointer-event props to
 * spread onto the pressable element, plus a contextmenu suppressor (iOS
 * callout). When `onCommit` is null the machine stays inert and no
 * handlers are attached — tap/drag behavior is untouched.
 *
 * Arming, not toggling: the dwell paints an armed visual on the element
 * (`.map-cairn-armed`, classList only — no re-render, so React Flow's
 * in-progress gesture tracking is never disturbed). The committed action
 * runs on pointerup after an armed press, never mid-gesture. Swapping
 * cairn/member nodes mid-gesture unmounts the element React Flow tracks
 * and the canvas pans instead of the stone moving — this is what the
 * commit-on-release contract prevents.
 */
export function useLongPress(onCommit: (() => void) | null, delayMs: number = CAIRN_LONG_PRESS_MS) {
  const commitRef = useRef(onCommit)
  commitRef.current = onCommit
  const elRef = useRef<HTMLElement | null>(null)
  const machineRef = useRef<ReturnType<typeof createLongPressMachine> | null>(null)
  if (!machineRef.current) {
    machineRef.current = createLongPressMachine({
      delayMs,
      onLongPress: () => elRef.current?.classList.add('map-cairn-armed'),
    })
  }
  useEffect(
    () => () => {
      machineRef.current?.dispose()
      elRef.current?.classList.remove('map-cairn-armed')
    },
    [],
  )
  const machine = machineRef.current
  return useMemo(() => {
    if (!onCommit) return {}
    const clearArmed = () => elRef.current?.classList.remove('map-cairn-armed')
    return {
      onPointerDown: (e: { clientX: number; clientY: number; currentTarget: unknown }) => {
        elRef.current = e.currentTarget as HTMLElement | null
        machine.pointerDown(e.clientX, e.clientY)
      },
      onPointerMove: (e: { clientX: number; clientY: number }) => machine.pointerMove(e.clientX, e.clientY),
      onPointerUp: () => {
        const wasArmed = machine.pointerUp()
        clearArmed()
        if (wasArmed) commitRef.current?.()
      },
      onPointerCancel: () => {
        machine.pointerCancel()
        clearArmed()
      },
      onContextMenu: (e: { preventDefault: () => void }) => e.preventDefault(),
    }
  }, [onCommit, machine])
}
