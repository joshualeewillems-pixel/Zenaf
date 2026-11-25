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
 * THE STACK channels are the founder's rulings: z-order by
 * interaction recency; fill alpha graded per voice from recorded
 * data — the voice's talk depth about the selected subject and who
 * spoke last — on a base-e approach (τ = 0.38s, driven in the view)
 * inside the ruled 10%–80% band, which has no ceiling control; ink
 * never touched by opacity; complexity = talk depth per seat about
 * the selected subject, presented as emergence replay depth — the
 * formation genuinely drawn to that fraction of its growth (the
 * stage ladders in ./stageImages, generated from the canonical
 * geometry by ./stagegen). There are no manual imagery controls:
 * nothing about the imagery is set by pressing buttons (founder,
 * 2026-11-25).
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

/** The well is water (founder, 2026-11-25: "let's not populate
 *  artifacts on top of the well"). NOTHING the layout places may
 *  intersect the well disc: no cairn, no stone, no label — the
 *  footprint box IS the pile plus its name label and count line,
 *  so box-vs-disc disjointness covers all three, and an item whose
 *  footprint merely touches the rim's edge from outside is fine
 *  while one whose footprint crosses the disc is a violation.
 *  (Before this fix the layout contained no well check at all —
 *  the relaxation's penalty counted only item-vs-item overlap, so
 *  the shake step could teleport the worst-overlapping cairn to
 *  the field's emptiest spot: the middle of the well.) The layout's
 *  other hard guarantee stands alongside: the shown cairns' LABELS
 *  never overlap each other. */

/** Does this rendered box (px, reference field) intersect the
 *  well disc? Rect–circle test: the box's closest point to the
 *  disc centre must lie at or beyond the radius. */
export function boxIntersectsWell(box: { left: number; top: number; width: number; height: number }): boolean {
  const nx = Math.max(box.left, Math.min(GARDEN_WELL.cx, box.left + box.width))
  const ny = Math.max(box.top, Math.min(GARDEN_WELL.cy, box.top + box.height))
  const dx = nx - GARDEN_WELL.cx
  const dy = ny - GARDEN_WELL.cy
  return dx * dx + dy * dy < GARDEN_WELL.r * GARDEN_WELL.r
}

/** Push a placed box radially out of the well disc until its
 *  footprint is disjoint (then re-clamp to the field). Returns
 *  true when the box moved. Bounded: a box that cannot clear the
 *  disc inside the field is left where the steps end — the layout
 *  tests pin the realistic gardens. */
function resolveWell(p: PlacedBox): boolean {
  if (!boxIntersectsWell(boxOf(p))) return false
  let dx = p.cx - GARDEN_WELL.cx
  let dy = p.cy - GARDEN_WELL.cy
  const len = Math.hypot(dx, dy)
  if (len < 0.001) {
    dx = 0
    dy = -1
  } else {
    dx /= len
    dy /= len
  }
  for (let step = 0; step < 90; step++) {
    p.cx += dx * 4
    p.cy += dy * 4
    clampToField(p)
    if (!boxIntersectsWell(boxOf(p))) return true
  }
  return true
}

/** Deterministic de-overlap: push overlapping footprints apart
 *  along their smaller overlap axis, keep every box out of the
 *  well and inside the field, until nothing overlaps or the
 *  iteration budget runs out. Returns true when overlap-free. */
/** Total pairwise overlap (area, gap-inflated) one box has with
 *  the rest — the penalty a placement pays. Standing on the well
 *  dominates any item overlap, so the shake step never chooses
 *  the disc as an escape. */
