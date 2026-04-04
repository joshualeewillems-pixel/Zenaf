import type { VESelection } from '../vision-execution'
import type { MapEntityRef, MapNodePayload } from './ontology'

export const PROJECTION_UNSCOPED_INITIATIVE_ID = '_projection_unscoped_'

export function councilAnchorRef(p: MapNodePayload): MapEntityRef {
  if (p.ref.veType === 'outcome' && p.parentRef) return p.parentRef
  return p.ref
}

/** Map a VE row ref to the execution UI selection (ideas tab vs execution subtree). */
export function veSelectionFromEntityRef(ref: MapEntityRef): VESelection | null {
  if (ref.veType === 'idea') return { tab: 'ideas', ideaId: ref.id }
  if (ref.veType === 'initiative') {
    if (ref.id === PROJECTION_UNSCOPED_INITIATIVE_ID) return { tab: 'execution' }
    return { tab: 'initiatives', initiativeId: ref.id }
  }
  if (ref.veType === 'project') return { tab: 'projects', projectId: ref.id }
  if (ref.veType === 'task') {
    return {
      tab: 'tasks',
      taskId: ref.id,
      projectId: ref.projectId ?? undefined,
    }
  }
  return null
}

export function veSelectionFromMapPayload(p: MapNodePayload): VESelection | null {
  return veSelectionFromEntityRef(councilAnchorRef(p))
}

export function councilQuestionForPayload(p: MapNodePayload): string {
  const anchor = councilAnchorRef(p)
  const headline = p.ref.veType === 'outcome' ? `Outcome note: ${p.label}` : p.label
  const detail = p.summaryLines.filter(Boolean).join('\n')
  return [
    'Vision map → Council: review this execution slice.',
    `Entity: ${anchor.veType} \`${anchor.id}\`.`,
    `Focus: ${headline}`,
    detail ? `Context:\n${detail}` : '',
    'Please surface risks, dependencies, and one concrete next move.',
  ]
    .filter(Boolean)
    .join('\n\n')
}

const CODE_HELP: Record<string, string> = {
  privacy_secret_externalization:
    'Supervision flagged possible secret or credential material in (or requested by) the native draft. Prefer refusal, redaction, or clarify-first.',
  wrong_domain_grounding:
    'Heuristic mismatch: answer looked like the wrong domain vs the prompt (e.g. electrical vs software). Verify grounding before acting.',
  fabricated_facts_citations_risk:
    'Native text may have invented specifics (numbers, citations, “sources”) under weak context. Treat as unverified.',
  clarify_first_violation:
    'Prompt pressure suggested clarification or refusal; native proceeded without enough guardrails.',
  teacher_native_disagreement:
    'Teacher pass disagreed with native on summary or next-step alignment (shadow/warn signal).',
}

export function explainTeacherMarkdown(p: MapNodePayload): string {
  const ct = p.councilTeacher
  if (!ct) {
    return 'No correlated council teacher run for this node (or studio history unavailable). Run council from Workspace with subject metadata to improve linkage.'
  }
  const lines: string[] = []
  lines.push(`Enforcement mode: ${ct.teacher_enforcement_mode ?? ct.teacher_mode ?? '—'}`)
  if (ct.teacher_vetoed) {
    lines.push('Veto: native output was blocked; client received teacher-corrected text or a safe refusal string.')
  } else if (ct.teacher_warning) {
    lines.push('Warning: native output was kept; response metadata flagged teacher concern.')
  } else {
    lines.push('Shadow / no flag: teacher ran for comparison; native text was final unless policy escalated elsewhere.')
  }
  if (ct.teacher_final_source) lines.push(`Final source: ${ct.teacher_final_source}`)
  const codes = ct.teacher_reason_codes || []
  if (codes.length) {
    lines.push('Reason codes:')
    for (const c of codes) {
      lines.push(`- ${c}${CODE_HELP[c] ? ` — ${CODE_HELP[c]}` : ''}`)
    }
  }
  if (ct.summary) lines.push(`Notes: ${ct.summary}`)
  return lines.join('\n\n')
}
