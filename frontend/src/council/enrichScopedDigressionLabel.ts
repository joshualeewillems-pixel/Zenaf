/**
 * Replace generic "Entity d4aca9c0…" style labels from entity-mention parsing with real titles
 * when the open idea editor or VE bundle has them.
 */
import type { EntityMentionOpenPayload } from '../components/EntityMentionText'
import type { CouncilIdeaLabelsSnapshot } from '../vision-execution'
import type { VisionMapEntityBundle } from '../vision-map/blockersFromVe'

const ENTITY_STUB_RE = /^entity\s+[0-9a-f]{8}/i

export function isGenericScopedEntityLabel(label: string): boolean {
  const t = (label || '').trim()
  if (!t) return true
  if (ENTITY_STUB_RE.test(t)) return true
  if (/^(task|idea|project|initiative)\s+[0-9a-f]{8}/i.test(t)) return true
  return false
}

export function enrichScopedDigressionLabel(
  p: EntityMentionOpenPayload,
  opts: {
    ideaLabels: CouncilIdeaLabelsSnapshot | null
    bundle: VisionMapEntityBundle | null
  },
): EntityMentionOpenPayload {
  if (!isGenericScopedEntityLabel(p.label)) {
    return p
  }
  const id = p.entityId.trim()
  const et = (p.entityType || '').toLowerCase()

  if (et === 'idea') {
    if (opts.ideaLabels?.entity_id === id && opts.ideaLabels.ve_focus_title?.trim()) {
      return { ...p, label: `Idea · ${opts.ideaLabels.ve_focus_title.trim()}` }
    }
    const row = opts.bundle?.ideas?.find((i) => i.id === id)
    if (row?.title?.trim()) {
      return { ...p, label: `Idea · ${row.title.trim()}` }
    }
  }
  if (et === 'task') {
    const row = opts.bundle?.tasks?.find((t) => t.id === id)
    if (row?.title?.trim()) {
      return { ...p, label: `Task · ${row.title.trim()}` }
    }
  }
  if (et === 'project') {
    const row = opts.bundle?.projects?.find((x) => x.id === id)
    if (row?.title?.trim()) {
      return { ...p, label: `Project · ${row.title.trim()}` }
    }
  }
  if (et === 'initiative') {
    const row = opts.bundle?.initiatives?.find((x) => x.id === id)
    if (row?.title?.trim()) {
      return { ...p, label: `Initiative · ${row.title.trim()}` }
    }
  }
  return p
}
