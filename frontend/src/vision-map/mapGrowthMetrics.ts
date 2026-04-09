/**
 * Growth triad (0–1): Water / Soil / Fruit — derived only from existing VE + map payload fields.
 *
 * **Soil** = grounding / substrate depth (filled brief, boundaries, criteria, etc.). Map **soil rim** visualizes
 * **deficit** (`1 − soil`), not presence. Not recency (water) or structural strain (condition). Council summary
 * nudges soil as “formed meaning,” not pulse.
 */
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import type { VisionMapEntityBundle } from './blockersFromVe'
import { MAP_SOIL_TIER_LOW_BELOW, MAP_SOIL_TIER_MEDIUM_BELOW } from './mapNodeAppearance'
import type { MapNodePayload } from './ontology'
import { effectiveGrowthTriad } from './effectiveGrowthTriad'

export type GrowthTriadMetrics = {
  water: number
  soil: number
  fruit: number
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}

/** Presence of text: 0–1 from length tiers */
function textDepth(s: string | null | undefined, tiers: number[]): number {
  const n = (s || '').trim().length
  let v = 0
  for (let i = 0; i < tiers.length; i++) {
    if (n >= tiers[i]!) v = (i + 1) / tiers.length
  }
  return v
}

/** Water: ownership, assignments, recency, council — aligns with map `water_level` + pulse */
export function computeWaterLevel(p: MapNodePayload): number {
  const base = p.water_level === 'high' ? 0.88 : p.water_level === 'medium' ? 0.52 : 0.26
  let x = base
  if (p.fertilizer_pulse) x += 0.09
  if (p.councilTeacher?.summary?.trim()) x += 0.06
  if (p.councilTeacher?.last_run_at) x += 0.04
  return clamp01(x)
}

function soilFromIdea(e: Idea): number {
  const desired = textDepth(e.desired_outcome, [12, 48, 120])
  const sum = textDepth(e.summary, [20, 80, 200])
  const desc = textDepth(e.description, [40, 150, 400])
  const notes = textDepth(e.notes, [25, 90, 220])
  const links = clamp01(((e.linked_people?.length ?? 0) + (e.linked_ideas?.length ?? 0)) * 0.1)
  return clamp01(0.1 + desired * 0.28 + sum * 0.24 + desc * 0.2 + notes * 0.14 + links)
}

function soilFromInitiative(e: Initiative): number {
  const brief = textDepth(e.brief, [30, 100, 220])
  const notes = textDepth(e.notes, [25, 100, 260])
  const next = textDepth(e.next_step_ai, [15, 60, 140])
  const risks = textDepth(e.risks, [10, 60, 160])
  const deps = textDepth(e.dependencies, [10, 50, 140])
  const kill = textDepth(e.kill_criteria, [8, 40, 100])
  const rec = textDepth(e.recommendation, [20, 80, 200])
  const align = textDepth(e.philosophical_alignment_ai, [20, 80, 180])
  const estCost = textDepth(e.estimated_cost_ai, [8, 40, 90])
  const estTime = textDepth(e.estimated_timeframe_ai, [8, 40, 90])
  const seats = (e.seats ?? []).filter((s) => s.assigned_person_id?.trim()).length
  const seatScore = clamp01(seats * 0.05 + (e.owner_id?.trim() ? 0.06 : 0))
  return clamp01(
    0.08 +
      brief * 0.22 +
      notes * 0.12 +
      next * 0.12 +
      risks * 0.1 +
      deps * 0.1 +
      kill * 0.06 +
      rec * 0.08 +
      align * 0.06 +
      (estCost + estTime) * 0.04 +
      seatScore,
  )
}

function soilFromProject(e: Project): number {
  const brief = textDepth(e.brief, [25, 90, 200])
  const next = textDepth(e.next_step_ai, [12, 50, 120])
  const deliv = textDepth(e.deliverables, [15, 80, 200])
  const notes = textDepth(e.notes, [20, 100, 280])
  const dates = (e.start_date ? 0.05 : 0) + (e.end_date ? 0.05 : 0)
  const assets = clamp01((e.required_assets?.length ?? 0) * 0.04)
  return clamp01(0.08 + brief * 0.24 + next * 0.14 + deliv * 0.16 + notes * 0.14 + dates + assets)
}

function soilFromTask(e: Task): number {
  const crit = textDepth(e.completion_criteria, [15, 60, 140])
  const desc = textDepth(e.description, [20, 80, 180])
  const notes = textDepth(e.notes, [15, 70, 200])
  const deps = clamp01((e.dependency_ids?.length ?? 0) * 0.06)
  const assets = clamp01((e.required_asset_ids?.length ?? 0) * 0.05)
  return clamp01(0.12 + crit * 0.32 + desc * 0.24 + notes * 0.12 + deps + assets)
}

function fruitFromGrowth(g: MapNodePayload['growth']): number {
  if (g === 'fruiting') return 0.88
  if (g === 'growing') return 0.55
  if (g === 'germinating') return 0.32
  if (g === 'dormant') return 0.18
  if (g === 'decaying') return 0.25
  if (g === 'pruned') return 0.12
  return 0.4
}

function statusDone(s: string | null | undefined): boolean {
  return /\b(done|complete|completed|shipped|closed|won)\b/i.test(s || '')
}

