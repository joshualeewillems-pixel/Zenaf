/**
 * The Living Palace — model gates.
 *
 * Pins the ruled discipline against a fixture body of work: the
 * hierarchy lands where the compound grammar puts it (initiatives
 * as buildings, floors as projects, rooms as tasks; loose work on
 * the grounds; undeveloped ideas on the drawing table); the display
 * rule holds (nested by default, un-nest available); furniture is
 * EARNED (a dependency makes the window, recorded figures make the
 * floor scales, recorded words fill the chest) and the affordance
 * instruments stand unpopulated (empty room scales by construction,
 * the Kintsugi vessel plain in this VE-only model — its gold is
 * earned by the attributed read's accepted-supersession lineage and
 * applied by the view, pinned in the read's own describe below).
 */
import { describe, expect, it } from 'vitest'
import type {
  CapacityProfile,
  Idea,
  Initiative,
  Person,
  Project,
  Task,
} from '../vision-execution/types'
import { SEAT_COLORS } from '../council/colors'
import {
  attendingGuests,
  buildBuilding,
  buildCompound,
  buildFloor,
  buildRoom,
  councilFlameColors,
  growthOf,
  type AttributedRead,
  type PalaceData,
} from './palaceLogic'

const PERSON: Person = {
  id: 'per1',
  name: 'Jo Keeper',
  role: '',
  notes: '',
  created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
} as Person

const PROFILE: CapacityProfile = {
  person_id: 'per1',
  weekly_capacity_hours: 20,
  created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
}

function initiative(partial: Partial<Initiative>): Initiative {
  return {
    id: 'i1',
    source_idea_id: null,
    title: 'Rebuild the workshop business',
    brief: '',
    status: 'Active',
    owner_id: null,
    priority: '',
    target_date: null,
    notes: '',
    next_step_ai: '',
    created_at: '2026-05-01T00:00:00',
    updated_at: '2026-05-01T00:00:00',
    ...partial,
  } as Initiative
}

function project(partial: Partial<Project>): Project {
  return {
    id: 'p1',
    initiative_id: 'i1',
    title: 'Winter client season',
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
  } as Project
}

function task(partial: Partial<Task>): Task {
  return {
    id: 't1',
    project_id: 'p1',
    parent_task_id: null,
    title: 'Task',
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
  } as Task
}

function idea(partial: Partial<Idea>): Idea {
  return {
    id: 'id1',
    title: 'Take on an apprentice',
    summary: '',
    description: '',
    status: 'New',
    tags: [],
    created_by: '',
    created_at: '2026-05-01T00:00:00',
    updated_at: '2026-05-01T00:00:00',
    ...partial,
  } as Idea
}

const I1 = initiative({})
const P1 = project({ id: 'p1', title: 'Winter client season', owner_id: 'per1', estimated_weekly_hours: 6 })
const P2 = project({ id: 'p2', title: 'Spring commissions' })
const LP = project({ id: 'lp', initiative_id: null, title: 'Loose project' })
const RP = project({ id: 'rp', initiative_id: null, title: 'Old sideline', status: 'Dropped' })

const TA = task({ id: 'ta', title: 'Alpha', notes: 'The yard confirmed Tuesday.' })
const TB = task({ id: 'tb', title: 'Beta', status: 'In Progress' })
const TC = task({ id: 'tc', title: 'Gamma', dependency_ids: ['tb'] })
const TD = task({ id: 'td', title: 'Delta', status: 'Done', dependency_ids: ['ta'] })
const TE = task({ id: 'te', title: 'Alpha detail', parent_task_id: 'ta' })
const TF = task({ id: 'tf', project_id: 'p2', title: 'Convergent', dependency_ids: ['ta', 'tb'], assignee_id: 'per1' })
const TG = task({ id: 'tg', project_id: 'p2', title: 'Waits on convergent', dependency_ids: ['tf'] })
const LT = task({ id: 'lt', project_id: null, title: 'Standalone errand' })

