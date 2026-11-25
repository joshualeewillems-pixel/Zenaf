/**
 * Severine's Bench — derivations from the user's real Vision
 * Execution records. Every visual fact on the Bench is derived here
 * from the record, with the rule stated beside it (the Campaign
 * Board's honesty pattern): nothing is drawn from a hash, a default,
 * or an invention.
 *
 * The governing definitions are
 * zenaf-bench-feature-visual-language-definitions-2026-11-21.md:
 * §0 the Shelf, §0b registers (VE-attached → wood; Steward terrain →
 * sumi ink), §2 wire, §4 footing, §5 jin, §7 foliage, §9 strand
 * weight.
 */
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import {
  growTree,
  type BenchElement,
  type BenchTwigSpec,
  type GeometryRegister,
  type GrownTree,
} from './growth'

/* ------------------------------------------------------------------ */
/* Seats                                                               */
/* ------------------------------------------------------------------ */

/** Archetype id -> the seat's name. Severine (skeptic) is the
 *  examiner: her colour is deliberately absent from the foliage
 *  palette (growth.SEAT_COLOURS), and discussion with her alone
 *  never foliates a branch (§7). */
export const SEAT_NAME_BY_ARCHETYPE: Record<string, string> = {
  mentor: 'Rumi',
  champion: 'Valen',
  guardian: 'Maeve',
  ambassador: 'Lucian',
  conductor: 'Aria',
  skeptic: 'Severine',
  maverick: 'Jynx',
}

export const SEAT_COLOUR_BY_ARCHETYPE: Record<string, string> = {
  mentor: '#92b692',
  champion: '#e24e4e',
  guardian: '#ac7c5b',
  ambassador: '#5c9cea',
  conductor: '#8892c3',
  maverick: '#a55cce',
}

/* ------------------------------------------------------------------ */
/* Proposals (wire)                                                    */
/* ------------------------------------------------------------------ */

/** A recorded task proposal (GET /vision-execution/task-proposals).
 *  §2: wire IS a recorded proposal awaiting a verdict — never a
 *  merely spoken suggestion. The proposing seat is the record's own
 *  `seat` (the archetype whose conversation produced it, verified
 *  server-side by C1 provenance when the proposal was recorded). */
export interface BenchProposal {
  id: string
  seat: string
  title: string
  parent_task_id: string | null
  state: string
  notes: string
  evidence_quote: string
  conversation_id: string
  created_at: string
}

/* ------------------------------------------------------------------ */
/* Foliage evidence (§7)                                               */
/* ------------------------------------------------------------------ */

export interface DiscussionEvidence {
  seatId: string
  seatName: string
  conversationId: string
}

/**
 * The one product record that evidences cross-seat discussion of a
 * task: its origin provenance. A task created by approving a seat's
 * proposal carries `origin_seat` (the proposing seat) and
 * `origin_conversation_id` (the recorded conversation the proposal
 * was discussed in, with a verbatim evidence quote kept on the
 * proposal row). That is a discussion of this very item with that
 * seat, in the record — so the task's twig foliates in that seat's
 * colour. `seat_ref` is NOT used: it is keystone ownership, not
 * discussion. `responsible_seat` is NOT used: it is user-assigned
 * stewardship, not discussion. Severine's own colour never foliates
 * her tree (she is the examiner).
 */
export function discussionForTask(task: Task): DiscussionEvidence | null {
  const seat = (task.origin_seat ?? '').trim()
  const conversationId = (task.origin_conversation_id ?? '').trim()
  if (!seat || !conversationId) return null
  if (seat === 'skeptic') return null
  const seatName = SEAT_NAME_BY_ARCHETYPE[seat]
  if (!seatName) return null
  return { seatId: seat, seatName, conversationId }
}

/* ------------------------------------------------------------------ */
/* Reading foliage (§7, the second source)                             */
/* ------------------------------------------------------------------ */

/** Foliage evidence from steward readings, as the backend serves
 *  it (GET /vision-execution/bench-foliage/by-parent/{type}/{id}):
 *  task id -> the archetype ids whose steward readings touch that
 *  task, under the pencil layer's gates. The endpoint is
 *  fail-closed — a closed gate or absent consent arrives here as
 *  simply no map entries, indistinguishable from no readings,
 *  which is the honest rendering either way: bare. */
export type FoliageByTask = ReadonlyMap<string, readonly string[]>

export const NO_FOLIAGE: FoliageByTask = new Map()

/** One seat's foliage on one task, with the source that evidences
 *  it. The two sources render as ONE foliage (§7) — the pads do
 *  not distinguish them — but the inspection keeps them distinct:
 *  provenance is the discussion the task came out of; a reading
 *  is a steward interpretation in that seat's voice naming the
 *  task in its evidence. */
