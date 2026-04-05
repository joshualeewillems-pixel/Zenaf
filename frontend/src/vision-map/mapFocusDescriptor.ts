import type { FocusDescriptor } from '../vision-execution/focus/types'
import { CONVERSATION_ENTITY_FIELD_KEY } from '../vision-execution/focus/conversationEntityFocus'
import type { MapNodePayload } from './ontology'
import { councilAnchorRef } from './mapCouncilActions'

/** Map node selection → shared focus descriptor (Vision Map surface). */
export function mapPayloadToConversationFocusDescriptor(p: MapNodePayload): FocusDescriptor | null {
  const anchor = councilAnchorRef(p)
  const et = anchor.veType
  if (et !== 'idea' && et !== 'initiative' && et !== 'project' && et !== 'task') return null
  const label = (p.label ?? '').trim() || anchor.id
  return {
    surface: 'vision_map',
    entity_type: et,
    entity_id: anchor.id,
    field_key: CONVERSATION_ENTITY_FIELD_KEY,
    field_label: `${et}: ${label}`,
    field_kind: 'idea_body',
  }
}