const DATA: PalaceData = {
  ideas: [idea({}), idea({ id: 'id2', title: 'Graduated notion', status: 'Graduated' })],
  initiatives: [I1],
  projects: [P1, P2, LP, RP],
  tasks: [TA, TB, TC, TD, TE, TF, TG, LT],
  persons: [PERSON],
  assets: [],
  capacityProfiles: [PROFILE],
}

describe('the fire', () => {
  it('burns in the seven council colours, from the canonical palette', () => {
    const colors = councilFlameColors()
    expect(colors).toHaveLength(7)
    expect(new Set(colors).size).toBe(7)
    expect(colors).toEqual([
      SEAT_COLORS.mentor,
      SEAT_COLORS.champion,
      SEAT_COLORS.guardian,
      SEAT_COLORS.maverick,
      SEAT_COLORS.ambassador,
      SEAT_COLORS.conductor,
      SEAT_COLORS.skeptic,
    ])
    // The prototype's geometry: the centre (tallest) tongue is the
    // fourth — Jynx's violet; Maeve's bronze stands just left of it.
    expect(colors[3]).toBe(SEAT_COLORS.maverick)
    expect(colors[2]).toBe('#ac7c5b')
  })
})

describe('growth readings', () => {
  it('grows only on recorded status', () => {
    expect(growthOf('In Progress')).toBe('growing')
    expect(growthOf('Done')).toBe('fruiting')
    expect(growthOf('Todo')).toBeNull()
    expect(growthOf('Blocked')).toBeNull()
    expect(growthOf('Parked')).toBeNull()
  })
})

describe('compound', () => {
  it('places the hierarchy: buildings, loose structures, grounds tasks, the table', () => {
    const model = buildCompound(DATA, { unnested: false })
    expect(model.buildings.map((b) => b.initiative.id)).toEqual(['i1'])
    expect(model.buildings[0].floors.map((p) => p.id).sort()).toEqual(['p1', 'p2'])
    // Every task under the initiative counts as a room, subtasks included.
    expect(model.buildings[0].roomCount).toBe(7)
    expect(model.looseProjects.map((p) => p.id)).toEqual(['lp'])
    expect(model.releasedProjects.map((p) => p.id)).toEqual(['rp'])
    expect(model.looseTasks.map((t) => t.id)).toEqual(['lt'])
    // Only the undeveloped idea rests on the drawing table.
    expect(model.ideas.map((i) => i.id)).toEqual(['id1'])
  })

  it('nests by default and un-nests on request', () => {
    expect(buildCompound(DATA, { unnested: false }).standingProjects).toEqual([])
    const unnested = buildCompound(DATA, { unnested: true })
    expect(unnested.standingProjects.map((p) => p.id).sort()).toEqual(['p1', 'p2'])
    // The buildings stand either way — un-nesting ADDS the standing
    // projects; it never dissolves the parents.
    expect(unnested.buildings).toHaveLength(1)
  })

  it('stands a house of forty rooms in pagoda tiers', () => {
    const many = Array.from({ length: 41 }, (_, i) =>
      task({ id: `m${i}`, title: `Room ${i}` }),
    )
    const model = buildCompound({ ...DATA, tasks: many }, { unnested: false })
    expect(model.buildings[0].form).toBe('pagoda')
    expect(buildCompound(DATA, { unnested: false }).buildings[0].form).toBe('building')
  })
})

describe('building', () => {
  it('floors are the initiative projects, top floor first', () => {
    const model = buildBuilding(DATA, I1)
    expect(model.floors.map((f) => f.project.id)).toEqual(['p2', 'p1'])
  })

  it('the balcony plant is earned by the floor’s own rooms', () => {
    const model = buildBuilding(DATA, I1)
    const p1 = model.floors.find((f) => f.project.id === 'p1')!
    // P1 holds a Done room (Delta) — the balcony plant fruits.
    expect(p1.plant).toBe('fruiting')
    const p2 = model.floors.find((f) => f.project.id === 'p2')!
    // P2's rooms are all Todo — the ledge stays bare.
    expect(p2.plant).toBeNull()
  })
})