export interface FoliageSeat {
  seatId: string
  seatName: string
  source: 'provenance' | 'reading'
}

/**
 * The merged §7 foliage for one task: origin provenance first
 * (it is the discussion the task came out of), then the seats
 * whose steward readings touch it. A seat named by both sources
 * is still one seat's foliage. Severine never appears: the
 * endpoint excludes her and discussionForTask already does —
 * the guard here keeps the rule local to the merge as well.
 */
export function foliageSeatsForTask(
  task: Task,
  foliage: FoliageByTask,
): FoliageSeat[] {
  const out: FoliageSeat[] = []
  const seen = new Set<string>()
  const provenance = discussionForTask(task)
  if (provenance) {
    out.push({
      seatId: provenance.seatId,
      seatName: provenance.seatName,
      source: 'provenance',
    })
    seen.add(provenance.seatId)
  }
  for (const seatId of foliage.get(task.id) ?? []) {
    if (seen.has(seatId) || seatId === 'skeptic') continue
    const seatName = SEAT_NAME_BY_ARCHETYPE[seatId]
    if (!seatName) continue
    out.push({ seatId, seatName, source: 'reading' })
    seen.add(seatId)
  }
  return out
}

/* ------------------------------------------------------------------ */
/* Strand weight (§9)                                                  */
/* ------------------------------------------------------------------ */

export function strandWeightForTask(
  task: Task,
  subtaskCount: number,
): { weight: number; rule: string } {
  const p = (task.priority ?? '').trim()
  let weight: number
  let rule: string
  const numeric = /^[1-5]$/.test(p) ? Number(p) : null
  if (numeric !== null) {
    weight = numeric * 2
    rule = `priority ${p} on the record, on the 1–10 dial`
  } else if (/^high$/i.test(p)) {
    weight = 8
    rule = 'priority High on the record, on the 1–10 dial'
  } else if (/^medium$/i.test(p)) {
    weight = 5
    rule = 'priority Medium on the record, on the 1–10 dial'
  } else if (/^low$/i.test(p)) {
    weight = 3
    rule = 'priority Low on the record, on the 1–10 dial'
  } else {
    weight = 4
    rule = 'no priority on the record — the dealing weight 4'
    if (subtaskCount > 0) weight += 1
    if ((task.estimated_hours ?? 0) >= 20) weight += 2
    else if ((task.estimated_hours ?? 0) >= 8) weight += 1
    if (subtaskCount > 0 || (task.estimated_hours ?? 0) >= 8) {
      rule = 'no priority on the record — weight from recorded substance (nested tasks, estimated hours)'
    }
  }
  if (task.status === 'Done') weight = Math.max(weight, 8)
  else if (task.status === 'In Progress') weight = Math.max(weight, 6)
  return { weight: Math.max(2, Math.min(10, weight)), rule }
}

/* ------------------------------------------------------------------ */
/* Branches                                                            */
/* ------------------------------------------------------------------ */

export interface BenchBranch {
  id: string
  name: string
  state: string
  /** The record this branch is: a project under an initiative, or
   *  the root itself for a branchless root. (Tasks are never
   *  branches under the corrected grammar — they are twigs.) */
  sourceKind: 'task' | 'project' | 'root'
  task: Task | null
  subtaskCount: number
  /** §5: a dropped reading stays visible as pale deadwood. */
  jin: boolean
  weight: number
  weightRule: string
  geometryRegister: GeometryRegister
  geometryRule: string
  /** §7 foliage evidence, or null — null means bare, honestly.
   *  Provenance lives on tasks, so on project branches this is
   *  always null: foliage renders on twigs, never on branches. */
  discussion: DiscussionEvidence | null
  /** §7 foliage, both sources merged (provenance first, then
   *  steward-reading seats) — empty means bare, honestly. On
   *  project branches this is always empty: foliage renders on
   *  twigs, never on branches. */
  foliageSeats: FoliageSeat[]
  /** §2 wire: pending recorded proposals attached under this branch. */
  proposals: BenchProposal[]
  element: BenchElement
}

/**
 * A twig — the corrected grammar's third level (founder,
 * 2026-11-24): a TASK, branching off its project's branch (or off
 * the trunk when its project stands as its own tree). Everything
 * the language attaches to a task record attaches here: wire from
 * a pending proposal on the task, jin from its Dropped state, and
 * §7 foliage from its origin provenance — provenance lives on
 * tasks, so this is the only level that foliates.
 */