/** Fruit: deliverables, done tasks, shipped-ish status */
export function computeFruitProgress(p: MapNodePayload, bundle: VisionMapEntityBundle | null): number {
  if (p.kind === 'fruit') return 0.92

  const g = fruitFromGrowth(p.growth)
  if (!bundle) return clamp01(g)

  const { ref } = p
  if (ref.veType === 'task') {
    const t = bundle.tasks.find((x) => x.id === ref.id)
    if (!t) return clamp01(g)
    const done = statusDone(t.status) ? 0.95 : g * 0.85
    return clamp01(done)
  }

  if (ref.veType === 'project') {
    const proj = bundle.projects.find((x) => x.id === ref.id)
    if (!proj) return clamp01(g)
    const tasks = bundle.tasks.filter((t) => t.project_id === proj.id)
    const doneN = tasks.filter((t) => statusDone(t.status)).length
    const ratio = tasks.length ? doneN / tasks.length : 0
    const delivBoost = (proj.deliverables || '').trim().length > 30 ? 0.18 : (proj.deliverables || '').trim().length > 0 ? 0.08 : 0
    const shipped = statusDone(proj.status) ? 0.35 : 0
    return clamp01(g * 0.35 + ratio * 0.42 + delivBoost + shipped)
  }

  if (ref.veType === 'initiative') {
    const projs = bundle.projects.filter((x) => x.initiative_id === ref.id)
    if (projs.length === 0) return clamp01(g * 0.4)
    let doneProj = 0
    let taskRatioSum = 0
    for (const pr of projs) {
      if (statusDone(pr.status)) doneProj += 1
      const ts = bundle.tasks.filter((t) => t.project_id === pr.id)
      const dn = ts.filter((t) => statusDone(t.status)).length
      taskRatioSum += ts.length ? dn / ts.length : 0
    }
    const pr = doneProj / projs.length
    const tr = taskRatioSum / projs.length
    return clamp01(g * 0.25 + pr * 0.35 + tr * 0.35)
  }

  if (ref.veType === 'idea') {
    const idea = bundle.ideas.find((x) => x.id === ref.id)
    if (idea && statusDone(idea.status)) return 0.55
    return clamp01(g * 0.7)
  }

  return clamp01(g)
}

/**
 * Council runs that produced a substantive summary count as “formation” (soil), not pulse (water).
 * Capped so this never outweighs actual filled VE fields.
 */
export function councilFormationSoilBump(p: MapNodePayload): number {
  const s = (p.councilTeacher?.summary || '').trim()
  if (s.length >= 160) return 0.08
  if (s.length >= 72) return 0.055
  if (s.length >= 24) return 0.03
  if (p.councilTeacher?.last_run_at) return 0.018
  return 0
}

/** Soil: structural completeness from VE row (+ small council-summary formation bump). */
export function computeSoilQuality(p: MapNodePayload, bundle: VisionMapEntityBundle | null): number {
  let base: number
  if (p.kind === 'fruit') {
    const parentId = p.parentRef?.id
    if (!bundle || !parentId) base = 0.62
    else {
      const proj = bundle.projects.find((x) => x.id === parentId)
      base = proj ? soilFromProject(proj) * 0.85 + 0.08 : 0.58
    }
  } else if (!bundle) {
    base = clamp01(0.28 + textDepth(p.summaryLines.join(' '), [40, 120, 280]) * 0.5)
  } else {
    const { ref } = p
    if (ref.veType === 'idea') {
      const e = bundle.ideas.find((x) => x.id === ref.id)
      base = e ? soilFromIdea(e) : 0.3
    } else if (ref.veType === 'initiative') {
      const e = bundle.initiatives.find((x) => x.id === ref.id)
      base = e ? soilFromInitiative(e) : 0.3
    } else if (ref.veType === 'project') {
      const e = bundle.projects.find((x) => x.id === ref.id)
      base = e ? soilFromProject(e) : 0.3
    } else if (ref.veType === 'task') {
      const e = bundle.tasks.find((x) => x.id === ref.id)
      base = e ? soilFromTask(e) : 0.3
    } else base = 0.42
  }

  return clamp01(base + councilFormationSoilBump(p))
}

export function computeGrowthTriad(p: MapNodePayload, bundle: VisionMapEntityBundle | null): GrowthTriadMetrics {
  return {
    water: computeWaterLevel(p),
    soil: computeSoilQuality(p, bundle),
    fruit: computeFruitProgress(p, bundle),
  }
}

/**
 * Triad for map + panel. Server `growth_triad.soil` is field-depth only; add council formation bump here
 * so soil can reflect meaning captured in council summaries without touching water (recency).
 */
export function mapVisualTriad(p: MapNodePayload, bundle: VisionMapEntityBundle | null): GrowthTriadMetrics {
  const base = effectiveGrowthTriad(p, bundle)
  const server =
    p.vitality_source === 'server' &&
    p.growth_triad &&
    typeof p.growth_triad.soil === 'number' &&
    Number.isFinite(p.growth_triad.soil)
  if (server) {
    return { ...base, soil: clamp01(base.soil + councilFormationSoilBump(p)) }
  }
  return base
}

/** One short sentence; visuals carry most meaning */
export function growthTriadCaption(m: GrowthTriadMetrics, kindLabel: string): string {
  const lowW = m.water < 0.38
  const lowS = m.soil < MAP_SOIL_TIER_LOW_BELOW
  const lowF = m.fruit < 0.35
  const hiF = m.fruit > 0.72

  const parts: string[] = []
  if (lowW) parts.push('under-watered')
  if (lowS) parts.push('lightly grounded')
  if (lowF && !hiF) parts.push('little output yet')
  if (hiF && !lowF) parts.push('strong output signal')

  if (parts.length === 0) {
    if (m.water > 0.75 && m.soil >= MAP_SOIL_TIER_MEDIUM_BELOW) return `${kindLabel} reads tended and well grounded.`
    return `${kindLabel} shows mixed signals — use the bars as a quick read.`
  }

  const join = parts.slice(0, 2).join(' and ')
  return `${kindLabel} is ${join}.`
}
