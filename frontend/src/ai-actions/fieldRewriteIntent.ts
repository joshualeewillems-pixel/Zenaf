/**
 * Resolves `action_intent` for `field_text_rewrite` traces from VE focus target.
 * Covers every field in `fieldCapabilityRegistry` that lists `rewrite` in `allowed_actions`.
 * Returns null only for unknown entity/field pairs (future fields or unregistered focus).
 */
export function actionIntentForFieldTextRewrite(entityType: string, fieldKey: string): string | null {
  const key = `${entityType}:${fieldKey}`
  const map: Record<string, string> = {
    'initiative:brief': 'initiative_brief_rewrite',
    'initiative:recommendation': 'initiative_recommendation_rewrite',
    'initiative:philosophical_alignment_ai': 'initiative_philosophical_alignment_ai_rewrite',
    'idea:title': 'idea_title_rewrite',
    'idea:description': 'idea_description_rewrite',
    'idea:summary': 'idea_summary_rewrite',
    'task:title': 'task_title_rewrite',
    'task:description': 'task_description_rewrite',
  }
  return map[key] ?? null
}
