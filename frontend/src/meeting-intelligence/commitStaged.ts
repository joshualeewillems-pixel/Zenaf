/**
 * Commit approved staged items to the Vision Execution API.
 * Routing is by overrideType (effectiveType), not by section: a card marked "project" creates a project regardless of section.
 * Applies traceability (source + sourceExcerpt). Persists assignedPersonIds and assignedAssetIds.
 * Parent link is used only when relationshipType is 'parent' or unset (hierarchy).
 */

import type { Initiative, Project } from '../vision-execution/types'
import type { CreatedEntityRef } from '../vision-execution/recognitionDecisions'
import type { StagingArea, StagedItem, CommitableStagedKind } from './stagingTypes'
import {
  toCreateIdeaPayload,
  toCreateInitiativePayload,
  toCreateProjectPayload,
  toCreateTaskPayload,
  toCreateAssetPayload,
  toCreatePersonPayload,
  withTraceability,
} from './stagingMappers'

/** Section keys that hold arrays of staged rows (used for single-item commit slices). */
export type StagingArraySectionKey =
  | 'insights'
  | 'ideas'
  | 'initiatives'
  | 'projects'
  | 'tasks'
  | 'assets'
  | 'people'
  | 'signals'

/**
 * Clone staging so exactly one item is approved (all others unapproved).
 * Used to commit one card at a time while preserving link/assignment edits on that row.
 */
export function stagingForSingleItemCommit(
  staging: StagingArea,
  sectionKey: StagingArraySectionKey,
  itemId: string
): StagingArea {
  const mark = <T extends StagedItem>(items: T[], key: StagingArraySectionKey): T[] =>
    items.map((i) => ({
      ...i,
      approved: key === sectionKey && i.id === itemId,
    }))

  return {
    ...staging,
    summary: staging.summary ? { ...staging.summary, approved: false } : null,
    insights: mark(staging.insights, 'insights'),
    ideas: mark(staging.ideas, 'ideas'),
    initiatives: mark(staging.initiatives, 'initiatives'),
    projects: mark(staging.projects, 'projects'),
    tasks: mark(staging.tasks, 'tasks'),
    assets: mark(staging.assets, 'assets'),
    people: mark(staging.people, 'people'),
    signals: mark(staging.signals ?? [], 'signals'),
  }
}

export interface CommitContext {
  apiPost: (path: string, body: unknown) => Promise<{ id: string; [k: string]: unknown }>
  existingInitiatives: Initiative[]
  existingProjects: Project[]
}

export interface CommitResult {
  created: { ideas: number; initiatives: number; projects: number; tasks: number; assets: number; persons: number }
  /** IDs returned from VE API for recognition / provenance decisions. */
  createdRefs: CreatedEntityRef[]
  errors: string[]
}

/** Order for commit: ideas first, then initiatives, then projects, then tasks, then assets, persons (signals handled in view). */
const COMMIT_TYPE_ORDER: CommitableStagedKind[] = ['idea', 'initiative', 'project', 'task', 'asset', 'person']

/**
 * Person assignment semantics at commit (assignedPersonIds from review UI):
 * - idea: none (ideas have no owner in create API)
 * - initiative: first id → owner_id
 * - project: first id → owner_id (supporting_owner_ids not set from review)
 * - task: first id → assignee_id
 * - asset: first id → owner_id
 * - person: N/A
 * - signal: no person assignment
 */

function isParentLink(item: StagedItem): boolean {
  const link = item.parentLink
  if (!link) return false
  const t = link.relationshipType
  return t === 'parent' || t === undefined
}

/** Collect all approved items from staging with effectiveType; sort by commit order. */
function collectApprovedByEffectiveType(staging: StagingArea): { item: StagedItem; effectiveType: CommitableStagedKind }[] {
  const sections: (keyof StagingArea)[] = ['ideas', 'initiatives', 'projects', 'tasks', 'assets', 'people']
  const out: { item: StagedItem; effectiveType: CommitableStagedKind }[] = []
  for (const key of sections) {
    const arr = staging[key]
    if (!Array.isArray(arr)) continue
    for (const item of arr) {
      if (!item.approved) continue
      const effectiveType = (item.overrideType ?? item.kind) as CommitableStagedKind
      if (!COMMIT_TYPE_ORDER.includes(effectiveType)) continue
      out.push({ item, effectiveType })
    }
  }
  out.sort((a, b) => COMMIT_TYPE_ORDER.indexOf(a.effectiveType) - COMMIT_TYPE_ORDER.indexOf(b.effectiveType))
  return out
}

