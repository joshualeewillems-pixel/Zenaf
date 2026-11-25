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
  applyWeighingFigures,
  attendingGuests,
  buildBuilding,
  buildCompound,
  buildFloor,
  buildRoom,
  buildWeighingDecision,
  composeBoundaryPanel,
  composeSubjectPending,
  composeSubjectThresholds,
  composeVesselHeld,
  councilFlameColors,
  growthOf,
  pendingActs,
  pendingEvidenceRefs,
  pendingSummaryLines,
  recordedCapacityFor,
  vesselPending,
  weighingBaseline,
  weighingChanges,
  weighingConsequences,
  weighingWithKeeper,
  type AttributedRead,
  type PalaceData,
  type WeighingFigures,
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

describe('boundaries panel composition', () => {
  it('composes only from records, dropping empty strands', () => {
    const model = composeBoundaryPanel({
      nonNegotiables: '  No work on Sundays. ',
      strandBoundaries: [
        { strandKey: 'hands', strandName: 'Hands', topics: ['pricing'] },
        { strandKey: 'heart', strandName: 'Heart', topics: [] },
      ],
      permissionGroups: [{ id: 'remember', state: 'ask_me' }],
    })
    expect(model.nonNegotiables).toContain('No work on Sundays.')
    expect(model.strandBoundaries).toHaveLength(1)
    expect(model.permissionGroups).toHaveLength(1)
    expect(model.hasAnyRecord).toBe(true)
  })

  it('says honestly when nothing is recorded', () => {
    const model = composeBoundaryPanel({
      nonNegotiables: '   ',
      strandBoundaries: [],
      permissionGroups: [],
    })
    expect(model.nonNegotiables).toBeNull()
    expect(model.hasAnyRecord).toBe(false)
  })
})

/* ------------------------------------------------------------------ */
/* the attributed read — Thresholds-1 / Kintsugi-1 / Guests-1          */
/* ------------------------------------------------------------------ */

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

  it('thresholds carry proposed and established, labelled apart', () => {
    const model = composeSubjectThresholds(READ)
    expect(model.hasSubjectMaterial).toBe(true)
    expect(model.proposed).toHaveLength(1)
    expect(model.proposed[0].author_name).toBe('Severine')
    expect(model.established).toHaveLength(1)
    expect(model.established[0].source).toBe('commitment')
    expect(composeSubjectThresholds(null).hasSubjectMaterial).toBe(false)
  })

  it('the vessel holds only CURRENT questions — history is not held open', () => {
    const held = composeVesselHeld(READ)
    expect(held.openQuestions).toEqual([
      { author: 'skeptic', text: 'Where does the weekend actually sit?' },
    ])
    expect(held.tensions).toEqual([
      { author: 'skeptic', text: 'Sundays keep colliding with deliveries' },
    ])
    expect(held.openReconsiderations).toEqual([
      { reading_id: 'r1', reason: 'The delivery facts changed.' },
    ])
    expect(held.hasMaterial).toBe(true)
  })

  it('the seam flag passes through untouched — and a gate-closed read holds nothing', () => {
    expect(composeVesselHeld(READ).restorationOfUnderstanding).toBe(true)
    const closed: AttributedRead = { ...READ, kintsugi: null }
    const held = composeVesselHeld(closed)
    expect(held.hasMaterial).toBe(false)
    expect(held.restorationOfUnderstanding).toBe(false)
  })

  it('the vessel names its accepted readings for the reconsideration ask', () => {
    // READ's kintsugi readings are proposed, not accepted: no ask.
    expect(composeVesselHeld(READ).acceptedReadings).toEqual([])
    const withAccepted: AttributedRead = {
      ...READ,
      kintsugi: {
        ...READ.kintsugi!,
        threads: READ.kintsugi!.threads.map((t) => ({
          ...t,
          readings: t.readings.map((r) =>
            r.reading_id === 'r1' ? { ...r, status: 'accepted' } : r,
          ),
        })),
      },
    }
    expect(composeVesselHeld(withAccepted).acceptedReadings).toEqual([
      {
        reading_id: 'r1',
        author: 'skeptic',
        label: 'Sundays keep colliding with deliveries',
      },
    ])
  })
})

