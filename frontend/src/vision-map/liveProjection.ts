/**
 * Live projection: Vision Execution entities → React Flow graph (no new backend ontology).
 *
 * Fruit (outcomes): project status looks shipped/done AND non-empty `deliverables` only (staged rule).
 * Water / fertilizer: see `mapVitalForces.ts` (simple, explainable tiers + pulse triggers).
 */
import type { Edge, Node } from '@xyflow/react'
import type { MapEdgeTier } from './MapFlowEdge'
import type { Project, Task } from '../vision-execution/types'
import { conditionFromSignals, growthFromStatus, isStaleIso } from './deriveVisualState'
import { findCouncilPreviewForRef } from './councilCorrelation'
import type { ConditionState, MapEntityRef, MapNodePayload, WaterLevel } from './ontology'
import type { StudioCouncilRunRow } from './studioCouncilTypes'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { ServerNodeVitalityMap } from './veMapApi'
import { PROJECTION_UNSCOPED_INITIATIVE_ID } from './mapCouncilActions'
import { computeMapEdgeVitality, type MapEdgeEndpointMeta } from './mapEdgeVitality'
import {
  deriveFertilizerPulse,
  edgeWaterTone,
  vitalBare,
  vitalForIdea,
  vitalForInitiative,
  vitalForProject,
  vitalForTask,
  waterLevelFromVital,
  type VitalInput,
} from './mapVitalForces'
import {
  branchAnglesForCount,
  branchTopLeft,
  columnWidthForBranchCount,
  fruitTopLeft,
  seedTopLeftAboveTree,
  taskTopLeft,
  treeTopLeftForColumn,
  VISION_MAP_LAYOUT,
} from './mapVisionLayout'
import { mapVisualTriad } from './mapGrowthMetrics'

const UNSCOPED_INIT_ID = PROJECTION_UNSCOPED_INITIATIVE_ID
/** Merged onto React Flow’s outer node wrapper — strips theme borders/shadows */
const RF_STONE_WRAPPER_CLASS = 'map-rf-node-stone'

function newestIso(dates: (string | null | undefined)[]): string | null {
  let best = 0
  for (const d of dates) {
    const t = d ? Date.parse(d) : NaN
    if (Number.isFinite(t) && t > best) best = t
  }
  return best > 0 ? new Date(best).toISOString() : null
}

function resolvedCondition(
  ref: MapEntityRef,
  base: ConditionState,
  councilRuns: StudioCouncilRunRow[],
): ConditionState {
  return mergeCondition(base, findCouncilPreviewForRef(councilRuns, ref))
}

function mapFlowEdge(
  id: string,
  source: string,
  target: string,
  tier: MapEdgeTier,
  endpoints?: { source?: MapEdgeEndpointMeta; target?: MapEdgeEndpointMeta },
): Edge {
  const vitality = computeMapEdgeVitality(endpoints?.source, endpoints?.target, tier)
  const waterTone = edgeWaterTone(endpoints?.source?.water_level, endpoints?.target?.water_level)
  return { id, source, target, type: 'mapFlow', data: { tier, vitality, waterTone } }
}

type TreeProjectionCtx = {
  treeTouch: string | null
  treeCondition: ConditionState
  treeWaterLevel: WaterLevel
}

function mergeCondition(base: ConditionState, preview?: ReturnType<typeof findCouncilPreviewForRef>): ConditionState {
  if (preview?.teacher_vetoed) return 'teacher-vetoed'
  if (preview?.teacher_warning) return 'teacher-warned'
  return base
}

function projectLooksDone(p: Project): boolean {
  return /\b(done|complete|shipped|closed|won)\b/i.test(p.status || '')
}

function clip(s: string, n: number): string {
  const t = s.trim()
  if (t.length <= n) return t
  return `${t.slice(0, n - 1)}…`
}