export interface BenchTwig {
  id: string
  name: string
  state: string
  task: Task
  /** The project branch this twig grows from, or null when it
   *  grows from the trunk (its project is the tree's root). */
  parentId: string | null
  subtaskCount: number
  /** §5: a dropped record stays visible as pale deadwood. */
  jin: boolean
  weight: number
  weightRule: string
  geometryRegister: GeometryRegister
  geometryRule: string
  /** §7 foliage evidence, or null — null means bare, honestly. */
  discussion: DiscussionEvidence | null
  /** §7 foliage, both sources merged (provenance first, then
   *  steward-reading seats) — empty means bare, honestly. */
  foliageSeats: FoliageSeat[]
  /** §2 wire: pending recorded proposals attached under this task. */
  proposals: BenchProposal[]
  spec: BenchTwigSpec
}

const DONE_LIKE = new Set(['Done', 'In Progress'])

/** Geometry register per branch — the artifact dealing, which is the
 *  growth grammar's own per-element register: wire where a recorded
 *  proposal hangs on the branch, ink for done / in-hand work, pencil
 *  for work not yet taken up. */
export function geometryRegisterFor(
  state: string,
  hasProposal: boolean,
): { register: GeometryRegister; rule: string } {
  if (hasProposal)
    return { register: 'wire', rule: 'a recorded proposal hangs on this branch (§2)' }
  if (DONE_LIKE.has(state))
    return { register: 'ink', rule: 'done or in hand in the record — established growth' }
  return { register: 'pencil', rule: 'not yet taken up in the record — provisional growth' }
}

/**
 * Deal branches into growth elements: the dealing the equivalence
 * harness proves against the Python machinery. Sides alternate in
 * record order starting left; stations spread evenly per side;
 * elevation and length come from the strand weight; nested records
 * lengthen the branch they hang under.
 */
export function dealElements(
  branches: Array<{
    id: string
    geometryRegister: GeometryRegister
    weight: number
    subtaskCount: number
  }>,
): Map<string, BenchElement> {
  const bySide = new Map<number, number>()
  const counts = new Map<number, number>()
  branches.forEach((b, i) => {
    const side = i % 2 === 0 ? -1 : 1
    bySide.set(i, side)
    counts.set(side, (counts.get(side) ?? 0) + 1)
  })
  const seen = new Map<number, number>()
  const out = new Map<string, BenchElement>()
  branches.forEach((b, i) => {
    const side = (bySide.get(i) ?? -1) as 1 | -1
    const m = counts.get(side) ?? 1
    const j = seen.get(side) ?? 0
    seen.set(side, j + 1)
    const tGrow = m === 1 ? 0.5 : 0.16 + 0.72 * (j / (m - 1))
    out.set(b.id, {
      handle: b.id,
      register: b.geometryRegister,
      side,
      tGrow,
      elev: 16 + b.weight * 2.2,
      lenOld: 46 + b.weight * 15 + Math.min(30, b.subtaskCount * 6),
      sprite: 1,
    })
  })
  return out
}

/**
 * Deal twigs into growth specs: twigs on one parent spread along
 * the parent's length (a lone twig sits just past the middle);
 * forks alternate sides in record order, as the grammar's children
 * alternate. A twig's dealt length is subordinate to a branch's by
 * construction — the branch deal is 46 + weight * 15; the twig deal
 * is 30 + weight * 5, with nested subtasks adding mass, capped —
 * and grow() at generation 2 thins it further. Subtasks are NOT
 * dealt their own geometry: the grammar's generations end at 2 and
 * its terminal fans are anonymous, so a subtask count lengthens
 * its task's twig and is named in the twig's inspection, never
 * drawn as a record it is not.
 */
export function dealTwigSpecs(
  twigs: Array<{
    id: string
    parentId: string | null
    geometryRegister: GeometryRegister
    weight: number
    subtaskCount: number
  }>,
): Map<string, BenchTwigSpec> {
  const groups = new Map<string | null, typeof twigs>()
  for (const t of twigs) {
    const g = groups.get(t.parentId) ?? []
    g.push(t)
    groups.set(t.parentId, g)
  }
  const out = new Map<string, BenchTwigSpec>()
  for (const [parentId, group] of groups) {
    const m = group.length
    group.forEach((t, j) => {
      const station =
        parentId === null
          ? m === 1
            ? 0.5
            : 0.18 + 0.64 * (j / (m - 1))
          : m === 1
            ? 0.55
            : 0.3 + 0.55 * (j / (m - 1))
      out.set(t.id, {
        handle: t.id,
        parentHandle: parentId,
        register: t.geometryRegister,
        station,
        fork: j % 2 === 0 ? 1 : -1,
        lenOld: 30 + t.weight * 5 + Math.min(18, t.subtaskCount * 4),
        sprite: 1,
      })
    })
  }
  return out
}