function penaltyOf(placed: PlacedBox[], idx: number, gap: number): number {
  let total = 0
  if (boxIntersectsWell(boxOf(placed[idx]))) total += 1_000_000
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
    placed.every((p) => !boxIntersectsWell(boxOf(p))) &&
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
        if (resolveWell(p)) moved = true
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
 * label, count line — NEVER overlap each other, NEVER intersect
 * the well disc, and stay in the field. Several deterministic
 * starts (ring allocations, field anchors) are relaxed in turn
 * until both invariants hold. A garden that does not fit at full
 * size is retried at a smaller uniform scale (the whole shown set
 * shrinks together — a cairn is never dropped and labels never
 * collide); the scale ladder bottoms out at 0.55, past which the
 * tightest relaxed packing is returned — with the well guarantee
 * still enforced on the way out, since that one is absolute.
 * Pure and deterministic.
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
  // The fallback packing may still touch the well; the water is
  // water, so the disc is cleared even here (a label compromise in
  // a pathological garden outranks nothing — the well does).
  for (const p of last!.placed) {
    resolveWell(p)
    clampToField(p)
  }
  return finish(last!.placed, last!.scale)
}

/* ------------------------------------------------------------------ */
/* The fan — an opened cairn's stones, never on the water              */
/* ------------------------------------------------------------------ */

/** A fan's estimated box as % of the garden field, measured on the
 *  reference field: fan stones are 76px wide with the fan's gaps
 *  and padding (atelier.css .atelier-fan / .atelier-fan-stone),
 *  wrapping at 94% of the field's width. On any wider field the
 *  fan's fixed pixel size is a smaller share, so the reference
 *  estimate is the conservative one. */
export interface FanBox {
  widthPct: number
  heightPct: number
}

export function fanBoxFor(stoneCount: number): FanBox {
  const n = Math.max(1, stoneCount)
  const stoneW = 76
  const gap = 5.6
  const padX = 12.8
  const padY = 11.2
  const maxW = GARDEN_REF_W * 0.94
  const perRow = Math.max(1, Math.floor((maxW - padX + gap) / (stoneW + gap)))
  const cols = Math.min(n, perRow)
  const rows = Math.ceil(n / perRow)
  const widthPx = Math.min(maxW, cols * stoneW + (cols - 1) * gap + padX)
  const heightPx = rows * 54 + (rows - 1) * gap + padY
  return {
    widthPct: (widthPx / GARDEN_REF_W) * 100,
    heightPct: (heightPx / GARDEN_REF_H) * 100,
  }
}

/** The well disc in the garden's % space, as an ellipse: centre
 *  (50, 44); radius 23.5% of the width, and 23.5 × 10/11 % of the
 *  height (the garden's aspect is 10/11). */
const WELL_PCT = { cx: 50, cy: 44, rx: 23.5, ry: 23.5 * (10 / 11) }

/** Distance from the disc centre to the fan box's closest point,
 *  in the y-scaled space where the ellipse is a circle (a rect
 *  stays a rect under the axis scaling, so this stays exact).
 *  Below WELL_PCT.rx the box intersects the disc. */
function fanWellClosest(left: number, top: number, box: FanBox): number {
  const s = WELL_PCT.rx / WELL_PCT.ry
  const nx = Math.max(left, Math.min(WELL_PCT.cx, left + box.widthPct))
  const ny = Math.max(top * s, Math.min(WELL_PCT.cy * s, (top + box.heightPct) * s))
  return Math.hypot(nx - WELL_PCT.cx, ny - WELL_PCT.cy * s)
}

function fanBoxIntersectsWell(left: number, top: number, box: FanBox): boolean {
  return fanWellClosest(left, top, box) < WELL_PCT.rx
}

/**
 * Where a fan sits: centred near its anchor, below it — or above
 * it when the anchor stands low — the garden's standing placement.
 * If that box would rest on the well disc, the flipped side is
 * tried, then the fan is walked radially outward from the disc's
 * centre in every direction (the anchor's own ray first) until
 * its whole box is clear of the water. A fan too large to clear
 * the disc anywhere inside the field at the reference width (a
 * dozen-plus stones on a phone-width pane) takes the placement
 * whose box penetrates the disc least — bottom-hugging, in
 * practice; on any wider field the same fan is a smaller share
 * of the field and clears outright. A fan is a resting artifact
 * while it stands open; the water is water.
 */
