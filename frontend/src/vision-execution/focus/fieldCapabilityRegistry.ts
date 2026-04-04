import type { ActionId, EntityType, FieldKind } from './types'

export type FieldCapabilityEntry = {
  field_key: string
  entity_type: EntityType
  field_label: string
  field_kind: FieldKind
  allowed_actions: ActionId[]
}

function key(entity_type: EntityType, field_key: string): string {
  return `${entity_type}:${field_key}`
}

/** Phase 1: minimal curated map only */
const REGISTRY: Record<string, FieldCapabilityEntry> = {
  [key('initiative', 'title')]: {
    entity_type: 'initiative',
    field_key: 'title',
    field_label: 'Title',
    field_kind: 'idea_body',
    allowed_actions: ['rewrite'],
  },
  [key('initiative', 'brief')]: {
    entity_type: 'initiative',
    field_key: 'brief',
    field_label: 'Brief',
    field_kind: 'long_form_strategy',
    allowed_actions: ['rewrite', 'distill', 'expand_to_steps', 'surface_tensions', 'summarize_for_council'],
  },
  [key('initiative', 'recommendation')]: {
    entity_type: 'initiative',
    field_key: 'recommendation',
    field_label: 'Recommendation',
    field_kind: 'evaluation_narrative',
    allowed_actions: [
      'rewrite',
      'distill',
      'surface_tensions',
      'compare_with_evaluation',
      'summarize_for_council',
      'expand_to_steps',
    ],
  },
  [key('initiative', 'philosophical_alignment_ai')]: {
    entity_type: 'initiative',
    field_key: 'philosophical_alignment_ai',
    field_label: 'Strategic alignment (AI)',
    field_kind: 'evaluation_narrative',
    allowed_actions: ['rewrite', 'distill', 'surface_tensions', 'compare_with_evaluation', 'summarize_for_council'],
  },
  [key('initiative', 'dependencies')]: {
    entity_type: 'initiative',
    field_key: 'dependencies',
    field_label: 'Dependencies',
    field_kind: 'dependencies_scope',
    allowed_actions: ['extract_constraints', 'surface_tensions', 'expand_to_steps'],
  },
  [key('idea', 'description')]: {
    entity_type: 'idea',
    field_key: 'description',
    field_label: 'Expanded description',
    field_kind: 'idea_body',
    allowed_actions: ['rewrite', 'distill', 'expand_to_steps', 'surface_tensions'],
  },
  [key('idea', 'title')]: {
    entity_type: 'idea',
    field_key: 'title',
    field_label: 'Title',
    field_kind: 'idea_body',
    allowed_actions: ['rewrite'],
  },
  [key('idea', 'summary')]: {
    entity_type: 'idea',
    field_key: 'summary',
    field_label: 'Short note',
    field_kind: 'idea_body',
    allowed_actions: ['rewrite'],
  },
  [key('project', 'title')]: {
    entity_type: 'project',
    field_key: 'title',
    field_label: 'Title',
    field_kind: 'idea_body',
    allowed_actions: ['rewrite'],
  },
  [key('project', 'brief')]: {
    entity_type: 'project',
    field_key: 'brief',
    field_label: 'Brief',
    field_kind: 'long_form_strategy',
    allowed_actions: ['rewrite', 'distill', 'expand_to_steps', 'surface_tensions', 'summarize_for_council'],
  },
  [key('task', 'title')]: {
    entity_type: 'task',
    field_key: 'title',
    field_label: 'Title',
    field_kind: 'idea_body',
    allowed_actions: ['rewrite'],
  },
  [key('task', 'description')]: {
    entity_type: 'task',
    field_key: 'description',
    field_label: 'Description',
    field_kind: 'idea_body',
    allowed_actions: ['rewrite'],
  },
}

export function getFieldCapabilities(
  entity_type: EntityType,
  field_key: string,
): FieldCapabilityEntry | undefined {
  if (entity_type === 'app_field') {
    return {
      entity_type: 'app_field',
      field_key,
      field_label: field_key,
      field_kind: 'idea_body',
      allowed_actions: [],
    }
  }
  return REGISTRY[key(entity_type, field_key)]
}

export function actionsForField(entity_type: EntityType, field_key: string): ActionId[] {
  const base = getFieldCapabilities(entity_type, field_key)?.allowed_actions ?? []
  const out = [...base]
  if (!out.includes('transcribe')) out.unshift('transcribe')
  return out
}

export const ACTION_LABELS: Record<ActionId, string> = {
  transcribe: 'Transcribe',
  rewrite: 'Rewrite',
  distill: 'Distill',
  expand_to_steps: 'Expand to steps',
  extract_constraints: 'Constraints',
  surface_tensions: 'Tensions',
  compare_with_evaluation: 'vs evaluation',
  summarize_for_council: 'Council summary',
  convert_to_task: 'To task',
}
