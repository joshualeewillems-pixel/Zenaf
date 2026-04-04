/**
 * Build the same MapTriadDevelopmentalSnapshot shape as VisionMapView, but from VE field focus
 * + a live entity bundle (so council/Zenaf get growth-triad scaffolding off the vision map tab).
 */
import type { FocusContextCore } from '../vision-execution/focus/types'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import type { VisionMapEntityBundle } from '../vision-map/blockersFromVe'
import { detectMissingDimensions } from '../vision-map/guidanceScripts'
import { computeGrowthTriad } from '../vision-map/mapGrowthMetrics'
import {
  deriveFertilizerPulse,
  vitalForIdea,
  vitalForInitiative,
  vitalForProject,
  vitalForTask,
  waterLevelFromVital,
} from '../vision-map/mapVitalForces'
import type { MapEntityRef, MapNodePayload } from '../vision-map/ontology'
import { conditionFromSignals, growthFromStatus, isStaleIso } from '../vision-map/deriveVisualState'
import type { MapTriadDevelopmentalSnapshot } from './types'

function clip(s: string, n: number): string {
  const t = s.trim()
  if (t.length <= n) return t
  return `${t.slice(0, n - 1)}…`
}

function veFocusEntityToMapKind(
  t: string,
): 'seed' | 'tree' | 'branch' | 'flower' | 'fruit' | null {
  switch (t.toLowerCase()) {
    case 'idea':
      return 'seed'
    case 'initiative':
      return 'tree'
    case 'project':
      return 'branch'
    case 'task':
      return 'flower'
    default:
      return null
  }
}

function mapKindToVeType(kind: MapNodePayload['kind']): MapEntityRef['veType'] | null {
  switch (kind) {
    case 'seed':
      return 'idea'
    case 'tree':
      return 'initiative'
    case 'branch':
      return 'project'
    case 'flower':
      return 'task'
    default:
      return null
  }
}

function syntheticFromIdea(idea: Idea): MapNodePayload {
  const ref: MapEntityRef = { veType: 'idea', id: idea.id }
  const v = vitalForIdea(idea)
  return {
    kind: 'seed',
    label: idea.title || 'Untitled idea',
    subtitle: 'Idea (seed)',
    ref,
    summaryLines: [
      clip(idea.summary || idea.description || '', 240),
      `Status: ${idea.status}`,
      idea.desired_outcome ? `Desired outcome: ${clip(idea.desired_outcome, 160)}` : '',
    ].filter(Boolean),
    growth: growthFromStatus(idea.status),
    condition: conditionFromSignals({ stale: isStaleIso(idea.updated_at, 45) }),
    water_level: waterLevelFromVital(v),
    fertilizer_pulse: deriveFertilizerPulse(ref, idea.updated_at ?? null, []),
  }
}

function syntheticFromInitiative(init: Initiative): MapNodePayload {
  const ref: MapEntityRef = { veType: 'initiative', id: init.id }
  const v = vitalForInitiative(init)
  return {
    kind: 'tree',
    label: init.title || 'Untitled initiative',
    subtitle: 'Initiative (tree)',
    ref,
    summaryLines: [clip(init.brief || '', 240), `Status: ${init.status}`].filter(Boolean),
    growth: growthFromStatus(init.status),
    condition: conditionFromSignals({ stale: isStaleIso(init.updated_at, 45) }),
    water_level: waterLevelFromVital(v),
    fertilizer_pulse: deriveFertilizerPulse(ref, init.updated_at ?? null, []),
  }
}

function syntheticFromProject(proj: Project): MapNodePayload {
  const ref: MapEntityRef = { veType: 'project', id: proj.id }
  const v = vitalForProject(proj)
  return {
    kind: 'branch',
    label: proj.title || 'Untitled project',
    subtitle: 'Project (branch)',
    ref,
    summaryLines: [clip(proj.brief || '', 240), `Status: ${proj.status}`].filter(Boolean),
    growth: growthFromStatus(proj.status),
    condition: conditionFromSignals({ stale: isStaleIso(proj.updated_at, 45) }),
    water_level: waterLevelFromVital(v),
    fertilizer_pulse: deriveFertilizerPulse(ref, proj.updated_at ?? null, []),
  }
}

