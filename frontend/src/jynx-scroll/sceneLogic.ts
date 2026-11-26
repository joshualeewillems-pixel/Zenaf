/**
 * Jynx's Scroll — Scene 1 derivation logic (founder commission,
 * 2026-11-25: "implement what we built as scene one").
 *
 * Scene 1 is the frozen room at ~/workspace/sprites/scroll-rebuild/
 * scene-1/ (fixture.json, composite sha256 def8bac6c1d…): the room
 * image as ground, the shelf wall tiled from the CANONICAL Penrose
 * deflation, the founder's sheet hanging at the fixture's rect.
 * Everything here is a port or a projection of recorded things —
 * nothing is invented:
 *
 *  - THE FABRIC is the canonical deflation of
 *    rendering-test-assets/atelier-demo/stage1c_jynx.py (Rosetta /
 *    preshing wheel + deflation, CUT = 1/φ), composed exactly as
 *    the frozen builder build_composite_v4.py composes it: 6
 *    deflations (890 thin + 1440 thick halves — the source table),
 *    halves merged over their shared diagonal into rhombs, scaled
 *    to side 59 in the 1536×1024 frame around wheel centre
 *    (752, 557), kept inside the wall field [105,262]–[1400,852]
 *    (±40 at the rim) and out of the sheet's exclusion rect
 *    [518,366]–[950,862] — 230 rhombs on the wall (146 thick,
 *    84 thin). The counts are pinned by sceneLogic.test.ts.
 *    Each rhomb is DRESSED as the frozen builder dresses it: the
 *    fixture's hollow wooden frame asset (frame-thick.png /
 *    frame-thin.png, byte copies in ./assets) laid onto the rhomb
 *    by the builder's own affine placement (frameTransform), over
 *    the builder's soft depth-reveal bands (depthBands). An
 *    earlier build drew stroked vector outlines instead of the
 *    wooden frames — a substitution the founder caught on device
 *    2026-11-26 ("our wood was sooo good"); the material is the
 *    asset, never a redraw.
 *
 *  - CUBBIES: one per top-level item (initiatives + loose items —
 *    shelfTopLevel's face, the bin's scrolls included: Scene 1 has
 *    no bin; every top-level scroll stands in a cell). Assignment
 *    is deterministic: units are ordered by their recorded size
 *    (appearance radius — kind + recorded mass) descending, ties
 *    by title then key; cells are taken from a fixed priority
 *    order — sorted by distance from the sheet, alternating left
 *    and right of the sheet's centre line, larger (thick) cells
 *    first within each distance band. A cell left of the sheet's
 *    centre line holds the left-facing scroll asset; right of it,
 *    the mirrored one (founder placement rule, 2026-11-25).
 *
 *  - CLUSTERS (the commission's named rule): a cubby whose item
 *    has nested projects/tasks holds multiple scrolls — the
 *    parent's at full cell size in front, up to THREE children at
 *    ~55% tucked behind it (projects first, then tasks, in shelf
 *    order). The rest of the nest lives on the table and in the
 *    popup's "…and N more within" line.
 *
 *  - THE POPUP's synopsis is composed from recorded fields only:
 *    kind, status, a project's declared window, counts within,
 *    a task's estimate and due date. No generated prose.
 *
 *  - THE TABLE (long-press): a scroll with children opens the
 *    worktable standing its children end-on, each with its own
 *    cluster; a leaf scroll opens on the sheet directly.
 */
import {
  scrollChildren,
  shelfTopLevel,
  type ShelfBay,
  type ShelfScroll,
} from './scrollLogic'

/* ------------------------------------------------------------------ */
/* The room frame (fixture coordinates, 1536×1024)                     */
/* ------------------------------------------------------------------ */

