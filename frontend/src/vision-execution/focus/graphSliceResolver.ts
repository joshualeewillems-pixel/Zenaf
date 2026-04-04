/**
 * resolveGraphSliceVE — Vision Execution graph lane from focus pointer + VE entity snapshot.
 * No field whitelists: whole entities are copied into node.data.
 */

import { canonicalCoreProfileId } from '../canonicalCoreProfile'
import type { FocusContextCore } from './types'
import type { GraphFocusSlice, GraphNodeKind, GraphNodeSnapshot, VeGraphDataSnapshot } from './graphSliceTypes'

const MAX_CHILDREN = 50
const MAX_LINKED = 40
const MAX_MATCHED = 20

function asRecord(o: unknown): Record<string, unknown> {
  if (o && typeof o === 'object' && !Array.isArray(o)) return { ...(o as Record<string, unknown>) }
  return {}
}

/** Keys often used for mediation / extraction — duplicated in node.system for quick access */
function extractSystemMetadata(data: Record<string, unknown>): Record<string, unknown> | undefined {
  const keys = [
    'interpretation',
    'action',
    'payload',
    'matchConfidence',
    'match_confidence',
    'consolidationMeta',
    'sourceExcerpt',
    'sourceQuote',
    'segmentId',
    'segmentTitle',
    'existingInitiativeMatchId',
    'existingProjectMatchId',
    'existingTaskMatchId',
    'existingPersonMatchId',
    'existingAssetMatchId',
    'possibleMatches',
  ] as const
  const out: Record<string, unknown> = {}
  for (const k of keys) {
    if (k in data && data[k] !== undefined) out[k] = data[k] as unknown
  }
  return Object.keys(out).length > 0 ? out : undefined
}

function makeNode(
  kind: GraphNodeKind,
  id: string,
  raw: unknown,
  hierarchyHint?: GraphNodeSnapshot['hierarchyHint'],
): GraphNodeSnapshot {
  const data = asRecord(raw)
  const sys = extractSystemMetadata(data)
  return {
    id,
    kind,
    data,
    relationships: { parent: null, children: [], linked: [], matched: [] },
    ...(sys ? { system: sys } : {}),
    ...(hierarchyHint ? { hierarchyHint } : {}),
  }
}

function coreProfileKey(id: string): string {
  return `core_profile:${id}`
}

function addMatched(
  rel: GraphNodeSnapshot['relationships'],
  kind: GraphNodeKind,
  id: string | null | undefined,
  source?: string,
) {
  const sid = typeof id === 'string' && id.trim() ? id.trim() : ''
  if (!sid) return
  if (rel.matched.length >= MAX_MATCHED) return
  rel.matched.push({ kind, id: sid, source })
}

/**
 * Build the VE graph slice for the current focus pointer and loaded VE data.
 */