function syntheticFromTask(task: Task): MapNodePayload {
  const ref: MapEntityRef = { veType: 'task', id: task.id, projectId: task.project_id ?? null }
  const v = vitalForTask(task)
  return {
    kind: 'flower',
    label: task.title || 'Untitled task',
    subtitle: 'Task (flower)',
    ref,
    summaryLines: [clip(task.description || '', 200), `Status: ${task.status}`].filter(Boolean),
    growth: growthFromStatus(task.status),
    condition: conditionFromSignals({ stale: isStaleIso(task.updated_at, 45) }),
    water_level: waterLevelFromVital(v),
    fertilizer_pulse: deriveFertilizerPulse(ref, task.updated_at ?? null, []),
  }
}

function syntheticFallback(
  entityType: string,
  entityId: string,
  lineageLabels: string[] | undefined,
): MapNodePayload | null {
  const kind = veFocusEntityToMapKind(entityType)
  if (!kind) return null
  const veT = mapKindToVeType(kind)
  if (!veT) return null
  const ref: MapEntityRef = { veType: veT, id: entityId }
  const labels = lineageLabels?.filter((s) => s.trim()) ?? []
  const labelFromLineage = labels.length > 0 ? labels[labels.length - 1]!.trim() : ''
  return {
    kind,
    label: labelFromLineage || `Focused ${entityType}`,
    ref,
    summaryLines: [],
    growth: 'growing',
    condition: 'healthy',
    water_level: 'medium',
    fertilizer_pulse: false,
  }
}

function buildSyntheticPayload(
  core: Pick<FocusContextCore, 'entity_type' | 'entity_id' | 'lineage_labels'>,
  bundle: VisionMapEntityBundle | null | undefined,
): MapNodePayload | null {
  const id = core.entity_id?.trim()
  if (!id) return null
  const et = core.entity_type?.toLowerCase()
  const b = bundle ?? null

  if (et === 'idea' && b) {
    const row = b.ideas.find((x) => x.id === id)
    if (row) return syntheticFromIdea(row)
  }
  if (et === 'initiative' && b) {
    const row = b.initiatives.find((x) => x.id === id)
    if (row) return syntheticFromInitiative(row)
  }
  if (et === 'project' && b) {
    const row = b.projects.find((x) => x.id === id)
    if (row) return syntheticFromProject(row)
  }
  if (et === 'task' && b) {
    const row = b.tasks.find((x) => x.id === id)
    if (row) return syntheticFromTask(row)
  }

  return syntheticFallback(et, id, core.lineage_labels)
}

/**
 * Triad + missing dimensions for the current VE focus, using the same heuristics as the vision map.
 * Returns null when focus is not a VE work entity (e.g. council field, core profile).
 */
export function buildVeMapTriadSnapshotFromFocus(
  core: Pick<FocusContextCore, 'entity_type' | 'entity_id' | 'lineage_labels'> | null | undefined,
  bundle: VisionMapEntityBundle | null | undefined,
): MapTriadDevelopmentalSnapshot | null {
  if (!core?.entity_id?.trim()) return null
  const payload = buildSyntheticPayload(core, bundle)
  if (!payload) return null

  const triad = computeGrowthTriad(payload, bundle ?? null)
  const missing_dimensions = detectMissingDimensions(triad)
  return {
    node_id: core.entity_id.trim(),
    is_nest_aggregate: false,
    node_kind: payload.kind,
    triad,
    missing_dimensions,
    node_label: payload.label?.trim() || null,
    triad_scope: 've_execution_focus',
  }
}