export const FRAME_W = 1536
export const FRAME_H = 1024
export const SHEET_RECT = { x: 542, y: 366, w: 384, h: 512 }
export const SHEET_CENTRE = { x: SHEET_RECT.x + SHEET_RECT.w / 2, y: SHEET_RECT.y + SHEET_RECT.h / 2 }
export const WALL = { x0: 105, y0: 262, x1: 1400, y1: 852 }
export const EXCLUSION = { x0: 518, y0: 366, x1: 950, y1: 862 }
export const VANISHING_POINT = { x: 768, y: 430 }
export const DEPTH_SCALE = 0.82

/* ------------------------------------------------------------------ */
/* The fabric — the canonical Penrose deflation, ported                */
/* ------------------------------------------------------------------ */

export interface Pt {
  x: number
  y: number
}

interface Half {
  thick: boolean
  a: Pt
  b: Pt
  c: Pt
}

const CUT = 2 / (1 + Math.sqrt(5))

function toward(p: Pt, q: Pt, t: number): Pt {
  return { x: p.x + (q.x - p.x) * t, y: p.y + (q.y - p.y) * t }
}

function wheel(): Half[] {
  const halves: Half[] = []
  for (let i = 0; i < 10; i++) {
    const b = {
      x: Math.cos((Math.PI * (2 * i - 1)) / 10),
      y: Math.sin((Math.PI * (2 * i - 1)) / 10),
    }
    const c = {
      x: Math.cos((Math.PI * (2 * i + 1)) / 10),
      y: Math.sin((Math.PI * (2 * i + 1)) / 10),
    }
    if (i % 2 === 0) halves.push({ thick: false, a: { x: 0, y: 0 }, b: c, c: b })
    else halves.push({ thick: false, a: { x: 0, y: 0 }, b, c })
  }
  return halves
}

function deflate(halves: Half[]): Half[] {
  const out: Half[] = []
  for (const h of halves) {
    if (h.thick) {
      const q = toward(h.b, h.a, CUT)
      const r = toward(h.b, h.c, CUT)
      out.push({ thick: true, a: r, b: h.c, c: h.a })
      out.push({ thick: true, a: q, b: r, c: h.b })
      out.push({ thick: false, a: r, b: q, c: h.a })
    } else {
      const p = toward(h.a, h.b, CUT)
      out.push({ thick: false, a: h.c, b: p, c: h.b })
      out.push({ thick: true, a: p, b: h.c, c: h.a })
    }
  }
  return out
}

function key5(p: Pt): string {
  const r = (v: number) => Math.round(v * 1e5) / 1e5
  return `${r(p.x)},${r(p.y)}`
}

export interface FabricRhomb {
  /** The rhomb's four corners, cyclic, in frame coordinates. */
  corners: [Pt, Pt, Pt, Pt]
  centre: Pt
  thick: boolean
}

export interface PenroseFabric {
  thinHalves: number
  thickHalves: number
  /** Halves paired over their shared diagonal, before the wall
   *  and exclusion filters (the Python builder's raw merge). */
  mergedRhombs: number
  /** The rhombs standing on the room's wall. */
  rhombs: FabricRhomb[]
}

const WHEEL_CENTRE = { x: 752, y: 557 }
const TARGET_SIDE = 59

