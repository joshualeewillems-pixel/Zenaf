import { describe, expect, it } from 'vitest'
import { buildLiveVisionMapGraph } from './liveProjection'
import { columnCentersForProjectCounts, columnWidthForBranchCount } from './mapVisionLayout'
import { ZEN_SAND_RING_PATTERN } from './ZenSandCanvas'
import type { VisionMapEntityBundle } from './blockersFromVe'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import { fitZoomForBounds, graphBounds } from './mapFitView'

/**
 * Vision map consolidated open (2026-11-12): the founder opened the map on
 * his phone at 20% zoom — two clusters far apart, mostly empty canvas,
 * tiny labels. The open view must fit the whole garden (every cairn) and
 * the layout must be consolidated, not scattered.
 *
 * Fixture mirrors the founder's live garden: 26 cairns · 154 stones
 * (here 26 cairns · 160 stones: 2 initiatives × 13 projects × 5 tasks,
 * plus 2 source seeds + 2 trees).
 */

const NOW = new Date().toISOString()

function idea(id: string, title: string): Idea {
  return {
    id,
    title,
    summary: '',
    description: '',
    status: 'Exploring',
    tags: [],
    created_by: 'fixture',
    created_at: NOW,
    updated_at: NOW,
  }
}

function initiative(id: string, sourceIdeaId: string, title: string): Initiative {
  return {
    id,
    source_idea_id: sourceIdeaId,
    title,
    brief: '',
    status: 'Active',
    owner_id: null,
    evaluation_priority: 2,
    estimated_cost_ai: 'Medium',
    estimated_timeframe_ai: '4–6 weeks',
    philosophical_alignment_ai: 'Strong',
    next_step_ai: '',
    required_assets: [],
    dependencies: '',
    risks: '',
    recommendation: '',
    kill_criteria: '',
    notes: '',
    created_at: NOW,
    updated_at: NOW,
  }
}

function project(id: string, initiativeId: string, title: string): Project {
  return {
    id,
    initiative_id: initiativeId,
    title,
    brief: '',
    status: 'Active',
    owner_id: null,
    supporting_owner_ids: [],
    required_assets: [],
    priority: '2',
    start_date: null,
    end_date: null,
    estimated_weekly_hours: 4,
    next_step_ai: '',
    notes: '',
    created_at: NOW,
    updated_at: NOW,
  }
}

function task(id: string, projectId: string, title: string): Task {
  return {
    id,
    project_id: projectId,
    parent_task_id: null,
    title,
    description: '',
    assignee_id: null,
    status: 'Todo',
    priority: '2',
    estimated_hours: 2,
    due_date: null,
    dependency_ids: [],
    completion_criteria: '',
    notes: '',
    created_at: NOW,
    updated_at: NOW,
  }
}

function founderScaleBundle(): VisionMapEntityBundle {
  const ideas: Idea[] = []
  const initiatives: Initiative[] = []
  const projects: Project[] = []
  const tasks: Task[] = []
  const titles = ['Zenaf — outsourced executive function', 'Zenaf build directions']
  for (let c = 0; c < 2; c++) {
    const ideaId = `idea-${c}`
    ideas.push(idea(ideaId, `Seed ${c}`))
    const iniId = `ini-${c}`
    initiatives.push(initiative(iniId, ideaId, titles[c]!))
    for (let p = 0; p < 13; p++) {
      const projId = `proj-${c}-${p}`
      projects.push(project(projId, iniId, `Project ${c}-${p}`))
      for (let t = 0; t < 5; t++) {
        tasks.push(task(`task-${c}-${p}-${t}`, projId, `Task ${c}-${p}-${t}`))
      }
    }
  }
  return { ideas, initiatives, projects, tasks }
}

/** Phone pane the founder used, and a desktop pane, in CSS px. */
const PHONE_PANE = { width: 390, height: 1100 }
const DESKTOP_PANE = { width: 1440, height: 900 }

