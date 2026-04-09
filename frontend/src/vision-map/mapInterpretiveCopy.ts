import type { MapNodePayload } from './ontology'
import type { VisionMapEntityBundle } from './blockersFromVe'
import { isStaleIso } from './deriveVisualState'
import { PROJECTION_UNSCOPED_INITIATIVE_ID } from './mapCouncilActions'
import { effectiveConditionSeverity } from './resolveConditionSeverity'

function projectsUnderInitiative(bundle: VisionMapEntityBundle, initiativeId: string) {
  return bundle.projects.filter((p) => {
    if (initiativeId === PROJECTION_UNSCOPED_INITIATIVE_ID) return !p.initiative_id
    return p.initiative_id === initiativeId
  })
}

/** One-line “living” read for the chat shell header. */
export function livingSummaryLine(p: MapNodePayload, bundle: VisionMapEntityBundle | null): string {
  const g = p.growth
  const sev = effectiveConditionSeverity(p)
  const growthPhrase =
    g === 'growing'
      ? 'is growing'
      : g === 'germinating'
        ? 'is germinating'
        : g === 'fruiting'
          ? 'is fruiting'
          : g === 'dormant'
            ? 'reads quiet'
            : g === 'decaying'
              ? 'shows strain'
              : g === 'pruned'
                ? 'is parked or closed'
                : 'is in motion'

  const noun =
    p.kind === 'tree'
      ? 'This tree'
      : p.kind === 'branch'
        ? 'This branch'
        : p.kind === 'flower'
          ? 'This flower'
          : p.kind === 'fruit'
            ? 'This fruit'
            : 'This seed'

  const stoneRead =
    sev >= 3
      ? 'Map stone: critical fractures.'
      : sev === 2
        ? 'Map stone: clear structural cracks.'
        : sev === 1
          ? 'Map stone: light hairline stress.'
          : 'Map stone: smooth.'

  if (p.kind === 'flower') {
    return `${noun} ${growthPhrase}. ${stoneRead}`
  }

  if (p.kind === 'fruit') {
    return `${noun} is an outcome signal from VE fields — confirm in operator tables when stakes are high.`
  }

  if (p.kind === 'seed') {
    return `${noun} ${growthPhrase}, still adjacent to formal structure. ${stoneRead}`
  }

  if (p.kind === 'branch' && bundle && p.ref.veType === 'project') {
    const tasks = bundle.tasks.filter((t) => t.project_id === p.ref.id)
    const blocked = tasks.filter((t) => /\bblock/i.test(t.status || '')).length
    const staleT = tasks.filter((t) => isStaleIso(t.updated_at, 30)).length
    const bits: string[] = []
    if (blocked >= 1) bits.push(`${blocked} flower${blocked > 1 ? 's' : ''} read blocked`)
    if (staleT >= 1) bits.push(`${staleT} quiet petal${staleT > 1 ? 's' : ''}`)
    const stem = `${noun} ${growthPhrase}`
    const tail = sev >= 1 ? ` ${stoneRead}` : ''
    if (bits.length === 0) return `${stem}; downstream tasks look even from timestamps.${tail}`
    return `${stem}, while ${bits.join('; ')}.${tail}`
  }

  if (p.kind === 'tree' && bundle && p.ref.veType === 'initiative') {
    const projs = projectsUnderInitiative(bundle, p.ref.id)
    const staleProj = projs.filter((pr) => isStaleIso(pr.updated_at, 21)).length
    let blockedFlowers = 0
    let staleFlowers = 0
    for (const pr of projs) {
      for (const t of bundle.tasks.filter((tk) => tk.project_id === pr.id)) {
        if (/\bblock/i.test(t.status || '')) blockedFlowers += 1
        if (isStaleIso(t.updated_at, 30)) staleFlowers += 1
      }
    }
    const bits: string[] = []
    if (staleProj >= 1) bits.push(`${staleProj} branch${staleProj > 1 ? 'es' : ''} read stale`)
    if (blockedFlowers >= 1)
      bits.push(`${blockedFlowers} blocked flower${blockedFlowers > 1 ? 's' : ''} under the canopy`)
    if (staleFlowers >= 3) bits.push(`${staleFlowers} quiet tasks across the field`)
    const stem = `${noun} ${growthPhrase}`
    const tail = sev >= 1 ? ` ${stoneRead}` : ''
    if (bits.length === 0) return `${stem}; the understory looks evenly tended from timestamps.${tail}`
    return `${stem}, while ${bits.join('; ')}.${tail}`
  }

  return `${noun} ${growthPhrase}. ${stoneRead}`
}

/** Prose read on the node’s state — not raw enum labels. */
export function interpretiveNodeSummary(p: MapNodePayload): string {
  const kind = p.kind
  const g = p.growth
  const sev = effectiveConditionSeverity(p)

  const kindPhrase =
    kind === 'tree'
      ? 'This initiative anchors a column of execution on the map.'
      : kind === 'branch'
        ? 'This project carries concrete work under an initiative.'
        : kind === 'flower'
          ? 'This task is a small, actionable petal on a branch.'
          : kind === 'fruit'
            ? 'This outcome is projected as a result signal (from VE text fields), not a separate table row.'
            : 'This idea is the seed before or beside formalized initiatives.'

  let life = ''
  if (g === 'germinating') life = 'Lifecycle reads early: forming, not yet fully in motion.'
  else if (g === 'growing') life = 'Lifecycle reads active: energy is going into forward motion.'
  else if (g === 'fruiting') life = 'Lifecycle reads mature: delivery or completion pressure shows through.'
  else if (g === 'decaying') life = 'Lifecycle reads strained: risk, blockage, or decay signals in status.'
  else if (g === 'dormant') life = 'Lifecycle reads quiet: little motion signal from status.'
  else if (g === 'pruned') life = 'Lifecycle reads closed or parked: treat as archival context.'

  let tension = ''
  if (sev >= 3) {
    tension =
      'Structural read: heavy fractures on the map stone — critical instability (veto, hard block, or equivalent). Cracks are the signal, not glow or hatch.'
  } else if (sev === 2) {
    tension =
      'Structural read: branching cracks on the map stone — execution or supervision tension needs attention before it widens.'
  } else if (sev === 1) {
    tension =
      'Structural read: hairline cracks on the map stone — light stress; worth a glance before trusting the snapshot.'
  } else {
    tension = 'Structural read: smooth stone — no material fracture signal on the map for this row.'
  }

  return [kindPhrase, life, tension].filter(Boolean).join(' ')
}

export function tensionBadges(p: MapNodePayload): { key: string; label: string; tone: 'amber' | 'slate' | 'red' | 'violet' }[] {
  const out: { key: string; label: string; tone: 'amber' | 'slate' | 'red' | 'violet' }[] = []
  const sev = effectiveConditionSeverity(p)
  if (sev >= 3) out.push({ key: 'critical', label: 'Critical', tone: 'slate' })
  else if (sev === 2) out.push({ key: 'fractured', label: 'Fractured', tone: 'slate' })
  else if (sev === 1) out.push({ key: 'stressed', label: 'Stressed', tone: 'slate' })
  if (p.growth === 'decaying') out.push({ key: 'at-risk', label: 'At risk', tone: 'violet' })
  return out
}
