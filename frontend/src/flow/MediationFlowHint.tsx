import { useMemo } from 'react'
import type { VESelection } from '../vision-execution/VisionExecutionView'
import { useVisionExecutionGraphDataOptional } from '../vision-execution/focus/VisionExecutionGraphDataContext'
import type { MapEntityRef } from '../vision-map/ontology'
import { assessNodeFlowAndChannels } from './assessNodeFlowAndChannels'
import { mediationFlowToneLine } from './flowAssessment'
import { minimalMapPayloadForVeEntity } from './flowInputAdapter'

function veSelectionToMapRef(sel: VESelection): MapEntityRef | null {
  if (sel.ideaId) return { veType: 'idea', id: sel.ideaId }
  if (sel.initiativeId) return { veType: 'initiative', id: sel.initiativeId }
  if (sel.projectId) return { veType: 'project', id: sel.projectId }
  if (sel.taskId) return { veType: 'task', id: sel.taskId }
  return null
}

/**
 * FLOW_RECEPTION (mediation panel — Chat mode strip)
 * (1) Reads: `assessFlow` after `buildFlowInputFromVeEntity` — uses `dominantIssue`, `axes.grounding`, `axes.tension`
 *     inside `mediationFlowToneLine`.
 * (2) Behavior: optional helper line under mode headline; nudges tone toward steps / contrast, not closure.
 * (3) Hard vs productive: additive copy only — does not block council; user can ignore (productive tension visible).
 */
export function MediationFlowHint({ veSelection }: { veSelection: VESelection | null }) {
  const graph = useVisionExecutionGraphDataOptional()
  const line = useMemo(() => {
    if (!veSelection) return null
    const ref = veSelectionToMapRef(veSelection)
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
    return mediationFlowToneLine(assessNodeFlowAndChannels(payload, { bundle, councilRuns: [] }).flow)
  }, [veSelection, graph?.snapshot])

  if (!line) return null
  return (
    <p
      className="text-[11px] text-amber-200/75 mt-1.5 leading-snug border-t border-amber-900/20 pt-1.5"
      data-testid="mediation-flow-tone-hint"
    >
      {line}
    </p>
  )
}