export function buildPenroseFabric(): PenroseFabric {
  let halves = wheel()
  for (let i = 0; i < 6; i++) halves = deflate(halves)
  const thinHalves = halves.filter((h) => !h.thick).length
  const thickHalves = halves.length - thinHalves

  // Merge halves into rhombs over their shared diagonal (the
  // builder's pairing: same thickness, same diagonal endpoints).
  const pairs = new Map<string, Half[]>()
  for (const h of halves) {
    const diag = [key5(h.b), key5(h.c)].sort()
    const k = `${h.thick ? 'T' : 't'}|${diag[0]}|${diag[1]}`
    const arr = pairs.get(k) ?? []
    arr.push(h)
    pairs.set(k, arr)
  }

  const unitSide = Math.min(
    ...halves.map((h) => Math.hypot(h.a.x - h.b.x, h.a.y - h.b.y)),
  )
  const scale = TARGET_SIDE / unitSide
  const toCanvas = (p: Pt): Pt => ({
    x: WHEEL_CENTRE.x + p.x * scale,
    y: WHEEL_CENTRE.y + p.y * scale,
  })
  const inExcl = (p: Pt) =>
    p.x >= EXCLUSION.x0 && p.x <= EXCLUSION.x1 && p.y >= EXCLUSION.y0 && p.y <= EXCLUSION.y1

  let mergedRhombs = 0
  const rhombs: FabricRhomb[] = []
  for (const hs of pairs.values()) {
    if (hs.length !== 2) continue // rim halves have no partner in the wheel
    mergedRhombs += 1
    const [h0, h1] = hs
    const corners: [Pt, Pt, Pt, Pt] = [
      toCanvas(h0.a),
      toCanvas(h0.b),
      toCanvas(h1.a),
      toCanvas(h0.c),
    ]
    const centre = {
      x: (corners[0].x + corners[1].x + corners[2].x + corners[3].x) / 4,
      y: (corners[0].y + corners[1].y + corners[2].y + corners[3].y) / 4,
    }
    if (
      !(
        centre.x >= WALL.x0 - 40 &&
        centre.x <= WALL.x1 + 40 &&
        centre.y >= WALL.y0 - 40 &&
        centre.y <= WALL.y1 + 40
      )
    ) {
      continue
    }
    if (inExcl(centre)) continue
    if (corners.some(inExcl)) continue
    rhombs.push({ corners, centre, thick: h0.thick })
  }
  return { thinHalves, thickHalves, mergedRhombs, rhombs }
}

/** A cell's inscribed diameter — the largest scroll end that
 *  stands inside the rhomb: side × sin(acute angle). */
export function cellInDiameter(cell: FabricRhomb): number {
  const [c0, c1, , c3] = cell.corners
  const side = Math.hypot(c1.x - c0.x, c1.y - c0.y)
  const v1 = { x: c1.x - c0.x, y: c1.y - c0.y }
  const v2 = { x: c3.x - c0.x, y: c3.y - c0.y }
  const dot = (v1.x * v2.x + v1.y * v2.y) / (side * side)
  const angle = Math.acos(Math.min(1, Math.max(-1, dot)))
  const acute = Math.min(angle, Math.PI - angle)
  return side * Math.sin(acute)
}

/* ------------------------------------------------------------------ */
/* The wooden frames — the frozen fixture's assets, placed as the    */
/* frozen builder (build_composite_v4.py) places them                */
/* ------------------------------------------------------------------ */

/** The frame assets in the app bundle are byte copies of the
 *  frozen fixture's frames (sprites/scroll-rebuild/scene-1/
 *  frame-thick.png, frame-thin.png — the founder's skew-corrected
 *  hollow wooden rhombs). Their geometry here is fixture data,
 *  measured off the assets exactly as the builder measures them:
 *  the alpha extremes (L/T/R/B) in each asset's own pixels, in the
 *  builder's cycle order per kind. */
export const FRAME_IMG = {
  thick: {
    w: 971,
    h: 705,
    cycle: [
      { x: 7, y: 356 },
      { x: 485, y: 6 },
      { x: 964, y: 356 },
      { x: 486, y: 699 },
    ] as Pt[],
  },
  thin: {
    w: 371,
    h: 1141,
    cycle: [
      { x: 185, y: 10 },
      { x: 366, y: 571 },
      { x: 185, y: 1132 },
      { x: 6, y: 572 },
    ] as Pt[],
  },
} as const

function cornerAngle(cs: Pt[], i: number): number {
  const p = cs[(i + 3) % 4]
  const q = cs[(i + 1) % 4]
  const c = cs[i]
  const v1 = { x: p.x - c.x, y: p.y - c.y }
  const v2 = { x: q.x - c.x, y: q.y - c.y }
  const dot = (v1.x * v2.x + v1.y * v2.y) / (Math.hypot(v1.x, v1.y) * Math.hypot(v2.x, v2.y))
  return (Math.acos(Math.min(1, Math.max(-1, dot))) * 180) / Math.PI
}

