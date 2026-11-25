/**
 * Parents + loose by default (founder rulings 2026-11-24 / 2026-11-25).
 *
 * Pins the nested default for Vision Execution's collection views:
 * the shared grouping helper, plus the Execution timeline view's row
 * builder (buildTimelineRows is the timeline's data layer — the rows it
 * returns are exactly what the view lists).
 *   1. Default lists parents + loose only; children absent.
 *   2. Un-nesting a parent reveals its children, level by level.
 *   3. Collapsing (restoring the default collapsed set) restores the
 *      default listing.
 */
import { describe, expect, it } from 'vitest'
import type { Initiative, Project, Task } from './types'
import {
  allNestableIds,
  defaultNestedCollapsedIds,
  looseProjects,
  looseTasks,
  projectsOfInitiative,
  rootTasksOf,
  subtasksOf,
  tasksOfProject,
} from './nestedVisibility'
import { buildTimelineRows } from './timeline/timelineUtils'

const init = { id: 'init-1', title: 'Initiative One', status: 'Active', brief: '' } as unknown as Initiative
const anchoredProject = { id: 'proj-1', initiative_id: 'init-1', title: 'Anchored Project', status: 'Active', brief: '' } as unknown as Project
const looseProject = { id: 'proj-2', initiative_id: null, title: 'Loose Project', status: 'Active', brief: '' } as unknown as Project

const task = (id: string, project_id: string | null, parent_task_id: string | null, title: string) =>
  ({ id, project_id, parent_task_id, title, status: 'Open', description: '' }) as unknown as Task

const anchoredTask = task('task-1', 'proj-1', null, 'Anchored Task')
const anchoredSubtask = task('sub-1', 'proj-1', 'task-1', 'Anchored Subtask')
const looseProjectTask = task('task-2', 'proj-2', null, 'Loose Project Task')
const standaloneTask = task('task-3', null, null, 'Standalone Task')
const standaloneSubtask = task('sub-2', null, 'task-3', 'Standalone Subtask')

const initiatives = [init]
const projects = [anchoredProject, looseProject]
const tasks = [anchoredTask, anchoredSubtask, looseProjectTask, standaloneTask, standaloneSubtask]

describe('nestedVisibility grouping (parents + loose)', () => {
  it('separates anchored children from loose items', () => {
    expect(projectsOfInitiative(projects, 'init-1').map((p) => p.id)).toEqual(['proj-1'])
    expect(looseProjects(projects).map((p) => p.id)).toEqual(['proj-2'])
    expect(tasksOfProject(tasks, 'proj-1').map((t) => t.id)).toEqual(['task-1', 'sub-1'])
    // Loose tasks are root standalone tasks only — the subtask is a child.
    expect(looseTasks(tasks).map((t) => t.id)).toEqual(['task-3'])
  })

  it('treats subtasks as children of their parent task, not roots', () => {
    const projTasks = tasksOfProject(tasks, 'proj-1')
    expect(rootTasksOf(projTasks).map((t) => t.id)).toEqual(['task-1'])
    expect(subtasksOf(projTasks, 'task-1').map((t) => t.id)).toEqual(['sub-1'])
    expect(subtasksOf(tasks, 'task-3').map((t) => t.id)).toEqual(['sub-2'])
  })

  it('default collapsed set nests every parent but never the loose section groups', () => {
    const collapsed = defaultNestedCollapsedIds(initiatives, projects, tasks)
    expect(collapsed.has('init-1')).toBe(true)
    expect(collapsed.has('proj-1')).toBe(true)
    expect(collapsed.has('proj-2')).toBe(true)
    expect(collapsed.has('task-1')).toBe(true)
    expect(collapsed.has('task-3')).toBe(true)
    expect(collapsed.has('_unanchored')).toBe(false)
    expect(collapsed.has('_orphan_tasks')).toBe(false)
  })

  it('expand-all ids cover every nestable parent at all three levels', () => {
    const all = allNestableIds(initiatives, projects, tasks)
    expect(all.initiativeIds).toEqual(['init-1'])
    expect(all.projectIds).toEqual(['proj-1', 'proj-2'])
    expect(all.taskIds.sort()).toEqual(['task-1', 'task-3'])
  })
})

describe('Execution timeline rows under the nested default', () => {
  const labels = (collapsed: Set<string>) =>
    buildTimelineRows({ initiatives, projects, tasks, collapsedIds: collapsed }).map((r) => r.label)

  it('default lists parents + loose only, children absent', () => {
    const shown = labels(defaultNestedCollapsedIds(initiatives, projects, tasks))
    // Parents
    expect(shown).toContain('Initiative One')
    // Loose items stand in the default listing
    expect(shown).toContain('Loose Project')
    expect(shown).toContain('Standalone Task')
    // Children are absent until their parent is un-nested
    expect(shown).not.toContain('Anchored Project')
    expect(shown).not.toContain('Anchored Task')
    expect(shown).not.toContain('Anchored Subtask')
    expect(shown).not.toContain('Loose Project Task')
    expect(shown).not.toContain('Standalone Subtask')
  })

  it('un-nesting a parent reveals its children, level by level', () => {
    const collapsed = defaultNestedCollapsedIds(initiatives, projects, tasks)
    collapsed.delete('init-1')
    let shown = labels(collapsed)
    expect(shown).toContain('Anchored Project')
    expect(shown).not.toContain('Anchored Task')

    collapsed.delete('proj-1')
    shown = labels(collapsed)
    expect(shown).toContain('Anchored Task')
    expect(shown).not.toContain('Anchored Subtask')

    collapsed.delete('task-1')
    shown = labels(collapsed)
    expect(shown).toContain('Anchored Subtask')

    // A loose parent un-nests the same way
    collapsed.delete('task-3')
    shown = labels(collapsed)
    expect(shown).toContain('Standalone Subtask')
  })

  it('collapsing restores the nested default listing', () => {
    const collapsed = defaultNestedCollapsedIds(initiatives, projects, tasks)
    const defaultShown = labels(collapsed)
    // Un-nest everything, then collapse back to the default set
    const expanded = labels(new Set<string>())
    expect(expanded).toContain('Anchored Subtask')
    expect(expanded).toContain('Standalone Subtask')
    expect(labels(defaultNestedCollapsedIds(initiatives, projects, tasks))).toEqual(defaultShown)
  })
})
