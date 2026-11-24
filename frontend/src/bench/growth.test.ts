/**
 * Growth-port equivalence — the port is proven, not asserted.
 *
 * growthHarness.py deals two trees (B1, B2) from the frozen fixture
 * and grows them with the canonical Python machinery
 * (growth_demo3.grow / trunk_point / cluster_pads), dumping every
 * polyline. This suite grows the SAME element tables with the
 * TypeScript port and compares point for point: primaries, every
 * wood entry, twigs, anchors, clustered pads, bridge pads, and the
 * trunk itself. It also checks the RNG port against CPython draw
 * sequences directly (random / uniform / choice / gauss / randint,
 * including an interleaved sequence, since geometry depends on draw
 * order across methods).
 */
import { describe, it, expect } from 'vitest'
import fixture from './__fixtures__/growth-fixture.json'
import { PythonRandom, seedRng } from './rng'
import {
  growTree,
  TRUNK_PATH,
  type BenchElement,
  type GeometryRegister,
  type Pt,
} from './growth'

interface DumpElement {
  handle: string
  register: GeometryRegister
  side: 1 | -1
  weight: number
  len_old: number
  elev: number
  sprite: number
  t_grow: number
}
interface DumpTree {
  elements: DumpElement[]
  crosses: Array<[string, string]>
  primaries: Record<string, Pt[]>
  wood: Array<{ pts: Pt[]; wRoot: number; wTip: number; gen: number; handle: string }>
  twigs: Array<[Pt, Pt]>
  anchors: Record<string, Pt[]>
  pads: Record<string, Array<{ c: Pt; rx: number; ry: number; n: number }>>
  bridges: Array<{ c: Pt; handle: string; rx: number; ry: number; reach: boolean }>
}

const dump = fixture as unknown as {
  rngCheck: Record<string, number[]>
  trunkPath: Pt[]
  trees: Record<string, DumpTree>
}

function maxDeviation(a: Pt[], b: Pt[]): number {
  expect(a.length).toBe(b.length)
  let max = 0
  for (let i = 0; i < a.length; i++) {
    max = Math.max(max, Math.abs(a[i][0] - b[i][0]), Math.abs(a[i][1] - b[i][1]))
  }
  return max
}

describe('PythonRandom — CPython draw equivalence', () => {
  it('random() sequence matches', () => {
    const r = seedRng('grammar5', 'B1-T2')
    const got = [r.random(), r.random(), r.random(), r.random(), r.random()]
    expect(got).toEqual(dump.rngCheck.random5)
  })
  it('uniform() sequence matches', () => {
    const r = seedRng('grammar5', 'B1-T2')
    const got = [r.uniform(-1.3, 1.3), r.uniform(-1.3, 1.3), r.uniform(-1.3, 1.3)]
    expect(got).toEqual(dump.rngCheck.uniform3)
  })
  it('choice() sequence matches (_randbelow over getrandbits)', () => {
    const r = seedRng('grammar5', 'B1-T2')
    const got = Array.from({ length: 6 }, () => r.choice([1, -1] as const))
    expect(got).toEqual(dump.rngCheck.choice6)
  })
  it('gauss() sequence matches (polar method + cached value)', () => {
    const r = seedRng('grammar5', 'B1-T2')
    const got = [r.gauss(0, 1), r.gauss(0, 1), r.gauss(0, 1), r.gauss(0, 1)]
    got.forEach((g, i) => expect(g).toBeCloseTo(dump.rngCheck.gauss4[i], 12))
  })
  it('randint() sequence matches', () => {
    const r = seedRng('grammar5', 'B1-T2')
    const got = [r.randint(35, 105), r.randint(35, 105), r.randint(35, 105), r.randint(35, 105)]
    expect(got).toEqual(dump.rngCheck.randint4)
  })
  it('interleaved draws across methods stay in lockstep', () => {
    const r = seedRng('grammar5', 'B1-T2')
    const got = [
      r.uniform(0.85, 1.12),
      r.choice([1, -1] as const),
      r.gauss(0, 10),
      r.randint(95, 175),
      r.random(),
    ]
    got.forEach((g, i) => expect(g).toBeCloseTo(dump.rngCheck.mixed[i], 12))
  })
  it('a raw PythonRandom(seed) is deterministic', () => {
    const a = new PythonRandom(12345)
    const b = new PythonRandom(12345)
    for (let i = 0; i < 50; i++) expect(a.random()).toBe(b.random())
  })
})