describe('floor', () => {
  it('nests subtasks inside their room by default; un-nest stands them as rooms', () => {
    const nested = buildFloor(DATA, P1, { unnested: false })
    expect(nested.rooms.map((r) => r.task.id).sort()).toEqual(['ta', 'tb', 'tc', 'td'])
    expect(nested.rooms.find((r) => r.task.id === 'ta')!.subtaskCount).toBe(1)
    const unnested = buildFloor(DATA, P1, { unnested: true })
    expect(unnested.rooms.map((r) => r.task.id).sort()).toEqual(['ta', 'tb', 'tc', 'td', 'te'])
  })

  it('pierces a labelled doorway only where a recorded edge joins adjacent rooms of a column', () => {
    const model = buildFloor(DATA, P1, { unnested: false })
    // Sorted rooms: Alpha (col 0, row 0), Beta (col 1, row 0),
    // Delta (col 0, row 1), Gamma (col 1, row 1). Delta→Alpha and
    // Gamma→Beta are same-column adjacent pairs — both pierce.
    const pairs = model.doorways.map((d) => [d.aId, d.bId].sort().join('-')).sort()
    expect(pairs).toEqual(['ta-td', 'tb-tc'])
  })

  it('names edges that leave the floor instead of drawing them', () => {
    const model = buildFloor(DATA, P2, { unnested: false })
    // Convergent's two dependencies live on P1's floor — named as
    // cross edges, never drawn as doorways here.
    expect(model.crossEdges.map((e) => e.other.id).sort()).toEqual(['ta', 'tb'])
    expect(model.doorways).toEqual([])
    // But "Waits on convergent" → Convergent joins two rooms of THIS
    // floor, so the mosaic is earned even here.
    expect(model.mosaic).toBe(true)
  })

  it('earns its hall furniture from the rooms’ records', () => {
    const p1 = buildFloor(DATA, P1, { unnested: false })
    expect(p1.cabinets).toBe(true) // Alpha holds recorded notes
    expect(p1.mosaic).toBe(true) // recorded edges join rooms of this floor
    const p2 = buildFloor(DATA, P2, { unnested: false })
    expect(p2.cabinets).toBe(false)
  })

  it('floor scales stand only on recorded figures', () => {
    const p1 = buildFloor(DATA, P1, { unnested: false })
    expect(p1.scalesFigures).toEqual({ projectHours: 6, capacityHours: 20, ownerName: 'Jo Keeper' })
    const p2 = buildFloor(DATA, P2, { unnested: false })
    expect(p2.scalesFigures).toBeNull()
  })
})

describe('room', () => {
  it('the window reads the waited-on rooms’ recorded states', () => {
    // Gamma waits on Beta (In Progress — unfinished): a wall being built.
    expect(buildRoom(DATA, TC).windowState).toBe('building')
    // Delta waits on Alpha (Todo — unfinished): still building.
    expect(buildRoom(DATA, TD).windowState).toBe('building')
    // A room waiting only on finished work sees a completed wall.
    const done = task({ id: 'tx', title: 'After', dependency_ids: ['td'] })
    expect(buildRoom({ ...DATA, tasks: [...DATA.tasks, done] }, done).windowState).toBe('complete')
    // Nothing waited on: no window reading at all.
    expect(buildRoom(DATA, TA).windowState).toBeNull()
    expect(buildRoom(DATA, TA).waitsOn).toEqual([])
  })

  it('the mandala is earned at two recorded edges, not fewer', () => {
    expect(buildRoom(DATA, TF).convergence).toBe(3) // waits on two, waited on by one
    expect(buildRoom(DATA, TF).mandala).toBe(true)
    expect(buildRoom(DATA, TC).mandala).toBe(false)
  })

  it('the chest holds only recorded words; the vessel stands plain', () => {
    const alpha = buildRoom(DATA, TA)
    expect(alpha.held?.notes).toContain('yard confirmed')
    expect(buildRoom(DATA, TB).held).toBeNull()
    // No endpoint serves repair material to the frontend: the vessel
    // is an affordance everywhere in this increment, never gold.
    expect(alpha.vesselGold).toBe(false)
    expect(buildRoom(DATA, TF).vesselGold).toBe(false)
  })

  it('the gathering table seats recorded people only', () => {
    expect(buildRoom(DATA, TF).people.map((p) => p.name)).toEqual(['Jo Keeper'])
    // Beta records no one: its places stand empty (the view renders
    // the affordance; the model invents no company).
    const beta = buildRoom(DATA, TB)
    expect(beta.people.map((p) => p.id)).toEqual(['per1']) // P1's recorded keeper
    const loose = buildRoom(DATA, LT)
    expect(loose.people).toEqual([])
    expect(loose.project).toBeNull()
  })

  it('chambers are the room’s own subtasks', () => {
    expect(buildRoom(DATA, TA).subtasks.map((t) => t.id)).toEqual(['te'])
    expect(buildRoom(DATA, TB).subtasks).toEqual([])
  })
})


