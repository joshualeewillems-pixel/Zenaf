/**
 * Conversation colour (founder's law, 2026-11-14): "conversation within
 * the project with one of the characters shifts the color of the stone
 * towards that characters color" — and an exclusive conversation
 * history shifts it ENTIRELY. These tests pin:
 *  (i)   the iOS touch-callout suppression on the painted stone's img
 *        class (the hold-hijack fix),
 *  (ii)  the formula: zero conversations ⇒ stated weights pass through
 *        unchanged; exclusive seat ⇒ exactly that seat's blend;
 *        two seats ⇒ the proportional mix,
 *  (iii) the keystone source: a seat's "Meet the {character}" pile
 *        tints with the seat's blend once its "First meeting" task is
 *        Done, and stays neutral before,
 *  (iv)  an unstacked tree's painted single (not the legacy oval),
 *  (v)   a weighed plain single paints with its blend; an unweighed
 *        plain single does not paint (oval path preserved).
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { Node } from '@xyflow/react'
import {
  conversationWeights,
  effectiveStrandWeights,
  keystoneConversationCountsByProject,
  seatBlendFor,
} from './conversationColour'
import { paintedSingleStoneFor } from './cairn'
import { blendStainHex, towerLayoutForMembers, type CairnMemberInput } from './cairnTower'
import { buildLiveVisionMapGraph } from './liveProjection'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import type { MapNodePayload } from './ontology'

const NEUTRAL = '#a8a29e'
const NOW = new Date().toISOString()

function channels(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function expectHexClose(actual: string, expected: string, tol: number) {
  const a = channels(actual)
  const e = channels(expected)
  for (let i = 0; i < 3; i++) expect(Math.abs(a[i]! - e[i]!)).toBeLessThanOrEqual(tol)
}

/* ---------- (i) the hold hijack: callout suppression ---------- */

describe('iOS touch callout suppression (mapAesthetics.css)', () => {
  const css = readFileSync(new URL('./mapAesthetics.css', import.meta.url), 'utf8')

  it('the painted stone img class suppresses the native callout', () => {
    const start = css.indexOf('.cairn-stone-base {')
    expect(start).toBeGreaterThanOrEqual(0)
    const block = css.slice(start, css.indexOf('}', start))
    expect(block).toContain('-webkit-touch-callout: none')
  })

  it('map stone surfaces suppress the callout on any contained image', () => {
    const start = css.indexOf('.map-stone-surface img {')
    expect(start).toBeGreaterThanOrEqual(0)
    const block = css.slice(start, css.indexOf('}', start))
    expect(block).toContain('-webkit-touch-callout: none')
  })
})

/* ---------- (ii) the formula ---------- */

