/**
 * Vision map spatial layout — calm arcs, initiative clearance zone, vertical task stacks.
 * Box sizes ≈ mapNodeAppearance tiers (large tree / medium branch / small flower).
 */
export const VISION_MAP_LAYOUT = {
  TREE: { w: 332, h: 248 },
  BRANCH: { w: 288, h: 204 },
  SEED: { w: 224, h: 172 },
  FLOWER: { w: 228, h: 168 },
  FRUIT: { w: 268, h: 192 },
  /** No other node center closer than this to initiative (tree) center */
  INITIATIVE_BUFFER_R: 300,
  /** Branch stone centers sit on this radius from tree center (≥ buffer + visual margin) */
  BRANCH_ORBIT_R: 318,
  TREE_TOP_Y: 200,
  SEED_CLEAR_ABOVE_TREE: 56,
  TASK_STACK_TOP_GAP: 44,
  TASK_ROW_V_GAP: 40,
  /** Horizontal gap between task columns — avoids sibling overlap */
  TASK_COL_H_GAP: 36,
  MAX_TASK_ROWS: 5,
  ORPHAN_COLUMN_PITCH: 360,
} as const

const L = VISION_MAP_LAYOUT

type XY = { x: number; y: number }

/** Tree visual center from React Flow top-left */
export function treeCenter(treeTopLeft: XY): XY {
  return { x: treeTopLeft.x + L.TREE.w / 2, y: treeTopLeft.y + L.TREE.h / 2 }
}

/**
 * Evenly spaced angles on lower semicircle (screen coords: +y down).
 * θ = π/2 points straight below tree center; arc fans left–right symmetrically.
 */
export function branchAnglesForCount(n: number): number[] {
  if (n <= 0) return []
  if (n === 1) return [Math.PI / 2]
  const arcHalf = Math.min(1.12, 0.38 + n * 0.062)
  const lo = Math.PI / 2 - arcHalf
  const hi = Math.PI / 2 + arcHalf
  const out: number[] = []
  for (let i = 0; i < n; i++) {
    out.push(lo + (i / (n - 1)) * (hi - lo))
  }
  return out
}

/** Branch top-left from tree top-left and polar slot */
export function branchTopLeft(treeTopLeft: XY, theta: number): XY {
  const c = treeCenter(treeTopLeft)
  const bcx = c.x + L.BRANCH_ORBIT_R * Math.cos(theta)
  const bcy = c.y + L.BRANCH_ORBIT_R * Math.sin(theta)
  return { x: bcx - L.BRANCH.w / 2, y: bcy - L.BRANCH.h / 2 }
}

/**
 * Outcome stone between tree and branch on the same radial (calm symmetry),
 * still outside initiative buffer (r > INITIATIVE_BUFFER_R).
 */
export function fruitTopLeft(treeTopLeft: XY, theta: number): XY {
  const c = treeCenter(treeTopLeft)
  const r = Math.min(L.BRANCH_ORBIT_R - 10, L.INITIATIVE_BUFFER_R + 42)
  const fcx = c.x + r * Math.cos(theta)
  const fcy = c.y + r * Math.sin(theta)
  return { x: fcx - L.FRUIT.w / 2, y: fcy - L.FRUIT.h / 2 }
}

/**
 * Tasks below branch: primary vertical stack; extra columns only when many tasks,
 * with fixed horizontal stride so boxes do not overlap.
 */
export function taskTopLeft(branchTopLeft: XY, taskIndex: number, taskCount: number): XY {
  const bc = {
    x: branchTopLeft.x + L.BRANCH.w / 2,
    y: branchTopLeft.y + L.BRANCH.h / 2,
  }
  const ncol = Math.max(1, Math.ceil(taskCount / L.MAX_TASK_ROWS))
  const col = taskIndex % ncol
  const row = Math.floor(taskIndex / ncol)
  const stride = L.FLOWER.w + L.TASK_COL_H_GAP
  const gridW = ncol * stride - L.TASK_COL_H_GAP
  const x0 = bc.x - gridW / 2 + L.FLOWER.w / 2
  const fx = x0 + col * stride - L.FLOWER.w / 2
  const fy = branchTopLeft.y + L.BRANCH.h + L.TASK_STACK_TOP_GAP + row * (L.FLOWER.h + L.TASK_ROW_V_GAP)
  return { x: fx, y: fy }
}

/** Tree centered in column */
export function treeTopLeftForColumn(columnCenterX: number, treeTopY: number): XY {
  return { x: columnCenterX - L.TREE.w / 2, y: treeTopY }
}

/** Idea seed above tree, centered; vertical gap so seed–tree centers respect buffer */
export function seedTopLeftAboveTree(treeTopLeft: XY): XY {
  const c = treeCenter(treeTopLeft)
  const scy = c.y - L.INITIATIVE_BUFFER_R - L.SEED.h / 2 - L.SEED_CLEAR_ABOVE_TREE
  return { x: c.x - L.SEED.w / 2, y: scy }
}

/**
 * Minimum column width so the widest branch arc + padding fits between initiative columns.
 */
export function columnWidthForBranchCount(maxBranches: number): number {
  const n = Math.max(1, maxBranches)
  const angles = branchAnglesForCount(n)
  const xs = angles.map((th) => L.BRANCH_ORBIT_R * Math.cos(th))
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const arcSpan = maxX - minX + L.BRANCH.w
  const fromBuffer = 2 * L.INITIATIVE_BUFFER_R + L.TREE.w * 0.35
  return Math.ceil(Math.max(fromBuffer, arcSpan + 200, 720))
}