/* ------------------------------------------------------------------ */
/* Tree register (§0b)                                                 */
/* ------------------------------------------------------------------ */

export type BenchRegister = 'wood' | 'sumi'
export type RootKind = 'initiative' | 'project' | 'idea' | 'task'

export function treeRegisterFor(
  rootKind: RootKind,
  attached: boolean,
): { register: BenchRegister; rule: string } {
  if (attached)
    return {
      register: 'wood',
      rule: 'attached to Vision Execution structure — the wood register (§0b)',
    }
  return {
    register: 'sumi',
    rule: 'no Vision Execution structure attached — Steward terrain, the sumi register (§0b)',
  }
}

/* ------------------------------------------------------------------ */
/* Footing (§4)                                                        */
/* ------------------------------------------------------------------ */

export type FootingKind = 'documented' | 'reported' | 'assumed'

export interface Footing {
  kind: FootingKind
  proseChars: number
  /** 0..1 — the triangle's size within its small limit (§4). */
  proseScale: number
  rule: string
}

/**
 * Footing kind from the record's own evidence: documented when a
 * verbatim-linked record stands under the tree (a branch whose
 * origin provenance names the recorded conversation it came from);
 * reported when the record carries the user's own prose but no
 * verbatim link; assumed when the record is a name and a state only.
 */
export function footingFor(args: {
  proseChars: number
  hasVerbatim: boolean
}): Footing {
  const { proseChars, hasVerbatim } = args
  const proseScale = Math.max(0.15, Math.min(1, proseChars / 1200))
  if (hasVerbatim)
    return {
      kind: 'documented',
      proseChars,
      proseScale,
      rule: 'a verbatim-linked record stands under this tree (origin provenance to a recorded conversation)',
    }
  if (proseChars > 0)
    return {
      kind: 'reported',
      proseChars,
      proseScale,
      rule: "the record carries the user's own prose and no verbatim link — as you've told it",
    }
  return {
    kind: 'assumed',
    proseChars,
    proseScale: 0,
    rule: 'the record cites nothing beneath this tree — no triangle stands under it',
  }
}

/* ------------------------------------------------------------------ */
/* Notebook (§4 / §11)                                                 */
/* ------------------------------------------------------------------ */

export interface NotebookEntry {
  kind: 'Documented' | "As you've told it" | 'Record'
  title: string
  body: string
  custody: string
  date: string
}

/* ------------------------------------------------------------------ */
/* The tree model                                                      */
/* ------------------------------------------------------------------ */

export interface BenchTreeModel {
  rootId: string
  rootKind: RootKind
  title: string
  state: string
  register: BenchRegister
  registerRule: string
  branches: BenchBranch[]
  /** The tree's twigs — its tasks (corrected grammar, 2026-11-24). */
  twigs: BenchTwig[]
  crosses: Array<[string, string]>
  grown: GrownTree
  /** handle -> discussing seat names (growth.padStyleFor input).
   *  Keys are TWIG handles for task discussions (provenance lives
   *  on tasks), plus the root branch of a loose-task tree, whose
   *  root IS the task. Project branches never appear here. */
  discussion: Map<string, string[]>
  elementsByHandle: Map<string, BenchElement>
  footing: Footing
  notebook: NotebookEntry[]
}

export interface BenchEntities {
  ideas: Idea[]
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
}

function proseOf(...fields: Array<string | null | undefined>): number {
  return fields.reduce((n, f) => n + (f ? f.trim().length : 0), 0)
}

