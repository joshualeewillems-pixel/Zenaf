/** Perspective Workout thread message (ephemeral; cleared on exit). */
export interface WorkoutMessage {
  id: string
  kind: 'user' | 'perspective' | 'seat'
  seatId?: string
  seatName?: string
  content: string
  timestamp: string
  /** Stable id for ResonanceSlider + sessionStorage */
  responseId: string
}

export function newWorkoutMessageId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `w-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

export function formatWorkoutContextBlock(thread: WorkoutMessage[], perspectiveLabel: string): string {
  const tail = thread.slice(-5)
  const lines: string[] = []
  for (const m of tail) {
    if (m.kind === 'user') lines.push(`User: ${m.content}`)
    else if (m.kind === 'perspective') lines.push(`${perspectiveLabel}: ${m.content}`)
    else lines.push(`${m.seatName ?? m.seatId ?? 'Seat'}: ${m.content}`)
  }
  return lines.join('\n\n')
}

export function countWorkoutRatingsInStorage(thread: WorkoutMessage[]): number {
  let n = 0
  for (const m of thread) {
    if (m.kind === 'user') continue
    try {
      const raw = sessionStorage.getItem(`atria.resonance.v1.${m.responseId}`)
      if (raw != null && raw.trim() !== '') n += 1
    } catch {
      /* ignore */
    }
  }
  return n
}
