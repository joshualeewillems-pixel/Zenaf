/**
 * Parents + loose by default (founder rulings 2026-11-24 / 2026-11-25).
 *
 * Shared grouping/visibility helpers for Vision Execution's collection
 * views (Execution list, Execution timeline, Roadmap). The nested default
 * lists ONLY:
 *   - top-level parents: initiatives,
 *   - loose/unanchored items: projects with no initiative, tasks with no
 *     project, and root standalone tasks.
 * Children — projects under an initiative, tasks under a project, and
 * subtasks under a task (parent_task_id) — appear only when their parent
 * is un-nested (expanded). Every child stays reachable: expanding a parent
 * reveals its children, expand-all reveals everything, and collapse-all
 * restores exactly this default. Nothing is deleted or permanently hidden.
 */

import type { Initiative, Project, Task } from './types'

/** Projects that belong to an initiative. */
export function projectsOfInitiative(projects: Project[], initiativeId: string): Project[] {
  return projects.filter((p) => p.initiative_id === initiativeId)
}

/** Loose projects: no initiative anchors them, so they stand on their own. */
export function looseProjects(projects: Project[]): Project[] {
  return projects.filter((p) => !p.initiative_id)
}

/** Tasks that belong to a project. */
export function tasksOfProject(tasks: Task[], projectId: string): Task[] {
  return tasks.filter((t) => t.project_id === projectId)
}

/**
 * Children of each task within the given set, keyed by parent task id.
 * A parent_task_id pointing outside the set (or at the task itself) does
 * not make the task a child here — it stands as a root of this set,
 * mirroring the timeline's pushTaskSubtree treatment.
 */
export function taskChildrenByParentId(tasks: Task[]): Map<string, Task[]> {
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const children = new Map<string, Task[]>()
  for (const t of tasks) {
    const pid = t.parent_task_id ?? null
    if (pid && pid !== t.id && byId.has(pid)) {
      const list = children.get(pid) || []
      list.push(t)
      children.set(pid, list)
    }
  }
  return children
}

/** Root tasks of a set: tasks whose parent task is not itself in the set. */
export function rootTasksOf(tasks: Task[]): Task[] {
  const childIds = new Set<string>()
  for (const list of taskChildrenByParentId(tasks).values()) {
    for (const t of list) childIds.add(t.id)
  }
  return tasks.filter((t) => !childIds.has(t.id))
}

/** Subtasks of one task within the given set. */
export function subtasksOf(tasks: Task[], parentTaskId: string): Task[] {
  return taskChildrenByParentId(tasks).get(parentTaskId) ?? []
}

/**
 * Loose tasks: no project anchors them. Only root standalone tasks are
 * loose in their own right — a subtask of a standalone task is that
 * task's child, revealed by un-nesting it.
 */
export function looseTasks(tasks: Task[]): Task[] {
  return rootTasksOf(tasks.filter((t) => !t.project_id))
}

/**
 * Ids that start collapsed in the nested default for set-based views
 * (the timeline): every initiative, every project, and every task that
 * has subtasks. The loose section groups ('_unanchored',
 * '_orphan_tasks') are deliberately NOT in this set — loose projects and
 * loose tasks are listed by default, standing under their section
 * heading, while their own children stay nested.
 */
export function defaultNestedCollapsedIds(
  initiatives: Initiative[],
  projects: Project[],
  tasks: Task[],
): Set<string> {
  const collapsed = new Set<string>()
  for (const i of initiatives) collapsed.add(i.id)
  for (const p of projects) collapsed.add(p.id)
  const allChildren = taskChildrenByParentId(tasks)
  for (const t of tasks) {
    if ((allChildren.get(t.id) ?? []).length > 0) collapsed.add(t.id)
  }
  return collapsed
}

/** Every id that can be un-nested across the three levels (expand-all). */
export function allNestableIds(
  initiatives: Initiative[],
  projects: Project[],
  tasks: Task[],
): { initiativeIds: string[]; projectIds: string[]; taskIds: string[] } {
  const allChildren = taskChildrenByParentId(tasks)
  return {
    initiativeIds: initiatives.map((i) => i.id),
    projectIds: projects.map((p) => p.id),
    taskIds: tasks.filter((t) => (allChildren.get(t.id) ?? []).length > 0).map((t) => t.id),
  }
}
