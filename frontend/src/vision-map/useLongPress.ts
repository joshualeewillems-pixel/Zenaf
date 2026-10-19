import { useEffect, useMemo, useRef } from 'react'
import { createLongPressMachine } from './longPressMachine'
import { CAIRN_LONG_PRESS_MS } from './cairn'

/**
 * React binding for the long-press machine. Returns pointer-event props to
 * spread onto the pressable element, plus a contextmenu suppressor (iOS
 * callout). When `onLongPress` is null the machine stays inert and no
 * handlers are attached — tap/drag behavior is untouched.
 */
export function useLongPress(onLongPress: (() => void) | null, delayMs: number = CAIRN_LONG_PRESS_MS) {
  const cbRef = useRef(onLongPress)
  cbRef.current = onLongPress
  const machineRef = useRef<ReturnType<typeof createLongPressMachine> | null>(null)
  if (!machineRef.current) {
    machineRef.current = createLongPressMachine({
      delayMs,
      onLongPress: () => cbRef.current?.(),
    })
  }
  useEffect(() => () => machineRef.current?.dispose(), [])
  const machine = machineRef.current
  return useMemo(() => {
    if (!onLongPress) return {}
    return {
      onPointerDown: (e: { clientX: number; clientY: number }) => machine.pointerDown(e.clientX, e.clientY),
      onPointerMove: (e: { clientX: number; clientY: number }) => machine.pointerMove(e.clientX, e.clientY),
      onPointerUp: () => machine.pointerUp(),
      onPointerCancel: () => machine.pointerCancel(),
      onContextMenu: (e: { preventDefault: () => void }) => e.preventDefault(),
    }
  }, [onLongPress, machine])
}
