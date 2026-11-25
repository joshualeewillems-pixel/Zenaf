/**
 * Painting verification — structural, against a recording 2D context.
 *
 * jsdom has no canvas rasteriser, so this suite records every fill
 * the painters issue and checks the foliage rule at the level that
 * matters: blossom tint fills in a discussing seat's colour appear
 * ONLY for the branch whose record carries discussion evidence, and
 * no foliage fills at all appear for an undiscussed tree. (Geometry
 * itself is proven in growth.test.ts; on-device painting is the
 * founder's acceptance.)
 */
import { describe, it, expect } from 'vitest'
import type { Initiative, Project, Task } from '../vision-execution/types'
import { seatTint, TINTS } from './growth'
import { paintScene, type SceneModel } from './paint'
import {
  buildInitiativeTree,
  buildProjectTree,
  type BenchEntities,
  type BenchProposal,
  type BenchTreeModel,
} from './benchLogic'

class RecordingContext {
  fills: string[] = []
  strokes: string[] = []
  fillStyle: string | CanvasGradient | CanvasPattern = ''
  strokeStyle: string | CanvasGradient | CanvasPattern = ''
  lineWidth = 1
  lineCap: CanvasLineCap = 'butt'
  globalAlpha = 1
  save() {}
  restore() {}
  beginPath() {}
  moveTo() {}
  lineTo() {}
  closePath() {}
  clip() {}
  clearRect() {}
  fillRect() {
    this.fills.push(String(this.fillStyle))
  }
  fill() {
    this.fills.push(String(this.fillStyle))
  }
  stroke() {
    this.strokes.push(String(this.strokeStyle))
  }
  ellipse() {}
  arc() {}
  setTransform() {}
}

function task(partial: Partial<Task> & { id: string }): Task {
  return {
    project_id: 'p1', parent_task_id: null, title: partial.id, description: '',
    assignee_id: null, status: 'Todo', priority: '', estimated_hours: null,
    due_date: null, dependency_ids: [], completion_criteria: '', notes: '',
    created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    seat_ref: '', origin_seat: null, origin_conversation_id: null,
    origin_message_id: null, responsible_seat: null, ...partial,
  }
}

const PROJECT: Project = {
  id: 'p1', initiative_id: null, title: 'Winter client season', brief: '',
  status: 'Active', owner_id: null, supporting_owner_ids: [], priority: '',
  start_date: null, end_date: null, estimated_weekly_hours: null,
  next_step_ai: '', notes: '', created_at: '2026-05-01T00:00:00',
  updated_at: '2026-05-01T00:00:00',
}

function sceneForTree(tree: BenchTreeModel): SceneModel {
  return {
    grown: tree.grown,
    register: tree.register,
    elementsByHandle: tree.elementsByHandle,
    discussion: tree.discussion,
    branches: tree.branches.map((b) => ({ id: b.id, jin: b.jin, widthScale: 1, wireSeatColour: null })),
    twigs: tree.twigs.map((t) => ({ id: t.id, jin: t.jin, widthScale: 1, wireSeatColour: null })),
    footing: tree.footing,
    showExploratory: true,
    selectedId: null,
    pencil: null,
  }
}

function sceneFor(tasks: Task[]): SceneModel {
  const entities: BenchEntities = { ideas: [], initiatives: [], projects: [PROJECT], tasks }
  const tree = buildProjectTree(PROJECT, entities, new Map<string, BenchProposal[]>())
  return sceneForTree(tree)
}

function tintFills(ctx: RecordingContext): string[] {
  // every seat's blossom petal tint over the cherry family (sprite 1)
  const petals = ['Rumi', 'Valen', 'Maeve', 'Jynx', 'Lucian', 'Aria'].map((seat) => {
    const [petal] = seatTint(TINTS[1][0], TINTS[1][1], seat)
    return `rgba(${petal[0]},${petal[1]},${petal[2]},`
  })
  return ctx.fills.filter((f) => petals.some((p) => f.startsWith(p)))
}

describe('paintScene — foliage is painted only where evidenced', () => {
  const discussed = task({
    id: 't-discussed', title: 'Order timber',
    origin_seat: 'guardian', origin_conversation_id: 'talk-123', origin_message_id: 'm-9',
  })
  const plain = task({ id: 't-plain', title: 'Confirm bookings' })
  const other = task({ id: 't-other', title: 'Invoice the job', status: 'In Progress' })

  it("paints Maeve-tinted blossom fills for the discussed twig's tree", () => {
    const ctx = new RecordingContext()
    paintScene(ctx as unknown as CanvasRenderingContext2D, sceneFor([discussed, plain, other]))
    const [maevelPetal] = seatTint(TINTS[1][0], TINTS[1][1], 'Maeve')
    const maeve = `rgba(${maevelPetal[0]},${maevelPetal[1]},${maevelPetal[2]},`
    expect(ctx.fills.some((f) => f.startsWith(maeve))).toBe(true)
  })

  it('paints NO foliage fills at all when no twig carries discussion evidence', () => {
    const ctx = new RecordingContext()
    paintScene(ctx as unknown as CanvasRenderingContext2D, sceneFor([plain, other]))
    expect(tintFills(ctx)).toEqual([])
    // the tree itself still paints (wood, trunk, environment)
    expect(ctx.fills.length).toBeGreaterThan(10)
  })

  it('Gate 0: on an initiative tree, the prototype’s two records paint Maeve foliage as twigs', () => {
    // B1-T2 "Order timber" and B2-T2 "Rewire the bench sockets" —
    // tasks discussed with Maeve in the accepted prototype. As
    // twigs on their projects' branches, Maeve-tinted blossom fills
    // must still appear; and no OTHER seat's tint may appear.
    const ini: Initiative = {
      id: 'ini-b', source_idea_id: null, title: 'Workshop season', brief: '',
      status: 'Active', owner_id: null, evaluation_priority: null, estimated_cost_ai: '',
      estimated_timeframe_ai: '', philosophical_alignment_ai: '', next_step_ai: '',
      required_assets: [], dependencies: '', risks: '', recommendation: '',
      kill_criteria: '', notes: '', created_at: '2026-05-01T00:00:00', updated_at: '2026-05-01T00:00:00',
    }
    const b1: Project = { ...PROJECT, id: 'B1', initiative_id: 'ini-b', title: 'Winter client season' }
    const b2: Project = { ...PROJECT, id: 'B2', initiative_id: 'ini-b', title: 'Workshop refit' }
    const entities: BenchEntities = {
      ideas: [],
      initiatives: [ini],
      projects: [b1, b2],
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
    const tree = buildInitiativeTree(ini, entities, new Map<string, BenchProposal[]>())
    const ctx = new RecordingContext()
    paintScene(ctx as unknown as CanvasRenderingContext2D, sceneForTree(tree))
    const fills = tintFills(ctx)
    const [maevelPetal] = seatTint(TINTS[1][0], TINTS[1][1], 'Maeve')
    const maeve = `rgba(${maevelPetal[0]},${maevelPetal[1]},${maevelPetal[2]},`
    expect(fills.length).toBeGreaterThan(0)
    expect(fills.every((f) => f.startsWith(maeve))).toBe(true)
  })
})
