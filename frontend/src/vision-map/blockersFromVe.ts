import type { Asset, Idea, Initiative, Person, Project, Task } from '../vision-execution/types'
import type { MapEntityRef } from './ontology'

export type VisionMapEntityBundle = {
  ideas: Idea[]
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  /** Garden landmarks (people/assets) — rendered without growth glyphs. Optional for callers that don't fetch them. */
  persons?: Person[]
  assets?: Asset[]
}

function taskBlocked(t: Task): boolean {
  return /\bblock/i.test(t.status || '') || /\bblock/i.test(t.notes || '')
}

function linesForRef(ref: MapEntityRef, b: VisionMapEntityBundle): string[] {
  const lines: string[] = []
  if (ref.veType === 'task') {
    const t = b.tasks.find((x) => x.id === ref.id)
    if (t) {
      if (taskBlocked(t)) lines.push(`Task is marked blocked: ${t.title}`)
      if ((t.notes || '').trim()) lines.push(`Task notes: ${t.notes.trim()}`)
      if ((t.description || '').trim()) lines.push(`Description: ${String(t.description).slice(0, 200)}`)
    }
    return lines
  }
  if (ref.veType === 'project') {
    const p = b.projects.find((x) => x.id === ref.id)
    if (p) {
      if ((p.notes || '').trim()) lines.push(`Project notes: ${p.notes.trim()}`)
      const subs = b.tasks.filter((t) => t.project_id === p.id)
      const blk = subs.filter(taskBlocked)
      if (blk.length) lines.push(`${blk.length} blocked task(s) under this project.`)
      blk.forEach((t) => lines.push(`  · ${t.title}`))
    }
    return lines
  }
  if (ref.veType === 'initiative') {
    const i = b.initiatives.find((x) => x.id === ref.id)
    if (i) {
      if ((i.risks || '').trim()) lines.push(`Risks (initiative): ${i.risks.trim()}`)
      if ((i.dependencies || '').trim()) lines.push(`Dependencies: ${i.dependencies.trim()}`)
      const projs = b.projects.filter((p) => p.initiative_id === i.id)
      for (const p of projs) {
        const blk = b.tasks.filter((t) => t.project_id === p.id && taskBlocked(t))
        if (blk.length) lines.push(`Project "${p.title}": ${blk.length} blocked task(s)`)
      }
    }
    return lines
  }
  if (ref.veType === 'idea') {
    const idea = b.ideas.find((x) => x.id === ref.id)
    if (idea && (idea.description || '').length > 400) {
      lines.push('Large idea body — scan for constraints in operator view.')
    }
    return lines
  }
  return lines
}

export function deriveBlockersMarkdown(ref: MapEntityRef | null, b: VisionMapEntityBundle | null): string {
  if (!ref || !b) return ''
  const lines = linesForRef(ref, b)
  if (!lines.length) return 'No obvious blockers detected from status/notes/risks on this slice (projection heuristic).'
  return lines.map((l) => (l.startsWith('  ·') ? l : `• ${l}`)).join('\n')
}
