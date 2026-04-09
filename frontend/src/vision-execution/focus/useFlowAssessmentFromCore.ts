/**
 * FLOW_RECEPTION (hook)
 * (1) Reads: graph snapshot entity lists; focus `entity_type` / `entity_id` → `MapEntityRef`.
 * (2) Behavior: returns `FlowAssessment | null` for invite chips and similar consumers.
 * (3) Hard vs productive: null when no snapshot (no fake flow); consumers fall back to registry-only invites.
 */
import { useMemo } from 'react'
import { assessNodeFlowAndChannels } from '../../flow/assessNodeFlowAndChannels'
import { minimalMapPayloadForVeEntity } from '../../flow/flowInputAdapter'
import type { MapEntityRef } from '../../vision-map/ontology'
import { useVisionExecutionGraphDataOptional } from './VisionExecutionGraphDataContext'
import type { FocusContextCore } from './types'

function coreToMapRef(core: FocusContextCore): MapEntityRef | null {
  if (core.entity_type === 'idea') return { veType: 'idea', id: core.entity_id }
  if (core.entity_type === 'initiative') return { veType: 'initiative', id: core.entity_id }
  if (core.entity_type === 'project') return { veType: 'project', id: core.entity_id }
  if (core.entity_type === 'task') return { veType: 'task', id: core.entity_id }
  return null
}

/** Resolves FlowAssessment for focused VE entity using graph snapshot (Flow Spine Charter). */
export function useFlowAssessmentFromCore(core: FocusContextCore | null | undefined) {
  const graph = useVisionExecutionGraphDataOptional()
  return useMemo(() => {
    if (!core) return null
    const ref = coreToMapRef(core)
    if (!ref) return null
    const snap = graph?.snapshot
    if (!snap) return null
    const bundle = {
      ideas: snap.ideas,
      initiatives: snap.initiatives,
      projects: snap.projects,
      tasks: snap.tasks,
    }
    const payload = minimalMapPayloadForVeEntity(ref, bundle)
    if (!payload) return null
    return assessNodeFlowAndChannels(payload, { bundle, councilRuns: [] }).flow
  }, [core, graph?.snapshot])
}
