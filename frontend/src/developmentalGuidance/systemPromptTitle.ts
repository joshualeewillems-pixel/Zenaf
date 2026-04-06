/**
 * Consistent "{EntityType} — {EntityName}" titles for system / guide prompts and reminder surfaces.
 */

const MAP_KIND_TO_LABEL: Record<string, string> = {
  seed: 'Idea',
  tree: 'Initiative',
  branch: 'Project',
  flower: 'Task',
  fruit: 'Outcome',
}

const VE_TYPE_TO_LABEL: Record<string, string> = {
  idea: 'Idea',
  initiative: 'Initiative',
  project: 'Project',
  task: 'Task',
  outcome: 'Outcome',
}

export const ENTITY_SCOPE_LABELS: Record<'idea' | 'initiative' | 'project' | 'task' | 'workspace', string> = {
  idea: 'Idea',
  initiative: 'Initiative',
  project: 'Project',
  task: 'Task',
  workspace: 'Workspace',
}

/** Map ontology kind, VE ref type, or server vm_entity_type string → display type. */
export function entityTypeLabelForKey(kindOrVeType: string): string {
  const k = kindOrVeType.trim().toLowerCase()
  if (k === 'nest') return 'Map'
  return (
    MAP_KIND_TO_LABEL[k] ??
    VE_TYPE_TO_LABEL[k] ??
    (kindOrVeType ? kindOrVeType.charAt(0).toUpperCase() + kindOrVeType.slice(1) : 'Workspace')
  )
}

export type MainViewHint = 'vision_map' | 'vision_execution' | string

/**
 * Thread guide bubbles: map selection, developmental inject, etc.
 */
export function formatSystemPromptContextTitle(opts: {
  mainView: MainViewHint
  /** Map node kind (seed | tree | …) or snapshot node_kind including nest */
  mapNodeKind?: string | null
  /** VE ref.veType when map kind not used */
  veType?: string | null
  nodeLabel?: string | null
  nestAggregate?: boolean
}): string {
  const name = (opts.nodeLabel ?? '').trim()
  if (opts.nestAggregate) {
    return name ? `Map — ${name}` : 'Map'
  }
  const kindKey = (opts.mapNodeKind ?? opts.veType ?? '').trim()
  if (!kindKey && !name) {
    return opts.mainView === 'vision_map' ? 'Map' : 'Workspace'
  }
  const typeLabel = entityTypeLabelForKey(kindKey)
  if (!name) {
    if (opts.mainView === 'vision_map') return 'Map'
    return `${typeLabel} — Untitled`
  }
  return `${typeLabel} — ${name}`
}

/** Vision map workspace-scoped deferred list (entity workspace / vision_map). */
export function mapWorkspaceRemindersTitle(selectedNodeLabel: string | null | undefined): string {
  const n = (selectedNodeLabel ?? '').trim()
  return n ? `Map — ${n}` : 'Map'
}

/** VE detail panels: deferred prompts for a specific entity row. */
export function formatVeEntityPromptTitle(
  entityType: keyof typeof ENTITY_SCOPE_LABELS,
  entityTitle: string | null | undefined,
): string {
  const label = ENTITY_SCOPE_LABELS[entityType]
  const n = (entityTitle ?? '').trim()
  if (!n) return entityType === 'workspace' ? 'Workspace' : `${label} — Untitled`
  return `${label} — ${n}`
}
