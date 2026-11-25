/**
 * Bench derivations — the definitions doc's hard rules as tests:
 * foliage ONLY from discussion evidence (§7), wire ONLY from a
 * recorded pending proposal (§2), registers per §0b, footing per §4,
 * jin for dropped material (§5), strand weight per §9, and the
 * shelf's true kinds (§0).
 */
import { describe, it, expect } from 'vitest'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import { padStyleFor, seatTint, TINTS } from './growth'
import {
  buildInitiativeTree,
  buildProjectTree,
  buildShelf,
  discussionForTask,
  footingFor,
  geometryRegisterFor,
  strandWeightForTask,
  verdictLogEntry,
  type BenchEntities,
  type BenchProposal,
} from './benchLogic'

function task(partial: Partial<Task> & { id: string }): Task {
  return {
    project_id: 'p1',
    parent_task_id: null,
    title: partial.id,
    description: '',
    assignee_id: null,
    status: 'Todo',
    priority: '',
    estimated_hours: null,
    due_date: null,
    dependency_ids: [],
    completion_criteria: '',
    notes: '',
    created_at: '2026-05-01T00:00:00',
    updated_at: '2026-05-01T00:00:00',
    seat_ref: '',
    origin_seat: null,
    origin_conversation_id: null,
    origin_message_id: null,
    responsible_seat: null,
    ...partial,
  }
}

function project(partial: Partial<Project> & { id: string }): Project {
  return {
    initiative_id: null,
    title: partial.id,
    brief: '',
    status: 'Active',
    owner_id: null,
    supporting_owner_ids: [],
    priority: '',
    start_date: null,
    end_date: null,
    estimated_weekly_hours: null,
    next_step_ai: '',
    notes: '',
    created_at: '2026-05-01T00:00:00',
    updated_at: '2026-05-01T00:00:00',
    ...partial,
  }
}

const DISCUSSED = task({
  id: 't-discussed',
  title: 'Order timber',
  origin_seat: 'guardian',
  origin_conversation_id: 'talk-123',
  origin_message_id: 'm-9',
})
const PLAIN = task({ id: 't-plain', title: 'Confirm bookings' })
const KEYSTONE_ONLY = task({
  id: 't-keystone',
  title: 'First meeting',
  seat_ref: 'guardian',
})
const STEWARDED = task({ id: 't-stewarded', title: 'Stewarded', responsible_seat: 'guardian' })
const DROPPED = task({ id: 't-dropped', title: 'Old reading', status: 'Dropped' })

const ENTITIES: BenchEntities = {
  ideas: [],
  initiatives: [],
  projects: [project({ id: 'p1', title: 'Winter client season' })],
  tasks: [DISCUSSED, PLAIN, KEYSTONE_ONLY, STEWARDED, DROPPED],
}

const PROPOSAL: BenchProposal = {
  id: 'prop-1',
  seat: 'champion',
  title: 'Book the scaffolding early',
  parent_task_id: 't-plain',
  state: 'pending',
  notes: '',
  evidence_quote: 'the yard gets busy in November',
  conversation_id: 'talk-77',
  created_at: '2026-05-02T00:00:00',
}

describe('foliage evidence (§7)', () => {
  it('origin provenance with a recorded conversation is discussion evidence', () => {
    expect(discussionForTask(DISCUSSED)).toEqual({
      seatId: 'guardian',
      seatName: 'Maeve',
      conversationId: 'talk-123',
    })
  })
  it('seat_ref (keystone ownership) is NOT discussion evidence', () => {
    expect(discussionForTask(KEYSTONE_ONLY)).toBeNull()
  })
  it('responsible_seat (assigned stewardship) is NOT discussion evidence', () => {
    expect(discussionForTask(STEWARDED)).toBeNull()
  })
  it('an origin seat without its conversation is NOT evidence', () => {
    expect(discussionForTask(task({ id: 'x', origin_seat: 'guardian' }))).toBeNull()
  })
  it("Severine's own origin never foliates her tree (she is the examiner)", () => {
    expect(
      discussionForTask(task({ id: 'x', origin_seat: 'skeptic', origin_conversation_id: 'talk-1' })),
    ).toBeNull()
  })
  it('in the built tree, foliage hangs ONLY on the evidenced twig', () => {
    const tree = buildProjectTree(ENTITIES.projects[0], ENTITIES, new Map())
    expect([...tree.discussion.keys()]).toEqual(['t-discussed'])
    expect(tree.discussion.get('t-discussed')).toEqual(['Maeve'])
    // and the pad style gate agrees: style for the discussed twig,
    // none for any other
    for (const twig of tree.twigs) {
      const pads = tree.grown.padsByHandle.get(twig.id) ?? []
      for (const pad of pads) {
        const style = padStyleFor(pad, tree.elementsByHandle, tree.discussion)
        if (twig.id === 't-discussed') expect(style).not.toBeNull()
        else expect(style).toBeNull()
      }
    }
  })
})

