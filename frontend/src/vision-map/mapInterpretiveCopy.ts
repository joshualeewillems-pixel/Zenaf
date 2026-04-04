import type { MapNodePayload } from './ontology'
import type { VisionMapEntityBundle } from './blockersFromVe'
import { isStaleIso } from './deriveVisualState'
import { PROJECTION_UNSCOPED_INITIATIVE_ID } from './mapCouncilActions'

function projectsUnderInitiative(bundle: VisionMapEntityBundle, initiativeId: string) {
  return bundle.projects.filter((p) => {
    if (initiativeId === PROJECTION_UNSCOPED_INITIATIVE_ID) return !p.initiative_id
    return p.initiative_id === initiativeId
  })
}

/** One-line “living” read for the chat shell header. */
export function livingSummaryLine(p: MapNodePayload, bundle: VisionMapEntityBundle | null): string {
  const g = p.growth
  const c = p.condition
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

  if (p.kind === 'flower') {
    if (c === 'blocked') return `${noun} is blocked — the stem should read tense until cleared.`
    if (c === 'stale') return `${noun} has gone quiet; worth a nudge or scope check.`
    if (c === 'teacher-warned') return `${noun} sits under a teacher warning — keep supervision in view.`
    if (c === 'teacher-vetoed') return `${noun} is framed by teacher veto — treat downstream text as supervised.`
    return `${noun} ${growthPhrase}; the row reads ${c === 'healthy' ? 'steady' : 'mixed'}.`
  }

  if (p.kind === 'fruit') {
    return `${noun} is an outcome signal from VE fields — confirm in operator tables when stakes are high.`
  }

  if (p.kind === 'seed') {
    if (c === 'stale') return `${noun} has rested a long while; promote, link, or prune intentionally.`
    if (c === 'blocked') return `${noun} carries tension at the root before it becomes a tree.`
    return `${noun} ${growthPhrase}, still adjacent to formal structure.`
  }

  if (p.kind === 'branch' && bundle && p.ref.veType === 'project') {
    const tasks = bundle.tasks.filter((t) => t.project_id === p.ref.id)
    const blocked = tasks.filter((t) => /\bblock/i.test(t.status || '')).length
    const staleT = tasks.filter((t) => isStaleIso(t.updated_at, 30)).length
    const bits: string[] = []
    if (blocked >= 1) bits.push(`${blocked} flower${blocked > 1 ? 's' : ''} read blocked`)
    if (staleT >= 1) bits.push(`${staleT} quiet petal${staleT > 1 ? 's' : ''}`)
    if (c === 'teacher-warned') bits.push('a teacher warning rides this branch')
    if (c === 'teacher-vetoed') bits.push('teacher veto touches this branch')
    const stem = `${noun} ${growthPhrase}`
    if (bits.length === 0) return `${stem}; downstream tasks look even from timestamps.`
    return `${stem}, while ${bits.join('; ')}.`
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
    if (c === 'teacher-warned') bits.push('teacher conflict signal in scope')
    if (c === 'teacher-vetoed') bits.push('teacher veto in scope')
    const stem = `${noun} ${growthPhrase}`
    if (bits.length === 0) return `${stem}; the understory looks evenly tended from timestamps.`
    return `${stem}, while ${bits.join('; ')}.`
  }

  return `${noun} ${growthPhrase}; ${c === 'healthy' ? 'supervision reads calm.' : `condition reads ${c.replace('teacher-', '')}.`}`
}

/** Prose read on the node’s state — not raw enum labels. */
export function interpretiveNodeSummary(p: MapNodePayload): string {
  const kind = p.kind
  const g = p.growth
  const c = p.condition

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
  if (c === 'blocked') {
    tension =
      'Tension: blocked — execution is waiting on something; the map dims and jitters slightly to draw the eye without screaming.'
  } else if (c === 'stale') {
    tension =
      'Tension: stale — time has passed without fresh updates; worth a quick operator check before trusting the snapshot.'
  } else if (c === 'teacher-warned') {
    tension =
      'Tension: conflicted — teacher supervision flagged a disagreement or risk while keeping native output visible.'
  } else if (c === 'teacher-vetoed') {
    tension =
      'Tension: high — teacher enforcement replaced or refused native output; treat recommendations as supervisory.'
  } else {
    tension = 'Supervision channel reads calm: no veto or warning correlated to this node from recent studio runs.'
  }

  return [kindPhrase, life, tension].filter(Boolean).join(' ')
}

export function tensionBadges(p: MapNodePayload): { key: string; label: string; tone: 'amber' | 'slate' | 'red' | 'violet' }[] {
  const out: { key: string; label: string; tone: 'amber' | 'slate' | 'red' | 'violet' }[] = []
  if (p.condition === 'blocked') out.push({ key: 'blocked', label: 'Blocked', tone: 'amber' })
  if (p.condition === 'stale') out.push({ key: 'stale', label: 'Stale', tone: 'slate' })
  if (p.condition === 'teacher-warned') out.push({ key: 'conflicted', label: 'Conflicted', tone: 'amber' })
  if (p.condition === 'teacher-vetoed') out.push({ key: 'vetoed', label: 'Vetoed', tone: 'red' })
  if (p.growth === 'decaying') out.push({ key: 'at-risk', label: 'At risk', tone: 'violet' })
  return out
}
