import type { ConditionState, GrowthState } from './ontology'
/**
 * Derive growth from VE-style status strings (read-only heuristic; prototype-friendly).
 */
export function growthFromStatus(status: string | null | undefined, opts?: { doneRatio?: number }): GrowthState {
  const s = (status || '').trim().toLowerCase()
  const ratio = opts?.doneRatio
  if (s.includes('cancel') || s.includes('kill') || s.includes('archived')) return 'pruned'
  if (s.includes('blocked') || s.includes('at risk') || s.includes('at_risk')) return 'decaying'
  if (s.includes('done') || s.includes('complete') || s.includes('shipped')) return 'fruiting'
  if (s.includes('draft') || s.includes('evaluat')) return 'germinating'
  if (typeof ratio === 'number' && ratio >= 0.85) return 'fruiting'
  if (typeof ratio === 'number' && ratio <= 0.15) return 'germinating'
  if (s.includes('active') || s.includes('progress') || s.includes('in flight')) return 'growing'
  return 'growing'
}

/**
 * Idea-stone growth driven by checklist progress: the stone visibly ripens as the
 * idea's checklist fills in. No checklist → seed (germinating); partial → growing;
 * all done → ripe (fruiting); graduated → fruiting. Terminal/negative statuses
 * (pruned, decaying) still win over progress.
 */
export function ideaGrowthFromChecklist(
  status: string | null | undefined,
  progress?: { total: number; done: number } | null,
): GrowthState {
  const s = (status || '').trim().toLowerCase()
  if (s.includes('cancel') || s.includes('kill') || s.includes('archived')) return 'pruned'
  if (s.includes('blocked') || s.includes('at risk') || s.includes('at_risk')) return 'decaying'
  if (s.includes('graduat')) return 'fruiting'
  const total = progress?.total ?? 0
  if (total <= 0) return 'germinating'
  const done = Math.min(Math.max(progress?.done ?? 0, 0), total)
  return growthFromStatus(status, { doneRatio: done / total })
}

/**
 * Derive condition channel from flags + staleness (prototype; teacher fields from last council run metadata when wired).
 */
export function conditionFromSignals(input: {
  blocked?: boolean
  stale?: boolean
  teacher_vetoed?: boolean
  teacher_warning?: boolean
}): ConditionState {
  if (input.teacher_vetoed) return 'teacher-vetoed'
  if (input.teacher_warning) return 'teacher-warned'
  if (input.blocked) return 'blocked'
  if (input.stale) return 'stale'
  return 'healthy'
}

/** Days since ISO date string → stale for demo thresholds */
export function isStaleIso(updatedAt: string | undefined, thresholdDays = 21): boolean {
  if (!updatedAt) return false
  const t = Date.parse(updatedAt)
  if (Number.isNaN(t)) return false
  const days = (Date.now() - t) / (86400 * 1000)
  return days > thresholdDays
}

export function growthClass(g: GrowthState): string {
  const map: Record<GrowthState, string> = {
    dormant: 'bg-slate-800/90 border-slate-600',
    germinating: 'bg-sky-950/80 border-sky-700/60',
    growing: 'bg-emerald-950/70 border-emerald-600/50',
    fruiting: 'bg-amber-950/70 border-amber-500/45',
    decaying: 'bg-orange-950/60 border-orange-600/50',
    pruned: 'bg-slate-900/95 border-slate-600 opacity-75',
  }
  return map[g] || map.growing
}