describe('conversation colour formula', () => {
  it('every canonical seat_ref resolves to a blend; unknown seats do not', () => {
    for (const seat of ['conductor', 'mentor', 'champion', 'guardian', 'ambassador', 'skeptic', 'maverick']) {
      expect(seatBlendFor(seat), seat).not.toBeNull()
    }
    expect(seatBlendFor('')).toBeNull()
    expect(seatBlendFor(null)).toBeNull()
    expect(seatBlendFor('nobody')).toBeNull()
  })

  it('seat blends are the authored archetype vectors (Mentor spot values)', () => {
    const mentor = seatBlendFor('mentor')!
    expect(mentor.self).toBeCloseTo(0.35, 10)
    expect(mentor.number).toBeCloseTo(0.3, 10)
    expect(mentor.word).toBeCloseTo(0.15, 10)
    expect(mentor.body).toBeCloseTo(0.02, 10)
  })

  it('no conversations ⇒ no conversation weights', () => {
    expect(conversationWeights(null)).toBeNull()
    expect(conversationWeights(undefined)).toBeNull()
    expect(conversationWeights({})).toBeNull()
    expect(conversationWeights({ mentor: 0 })).toBeNull()
    expect(conversationWeights({ nobody: 3 })).toBeNull()
  })

  it('zero conversations ⇒ stated weights pass through unchanged', () => {
    const stated = { word: 0.5, number: 0.5 }
    expect(effectiveStrandWeights(stated, null)).toEqual(stated)
    expect(effectiveStrandWeights(stated, {})).toEqual(stated)
    expect(effectiveStrandWeights(stated, { mentor: 0 })).toEqual(stated)
    expect(effectiveStrandWeights(null, null)).toBeNull()
    expect(effectiveStrandWeights(undefined, undefined)).toBeNull()
  })

  it('an exclusive conversation history is entirely that seat’s blend', () => {
    const one = conversationWeights({ mentor: 1 })!
    const five = conversationWeights({ mentor: 5 })!
    // Same colour at any exclusive count (compared per-strand: the
    // accumulation order makes exact float equality the wrong pin).
    for (const k of Object.keys(one) as (keyof typeof one)[]) {
      expect(five[k]).toBeCloseTo(one[k]!, 12)
    }
    expect(one.self).toBeCloseTo(0.35, 10)
    expect(one.number).toBeCloseTo(0.3, 10)
    expect(one.body).toBeCloseTo(0.02, 10)
    const sum = Object.values(one).reduce((a, b) => a + (b ?? 0), 0)
    expect(sum).toBeCloseTo(1, 10)
  })

  it('two seats mix proportionally to their conversation counts', () => {
    const even = conversationWeights({ mentor: 1, champion: 1 })!
    // self: (0.35 + 0.30) / 2 · body: (0.02 + 0.35) / 2 · word: (0.15 + 0.05) / 2
    expect(even.self).toBeCloseTo(0.325, 10)
    expect(even.body).toBeCloseTo(0.185, 10)
    expect(even.word).toBeCloseTo(0.1, 10)
    const weighted = conversationWeights({ mentor: 3, champion: 1 })!
    expect(weighted.self).toBeCloseTo((3 * 0.35 + 0.3) / 4, 10)
    expect(weighted.body).toBeCloseTo((3 * 0.02 + 0.35) / 4, 10)
  })

  it('conversations replace the stated vector entirely (the formula has no stated term)', () => {
    const eff = effectiveStrandWeights({ image: 1 }, { mentor: 1 })!
    expect(eff.image).toBeCloseTo(0.05, 10)
    expect(eff.self).toBeCloseTo(0.35, 10)
  })
})

/* ---------- keystone counts ---------- */

function keystoneTask(id: string, projectId: string, seat: string, status: string, deps: string[]): Task {
  return {
    id,
    project_id: projectId,
    parent_task_id: null,
    title: id,
    description: '',
    assignee_id: null,
    status,
    priority: '2',
    estimated_hours: 1,
    due_date: null,
    dependency_ids: deps,
    completion_criteria: '',
    notes: '',
    seat_ref: seat,
    created_at: NOW,
    updated_at: NOW,
  } as Task
}

function chain(seat: string, projectId: string, statuses: [string, string, string, string]): Task[] {
  const ids = [`${seat}-k1`, `${seat}-k2`, `${seat}-k3`, `${seat}-k4`]
  return ids.map((id, i) =>
    keystoneTask(id, projectId, seat, statuses[i]!, i === 0 ? [] : [ids[i - 1]!]),
  )
}

describe('keystone conversation counts', () => {
  it('K1 Done counts one conversation for the seat in its project', () => {
    const counts = keystoneConversationCountsByProject(chain('mentor', 'p-gardener', ['Done', 'Todo', 'Todo', 'Todo']))
    expect(counts.get('p-gardener')).toEqual({ mentor: 1 })
  })

  it('the chain is found by dependency depth, not array order', () => {
    const tasks = chain('mentor', 'p-gardener', ['Done', 'Todo', 'Todo', 'Todo'])
    const shuffled = [tasks[2]!, tasks[0]!, tasks[3]!, tasks[1]!]
    expect(keystoneConversationCountsByProject(shuffled).get('p-gardener')).toEqual({ mentor: 1 })
  })

  it('before the first meeting there is no count — later keystones alone do not colour', () => {
    const counts = keystoneConversationCountsByProject(chain('mentor', 'p-gardener', ['Todo', 'Done', 'Done', 'Done']))
    expect(counts.has('p-gardener')).toBe(false)
  })

  it('ordinary tasks (no seat_ref) never contribute', () => {
    const plain = keystoneTask('t-plain', 'p-other', '', 'Done', [])
    const counts = keystoneConversationCountsByProject([plain])
    expect(counts.size).toBe(0)
  })
})

/* ---------- (iii) keystone staining end-to-end through the projection ---------- */