describe('the verdict door composition (Slice 1)', () => {
  it('the threshold carries every pending kind; the vessel only readings and candidacies', () => {
    expect(composeSubjectPending(READ).map((i) => i.item_kind)).toEqual([
      'reading',
      'reconsideration',
      'birth',
    ])
    expect(vesselPending(READ).map((i) => i.item_kind)).toEqual(['reading', 'reconsideration'])
    expect(composeSubjectPending(null)).toEqual([])
    expect(composeSubjectPending({ ...READ, resolved: false })).toEqual([])
  })

  it('acts follow the routes: endorse is reading-only, explore rides three kinds', () => {
    const [reading, candidacy, birth] = composeSubjectPending(READ)
    expect(pendingActs(reading)).toEqual({ endorse: true, explore: true })
    expect(pendingActs(candidacy)).toEqual({ endorse: false, explore: false })
    expect(pendingActs(birth)).toEqual({ endorse: false, explore: false })
  })

  it('evidence refs are read as recorded — rows, strings, and nothing invented', () => {
    const [reading, candidacy] = composeSubjectPending(READ)
    expect(pendingEvidenceRefs(reading)).toEqual(['event:evt-1'])
    expect(pendingEvidenceRefs(candidacy)).toEqual([])
    expect(pendingSummaryLines(reading)).toEqual(['A newer tension, awaiting a word'])
    expect(pendingSummaryLines(candidacy)).toEqual(['The delivery facts changed.'])
  })
})

/* ------------------------------------------------------------------ */
/* Scales-1 — the weighing                                             */
/*                                                                     */
/* The fixture body for the weighing describes: Jo (capacity 20)     */
/* keeps the anchor floor PA (Active, 6h, Sam supporting); Sam       */
/* (capacity 10) also keeps PB (Ready, 8h) — so as recorded Sam is   */
/* committed 14h against 10h and stands over. Two heavy projects in  */
/* non-counting statuses (In Progress, Done) and a null-estimate     */
/* project test the derivation's edges; PE is owned AND supported    */
/* by Jo, to be counted once.                                        */
/* ------------------------------------------------------------------ */

const SAM: Person = {
  id: 'per2',
  name: 'Sam Support',
  role: '',
  notes: '',
  created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
} as Person

const NOPROFILE: Person = {
  id: 'per3',
  name: 'Noor Unprofiled',
  role: '',
  notes: '',
  created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
} as Person

const SAM_PROFILE: CapacityProfile = {
  person_id: 'per2',
  weekly_capacity_hours: 10,
  created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
}

const PA = project({ id: 'pa', title: 'Anchor floor', owner_id: 'per1', supporting_owner_ids: ['per2'], estimated_weekly_hours: 6 })
const PB = project({ id: 'pb', title: 'Sam’s own floor', status: 'Ready', owner_id: 'per2', estimated_weekly_hours: 8 })
const PC = project({ id: 'pc', title: 'Under way', status: 'In Progress', owner_id: 'per1', estimated_weekly_hours: 40 })
const PD = project({ id: 'pd', title: 'Finished', status: 'Done', owner_id: 'per1', estimated_weekly_hours: 40 })
const PE = project({ id: 'pe', title: 'Owned and supported', owner_id: 'per1', supporting_owner_ids: ['per1'], estimated_weekly_hours: 3 })
const PF = project({ id: 'pf', title: 'Noor’s floor', owner_id: 'per3', estimated_weekly_hours: 5 })
const PG = project({ id: 'pg', title: 'Unestimated', owner_id: 'per1', estimated_weekly_hours: null })

const WA = task({ id: 'wa', project_id: 'pa', title: 'Weighed room', estimated_hours: 4, assignee_id: 'per2' })
const WB = task({ id: 'wb', project_id: 'pa', title: 'Unweighed room', estimated_hours: null })

const WDATA: PalaceData = {
  ideas: [],
  initiatives: [I1],
  projects: [PA, PB, PC, PD, PE, PF, PG],
  tasks: [WA, WB],
  persons: [PERSON, SAM, NOPROFILE],
  assets: [],
  capacityProfiles: [PROFILE, SAM_PROFILE],
}

function pictureFor(
  consequences: ReturnType<typeof weighingConsequences>,
  personId: string,
): { recorded: (typeof consequences)[number]['recorded']; arranged: (typeof consequences)[number]['arranged'] } {
  const row = consequences.find((c) => c.arranged.personId === personId)
  expect(row, `no consequence for ${personId}`).toBeDefined()
  return row!
}