describe('vision map consolidated open — founder-scale garden', () => {
  it('collapses to 26 cairns over 160 stones at the narrow threshold', () => {
    const g = buildLiveVisionMapGraph(founderScaleBundle(), [], undefined, {
      cairnThreshold: 40,
    })
    expect(g.totalStones).toBe(160)
    expect(g.cairnCount).toBe(26)
    expect(g.cairned).toBe(true)
  })

  it('measures the cairn-mode garden bounds and fit zooms (logged for the report)', () => {
    const g = buildLiveVisionMapGraph(founderScaleBundle(), [], undefined, {
      cairnThreshold: 40,
    })
    const bounds = graphBounds(g.nodes)
    expect(bounds).not.toBeNull()
    const b = bounds!
    // The consolidated garden must fit on one phone screen width-wise with
    // room to spare: two initiative columns, no global max-width padding.
    // Pre-consolidation this measured 1895 wide (phone fit 0.179).
    expect(b.width).toBeLessThan(1850)
    const phoneZoom = fitZoomForBounds(b, PHONE_PANE, { padding: 0.15, minZoom: 0.15, maxZoom: 0.9 })
    const desktopZoom = fitZoomForBounds(b, DESKTOP_PANE, { padding: 0.15, minZoom: 0.15, maxZoom: 0.9 })
    console.log(
      `[consolidated-open] cairn-mode bounds ${Math.round(b.width)}x${Math.round(b.height)} ` +
        `phone fit zoom ${phoneZoom.toFixed(3)} desktop fit zoom ${desktopZoom.toFixed(3)}`,
    )
    // Desktop fit must leave tree labels (23px) readable: >= ~0.45.
    expect(desktopZoom).toBeGreaterThanOrEqual(0.45)
    // Phone fit is width-bound; the consolidated layout lifts it above the
    // pre-fix 0.179. Full phone label readability needs a compact
    // cairn-mode layout (open question — see report), not just this fit.
    expect(phoneZoom).toBeGreaterThanOrEqual(0.185)
  })

  it('sizes each initiative column by its own branch count, not the widest', () => {
    const wide = columnWidthForBranchCount(8)
    const narrow = columnWidthForBranchCount(2)
    expect(narrow).toBeLessThan(wide)
    // Uneven columns: total span is narrower than the old uniform layout
    // (every column paying for the widest initiative's arc).
    const centers = columnCentersForProjectCounts([2, 8])
    const span = centers[1]! + wide / 2 - (centers[0]! - narrow / 2)
    expect(span).toBeLessThan(2 * wide)
    expect(span).toBe(narrow + wide)
    // Equal counts reproduce the old uniform layout exactly.
    const uniform = columnCentersForProjectCounts([8, 8])
    expect(uniform[0]).toBe(wide / 2)
    expect(uniform[1]).toBe(wide + wide / 2)
    // Strictly increasing, no overlap.
    expect(centers[1]!).toBeGreaterThan(centers[0]!)
  })

  it('replaces ruled lines with low-contrast concentric rings', () => {
    const spec = ZEN_SAND_RING_PATTERN
    expect(spec.tilePx).toBeGreaterThan(0)
    expect(spec.ringStepPx).toBeGreaterThan(0)
    for (const f of spec.foci) {
      // Every ring stays fully inside the tile: no clipped arcs, no seams
      // where the tile repeats.
      const maxR = f.rings * spec.ringStepPx
      expect(f.x - maxR).toBeGreaterThanOrEqual(0)
      expect(f.y - maxR).toBeGreaterThanOrEqual(0)
      expect(f.x + maxR).toBeLessThanOrEqual(spec.tilePx)
      expect(f.y + maxR).toBeLessThanOrEqual(spec.tilePx)
    }
    // Texture, not drawing: strokes stay at alpha <= 0.10.
    expect(spec.alpha).toBeLessThanOrEqual(0.1)
    expect(spec.alphaAlternate).toBeLessThanOrEqual(0.1)
  })
})