function councilBundle(k1Status: string): VisionMapEntityBundle {
  const ideas: Idea[] = []
  const initiatives: Initiative[] = [
    {
      id: 'ini-council', source_idea_id: null, title: 'Meet your council', brief: '', status: 'Active',
      owner_id: null, evaluation_priority: 2, estimated_cost_ai: 'Medium', estimated_timeframe_ai: '4–6 weeks',
      philosophical_alignment_ai: 'Strong', next_step_ai: '', required_assets: [], dependencies: '',
      risks: '', recommendation: '', kill_criteria: '', notes: '', created_at: NOW, updated_at: NOW,
    } as unknown as Initiative,
  ]
  const project = (id: string, title: string): Project =>
    ({
      id, initiative_id: 'ini-council', title, brief: '', status: 'Active', owner_id: null,
      supporting_owner_ids: [], required_assets: [], priority: '2', start_date: null, end_date: null,
      estimated_weekly_hours: 4, next_step_ai: '', notes: '', created_at: NOW, updated_at: NOW,
    }) as Project
  const plainTask = (id: string, projectId: string, title: string): Task =>
    ({
      id, project_id: projectId, parent_task_id: null, title, description: '', assignee_id: null,
      status: 'Todo', priority: '2', estimated_hours: 2, due_date: null, dependency_ids: [],
      completion_criteria: '', notes: '', created_at: NOW, updated_at: NOW,
    }) as Task
  return {
    ideas,
    initiatives,
    projects: [project('p-gardener', 'Meet the Gardener'), project('p-plain', 'Ordinary project')],
    tasks: [
      ...chain('mentor', 'p-gardener', [k1Status, 'Todo', 'Todo', 'Todo']),
      plainTask('t-plain', 'p-plain', 'Ordinary task'),
    ],
  }
}

const payloadWeights = (g: ReturnType<typeof buildLiveVisionMapGraph>, nodeId: string) =>
  (g.nodes.find((n) => n.id === nodeId)?.data as { entity_strand_weights?: unknown })?.entity_strand_weights

describe('keystone met ⇒ seat blend; unmet ⇒ neutral', () => {
  it('met: branch + flower payloads carry the seat blend; the seat link is threaded', () => {
    const g = buildLiveVisionMapGraph(councilBundle('Done'), [], undefined, {})
    const branch = payloadWeights(g, 'branch-p-gardener') as Record<string, number>
    expect(branch).not.toBeNull()
    expect(branch.self).toBeCloseTo(0.35, 10)
    expect(branch.number).toBeCloseTo(0.3, 10)
    const flower = payloadWeights(g, 'flower-mentor-k1') as Record<string, number>
    expect(flower.self).toBeCloseTo(0.35, 10)
    const flowerData = g.nodes.find((n) => n.id === 'flower-mentor-k1')?.data as { seat_ref?: string }
    expect(flowerData.seat_ref).toBe('mentor')
  })

  it('met: the pile members inherit the blend and the pile tints with it', () => {
    const g = buildLiveVisionMapGraph(councilBundle('Done'), [], undefined, { cairnThreshold: 1 })
    const cairn = g.nodes.find((n) => (n.data as { cairnProjectId?: string }).cairnProjectId === 'p-gardener')
    expect(cairn).toBeTruthy()
    const ms = (cairn!.data as { cairnMembers?: CairnMemberInput[] }).cairnMembers ?? []
    expect(ms.length).toBe(5)
    for (const m of ms) {
      expect(m.weights, m.id).not.toBeNull()
      expect(m.weights!.self).toBeCloseTo(0.35, 10)
    }
    const layout = towerLayoutForMembers(cairn!.id, ms)
    const branchStone = layout.stones.find((s) => s.memberId === 'branch-p-gardener')!
    expectHexClose(branchStone.tint, blendStainHex(seatBlendFor('mentor')!)!, 16)
  })

  it('unmet: every keystone payload and member stays unweighed (neutral)', () => {
    const plain = buildLiveVisionMapGraph(councilBundle('Todo'), [], undefined, {})
    expect(payloadWeights(plain, 'branch-p-gardener')).toBeNull()
    expect(payloadWeights(plain, 'flower-mentor-k1')).toBeNull()
    const g = buildLiveVisionMapGraph(councilBundle('Todo'), [], undefined, { cairnThreshold: 1 })
    const cairn = g.nodes.find((n) => (n.data as { cairnProjectId?: string }).cairnProjectId === 'p-gardener')
    const ms = (cairn!.data as { cairnMembers?: CairnMemberInput[] }).cairnMembers ?? []
    for (const m of ms) expect(m.weights).toBeNull()
    const layout = towerLayoutForMembers(cairn!.id, ms)
    const branchStone = layout.stones.find((s) => s.memberId === 'branch-p-gardener')!
    expectHexClose(branchStone.tint, NEUTRAL, 16)
  })

  it('conversations in one project never leak into another project’s stated weights', () => {
    const g = buildLiveVisionMapGraph(councilBundle('Done'), [], undefined, {
      strandWeights: { 'project:p-plain': { image: 1 }, 'project:p-gardener': { image: 1 } },
    })
    // Ordinary project: no conversations ⇒ stated vector untouched.
    expect(payloadWeights(g, 'branch-p-plain')).toEqual({ image: 1 })
    // Keystone project: conversations exist ⇒ they determine the colour,
    // even over a stated vector.
    const gardener = payloadWeights(g, 'branch-p-gardener') as Record<string, number>
    expect(gardener.image).toBeCloseTo(0.05, 10)
    expect(gardener.self).toBeCloseTo(0.35, 10)
  })
})

