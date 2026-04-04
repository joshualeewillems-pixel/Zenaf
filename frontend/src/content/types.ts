/**
 * Content pipeline: first-class briefs with lifecycle (draft / generated / in_production).
 */

/** Config for Content module: API base for /run and transcript tools; optional separate base for VE. */
export interface ContentConfig {
  apiBase: string
  veApiBase?: string
}

export type ContentBriefStatus = 'draft' | 'generated' | 'in_production'

export interface ContentBriefPayload {
  title: string
  linked_initiative_id: string
  linked_project_id: string
  linked_task_ids: string[]
  audience: string
  content_goal: string
  key_themes: string[]
  claims: string[]
  cta: string
  tone_voice: string
  target_formats: string[]
  source_materials: string
  notes: string
}

export interface ContentBrief extends ContentBriefPayload {
  id: string
  status: ContentBriefStatus
  created_at?: string
  updated_at?: string
}

export const DEFAULT_BRIEF_PAYLOAD: ContentBriefPayload = {
  title: '',
  linked_initiative_id: '',
  linked_project_id: '',
  linked_task_ids: [],
  audience: '',
  content_goal: '',
  key_themes: [],
  claims: [],
  cta: '',
  tone_voice: '',
  target_formats: [],
  source_materials: '',
  notes: '',
}

/** Build full ContentBrief from API shape { id, title, status, payload, ... } */
export function apiBriefToBrief(api: { id: string; title: string; status: string; payload: ContentBriefPayload; created_at?: string; updated_at?: string }): ContentBrief {
  const p = api.payload || DEFAULT_BRIEF_PAYLOAD
  return {
    id: api.id,
    status: (api.status as ContentBriefStatus) || 'draft',
    created_at: api.created_at,
    updated_at: api.updated_at,
    ...p,
    title: api.title || p.title,
  }
}

/** Payload sent to /run for content_script or content_newsletter */
export function briefToRunPayload(brief: ContentBrief | ContentBriefPayload, outputType: 'script' | 'newsletter') {
  return {
    title: brief.title,
    audience: brief.audience,
    content_goal: brief.content_goal,
    key_themes: brief.key_themes,
    claims: brief.claims,
    cta: brief.cta,
    tone_voice: brief.tone_voice,
    target_formats: brief.target_formats,
    notes: brief.notes,
  }
}

export const VE_TASK_TEMPLATES = [
  { id: 'record_narration', label: 'Record narration', title: 'Record narration' },
  { id: 'produce_avatar_video', label: 'Produce avatar video', title: 'Produce avatar video' },
  { id: 'build_landing_page', label: 'Build landing page', title: 'Build landing page' },
  { id: 'send_newsletter', label: 'Send newsletter', title: 'Send newsletter' },
] as const
