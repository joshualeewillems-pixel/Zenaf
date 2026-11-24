/**
 * Aria's Atelier — pure logic: the garden model, cast scopes, and the
 * layer stack's presentation channels. No React, no fetch — everything
 * here is driven directly by unit tests.
 *
 * THE GARDEN is the user's real Vision-map garden, grouped the way the
 * map groups it: the cairn index comes from the map's own graph build
 * (buildLiveVisionMapGraph + applyCairnMode — a cairn is a project
 * subtree piled: the project's branch stone as the pile's parent, its
 * task flowers as members), and pile members are read through the
 * map's own cairnMembersOf, so the tower layout seats exactly the
 * members the Vision map seats, keyed by their stable ids. Projects
 * the graph left unpiled (no linked members) and standalone tasks are
 * carried as single-stone piles built from the bundle directly —
 * nothing is dropped from Aria's garden that the work contains.
 *
 * CAST SCOPES follow the real hierarchy the data carries: a stone is
 * a task; a project cast throws the whole cairn in; an initiative
 * cast throws the whole undertaking in. A scope that does not exist
 * for a given cairn (a project with no tasks has no stones; a project
 * under no initiative has no initiative cast) is simply absent —
 * never invented.
 *
 * THE STACK channels are the founder's rulings as implemented in the
 * accepted prototype: z-order by interaction recency; fill alpha
 * moment-to-moment on a base-e approach (τ = 0.38s, driven in the
 * view) inside the 10%–80% band, the Discussion slider setting the
 * ceiling; ink never touched; complexity = talk depth per seat about
 * the selected subject, presented as emergence replay depth.
 */
import type { Node } from '@xyflow/react'
import type { CairnIndex } from '../vision-map/cairn'
import { cairnMembersOf } from '../vision-map/cairn'
import type { CairnMemberInput } from '../vision-map/cairnTower'
import type { MapNodePayload } from '../vision-map/ontology'
import type { Initiative, Project, Task } from '../vision-execution/types'

/* ------------------------------------------------------------------ */
/* Voices                                                              */
/* ------------------------------------------------------------------ */

export const VOICES = ['rumi', 'valen', 'maeve', 'lucian', 'aria', 'severine', 'jynx'] as const
export type Voice = (typeof VOICES)[number]

/** Engine archetype id → the voice's personal name (the layer keys). */
export const VOICE_BY_ARCHETYPE: Record<string, Voice> = {
  mentor: 'rumi',
  champion: 'valen',
  guardian: 'maeve',
  ambassador: 'lucian',
  conductor: 'aria',
  skeptic: 'severine',
  maverick: 'jynx',
}

export const VOICE_NAMES: Record<Voice, string> = {
  rumi: 'Rumi',
  valen: 'Valen',
  maeve: 'Maeve',
  lucian: 'Lucian',
  aria: 'Aria',
  severine: 'Severine',
  jynx: 'Jynx',
}

/** The seats' palette (the same colours the water's SEATS table uses). */
export const VOICE_COLORS: Record<Voice, string> = {
  rumi: '#92b692',
  valen: '#e24e4e',
  maeve: '#ac7c5b',
  lucian: '#5c9cea',
  aria: '#8892c3',
  severine: '#a29ac1',
  jynx: '#a55cce',
}

/** Each voice's home in the 1000×1320 field model (the water's SEATS
 *  table) — the point its formation re-forms from on a replay. */
export const VOICE_HOMES: Record<Voice, [number, number]> = {
  valen: [625, 445],
  maeve: [445, 735],
  aria: [500, 590],
  rumi: [295, 400],
  severine: [715, 715],
  lucian: [460, 500],
  jynx: [528, 520],
}

/* ------------------------------------------------------------------ */
/* The garden                                                          */
/* ------------------------------------------------------------------ */

export interface AtelierStone {
  taskId: string
  title: string
  /** The pile member's stable node id — keys the fan stone's sprite
   *  to the sprite the member wears in the pile. */
  memberId: string
}

export interface AtelierCairn {
  /** Stable pile id the tower layout keys on (the map's cairn id for
   *  graph-piled projects). */
  cairnId: string
  projectId: string
  projectTitle: string
  initiativeId: string | null
  initiativeTitle: string | null
  members: CairnMemberInput[]
  stones: AtelierStone[]
}

