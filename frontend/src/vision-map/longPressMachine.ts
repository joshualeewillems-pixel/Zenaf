/**
 * Long-press state machine — framework-free so it can be driven directly
 * in a node/jsdom harness with real or fake timers.
 *
 * Contract: pointerDown starts a dwell timer; pointerMove past `slopPx`
 * (a drag) or pointerUp/pointerCancel before the dwell cancels it. Tap
 * (quick down→up) never fires — the tap path stays untouched.
 *
 * Arming, not toggling: when the dwell elapses, `onLongPress` fires to
 * signal the press has *armed* (e.g. paint an armed visual), but nothing
 * structural happens yet. `pointerUp` returns true when an armed press is
 * released — the caller commits the action there. This keeps DOM swaps
 * (cairn expand/collapse) out of the middle of an active gesture: swapping
 * nodes mid-gesture unmounts the element React Flow is tracking, kills the
 * node drag, and the pane's own drag tracking takes over (the canvas pans
 * instead). pointerCancel discards an armed press.
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
  let armed = false
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
      armed = false
      cancel()
      timer = setTimeout(() => {
        timer = null
        armed = true
        opts.onLongPress()
      }, delayMs)
    },
    pointerMove(x: number, y: number) {
      // Movement after arming never disarms: hold, then drag, then lift is
      // a legal gesture (the armed action commits on release).
      if (!armed && timer !== null && Math.hypot(x - startX, y - startY) > slopPx) cancel()
    },
    /**
     * End the press. Returns true when a long-press had armed and is now
     * consumed — the caller should commit the armed action. Returns false
     * for taps, cancelled dwells, and idle presses.
     */
    pointerUp(): boolean {
      const wasArmed = armed
      armed = false
      cancel()
      return wasArmed
    },
    /** Abandon the press entirely — an armed press is discarded, not committed. */
    pointerCancel(): boolean {
      armed = false
      cancel()
      return false
    },
    dispose() {
      cancel()
    },
  }
}
