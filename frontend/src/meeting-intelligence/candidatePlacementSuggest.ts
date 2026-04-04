/**
 * Types + patch builder for POST /vision-execution/suggest-candidate-placement (per-card placement; suggest-only).
 */

import type { CommitableStagedKind, StagedParentLink } from './stagingTypes'

export type PlacementEntityType = 'idea' | 'initiative' | 'project' | 'task'

export interface PlacementNodeRef {
  id: string
  type: PlacementEntityType
  title: string
  confidence: number
}

export interface CandidatePlacementAlternative {
  type: string
  reason: string
  confidence: number
}

export type StrategicFitLevel = 'high' | 'medium' | 'low'
export type CapacityRiskLevel = 'low' | 'medium' | 'high'

export interface CandidatePlacementResponse {
  proposed_type?: string
  confidence?: number
  placement_mode?: 'new' | 'attach' | 'amend'
  target?: PlacementNodeRef | null
  suggested_parent?: PlacementNodeRef | null
  reason?: string
  alternatives?: CandidatePlacementAlternative[]
  /** Present when a core profile shaped the suggestion (server-resolved or client-sent). */
  profile_id?: string | null
  profile_name?: string | null
  profile_alignment?: number | null
  profile_reason?: string | null
  strategic_fit?: StrategicFitLevel | null
  capacity_risk?: CapacityRiskLevel | null
  error?: string
  execution_blocked?: boolean
  model_used?: string
  provider_used?: string
  /** Echo of optional client_correlation_id from the request (bulk / debug). */
  client_correlation_id?: string
  _fallback?: boolean
}

const COMMITABLE: readonly CommitableStagedKind[] = [
  'idea',
  'initiative',
  'project',
  'task',
  'signal',
  'asset',
  'person',
]

const PARENT_TYPES: readonly PlacementEntityType[] = ['idea', 'initiative', 'project', 'task']

function isCommitable(t: string): t is CommitableStagedKind {
  return COMMITABLE.includes(t as CommitableStagedKind)
}

function isParentType(t: string): t is StagedParentLink['parentType'] {
  return (PARENT_TYPES as readonly string[]).includes(t)
}

/**
 * Maps API suggestion to staging fields. Does not persist — caller merges via onStagingChange.
 */
export function buildStagingPatchFromPlacementSuggestion(s: CandidatePlacementResponse): {
  overrideType: CommitableStagedKind
  acceptedExistingId: string | null
  parentLink: StagedParentLink | null
} {
  const ptRaw = (s.proposed_type || 'idea').toLowerCase()
  let overrideType: CommitableStagedKind = isCommitable(ptRaw) ? ptRaw : 'idea'
  let acceptedExistingId: string | null = null
  let parentLink: StagedParentLink | null = null
  const mode = s.placement_mode ?? 'new'

  if ((mode === 'attach' || mode === 'amend') && s.target?.id && isParentType(s.target.type)) {
    acceptedExistingId = s.target.id
    parentLink = null
    if (isCommitable(s.target.type)) {
      overrideType = s.target.type
    }
  } else {
    acceptedExistingId = null
    const sp = s.suggested_parent
    if (sp?.id && isParentType(sp.type)) {
      parentLink = { parentType: sp.type, parentId: sp.id }
    } else {
      parentLink = null
    }
  }

  return { overrideType, acceptedExistingId, parentLink }
}