function buildTree(args: {
  rootId: string
  rootKind: RootKind
  title: string
  state: string
  attached: boolean
  branchDrafts: Array<{
    id: string
    name: string
    state: string
    sourceKind: BenchBranch['sourceKind']
    task: Task | null
    subtaskCount: number
    proposals: BenchProposal[]
  }>
  twigDrafts?: Array<{
    id: string
    name: string
    state: string
    task: Task
    parentId: string | null
    subtaskCount: number
    proposals: BenchProposal[]
  }>
  crosses: Array<[string, string]>
  rootProse: number
  hasVerbatim: boolean
  notebook: NotebookEntry[]
  /** §7 reading foliage for this tree's tasks, when the Bench
   *  has fetched it for the opened root. Absent (the shelf, or a
   *  failed/closed read) renders provenance foliage only. */
  foliage?: FoliageByTask
}): BenchTreeModel {
  const { register, rule: registerRule } = treeRegisterFor(args.rootKind, args.attached)
  const drafts = args.branchDrafts.map((d) => {
    const { weight, rule: weightRule } = d.task
      ? strandWeightForTask(d.task, d.subtaskCount)
      : { weight: Math.max(2, Math.min(10, 2 + d.subtaskCount)), rule: 'weight from the records nested under it' }
    const { register: geometryRegister, rule: geometryRule } = geometryRegisterFor(
      d.state,
      d.proposals.length > 0,
    )
    return { ...d, weight, weightRule, geometryRegister, geometryRule }
  })
  const elements = dealElements(drafts)
  const branches: BenchBranch[] = drafts.map((d) => ({
    id: d.id,
    name: d.name,
    state: d.state,
    sourceKind: d.sourceKind,
    task: d.task,
    subtaskCount: d.subtaskCount,
    jin: d.state === 'Dropped',
    weight: d.weight,
    weightRule: d.weightRule,
    geometryRegister: d.geometryRegister,
    geometryRule: d.geometryRule,
    discussion: d.task ? discussionForTask(d.task) : null,
    foliageSeats: d.task ? foliageSeatsForTask(d.task, args.foliage ?? NO_FOLIAGE) : [],
    proposals: d.proposals,
    element: elements.get(d.id)!,
  }))
  const twigDrafts = (args.twigDrafts ?? []).map((d) => {
    const { weight, rule: weightRule } = strandWeightForTask(d.task, d.subtaskCount)
    const { register: geometryRegister, rule: geometryRule } = geometryRegisterFor(
      d.state,
      d.proposals.length > 0,
    )
    return { ...d, weight, weightRule, geometryRegister, geometryRule }
  })
  const twigSpecs = dealTwigSpecs(twigDrafts)
  const twigs: BenchTwig[] = twigDrafts.map((d) => ({
    id: d.id,
    name: d.name,
    state: d.state,
    task: d.task,
    parentId: d.parentId,
    subtaskCount: d.subtaskCount,
    jin: d.state === 'Dropped',
    weight: d.weight,
    weightRule: d.weightRule,
    geometryRegister: d.geometryRegister,
    geometryRule: d.geometryRule,
    discussion: discussionForTask(d.task),
    foliageSeats: foliageSeatsForTask(d.task, args.foliage ?? NO_FOLIAGE),
    proposals: d.proposals,
    spec: twigSpecs.get(d.id)!,
  }))
  const discussion = new Map<string, string[]>()
  for (const b of branches) {
    if (b.foliageSeats.length)
      discussion.set(b.id, b.foliageSeats.map((s) => s.seatName))
  }
  for (const t of twigs) {
    if (t.foliageSeats.length)
      discussion.set(t.id, t.foliageSeats.map((s) => s.seatName))
  }
  const grown = growTree(
    branches.map((b) => b.element),
    args.crosses,
    twigs.map((t) => t.spec),
  )
  // padStyleFor looks every pad's handle up here: branches AND
  // twigs, the twig element in the same shape growth.ts deals it.
  const elementsByHandle = new Map<string, BenchElement>(elements)
  for (const t of twigs) {
    elementsByHandle.set(t.id, {
      handle: t.id,
      register: t.spec.register,
      side: t.spec.fork,
      tGrow: t.spec.station,
      elev: 0,
      lenOld: t.spec.lenOld,
      sprite: t.spec.sprite,
    })
  }
  const footing = footingFor({ proseChars: args.rootProse, hasVerbatim: args.hasVerbatim })
  const notebook = [...args.notebook].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  return {
    rootId: args.rootId,
    rootKind: args.rootKind,
    title: args.title,
    state: args.state,
    register,
    registerRule,
    branches,
    twigs,
    crosses: args.crosses,
    grown,
    discussion,
    elementsByHandle,
    footing,
    notebook,
  }
}

function branchNotebookEntries(branch: {
  name: string
  task: Task | null
  discussion: DiscussionEvidence | null
  proposals: BenchProposal[]
}): NotebookEntry[] {
  const out: NotebookEntry[] = []
  const t = branch.task
  if (t) {
    if (branch.discussion) {
      out.push({
        kind: 'Documented',
        title: `Discussed with ${branch.discussion.seatName} — ${branch.name}`,
        body: `This task came out of a recorded conversation with ${branch.discussion.seatName}. The proposal that created it is kept on the record with a verbatim evidence quote from that conversation.`,
        custody: `Task record · origin_seat ${t.origin_seat} · origin_conversation_id ${branch.discussion.conversationId} · origin_message_id ${t.origin_message_id ?? '—'}.`,
        date: t.created_at,
      })
    }
    if (t.completion_criteria?.trim()) {
      out.push({
        kind: "As you've told it",
        title: `Completion criteria — ${branch.name}`,
        body: t.completion_criteria.trim(),
        custody: `Task record for ${t.id} · completion_criteria.`,
        date: t.updated_at,
      })
    }
    if (t.description?.trim()) {
      out.push({
        kind: "As you've told it",
        title: `Description — ${branch.name}`,
        body: t.description.trim(),
        custody: `Task record for ${t.id} · description.`,
        date: t.updated_at,
      })
    }
    if (t.notes?.trim()) {
      out.push({
        kind: "As you've told it",
        title: `Note — ${branch.name}`,
        body: t.notes.trim(),
        custody: `Task record for ${t.id} · notes.`,
        date: t.updated_at,
      })
    }
  }
  for (const p of branch.proposals) {
    const seatName = SEAT_NAME_BY_ARCHETYPE[p.seat] ?? p.seat
    out.push({
      kind: 'Record',
      title: `Proposal awaiting your verdict — ${p.title}`,
      body: p.evidence_quote ? `“${p.evidence_quote}”` : p.title,
      custody: `Task proposal ${p.id} · proposed by ${seatName} in conversation ${p.conversation_id} · state: pending.`,
      date: p.created_at,
    })
  }
  return out
}