export interface AtelierLooseStone {
  taskId: string
  title: string
  members: CairnMemberInput[]
}

export interface AtelierGarden {
  cairns: AtelierCairn[]
  looseStones: AtelierLooseStone[]
}

export interface GardenBundle {
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
}

function memberFromTask(t: Task): CairnMemberInput {
  return {
    id: `flower-${t.id}`,
    kind: 'flower',
    activity: 0.5,
    createdAt: t.created_at ?? null,
  }
}

/**
 * Build the Atelier garden from the fetched bundle and the map's own
 * cairn index (from buildLiveVisionMapGraph). Graph-piled projects
 * keep the map's members verbatim (cairnMembersOf); the rest are
 * carried from the bundle so no project or task is dropped.
 */
export function buildGarden(bundle: GardenBundle, cairnIndex: CairnIndex): AtelierGarden {
  const projectById = new Map(bundle.projects.map((p) => [p.id, p]))
  const initiativeById = new Map(bundle.initiatives.map((i) => [i.id, i]))
  const cairns: AtelierCairn[] = []
  const cairnedProjectIds = new Set<string>()
  const stonedTaskIds = new Set<string>()

  for (const entry of Object.values(cairnIndex)) {
    const project = projectById.get(entry.projectId)
    if (!project) continue
    cairnedProjectIds.add(entry.projectId)
    const memberNodes = entry.memberNodes as Array<Node<MapNodePayload>>
    const branch = memberNodes.find(
      (n) => n.data.ref.veType === 'project' && n.data.ref.id === entry.projectId,
    )
    const members = cairnMembersOf(memberNodes, branch?.id)
    const stones: AtelierStone[] = []
    for (const n of memberNodes) {
      if (n.data.ref.veType === 'task') {
        stones.push({ taskId: n.data.ref.id, title: n.data.label, memberId: n.id })
        stonedTaskIds.add(n.data.ref.id)
      }
    }
    const initiative = project.initiative_id ? initiativeById.get(project.initiative_id) : undefined
    cairns.push({
      cairnId: entry.cairnId,
      projectId: entry.projectId,
      projectTitle: entry.projectTitle || project.title,
      initiativeId: project.initiative_id ?? null,
      initiativeTitle: initiative?.title ?? null,
      members,
      stones,
    })
  }

  /* Projects the graph left unpiled: a lone pile from the bundle —
     the project as parent stone, its tasks as members. */
  for (const p of bundle.projects) {
    if (cairnedProjectIds.has(p.id)) continue
    const tasks = bundle.tasks
      .filter((t) => t.project_id === p.id)
      .sort((a, b) => (a.title || '').localeCompare(b.title || ''))
    const members: CairnMemberInput[] = [
      {
        id: `branch-${p.id}`,
        kind: 'branch',
        activity: 0.5,
        createdAt: p.created_at ?? null,
        parent: true,
      },
      ...tasks.map(memberFromTask),
    ]
    const initiative = p.initiative_id ? initiativeById.get(p.initiative_id) : undefined
    cairns.push({
      cairnId: `atelier-cairn-${p.id}`,
      projectId: p.id,
      projectTitle: p.title,
      initiativeId: p.initiative_id ?? null,
      initiativeTitle: initiative?.title ?? null,
      members,
      stones: tasks.map((t) => {
        stonedTaskIds.add(t.id)
        return { taskId: t.id, title: t.title || 'Task', memberId: `flower-${t.id}` }
      }),
    })
  }

  /* Standalone tasks — a single stone, standing alone in the garden. */
  const looseStones: AtelierLooseStone[] = []
  for (const t of bundle.tasks) {
    if (t.project_id || stonedTaskIds.has(t.id)) continue
    looseStones.push({
      taskId: t.id,
      title: t.title || 'Task',
      members: [memberFromTask(t)],
    })
  }

  cairns.sort((a, b) => a.projectTitle.localeCompare(b.projectTitle))
  looseStones.sort((a, b) => a.title.localeCompare(b.title))
  return { cairns, looseStones }
}

/**
 * Deterministic garden layout: cairns and loose stones on a ring
 * around the well (centre 50%, 44%), starting at the top and running
 * clockwise, clamped inside the field. Pure — the same garden always
 * lays out the same way.
 */
