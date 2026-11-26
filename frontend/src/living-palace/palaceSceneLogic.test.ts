/**
 * Palace Scene 1 — placement-law invariants, pinned on the REAL
 * geometry asset (the founder's art-derived courts). The study
 * builder verifies in two passes; these are the ground-plan pass
 * as tests: containment, separation, determinism, on the shapes
 * the Palace must actually stand — the founder's live shape first.
 */
import { describe, it, expect } from 'vitest'
import {
  GAP,
  FOOTPRINT_SQUASH,
  PALACE_GEOMETRY,
  classForNestedCount,
  ellipseContainedInMask,
  ivyColorFor,
  ivyStageFor,
  masterAspect,
  planCompoundScene,
  type PlacedStructure,
  type SceneStructureInput,
} from './palaceSceneLogic'
import { NATURAL_IVY_GREEN } from './palaceSceneLogic'
import { SEAT_COLORS } from '../council/colors'

const { width: W, height: H } = PALACE_GEOMETRY

function structure(
  entityType: 'initiative' | 'project',
  entityId: string,
  title: string,
  nestedCount: number,
): SceneStructureInput {
  const klass = classForNestedCount(nestedCount)
  return {
    key: `${entityType}:${entityId}`,
    entityType,
    entityId,
    title,
    nestedCount,
    aspect: masterAspect(klass, 1),
  }
}

/** The founder's live shape: four initiatives (by floor count)
 *  plus loose projects (by room count). */
const LIVE_SHAPE: SceneStructureInput[] = [
  structure('initiative', 'i1', 'Zenaf build', 9),
  structure('initiative', 'i2', 'Home front', 6),
  structure('initiative', 'i3', 'Money', 3),
  structure('initiative', 'i4', 'Health', 1),
  structure('project', 'lp1', 'Loose big', 12),
  structure('project', 'lp2', 'Loose mid', 4),
  structure('project', 'lp3', 'Loose small', 0),
]

function expectLawful(placements: PlacedStructure[]) {
  for (const p of placements) {
    expect(
      ellipseContainedInMask(PALACE_GEOMETRY.usable[p.court], W, H, p.fcx, p.fcy, p.rx, p.ry),
      `${p.key} foundation leaves court ${p.court}`,
    ).toBe(true)
  }
  for (let i = 0; i < placements.length; i++) {
    for (let j = i + 1; j < placements.length; j++) {
      const a = placements[i]
      const b = placements[j]
      const dn =
        ((a.fcx - b.fcx) / (a.rx + b.rx + GAP)) ** 2 +
        ((a.fcy - b.fcy) / (a.ry + b.ry + GAP * FOOTPRINT_SQUASH)) ** 2
      expect(dn, `${a.key} vs ${b.key} separation`).toBeGreaterThanOrEqual(1)
    }
  }
}

describe('palace geometry asset', () => {
  it('decodes to the study-verified usable areas', () => {
    // The study builder's verified counts (build_study_v14/v16):
    // the asset and the RLE decoder are pinned together here.
    const sums = { top: 0, left: 0, right: 0 } as Record<string, number>
    for (const court of ['top', 'left', 'right'] as const) {
      sums[court] = PALACE_GEOMETRY.usable[court].reduce((a, b) => a + b, 0)
    }
    expect(sums).toEqual({ top: 54805, left: 72753, right: 72299 })
    expect(PALACE_GEOMETRY.plinths).toEqual({ big: 0.91, medium: 0.908, small: 0.874 })
  })
})

describe('placement law', () => {
  it('places the founder’s live shape, all inside the law', () => {
    const placements = planCompoundScene(LIVE_SHAPE)
    expect(placements).toHaveLength(LIVE_SHAPE.length)
    expectLawful(placements)
    // The live shape is sparse: nothing yields below the floor.
    for (const p of placements) expect(p.scaleUsed).toBeGreaterThanOrEqual(0.64)
  })

  it('is deterministic — same input, same plan', () => {
    const a = planCompoundScene(LIVE_SHAPE)
    const b = planCompoundScene([...LIVE_SHAPE].reverse())
    expect(a).toEqual(b)
  })

  it('deals largest-first across the three courts', () => {
    const placements = planCompoundScene(LIVE_SHAPE)
    const byCourt = { top: [] as string[], left: [] as string[], right: [] as string[] }
    // Reconstruct deal order from placement court + the sorted order.
    const sorted = [...LIVE_SHAPE].sort(
      (x, y) => y.nestedCount - x.nestedCount || x.title.localeCompare(y.title),
    )
    sorted.forEach((s, i) => {
      const court = (['top', 'left', 'right'] as const)[i % 3]
      byCourt[court].push(s.key)
    })
    for (const court of ['top', 'left', 'right'] as const) {
      const placedKeys = placements.filter((p) => p.court === court).map((p) => p.key).sort()
      expect(placedKeys).toEqual([...byCourt[court]].sort())
    }
    // The largest structure (12 rooms) is dealt first, to top.
    expect(placements.find((p) => p.key === 'project:lp1')?.court).toBe('top')
  })

  it('returns placements in foundation-depth order', () => {
    const placements = planCompoundScene(LIVE_SHAPE)
    const bys = placements.map((p) => p.by)
    expect(bys).toEqual([...bys].sort((a, b) => a - b))
  })

  it('stands the study density — 27 structures — inside the law', () => {
    const many: SceneStructureInput[] = []
    const counts = [10, 9, 8, 7, 6, 5, 4, 3, 2]
    for (let round = 0; round < 3; round++) {
      for (const [i, n] of counts.entries()) {
        many.push(structure('project', `s${round}-${i}`, `Structure ${round}-${i}`, n))
      }
    }
    const placements = planCompoundScene(many)
    expect(placements).toHaveLength(27)
    expectLawful(placements)
  })
})

describe('class by nested count', () => {
  it('reads the ruled thresholds', () => {
    expect(classForNestedCount(8)).toBe('big')
    expect(classForNestedCount(40)).toBe('big')
    expect(classForNestedCount(7)).toBe('medium')
    expect(classForNestedCount(3)).toBe('medium')
    expect(classForNestedCount(2)).toBe('small')
    expect(classForNestedCount(0)).toBe('small')
  })
})

describe('ivy stage and hue', () => {
  it('stage thresholds: 0 → 1, 1–4 → 2, ≥5 → 3', () => {
    expect(ivyStageFor(0)).toBe(1)
    expect(ivyStageFor(1)).toBe(2)
    expect(ivyStageFor(4)).toBe(2)
    expect(ivyStageFor(5)).toBe(3)
    expect(ivyStageFor(30)).toBe(3)
  })

  it('hue is the dominant interacting seat’s colour', () => {
    expect(
      ivyColorFor({ entity_type: 'project', entity_id: 'p', total: 5, per_seat: { mentor: 2, maverick: 3 } }),
    ).toBe(SEAT_COLORS.maverick)
    // Ties break deterministically, by seat id.
    expect(
      ivyColorFor({ entity_type: 'project', entity_id: 'p', total: 4, per_seat: { mentor: 2, guardian: 2 } }),
    ).toBe(SEAT_COLORS.guardian)
  })

  it('no interaction — or no known seat — rests at natural green', () => {
    expect(ivyColorFor(undefined)).toBe(NATURAL_IVY_GREEN)
    expect(
      ivyColorFor({ entity_type: 'project', entity_id: 'p', total: 3, per_seat: { nobody: 3 } }),
    ).toBe(NATURAL_IVY_GREEN)
  })
})
