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
 *    The fabric is DISPLAYED as the frozen builder's own raster:
 *    assets/scroll-fabric.png is generated from
 *    build_composite_v4.py's fabric code verbatim (depth bands +
 *    the hollow wooden frames, keep-masked) by
 *    sprites/scroll-rebuild/scene-1/gen_fabric.py, and verified
 *    against the frozen composite (wall-band diff ≈ 0). The view
 *    lays that one image over the room; the deflation here still
 *    computes the CELLS the cubbies stand in. Two earlier builds
 *    substituted their own drawing for the builder's fabric — a
 *    stroked vector lattice (PR #449), then per-rhomb SVG image
 *    transforms that iOS painted as a giant overlapping web
 *    (PR #450) — both caught by the founder on device 2026-11-26.
 *    The material is the builder's raster, never a redraw.
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
  // Which cells may hold a scroll, in order (founder, 2026-11-26:
  // "fit within the rhombi — specifically only the large rhombi"):
  // LARGE (thick) rhombi inside the wall band first — the band
  // inset far enough that a standing scroll never reaches the
  // floor or spills past the wall's side edges, a hard preference
  // since the founder caught a scroll on the floorboards twice —
  // then large rhombi outside the band, and only as the
  // never-drop last resort the thin rhombi. Within each pool,
  // spaced cells before crowded ones.
  const inBand = (c: FabricRhomb) =>
    c.centre.x >= 175 && c.centre.x <= 1330 && c.centre.y >= 290 && c.centre.y <= 780
  const priority = cellPriorityOrder(rhombs)
  const pools = [
    priority.filter((c) => c.thick && inBand(c)),
    priority.filter((c) => c.thick && !inBand(c)),
    priority.filter((c) => !c.thick && inBand(c)),
    priority.filter((c) => !c.thick && !inBand(c)),
  ]
  const taken: FabricRhomb[] = []
  const chosen: FabricRhomb[] = []
  const spaced = (c: FabricRhomb) =>
    taken.every(
      (t) => Math.hypot(t.centre.x - c.centre.x, t.centre.y - c.centre.y) >= CUBBY_MIN_SEPARATION,
    )
  for (let i = 0; i < units.length; i++) {
    let cell: FabricRhomb | undefined
    for (const pool of pools) {
      cell =
        pool.find((c) => !taken.includes(c) && spaced(c)) ??
        pool.find((c) => !taken.includes(c))
      if (cell) break
    }
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

/** The end-on asset's silhouette contour: 48 points around the
 *  asset's opaque shape (alpha > 128), measured from the asset
 *  itself (scroll-end.png, 709×699) as offsets from the asset's
 *  centre in units of the asset's width. The shape is not its
 *  bounding box — the corners are empty parchment-free air, the
 *  tag protrudes below — so the fit works from the silhouette,
 *  not the rectangle. The right-side asset is the mirror image;
 *  the fit mirrors the contour's x with it. */
export const SCROLL_CONTOUR: [number, number][] = [
  [0.4006, 0.0], [0.3384, 0.0446], [0.2684, 0.0719], [0.215, 0.0891],
  [0.1759, 0.1016], [0.1477, 0.1133], [0.1217, 0.1217], [0.0996, 0.1298],
  [0.079, 0.1368], [0.0599, 0.1446], [0.0405, 0.1512], [0.0208, 0.158],
  [0.0, 0.165], [-0.0219, 0.1664], [-0.0383, 0.143], [-0.1981, 0.4782],
  [-0.2715, 0.4703], [-0.3555, 0.4633], [-0.378, 0.378], [-0.3726, 0.2859],
  [-0.3664, 0.2116], [-0.3623, 0.1501], [-0.3638, 0.0975], [-0.4111, 0.0541],
  [-0.4471, 0.0], [-0.4726, -0.0622], [-0.4864, -0.1303], [-0.4847, -0.2008],
  [-0.4678, -0.2701], [-0.4386, -0.3366], [-0.392, -0.392], [-0.3357, -0.4375],
  [-0.2694, -0.4666], [-0.1986, -0.4795], [-0.127, -0.4741], [-0.0596, -0.4531],
  [-0.0, -0.4288], [0.0532, -0.4041], [0.1029, -0.3842], [0.1517, -0.3662],
  [0.2038, -0.353], [0.2584, -0.3368], [0.3172, -0.3172], [0.386, -0.2962],
  [0.4593, -0.2652], [0.4887, -0.2024], [0.4796, -0.1285], [0.4559, -0.06],
]

/** The fit margin: a scroll's silhouette is fitted inside the
 *  rhomb shrunk to this fraction of itself about its centre, so
 *  the scroll stands clear of the frame's wood on every side. */
export const SCROLL_FIT_MARGIN = 0.94

/** Is a point inside a convex quad (corners in cyclic order)?
 *  Consistent cross-product signs — boundary counts as inside. */
function pointInConvexQuad(p: Pt, quad: Pt[]): boolean {
  let sign = 0
  for (let i = 0; i < 4; i++) {
    const a = quad[i]
    const b = quad[(i + 1) % 4]
    const cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
    if (cross !== 0) {
      if (sign === 0) sign = Math.sign(cross)
      else if (Math.sign(cross) !== sign) return false
    }
  }
  return true
}

/** A scroll's placement in its cell (founder, 2026-11-26: "Scale
 *  and move the scrolls until they fit within the rhombi"). The
 *  asset's measured silhouette is scaled as large as it can be
 *  while every contour point stands inside the rhomb (shrunk by
 *  SCROLL_FIT_MARGIN), and its centre may shift within the cell
 *  to win size: candidate offsets are tried nearest-first, a
 *  shift is kept only when it buys real width. Deterministic:
 *  fixed offset grid, fixed binary search. Recorded size keeps
 *  its role where the brief puts it: it orders the assignment,
 *  so bigger items take earlier cells. */
export function scrollPlacementFor(
  cell: FabricRhomb,
  side: 'left' | 'right',
): { width: number; cx: number; cy: number } {
  const target = cell.corners.map((c) => ({
    x: cell.centre.x + (c.x - cell.centre.x) * SCROLL_FIT_MARGIN,
    y: cell.centre.y + (c.y - cell.centre.y) * SCROLL_FIT_MARGIN,
  }))
  const flip = side === 'right' ? -1 : 1
  const fits = (cx: number, cy: number, w: number) =>
    SCROLL_CONTOUR.every(([dx, dy]) =>
      pointInConvexQuad({ x: cx + flip * dx * w, y: cy + dy * w }, target),
    )
  const maxWidthAt = (cx: number, cy: number) => {
    let lo = 1
    let hi = 240
    for (let i = 0; i < 24; i++) {
      const mid = (lo + hi) / 2
      if (fits(cx, cy, mid)) lo = mid
      else hi = mid
    }
    return lo
  }
  const offsets = [0, -6, 6, -12, 12]
    .flatMap((dx) => [0, -6, 6, -12, 12].map((dy) => ({ dx, dy })))
    .sort((a, b) => Math.abs(a.dx) + Math.abs(a.dy) - (Math.abs(b.dx) + Math.abs(b.dy)))
  let best = { width: 0, cx: cell.centre.x, cy: cell.centre.y }
  for (const { dx, dy } of offsets) {
    const w = maxWidthAt(cell.centre.x + dx, cell.centre.y + dy)
    if (w > best.width + 0.5) best = { width: w, cx: cell.centre.x + dx, cy: cell.centre.y + dy }
  }
  return best
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