export function gardenPositions(count: number): Array<{ x: number; y: number }> {
  const out: Array<{ x: number; y: number }> = []
  for (let i = 0; i < count; i++) {
    const angle = (-90 + (360 / Math.max(count, 1)) * i) * (Math.PI / 180)
    const x = 50 + 36 * Math.cos(angle)
    const y = 44 + 35 * Math.sin(angle)
    out.push({
      x: Math.min(86, Math.max(14, x)),
      y: Math.min(83, Math.max(17, y)),
    })
  }
  return out
}

/* ------------------------------------------------------------------ */
/* Cast scopes                                                         */
/* ------------------------------------------------------------------ */

export type CastTarget =
  | { scope: 'task'; taskId: string; title: string; cairn: AtelierCairn }
  | { scope: 'project'; projectId: string; title: string; cairn: AtelierCairn }
  | { scope: 'initiative'; initiativeId: string; title: string; cairn: AtelierCairn }
  | { scope: 'loose'; taskId: string; title: string }

export function castStone(cairn: AtelierCairn, stone: AtelierStone): CastTarget {
  return { scope: 'task', taskId: stone.taskId, title: stone.title, cairn }
}

export function castProject(cairn: AtelierCairn): CastTarget {
  return { scope: 'project', projectId: cairn.projectId, title: cairn.projectTitle, cairn }
}

export function castInitiative(cairn: AtelierCairn): CastTarget | null {
  if (!cairn.initiativeId) return null
  return {
    scope: 'initiative',
    initiativeId: cairn.initiativeId,
    title: cairn.initiativeTitle ?? cairn.projectTitle,
    cairn,
  }
}

export function castLooseStone(stone: AtelierLooseStone): CastTarget {
  return { scope: 'loose', taskId: stone.taskId, title: stone.title }
}

/** The conversation a cast loads — keyed per subject and scope, so
 *  each subject's talk with Aria is its own continuing thread. */
export function conversationIdFor(target: CastTarget | null): string {
  if (!target) return 'aria-atelier:garden'
  switch (target.scope) {
    case 'task':
      return `aria-atelier:task:${target.taskId}`
    case 'loose':
      return `aria-atelier:task:${target.taskId}`
    case 'project':
      return `aria-atelier:project:${target.projectId}`
    case 'initiative':
      return `aria-atelier:initiative:${target.initiativeId}`
  }
}

/** The live context the cast carries into Aria's conversation — the
 *  same closed LiveContext seam the Campaign Board uses. */
export function chatContextFor(target: CastTarget | null): Record<string, unknown> {
  if (!target) return { sheet_type: 'aria_atelier' }
  switch (target.scope) {
    case 'task':
    case 'loose':
      return { sheet_type: 'aria_atelier', entity_type: 'task', entity_id: target.taskId }
    case 'project':
      return { sheet_type: 'aria_atelier', entity_type: 'project', entity_id: target.projectId }
    case 'initiative':
      return {
        sheet_type: 'aria_atelier',
        entity_type: 'initiative',
        entity_id: target.initiativeId,
      }
  }
}

/** The project whose recorded conversation history scopes a cast's
 *  talk depth (a task speaks within its project; an initiative takes
 *  its broadest project's history). */
export function depthProjectId(target: CastTarget, garden: AtelierGarden): string | null {
  switch (target.scope) {
    case 'task':
    case 'project':
      return target.cairn.projectId
    case 'loose':
      return null
    case 'initiative': {
      let best: string | null = null
      let bestCount = -1
      for (const c of garden.cairns) {
        if (c.initiativeId !== target.initiativeId) continue
        if (c.stones.length > bestCount) {
          bestCount = c.stones.length
          best = c.projectId
        }
      }
      return best
    }
  }
}

/* ------------------------------------------------------------------ */
/* Talk depth (complexity)                                             */
/* ------------------------------------------------------------------ */

/**
 * Talk depth for one seat about the selected subject, 0–1.
 *
 * The inputs are real conversation counts, from the two seams that
 * expose them: `turns` — that seat's messages in the subject's own
 * Atelier conversation (GET /conversation, the read CouncilChat
 * hydrates from); `keystoneCount` — the seat's completed first-meeting
 * arcs within the subject's project (keystoneConversationCountsByProject,
 * the count conversation colour is built on). The mapping is a
 * presentation constant, declared here: a completed meeting arc
 * counts as four turns of talk; six turns saturate. Ordinary seat
 * conversations outside the keystones and this surface carry no
 * subject link the frontend can read (conversationColour.ts documents
 * the same gap) — they count as zero here, never as an invented value.
 */
