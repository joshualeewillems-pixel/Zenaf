/**
 * FLOW_RECEPTION (adapter — no UI)
 * (1) Reads: `MapNodePayload` + bundle; VE rows for minimal payload path.
 * (2) Behavior: produces `FlowInput` via `assessNodeFlowAndChannels` + `buildFlowInputForMapNode` — single scoring path.
 * (3) Hard vs productive: N/A here; downstream consumers apply contradiction rules.
 */

import type { VisionMapEntityBundle } from '../vision-map/blockersFromVe'
import { conditionFromSignals, growthFromStatus, isStaleIso } from '../vision-map/deriveVisualState'
import {
  deriveFertilizerPulse,
  vitalForIdea,
  vitalForInitiative,
  vitalForProject,
  vitalForTask,
  waterLevelFromVital,
} from '../vision-map/mapVitalForces'
import type { MapEntityRef, MapNodePayload } from '../vision-map/ontology'
import type { StudioCouncilRunRow } from '../vision-map/studioCouncilTypes'
import { assessNodeFlowAndChannels, buildFlowInputForMapNode } from './assessNodeFlowAndChannels'
import type { FlowInput } from './flowAssessment'

export { structureHintsForEntity } from './structureHintsForMapEntity'

export function buildFlowInputFromMapPayload(
  payload: MapNodePayload,
  bundle: VisionMapEntityBundle | null,
  councilRuns: StudioCouncilRunRow[] = [],
): FlowInput {
  const u = assessNodeFlowAndChannels(payload, { bundle, councilRuns })
  const merged: MapNodePayload = {
    ...payload,
    water_level: u.derived.water_level,
    fertilizer_pulse: u.derived.fertilizer_pulse,
  }
  return buildFlowInputForMapNode(merged, bundle, u.derived.map_visual_triad, u.derived.condition_severity)
}

export function minimalMapPayloadForVeEntity(ref: MapEntityRef, bundle: VisionMapEntityBundle): MapNodePayload | null {
  if (ref.veType === 'idea') {
    const idea = bundle.ideas.find((x) => x.id === ref.id)
    if (!idea) return null
    const wl = waterLevelFromVital(vitalForIdea(idea))
    const pulse = deriveFertilizerPulse(ref, idea.updated_at ?? null, [])
    return {
      kind: 'seed',
      label: idea.title || 'Idea',
      subtitle: 'Idea',
      growth: growthFromStatus(idea.status),
      condition: conditionFromSignals({ stale: isStaleIso(idea.updated_at, 45) }),
      ref,
      summaryLines: [(idea.summary || idea.description || '').trim()].filter(Boolean),
      water_level: wl,
      fertilizer_pulse: pulse,
    }
  }
  if (ref.veType === 'initiative') {
    const ini = bundle.initiatives.find((x) => x.id === ref.id)
    if (!ini) return null
    const wl = waterLevelFromVital(vitalForInitiative(ini))
    const pulse = deriveFertilizerPulse(ref, ini.updated_at ?? null, [])
    const stale = isStaleIso(ini.updated_at, 30)
    return {
      kind: 'tree',
      label: ini.title || 'Initiative',
      subtitle: 'Initiative',
      growth: growthFromStatus(ini.status),
      condition: conditionFromSignals({ stale }),
      ref,
      summaryLines: [(ini.brief || '').trim(), `Status: ${ini.status || ''}`].filter(Boolean),
      water_level: wl,
      fertilizer_pulse: pulse,
    }
  }
  if (ref.veType === 'project') {
    const proj = bundle.projects.find((x) => x.id === ref.id)
    if (!proj) return null
    const wl = waterLevelFromVital(vitalForProject(proj))
    const pulse = deriveFertilizerPulse(ref, proj.updated_at ?? null, [])
    return {
      kind: 'branch',
      label: proj.title || 'Project',
      subtitle: 'Project',
      growth: growthFromStatus(proj.status, {
        doneRatio:
          bundle.tasks.filter((t) => t.project_id === proj.id).length > 0
            ? bundle.tasks.filter((t) => t.project_id === proj.id && /\b(done|complete)\b/i.test(t.status || ''))
                .length /
              bundle.tasks.filter((t) => t.project_id === proj.id).length
            : undefined,
      }),
      condition: conditionFromSignals({ stale: isStaleIso(proj.updated_at, 28) }),
      ref,
      summaryLines: [(proj.brief || '').trim()].filter(Boolean),
      water_level: wl,
      fertilizer_pulse: pulse,
    }
  }
  if (ref.veType === 'task') {
    const task = bundle.tasks.find((x) => x.id === ref.id)
    if (!task) return null
    const wl = waterLevelFromVital(vitalForTask(task))
    const pulse = deriveFertilizerPulse(ref, task.updated_at ?? null, [])
    const blocked = /\bblock/i.test(task.status || '') || /\bblock/i.test(task.notes || '')
    return {
      kind: 'flower',
      label: task.title || 'Task',
      subtitle: 'Task',
      growth: growthFromStatus(task.status),
      condition: conditionFromSignals({ blocked, stale: isStaleIso(task.updated_at, 21) }),
      ref,
      summaryLines: [(task.description || '').trim()].filter(Boolean),
      water_level: wl,
      fertilizer_pulse: pulse,
    }
  }
  return null
}

export function buildFlowInputFromVeEntity(
  ref: MapEntityRef,
  bundle: VisionMapEntityBundle | null,
): FlowInput | null {
  if (!bundle) return null
  const payload = minimalMapPayloadForVeEntity(ref, bundle)
  if (!payload) return null
  return buildFlowInputFromMapPayload(payload, bundle, [])
}