function signedArea(pts: Pt[]): number {
  let s = 0
  for (let i = 0; i < 4; i++) {
    const a = pts[i]
    const b = pts[(i + 1) % 4]
    s += a.x * b.y - b.x * a.y
  }
  return 0.5 * s
}

/** The affine that lays a frame asset onto a rhomb, in SVG matrix
 *  terms — a direct port of the frozen builder's placement: the
 *  asset's corner cycle is rotated to the rotation whose first
 *  corner's angle best matches the rhomb's, flipped if the signed
 *  areas disagree, and the affine is solved from corners 0, 1, 3.
 *  Pinned against the builder's own output in sceneLogic.test.ts. */
export function frameTransform(cell: FabricRhomb): {
  a: number
  b: number
  c: number
  d: number
  e: number
  f: number
} {
  const cyc = FRAME_IMG[cell.thick ? 'thick' : 'thin'].cycle
  const ia = cyc.map((_, i) => cornerAngle(cyc, i))
  const target = cornerAngle(cell.corners, 0)
  let start = 0
  for (let i = 1; i < 4; i++) {
    if (Math.abs(ia[i] - target) < Math.abs(ia[start] - target)) start = i
  }
  let ip = [0, 1, 2, 3].map((k) => cyc[(start + k) % 4])
  let qp: Pt[] = [...cell.corners]
  if (Math.sign(signedArea(ip)) !== Math.sign(signedArea(qp))) {
    ip = [ip[0], ip[3], ip[2], ip[1]]
    qp = [qp[0], qp[3], qp[2], qp[1]]
  }
  // Solve [[x0,y0,1],[x1,y1,1],[x3,y3,1]] · m = q for both axes.
  const [p0, p1, p3] = [ip[0], ip[1], ip[3]]
  const det =
    p0.x * (p1.y - p3.y) - p0.y * (p1.x - p3.x) + (p1.x * p3.y - p3.x * p1.y)
  const solve = (q0: number, q1: number, q3: number): [number, number, number] => [
    (q0 * (p1.y - p3.y) - q1 * (p0.y - p3.y) + q3 * (p0.y - p1.y)) / det,
    (q0 * (p3.x - p1.x) - q1 * (p3.x - p0.x) + q3 * (p1.x - p0.x)) / det,
    (q0 * (p1.x * p3.y - p3.x * p1.y) - q1 * (p0.x * p3.y - p3.x * p0.y) + q3 * (p0.x * p1.y - p1.x * p0.y)) / det,
  ]
  const mx = solve(qp[0].x, qp[1].x, qp[3].x)
  const my = solve(qp[0].y, qp[1].y, qp[3].y)
  return { a: mx[0], b: my[0], c: mx[1], d: my[1], e: mx[2], f: my[2] }
}

/** The composite's depth reveal for one rhomb: the four bands
 *  between the rhomb and its vanishing-point-pulled back, filled
 *  (110,74,40) at the builder's per-edge strengths — upper edges
 *  64/255, lower 88/255, side edges 40/255. (The builder also
 *  strokes the back outline and blurs the layer; the frames carry
 *  the read without it.) */
export function depthBands(cell: FabricRhomb): { points: Pt[]; opacity: number }[] {
  const back = cell.corners.map((c) => ({
    x: VANISHING_POINT.x + (c.x - VANISHING_POINT.x) * DEPTH_SCALE,
    y: VANISHING_POINT.y + (c.y - VANISHING_POINT.y) * DEPTH_SCALE,
  }))
  return cell.corners.map((c, i) => {
    const j = (i + 1) % 4
    const midY = (c.y + cell.corners[j].y) / 2
    const opacity = midY < cell.centre.y - 4 ? 64 / 255 : midY > cell.centre.y + 4 ? 88 / 255 : 40 / 255
    return { points: [c, cell.corners[j], back[j], back[i]], opacity }
  })
}

