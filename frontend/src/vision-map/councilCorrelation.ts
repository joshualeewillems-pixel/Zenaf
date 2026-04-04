import type { CouncilTeacherPreview, MapEntityRef } from './ontology'
import type { StudioCouncilRunRow } from './studioCouncilTypes'

function normVeType(t: string | undefined | null): string {
  const x = (t || '').trim().toLowerCase().replace(/s$/, '')
  if (x === 'unknown') return ''
  return x
}

function subjectMatchesRef(ref: MapEntityRef, r: StudioCouncilRunRow): boolean {
  const sub = r.native_artifact?.subject
  if (!sub || typeof sub !== 'object') return false
  const sid = sub.entity_id
  const st = normVeType(sub.entity_type || sub.type)
  if (!sid || sid !== ref.id) return false
  const rt = normVeType(ref.veType)
  return st === rt || st === ''
}

export function councilRunToPreview(r: StudioCouncilRunRow): CouncilTeacherPreview {
  return {
    teacher_mode: r.teacher_mode,
    teacher_enforcement_mode: r.teacher_enforcement_mode ?? r.teacher_mode,
    teacher_vetoed: Boolean(r.teacher_vetoed),
    teacher_warning: Boolean(r.teacher_warning),
    teacher_final_source: r.teacher_final_source,
    teacher_reason_codes: Array.isArray(r.teacher_reason_codes) ? r.teacher_reason_codes : [],
    last_run_at: r.created_at,
    summary: r.teacher_notes
      ? String(r.teacher_notes).slice(0, 600)
      : r.native_artifact?.question
        ? `Last stored question (truncated): ${String(r.native_artifact.question).slice(0, 220)}…`
        : undefined,
  }
}

/**
 * Best-effort match: artifact.subject vs VE id/type, then question text contains id.
 * Runs should be newest-first (API order).
 */
export function findCouncilPreviewForRef(runs: StudioCouncilRunRow[], ref: MapEntityRef): CouncilTeacherPreview | undefined {
  for (const r of runs) {
    if (subjectMatchesRef(ref, r)) return councilRunToPreview(r)
  }
  for (const r of runs) {
    const q = r.native_artifact?.question
    if (q && String(q).includes(ref.id)) return councilRunToPreview(r)
  }
  return undefined
}

/** Newest-first `runs` → first matching row (for recency checks). */
export function getLatestCouncilRunForRef(
  runs: StudioCouncilRunRow[],
  ref: MapEntityRef,
): StudioCouncilRunRow | undefined {
  for (const r of runs) {
    if (subjectMatchesRef(ref, r)) return r
  }
  for (const r of runs) {
    const q = r.native_artifact?.question
    if (q && String(q).includes(ref.id)) return r
  }
  return undefined
}