describe('Scales-1 — the weighing baseline', () => {
  it('starts from recorded figures only; only recorded figures are adjustable', () => {
    const floorBase = weighingBaseline(WDATA, PA, null)
    expect(floorBase.figures).toEqual({ projectHours: 6, taskHours: null, keeperId: 'per1', keeperCapacity: 20 })
    expect(floorBase.adjustable).toEqual({ projectHours: true, taskHours: false, keeper: true, keeperCapacity: true })

    const roomBase = weighingBaseline(WDATA, PA, WA)
    expect(roomBase.figures.taskHours).toBe(4)
    expect(roomBase.adjustable.taskHours).toBe(true)

    const unweighed = weighingBaseline(WDATA, PA, WB)
    expect(unweighed.figures.taskHours).toBeNull()
    expect(unweighed.adjustable.taskHours).toBe(false)
  })

  it('a floor with nothing recorded exposes nothing to adjust', () => {
    const bare = weighingBaseline(WDATA, P2, null) // owner null, hours null
    expect(bare.figures).toEqual({ projectHours: null, taskHours: null, keeperId: null, keeperCapacity: null })
    expect(bare.adjustable).toEqual({ projectHours: false, taskHours: false, keeper: false, keeperCapacity: false })
  })

  it('a keeper with no recorded capacity has none to adjust', () => {
    const base = weighingBaseline(WDATA, PF, null)
    expect(base.figures.keeperId).toBe('per3')
    expect(base.figures.keeperCapacity).toBeNull()
    expect(base.adjustable.keeper).toBe(true)
    expect(base.adjustable.keeperCapacity).toBe(false)
    expect(recordedCapacityFor(WDATA, 'per3')).toBeNull()
    expect(recordedCapacityFor(WDATA, null)).toBeNull()
  })

  it('re-seating the keeper re-bases the capacity figure to the new keeper’s record', () => {
    const base = weighingBaseline(WDATA, PA, null)
    const toSam = weighingWithKeeper(WDATA, base.figures, 'per2')
    expect(toSam.keeperId).toBe('per2')
    expect(toSam.keeperCapacity).toBe(10)
    const toNoor = weighingWithKeeper(WDATA, base.figures, 'per3')
    expect(toNoor.keeperCapacity).toBeNull()
  })
})

describe('Scales-1 — the derivation mirror (derived.py add_capacity_derived)', () => {
  it('counts Ready/Active only, owner-or-supporter once, null estimates as 0', () => {
    const base = weighingBaseline(WDATA, PA, null)
    const consequences = weighingConsequences(WDATA, base, base.figures)
    // Jo: PA 6 + PE 3 (owned AND supported — once) = 9; PC/PD excluded by
    // status; PG's null counts 0. Against capacity 20: within.
    const jo = pictureFor(consequences, 'per1')
    expect(jo.recorded.committedHours).toBe(9)
    expect(jo.recorded.capacityHours).toBe(20)
    expect(jo.recorded.capacityDelta).toBe(-11)
    expect(jo.recorded.over).toBe(false)
    // Sam: PA 6 (supporting) + PB 8 (owner) = 14 against 10: over by 4.
    const sam = pictureFor(consequences, 'per2')
    expect(sam.recorded.committedHours).toBe(14)
    expect(sam.recorded.capacityDelta).toBe(4)
    expect(sam.recorded.over).toBe(true)
  })

  it('rounds as the backend rounds — and judges over on the UNROUNDED difference', () => {
    // 10.04 committed against capacity 10: activeWeeklyHours reads
    // 10.0 and capacityDelta reads 0.0, yet overcapacity is TRUE,
    // because derived.py tests the unrounded difference.
    const edge = project({ id: 'edge', status: 'Active', owner_id: 'per1', estimated_weekly_hours: 10.04 })
    const edgeData: PalaceData = {
      ...WDATA,
      projects: [edge],
      capacityProfiles: [{ ...PROFILE, weekly_capacity_hours: 10 }],
    }
    const base = weighingBaseline(edgeData, edge, null)
    const jo = pictureFor(weighingConsequences(edgeData, base, base.figures), 'per1')
    expect(jo.recorded.committedHours).toBe(10)
    expect(jo.recorded.capacityDelta).toBe(0)
    expect(jo.recorded.over).toBe(true)
  })

  it('makes no judgement where no capacity is recorded', () => {
    const base = weighingBaseline(WDATA, PF, null)
    const noor = pictureFor(weighingConsequences(WDATA, base, base.figures), 'per3')
    expect(noor.recorded.committedHours).toBe(5)
    expect(noor.recorded.capacityHours).toBeNull()
    expect(noor.recorded.capacityDelta).toBeNull()
    expect(noor.recorded.over).toBe(false)
  })

  it('a loose task has no capacity consequences — task estimates are not weekly commitments', () => {
    const loose = task({ id: 'lt2', project_id: null, title: 'Loose', estimated_hours: 3 })
    const base = weighingBaseline(WDATA, null, loose)
    expect(weighingConsequences(WDATA, base, base.figures)).toEqual([])
  })
})

