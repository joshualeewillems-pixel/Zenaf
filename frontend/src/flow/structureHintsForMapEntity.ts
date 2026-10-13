import type { VisionMapEntityBundle } from '../vision-map/blockersFromVe'
import type { MapEntityRef } from '../vision-map/ontology'

export function structureHintsForEntity(ref: MapEntityRef, bundle: VisionMapEntityBundle | null): {
  hasBrief?: boolean
  hasNextStep?: boolean
  hasDeps?: boolean
} {
  if (!bundle) return {}
  if (ref.veType === 'idea') {
    const e = bundle.ideas.find((x) => x.id === ref.id)
    if (!e) return {}
    const briefLen = Math.max((e.description || '').trim().length, (e.summary || '').trim().length)
    return { hasBrief: briefLen >= 40 }
  }
  if (ref.veType === 'initiative') {
    const e = bundle.initiatives.find((x) => x.id === ref.id)
    if (!e) return {}
    return {
      hasBrief: (e.brief || '').trim().length >= 30,
      hasNextStep: (e.next_step_ai || '').trim().length > 5,
      hasDeps: (e.dependencies || '').trim().length > 5,
    }
  }
  if (ref.veType === 'project') {
    const e = bundle.projects.find((x) => x.id === ref.id)
    if (!e) return {}
    return {
      hasBrief: (e.brief || '').trim().length >= 25,
      hasNextStep: (e.next_step_ai || '').trim().length > 5,
      hasDeps: (e.required_assets?.length ?? 0) > 0,
    }
  }
  if (ref.veType === 'task') {
    const e = bundle.tasks.find((x) => x.id === ref.id)
    if (!e) return {}
    return {
      hasBrief: (e.description || '').trim().length >= 30,
      hasDeps: (e.dependency_ids?.length ?? 0) > 0,
    }
  }
  return {}
}