/** Get title from any item.data (cross-type commit). */
export function getDataTitle(data: Record<string, unknown>): string {
  return (data.title as string) ?? (data.name as string) ?? 'Untitled'
}

/** Single line for commit preview. */
export interface CommitPreviewLine {
  kind: 'create' | 'use_existing'
  effectiveType: CommitableStagedKind | 'signal'
  title: string
  parent?: { parentType: string; parentId: string }
  personCount: number
  assetCount: number
}

/** Build a lightweight summary of what commit will do (for preview before Commit). */
export function buildCommitPreview(staging: StagingArea): CommitPreviewLine[] {
  const items = collectApprovedByEffectiveType(staging)
  const lines: CommitPreviewLine[] = []
  for (const { item, effectiveType } of items) {
    const data = item.data as unknown as Record<string, unknown>
    const title = getDataTitle(data)
    const personCount = (item.assignedPersonIds ?? []).length
    const assetCount = (item.assignedAssetIds ?? []).length
    const parent = isParentLink(item) && item.parentLink ? { parentType: item.parentLink.parentType, parentId: item.parentLink.parentId } : undefined
    if (item.acceptedExistingId) {
      lines.push({ kind: 'use_existing', effectiveType, title, personCount, assetCount })
    } else {
      lines.push({ kind: 'create', effectiveType, title, parent, personCount, assetCount })
    }
  }
  const signalKinds = ['attention', 'risk', 'opportunity', 'blocker'] as const
  const approvedSignals = (staging.signals ?? []).filter((s) => s.approved && signalKinds.includes(s.data.kind as (typeof signalKinds)[number]))
  for (const item of approvedSignals) {
    const title = (item.data as { label?: string }).label ?? (item.data as { kind?: string }).kind ?? 'Signal'
    const assetCount = (item.assignedAssetIds ?? []).length
    lines.push({
      kind: 'create',
      effectiveType: 'signal',
      title,
      parent: isParentLink(item) && item.parentLink ? { parentType: item.parentLink.parentType, parentId: item.parentLink.parentId } : undefined,
      personCount: 0,
      assetCount,
    })
  }
  return lines
}