describe('growth port vs canonical Python geometry', () => {
  it('trunk path matches', () => {
    expect(maxDeviation(TRUNK_PATH, dump.trunkPath)).toBeLessThan(1e-9)
  })

  for (const [treeId, tree] of Object.entries(dump.trees)) {
    it(`${treeId}: primaries, wood, twigs, anchors, pads match the Python original`, () => {
      const elements: BenchElement[] = tree.elements.map((e) => ({
        handle: e.handle,
        register: e.register,
        side: e.side,
        tGrow: e.t_grow,
        elev: e.elev,
        lenOld: e.len_old,
        sprite: e.sprite,
      }))
      const grown = growTree(elements, tree.crosses)
      let worst = 0
      // primaries
      for (const [handle, pts] of Object.entries(tree.primaries)) {
        worst = Math.max(worst, maxDeviation(grown.primaries.get(handle)!, pts))
      }
      // every wood entry, in order
      expect(grown.wood.length).toBe(tree.wood.length)
      grown.wood.forEach((w, i) => {
        expect(w.handle).toBe(tree.wood[i].handle)
        expect(w.gen).toBe(tree.wood[i].gen)
        expect(w.wRoot).toBeCloseTo(tree.wood[i].wRoot, 12)
        expect(w.wTip).toBeCloseTo(tree.wood[i].wTip, 12)
        worst = Math.max(worst, maxDeviation(w.pts, tree.wood[i].pts))
      })
      // twigs
      expect(grown.twigs.length).toBe(tree.twigs.length)
      grown.twigs.forEach((t, i) => {
        worst = Math.max(worst, maxDeviation([t.p0, t.p1], tree.twigs[i]))
      })
      // anchors
      for (const [handle, pts] of Object.entries(tree.anchors)) {
        worst = Math.max(worst, maxDeviation(grown.anchors.get(handle)!, pts))
      }
      // pads
      for (const [handle, pads] of Object.entries(tree.pads)) {
        const mine = grown.padsByHandle.get(handle)!
        expect(mine.length).toBe(pads.length)
        mine.forEach((p, i) => {
          worst = Math.max(worst, maxDeviation([p.c], [pads[i].c]))
          expect(p.rx).toBeCloseTo(pads[i].rx, 9)
          expect(p.ry).toBeCloseTo(pads[i].ry, 9)
          expect(p.n).toBe(pads[i].n)
        })
      }
      // bridges
      expect(grown.bridges.length).toBe(tree.bridges.length)
      grown.bridges.forEach((br, i) => {
        worst = Math.max(worst, maxDeviation([br.c], [tree.bridges[i].c]))
        expect(br.rx).toBeCloseTo(tree.bridges[i].rx, 9)
        expect(br.ry).toBeCloseTo(tree.bridges[i].ry, 9)
        expect(br.reach ?? false).toBe(tree.bridges[i].reach)
      })
      // The whole geometry, point for point: doubles on both sides,
      // identical operation order — deviation is float noise only.
      expect(worst).toBeLessThan(1e-6)
    })

    it(`${treeId}: growing twice with the same seeds is byte-identical (determinism)`, () => {
      const elements: BenchElement[] = tree.elements.map((e) => ({
        handle: e.handle,
        register: e.register,
        side: e.side,
        tGrow: e.t_grow,
        elev: e.elev,
        lenOld: e.len_old,
        sprite: e.sprite,
      }))
      const a = growTree(elements, tree.crosses)
      const b = growTree(elements, tree.crosses)
      const flat = (g: typeof a) =>
        JSON.stringify({
          wood: g.wood.map((w) => w.pts),
          twigs: g.twigs.map((t) => [t.p0, t.p1]),
          pads: [...g.padsByHandle.values()].map((ps) => ps.map((p) => [p.c, p.rx, p.ry, p.n])),
        })
      expect(flat(a)).toBe(flat(b))
    })
  }
})
