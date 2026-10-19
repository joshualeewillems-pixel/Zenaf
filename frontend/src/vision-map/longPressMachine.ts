/**
 * Long-press state machine — framework-free so it can be driven directly
 * in a node/jsdom harness with real or fake timers.
 *
 * Contract: pointerDown starts a dwell timer; pointerMove past `slopPx`
 * (a drag) or pointerUp/pointerCancel before the dwell cancels it. Tap
 * (quick down→up) never fires — the tap path stays untouched.
 */
export type LongPressOptions = {
  /** Dwell in ms before firing. Default 550. */
  delayMs?: number
  /** Pointer travel in px that cancels the dwell (drag). Default 10. */
  slopPx?: number
  onLongPress: () => void
}

export function createLongPressMachine(opts: LongPressOptions) {
  const delayMs = opts.delayMs ?? 550
  const slopPx = opts.slopPx ?? 10
  let timer: ReturnType<typeof setTimeout> | null = null
  let startX = 0
  let startY = 0

  const cancel = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  return {
    pointerDown(x: number, y: number) {
      startX = x
      startY = y
      cancel()
      timer = setTimeout(() => {
        timer = null
        opts.onLongPress()
      }, delayMs)
    },
    pointerMove(x: number, y: number) {
      if (timer !== null && Math.hypot(x - startX, y - startY) > slopPx) cancel()
    },
    pointerUp() {
      cancel()
    },
    pointerCancel() {
      cancel()
    },
    dispose() {
      cancel()
    },
  }
}
