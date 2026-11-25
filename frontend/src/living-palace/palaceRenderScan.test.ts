// @vitest-environment jsdom
/**
 * Geometry sanity scan (throwaway-grade gate, kept because it is
 * cheap): render all four Palace scenes from a fixture body of work
 * and assert the serialized SVG carries no NaN / undefined / broken
 * coordinates — the failure mode jsdom cannot see by painting. True
 * on-device painting remains the founder's visual acceptance.
 */
import { describe, it, expect } from 'vitest'
import * as React from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { BuildingScene, CompoundScene, FloorScene, RoomScene } from './palaceCanvas'
import { buildBuilding, buildCompound, buildFloor, buildRoom, type PalaceData } from './palaceLogic'
import type { Initiative, Project, Task } from '../vision-execution/types'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function renderToHtml(node: React.ReactElement): string {
  const container = document.createElement('div')
  const root = createRoot(container)
  act(() => root.render(node))
  const html = container.innerHTML
  act(() => root.unmount())
  return html
}

const I1 = { id: 'i1', source_idea_id: null, title: 'Rebuild the workshop business', status: 'Active' } as Initiative
const P1 = {
  id: 'p1', initiative_id: 'i1', title: 'Winter client season', status: 'Active',
  owner_id: 'per1', supporting_owner_ids: [], estimated_weekly_hours: 6,
} as unknown as Project

function task(partial: Partial<Task>): Task {
  return {
    project_id: 'p1', parent_task_id: null, title: 'Task', description: '', assignee_id: null,
    status: 'Todo', priority: '', estimated_hours: null, due_date: null, dependency_ids: [],
    completion_criteria: '', notes: '', created_at: '', updated_at: '', seat_ref: '',
    origin_seat: null, origin_conversation_id: null, origin_message_id: null, responsible_seat: null,
    ...partial,
  } as Task
}

const TASKS = [
  task({ id: 'ta', title: 'Alpha', notes: 'notes' }),
  task({ id: 'tb', title: 'Beta', status: 'In Progress' }),
  task({ id: 'tc', title: 'Gamma', dependency_ids: ['tb'] }),
  task({ id: 'td', title: 'Delta', status: 'Done', dependency_ids: ['ta'] }),
  task({ id: 'te', title: 'Alpha detail', parent_task_id: 'ta' }),
  task({ id: 'tf', title: 'Convergent', dependency_ids: ['ta', 'tb'] }),
]

const DATA: PalaceData = {
  ideas: [{ id: 'id1', title: 'Apprentice', summary: '', description: '', status: 'New', tags: [], created_by: '', created_at: '', updated_at: '' }],
  initiatives: [I1],
  projects: [P1, { ...P1, id: 'lp', initiative_id: null, title: 'Loose project' }],
  tasks: [...TASKS, task({ id: 'lt', project_id: null, title: 'Loose errand' })],
  persons: [{ id: 'per1', name: 'Jo Keeper', role: '', notes: '', created_at: '', updated_at: '' } as PalaceData['persons'][number]],
  assets: [],
  capacityProfiles: [{ person_id: 'per1', weekly_capacity_hours: 20, created_at: '', updated_at: '' }],
}

describe('scene geometry scan', () => {
  it('no scene serializes NaN or undefined geometry', () => {
    const scenes: [string, string][] = [
      ['compound', renderToHtml(React.createElement(CompoundScene, {
        model: buildCompound(DATA, { unnested: true }), attended: true,
        onAttend: () => {}, onOpenBuilding: () => {}, onOpenProject: () => {}, onOpenTask: () => {},
        onSelectIdea: () => {}, selectedIdeaId: null,
      }))],
      ['building', renderToHtml(React.createElement(BuildingScene, {
        model: buildBuilding(DATA, I1), attendedFloorId: 'p1', onAttend: () => {}, onOpenFloor: () => {},
      }))],
      ['floor', renderToHtml(React.createElement(FloorScene, {
        model: buildFloor(DATA, P1, { unnested: true }), onOpenRoom: () => {}, onThreshold: () => {}, onScales: () => {},
      }))],
      ['room-waiting', renderToHtml(React.createElement(RoomScene, {
        model: buildRoom(DATA, TASKS[2]), lit: true, onBringFire: () => {}, onThreshold: () => {},
        onOpenWaitedOn: () => {}, onFurniture: () => {}, onOpenSubtask: () => {},
      }))],
      ['room-convergent', renderToHtml(React.createElement(RoomScene, {
        model: buildRoom(DATA, TASKS[5]), lit: false, onBringFire: () => {}, onThreshold: () => {},
        onOpenWaitedOn: () => {}, onFurniture: () => {}, onOpenSubtask: () => {},
      }))],
      ['room-with-chambers', renderToHtml(React.createElement(RoomScene, {
        model: buildRoom(DATA, TASKS[0]), lit: false, onBringFire: () => {}, onThreshold: () => {},
        onOpenWaitedOn: () => {}, onFurniture: () => {}, onOpenSubtask: () => {},
      }))],
    ]
    for (const [name, html] of scenes) {
      expect(html.length, name).toBeGreaterThan(800)
      expect(html, name).not.toMatch(/NaN|undefined/)
      expect(html, name).toContain('<svg')
    }
    // The compound fire carries all seven council colours.
    const compound = scenes[0][1]
    for (const hex of ['#92b692', '#e24e4e', '#ac7c5b', '#a55cce', '#5c9cea', '#8892c3', '#a29ac1']) {
      expect(compound, `flame colour ${hex}`).toContain(hex)
    }
  })
})
