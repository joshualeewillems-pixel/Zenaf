import type { VisionMapEntityBundle } from '../../vision-map/blockersFromVe'
import type { VeGraphDataSnapshot } from './graphSliceTypes'
import type { EntityType, FieldKind, FocusContextCore, FocusDescriptor, FocusSurface } from './types'

/** Sentinel field for entity selection without a focused text control (VE + map). */
export const CONVERSATION_ENTITY_FIELD_KEY = '__conversation_entity__'

const SENTINEL_FIELD_KIND: FieldKind = 'idea_body'

/** Mirrors `VESelection` from VisionExecutionView — kept local to avoid circular imports. */
type VeSelectionCore = {
  tab: 'execution' | 'initiatives' | 'projects' | 'tasks' | 'assets' | 'ideas'
  initiativeId?: string
  projectId?: string
  taskId?: string
  ideaId?: string
  assetId?: string
}

function titleForSelection(sel: VeSelectionCore, b: VisionMapEntityBundle | null | undefined): string {
  if (!b) return 'Selected entity'
  if (sel.ideaId) {
    const row = b.ideas.find((x) => x.id === sel.ideaId)
    return row?.title?.trim() || 'Idea'
  }
  if (sel.initiativeId) {
    const row = b.initiatives.find((x) => x.id === sel.initiativeId)
    return row?.title?.trim() || 'Initiative'
  }
  if (sel.projectId) {
    const row = b.projects.find((x) => x.id === sel.projectId)
    return row?.title?.trim() || 'Project'
  }
  if (sel.taskId) {
    const row = b.tasks.find((x) => x.id === sel.taskId)
    return row?.title?.trim() || 'Task'
  }
  return 'Selected entity'
}

function selectionToEntity(sel: VeSelectionCore): { entity_type: EntityType; entity_id: string } | null {
  if (sel.ideaId) return { entity_type: 'idea', entity_id: sel.ideaId }
  if (sel.initiativeId) return { entity_type: 'initiative', entity_id: sel.initiativeId }
  if (sel.projectId) return { entity_type: 'project', entity_id: sel.projectId }
  if (sel.taskId) return { entity_type: 'task', entity_id: sel.taskId }
  return null
}

/** Sent on POST /run ``council_preflight.ve_selected_entity`` — open VE row / list selection, independent of field focus. */
export type VeSelectedEntityPayload = {
  entity_type: EntityType
  entity_id: string
  title: string
}

export function veSelectedEntityPayloadFromSelection(
  sel: VeSelectionCore | null | undefined,
  bundle: VisionMapEntityBundle | null | undefined,
): VeSelectedEntityPayload | null {
  if (!sel) return null
  const ent = selectionToEntity(sel)
  if (!ent) return null
  return { ...ent, title: titleForSelection(sel, bundle) }
}

/** Focus descriptor for list/map selection without a focused text control. */
export function focusDescriptorFromVeSelection(
  sel: VeSelectionCore,
  bundle: VisionMapEntityBundle | null | undefined,
  surface: FocusSurface,
): FocusDescriptor | null {
  const ent = selectionToEntity(sel)
  if (!ent) return null
  const label = titleForSelection(sel, bundle)
  return {
    surface,
    entity_type: ent.entity_type,
    entity_id: ent.entity_id,
    field_key: CONVERSATION_ENTITY_FIELD_KEY,
    field_label: `${ent.entity_type}: ${label}`,
    field_kind: SENTINEL_FIELD_KIND,
  }
}

/** Core pointer for council preflight when the focus bridge has no field focus but `veSelection` is set. */
export function veFocusCoreFromVeSelection(
  sel: VeSelectionCore | null | undefined,
  bundle: VisionMapEntityBundle | null | undefined,
  surface: FocusSurface = 'vision_execution',
): FocusContextCore | null {
  if (!sel) return null
  const desc = focusDescriptorFromVeSelection(sel, bundle, surface)
  if (!desc) return null
  return {
    ...desc,
    surface: desc.surface ?? surface,
  }
}

/** Minimal graph snapshot from map bundle so `resolveGraphSliceVE` can run off-map. */
export function veGraphSnapshotFromBundle(bundle: VisionMapEntityBundle | null | undefined): VeGraphDataSnapshot | null {
  if (!bundle) return null
  return {
    coreProfiles: [],
    ideas: bundle.ideas,
    initiatives: bundle.initiatives,
    projects: bundle.projects,
    tasks: bundle.tasks,
    persons: [],
    assets: [],
    capacityProfiles: [],
  }
}
