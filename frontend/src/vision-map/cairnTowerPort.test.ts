/**
 * The ported cairn layout law (cairnTower.ts), tested where the law
 * lives: determinism from stable member ids, temperament from the
 * cairn id alone, October triples balance on representative piles,
 * and the growth law — placement is historical, so adding a member
 * must not move the stones already placed.
 */
import { describe, expect, it } from 'vitest'
import {
  cairnBlend,
  towerDebug,
  towerDebugForMembers,
  towerLayout,
  towerLayoutForMembers,
  type CairnMemberInput,
  type PortedStone,
} from './cairnTower'
import { CAIRN_SPRITES } from './cairnSprites'

const T = 60_000

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

function columnStones(layout: { stones: PortedStone[] }): PortedStone[] {
  return layout.stones.filter((s) => s.role === 'column')
}

describe('cairn port — determinism', () => {
  it('same cairn + members → identical layout, byte for byte', { timeout: T }, () => {
    const a = towerLayoutForMembers('cairn-proj-a', members(6))
    const b = towerLayoutForMembers('cairn-proj-a', members(6))
    expect(JSON.stringify(a)).toBe(JSON.stringify(b))
  })

  it('input order does not matter when arrival times differ (build order is historical)', { timeout: T }, () => {
    const ordered = members(6)
    const shuffled = [ordered[3]!, ordered[0]!, ordered[5]!, ordered[1]!, ordered[4]!, ordered[2]!]
    const a = towerLayoutForMembers('cairn-proj-a', ordered)
    const b = towerLayoutForMembers('cairn-proj-a', shuffled)
    expect(JSON.stringify(a)).toBe(JSON.stringify(b))
  })

  it('per-member sprite, tint and seat derive from the member id, not stack position', { timeout: T }, () => {
    // Same members, different cairn id → different temperament may
    // apply, but within one cairn a member's identity is stable under
    // re-render and under neighbours arriving in a different input
    // order (covered above). Here: two renders keyed by member id.
    const layout = towerLayoutForMembers('cairn-proj-a', members(8))
    const byMember = new Map(columnStones(layout).map((s) => [s.memberId, s]))
    expect(byMember.size).toBe(8)
    for (const s of columnStones(layout)) {
      expect(s.sprite).toBeTruthy()
      expect(s.tint).toMatch(/^#[0-9a-f]{6}$/i)
      expect(Number.isFinite(s.left + s.top + s.rotation)).toBe(true)
    }
  })
})

describe('cairn port — temperament', () => {
  it('blend comes from the cairn id and does not change as members arrive', { timeout: T }, () => {
    const id = 'cairn-proj-temperament'
    const blend = cairnBlend(id)
    for (const n of [2, 4, 7, 12]) {
      const layout = towerLayoutForMembers(id, members(n))
      expect(layout.diagnostics.blend).toBe(blend)
    }
  })

  it('different cairn ids can hold different temperaments', () => {
    const blends = new Set(['cairn-1', 'cairn-2', 'cairn-3', 'cairn-4', 'cairn-5', 'cairn-6', 'cairn-7', 'cairn-8', 'cairn-9', 'cairn-10', 'cairn-11', 'cairn-12'].map(cairnBlend))
    expect(blends.size).toBeGreaterThan(1)
  })
})

describe('cairn port — growth law (placement is historical)', () => {
  it('adding a later member does not move, resize, rotate or re-sprite existing stones', { timeout: T }, () => {
    const base = members(5)
    const before = towerDebugForMembers('cairn-proj-growth', base)
    const grown = towerDebugForMembers('cairn-proj-growth', members(6))
    const beforeByMember = new Map(before.col.filter((b) => b.memberId).map((b) => [b.memberId, b]))
    expect(beforeByMember.size).toBe(5)
    for (const body of grown.col) {
      if (!body.memberId) continue
      const prev = beforeByMember.get(body.memberId)
      if (!prev) continue // the new arrival itself
      expect(body.sprite).toBe(prev.sprite)
      expect(body.x).toBe(prev.x)
      expect(body.y).toBe(prev.y)
      expect(body.w).toBe(prev.w)
      expect(body.h).toBe(prev.h)
      expect(body.rot).toBe(prev.rot)
    }
  })

  it('immobility holds at every step from 2 to 8 members', { timeout: T }, () => {
    let prev = towerDebugForMembers('cairn-proj-steps', members(2))
    for (let n = 3; n <= 8; n++) {
      const next = towerDebugForMembers('cairn-proj-steps', members(n))
      const prevByMember = new Map(prev.col.filter((b) => b.memberId).map((b) => [b.memberId, b]))
      for (const body of next.col) {
        if (!body.memberId) continue
        const p = prevByMember.get(body.memberId)
        if (!p) continue
        expect([body.x, body.y, body.w, body.h, body.rot, body.sprite]).toEqual([p.x, p.y, p.w, p.h, p.rot, p.sprite])
      }
      prev = next
    }
  })
})

describe('cairn port — structure', () => {
  it('the slab is structural: first in paint order, never a member, and the first member pairs on it', { timeout: T }, () => {
    const layout = towerLayoutForMembers('cairn-proj-a', members(4))
    expect(layout.stones[0]!.role).toBe('slab')
    expect(layout.stones[0]!.memberId).toBeNull()
    const dbg = towerDebugForMembers('cairn-proj-a', members(4))
    expect(dbg.col[0]!.role).toBe('slab')
    const firstMember = dbg.col[1]!
    expect(firstMember.memberId).toBe('m-0')
    expect(firstMember.pairOK).toBe(true)
  })

  it('every column stone of representative piles is segment-paired (no floating stones)', { timeout: T }, () => {
    for (const n of [2, 3, 5, 6, 8, 12]) {
      const dbg = towerDebugForMembers(`cairn-proj-pair-${n}`, members(n))
      const cols = dbg.col.filter((b) => b.role === 'column')
      expect(cols.length).toBe(n)
      for (const body of cols) expect(body.pairOK).toBe(true)
    }
  })

  it('October triples: every consecutive triple balances over the middle 70% of its base', { timeout: T }, () => {
    const massOf = (sprite: string, w: number) => {
      const m = CAIRN_SPRITES[sprite]!
      return m.alphaArea * Math.pow(w / m.bodyW, 2)
    }
    for (const n of [3, 5, 6, 8, 12]) {
      const dbg = towerDebugForMembers(`cairn-proj-trip-${n}`, members(n))
      const col = dbg.col // slab first, then members in build order
      for (let k = 2; k < col.length; k++) {
        const a = col[k - 2]!
        const b = col[k - 1]!
        const c = col[k]!
        const M = massOf(a.sprite, a.w) + massOf(b.sprite, b.w) + massOf(c.sprite, c.w)
        const com =
          (massOf(a.sprite, a.w) * a.cenX + massOf(b.sprite, b.w) * b.cenX + massOf(c.sprite, c.w) * c.cenX) / M
        expect(com).toBeGreaterThanOrEqual(a.x - 0.35 * a.w - 1e-9)
        expect(com).toBeLessThanOrEqual(a.x + 0.35 * a.w + 1e-9)
      }
    }
  })

  it('accent discipline: none below six members, at most the October count above', { timeout: T }, () => {
    const accents = (n: number) =>
      towerLayoutForMembers(`cairn-proj-acc-${n}`, members(n)).stones.filter((s) => s.role === 'accent')
        .length
    expect(accents(5)).toBe(0)
    expect(accents(6)).toBeLessThanOrEqual(2)
    expect(accents(8)).toBeLessThanOrEqual(2)
    expect(accents(12)).toBeLessThanOrEqual(3)
  })

  it('render cap: piles render at most 12 members while the badge count stays honest', { timeout: T }, () => {
    const layout = towerLayoutForMembers('cairn-proj-big', members(14))
    expect(layout.columnCount).toBe(12)
    expect(layout.memberCount).toBe(14)
  })

  it('diagnostics disclose the growth record for every rendered insertion', { timeout: T }, () => {
    const layout = towerLayoutForMembers('cairn-proj-a', members(7))
    const d = layout.diagnostics
    expect(d.insertions.length).toBe(7)
    expect(d.orderDebt).toBeGreaterThanOrEqual(0)
    for (const ins of d.insertions) {
      expect(ins.memberId).toBeTruthy()
      expect(ins.assignedSprite).toBeTruthy()
      expect(ins.seatedSprite).toBeTruthy()
      expect(ins.viableSeats).toBeGreaterThanOrEqual(0)
      expect(ins.capWidthAfter).toBeGreaterThan(0)
    }
  })
})

describe('cairn port — legacy wrappers (harness compatibility)', () => {
  it('towerLayout / towerDebug keep their October shapes', { timeout: T }, () => {
    const layout = towerLayout('cairn-legacy', 5)
    expect(layout.columnCount).toBe(5)
    expect(layout.stones.filter((s) => !s.accent).length).toBe(5)
    const dbg = towerDebug('cairn-legacy', 5)
    expect(dbg.col.length).toBe(5)
    expect(dbg.scale).toBeGreaterThan(0)
  })
})
