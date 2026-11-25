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
 * lays out the same way. (Kept for the fan's anchor math; the ring
 * itself is laid out by gardenLayout, which guarantees the shown
 * items' labels never overlap.)
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
/* Parents + loose — the garden's default face (founder, 2026-11-24)   */
/* ------------------------------------------------------------------ */

/** An initiative standing in the ring as one cairn: the union of
 *  its projects' piles. Its project cairns appear only when the
 *  initiative is opened (the fan), per the standing display rule. */
export interface AtelierInitiativePile {
  initiativeId: string
  title: string
  /** Stable pile id the tower layout keys on. */
  pileId: string
  /** Union of the initiative's cairns' members (member ids are
   *  unique across projects: branch-<project>, flower-<task>).
   *  Only the first cairn's branch keeps the parent flag — a pile
   *  has one base stone; the other projects' branches stand in
   *  the pile as ordinary stones. */
  members: CairnMemberInput[]
  /** Total stones (tasks) across the initiative's projects. */
  stoneCount: number
  /** The initiative's project cairns, in garden order. */
  cairns: AtelierCairn[]
}

export function ringInitiatives(garden: AtelierGarden): AtelierInitiativePile[] {
  const byId = new Map<string, AtelierCairn[]>()
  for (const c of garden.cairns) {
    if (!c.initiativeId) continue
    const arr = byId.get(c.initiativeId) ?? []
    arr.push(c)
    byId.set(c.initiativeId, arr)
  }
  const piles: AtelierInitiativePile[] = []
  for (const [initiativeId, cairns] of byId) {
    const members: CairnMemberInput[] = []
    let keptParent = false
    for (const c of cairns) {
      for (const m of c.members) {
        if (m.parent && keptParent) {
          members.push({ ...m, parent: false })
        } else {
          if (m.parent) keptParent = true
          members.push(m)
        }
      }
    }
    piles.push({
      initiativeId,
      title: cairns[0].initiativeTitle ?? cairns[0].projectTitle,
      pileId: `atelier-initiative-${initiativeId}`,
      members,
      stoneCount: cairns.reduce((n, c) => n + c.stones.length, 0),
      cairns,
    })
  }
  piles.sort((a, b) => a.title.localeCompare(b.title))
  return piles
}

/** The garden's loose cairns: projects under no initiative. */
export function looseCairns(garden: AtelierGarden): AtelierCairn[] {
  return garden.cairns.filter((c) => !c.initiativeId)
}

/* ------------------------------------------------------------------ */
/* The ring layout — shown labels NEVER overlap                        */
/* ------------------------------------------------------------------ */

/**
 * The garden field's reference size: the layout is computed in
 * pixels on a 360×396 field (the garden's 10/11 aspect at the
 * narrowest pane the surface is designed for — a phone's stacked
 * world pane). On any wider field the same percentage positions
 * spread further apart in pixels while the labels keep their
 * pixel size, so a layout that is overlap-free here stays
 * overlap-free there.
 */
export const GARDEN_REF_W = 360
export const GARDEN_REF_H = 396
/** The well's centre and radius on the reference field (the well
 *  is 47% of the field's width, centred at 50%, 44%). */
export const GARDEN_WELL = { cx: GARDEN_REF_W / 2, cy: GARDEN_REF_H * 0.44, r: (GARDEN_REF_W * 0.47) / 2 }
/** Clear space kept between neighbouring footprints. */
export const GARDEN_GAP = 8

export interface GardenFootprint {
  /** Full footprint width in px: the wider of the pile and its
   *  name label. */
  widthPx: number
  /** Full footprint height in px: pile + name label + count line. */
  heightPx: number
}

export interface GardenPlacement {
  /** Anchor position, % of the field (the cairn's translate point:
   *  centred horizontally, 56% down its footprint). */
  x: number
  y: number
  /** Uniform scale applied to every item in this layout (the
   *  cairn element's transform): 1 for gardens that fit at full
   *  size, smaller when the shown set is crowded — the whole set
   *  shrinks together rather than collapsing into overlap. */
  scale: number
  /** The footprint box on the reference field, px — at the
   *  layout's scale, i.e. the box as actually rendered. */
  box: { left: number; top: number; width: number; height: number }
}

/** Estimated width of a cairn's name pill: 0.86rem text in a pill
 *  capped at 150px (atelier.css .atelier-cairn-name). */
export function labelWidthPx(title: string): number {
  return Math.min(150, 20 + (title || '').length * 7.2)
}

/** A ring item's footprint from its rendered parts: the pile's
 *  pixel size, its title (the label), and whether a count line
 *  stands under the label. */
export function gardenFootprint(args: {
  title: string
  pileWidthPx: number
  pileHeightPx: number
  showCount: boolean
}): GardenFootprint {
  const labelW = labelWidthPx(args.title)
  const lines = Math.max(1, Math.ceil(labelW / 132))
  const labelH = lines * 15.2 + 7
  return {
    widthPx: Math.max(args.pileWidthPx, labelW),
    heightPx: args.pileHeightPx + 5 + labelH + (args.showCount ? 17 : 0),
  }
}

interface PlacedBox {
  cx: number
  cy: number
  w: number
  h: number
}

function boxOf(p: PlacedBox): { left: number; top: number; width: number; height: number } {
  // The cairn element anchors at translate(-50%, -56%).
  return { left: p.cx - p.w / 2, top: p.cy - p.h * 0.56, width: p.w, height: p.h }
}

function overlaps(a: PlacedBox, b: PlacedBox, gap: number): { ox: number; oy: number } | null {
  const ba = boxOf(a)
  const bb = boxOf(b)
  const ox = Math.min(ba.left + ba.width + gap, bb.left + bb.width + gap) - Math.max(ba.left, bb.left)
  const oy = Math.min(ba.top + ba.height + gap, bb.top + bb.height + gap) - Math.max(ba.top, bb.top)
  return ox > 0 && oy > 0 ? { ox, oy } : null
}

function clampToField(p: PlacedBox): boolean {
  const b = boxOf(p)
  const bleed = 6 // the garden already lets piles kiss the edge (overflow hidden)
  let dx = 0
  let dy = 0
  if (b.left < -bleed) dx = -bleed - b.left
  if (b.left + b.width > GARDEN_REF_W + bleed) dx = GARDEN_REF_W + bleed - (b.left + b.width)
  if (b.top < -bleed) dy = -bleed - b.top
  if (b.top + b.height > GARDEN_REF_H + bleed) dy = GARDEN_REF_H + bleed - (b.top + b.height)
  p.cx += dx
  p.cy += dy
  return dx !== 0 || dy !== 0
}

/** Note on the well: cairns ring the well by construction (the
 *  ring start), and a pile may kiss the well's stone rim — the
 *  cairns stand in front of it, as in the founder's reference
 *  garden. The layout's hard guarantee is the one the founder
 *  named: the shown cairns' LABELS never overlap each other. */

/** Deterministic de-overlap: push overlapping footprints apart
 *  along their smaller overlap axis, keep every box out of the
 *  well and inside the field, until nothing overlaps or the
 *  iteration budget runs out. Returns true when overlap-free. */
/** Total pairwise overlap (area, gap-inflated) one box has with
 *  the rest — the penalty a placement pays. */
function penaltyOf(placed: PlacedBox[], idx: number, gap: number): number {
  let total = 0
  for (let j = 0; j < placed.length; j++) {
    if (j === idx) continue
    const o = overlaps(placed[idx], placed[j], gap)
    if (o) total += o.ox * o.oy
  }
  return total
}

/** Escape a local minimum: move the worst-overlapping box to
 *  the field position (coarse grid) with the lowest penalty. */
function shake(placed: PlacedBox[], gap: number): boolean {
  let worst = -1
  let worstPenalty = 0
  for (let i = 0; i < placed.length; i++) {
    const p = penaltyOf(placed, i, gap)
    if (p > worstPenalty) {
      worstPenalty = p
      worst = i
    }
  }
  if (worst < 0) return false
  const box = placed[worst]
  const home = { cx: box.cx, cy: box.cy }
  let best = { cx: box.cx, cy: box.cy }
  let bestPenalty = worstPenalty
  for (let gx = box.w / 2 - 6; gx <= GARDEN_REF_W - box.w / 2 + 6; gx += 14) {
    for (let gy = box.h * 0.56 - 6; gy <= GARDEN_REF_H - box.h * 0.44 + 6; gy += 14) {
      box.cx = gx
      box.cy = gy
      const p = penaltyOf(placed, worst, gap)
      if (p < bestPenalty) {
        bestPenalty = p
        best = { cx: gx, cy: gy }
      }
    }
  }
  box.cx = best.cx
  box.cy = best.cy
  return best.cx !== home.cx || best.cy !== home.cy
}

function relax(placed: PlacedBox[], gap: number): boolean {
  const settled = () =>
    placed.every((p, i) => placed.every((q, j) => i === j || !overlaps(p, q, gap)))
  for (let round = 0; round < 8; round++) {
    for (let iter = 0; iter < 400; iter++) {
      let moved = false
      for (let i = 0; i < placed.length; i++) {
        for (let j = i + 1; j < placed.length; j++) {
          const o = overlaps(placed[i], placed[j], gap)
          if (!o) continue
          moved = true
          const a = placed[i]
          const b = placed[j]
          if (o.ox < o.oy) {
            const dir = b.cx >= a.cx ? 1 : -1
            a.cx -= (dir * o.ox) / 2
            b.cx += (dir * o.ox) / 2
          } else {
            const dir = b.cy >= a.cy ? 1 : -1
            a.cy -= (dir * o.oy) / 2
            b.cy += (dir * o.oy) / 2
          }
        }
      }
      for (const p of placed) {
        if (clampToField(p)) moved = true
      }
      if (!moved) break
    }
    if (settled()) return true
    if (!shake(placed, gap)) break
  }
  return settled()
}

interface RingConfig {
  twoRings: boolean
  /** How items are dealt to the two rings: by balanced arc load,
   *  in consecutive pairs, or strictly alternating. */
  deal: 'load' | 'pairs' | 'alternate'
  inner: { rx: number; ry: number }
  /** Inner ring's start offset, in slots of its first item. */
  innerOffsetSlots: number
}

/**
 * Ring start by arc-length allocation: each item claims arc
 * equal to its footprint width plus the gap, and stands at its
 * claim's midpoint — neighbours start separated by construction,
 * and the relaxation only has to polish. The inner ring starts
 * offset, so its items sit in the outer ring's gaps rather than
 * directly behind its piles.
 */
function ringStart(items: GardenFootprint[], cfg: RingConfig): PlacedBox[] {
  const rings: number[][] = cfg.twoRings ? [[], []] : [[...items.keys()]]
  if (cfg.twoRings) {
    if (cfg.deal === 'load') {
      const loads = [0, 0]
      items.forEach((f, i) => {
        const r = loads[0] <= loads[1] ? 0 : 1
        rings[r].push(i)
        loads[r] += f.widthPx + GARDEN_GAP
      })
    } else if (cfg.deal === 'pairs') {
      items.forEach((_, i) => rings[Math.floor(i / 2) % 2].push(i))
    } else {
      items.forEach((_, i) => rings[i % 2].push(i))
    }
  }
  const radii: Array<{ rx: number; ry: number }> = [{ rx: 133, ry: 140 }, cfg.inner]
  const out: PlacedBox[] = new Array(items.length)
  rings.forEach((idxs, ring) => {
    const { rx, ry } = radii[ring]
    const rEff = Math.sqrt((rx * rx + ry * ry) / 2)
    const total = idxs.reduce((n, i) => n + items[i].widthPx + GARDEN_GAP, 0)
    // A ring with room to spare spreads its items around the
    // whole ellipse; a full ring packs from the top.
    const spread = Math.min(total, 2 * Math.PI * rEff)
    let cursor = -spread / 2
    if (ring === 1 && idxs.length) {
      cursor += cfg.innerOffsetSlots * (items[idxs[0]].widthPx + GARDEN_GAP)
    }
    for (const i of idxs) {
      const demand = items[i].widthPx + GARDEN_GAP
      const theta = -Math.PI / 2 + (cursor + demand / 2) / rEff
      out[i] = {
        cx: GARDEN_WELL.cx + rx * Math.cos(theta),
        cy: GARDEN_WELL.cy + ry * Math.sin(theta),
        w: items[i].widthPx,
        h: items[i].heightPx,
      }
      cursor += demand
    }
  })
  return out
}

/** Anchor start: items dealt to the field's lobes (corners and
 *  edge midpoints, in reading order) — a strong start for the
 *  small shown sets the rule produces, where ring starts can
 *  trap the relaxation between the well and the rim. */
function anchorStart(items: GardenFootprint[]): PlacedBox[] {
  const anchors: Array<{ fx: number; fy: number }> = [
    { fx: 0.23, fy: 0.15 },
    { fx: 0.77, fy: 0.15 },
    { fx: 0.23, fy: 0.85 },
    { fx: 0.77, fy: 0.85 },
    { fx: 0.5, fy: 0.09 },
    { fx: 0.5, fy: 0.91 },
    { fx: 0.09, fy: 0.47 },
    { fx: 0.91, fy: 0.47 },
  ]
  return items.map((f, i) => {
    const a = anchors[i % anchors.length]
    const extra = Math.floor(i / anchors.length)
    return {
      cx: a.fx * GARDEN_REF_W + extra * 14,
      cy: a.fy * GARDEN_REF_H + extra * 14,
      w: f.widthPx,
      h: f.heightPx,
    }
  })
}

/**
 * Lay out the ring's shown items so their footprints — pile, name
 * label, count line — NEVER overlap each other, and stay in the
 * field. Several deterministic starts (ring allocations, field
 * anchors) are relaxed in turn until the invariant holds. A
 * garden that does not fit at full size is retried at a smaller
 * uniform scale (the whole shown set shrinks together — a cairn
 * is never dropped and labels never collide); the scale ladder
 * bottoms out at 0.55, past which the tightest relaxed packing
 * is returned. Pure and deterministic.
 */
export function gardenLayout(items: GardenFootprint[]): GardenPlacement[] {
  if (items.length === 0) return []
  const startMakers: Array<(scaled: GardenFootprint[]) => PlacedBox[]> = [
    (scaled) => ringStart(scaled, { twoRings: false, deal: 'load', inner: { rx: 99, ry: 103 }, innerOffsetSlots: 0.5 }),
    (scaled) => anchorStart(scaled),
    (scaled) => ringStart(scaled, { twoRings: true, deal: 'load', inner: { rx: 99, ry: 103 }, innerOffsetSlots: 0.5 }),
    (scaled) => ringStart(scaled, { twoRings: true, deal: 'pairs', inner: { rx: 99, ry: 103 }, innerOffsetSlots: 0.5 }),
    (scaled) => ringStart(scaled, { twoRings: true, deal: 'alternate', inner: { rx: 88, ry: 92 }, innerOffsetSlots: 1 }),
  ]
  const finish = (placed: PlacedBox[], scale: number): GardenPlacement[] =>
    placed.map((p) => {
      const b = boxOf(p)
      return { x: (p.cx / GARDEN_REF_W) * 100, y: (p.cy / GARDEN_REF_H) * 100, scale, box: b }
    })
  let last: { placed: PlacedBox[]; scale: number } | null = null
  for (const scale of [1, 0.85, 0.72, 0.6, 0.55]) {
    const scaled = items.map((f) => ({
      widthPx: f.widthPx * scale,
      heightPx: f.heightPx * scale,
    }))
    for (const make of startMakers) {
      const placed = make(scaled)
      if (relax(placed, GARDEN_GAP)) return finish(placed, scale)
      last = { placed, scale }
    }
  }
  return finish(last!.placed, last!.scale)
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

/**
 * How large the seven-voice formation stands in the cymatic bowl
 * (founder, 2026-11-24: "Arias fractals should take up more of the
 * Cymatic bowl"). The stack's height as a multiple of the bowl's
 * inner diameter: at 1 the formation's box exactly spanned the
 * bowl and the ink — which lives inside its PNGs' margins — read
 * small in a wide ring of empty water. At 1.3 the box overflows
 * the rim evenly on all sides (the bowl clips it), the ink fills
 * substantially more of the diameter, and water still rims the
 * formation. Scale only: z-order, the fill band, and ink opacity
 * are untouched.
 */
export const FORMATION_SCALE = 1.3

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
