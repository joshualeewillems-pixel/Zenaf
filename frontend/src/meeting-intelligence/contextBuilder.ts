/**
 * Build ExtractionContext from domain entity lists for pre-extraction context.
 * Kept compact for the extractor.
 */

import type { ExtractionContext } from './types'

export interface DomainInitiatives {
  id: string
  title: string
}

export interface DomainProjects {
  id: string
  title: string
  initiative_id?: string | null
}

export interface DomainTasks {
  id: string
  title: string
  project_id: string | null
}

export interface DomainAssets {
  id: string
  name: string
  asset_type?: string
}

export interface DomainPersons {
  id: string
  name: string
  role?: string
}

/** Build compact ExtractionContext from loaded domain state. */
export function buildExtractionContext(
  initiatives: DomainInitiatives[],
  projects: DomainProjects[],
  tasks: DomainTasks[],
  assets: DomainAssets[],
  persons: DomainPersons[]
): ExtractionContext {
  const initiativeById = new Map(initiatives.map((i) => [i.id, i]))
  const projectById = new Map(projects.map((p) => [p.id, p]))

  return {
    initiatives: initiatives.map((i) => ({ id: i.id, title: i.title || '' })),
    projects: projects.map((p) => {
      const init = p.initiative_id ? initiativeById.get(p.initiative_id) : null
      return {
        id: p.id,
        title: p.title || '',
        initiativeId: p.initiative_id ?? undefined,
        initiativeTitle: init?.title,
      }
    }),
    tasks: tasks.map((t) => {
      const proj = t.project_id ? projectById.get(t.project_id) : undefined
      const init = proj?.initiative_id ? initiativeById.get(proj.initiative_id) : null
      return {
        id: t.id,
        title: t.title || '',
        projectId: t.project_id ?? undefined,
        projectTitle: proj?.title,
        initiativeId: proj?.initiative_id ?? undefined,
        initiativeTitle: init?.title,
      }
    }),
    assets: assets.map((a) => ({ id: a.id, name: a.name || '', kind: a.asset_type })),
    people: persons.map((p) => ({ id: p.id, name: p.name || '', role: p.role })),
  }
}