/** The priority order cells are handed out in: distance from the
 *  sheet ascending, alternating left/right of the sheet's centre
 *  line, thick cells before thin ones within each distance band
 *  (30 frame units) on each side. Fully deterministic. */
export function cellPriorityOrder(rhombs: FabricRhomb[]): FabricRhomb[] {
  const dist = (c: FabricRhomb) =>
    Math.hypot(c.centre.x - SHEET_CENTRE.x, c.centre.y - SHEET_CENTRE.y)
  const byBand = (a: FabricRhomb, b: FabricRhomb) => {
    const band = Math.floor(dist(a) / 30) - Math.floor(dist(b) / 30)
    if (band !== 0) return band
    if (a.thick !== b.thick) return a.thick ? -1 : 1
    const d = dist(a) - dist(b)
    if (d !== 0) return d
    if (a.centre.y !== b.centre.y) return a.centre.y - b.centre.y
    return a.centre.x - b.centre.x
  }
  const left = rhombs.filter((c) => c.centre.x < SHEET_CENTRE.x).sort(byBand)
  const right = rhombs.filter((c) => c.centre.x >= SHEET_CENTRE.x).sort(byBand)
  const out: FabricRhomb[] = []
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    if (i < left.length) out.push(left[i])
    if (i < right.length) out.push(right[i])
  }
  return out
}

/* ------------------------------------------------------------------ */
/* Cubbies and clusters                                                */
/* ------------------------------------------------------------------ */

export interface CubbyUnit {
  /** The top-level scroll standing at the cubby's front. */
  head: ShelfScroll
  /** Its nested scrolls in shelf order (projects first, then
   *  tasks) — the cubby's cluster stands the first three. */
  cluster: ShelfScroll[]
}

export const CLUSTER_SHOWN = 3
export const CLUSTER_SCALE = 0.55

/** A scroll's cluster children: for an initiative, its projects
 *  then their tasks (shelf order); for a project, its tasks; for
 *  a task, its subtasks; an idea stands alone. */
export function clusterChildren(bays: ShelfBay[], scroll: ShelfScroll): ShelfScroll[] {
  if (scroll.kind === 'initiative') {
    const bay = bays.find((b) => b.initiative?.id === scroll.id)
    if (!bay) return []
    return [
      ...bay.projects.map((p) => p.scroll),
      ...bay.projects.flatMap((p) => p.tasks),
    ]
  }
  if (scroll.kind === 'project') {
    for (const bay of bays) {
      const found = bay.projects.find((p) => p.scroll.id === scroll.id)
      if (found) return found.tasks
    }
    return []
  }
  return scrollChildren(bays, scroll)
}

/** One cubby per top-level item: each initiative, then the loose
 *  face (unanchored projects, top-level loose tasks, ideas) in
 *  shelf order. */
export function cubbyUnits(bays: ShelfBay[]): CubbyUnit[] {
  const { lattice, bin } = shelfTopLevel(bays)
  return [...lattice, ...bin].map((head) => ({
    head,
    cluster: clusterChildren(bays, head),
  }))
}

export interface CubbyAssignment {
  unit: CubbyUnit
  cell: FabricRhomb
  side: 'left' | 'right'
}

/** The closest two cubbies may stand, centre to centre, in frame
 *  units. A cubby's cluster spills around its head scroll; below
 *  this distance neighbouring cubbies collide on the wall. */
export const CUBBY_MIN_SEPARATION = 105

