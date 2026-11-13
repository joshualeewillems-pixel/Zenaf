/**
 * Two-tier hold ladder — framework-free so it can be driven directly in
 * a node/jsdom harness with real or fake timers.
 *
 * One still press, two thresholds (founder gesture revision,
 * 2026-11-13 — the revision of the 2026-11-12 contract, which had
 * forgotten drag):
 *
 * - Tier 1 at `armDelayMs`: the press ARMS DRAG for the pressed node
 *   (`onArm` fires; the caller paints the armed visual and starts
 *   tracking the pointer). Nothing structural happens at this tier.
 * - Tier 2 at `toggleDelayMs` (from press start): if the press is still
 *   armed and the finger never really moved, `onToggle` fires
 *   immediately and the press is SPENT — releasing it, or moving after
 *   it, must not drag and must not commit anything else.
 *
 * Movement past `slopPx` before tier 1 cancels the ladder outright:
 * that press is a rake, not a hold. Movement past `slopPx` after tier 1
 * means the drag has begun, which cancels tier 2 for this press — you
 * cannot drag a stone and toggle its cairn with one press. Movement
 * within the slop (a steady hand's jitter) changes nothing.
 *
 * pointerUp before tier 1 is a tap: nothing fires. Between the tiers it
 * merely disarms. pointerCancel discards the press entirely.
 */
export type HoldLadderOptions = {
  /** Still-hold ms before drag arms. Default 450. */
  armDelayMs?: number
  /** Still-hold ms from press start before the toggle fires. Default 1100. */
  toggleDelayMs?: number
  /** Pointer travel in px that counts as "started moving". Default 10. */
  slopPx?: number
  onArm: () => void
  onToggle: () => void
}

export type HoldLadderPhase = 'idle' | 'dwelling' | 'armed' | 'dragging' | 'spent'

export function createHoldLadderMachine(opts: HoldLadderOptions) {
  const armDelayMs = opts.armDelayMs ?? 450
  const toggleDelayMs = opts.toggleDelayMs ?? 1100
  const slopPx = opts.slopPx ?? 10
  let armTimer: ReturnType<typeof setTimeout> | null = null
  let toggleTimer: ReturnType<typeof setTimeout> | null = null
  let phase: HoldLadderPhase = 'idle'
  let startX = 0
  let startY = 0

  const clearTimers = () => {
    if (armTimer !== null) {
      clearTimeout(armTimer)
      armTimer = null
    }
    if (toggleTimer !== null) {
      clearTimeout(toggleTimer)
      toggleTimer = null
    }
  }

  return {
    pointerDown(x: number, y: number) {
      startX = x
      startY = y
      clearTimers()
      phase = 'dwelling'
      armTimer = setTimeout(() => {
        armTimer = null
        if (phase !== 'dwelling') return
        phase = 'armed'
        opts.onArm()
      }, armDelayMs)
      toggleTimer = setTimeout(() => {
        toggleTimer = null
        if (phase !== 'armed') return
        phase = 'spent'
        opts.onToggle()
      }, toggleDelayMs)
    },
    pointerMove(x: number, y: number) {
      if (phase !== 'dwelling' && phase !== 'armed') return
      if (Math.hypot(x - startX, y - startY) <= slopPx) return
      if (phase === 'dwelling') {
        // Moved before the hold armed: not a hold at all.
        clearTimers()
        phase = 'idle'
      } else {
        // The drag has begun — tier 2 is cancelled for this press.
        if (toggleTimer !== null) {
          clearTimeout(toggleTimer)
          toggleTimer = null
        }
        phase = 'dragging'
      }
    },
    /** End the press; returns the phase it ended in. Nothing commits here — tier 2 already fired if it was reached. */
    pointerUp(): HoldLadderPhase {
      const ended = phase
      clearTimers()
      phase = 'idle'
      return ended
    },
    /** Abandon the press entirely — armed or not, nothing fires after this. */
    pointerCancel() {
      clearTimers()
      phase = 'idle'
    },
    currentPhase(): HoldLadderPhase {
      return phase
    },
    dispose() {
      clearTimers()
    },
  }
}