export function resolveGraphSliceVE(
  focus: FocusContextCore | null,
  graph: VeGraphDataSnapshot | null | undefined,
): GraphFocusSlice | null {
  if (!focus) return null
  const resolvedAt = new Date().toISOString()
  if (focus.entity_type === 'app_field') {
    return {
      anchor: { kind: 'draft', id: focus.entity_id, fieldKey: focus.field_key },
      nodes: {},
      edges: [],
      resolvedAt,
      dataUnavailable: true,
    }
  }
  if (!graph) {
    return {
      anchor: {
        kind: mapEntityTypeToKind(focus.entity_type),
        id: focus.entity_id,
        fieldKey: focus.field_key,
      },
      nodes: {},
      edges: [],
      resolvedAt,
      dataUnavailable: true,
    }
  }

  const f = focus

  const nodes: Record<string, GraphNodeSnapshot> = {}
  const edges: GraphFocusSlice['edges'] = []

  const { coreProfiles, ideas, initiatives, projects, tasks, persons, assets, capacityProfiles } = graph

  const ideaById = new Map(ideas.map((i) => [i.id, i]))
  const iniById = new Map(initiatives.map((i) => [i.id, i]))
  const projById = new Map(projects.map((p) => [p.id, p]))
  const taskById = new Map(tasks.map((t) => [t.id, t]))
  const personById = new Map(persons.map((p) => [p.id, p]))
  const assetById = new Map(assets.map((a) => [a.id, a]))

  const canonicalCoreRowId =
    coreProfiles.length > 0 ? canonicalCoreProfileId(coreProfiles) : null
  const multipleCoreProfiles = coreProfiles.length > 1

  function coreProfileHierarchyHint(profileRowId: string): GraphNodeSnapshot['hierarchyHint'] {
    return multipleCoreProfiles &&
      canonicalCoreRowId != null &&
      profileRowId !== canonicalCoreRowId
      ? 'legacy_secondary_core'
      : undefined
  }

  function ensureNode(
    kind: GraphNodeKind,
    id: string,
    raw: unknown,
    hierarchyHint?: GraphNodeSnapshot['hierarchyHint'],
  ): GraphNodeSnapshot | null {
    const key = kind === 'core_profile' ? coreProfileKey(id) : id
    if (nodes[key]) return nodes[key]!
    const n = makeNode(kind, key, raw, hierarchyHint)
    nodes[key] = n
    return n
  }

  // Active / relevant profiles: include all loaded profiles (typically small)
  for (const p of coreProfiles) {
    ensureNode('core_profile', p.id, p, coreProfileHierarchyHint(p.id))
  }

  const anchorKind = mapEntityTypeToKind(f.entity_type)
  const anchorId = f.entity_id

  function wireAnchor(): GraphNodeSnapshot | null {
    if (f.entity_type === 'council') {
      return ensureNode('council', anchorId, { synthetic: true, entity_id: anchorId })
    }

    if (anchorKind === 'core_profile') {
      const row = coreProfiles.find((p) => p.id === anchorId)
      return row
        ? ensureNode('core_profile', anchorId, row, coreProfileHierarchyHint(anchorId))
        : ensureNode('draft', anchorId, { id: anchorId, pending: true })
    }

    if (anchorKind === 'idea') {
      const row = ideaById.get(anchorId)
      return row ? ensureNode('idea', anchorId, row) : ensureNode('draft', anchorId, { id: anchorId, pending: true })
    }
    if (anchorKind === 'initiative') {
      const row = iniById.get(anchorId)
      return row ? ensureNode('initiative', anchorId, row) : ensureNode('draft', anchorId, { id: anchorId, pending: true })
    }
    if (anchorKind === 'project') {
      const row = projById.get(anchorId)
      return row ? ensureNode('project', anchorId, row) : ensureNode('draft', anchorId, { id: anchorId, pending: true })
    }
    if (anchorKind === 'task') {
      const row = taskById.get(anchorId)
      return row ? ensureNode('task', anchorId, row) : ensureNode('draft', anchorId, { id: anchorId, pending: true })
    }
    return ensureNode('draft', anchorId, { id: anchorId, kind: f.entity_type })
  }

  const anchorNode = wireAnchor()
  if (!anchorNode) {
    return {
      anchor: { kind: anchorKind, id: anchorId, fieldKey: f.field_key },
      nodes,
      edges,
      resolvedAt,
    }
  }

  // Relationships from anchor
  const rel = anchorNode.relationships

  if (anchorKind === 'idea') {
    const idea = ideaById.get(anchorId)
    if (idea) {
      for (const lid of (idea.linked_ideas ?? []).slice(0, MAX_LINKED)) {
        const row = ideaById.get(lid)
        if (row) {
          ensureNode('idea', lid, row)
          rel.linked.push({ kind: 'idea', id: lid, edge: 'linked_ideas' })
          edges.push({ from: anchorId, to: lid, relation: 'linked_ideas' })
        }
      }
      for (const pid of (idea.linked_people ?? []).slice(0, MAX_LINKED)) {
        const row = personById.get(pid)
        if (row) {
          ensureNode('person', pid, row)
          rel.linked.push({ kind: 'person', id: pid, edge: 'linked_people' })
          edges.push({ from: anchorId, to: pid, relation: 'linked_people' })
        }
      }
      for (const aid of (idea.linked_assets ?? []).slice(0, MAX_LINKED)) {
        const row = assetById.get(aid)
        if (row) {
          ensureNode('asset', aid, row)
          rel.linked.push({ kind: 'asset', id: aid, edge: 'linked_assets' })
          edges.push({ from: anchorId, to: aid, relation: 'linked_assets' })
        }
      }
      const inis = initiatives.filter((i) => i.source_idea_id === anchorId).slice(0, MAX_CHILDREN)
      for (const ini of inis) {
        ensureNode('initiative', ini.id, ini)
        rel.children.push({ kind: 'initiative', id: ini.id, relation: 'source_idea' })
        edges.push({ from: anchorId, to: ini.id, relation: 'source_idea' })
      }
    }
  }

  if (anchorKind === 'initiative') {
    const ini = iniById.get(anchorId)
    if (ini) {
      if (ini.source_idea_id) {
        const src = ideaById.get(ini.source_idea_id)
        if (src) {
          ensureNode('idea', ini.source_idea_id, src)
          rel.parent = { kind: 'idea', id: ini.source_idea_id }
          edges.push({ from: anchorId, to: ini.source_idea_id, relation: 'source_idea_id' })
        }
      }
      const kids = projects.filter((p) => p.initiative_id === anchorId).slice(0, MAX_CHILDREN)
      for (const p of kids) {
        ensureNode('project', p.id, p)
        rel.children.push({ kind: 'project', id: p.id, relation: 'initiative' })
        edges.push({ from: anchorId, to: p.id, relation: 'under_initiative' })
      }
    }
  }

  if (anchorKind === 'project') {
    const proj = projById.get(anchorId)
    if (proj) {
      if (proj.initiative_id) {
        const ini = iniById.get(proj.initiative_id)
        if (ini) {
          ensureNode('initiative', proj.initiative_id, ini)
          rel.parent = { kind: 'initiative', id: proj.initiative_id }
          edges.push({ from: anchorId, to: proj.initiative_id, relation: 'initiative_id' })
        }
      }
      const kids = tasks.filter((t) => t.project_id === anchorId).slice(0, MAX_CHILDREN)
      for (const t of kids) {
        ensureNode('task', t.id, t)
        rel.children.push({ kind: 'task', id: t.id, relation: 'project' })
        edges.push({ from: anchorId, to: t.id, relation: 'under_project' })
      }
      for (const pid of proj.supporting_owner_ids ?? []) {
        const row = personById.get(pid)
        if (row) {
          ensureNode('person', pid, row)
          rel.linked.push({ kind: 'person', id: pid, edge: 'supporting_owner' })
        }
      }
    }
  }

  if (anchorKind === 'task') {
    const task = taskById.get(anchorId)
    if (task) {
      if (task.project_id) {
        const proj = projById.get(task.project_id)
        if (proj) {
          ensureNode('project', task.project_id, proj)
          rel.parent = { kind: 'project', id: task.project_id }
          edges.push({ from: anchorId, to: task.project_id, relation: 'project_id' })
          if (proj.initiative_id) {
            const ini = iniById.get(proj.initiative_id)
            if (ini) {
              ensureNode('initiative', proj.initiative_id, ini)
              edges.push({ from: task.project_id, to: proj.initiative_id, relation: 'initiative_id' })
            }
          }
        }
      }
      if (task.parent_task_id) {
        const pt = taskById.get(task.parent_task_id)
        if (pt) {
          ensureNode('task', task.parent_task_id, pt)
          rel.parent = { kind: 'task', id: task.parent_task_id }
          edges.push({ from: anchorId, to: task.parent_task_id, relation: 'parent_task' })
        }
      }
      const tr = asRecord(task)
      addMatched(rel, 'initiative', tr.existingInitiativeMatchId as string | undefined, 'existingInitiativeMatchId')
      addMatched(rel, 'project', tr.existingProjectMatchId as string | undefined, 'existingProjectMatchId')
      addMatched(rel, 'task', tr.existingTaskMatchId as string | undefined, 'existingTaskMatchId')
      addMatched(rel, 'person', tr.existingPersonMatchId as string | undefined, 'existingPersonMatchId')
    }
  }

  // Parent descriptor from focus (UI lineage)
  if (f.parent?.entity_id && f.parent.entity_type) {
    const pk = mapEntityTypeToKind(f.parent.entity_type)
    const pid = f.parent.entity_id
    if (pk === 'idea' && ideaById.get(pid)) ensureNode('idea', pid, ideaById.get(pid))
    else if (pk === 'initiative' && iniById.get(pid)) ensureNode('initiative', pid, iniById.get(pid))
    else if (pk === 'project' && projById.get(pid)) ensureNode('project', pid, projById.get(pid))
    else if (pk === 'task' && taskById.get(pid)) ensureNode('task', pid, taskById.get(pid))
    edges.push({ from: anchorId, to: pid, relation: 'focus_parent' })
  }

  // Capacity profiles (linked by convention — owner_id on entities)
  if (anchorKind === 'initiative' || anchorKind === 'project' || anchorKind === 'task') {
    const row = asRecord(anchorNode.data)
    const ownerId = row.owner_id as string | null | undefined
    if (ownerId && personById.get(ownerId)) {
      ensureNode('person', ownerId, personById.get(ownerId))
      edges.push({ from: anchorId, to: ownerId, relation: 'owner' })
    }
  }

  for (const cp of capacityProfiles) {
    const kid = `capacity_profile:${cp.person_id}`
    if (!nodes[kid]) {
      nodes[kid] = makeNode('capacity_profile', kid, cp)
    }
  }

  return {
    anchor: { kind: anchorKind, id: anchorId, fieldKey: f.field_key },
    nodes,
    edges,
    resolvedAt,
  }
}

function mapEntityTypeToKind(t: FocusContextCore['entity_type']): GraphNodeKind {
  if (t === 'council') return 'council'
  if (t === 'core_profile') return 'core_profile'
  if (t === 'app_field') return 'draft'
  return t
}

/** @deprecated Use resolveGraphSliceVE — kept for incremental migration of imports */
export const resolveGraphSlice = resolveGraphSliceVE