describe('Scales-1 — exploration', () => {
  it('moves the derived balance without touching the record', () => {
    const base = weighingBaseline(WDATA, PA, null)
    const figures: WeighingFigures = { ...base.figures, projectHours: 30 }
    const arrangedProjects = applyWeighingFigures(WDATA, base, figures).projects
    expect(arrangedProjects.find((p) => p.id === 'pa')?.estimated_weekly_hours).toBe(30)
    // The record itself is untouched — exploration is pure.
    expect(WDATA.projects.find((p) => p.id === 'pa')?.estimated_weekly_hours).toBe(6)
    expect(PA.estimated_weekly_hours).toBe(6)

    const consequences = weighingConsequences(WDATA, base, figures)
    const jo = pictureFor(consequences, 'per1')
    expect(jo.arranged.committedHours).toBe(33) // 30 + PE 3
    expect(jo.arranged.over).toBe(true)
    expect(jo.recorded.committedHours).toBe(9)
    const sam = pictureFor(consequences, 'per2')
    expect(sam.arranged.committedHours).toBe(38) // 30 supporting + PB 8
  })

  it('re-seating the keeper moves the commitment between keepers', () => {
    const base = weighingBaseline(WDATA, PA, null)
    const figures = weighingWithKeeper(WDATA, base.figures, 'per2')
    const consequences = weighingConsequences(WDATA, base, figures)
    const jo = pictureFor(consequences, 'per1')
    expect(jo.arranged.committedHours).toBe(3) // only PE remains hers
    const sam = pictureFor(consequences, 'per2')
    // PA counts ONCE for Sam (owner now, and still a supporter) + PB 8.
    expect(sam.arranged.committedHours).toBe(14)
    expect(sam.arranged.capacityHours).toBe(10)
  })
})

describe('Scales-1 — establishment', () => {
  it('an unchanged arrangement settles nothing', () => {
    const base = weighingBaseline(WDATA, PA, WA)
    const changes = weighingChanges(WDATA, base, base.figures)
    expect(changes).toEqual({ projectPatch: null, taskPatch: null, capacityPut: null, changed: false })
  })

  it('writes exactly the settled figures, each through its own route shape', () => {
    const base = weighingBaseline(WDATA, PA, WA)
    const figures: WeighingFigures = { projectHours: 12, taskHours: 9, keeperId: 'per1', keeperCapacity: 20 }
    const changes = weighingChanges(WDATA, base, figures)
    expect(changes.projectPatch).toEqual({ estimated_weekly_hours: 12 })
    expect(changes.taskPatch).toEqual({ estimated_hours: 9 })
    expect(changes.capacityPut).toBeNull()
    expect(changes.changed).toBe(true)
  })

  it('re-seating alone never rewrites capacity; adjusting the new keeper’s does', () => {
    const base = weighingBaseline(WDATA, PA, null)
    const reseated = weighingWithKeeper(WDATA, base.figures, 'per2')
    const onlyReseat = weighingChanges(WDATA, base, reseated)
    expect(onlyReseat.projectPatch).toEqual({ owner_id: 'per2' })
    expect(onlyReseat.capacityPut).toBeNull()

    const adjusted = weighingChanges(WDATA, base, { ...reseated, keeperCapacity: 16 })
    expect(adjusted.capacityPut).toEqual({ person_id: 'per2', weekly_capacity_hours: 16 })
  })

  it('the decision carries the weighing’s provenance in the existing shape', () => {
    const base = weighingBaseline(WDATA, PA, null)
    const figures: WeighingFigures = { ...base.figures, projectHours: 30 }
    const changes = weighingChanges(WDATA, base, figures)
    const decision = buildWeighingDecision(WDATA, base, figures, changes)
    expect(decision).not.toBeNull()
    expect(decision!.entity_type).toBe('project')
    expect(decision!.entity_id).toBe('pa')
    expect(decision!.decision_type).toBe('scales_weighing')
    const proposal = decision!.ai_proposal_snapshot as {
      explored: Record<string, unknown>
      recorded_before: Record<string, unknown>
      consequences: { person_id: string; overcapacity: boolean }[]
    }
    expect(proposal.explored.project_weekly_hours).toBe(30)
    expect(proposal.recorded_before.project_weekly_hours).toBe(6)
    expect(proposal.consequences.find((c) => c.person_id === 'per2')?.overcapacity).toBe(true)
    const final = decision!.final_values_snapshot as {
      settled: Record<string, unknown>
      recorded_before: Record<string, unknown>
    }
    expect(final.settled.project_weekly_hours).toBe(30)
    expect(final.recorded_before.project_weekly_hours).toBe(6)
    // No who/when is invented client-side: the route stamps the
    // decision row's owner and created_at.
    expect(JSON.stringify(decision)).not.toContain('user_id')
    expect(JSON.stringify(decision)).not.toContain('created_at')
  })

  it('a room-only weighing keys its decision to the room', () => {
    const base = weighingBaseline(WDATA, PA, WA)
    const figures: WeighingFigures = { ...base.figures, taskHours: 9 }
    const changes = weighingChanges(WDATA, base, figures)
    const decision = buildWeighingDecision(WDATA, base, figures, changes)
    expect(decision!.entity_type).toBe('task')
    expect(decision!.entity_id).toBe('wa')
    const proposal = decision!.ai_proposal_snapshot as { explored: Record<string, unknown> }
    expect(proposal.explored.task_estimated_hours).toBe(9)
  })
})