const READ: AttributedRead = {
  resolved: true,
  subject: { entity_type: 'task', entity_id: 'tc', title: 'Gamma' },
  steward_gate_open: true,
  boundaries: {
    expressed: [],
    proposed: [
      {
        thread_id: 'th1',
        thread_title: 'The boundary thread',
        reading_id: 'r1',
        author: 'skeptic',
        author_name: 'Severine',
        status: 'proposed',
        placement: 'current',
        currency_labels: [],
        tensions: ['Sundays keep colliding with deliveries'],
        open_questions: ['Where does the weekend actually sit?'],
      },
    ],
    established: [
      { source: 'commitment', text: 'No Sunday deliveries, ever.', status: 'open', created_at: '2026-11-01T00:00:00Z' },
    ],
    enforceable: {
      permission_home_enabled: false,
      permission_consent_given: false,
      steward_derivation: true,
      steward_coordination: true,
    },
  },
  kintsugi: {
    threads: [
      {
        thread_id: 'th1',
        thread_title: 'The boundary thread',
        readings: [
          {
            reading_id: 'r1',
            author: 'skeptic',
            status: 'proposed',
            placement: 'current',
            currency_labels: [],
            tensions: ['Sundays keep colliding with deliveries'],
            open_questions: ['Where does the weekend actually sit?'],
          },
          {
            reading_id: 'r0',
            author: 'skeptic',
            status: 'proposed',
            placement: 'history',
            currency_labels: ['superseded'],
            tensions: ['A displaced tension is history, not held open'],
            open_questions: [],
          },
        ],
        reconsiderations: [{ reading_id: 'r1', status: 'proposed', reason: 'The delivery facts changed.' }],
      },
    ],
    restoration_of_understanding: true,
  },
  guests: {
    attending: [
      { seat: 'guardian', seat_name: 'Maeve', via: ['reading'] },
      { seat: 'ambassador', seat_name: 'Lucian', via: ['reading'] },
      { seat: 'champion', seat_name: 'Valen', via: ['conversation'] },
    ],
  },
  pending: [
    {
      item_id: 'reading:r2',
      item_kind: 'reading',
      thread_id: 'th1',
      surface: 'queue_card',
      status: 'proposed',
      title: 'The boundary thread',
      payload: {
        reading: { tensions: ['A newer tension, awaiting a word'], open_questions: [] },
        evidence_refs: [{ kind: 'event', ref_id: 'evt-1' }],
        currency: { placement: 'current', labels: ['emerging'] },
      },
    },
    {
      item_id: 'reconsideration:rcn1',
      item_kind: 'reconsideration',
      thread_id: 'th1',
      surface: 'queue_card',
      status: 'proposed',
      title: 'The boundary thread',
      payload: { reading_id: 'r1', reason: 'The delivery facts changed.' },
    },
    {
      item_id: 'birth:th9',
      item_kind: 'birth',
      thread_id: 'th9',
      surface: 'queue_card',
      status: 'nascent',
      title: 'A proposed thread',
      payload: { scope: '', origin: 'steward_proposal', strand_weights: {} },
    },
  ],
}
describe('attributed read composition', () => {
  it('guests exclude the host and keep their attribution', () => {
    const guests = attendingGuests(READ)
    expect(guests.map((g) => g.seat)).toEqual(['ambassador', 'champion'])
    expect(guests[0].via).toEqual(['reading'])
    expect(attendingGuests(null)).toEqual([])
    expect(attendingGuests({ ...READ, resolved: false })).toEqual([])
  })
})