/** Commit all approved items; routing by effectiveType (overrideType ?? kind). */
export async function commitStagedItems(
  staging: StagingArea,
  ctx: CommitContext
): Promise<CommitResult> {
  const result: CommitResult = {
    created: { ideas: 0, initiatives: 0, projects: 0, tasks: 0, assets: 0, persons: 0 },
    createdRefs: [],
    errors: [],
  }
  const createdInitiatives: { title: string; id: string }[] = []
  const createdProjects: { title: string; id: string }[] = []

  const getInitiativeId = (title: string): string | null => {
    const existing = ctx.existingInitiatives.find((i) => i.title === title)
    if (existing) return existing.id
    const created = createdInitiatives.find((c) => c.title === title)
    return created?.id ?? null
  }
  const getProjectId = (title: string): string | null => {
    const existing = ctx.existingProjects.find((p) => p.title === title)
    if (existing) return existing.id
    const created = createdProjects.find((c) => c.title === title)
    return created?.id ?? null
  }

  const items = collectApprovedByEffectiveType(staging)

  for (const { item, effectiveType } of items) {
    if (item.acceptedExistingId) continue

    const data = item.data as unknown as Record<string, unknown>
    const assignedPersonIds = item.assignedPersonIds ?? []
    const assignedAssetIds = item.assignedAssetIds ?? []
    const parentLink = isParentLink(item) ? item.parentLink : null
    const ownerId = assignedPersonIds[0] ?? null

    try {
      if (effectiveType === 'idea') {
        const p = toCreateIdeaPayload(data as unknown as Parameters<typeof toCreateIdeaPayload>[0])
        p.title = getDataTitle(data)
        p.description = withTraceability(p.description ?? '', data.sourceExcerpt as string | null)
        const ideaRes = (await ctx.apiPost('/ideas', p)) as { id?: string }
        result.created.ideas++
        if (ideaRes?.id)
          result.createdRefs.push({
            entity_type: 'idea',
            id: ideaRes.id,
            title: getDataTitle(data),
          })
      } else if (effectiveType === 'initiative') {
        const sourceIdeaId = parentLink?.parentType === 'idea' ? parentLink.parentId : null
        const p = toCreateInitiativePayload(
          data as unknown as Parameters<typeof toCreateInitiativePayload>[0],
          ownerId,
          sourceIdeaId,
          assignedAssetIds.length > 0 ? assignedAssetIds : undefined
        )
        p.title = getDataTitle(data)
        p.notes = withTraceability(p.notes ?? '', data.sourceExcerpt as string | null)
        const res = (await ctx.apiPost('/initiatives', p)) as { id: string; title?: string }
        result.created.initiatives++
        if (res?.id) {
          const t = (res as { title?: string }).title ?? getDataTitle(data)
          createdInitiatives.push({ title: t, id: res.id })
          result.createdRefs.push({ entity_type: 'initiative', id: res.id, title: t })
        }
      } else if (effectiveType === 'project') {
        const overrideInitiativeId = parentLink?.parentType === 'initiative' ? parentLink.parentId : null
        const p = toCreateProjectPayload(
          data as unknown as Parameters<typeof toCreateProjectPayload>[0],
          getInitiativeId,
          overrideInitiativeId,
          ownerId,
          assignedAssetIds.length > 0 ? assignedAssetIds : undefined
        )
        p.title = getDataTitle(data)
        p.notes = withTraceability(p.notes || '', data.sourceExcerpt as string | null)
        const res = (await ctx.apiPost('/projects', p)) as { id: string; title?: string }
        result.created.projects++
        if (res?.id) {
          const t = (res as { title?: string }).title ?? getDataTitle(data)
          createdProjects.push({ title: t, id: res.id })
          result.createdRefs.push({ entity_type: 'project', id: res.id, title: t })
        }
      } else if (effectiveType === 'task') {
        const projectId =
          (parentLink?.parentType === 'project' ? parentLink.parentId : null)
          ?? (data.existingProjectMatchId as string | null)
          ?? (data.projectId as string | null)
          ?? (data.projectTitle ? getProjectId(data.projectTitle as string) : null)
        const taskData = { ...data, title: getDataTitle(data) }
        const p = toCreateTaskPayload(
          taskData as unknown as Parameters<typeof toCreateTaskPayload>[0],
          projectId && String(projectId).length > 0 ? String(projectId) : null,
          undefined,
          ownerId,
          assignedAssetIds.length > 0 ? assignedAssetIds : undefined
        )
        p.notes = withTraceability(p.notes ?? '', data.sourceExcerpt as string | null)
        const taskRes = (await ctx.apiPost('/tasks', p)) as { id?: string }
        result.created.tasks++
        if (taskRes?.id)
          result.createdRefs.push({
            entity_type: 'task',
            id: taskRes.id,
            title: getDataTitle(data),
          })
      } else if (effectiveType === 'asset') {
        const assetData = {
          name: (data.name as string) ?? (data.title as string) ?? 'Untitled',
          kind: (data.kind as string) ?? 'other',
          description: (data.description as string) ?? (data.brief as string) ?? '',
          sourceExcerpt: data.sourceExcerpt,
        }
        const p = toCreateAssetPayload(assetData as unknown as Parameters<typeof toCreateAssetPayload>[0], ownerId)
        p.notes = withTraceability(p.notes ?? '', data.sourceExcerpt as string | null)
        const assetRes = (await ctx.apiPost('/assets', p)) as { id?: string; name?: string }
        result.created.assets++
        if (assetRes?.id)
          result.createdRefs.push({
            entity_type: 'asset',
            id: assetRes.id,
            title: assetRes.name ?? getDataTitle(data),
          })
      } else if (effectiveType === 'person') {
        const personData = {
          name: (data.name as string) ?? (data.title as string) ?? 'Unknown',
          role: (data.role as string) ?? '',
          context: (data.notes as string) ?? (data.context as string) ?? '',
          sourceExcerpt: data.sourceExcerpt,
        }
        const p = toCreatePersonPayload(personData as unknown as Parameters<typeof toCreatePersonPayload>[0])
        p.notes = withTraceability(p.notes ?? '', data.sourceExcerpt as string | null)
        const personRes = (await ctx.apiPost('/persons', p)) as { id?: string; name?: string }
        result.created.persons++
        if (personRes?.id)
          result.createdRefs.push({
            entity_type: 'person',
            id: personRes.id,
            title: personRes.name ?? getDataTitle(data),
          })
      }
    } catch (e) {
      result.errors.push(`${effectiveType} "${getDataTitle(data)}": ${e instanceof Error ? e.message : 'Failed'}`)
    }
  }

  return result
}
