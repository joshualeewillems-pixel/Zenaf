/**
 * Semantic grouping for map awareness strip (internal) vs flat one-line UI.
 * Data source: GET /vision-execution/radar only — no inbox/inventory fabrication.
 */
import type { RadarResponse } from './types'

/** DOM / scroll targets — must match `ve-radar-bucket-*` ids in VisionExecutionView Radar tab. */
export type VeRadarBucketId =
  | 'act_now'
  | 'blocked'
  | 'high_value_stalled'
  | 'unanchored'
  | 'kill_candidates'
  | 'overcapacity'
  | 'signals'

export type VeRadarSemanticGroups = {
  urgency: { act_now: number; blocked: number }
  drift: { stalled: number; unanchored: number }
  risk: { kill_candidates: number; overcapacity: number }
  signals: { open: number }
}

export function buildRadarSemanticGroups(data: RadarResponse | null): VeRadarSemanticGroups | null {
  if (!data) return null
  const signals = data.signals ?? []
  return {
    urgency: { act_now: data.act_now?.length ?? 0, blocked: data.blocked?.length ?? 0 },
    drift: { stalled: data.high_value_stalled?.length ?? 0, unanchored: data.unanchored?.length ?? 0 },
    risk: { kill_candidates: data.kill_candidates?.length ?? 0, overcapacity: data.overcapacity?.length ?? 0 },
    signals: { open: signals.length },
  }
}

/** One clickable segment for the strip (flat UI). Omit zero counts in the component. */
export type VeRadarStripSegment = {
  bucket: VeRadarBucketId
  /** Ultra-short label for single-line strip */
  label: string
  count: number
}

const SEGMENT_DEF: { bucket: VeRadarBucketId; label: string; pick: (g: VeRadarSemanticGroups) => number }[] = [
  { bucket: 'act_now', label: 'att', pick: (g) => g.urgency.act_now },
  { bucket: 'blocked', label: 'blk', pick: (g) => g.urgency.blocked },
  { bucket: 'high_value_stalled', label: 'stall', pick: (g) => g.drift.stalled },
  { bucket: 'unanchored', label: 'unanch', pick: (g) => g.drift.unanchored },
  { bucket: 'kill_candidates', label: 'kill', pick: (g) => g.risk.kill_candidates },
  { bucket: 'overcapacity', label: 'cap', pick: (g) => g.risk.overcapacity },
  { bucket: 'signals', label: 'sig', pick: (g) => g.signals.open },
]

export function buildRadarStripSegments(groups: VeRadarSemanticGroups | null): VeRadarStripSegment[] {
  if (!groups) return []
  return SEGMENT_DEF.map((d) => ({
    bucket: d.bucket,
    label: d.label,
    count: d.pick(groups),
  })).filter((s) => s.count > 0)
}

/**
 * First bucket to scroll when user wants "risk" overview: prefer kill, then capacity, then signals.
 */
export function firstNonEmptyRiskBucket(groups: VeRadarSemanticGroups | null): VeRadarBucketId | null {
  if (!groups) return null
  if (groups.risk.kill_candidates > 0) return 'kill_candidates'
  if (groups.risk.overcapacity > 0) return 'overcapacity'
  if (groups.signals.open > 0) return 'signals'
  return null
}

/** Non-interactive hint line: counts only, priority-ordered (no dashboard). */
export function buildMostUrgentHint(groups: VeRadarSemanticGroups | null): string | null {
  if (!groups) return null
  const parts: string[] = []
  if (groups.urgency.blocked > 0) parts.push(`${groups.urgency.blocked} blocked`)
  if (groups.urgency.act_now > 0) parts.push(`${groups.urgency.act_now} need attention`)
  if (groups.drift.stalled > 0) parts.push(`${groups.drift.stalled} stalled`)
  if (groups.drift.unanchored > 0) parts.push(`${groups.drift.unanchored} unanchored`)
  if (groups.risk.kill_candidates > 0) parts.push(`${groups.risk.kill_candidates} watch/kill`)
  if (groups.risk.overcapacity > 0) parts.push(`${groups.risk.overcapacity} over capacity`)
  if (groups.signals.open > 0) parts.push(`${groups.signals.open} signals`)
  if (parts.length === 0) return null
  return `Most urgent: ${parts.slice(0, 3).join(', ')}`
}