export function talkDepth(turns: number, keystoneCount: number): number {
  return Math.min(1, (Math.max(0, turns) + 4 * Math.max(0, keystoneCount)) / 6)
}

/** Per-voice depths for a subject, from per-archetype turn counts and
 *  the subject project's keystone counts (keyed by archetype id). */
export function depthsForSubject(
  turnCountsByArchetype: Record<string, number>,
  keystoneCountsByArchetype: Partial<Record<string, number>> | undefined,
): Record<Voice, number> {
  const out = {} as Record<Voice, number>
  for (const v of VOICES) out[v] = 0
  const archetypeByVoice = Object.entries(VOICE_BY_ARCHETYPE)
  for (const [archetype, voice] of archetypeByVoice) {
    out[voice] = talkDepth(
      turnCountsByArchetype[archetype] ?? 0,
      keystoneCountsByArchetype?.[archetype] ?? 0,
    )
  }
  return out
}

/** Complexity rung 1–5 for a depth (the prototype's rungOf). */
export function rungOf(depth: number): number {
  return Math.max(1, Math.min(5, Math.ceil(depth * 5)))
}

/* ------------------------------------------------------------------ */
/* The layer stack's channels                                          */
/* ------------------------------------------------------------------ */

/** Resting order, back → front. */
export const STACK_DEFAULT: Voice[] = ['rumi', 'valen', 'maeve', 'lucian', 'aria', 'jynx', 'severine']

/** Each voice's baked fill level inside the standing band, as rendered
 *  in the accepted pure composite (Aria's is her white lighten layer). */
export const FILL_BAKED: Record<Voice, number> = {
  rumi: 0.8,
  valen: 0.5,
  maeve: 0.3,
  lucian: 0.2,
  aria: 0.5,
  jynx: 0.2,
  severine: 0.1,
}

/** Effective fill alpha a silent seat recedes toward. */
export const FILL_FLOOR = 0.1

/** Base-e approach constant for fill travel (seconds). */
export const FILL_TAU = 0.38

/** Multiplier that puts a voice's effective fill alpha at the floor:
 *  baked × floorMult = 0.10 at full ceiling. */
export function floorMult(v: Voice): number {
  return Math.min(1, FILL_FLOOR / FILL_BAKED[v])
}

/** The Discussion slider sets the band's ceiling: at 80 the responding
 *  seat's fill is at its full baked intensity. */
export function ceilingScale(slider: number): number {
  return slider / 80
}

/** Fill target (the multiplier written to the fill image's opacity)
 *  for one voice given the current selection and ceiling. */
export function fillTarget(v: Voice, selected: Voice | 'all', slider: number): number {
  const base = selected === 'all' || selected === v ? 1 : floorMult(v)
  return base * ceilingScale(slider)
}

/** Z-order by interaction recency: the interacted voice comes to the
 *  front; the rest stay layered behind in their relative order. */
export function bringToFront(order: Voice[], v: Voice): Voice[] {
  const i = order.indexOf(v)
  if (i < 0) return order
  const next = order.slice()
  next.splice(i, 1)
  next.push(v)
  return next
}

/** One base-e step of the fill approach: closes 1 − e^(−Δt/τ) of the
 *  remaining distance. */
export function fillStep(current: number, target: number, dtSeconds: number): number {
  const k = 1 - Math.exp(-dtSeconds / FILL_TAU)
  const next = current + (target - current) * k
  return Math.abs(target - next) <= 0.002 ? target : next
}

/** Replay rates (presentation slowing, founder-ruled): 0.75× for all
 *  voices, Jynx 0.6×. */
export const REPLAY_RATES: Record<Voice, number> = {
  rumi: 0.75,
  valen: 0.75,
  maeve: 0.75,
  lucian: 0.75,
  aria: 0.75,
  severine: 0.75,
  jynx: 0.6,
}

/** Base replay duration at rate 1 (ms) — the reveal travels to the
 *  depth fraction, holds a beat, then completes. */
export const REPLAY_BASE_MS = 1500
export const REPLAY_HOLD_MS = 650
