/**
 * The Blend ruling (founder, 2026-11-13): each cairn stone's stain is
 * its OWN strand weight vector mixed in CIELAB over the subdued L2 wood
 * stains — never one wash per pile. Unweighed members, fruit, the slab,
 * rim accents and companions render grayscale. Plus the accent host
 * law from the founder's leaner diagnosis the same evening: rim accents
 * host only on stack members and never overlap a companion.
 *
 * Expected blend hexes below were computed by the colour-comparison
 * sheet's renderer (render-cairn-color-options.py) — the reference
 * implementation this module ports — not by the code under test.
 */
import { describe, expect, it } from 'vitest'
import {
  blendStainHex,
  cairnBlend,
  towerDebugForMembers,
  towerLayoutForMembers,
  type CairnMemberInput,
  type PortedStone,
} from './cairnTower'
import { cairnMembersOf } from './cairn'
import { buildLiveVisionMapGraph } from './liveProjection'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import type { MapNodePayload } from './ontology'
import type { Node } from '@xyflow/react'

const NEUTRAL = '#a8a29e'
const T = 60_000

function channels(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function expectHexClose(actual: string | null, expected: string, tol = 2) {
  expect(actual).not.toBeNull()
  const a = channels(actual!)
  const e = channels(expected)
  for (let i = 0; i < 3; i++) expect(Math.abs(a[i]! - e[i]!)).toBeLessThanOrEqual(tol)
}

/** The port tests' member fixture — the accent sweep below must build
    the same piles the defect scan measured. */
function members(n: number, prefix = 'm'): CairnMemberInput[] {
  const kinds = ['branch', 'flower', 'flower', 'fruit', 'flower', 'seed', 'flower', 'fruit', 'flower', 'flower', 'seed', 'flower', 'flower', 'fruit']
  const growths = ['growing', 'fruiting', 'germinating', 'dormant', 'growing', 'decaying'] as const
  const out: CairnMemberInput[] = []
  for (let i = 0; i < n; i++) {
    out.push({
      id: `${prefix}-${i}`,
      kind: kinds[i % kinds.length]!,
      activity: 0.25 + ((i * 37) % 65) / 100,
      createdAt: new Date(1700000000000 + i * 86400000).toISOString(),
      growth: growths[i % growths.length],
    })
  }
  return out
}

function cairnIdWithBlend(blend: number): string {
  for (let i = 0; ; i++) {
    const id = `cairn-blend-test-${i}`
    if (cairnBlend(id) === blend) return id
  }
}

describe('blend stain math (CIELAB mix over the L2 wood stains)', () => {
  it('mixes a balanced vector to the reference warm gray', () => {
    // Even Split on the comparison sheet: sound .34 / self .33 / number .33.
    expectHexClose(blendStainHex({ sound: 0.34, self: 0.33, number: 0.33 }), '#77716d')
  })

  it('mixes a word-led vector to the reference walnut blend', () => {
    expectHexClose(blendStainHex({ word: 0.45, sound: 0.35, image: 0.2 }), '#a16c55')
  })

  it('a single-strand vector returns that strand’s stain itself', () => {
    expectHexClose(blendStainHex({ image: 1 }), '#b98d55', 1)
    expectHexClose(blendStainHex({ people: 1 }), '#77598a', 1)
  })

  it('mixes two- and three-strand vectors to the reference hexes', () => {
    expectHexClose(blendStainHex({ word: 0.5, number: 0.5 }), '#7e6765')
    expectHexClose(blendStainHex({ body: 0.65, self: 0.35 }), '#728464')
  })

  it('weights need not be normalized — the mix is a weighted average', () => {
    expectHexClose(
      blendStainHex({ sound: 34, self: 33, number: 33 }),
      blendStainHex({ sound: 0.34, self: 0.33, number: 0.33 })!,
      1,
    )
  })

  it('no positive weight → null (unweighed renders grayscale)', () => {
    expect(blendStainHex({})).toBeNull()
    expect(blendStainHex({ word: 0, image: 0 })).toBeNull()
  })
})

describe('blend stains in the laid-out pile', () => {
  it('a weighed member wears its own blend; unweighed, fruit, slab, accents and companions stay neutral', { timeout: T }, () => {
    // Blend 0 temperament => jitter factor 0, so a member's tint IS its
    // base stain, byte for byte.
    const id = cairnIdWithBlend(0)
    const ms = members(6)
    ms[0]!.weights = { word: 0.45, sound: 0.35, image: 0.2 }
    ms[1]!.weights = null
    ms[3]!.weights = { image: 1 } // fruit kind — never weighable
    const layout = towerLayoutForMembers(id, ms)
    const byMember = new Map(layout.stones.filter((s) => s.memberId).map((s) => [s.memberId, s]))
    expectHexClose(byMember.get('m-0')!.tint, '#a16c55', 0)
    expect(byMember.get('m-1')!.tint).toBe(NEUTRAL)
    expect(byMember.get('m-3')!.tint).toBe(NEUTRAL)
    for (const s of layout.stones) {
      if (s.role === 'column') continue
      expect(s.tint).toBe(NEUTRAL) // slab, accents, companions
    }
  })

  it('under a jittering temperament the blend is jittered, not replaced', { timeout: T }, () => {
    const id = cairnIdWithBlend(2)
    const ms = members(6)
    ms[0]!.weights = { word: 0.45, sound: 0.35, image: 0.2 }
    ms[1]!.weights = null
    const layout = towerLayoutForMembers(id, ms)
    const byMember = new Map(layout.stones.filter((s) => s.memberId).map((s) => [s.memberId, s]))
    const tinted = byMember.get('m-0')!.tint
    expect(tinted).not.toBe(NEUTRAL)
    expectHexClose(tinted, '#a16c55', 40) // jitter range, not a new colour
    // An unweighed member under jitter stays the neutral wash family —
    // jittered neutral, never a strand colour.
    expectHexClose(byMember.get('m-1')!.tint, NEUTRAL, 40)
  })

  it('two members with different vectors wear visibly different stains in one pile', { timeout: T }, () => {
    const id = cairnIdWithBlend(0)
    const ms = members(6)
    ms[0]!.weights = { image: 1 }
    ms[1]!.weights = { people: 1 }
    const layout = towerLayoutForMembers(id, ms)
    const byMember = new Map(layout.stones.filter((s) => s.memberId).map((s) => [s.memberId, s]))
    expectHexClose(byMember.get('m-0')!.tint, '#b98d55', 0)
    expectHexClose(byMember.get('m-1')!.tint, '#77598a', 0)
  })
})

/* ---------- projection payload plumbing ---------- */

const NOW = new Date().toISOString()

function bundleFixture(): VisionMapEntityBundle {
  const ideas: Idea[] = [
    { id: 'idea-1', title: 'Seed', summary: '', description: '', status: 'Exploring', tags: [], created_by: 'fixture', created_at: NOW, updated_at: NOW } as Idea,
  ]
  const initiatives: Initiative[] = [
    {
      id: 'ini-1', source_idea_id: 'idea-1', title: 'Initiative', brief: '', status: 'Active', owner_id: null,
      evaluation_priority: 2, estimated_cost_ai: 'Medium', estimated_timeframe_ai: '4–6 weeks',
      philosophical_alignment_ai: 'Strong', next_step_ai: '', required_assets: [], dependencies: '',
      risks: '', recommendation: '', kill_criteria: '', notes: '', created_at: NOW, updated_at: NOW,
    } as Initiative,
  ]
  const project = (id: string, title: string): Project =>
    ({
      id, initiative_id: 'ini-1', title, brief: '', status: 'Active', owner_id: null,
      supporting_owner_ids: [], required_assets: [], priority: '2', start_date: null, end_date: null,
      estimated_weekly_hours: 4, next_step_ai: '', notes: '', created_at: NOW, updated_at: NOW,
    }) as Project
  const task = (id: string, projectId: string, title: string): Task =>
    ({
      id, project_id: projectId, parent_task_id: null, title, description: '', assignee_id: null,
      status: 'Todo', priority: '2', estimated_hours: 2, due_date: null, dependency_ids: [],
      completion_criteria: '', notes: '', created_at: NOW, updated_at: NOW,
    }) as Task
  return {
    ideas,
    initiatives,
    projects: [project('p-weighed', 'Weighed project'), project('p-plain', 'Plain project')],
    tasks: [task('t-weighed', 'p-weighed', 'Weighed task'), task('t-plain', 'p-weighed', 'Plain task')],
  }
}

const WEIGHTS = {
  'project:p-weighed': { word: 0.5, number: 0.5 },
  'task:t-weighed': { image: 1 },
}

describe('strand weights in the projection payload', () => {
  it('a weighed member carries its vector; an unweighed member carries null', () => {
    const g = buildLiveVisionMapGraph(bundleFixture(), [], undefined, { strandWeights: WEIGHTS })
    const payloadOf = (nodeId: string) =>
      g.nodes.find((n) => n.id === nodeId)?.data as { entity_strand_weights?: unknown } | undefined
    expect(payloadOf('branch-p-weighed')?.entity_strand_weights).toEqual({ word: 0.5, number: 0.5 })
    expect(payloadOf('flower-t-weighed')?.entity_strand_weights).toEqual({ image: 1 })
    expect(payloadOf('branch-p-plain')?.entity_strand_weights).toBeNull()
    expect(payloadOf('flower-t-plain')?.entity_strand_weights).toBeNull()
  })

  it('without a weightings fetch every member is honestly unweighed', () => {
    const g = buildLiveVisionMapGraph(bundleFixture(), [], undefined, {})
    const branch = g.nodes.find((n) => n.id === 'branch-p-weighed')?.data as
      | { entity_strand_weights?: unknown }
      | undefined
    expect(branch?.entity_strand_weights).toBeNull()
  })

  it('cairn members inherit the payload weights end-to-end', () => {
    const g = buildLiveVisionMapGraph(bundleFixture(), [], undefined, {
      strandWeights: WEIGHTS,
      cairnThreshold: 1,
    })
    const cairn = g.nodes.find((n) => (n.data as { cairnProjectId?: string }).cairnProjectId === 'p-weighed')
    expect(cairn).toBeTruthy()
    const ms = (cairn!.data as { cairnMembers?: CairnMemberInput[] }).cairnMembers ?? []
    const byId = new Map(ms.map((m) => [m.id, m]))
    expect(byId.get('branch-p-weighed')?.weights).toEqual({ word: 0.5, number: 0.5 })
    expect(byId.get('flower-t-weighed')?.weights).toEqual({ image: 1 })
    expect(byId.get('flower-t-plain')?.weights).toBeNull()
  })

  it('cairnMembersOf shape-checks the payload vector', () => {
    const node = (id: string, weights: unknown) =>
      ({
        id,
        position: { x: 0, y: 0 },
        data: {
          kind: 'flower',
          label: id,
          growth: 'growing',
          condition: 'healthy',
          ref: { veType: 'task', id },
          summaryLines: [],
          water_level: 'low',
          fertilizer_pulse: false,
          entity_strand_weights: weights,
        } as MapNodePayload,
      }) as unknown as Node<MapNodePayload>
    const [good] = cairnMembersOf([node('a', { word: 0.5, number: 0.5 })])
    expect(good!.weights).toEqual({ word: 0.5, number: 0.5 })
    const [bad] = cairnMembersOf([node('b', { word: 'lots' })])
    expect(bad!.weights).toBeNull()
    const [bogus] = cairnMembersOf([node('c', { bogus: 1 })])
    expect(bogus!.weights).toBeNull()
    const [absent] = cairnMembersOf([node('d', undefined)])
    expect(absent!.weights).toBeNull()
  })
})

/* ---------- accent host law ---------- */

type Pt = [number, number]

function bodyPoly(s: PortedStone): Pt[] {
  const r = (s.rotation * Math.PI) / 180
  const c = Math.cos(r)
  const sn = Math.sin(r)
  const hw = s.bodyWidth / 2
  const hh = s.bodyHeight / 2
  return (
    [
      [-hw, -hh],
      [hw, -hh],
      [hw, hh],
      [-hw, hh],
    ] as Pt[]
  ).map(([x, y]) => [s.bodyCx + x * c - y * sn, s.bodyCy + x * sn + y * c] as Pt)
}

function polyArea(p: Pt[]): number {
  let a = 0
  for (let i = 0; i < p.length; i++) {
    const [x1, y1] = p[i]!
    const [x2, y2] = p[(i + 1) % p.length]!
    a += x1 * y2 - x2 * y1
  }
  return a / 2
}

function clipPoly(subject: Pt[], clip: Pt[]): Pt[] {
  const signed = polyArea(clip)
  const inside = (p: Pt, a: Pt, b: Pt) => {
    const cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    return signed >= 0 ? cross >= 0 : cross <= 0
  }
  const intersect = (p1: Pt, p2: Pt, a: Pt, b: Pt): Pt => {
    const d1x = p2[0] - p1[0]
    const d1y = p2[1] - p1[1]
    const d2x = b[0] - a[0]
    const d2y = b[1] - a[1]
    const denom = d1x * d2y - d1y * d2x
    if (Math.abs(denom) < 1e-12) return p2
    const t = ((a[0] - p1[0]) * d2y - (a[1] - p1[1]) * d2x) / denom
    return [p1[0] + t * d1x, p1[1] + t * d1y]
  }
  let out = subject
  for (let i = 0; i < clip.length; i++) {
    const a = clip[i]!
    const b = clip[(i + 1) % clip.length]!
    const inp = out
    out = []
    for (let j = 0; j < inp.length; j++) {
      const cur = inp[j]!
      const prv = inp[(j + inp.length - 1) % inp.length]!
      const curIn = inside(cur, a, b)
      const prvIn = inside(prv, a, b)
      if (curIn) {
        if (!prvIn) out.push(intersect(prv, cur, a, b))
        out.push(cur)
      } else if (prvIn) {
        out.push(intersect(prv, cur, a, b))
      }
    }
    if (!out.length) break
  }
  return out
}

/** Fraction of an accent's body rectangle overlapping a companion's. */
function rectOverlapFraction(accent: PortedStone, companion: PortedStone): number {
  const aPoly = bodyPoly(accent)
  const aArea = Math.abs(polyArea(aPoly))
  if (aArea <= 0) return 0
  const inter = clipPoly(aPoly, bodyPoly(companion))
  return inter.length ? Math.abs(polyArea(inter)) / aArea : 0
}

describe('accent host law (accents sit on stack members, never on companions)', () => {
  // The defect scan (pre-fix engine, same fixture + metric): 39
  // accent–companion overlapping pairs across these piles, the worst
  // at 100% of the accent's body rect inside the leaner — the founder's
  // screenshot exactly. Post-fix the same sweep measures 5 pairs, worst
  // 25.9% (body-rect overlap; alpha-cell overlap is ≤3 cells by the
  // placement rule). The 0.30 bound separates the two regimes.
  const SCAN_IDS = [0, 1, 7, 29, 44, 52, 56]
  const SIZES = [6, 8, 10, 12]

  it('no accent overlaps a companion beyond a rim touch, across the scanned piles', { timeout: 240_000 }, () => {
    for (const ci of SCAN_IDS) {
      const cairn = `cairn-scan-${ci}`
      for (const n of SIZES) {
        const layout = towerLayoutForMembers(cairn, members(n))
        const accents = layout.stones.filter((s) => s.role === 'accent')
        const companions = layout.stones.filter((s) => s.role === 'leaner' || s.role === 'wedge')
        for (const a of accents) {
          for (const cp of companions) {
            expect(
              rectOverlapFraction(a, cp),
              `${cairn} n=${n}: accent overlaps ${cp.role}`,
            ).toBeLessThanOrEqual(0.3)
          }
        }
      }
    }
  })

  it('every accent host is an eligible stack member — never the base, never the summit two, never a companion', { timeout: T }, () => {
    for (const ci of SCAN_IDS) {
      const cairn = `cairn-scan-${ci}`
      for (const n of SIZES) {
        const dbg = towerDebugForMembers(cairn, members(n))
        for (const a of dbg.accents) {
          // Debug host is a member index: eligible hosts are members
          // 1..n-3 (column 2..n-2). Companions are not column members
          // and can never appear here.
          expect(a.host).toBeGreaterThanOrEqual(1)
          expect(a.host).toBeLessThanOrEqual(n - 3)
        }
      }
    }
  })
})