/* ------------------------------------------------------------------ */
/* Tree builders per root kind                                         */
/* ------------------------------------------------------------------ */

export function buildProjectTree(
  project: Project,
  entities: BenchEntities,
  proposalsByParent: ReadonlyMap<string, BenchProposal[]>,
  foliage: FoliageByTask = NO_FOLIAGE,
): BenchTreeModel {
  // A project standing as its own tree (a loose project on the
  // shelf, or an initiative's branch brought forward): the project
  // is the trunk, and its top-level tasks are TWIGS off the trunk —
  // the same level they hold on their initiative's tree, off its
  // branch. Subtasks are not twigs of twigs (see dealTwigSpecs).
  const tasks = entities.tasks.filter((t) => t.project_id === project.id)
  const top = tasks.filter((t) => !t.parent_task_id)
  const subtaskCount = (id: string) => tasks.filter((t) => t.parent_task_id === id).length
  const twigDrafts = top.map((t) => ({
    id: t.id,
    name: t.title,
    state: t.status,
    task: t,
    parentId: null,
    subtaskCount: subtaskCount(t.id),
    proposals: proposalsByParent.get(t.id) ?? [],
  }))
  const topIds = new Set(top.map((t) => t.id))
  const crosses: Array<[string, string]> = []
  for (const t of top) {
    for (const dep of t.dependency_ids ?? []) {
      if (topIds.has(dep)) crosses.push([t.id, dep])
    }
  }
  const notebook: NotebookEntry[] = []
  if (project.brief?.trim()) {
    notebook.push({
      kind: "As you've told it",
      title: `Brief — ${project.title}`,
      body: project.brief.trim(),
      custody: `Project record for ${project.id} · brief.`,
      date: project.created_at,
    })
  }
  if (project.notes?.trim()) {
    notebook.push({
      kind: "As you've told it",
      title: `Notes — ${project.title}`,
      body: project.notes.trim(),
      custody: `Project record for ${project.id} · notes.`,
      date: project.updated_at,
    })
  }
  for (const d of twigDrafts) {
    notebook.push(
      ...branchNotebookEntries({
        name: d.name,
        task: d.task,
        discussion: discussionForTask(d.task),
        proposals: d.proposals,
      }),
    )
  }
  if (crosses.length) {
    notebook.push({
      kind: 'Record',
      title: 'Dependencies inside this project',
      body: crosses
        .map(([a, b]) => {
          const an = top.find((t) => t.id === a)?.title ?? a
          const bn = top.find((t) => t.id === b)?.title ?? b
          return `“${an}” depends on “${bn}”.`
        })
        .join(' '),
      custody: 'Task records · dependency_ids.',
      date: project.updated_at,
    })
  }
  const rootProse =
    proseOf(project.brief, project.notes, project.next_step_ai) +
    twigDrafts.reduce(
      (n, d) => n + proseOf(d.task?.description, d.task?.notes, d.task?.completion_criteria),
      0,
    )
  const hasVerbatim = twigDrafts.some((d) => discussionForTask(d.task) !== null)
  const attached =
    project.initiative_id !== null ||
    top.length > 0 ||
    project.start_date !== null ||
    project.end_date !== null ||
    (project.brief ?? '').trim().length > 0
  return buildTree({
    rootId: project.id,
    rootKind: 'project',
    title: project.title,
    state: project.status,
    attached,
    branchDrafts: [],
    twigDrafts,
    crosses,
    rootProse,
    hasVerbatim,
    notebook,
    foliage,
  })
}