/* ---------- (iv) + (v) painted singles ---------- */

function nodeFixture(id: string, data: Partial<MapNodePayload> & { kind: MapNodePayload['kind'] }): Node<MapNodePayload> {
  return {
    id,
    type: 'entityMap',
    position: { x: 0, y: 0 },
    data: {
      label: id,
      growth: 'growing',
      condition: 'healthy',
      ref: { veType: 'project', id: 'p-x' },
      summaryLines: [],
      water_level: 'low',
      fertilizer_pulse: false,
      ...data,
    } as MapNodePayload,
  } as Node<MapNodePayload>
}

describe('painted singles (paintedSingleStoneFor — the EntityMapNode paint decision)', () => {
  it('(iv) an unstacked tree paints: a column stone of its own, deterministic', () => {
    const tree = nodeFixture('tree-ini-1', {
      kind: 'tree',
      ref: { veType: 'initiative', id: 'ini-1' },
    })
    const stone = paintedSingleStoneFor(tree)
    expect(stone).not.toBeNull()
    expect(stone!.role).toBe('column')
    expect(stone!.memberId).toBe('tree-ini-1')
    expect(stone!.spriteUrl).toBeTruthy()
    // The tree carries no weights: its tint is the (jittered) neutral wash.
    expectHexClose(stone!.tint, NEUTRAL, 16)
    // Same node, same stone — member/cairn-id-keyed determinism.
    expect(paintedSingleStoneFor(tree)).toEqual(stone)
  })

  it('(v) a weighed branch single paints with its blend tint', () => {
    const branch = nodeFixture('branch-p-x', {
      kind: 'branch',
      ref: { veType: 'project', id: 'p-x' },
      entity_strand_weights: { image: 1 },
    })
    const stone = paintedSingleStoneFor(branch)
    expect(stone).not.toBeNull()
    expect(stone!.memberId).toBe('branch-p-x')
    expectHexClose(stone!.tint, '#b98d55', 16)
  })

  it('(v) a weighed flower single paints with its blend tint', () => {
    const flower = nodeFixture('flower-t-x', {
      kind: 'flower',
      ref: { veType: 'task', id: 't-x', projectId: 'p-x' },
      entity_strand_weights: { word: 1 },
    })
    const stone = paintedSingleStoneFor(flower)
    expect(stone).not.toBeNull()
    expectHexClose(stone!.tint, '#96604a', 16)
  })

  it('(v) an unweighed branch or flower single does not paint (symbolic oval preserved)', () => {
    const branch = nodeFixture('branch-p-x', { kind: 'branch', ref: { veType: 'project', id: 'p-x' } })
    expect(paintedSingleStoneFor(branch)).toBeNull()
    const flower = nodeFixture('flower-t-x', {
      kind: 'flower',
      ref: { veType: 'task', id: 't-x', projectId: 'p-x' },
      entity_strand_weights: null,
    })
    expect(paintedSingleStoneFor(flower)).toBeNull()
  })

  it('landmarks, seeds and fruit never paint as singles', () => {
    const landmark = nodeFixture('landmark-person-p1', {
      kind: 'landmark',
      ref: { veType: 'person', id: 'p1' },
      entity_strand_weights: { image: 1 },
    })
    expect(paintedSingleStoneFor(landmark)).toBeNull()
    const seed = nodeFixture('seed-i1', { kind: 'seed', ref: { veType: 'idea', id: 'i1' } })
    expect(paintedSingleStoneFor(seed)).toBeNull()
    const fruit = nodeFixture('fruit-proj-p1', {
      kind: 'fruit',
      ref: { veType: 'outcome', id: 'o1' },
      entity_strand_weights: { image: 1 },
    })
    expect(paintedSingleStoneFor(fruit)).toBeNull()
  })
})
