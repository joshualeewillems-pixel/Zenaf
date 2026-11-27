// @vitest-environment jsdom
/**
 * The overhead scene fixture (the brief's scene gate): twelve
 * tasks under the ported packing law, rendered in jsdom.
 * Asserts the composite ORDER (sky band → shell back → floor →
 * rooms → shell front), the asset wiring (twelve task rooms plus
 * the four standing artifact rooms, each a domed sprite; the
 * hearth flame present), and the tap wiring (a task room opens
 * its chamber; an artifact room stages its instrument; the
 * drawing-table room reports the table).
 *
 * jsdom cannot paint: pixel checks (doorways showing paving,
 * sprite registration on device) are out of scope for this
 * suite — on-device rendering remains the founder's visual
 * acceptance, as with every Palace scene.
 */
import { describe, it, expect, vi } from 'vitest'
import * as React from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { OverheadScene } from './palaceCanvas'
import { buildTaskLevel, type PalaceData, type TaskLevelModel } from './palaceLogic'
import { planOverheadLayout, type OverheadArtifactKind } from './palaceOverheadLogic'
import { taskSizeWeight } from './palaceScene2Logic'
import type { Project, Task } from '../vision-execution/types'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const PROJECT = {
  id: 'px', initiative_id: null, title: 'Fixture project', status: 'Active',
  owner_id: 'per1', supporting_owner_ids: [], estimated_weekly_hours: null,
} as unknown as Project

function task(partial: Partial<Task>): Task {
  return {
    project_id: 'px', parent_task_id: null, title: 'Task', description: '', assignee_id: null,
    status: 'Todo', priority: '', estimated_hours: null, due_date: null, dependency_ids: [],
    completion_criteria: '', notes: '', created_at: '', updated_at: '', seat_ref: '',
    origin_seat: null, origin_conversation_id: null, origin_message_id: null, responsible_seat: null,
    ...partial,
  } as Task
}

const HOURS: (number | null)[] = [12, 10, 9, 8, 7, 6, 5, 4, 3, 2, null, null]
const DATA: PalaceData = {
  ideas: [],
  initiatives: [],
  projects: [PROJECT],
  tasks: HOURS.map((hours, i) =>
    task({
      id: `t${i + 1}`,
      title: `Task ${i + 1}`,
      estimated_hours: hours,
      dependency_ids: i === 2 ? ['t2'] : [],
    }),
  ),
  persons: [],
  assets: [],
  capacityProfiles: [],
}

function layoutFor(model: TaskLevelModel) {
  const partners = new Map<string, Set<string>>()
  const link = (a: string, b: string) => {
    const set = partners.get(a) ?? new Set<string>()
    set.add(b)
    partners.set(a, set)
  }
  for (const l of model.links) {
    link(l.aId, l.bId)
    link(l.bId, l.aId)
  }
  return planOverheadLayout(
    model.tasks.map((t) => ({ id: t.id, weight: taskSizeWeight(t.estimated_hours) })),
    partners,
    null,
    { fixtures: true },
  )
}

function renderScene() {
  const model = buildTaskLevel(DATA, PROJECT)
  const onOpenTask = vi.fn()
  const onOpenArtifact = vi.fn()
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  act(() => {
    root.render(
      React.createElement(OverheadScene, {
        model,
        layout: layoutFor(model),
        onOpenTask,
        onOpenArtifact,
      }),
    )
  })
  return { container, root, onOpenTask, onOpenArtifact }
}