/** Assign cubbies to cells: units by recorded size descending
 *  (ties by title, then key), cells taken in the fixed priority
 *  order, skipping any cell that would crowd an already-placed
 *  cubby (nearer than CUBBY_MIN_SEPARATION) — the priority order
 *  decides who stands closest to the sheet; the spacing keeps
 *  every cubby readable on the wall. If the wall ever runs out
 *  of spaced cells, the remaining units take the nearest cells
 *  left, crowded or not — a scroll is never dropped. The side
 *  follows the cell's place against the sheet's centre line —
 *  it chooses which way the scroll's end faces. */
export function assignCubbies(bays: ShelfBay[], rhombs: FabricRhomb[]): CubbyAssignment[] {
  const units = cubbyUnits(bays).sort((a, b) => {
    const r = b.head.appearance.radius - a.head.appearance.radius
    if (r !== 0) return r
    const t = a.head.title.localeCompare(b.head.title)
    if (t !== 0) return t
    return `${a.head.kind}:${a.head.id}`.localeCompare(`${b.head.kind}:${b.head.id}`)
  })
  // Cells are preferred inside the wall band, inset enough that a
  // standing scroll (sized by its face to the cell) never reaches
  // the floor or spills past the wall's edges; cells outside the
  // band remain as the never-drop fallback, in priority order.
  const inBand = (c: FabricRhomb) =>
    c.centre.x >= 150 && c.centre.x <= 1360 && c.centre.y >= 290 && c.centre.y <= 795
  const priority = cellPriorityOrder(rhombs)
  const order = [...priority.filter(inBand), ...priority.filter((c) => !inBand(c))]
  const taken: FabricRhomb[] = []
  const chosen: FabricRhomb[] = []
  for (let i = 0; i < units.length; i++) {
    const cell =
      order.find(
        (c) =>
          !taken.includes(c) &&
          taken.every(
            (t) => Math.hypot(t.centre.x - c.centre.x, t.centre.y - c.centre.y) >= CUBBY_MIN_SEPARATION,
          ),
      ) ?? order.find((c) => !taken.includes(c))
    if (!cell) break
    taken.push(cell)
    chosen.push(cell)
  }
  return units.slice(0, chosen.length).map((unit, i) => ({
    unit,
    cell: chosen[i],
    side: chosen[i].centre.x < SHEET_CENTRE.x ? ('left' as const) : ('right' as const),
  }))
}

/** A scroll's standing width in its cell. The scroll is sized by
 *  its END FACE (the founder's ruling: the scrolls must read in
 *  their cubbies): the end disc is 0.6 of the end-on asset's width
 *  (END_FACE in the view), and the disc stands at 98% of the
 *  cell's inscribed diameter — the largest disc the frame holds.
 *  Recorded size keeps its role where the brief puts it: it orders
 *  the assignment, so bigger items take bigger cells first. */
export function scrollWidthFor(_scroll: ShelfScroll, cell: FabricRhomb): number {
  return (cellInDiameter(cell) * 0.98) / 0.6
}

/* ------------------------------------------------------------------ */
/* The popup's synopsis — recorded fields only                         */
/* ------------------------------------------------------------------ */

const KIND_LABEL: Record<ShelfScroll['kind'], string> = {
  initiative: 'Initiative',
  project: 'Project',
  task: 'Task',
  idea: 'Idea',
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  if (!Number.isFinite(d.getTime())) return iso
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(d)
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}

/** The popup card's lines for one scroll: kind and status; a
 *  project's declared window; the counts within; a task's
 *  estimate and due date; and, when the cubby's cluster cannot
 *  show the whole nest, the "…and N more within" line. Every word
 *  is a recorded field or a count of recorded fields. */
