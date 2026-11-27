// @vitest-environment jsdom
/**
 * Geometry sanity scan (throwaway-grade gate, kept because it is
 * cheap): render all four Palace scenes from a fixture body of work
 * and assert the serialized output carries no NaN / undefined /
 * broken coordinates — the failure mode jsdom cannot see by
 * painting. (The compound and building scenes are positioned DOM
 * since Scenes 1 and 2, and the room scene since the chamber
 * rebuild; the floor scene remains SVG.)
 * True on-device painting remains the founder's visual acceptance.
 */
import { describe, it, expect } from 'vitest'
import * as React from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import { BuildingScene, CompoundScene, FloorScene, RoomScene } from './palaceCanvas'
import { buildBuilding, buildCompound, buildFloor, buildRoom, type PalaceData } from './palaceLogic'
import type { RoomPlate } from './palaceScene2Logic'
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
    }
    // The compound and floor scenes still serialize SVG; the room
    // scenes are the furnished chamber now — positioned DOM over
    // the founder's rose plate, no drawn room geometry to scan.
    expect(scenes[0][1]).toContain('<svg')
    expect(scenes[1][1]).toContain('<svg')
    for (const [, html] of scenes.slice(2)) {
      expect(html).toContain('palace-room-rose')
    }
    // The compound fire is the founder's own flame (his ruling,
    // 2026-11-26 12:09 PT: "use the fire I gave you"), standing on
    // the lotus — an image, not the SVG council flames.
    const compound = scenes[0][1]
    expect(compound).toContain('palace-fire')
    // The floor hearth burns the SAME fire (founder, 2026-11-26:
    // "Fire — same fire") — the founder's flame image stands in
    // the floor's firebox, not the drawn council tongues.
    const floor = scenes[1][1]
    expect(floor).toContain('palace-floor-hearth')
    expect(floor).toContain('palace-fire')
    // The floor's scales are the founder's supplied art.
    expect(floor).toContain('palace-floor-scales')
    expect(floor).toContain('palace-scales')
    // The plants: jsdom has no canvas, so the Bench-bonsai bridge
    // (palacePlant) yields no image here and the PlantGlyph
    // stands, as it does in any canvas-less browser. The bridge
    // itself — grow, paint, image — is proven in
    // palacePlant.test.ts against a fake 2d context.
    expect(floor).not.toContain('data:image/png')
    // The room furniture is the founder's supplied art (2026-11-26),
    // state-selected: this room's task carries no estimate, no
    // recorded repair and no held material, so the vessel stands
    // plain, the scales unweighed and the chest CLOSED; the room
    // is lit, so the founder's flame stands in the plate's ring,
    // and the drawing table is his art.
    const roomWaiting = scenes[2][1]
    expect(roomWaiting).toContain('palace-room-vessel')
    expect(roomWaiting).toContain('palace-vessel-plain')
    expect(roomWaiting).not.toContain('palace-vessel-gold')
    expect(roomWaiting).toContain('palace-room-scales')
    expect(roomWaiting).toContain('palace-scales')
    expect(roomWaiting).not.toContain('palace-scales-weighed')
    expect(roomWaiting).toContain('palace-room-chest')
    expect(roomWaiting).toContain('palace-chest')
    expect(roomWaiting).not.toContain('palace-chest-open')
    expect(roomWaiting).toContain('palace-room-table')
    expect(roomWaiting).toContain('palace-drawing-table')
    expect(roomWaiting).toContain('palace-fire')
    // The window state reads on the plate's lancets: Gamma waits
    // on unfinished Beta — a wall still building.
    expect(roomWaiting).toContain('palace-room-window')
    expect(roomWaiting).toContain('data-window-state="building"')
    // The convergent room is unlit: no flame stands in its ring.
    // (It waits on two unfinished rooms — its window is building.)
    const roomConvergent = scenes[3][1]
    expect(roomConvergent).not.toContain('palace-fire')
    expect(roomConvergent).toContain('data-window-state="building"')
    // A room that waits on nothing carries no window overlay.
    const roomNoWait = renderToHtml(React.createElement(RoomScene, {
      model: buildRoom(DATA, TASKS[1]), lit: false, onBringFire: () => {}, onThreshold: () => {},
      onOpenWaitedOn: () => {}, onFurniture: () => {}, onOpenSubtask: () => {},
    }))
    expect(roomNoWait).toContain('data-window-state="none"')
    // The room with chambers: Alpha holds recorded material
    // (notes), so its chest stands OPEN. A room waiting only on
    // finished Delta reads a completed wall in its window.
    const roomChambers = scenes[4][1]
    expect(roomChambers).toContain('palace-chest-open')
    const roomComplete = renderToHtml(React.createElement(RoomScene, {
      model: buildRoom(DATA, task({ id: 'tx', title: 'After Delta', dependency_ids: ['td'] })),
      lit: false, onBringFire: () => {}, onThreshold: () => {},
      onOpenWaitedOn: () => {}, onFurniture: () => {}, onOpenSubtask: () => {},
    }))
    expect(roomComplete).toContain('data-window-state="complete"')
    // Gold iff vesselGold, weighed iff the task carries an
    // estimate: a gilded, estimated room flips both states.
    const gilded = renderToHtml(React.createElement(RoomScene, {
      model: buildRoom(DATA, task({ id: 'tg', title: 'Gilded', estimated_hours: 3 })),
      lit: true, vesselGold: true, onBringFire: () => {}, onThreshold: () => {},
      onOpenWaitedOn: () => {}, onFurniture: () => {}, onOpenSubtask: () => {},
    }))
    expect(gilded).toContain('palace-vessel-gold')
    expect(gilded).not.toContain('palace-vessel-plain')
    expect(gilded).toContain('palace-scales-weighed')
    // The building scene is Scene 2 (founder, 2026-11-26): plain
    // positioned DOM, not SVG — the founder's architecture dome
    // as the ground, floors as room-circles spaced in its whole
    // space in the relaxed Apollonian fashion and the one
    // hearth in the dome's own ring on its floor, its flame the
    // same founder image. No NaN / undefined geometry either.
    const building = renderToHtml(React.createElement(BuildingScene, {
      model: buildBuilding(DATA, I1), attendedFloorId: 'p1', onAttend: () => {}, onOpenFloor: () => {},
    }))
    expect(building.length, 'building').toBeGreaterThan(800)
    expect(building, 'building').not.toMatch(/NaN|undefined/)
    expect(building).toContain('palace-zenaf-background')
    expect(building).toContain('palace-architecture')
    expect(building).toContain('palace-floor-p1')
    expect(building).toContain('palace-building-hearth')
    expect(building).toContain('palace-fire')
    // floor interiors are the founder's room plates (addendum
    // 2026-11-26 13:16 PT), assigned by size rank
    expect(building).toContain('palace-room-')
    // no text rides the circles (the founder's ruling,
    // 2026-11-26 14:03 PT: "Don't show the cards/tags/
    // percentages") — no share/count plaque, no released tag
    expect(building).not.toMatch(/\d+%\s*·/)
    expect(building).not.toContain('· released')
  })

  it('the room stands in its floor’s chamber — per-plate seats, the 1.5× flame, the hearth wall', () => {
    // The three chambers (founder, 2026-11-26 18:55 PT): a room
    // takes the plate of its floor; the flame stands 1.5× larger
    // in all three (heights 150 / 188 / 177 frame units); the
    // spiral and tiers hearths carry the plate's front wall back
    // over the flame's base, the rose hearth does not.
    const FLAME_ASPECT = 989 / 1530
    const flameHeight = (html: string): number => {
      const tag = html.match(/<img[^>]*palace-fire[^>]*>/)?.[0] ?? ''
      const widthPct = Number(tag.match(/width:\s*([\d.]+)%/)?.[1])
      return ((widthPct / 100) * 1254) / FLAME_ASPECT
    }
    const cases: { plate: RoomPlate; asset: string; flame: number; wall: boolean }[] = [
      { plate: 'rose', asset: 'palace-room-rose', flame: 150, wall: false },
      { plate: 'spiral', asset: 'palace-room-spiral', flame: 188, wall: true },
      { plate: 'tiers', asset: 'palace-room-tiers', flame: 177, wall: true },
    ]
    for (const c of cases) {
      const html = renderToHtml(React.createElement(RoomScene, {
        model: buildRoom(DATA, TASKS[0]), lit: true, plate: c.plate,
        onBringFire: () => {}, onThreshold: () => {},
        onOpenWaitedOn: () => {}, onFurniture: () => {}, onOpenSubtask: () => {},
      }))
      expect(html, c.plate).toContain(c.asset)
      expect(html, c.plate).not.toMatch(/NaN|undefined/)
      // the chamber's furniture stands at its own seats
      expect(html, c.plate).toContain('palace-room-scales')
      expect(html, c.plate).toContain('palace-room-chest')
      expect(html, c.plate).toContain('palace-room-table')
      expect(html, c.plate).toContain('palace-room-vessel')
      expect(html, c.plate).toContain('palace-room-hearth')
      // the flame, at this chamber's 1.5× height
      expect(html, c.plate).toContain('palace-fire')
      expect(flameHeight(html), c.plate).toBeGreaterThan(c.flame - 1.5)
      expect(flameHeight(html), c.plate).toBeLessThan(c.flame + 1.5)
      // the hearth's front wall: present on spiral and tiers,
      // absent on rose
      if (c.wall) {
        expect(html, c.plate).toContain('palace-room-hearth-wall')
      } else {
        expect(html, c.plate).not.toContain('palace-room-hearth-wall')
      }
    }
    // No plate named: the room stands in the rose chamber, as it
    // did before the three chambers were wired.
    const unplated = renderToHtml(React.createElement(RoomScene, {
      model: buildRoom(DATA, TASKS[0]), lit: true,
      onBringFire: () => {}, onThreshold: () => {},
      onOpenWaitedOn: () => {}, onFurniture: () => {}, onOpenSubtask: () => {},
    }))
    expect(unplated).toContain('palace-room-rose')
    expect(unplated).not.toContain('palace-room-hearth-wall')
  })
})