function click(container: HTMLElement, testid: string) {
  const el = container.querySelector(`[data-testid="${testid}"]`)
  expect(el, `missing ${testid}`).not.toBeNull()
  act(() => {
    el!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

describe('the overhead scene — twelve tasks', () => {
  it('composes in the gated order and wires every asset', () => {
    const { container, root } = renderScene()
    const html = container.innerHTML
    // The composite order is a gate: sky band → shell BACK →
    // floor paving disc → rooms back-to-front → shell FRONT.
    const sky = html.indexOf('palace-sky')
    const shellBack = html.indexOf('palace-shell-back')
    const floor = html.indexOf('palace-floor')
    const firstRoom = html.indexOf('palace-task-')
    const shellFront = html.indexOf('palace-shell-front')
    expect(sky).toBeGreaterThanOrEqual(0)
    expect(shellBack).toBeGreaterThan(sky)
    expect(floor).toBeGreaterThan(shellBack)
    expect(firstRoom).toBeGreaterThan(floor)
    expect(shellFront).toBeGreaterThan(firstRoom)
    // The shell's front band paints after EVERY room.
    expect(shellFront).toBeGreaterThan(html.lastIndexOf('palace-artifact-'))
    // Twelve task rooms, four artifact rooms — sixteen domed
    // sprites in all.
    for (let i = 1; i <= 12; i++) {
      expect(container.querySelector(`[data-testid="palace-task-t${i}"]`)).not.toBeNull()
    }
    expect((html.match(/founder-domed-/g) ?? []).length).toBe(16)
    // The four standing artifact rooms, each identified by its
    // object alone: the vessel (plain — no gold read here), the
    // scales, the drawing table, the chest.
    for (const kind of ['vessel', 'scales', 'table', 'chest']) {
      expect(container.querySelector(`[data-testid="palace-artifact-${kind}"]`)).not.toBeNull()
    }
    expect(container.querySelector('[data-testid="palace-vessel-plain"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-scales"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-drawing-table"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-chest"]')).not.toBeNull()
    // The hearth stands at the centre with the founder flame.
    expect(container.querySelector('[data-testid="palace-overhead-hearth"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="palace-overhead-fire"]')).not.toBeNull()
    // The shell is the extracted art in both halves; the floor
    // is the study's paving; nothing in the scene paints white
    // (SVG mask fills are luminance, never rendered colour).
    expect(html).toContain('dome-shell-extracted-v2')
    expect(html).toContain('palace-floor-paving')
    expect(html).not.toMatch(/background:\s*(#fff|#ffffff|white)\b/)
    expect(html).not.toMatch(/background-color:\s*(#fff|#ffffff|white)\b/)
    act(() => root.unmount())
  })

  it('taps: a task room opens its chamber; artifact rooms stage their instruments', () => {
    const { container, root, onOpenTask, onOpenArtifact } = renderScene()
    click(container, 'palace-task-t5')
    expect(onOpenTask).toHaveBeenCalledWith('t5')
    click(container, 'palace-artifact-scales')
    expect(onOpenArtifact).toHaveBeenCalledWith('scales' satisfies OverheadArtifactKind)
    click(container, 'palace-artifact-table')
    expect(onOpenArtifact).toHaveBeenCalledWith('table')
    click(container, 'palace-artifact-vessel')
    expect(onOpenArtifact).toHaveBeenCalledWith('vessel')
    click(container, 'palace-artifact-chest')
    expect(onOpenArtifact).toHaveBeenCalledWith('chest')
    act(() => root.unmount())
  })

  it('an empty project still stands: hearth, four artifact rooms, no task rooms', () => {
    const empty: PalaceData = { ...DATA, tasks: [] }
    const model = buildTaskLevel(empty, PROJECT)
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => {
      root.render(
        React.createElement(OverheadScene, {
          model,
          layout: layoutFor(model),
          onOpenTask: () => {},
          onOpenArtifact: () => {},
        }),
      )
    })
    expect(container.querySelector('[data-testid="palace-overhead-hearth"]')).not.toBeNull()
    for (const kind of ['vessel', 'scales', 'table', 'chest']) {
      expect(container.querySelector(`[data-testid="palace-artifact-${kind}"]`)).not.toBeNull()
    }
    expect(container.querySelector('[data-testid^="palace-task-"]')).toBeNull()
    expect(container.textContent).toContain('No tasks yet')
    act(() => root.unmount())
  })
})