function payload(
  partial: Omit<MapNodePayload, 'growth' | 'condition' | 'water_level' | 'fertilizer_pulse'> & {
    growth?: MapNodePayload['growth']
    condition?: ConditionState
  },
  councilRuns: StudioCouncilRunRow[],
  vital: VitalInput,
): MapNodePayload {
  const ref = partial.ref as MapEntityRef
  const preview = findCouncilPreviewForRef(councilRuns, ref)
  const growth = partial.growth ?? 'growing'
  const baseCond = partial.condition ?? 'healthy'
  const water_level = waterLevelFromVital(vital)
  const fertilizer_pulse = deriveFertilizerPulse(ref, vital.entityUpdatedAt ?? null, councilRuns)
  return {
    ...partial,
    growth,
    condition: mergeCondition(baseCond, preview),
    councilTeacher: preview,
    water_level,
    fertilizer_pulse,
    dimmed: false,
  } as MapNodePayload
}

function applyServerVitality(data: MapNodePayload, serverVitality?: ServerNodeVitalityMap): MapNodePayload {
  if (!serverVitality) {
    return { ...data, vitality_source: 'client' }
  }
  const key = `${data.ref.veType}:${data.ref.id}`
  const s = serverVitality[key]
  if (!s || ![s.water, s.soil, s.fruit].every((n) => typeof n === 'number' && Number.isFinite(n))) {
    return { ...data, vitality_source: 'client' }
  }
  return {
    ...data,
    growth_triad: { water: s.water, soil: s.soil, fruit: s.fruit },
    vitality_source: 'server',
  }
}

function finalizeMapNodePayload(
  data: MapNodePayload,
  bundle: VisionMapEntityBundle,
  serverVitality?: ServerNodeVitalityMap,
): MapNodePayload {
  const v = applyServerVitality(data, serverVitality)
  return { ...v, map_visual_triad: mapVisualTriad(v, bundle) }
}