describe('wire (§2)', () => {
  it('a pending recorded proposal makes the twig wire, in the proposer’s colour path', () => {
    const tree = buildProjectTree(
      ENTITIES.projects[0],
      ENTITIES,
      new Map([['t-plain', [PROPOSAL]]]),
    )
    const twig = tree.twigs.find((t) => t.id === 't-plain')!
    expect(twig.geometryRegister).toBe('wire')
    expect(twig.proposals).toEqual([PROPOSAL])
  })
  it('without a proposal record there is no wire — never by default', () => {
    const tree = buildProjectTree(ENTITIES.projects[0], ENTITIES, new Map())
    for (const t of tree.twigs) expect(t.geometryRegister).not.toBe('wire')
    for (const b of tree.branches) expect(b.geometryRegister).not.toBe('wire')
    expect(geometryRegisterFor('Todo', false).register).toBe('pencil')
    expect(geometryRegisterFor('Done', false).register).toBe('ink')
    expect(geometryRegisterFor('In Progress', false).register).toBe('ink')
  })
})

describe('registers (§0b)', () => {
  it('a project with VE structure is wood; a bare shell project is sumi', () => {
    const withTasks = buildProjectTree(ENTITIES.projects[0], ENTITIES, new Map())
    expect(withTasks.register).toBe('wood')
    const bare = buildProjectTree(
      project({ id: 'bare', title: 'Tax paperwork' }),
      { ...ENTITIES, tasks: [] },
      new Map(),
    )
    expect(bare.register).toBe('sumi')
  })
  it('the shelf keeps true kinds — never flattened to projects', () => {
    const idea: Idea = {
      id: 'idea-1', title: 'Take on an apprentice', summary: '', description: '',
      status: 'Captured', tags: [], created_by: 'user',
      created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const ini: Initiative = {
      id: 'ini-1', source_idea_id: null, title: 'Rebuild the workshop', brief: 'b',
      status: 'Active', owner_id: null, evaluation_priority: null, estimated_cost_ai: '',
      estimated_timeframe_ai: '', philosophical_alignment_ai: '', next_step_ai: '',
      required_assets: [], dependencies: '', risks: '', recommendation: '',
      kill_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const loose = task({ id: 'loose-1', title: 'Fix the gate latch', project_id: null })
    const shelf = buildShelf({
      ideas: [idea],
      initiatives: [ini],
      projects: [project({ id: 'p9', title: 'Depot refit' })],
      tasks: [loose],
    })
    expect(shelf.map((s) => s.kindLabel)).toEqual(['Initiative', 'Project', 'Idea', 'Task'])
    // a checklist-only idea with no origin edge is Steward terrain
    expect(shelf.find((s) => s.id === 'idea-1')!.register).toBe('sumi')
    // a loose task is Steward terrain
    expect(shelf.find((s) => s.id === 'loose-1')!.register).toBe('sumi')
  })
  it('the shelf holds parents + loose only — an initiative-owned project stands as a branch, not a root', () => {
    const ini: Initiative = {
      id: 'ini-1', source_idea_id: null, title: 'Rebuild the workshop', brief: 'b',
      status: 'Active', owner_id: null, evaluation_priority: null, estimated_cost_ai: '',
      estimated_timeframe_ai: '', philosophical_alignment_ai: '', next_step_ai: '',
      required_assets: [], dependencies: '', risks: '', recommendation: '',
      kill_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const entities: BenchEntities = {
      ideas: [],
      initiatives: [ini],
      projects: [
        project({ id: 'p-owned', title: 'Depot refit', initiative_id: 'ini-1' }),
        project({ id: 'p-loose', title: 'Gate latch' }),
        project({ id: 'p-dangling', title: 'Orphan refit', initiative_id: 'gone' }),
      ],
      tasks: [],
    }
    const shelf = buildShelf(entities)
    // The owned project is NOT a shelf root; the loose and the
    // dangling-initiative projects are.
    expect(shelf.map((s) => s.id)).toEqual(['ini-1', 'p-loose', 'p-dangling'])
    // Reachability: the owned project stands as a branch of its
    // initiative's tree, marked as a project branch.
    const tree = buildInitiativeTree(ini, entities, new Map())
    const branch = tree.branches.find((b) => b.id === 'p-owned')
    expect(branch).toBeTruthy()
    expect(branch!.sourceKind).toBe('project')
  })
})

describe('footing (§4)', () => {
  it('verbatim-linked evidence is documented footing', () => {
    expect(footingFor({ proseChars: 300, hasVerbatim: true }).kind).toBe('documented')
  })
  it('prose without a verbatim link is reported footing', () => {
    expect(footingFor({ proseChars: 300, hasVerbatim: false }).kind).toBe('reported')
  })
  it('an empty record is assumed — and grows no triangle (scale 0)', () => {
    const f = footingFor({ proseChars: 0, hasVerbatim: false })
    expect(f.kind).toBe('assumed')
    expect(f.proseScale).toBe(0)
  })
  it('the built tree over the discussed project stands documented', () => {
    const tree = buildProjectTree(ENTITIES.projects[0], ENTITIES, new Map())
    expect(tree.footing.kind).toBe('documented')
    expect(tree.notebook.some((e) => e.kind === 'Documented' && e.title.includes('Maeve'))).toBe(true)
  })
})

describe('jin (§5) and strand weight (§9)', () => {
  it('a dropped twig is jin; standing twigs are not', () => {
    const tree = buildProjectTree(ENTITIES.projects[0], ENTITIES, new Map())
    expect(tree.twigs.find((t) => t.id === 't-dropped')!.jin).toBe(true)
    expect(tree.twigs.find((t) => t.id === 't-plain')!.jin).toBe(false)
  })
  it('weight reads the record: numeric priority scales, Done floors at 8', () => {
    expect(strandWeightForTask(task({ id: 'a', priority: '3' }), 0).weight).toBe(6)
    expect(strandWeightForTask(task({ id: 'b', status: 'Done' }), 0).weight).toBe(8)
    expect(strandWeightForTask(task({ id: 'c', priority: 'High' }), 0).weight).toBe(8)
    const w = strandWeightForTask(task({ id: 'd' }), 0)
    expect(w.weight).toBe(4)
    expect(w.rule).toContain('dealing weight 4')
  })
})

describe('corrected grammar (founder, 2026-11-24): tree = initiative, branches = projects, twigs = tasks', () => {
  const ini: Initiative = {
    id: 'ini-1', source_idea_id: null, title: 'Rebuild the workshop', brief: 'b',
    status: 'Active', owner_id: null, evaluation_priority: null, estimated_cost_ai: '',
    estimated_timeframe_ai: '', philosophical_alignment_ai: '', next_step_ai: '',
    required_assets: [], dependencies: '', risks: '', recommendation: '',
    kill_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
  }
  const entities: BenchEntities = {
    ideas: [],
    initiatives: [ini],
    projects: [
      project({ id: 'p-a', title: 'Depot refit', initiative_id: 'ini-1' }),
      project({ id: 'p-b', title: 'Yard works', initiative_id: 'ini-1' }),
    ],
    tasks: [
      task({ id: 'ta-1', project_id: 'p-a', title: 'Survey the depot' }),
      task({ id: 'ta-2', project_id: 'p-a', title: 'Order steel' }),
      task({ id: 'ta-sub', project_id: 'p-a', parent_task_id: 'ta-1', title: 'Measure twice' }),
      task({ id: 'tb-1', project_id: 'p-b', title: 'Clear the yard' }),
    ],
  }

  it('the initiative tree: branches are exactly its projects', () => {
    const tree = buildInitiativeTree(ini, entities, new Map())
    expect(tree.branches.map((b) => b.id)).toEqual(['p-a', 'p-b'])
    expect(tree.branches.every((b) => b.sourceKind === 'project')).toBe(true)
  })

  it('tasks are twigs off their project’s branch; subtasks are not twigs', () => {
    const tree = buildInitiativeTree(ini, entities, new Map())
    expect(tree.twigs.map((t) => t.id)).toEqual(['ta-1', 'ta-2', 'tb-1'])
    expect(tree.twigs.find((t) => t.id === 'ta-1')!.parentId).toBe('p-a')
    expect(tree.twigs.find((t) => t.id === 'tb-1')!.parentId).toBe('p-b')
    // the subtask is carried as its parent twig's nested count
    expect(tree.twigs.find((t) => t.id === 'ta-1')!.subtaskCount).toBe(1)
    // every twig has grown geometry, rooted ON its branch's primary
    const distToSeg = (
      p: [number, number],
      a: [number, number],
      b: [number, number],
    ) => {
      const dx = b[0] - a[0]
      const dy = b[1] - a[1]
      const L2 = dx * dx + dy * dy || 1
      const s = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
      return Math.hypot(p[0] - (a[0] + dx * s), p[1] - (a[1] + dy * s))
    }
    for (const t of tree.twigs) {
      const rec = tree.grown.recordTwigs.find((r) => r.handle === t.id)
      expect(rec).toBeTruthy()
      expect(rec!.parentHandle).toBe(t.parentId)
      const primary = tree.grown.primaries.get(t.parentId!)!
      let best = Infinity
      for (let i = 0; i < primary.length - 1; i++) {
        best = Math.min(
          best,
          distToSeg(
            rec!.pts[0] as [number, number],
            primary[i] as [number, number],
            primary[i + 1] as [number, number],
          ),
        )
      }
      expect(best).toBeLessThan(1e-9)
    }
  })

  it('twig geometry is subordinate: generation-2 wood, shorter than its branch', () => {
    const tree = buildInitiativeTree(ini, entities, new Map())
    const pathLen = (pts: Array<[number, number]>) =>
      pts.reduce((n, p, i) => (i === 0 ? 0 : n + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1])), 0)
    for (const t of tree.twigs) {
      const rec = tree.grown.recordTwigs.find((r) => r.handle === t.id)!
      const branchLen = pathLen(tree.grown.primaries.get(t.parentId!)! as Array<[number, number]>)
      expect(pathLen(rec.pts as Array<[number, number]>)).toBeLessThan(branchLen)
      const wood = tree.grown.wood.filter((w) => w.handle === t.id)
      expect(wood.length).toBeGreaterThan(0)
      expect(wood.every((w) => w.gen === 2)).toBe(true)
      expect(wood[0].wRoot).toBe(1.15)
    }
  })

  it('a project standing as its own tree carries its tasks as trunk twigs — no branches', () => {
    const tree = buildProjectTree(entities.projects[0], entities, new Map())
    expect(tree.branches).toEqual([])
    expect(tree.twigs.map((t) => t.id)).toEqual(['ta-1', 'ta-2'])
    expect(tree.twigs.every((t) => t.parentId === null)).toBe(true)
    for (const t of tree.twigs) {
      expect(tree.grown.recordTwigs.find((r) => r.handle === t.id)).toBeTruthy()
    }
  })

  it('wire on an initiative tree hangs on the twig, not the branch', () => {
    const prop: BenchProposal = { ...PROPOSAL, parent_task_id: 'ta-2' }
    const tree = buildInitiativeTree(ini, entities, new Map([['ta-2', [prop]]]))
    expect(tree.twigs.find((t) => t.id === 'ta-2')!.geometryRegister).toBe('wire')
    expect(tree.branches.find((b) => b.id === 'p-a')!.geometryRegister).not.toBe('wire')
  })
})

describe('Gate 0 — the accepted prototype’s foliage records, as twigs', () => {
  // The prototype's two foliage records are TASKS: B1-T2 "Order
  // timber" and B2-T2 "Rewire the bench sockets", each discussed
  // with Maeve ({seat: "Maeve"}). Under the corrected grammar they
  // stand as twigs on their projects' branches — and their foliage
  // must still render, in Maeve's colour, on the twigs.
  const ini: Initiative = {
    id: 'ini-b', source_idea_id: null, title: 'Workshop season', brief: '',
    status: 'Active', owner_id: null, evaluation_priority: null, estimated_cost_ai: '',
    estimated_timeframe_ai: '', philosophical_alignment_ai: '', next_step_ai: '',
    required_assets: [], dependencies: '', risks: '', recommendation: '',
    kill_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
  }
  const entities: BenchEntities = {
    ideas: [],
    initiatives: [ini],
    projects: [
      project({ id: 'B1', title: 'Winter client season', initiative_id: 'ini-b' }),
      project({ id: 'B2', title: 'Workshop refit', initiative_id: 'ini-b' }),
    ],
    tasks: [
      task({ id: 'B1-T1', project_id: 'B1', title: 'Confirm Saturday bookings', status: 'In Progress' }),
      task({
        id: 'B1-T2', project_id: 'B1', title: 'Order timber',
        origin_seat: 'guardian', origin_conversation_id: 'talk-b1', origin_message_id: 'm-1',
      }),
      task({ id: 'B2-T1', project_id: 'B2', title: 'Strip the old benches' }),
      task({
        id: 'B2-T2', project_id: 'B2', title: 'Rewire the bench sockets', status: 'Parked',
        origin_seat: 'guardian', origin_conversation_id: 'talk-b2', origin_message_id: 'm-2',
      }),
    ],
  }

  it('B1-T2 and B2-T2 stand as twigs on their projects’ branches', () => {
    const tree = buildInitiativeTree(ini, entities, new Map())
    expect(tree.branches.map((b) => b.id)).toEqual(['B1', 'B2'])
    expect(tree.twigs.find((t) => t.id === 'B1-T2')!.parentId).toBe('B1')
    expect(tree.twigs.find((t) => t.id === 'B2-T2')!.parentId).toBe('B2')
    expect(tree.grown.recordTwigs.map((r) => r.handle)).toEqual(
      expect.arrayContaining(['B1-T2', 'B2-T2']),
    )
  })

  it('their foliage renders in Maeve’s colour — on the twigs, nowhere else', () => {
    const tree = buildInitiativeTree(ini, entities, new Map())
    expect([...tree.discussion.entries()].sort()).toEqual([
      ['B1-T2', ['Maeve']],
      ['B2-T2', ['Maeve']],
    ])
    const [maevelPetal, maeveCentre] = seatTint(TINTS[1][0], TINTS[1][1], 'Maeve')
    for (const id of ['B1-T2', 'B2-T2']) {
      const pads = tree.grown.padsByHandle.get(id) ?? []
      expect(pads.length).toBeGreaterThan(0)
      for (const pad of pads) {
        const style = padStyleFor(pad, tree.elementsByHandle, tree.discussion)
        expect(style).not.toBeNull()
        expect(style!.tints).toEqual([[maevelPetal, maeveCentre]])
      }
    }
    // siblings and branches carry no foliage style at all
    for (const id of ['B1-T1', 'B2-T1', 'B1', 'B2']) {
      const pads = tree.grown.padsByHandle.get(id) ?? []
      for (const pad of pads) {
        expect(padStyleFor(pad, tree.elementsByHandle, tree.discussion)).toBeNull()
      }
    }
  })

  it('the same records foliate as trunk twigs when B1 stands as its own tree', () => {
    const tree = buildProjectTree(entities.projects[0], entities, new Map())
    const twig = tree.twigs.find((t) => t.id === 'B1-T2')!
    expect(twig.parentId).toBeNull()
    expect(twig.discussion?.seatName).toBe('Maeve')
    const pads = tree.grown.padsByHandle.get('B1-T2') ?? []
    expect(pads.length).toBeGreaterThan(0)
    expect(padStyleFor(pads[0], tree.elementsByHandle, tree.discussion)).not.toBeNull()
  })
})

describe('verdict log (§11)', () => {
  it('entries name the ruling, the proposal, the branch and the tree', () => {
    const entry = verdictLogEntry({
      proposal: PROPOSAL,
      branchName: 'Confirm bookings',
      rootTitle: 'Winter client season',
      kind: 'stand',
      when: '9:41 AM, this session',
    })
    expect(entry.text).toBe(
      'Let stand — “Book the scaffolding early” on “Confirm bookings” (Winter client season)',
    )
    expect(entry.kind).toBe('stand')
  })
})
