/**
 * Initiative `next_step_ai` column holds a versioned JSON payload (mediative next steps),
 * not a separate DB column. Legacy plain text is treated as a single step.
 *
 * @see docs/NEXT_STEPS_MEDIATION_NOTE.md for evolution toward tasks / recursive planning.
 */

export const NEXT_STEPS_PAYLOAD_VERSION = 1 as const

export type NextStepsPayload = {
  v: typeof NEXT_STEPS_PAYLOAD_VERSION
  steps: string[]
  /** Index of the step the user is focusing on (0-based). */
  current: number
  /** Indices of steps marked done via "Next". */
  completed: number[]
}

export function emptyNextStepsPayload(): NextStepsPayload {
  return { v: NEXT_STEPS_PAYLOAD_VERSION, steps: [], current: 0, completed: [] }
}

/** Parse DB/API string into structured state (never throws). */
export function parseNextStepsPayload(raw: string | undefined | null): NextStepsPayload {
  const trimmed = String(raw ?? '').trim()
  if (!trimmed) return emptyNextStepsPayload()
  try {
    const j = JSON.parse(trimmed) as unknown
    if (j && typeof j === 'object' && !Array.isArray(j) && (j as NextStepsPayload).v === NEXT_STEPS_PAYLOAD_VERSION) {
      const o = j as Partial<NextStepsPayload>
      const steps = Array.isArray(o.steps) ? o.steps.map((s) => String(s ?? '').trim()).filter(Boolean) : []
      const completed = Array.isArray(o.completed)
        ? [...new Set(o.completed.filter((i): i is number => typeof i === 'number' && i >= 0 && Number.isInteger(i)))].sort(
            (a, b) => a - b,
          )
        : []
      let current = typeof o.current === 'number' && Number.isInteger(o.current) ? o.current : 0
      if (steps.length === 0) return emptyNextStepsPayload()
      current = Math.max(0, Math.min(steps.length - 1, current))
      const completedClean = completed.filter((i) => i < steps.length)
      return { v: NEXT_STEPS_PAYLOAD_VERSION, steps, current, completed: completedClean }
    }
    if (Array.isArray(j)) {
      const steps = j.map((x) => String(x ?? '').trim()).filter(Boolean)
      return { v: NEXT_STEPS_PAYLOAD_VERSION, steps, current: 0, completed: [] }
    }
  } catch {
    /* legacy string */
  }
  return { v: NEXT_STEPS_PAYLOAD_VERSION, steps: [trimmed], current: 0, completed: [] }
}

export function serializeNextStepsPayload(s: NextStepsPayload): string {
  return JSON.stringify({
    v: NEXT_STEPS_PAYLOAD_VERSION,
    steps: s.steps,
    current: s.current,
    completed: s.completed,
  })
}

/** First line to show in summary chips (current or first incomplete). */
export function nextStepsPrimaryLine(raw: string | undefined | null): string {
  const s = parseNextStepsPayload(raw)
  if (s.steps.length === 0) return ''
  const incomplete = s.steps.findIndex((_, i) => !s.completed.includes(i))
  const idx = incomplete >= 0 ? incomplete : Math.min(s.current, s.steps.length - 1)
  return s.steps[idx] ?? ''
}

/** True if there is at least one step worth surfacing. */
export function hasNextStepsContent(raw: string | undefined | null): boolean {
  return parseNextStepsPayload(raw).steps.length > 0
}

/**
 * Mark current step completed and advance focus to the next incomplete step.
 * If none selected, uses index 0.
 */
export function advanceNextStepsProgress(s: NextStepsPayload): NextStepsPayload {
  if (s.steps.length === 0) return s
  let cur = s.current
  if (cur < 0 || cur >= s.steps.length) cur = 0
  const done = new Set(s.completed)
  done.add(cur)
  let nextIdx = -1
  for (let i = cur + 1; i < s.steps.length; i++) {
    if (!done.has(i)) {
      nextIdx = i
      break
    }
  }
  if (nextIdx < 0) {
    for (let i = 0; i < s.steps.length; i++) {
      if (!done.has(i)) {
        nextIdx = i
        break
      }
    }
  }
  const newCurrent = nextIdx >= 0 ? nextIdx : cur
  return {
    v: NEXT_STEPS_PAYLOAD_VERSION,
    steps: s.steps,
    current: newCurrent,
    completed: [...done].sort((a, b) => a - b),
  }
}

/** Build payload from newline-separated editor text (edit mode). Resets progress indices. */
export function nextStepsFromLines(text: string): NextStepsPayload {
  const steps = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  return { v: NEXT_STEPS_PAYLOAD_VERSION, steps, current: 0, completed: [] }
}
