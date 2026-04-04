/**
 * Map extracted (staged) items to domain/API payloads for commit.
 * Produces typed bodies for POST to vision-execution API; owner_id / assignee_id
 * remain null unless resolved from people lookup.
 */

import type { ExtractedIdea, ExtractedInitiative, ExtractedProject, ExtractedTask, ExtractedAsset, ExtractedPersonReference } from './types'

/** Payload for POST /ideas (backend creates id, created_at, updated_at). */
export interface CreateIdeaPayload {
  title: string
  summary: string
  description: string
  status: string
}

/** Payload for POST /initiatives. */
export interface CreateInitiativePayload {
  title: string
  brief: string
  status: string
  notes: string
  owner_id: string | null
  source_idea_id?: string | null
  required_people?: string[]
  required_assets?: string[]
}

/** Payload for POST /projects. */
export interface CreateProjectPayload {
  title: string
  brief: string
  status: string
  initiative_id: string | null
  owner_id: string | null
  required_assets?: string[]
  notes: string
}

/** Payload for POST /tasks. */
export interface CreateTaskPayload {
  project_id: string | null
  title: string
  description: string
  status: string
  assignee_id: string | null
  required_asset_ids?: string[]
  notes: string
}

/** Payload for POST /assets. */
export interface CreateAssetPayload {
  name: string
  asset_type: string
  notes: string
  owner_id: string | null
}

/** Payload for POST /persons. */
export interface CreatePersonPayload {
  name: string
  role: string
  notes: string
}

export type ResolveInitiativeId = (initiativeTitleOrId: string) => string | null
export type ResolveProjectId = (projectTitleOrId: string) => string | null
export type ResolvePersonId = (personName: string) => string | null

/** Map extracted idea to API create payload. */
export function toCreateIdeaPayload(extracted: ExtractedIdea): CreateIdeaPayload {
  return {
    title: extracted.title || 'Untitled',
    summary: extracted.summary ?? '',
    description: extracted.description ?? '',
    status: extracted.status ?? 'Captured',
  }
}

/** Map extracted initiative to API create payload. Notes get traceability in commit flow. */
export function toCreateInitiativePayload(extracted: ExtractedInitiative, ownerId?: string | null, sourceIdeaId?: string | null, requiredAssets?: string[]): CreateInitiativePayload {
  return {
    title: extracted.title || 'Untitled',
    brief: extracted.brief ?? extracted.description ?? '',
    status: extracted.status ?? 'Draft',
    notes: extracted.notes ?? '',
    owner_id: ownerId ?? null,
    source_idea_id: sourceIdeaId ?? undefined,
    required_assets: requiredAssets && requiredAssets.length > 0 ? requiredAssets : undefined,
  }
}

/** Map extracted project to API create payload; resolve initiative_id if resolver provided. Prefer parentLink then existingInitiativeMatchId. */
export function toCreateProjectPayload(
  extracted: ExtractedProject,
  resolveInitiativeId?: ResolveInitiativeId,
  overrideInitiativeId?: string | null,
  ownerId?: string | null,
  requiredAssets?: string[]
): CreateProjectPayload {
  const initiative_id =
    overrideInitiativeId ??
    extracted.existingInitiativeMatchId ??
    extracted.initiativeId ??
    (extracted.initiativeTitle && resolveInitiativeId
      ? resolveInitiativeId(extracted.initiativeTitle)
      : null)
  return {
    title: extracted.title || 'Untitled',
    brief: extracted.brief ?? '',
    status: extracted.status ?? 'Draft',
    initiative_id,
    owner_id: ownerId ?? null,
    required_assets: requiredAssets && requiredAssets.length > 0 ? requiredAssets : undefined,
    notes: '',
  }
}

/** Map extracted task to API create payload; project_id optional (standalone task). */
export function toCreateTaskPayload(
  extracted: ExtractedTask,
  projectId: string | null,
  resolvePersonId?: ResolvePersonId,
  overrideAssigneeId?: string | null,
  requiredAssetIds?: string[]
): CreateTaskPayload {
  const assignee_id =
    overrideAssigneeId ??
    ((extracted.suggestedOwner ?? extracted.assigneeName) && resolvePersonId
      ? resolvePersonId(extracted.suggestedOwner ?? extracted.assigneeName ?? '')
      : null)
  return {
    project_id: projectId && projectId.length > 0 ? projectId : null,
    title: extracted.title || 'Untitled',
    description: extracted.description ?? '',
    status: extracted.status ?? 'Todo',
    assignee_id,
    required_asset_ids: requiredAssetIds && requiredAssetIds.length > 0 ? requiredAssetIds : undefined,
    notes: extracted.notes ?? '',
  }
}

/** Map extracted asset to API create payload; asset_type from kind. */
export function toCreateAssetPayload(extracted: ExtractedAsset, ownerId?: string | null): CreateAssetPayload {
  const asset_type = extracted.kind === 'inventory' ? 'supply' : extracted.kind
  return {
    name: extracted.name || 'Untitled',
    asset_type,
    notes: extracted.description ?? '',
    owner_id: ownerId ?? null,
  }
}

/** Map extracted person reference to API create payload. */
export function toCreatePersonPayload(extracted: ExtractedPersonReference): CreatePersonPayload {
  return {
    name: extracted.name || 'Unknown',
    role: extracted.role ?? '',
    notes: extracted.context ?? '',
  }
}

const SOURCE_LABEL = '[Source: meeting-extraction]'

/** Append traceability to a notes string (for domain commit). */
export function withTraceability(notes: string, sourceExcerpt?: string | null): string {
  const parts = [notes.trim(), SOURCE_LABEL]
  if (sourceExcerpt?.trim()) parts.push(`Quote: ${sourceExcerpt.trim().slice(0, 500)}`)
  return parts.filter(Boolean).join('\n\n')
}

/** Parsed traceability from notes or description (for UI display). */
export interface ParsedTraceability {
  source: string | null
  sourceExcerpt: string | null
}

/** Parse notes/description for "[Source: ...]" and "Quote: ..." written by withTraceability. */
export function parseTraceabilityFromNotes(notes: string | null | undefined): ParsedTraceability {
  const text = (notes ?? '').trim()
  if (!text) return { source: null, sourceExcerpt: null }
  const sourceMatch = text.match(/\[Source:\s*([^\]]+)\]/)
  const quoteMatch = text.match(/Quote:\s*([\s\S]*)/)
  return {
    source: sourceMatch ? sourceMatch[1].trim() : null,
    sourceExcerpt: quoteMatch ? quoteMatch[1].trim().slice(0, 500) : null,
  }
}