export function popupSynopsis(bays: ShelfBay[], scroll: ShelfScroll): string[] {
  const lines: string[] = []
  lines.push(
    scroll.status
      ? `${KIND_LABEL[scroll.kind]} · ${scroll.status}`
      : KIND_LABEL[scroll.kind],
  )
  if (scroll.kind === 'initiative') {
    const bay = bays.find((b) => b.initiative?.id === scroll.id)
    const projects = bay?.projects.length ?? 0
    const tasks = bay?.projects.reduce((n, p) => n + p.tasks.length, 0) ?? 0
    if (projects + tasks > 0) {
      lines.push(`${plural(projects, 'project', 'projects')} · ${plural(tasks, 'task', 'tasks')} within`)
    }
  } else if (scroll.kind === 'project') {
    const cluster = clusterChildren(bays, scroll)
    if (cluster.length > 0) lines.push(plural(cluster.length, 'task', 'tasks'))
    if (scroll.windowStart && scroll.windowEnd) {
      lines.push(`${fmtDate(scroll.windowStart)} – ${fmtDate(scroll.windowEnd)}`)
    } else if (scroll.windowStart) {
      lines.push(`from ${fmtDate(scroll.windowStart)}`)
    } else if (scroll.windowEnd) {
      lines.push(`until ${fmtDate(scroll.windowEnd)}`)
    }
  } else if (scroll.kind === 'task') {
    if (scroll.mass != null) lines.push(`${scroll.mass}h estimated`)
    if (scroll.dueDate) lines.push(`due ${fmtDate(scroll.dueDate)}`)
  }
  const cluster = clusterChildren(bays, scroll)
  if (cluster.length > CLUSTER_SHOWN) {
    lines.push(`…and ${cluster.length - CLUSTER_SHOWN} more within`)
  }
  return lines
}

/* ------------------------------------------------------------------ */
/* Trails and the table                                                */
/* ------------------------------------------------------------------ */

export function scrollKey(scroll: ShelfScroll): string {
  return `${scroll.kind}:${scroll.id}`
}

/** The open trail that lands on a scroll through its parents:
 *  shelf → … → the scroll itself. Opening from a popup or the
 *  table walks this trail, so the back step always lands on the
 *  parent it came from (the trail the open screen already uses). */
export function trailForScroll(bays: ShelfBay[], target: ShelfScroll): string[] {
  const parent = new Map<string, ShelfScroll>()
  for (const bay of bays) {
    for (const p of bay.projects) {
      if (bay.initiative) parent.set(scrollKey(p.scroll), bay.initiative)
      for (const t of p.tasks) {
        const par =
          t.parentTaskId && p.tasks.some((x) => x.id === t.parentTaskId)
            ? p.tasks.find((x) => x.id === t.parentTaskId)!
            : p.scroll
        parent.set(scrollKey(t), par)
      }
    }
    for (const t of bay.looseTasks) {
      if (t.parentTaskId) {
        const par = bay.looseTasks.find((x) => x.id === t.parentTaskId)
        if (par) parent.set(scrollKey(t), par)
      }
    }
  }
  const trail: string[] = []
  let cur: ShelfScroll | undefined = target
  const seen = new Set<string>()
  while (cur && !seen.has(scrollKey(cur))) {
    seen.add(scrollKey(cur))
    trail.unshift(scrollKey(cur))
    cur = parent.get(scrollKey(cur))
  }
  return trail
}

export interface TableRow {
  scroll: ShelfScroll
  /** The row scroll's own cluster (first three, as in a cubby). */
  cluster: ShelfScroll[]
}

/** What stands on the worktable for a parent: its children in
 *  shelf order (scrollChildren — an initiative's projects, a
 *  project's top-level tasks, a task's subtasks), each carrying
 *  its own cluster. */
export function tableRows(bays: ShelfBay[], parentScroll: ShelfScroll): TableRow[] {
  return scrollChildren(bays, parentScroll).map((s) => ({
    scroll: s,
    cluster: clusterChildren(bays, s).slice(0, CLUSTER_SHOWN),
  }))
}

/** The long-press route: a scroll with children opens the table;
 *  a leaf opens on the sheet directly. */
export function longPressRoute(bays: ShelfBay[], scroll: ShelfScroll): 'table' | 'sheet' {
  return scrollChildren(bays, scroll).length > 0 ? 'table' : 'sheet'
}