export function buildLiveVisionMapGraph(
  bundle: VisionMapEntityBundle,
  councilRuns: StudioCouncilRunRow[],
  serverVitality?: ServerNodeVitalityMap,
): { nodes: Node<MapNodePayload>[]; edges: Edge[] } {
  const { ideas, initiatives, projects, tasks } = bundle
  const nodes: Node<MapNodePayload>[] = []
  const edges: Edge[] = []

  const initiativesSorted = [...initiatives].sort((a, b) => (a.title || '').localeCompare(b.title || ''))
  const ideaById = new Map(ideas.map((i) => [i.id, i]))
  const projectsByInit = new Map<string, Project[]>()
  for (const p of projects) {
    const k = p.initiative_id || UNSCOPED_INIT_ID
    const list = projectsByInit.get(k) || []
    list.push(p)
    projectsByInit.set(k, list)
  }

  let maxProjectsInColumn = 1
  for (const plist of projectsByInit.values()) {
    if (plist.length > maxProjectsInColumn) maxProjectsInColumn = plist.length
  }
  const colW = columnWidthForBranchCount(maxProjectsInColumn)

  const sourcedIdeaIds = new Set(initiatives.map((i) => i.source_idea_id).filter(Boolean) as string[])
  const orphanIdeas = ideas.filter((i) => !sourcedIdeaIds.has(i.id))
  const seedNodeAdded = new Set<string>()

  let orphanCol = 0
  for (const idea of orphanIdeas) {
    const x = orphanCol * VISION_MAP_LAYOUT.ORPHAN_COLUMN_PITCH
    const yOrphan = -56 + (orphanCol % 3) * 28
    orphanCol += 1
    const ref: MapEntityRef = { veType: 'idea', id: idea.id }
    const stale = isStaleIso(idea.updated_at, 45)
    seedNodeAdded.add(idea.id)
    const vSeed = vitalForIdea(idea)
    nodes.push({
      id: `seed-${idea.id}`,
      type: 'entityMap',
      className: RF_STONE_WRAPPER_CLASS,
      position: { x, y: yOrphan },
      data: finalizeMapNodePayload(
        payload(
          {
            kind: 'seed',
            label: idea.title || 'Untitled idea',
            subtitle: 'Idea (seed)',
            ref,
            summaryLines: [
              clip(idea.summary || idea.description || '', 240),
              `Status: ${idea.status}`,
              idea.desired_outcome ? `Desired outcome: ${clip(idea.desired_outcome, 160)}` : '',
            ].filter(Boolean),
            growth: growthFromStatus(idea.status),
            condition: conditionFromSignals({ stale }),
          },
          councilRuns,
          vSeed,
        ),
        bundle,
        serverVitality,
      ),
    })
  }

  const unscoped = projectsByInit.get(UNSCOPED_INIT_ID) || []
  if (unscoped.length > 0) {
    const col = initiativesSorted.length
    const columnCenterX = col * colW + colW / 2
    const treeTL = treeTopLeftForColumn(columnCenterX, VISION_MAP_LAYOUT.TREE_TOP_Y)
    const ref: MapEntityRef = { veType: 'initiative', id: UNSCOPED_INIT_ID }
    const uTouch = newestIso(unscoped.map((p) => p.updated_at))
    const vUnscopedTree = vitalBare(uTouch)
    nodes.push({
      id: `tree-${UNSCOPED_INIT_ID}`,
      type: 'entityMap',
      className: RF_STONE_WRAPPER_CLASS,
      position: treeTL,
      data: finalizeMapNodePayload(
        payload(
          {
            kind: 'tree',
            label: 'Unscoped work',
            subtitle: 'Initiative (projection)',
            ref,
            summaryLines: [
              'Projects with no initiative_id; shown for visibility. Assign an initiative in operator mode.',
              `${unscoped.length} project(s)`,
            ],
            growth: 'dormant',
            condition: 'healthy',
          },
          councilRuns,
          vUnscopedTree,
        ),
        bundle,
        serverVitality,
      ),
    })
    const uTreeCond = resolvedCondition(ref, 'healthy', councilRuns)
    layoutProjectsUnderTree(
      UNSCOPED_INIT_ID,
      treeTL,
      unscoped,
      tasks,
      nodes,
      edges,
      councilRuns,
      {
        treeTouch: uTouch,
        treeCondition: uTreeCond,
        treeWaterLevel: waterLevelFromVital(vUnscopedTree),
      },
      bundle,
      serverVitality,
    )
  }

  initiativesSorted.forEach((ini, col) => {
    const columnCenterX = col * colW + colW / 2
    const treeTL = treeTopLeftForColumn(columnCenterX, VISION_MAP_LAYOUT.TREE_TOP_Y)
    const treeId = `tree-${ini.id}`
    const idea = ini.source_idea_id ? ideaById.get(ini.source_idea_id) : undefined

    const iniRef: MapEntityRef = { veType: 'initiative', id: ini.id }
    const iniStale = isStaleIso(ini.updated_at, 30)
    const treeCondEarly = resolvedCondition(iniRef, conditionFromSignals({ stale: iniStale }), councilRuns)
    const vIni = vitalForInitiative(ini)

    if (idea) {
      const iref: MapEntityRef = { veType: 'idea', id: idea.id }
      const stale = isStaleIso(idea.updated_at, 45)
      const ideaBase = conditionFromSignals({ stale })
      const vIdea = vitalForIdea(idea)
      if (!seedNodeAdded.has(idea.id)) {
        seedNodeAdded.add(idea.id)
        nodes.push({
          id: `seed-${idea.id}`,
          type: 'entityMap',
          className: RF_STONE_WRAPPER_CLASS,
          position: seedTopLeftAboveTree(treeTL),
          data: finalizeMapNodePayload(
            payload(
              {
                kind: 'seed',
                label: idea.title || 'Idea',
                subtitle: 'Idea (seed)',
                ref: iref,
                summaryLines: [
                  clip(idea.summary || idea.description || '', 200),
                  `Status: ${idea.status}`,
                ].filter(Boolean),
                growth: growthFromStatus(idea.status),
                condition: ideaBase,
              },
              councilRuns,
              vIdea,
            ),
            bundle,
            serverVitality,
          ),
        })
      }
      const seedCond = resolvedCondition(iref, ideaBase, councilRuns)
      edges.push(
        mapFlowEdge(`e-seed-${idea.id}-${ini.id}`, `seed-${idea.id}`, treeId, 'trunk', {
          source: {
            touch: idea.updated_at ?? null,
            condition: seedCond,
            water_level: waterLevelFromVital(vIdea),
          },
          target: {
            touch: ini.updated_at ?? null,
            condition: treeCondEarly,
            water_level: waterLevelFromVital(vIni),
          },
        }),
      )
    }
    nodes.push({
      id: treeId,
      type: 'entityMap',
      className: RF_STONE_WRAPPER_CLASS,
      position: treeTL,
      data: finalizeMapNodePayload(
        payload(
          {
            kind: 'tree',
            label: ini.title || 'Initiative',
            subtitle: 'Initiative (tree)',
            ref: iniRef,
            summaryLines: [
              clip(ini.brief || '', 220),
              `Status: ${ini.status}`,
              ini.next_step_ai ? `Next step: ${clip(ini.next_step_ai, 120)}` : '',
            ].filter(Boolean),
            growth: growthFromStatus(ini.status),
            condition: conditionFromSignals({ stale: iniStale }),
          },
          councilRuns,
          vIni,
        ),
        bundle,
        serverVitality,
      ),
    })

    const treeCond = treeCondEarly

    const plist = projectsByInit.get(ini.id) || []
    layoutProjectsUnderTree(ini.id, treeTL, plist, tasks, nodes, edges, councilRuns, {
      treeTouch: ini.updated_at ?? null,
      treeCondition: treeCond,
      treeWaterLevel: waterLevelFromVital(vIni),
    }, bundle, serverVitality)
  })

  return { nodes, edges }
}