export function buildInitiativeTree(
  initiative: Initiative,
  entities: BenchEntities,
  proposalsByParent: ReadonlyMap<string, BenchProposal[]>,
  foliage: FoliageByTask = NO_FOLIAGE,
): BenchTreeModel {
  // THE corrected grammar (founder, 2026-11-24): the initiative is
  // the TREE, its projects are the BRANCHES, and each project's
  // top-level tasks are TWIGS off that project's branch. Foliage,
  // wire and jin attach at the twig, because that is the level of
  // the record they belong to (a task's provenance, a task's
  // proposals, a task's state).
  const projects = entities.projects.filter((p) => p.initiative_id === initiative.id)
  const drafts = projects.map((p) => ({
    id: p.id,
    name: p.title,
    state: p.status,
    sourceKind: 'project' as const,
    task: null,
    subtaskCount: entities.tasks.filter((t) => t.project_id === p.id && !t.parent_task_id).length,
    proposals: [] as BenchProposal[],
  }))
  const twigDrafts: Array<{
    id: string
    name: string
    state: string
    task: Task
    parentId: string | null
    subtaskCount: number
    proposals: BenchProposal[]
  }> = []
  for (const p of projects) {
    const tasks = entities.tasks.filter((t) => t.project_id === p.id)
    for (const t of tasks.filter((x) => !x.parent_task_id)) {
      twigDrafts.push({
        id: t.id,
        name: t.title,
        state: t.status,
        task: t,
        parentId: p.id,
        subtaskCount: tasks.filter((x) => x.parent_task_id === t.id).length,
        proposals: proposalsByParent.get(t.id) ?? [],
      })
    }
  }
  const twigIds = new Set(twigDrafts.map((d) => d.id))
  const crosses: Array<[string, string]> = []
  for (const d of twigDrafts) {
    for (const dep of d.task.dependency_ids ?? []) {
      if (twigIds.has(dep)) crosses.push([d.id, dep])
    }
  }
  const notebook: NotebookEntry[] = []
  if (initiative.brief?.trim()) {
    notebook.push({
      kind: "As you've told it",
      title: `Brief — ${initiative.title}`,
      body: initiative.brief.trim(),
      custody: `Initiative record for ${initiative.id} · brief.`,
      date: initiative.created_at,
    })
  }
  if (initiative.notes?.trim()) {
    notebook.push({
      kind: "As you've told it",
      title: `Notes — ${initiative.title}`,
      body: initiative.notes.trim(),
      custody: `Initiative record for ${initiative.id} · notes.`,
      date: initiative.updated_at,
    })
  }
  if (projects.length) {
    notebook.push({
      kind: 'Record',
      title: 'Projects under this initiative',
      body: projects.map((p) => `“${p.title}” (${p.status}).`).join(' '),
      custody: 'Project records · initiative_id.',
      date: initiative.updated_at,
    })
  }
  for (const d of twigDrafts) {
    notebook.push(
      ...branchNotebookEntries({
        name: d.name,
        task: d.task,
        discussion: discussionForTask(d.task),
        proposals: d.proposals,
      }),
    )
  }
  const rootProse =
    proseOf(initiative.brief, initiative.notes, initiative.next_step_ai) +
    twigDrafts.reduce(
      (n, d) => n + proseOf(d.task.description, d.task.notes, d.task.completion_criteria),
      0,
    )
  const hasVerbatim = twigDrafts.some((d) => discussionForTask(d.task) !== null)
  return buildTree({
    rootId: initiative.id,
    rootKind: 'initiative',
    title: initiative.title,
    state: initiative.status,
    attached: true,
    branchDrafts: drafts,
    twigDrafts,
    crosses,
    rootProse,
    hasVerbatim,
    notebook,
    foliage,
  })
}

export function buildIdeaTree(
  idea: Idea,
  entities: BenchEntities,
): BenchTreeModel {
  const originated = entities.initiatives.some((i) => i.source_idea_id === idea.id)
  const notebook: NotebookEntry[] = []
  const prose = idea.description?.trim() || idea.summary?.trim() || idea.notes?.trim() || ''
  if (prose) {
    notebook.push({
      kind: "As you've told it",
      title: `On the record — ${idea.title}`,
      body: prose,
      custody: `Idea record for ${idea.id}.`,
      date: idea.created_at,
    })
  }
  if (originated) {
    const ini = entities.initiatives.find((i) => i.source_idea_id === idea.id)!
    notebook.push({
      kind: 'Record',
      title: 'Origin edge',
      body: `This idea is the recorded origin of the initiative “${ini.title}”.`,
      custody: 'Initiative record · source_idea_id.',
      date: ini.created_at,
    })
  }
  return buildTree({
    rootId: idea.id,
    rootKind: 'idea',
    title: idea.title,
    state: idea.status,
    attached: originated,
    branchDrafts: [
      {
        id: idea.id,
        name: idea.title,
        state: idea.status,
        sourceKind: 'root' as const,
        task: null,
        subtaskCount: idea.checklist_progress?.total ?? 0,
        proposals: [],
      },
    ],
    crosses: [],
    rootProse: proseOf(idea.description, idea.summary, idea.notes, idea.desired_outcome),
    hasVerbatim: false,
    notebook,
  })
}