export function fanPositionClear(
  anchor: { x: number; y: number },
  box: FanBox,
): { left: number; top: number } {
  const place = (cx: number, top: number) => ({
    left: Math.max(box.widthPct / 2, Math.min(100 - box.widthPct / 2, cx)),
    top: Math.max(0, Math.min(100 - box.heightPct, top)),
  })
  const penetration = (p: { left: number; top: number }) =>
    Math.max(0, WELL_PCT.rx - fanWellClosest(p.left - box.widthPct / 2, p.top, box))
  const clear = (p: { left: number; top: number }) => penetration(p) <= 0
  const legacy = place(
    Math.max(38, Math.min(62, anchor.x)),
    anchor.y > 70 ? anchor.y - 7 - box.heightPct : anchor.y + 7,
  )
  if (clear(legacy)) return legacy
  const flipped = place(
    legacy.left,
    anchor.y > 70 ? anchor.y + 7 : anchor.y - 7 - box.heightPct,
  )
  if (clear(flipped)) return flipped
  let best = penetration(flipped) < penetration(legacy) ? flipped : legacy
  let bestPen = penetration(best)
  // Radial walks in the scaled space (where the disc is a
  // circle): the anchor's ray first, then the cardinals and
  // diagonals. Each walk steps the fan's centre outward and
  // tests the field-clamped placement.
  const s = WELL_PCT.rx / WELL_PCT.ry
  let ax = anchor.x - WELL_PCT.cx
  let ay = (anchor.y - WELL_PCT.cy) * s
  const alen = Math.hypot(ax, ay)
  if (alen < 0.001) {
    ax = 0
    ay = -1
  } else {
    ax /= alen
    ay /= alen
  }
  const dirs: Array<[number, number]> = [
    [ax, ay],
    [0, -1],
    [0, 1],
    [-1, 0],
    [1, 0],
    [-0.7071, -0.7071],
    [0.7071, -0.7071],
    [-0.7071, 0.7071],
    [0.7071, 0.7071],
  ]
  for (const [dx, dy] of dirs) {
    for (let d = 0; d <= 130; d += 2) {
      const cx = WELL_PCT.cx + dx * d
      const cy = WELL_PCT.cy + (dy * d) / s
      const p = place(cx, cy - box.heightPct / 2)
      if (clear(p)) return p
      const pen = penetration(p)
      if (pen < bestPen) {
        bestPen = pen
        best = p
      }
    }
  }
  return best
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

/**
 * GRADED FILL — from recorded data only (founder, 2026-11-25:
 * "the imagery is supposed to represent system data"). A voice's
 * fill presence is its EFFECTIVE alpha inside the ruled band —
 * never below the 10% floor, never above its baked level:
 *
 *   - the voice who spoke last about this subject (the recorded
 *     lastArchetype of the subject conversation) stands at FULL
 *     presence: its baked level;
 *   - any other voice with recorded talk about the subject holds
 *     the floor plus the depth-graded share of its remaining
 *     range: floor + (baked − floor) × depth, where depth is its
 *     recorded talk depth (depthsForSubject);
 *   - a voice with no recorded talk about the subject sits at
 *     the floor.
 *
 * Deterministic in (depths, lastVoice) — the two recorded inputs
 * the view already fetches. No stance or activity inference, no
 * other data. There is no ceiling control: the band is the band.
 */
export function fillPresence(
  v: Voice,
  depths: Record<Voice, number>,
  lastVoice: Voice | null,
): number {
  const baked = FILL_BAKED[v]
  if (lastVoice === v) return baked
  const depth = Math.max(0, Math.min(1, depths[v] ?? 0))
  if (depth <= 0) return FILL_FLOOR
  return FILL_FLOOR + (baked - FILL_FLOOR) * depth
}

/** The multiplier written to the fill image's opacity: the fill
 *  PNG bakes the voice's level in, so presence ÷ baked is what
 *  the image wears. Always within (0, 1]. */
export function fillMultiplier(
  v: Voice,
  depths: Record<Voice, number>,
  lastVoice: Voice | null,
): number {
  return fillPresence(v, depths, lastVoice) / FILL_BAKED[v]
}

/* ------------------------------------------------------------------ */
/* The drawing stages                                                  */
/* ------------------------------------------------------------------ */

/** Stages in each voice's formation ladder (stageImages.ts). Stage
 *  j is the canonical geometry genuinely drawn to j/12 of its
 *  growth — every stage a true prefix of the next, the last the
 *  completed formation (see stagegen/generate_stages.py and
 *  stage-manifest.json). Stage 0 is nothing drawn yet. */
export const STAGE_COUNT = 12

/** The stage a voice's replay holds at: its recorded depth
 *  fraction of the ladder, so what stands at the hold is the
 *  formation drawn to exactly that fraction (within one stage). */
export function stageForDepth(depth: number): number {
  return Math.max(0, Math.min(STAGE_COUNT, Math.round(depth * STAGE_COUNT)))
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

/** Base replay duration at rate 1 (ms) — the drawing travels to
 *  the depth fraction, holds a beat, then completes. */
export const REPLAY_BASE_MS = 1500
export const REPLAY_HOLD_MS = 650
/** Duration of the completion beat (ms): the drawing runs from
 *  its held depth to the completed formation. */
export const REPLAY_COMPLETE_MS = 400

/* ------------------------------------------------------------------ */
/* Dynamism — buoyancy, and the refraction twin's offset               */
/* ------------------------------------------------------------------ */

/**
 * BUOYANCY (dynamism spec §2.1 — EXPERIMENTAL, founder review
 * 2026-11-25): a voice's ink and fill layers ride that voice's
 * own phase in the water field. The transform is pure arithmetic
 * on the phase: translation follows the phase within a drift
 * amplitude set by the layer's recency rank, and the scale
 * breathes inside [1.000, 1.006] — it never shrinks the formation
 * below its canonical size. No rotation: the formations are
 * centred and symmetrical by ruling, and rotation would fight
 * the symmetry. The founder's governing gate is perceptual (the
 * on-device still comparison — see stillComparisonIn), not this
 * arithmetic; these bounds are the numerical half of the gate.
 */

/** Drift amplitude (px) for a layer `rankFromFront` steps behind
 *  the front of the stack: 1.5px at the front, halving per layer
 *  back, floored at 0.3px. */
export function buoyancyDrift(rankFromFront: number): number {
  const rank = Math.max(0, Math.floor(rankFromFront))
  return Math.max(0.3, 1.5 * Math.pow(0.5, rank))
}

export interface BuoyancyTransform {
  dx: number
  dy: number
  scale: number
}

/** The layer transform for a voice at field phase `phase`,
 *  `rankFromFront` steps behind the front. Translation values are
 *  rounded to 0.1px, as the spec requires before they are written
 *  to style. */
export function buoyancyTransform(phase: number, rankFromFront: number): BuoyancyTransform {
  const d = buoyancyDrift(rankFromFront)
  const round1 = (x: number) => Math.round(x * 10) / 10
  return {
    dx: round1(Math.sin(phase) * d),
    dy: round1(Math.cos(phase * 0.9) * d * 0.6),
    scale: 1 + 0.003 * (1 + Math.sin(phase * 0.5)),
  }
}

/** The refraction twin's offset (dynamism spec §2.3): the twin
 *  rides beneath its ink, displaced by the water's phase for its
 *  voice — at most 2px across, 1.2px down. Rounded to 0.1px like
 *  every dynamism style write. */
export function twinOffset(phase: number): { dx: number; dy: number } {
  const round1 = (x: number) => Math.round(x * 10) / 10
  return {
    dx: round1(Math.sin(phase) * 2),
    dy: round1(Math.cos(phase) * 1.2),
  }
}

/**
 * The still comparison (dynamism spec §2.1, perceptual gate): a
 * `?still=1` query parameter, read once at mount by the view,
 * stills every dynamism rendering the pass adds — buoyancy
 * transforms stay identity and the twin sits at zero offset — so
 * the same cast can be compared against a completely stationary
 * formation on device. Acceptance tooling only: it is never a
 * visible control, never persisted, and the water's own motion
 * (which predates this pass) is untouched by it.
 */
export function stillComparisonIn(search: string): boolean {
  try {
    return new URLSearchParams(search).get('still') === '1'
  } catch {
    return false
  }
}