function layoutProjectsUnderTree(
  initiativeKey: string,
  treeTopLeft: { x: number; y: number },
  plist: Project[],
  tasks: Task[],
  nodes: Node<MapNodePayload>[],
  edges: Edge[],
  councilRuns: StudioCouncilRunRow[],
  treeCtx: TreeProjectionCtx,
  bundle: VisionMapEntityBundle,
  serverVitality?: ServerNodeVitalityMap,
) {
  const treeId = `tree-${initiativeKey}`
  const sorted = [...plist].sort((a, b) => (a.title || '').localeCompare(b.title || ''))
  const angles = branchAnglesForCount(sorted.length)

  sorted.forEach((proj, pi) => {
    const branchId = `branch-${proj.id}`
    const theta = angles[pi] ?? Math.PI / 2
    const branchPos = branchTopLeft(treeTopLeft, theta)
    const pStale = isStaleIso(proj.updated_at, 21)
    const pref: MapEntityRef = { veType: 'project', id: proj.id }
    const branchBaseCond = conditionFromSignals({ stale: pStale })
    const vProj = vitalForProject(proj)
    nodes.push({
      id: branchId,
      type: 'entityMap',
      className: RF_STONE_WRAPPER_CLASS,
      position: branchPos,
      data: finalizeMapNodePayload(
        payload(
          {
            kind: 'branch',
            label: proj.title || 'Project',
            subtitle: 'Project (branch)',
            ref: pref,
            summaryLines: [
              clip(proj.brief || '', 180),
              `Status: ${proj.status}`,
              proj.next_step_ai ? `Next: ${clip(proj.next_step_ai, 100)}` : '',
            ].filter(Boolean),
            growth: growthFromStatus(proj.status),
            condition: branchBaseCond,
          },
          councilRuns,
          vProj,
        ),
        bundle,
        serverVitality,
      ),
    })
    const branchCond = resolvedCondition(pref, branchBaseCond, councilRuns)
    const wBranch = waterLevelFromVital(vProj)
    edges.push(
      mapFlowEdge(`e-${treeId}-${branchId}`, treeId, branchId, 'structural', {
        source: {
          touch: treeCtx.treeTouch,
          condition: treeCtx.treeCondition,
          water_level: treeCtx.treeWaterLevel,
        },
        target: { touch: proj.updated_at ?? null, condition: branchCond, water_level: wBranch },
      }),
    )

    if (projectLooksDone(proj) && (proj.deliverables || '').trim()) {
      const fid = `fruit-proj-${proj.id}-deliver`
      const fruitRef: MapEntityRef = { veType: 'outcome', id: fid }
      nodes.push({
        id: fid,
        type: 'entityMap',
        className: RF_STONE_WRAPPER_CLASS,
        position: fruitTopLeft(treeTopLeft, theta),
        data: finalizeMapNodePayload(
          payload(
            {
              kind: 'fruit',
              label: clip(proj.deliverables.trim(), 72),
              subtitle: 'Outcome (fruit)',
              ref: fruitRef,
              parentRef: pref,
              summaryLines: [
                'From completed/shipped project `deliverables` column.',
                clip(proj.deliverables.trim(), 400),
              ],
              growth: 'fruiting',
              condition: 'healthy',
            },
            councilRuns,
            vProj,
          ),
          bundle,
          serverVitality,
        ),
      })
      const deliverCond = resolvedCondition(fruitRef, 'healthy', councilRuns)
      edges.push(
        mapFlowEdge(`e-${branchId}-${fid}`, branchId, fid, 'outcome', {
          source: { touch: proj.updated_at ?? null, condition: branchCond, water_level: wBranch },
          target: { touch: proj.updated_at ?? null, condition: deliverCond, water_level: wBranch },
        }),
      )
    }

    const ptasks = tasks
      .filter((t) => t.project_id === proj.id)
      .sort((a, b) => (a.title || '').localeCompare(b.title || ''))
    const nTasks = ptasks.length
    ptasks.forEach((t, ti) => {
      const flowerId = `flower-${t.id}`
      const taskRef: MapEntityRef = { veType: 'task', id: t.id, projectId: proj.id }
      const taskBase = conditionFromSignals({
        blocked: /\bblock/i.test(t.status || ''),
        stale: isStaleIso(t.updated_at, 30),
      })
      const vTask = vitalForTask(t)
      nodes.push({
        id: flowerId,
        type: 'entityMap',
        className: RF_STONE_WRAPPER_CLASS,
        position: taskTopLeft(branchPos, ti, nTasks),
        data: finalizeMapNodePayload(
          payload(
            {
              kind: 'flower',
              label: t.title || 'Task',
              subtitle: 'Task (flower)',
              ref: taskRef,
              summaryLines: [
                `Status: ${t.status}`,
                t.completion_criteria ? `Done when: ${clip(t.completion_criteria, 120)}` : '',
                t.notes ? `Notes: ${clip(t.notes, 100)}` : '',
              ].filter(Boolean),
              growth: growthFromStatus(t.status),
              condition: taskBase,
            },
            councilRuns,
            vTask,
          ),
          bundle,
          serverVitality,
        ),
      })
      const taskCond = resolvedCondition(taskRef, taskBase, councilRuns)
      edges.push(
        mapFlowEdge(`e-${branchId}-${flowerId}`, branchId, flowerId, 'task', {
          source: { touch: proj.updated_at ?? null, condition: branchCond, water_level: wBranch },
          target: {
            touch: t.updated_at ?? null,
            condition: taskCond,
            water_level: waterLevelFromVital(vTask),
          },
        }),
      )
    })
  })
}
