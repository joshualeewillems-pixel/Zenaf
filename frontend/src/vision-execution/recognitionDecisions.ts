/**
 * Client helpers for recognition lifecycle — entity AND/OR decision by subsystem.
 * @see local_ai/vision_execution/recognition.py
 */

export const DECISION_TYPE_MEETING_EXTRACTION_COMMIT = 'meeting_extraction_commit'
export const DECISION_TYPE_COUNCIL_INSIGHT = 'council_insight'
export const DECISION_TYPE_CORE_PROFILE_IDENTITY_SHIFT = 'core_profile_identity_shift'

export const ENTITY_TYPE_MEETING_EXTRACTION_SESSION = 'meeting_extraction'
export const ENTITY_TYPE_COUNCIL_INSIGHT = 'council_insight'
export const ENTITY_TYPE_CORE_PROFILE = 'core_profile'

const INSIGHT_TEXT_CAP = 24_000
const PROFILE_FIELD_SNAPSHOT_MAX = 600

export type CreatedEntityRef = {
  entity_type: 'idea' | 'initiative' | 'project' | 'task' | 'asset' | 'person'
  id: string
  title: string
}

/** Matches VE `apiPost` wrappers (generic return). */
export type VisionExecutionPost = (path: string, body: unknown) => Promise<unknown>

function safeUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `id-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`
}

/** Meeting commit: entities (already created) + provenance decision. */
export async function postMeetingExtractionRecognition(
  apiPost: VisionExecutionPost,
  params: {
    meetingId?: string | null
    createdRefs: CreatedEntityRef[]
    signalsCreated?: number
    userId?: string | null
  },
): Promise<void> {
  const { meetingId, createdRefs, signalsCreated = 0, userId } = params
  if (createdRefs.length === 0 && signalsCreated <= 0) return

  const sessionId = safeUuid()
  await apiPost('/decisions', {
    user_id: userId ?? null,
    entity_type: ENTITY_TYPE_MEETING_EXTRACTION_SESSION,
    entity_id: sessionId,
    decision_type: DECISION_TYPE_MEETING_EXTRACTION_COMMIT,
    ai_proposal_snapshot: null,
    final_values_snapshot: {
      recognition_kind: 'structure_and_provenance',
      meeting_id: meetingId ?? null,
      created_entities: createdRefs,
      signals_created: signalsCreated,
    },
  })
}

/** Council: decision only — meaning without a new VE entity row. */
export async function postCouncilInsightRecognition(
  apiPost: VisionExecutionPost,
  params: {
    bodyText: string
    label?: string | null
    userId?: string | null
  },
): Promise<void> {
  const text = (params.bodyText ?? '').trim()
  if (!text) return

  const entityId = safeUuid()
  await apiPost('/decisions', {
    user_id: params.userId ?? null,
    entity_type: ENTITY_TYPE_COUNCIL_INSIGHT,
    entity_id: entityId,
    decision_type: DECISION_TYPE_COUNCIL_INSIGHT,
    ai_proposal_snapshot: {
      body_text: text.slice(0, INSIGHT_TEXT_CAP),
      label: params.label ?? null,
    },
    final_values_snapshot: {
      recognition_kind: 'meaning_only',
    },
  })
}

/** Core profile: entity already saved via PATCH; this is the identity-shift decision. */
export async function postCoreProfileIdentityRecognition(
  apiPost: VisionExecutionPost,
  params: {
    profileId: string
    fieldSnapshot: Record<string, string>
    userId?: string | null
  },
): Promise<void> {
  const { profileId, fieldSnapshot, userId } = params
  const condensed: Record<string, string> = {}
  for (const [k, v] of Object.entries(fieldSnapshot)) {
    const s = typeof v === 'string' ? v : String(v ?? '')
    condensed[k] = s.length > PROFILE_FIELD_SNAPSHOT_MAX ? `${s.slice(0, PROFILE_FIELD_SNAPSHOT_MAX)}…` : s
  }

  await apiPost('/decisions', {
    user_id: userId ?? null,
    entity_type: ENTITY_TYPE_CORE_PROFILE,
    entity_id: profileId,
    decision_type: DECISION_TYPE_CORE_PROFILE_IDENTITY_SHIFT,
    ai_proposal_snapshot: null,
    final_values_snapshot: {
      recognition_kind: 'structure_and_identity',
      profile_id: profileId,
      fields: condensed,
    },
  })
}