export function buildLooseTaskTree(
  task: Task,
  foliage: FoliageByTask = NO_FOLIAGE,
): BenchTreeModel {
  const notebook = branchNotebookEntries({
    name: task.title,
    task,
    discussion: discussionForTask(task),
    proposals: [],
  })
  return buildTree({
    rootId: task.id,
    rootKind: 'task',
    title: task.title,
    state: task.status,
    attached: false,
    foliage,
    branchDrafts: [
      {
        id: task.id,
        name: task.title,
        state: task.status,
        sourceKind: 'root' as const,
        task,
        subtaskCount: 0,
        proposals: [],
      },
    ],
    crosses: [],
    rootProse: proseOf(task.description, task.notes, task.completion_criteria),
    hasVerbatim: discussionForTask(task) !== null,
    notebook,
  })
}

/* ------------------------------------------------------------------ */
/* The Shelf (§0)                                                      */
/* ------------------------------------------------------------------ */

export interface ShelfItem {
  id: string
  kind: RootKind
  kindLabel: string
  title: string
  state: string
  register: BenchRegister
  registerRule: string
}

const KIND_LABEL: Record<RootKind, string> = {
  initiative: 'Initiative',
  project: 'Project',
  idea: 'Idea',
  task: 'Task',
}

/** The shelf holds the record's roots under the standing display
 *  rule (founder, 2026-11-24 — parents and loose items only):
 *  initiatives, LOOSE projects (no initiative, or one the record
 *  does not carry), ideas, and loose tasks — each captioned with
 *  its TRUE kind, never flattened to "projects". A project under
 *  a fetched initiative is not a shelf root: it stands as a
 *  branch of its initiative's tree (branch = nested record) and
 *  is brought to the bench from there, so it stays reachable
 *  through its parent. */
export function buildShelf(entities: BenchEntities): ShelfItem[] {
  const items: ShelfItem[] = []
  const noProposals = new Map<string, BenchProposal[]>()
  for (const ini of entities.initiatives) {
    const t = buildInitiativeTree(ini, entities, noProposals)
    items.push({
      id: ini.id,
      kind: 'initiative',
      kindLabel: KIND_LABEL.initiative,
      title: ini.title,
      state: ini.status,
      register: t.register,
      registerRule: t.registerRule,
    })
  }
  for (const p of entities.projects) {
    if (p.initiative_id && entities.initiatives.some((i) => i.id === p.initiative_id)) continue
    const t = buildProjectTree(p, entities, noProposals)
    items.push({
      id: p.id,
      kind: 'project',
      kindLabel: KIND_LABEL.project,
      title: p.title,
      state: p.status,
      register: t.register,
      registerRule: t.registerRule,
    })
  }
  for (const idea of entities.ideas) {
    const t = buildIdeaTree(idea, entities)
    items.push({
      id: idea.id,
      kind: 'idea',
      kindLabel: KIND_LABEL.idea,
      title: idea.title,
      state: idea.status,
      register: t.register,
      registerRule: t.registerRule,
    })
  }
  for (const task of entities.tasks) {
    if (task.project_id || task.parent_task_id) continue
    const t = buildLooseTaskTree(task)
    items.push({
      id: task.id,
      kind: 'task',
      kindLabel: KIND_LABEL.task,
      title: task.title,
      state: task.status,
      register: t.register,
      registerRule: t.registerRule,
    })
  }
  return items
}

/* ------------------------------------------------------------------ */
/* Verdicts (§2 / §11)                                                 */
/* ------------------------------------------------------------------ */

export interface VerdictLogEntry {
  proposalId: string
  branchId: string
  kind: 'stand' | 'cut'
  text: string
  when: string
}

/** The session verdict log line — the durable verdict itself is the
 *  proposal row's state, written by the governed approve/decline
 *  endpoints; this log is the session's notebook view of it (§11). */
export function verdictLogEntry(args: {
  proposal: BenchProposal
  branchName: string
  rootTitle: string
  kind: 'stand' | 'cut'
  when: string
}): VerdictLogEntry {
  return {
    proposalId: args.proposal.id,
    branchId: args.proposal.parent_task_id ?? '',
    kind: args.kind,
    text: `${args.kind === 'stand' ? 'Let stand' : 'Cut back'} — “${args.proposal.title}” on “${args.branchName}” (${args.rootTitle})`,
    when: args.when,
  }
}
