/**
 * Briefs grouping — the founder's parents/loose display rule
 * (2026-11-24: "All screens are overwhelmed and should only be
 * parents and loose by default"; 2026-11-25: "should be able to
 * un nest in all cases but default should be nested").
 *
 * The Content data model (types.ts) anchors every brief to the
 * Vision Execution hierarchy: a brief carries `linked_project_id`
 * and/or `linked_initiative_id`, and a Project carries
 * `initiative_id`. So the parent structure of the briefs list is:
 *
 *   Initiative (parent)
 *     └─ Project (parent, via Project.initiative_id)
 *          └─ Brief (child, via linked_project_id)
 *     └─ Brief (child, via linked_initiative_id directly)
 *   Project with no (resolvable) initiative — a loose parent
 *     └─ Brief
 *   Brief with no resolvable initiative/project link — loose
 *
 * The default listing shows only the top level of this grouping
 * (initiative parents, loose project parents, loose briefs);
 * children are revealed by expanding their parent in place.
 */
import type { ContentBrief } from './types'
import type { Initiative, Project } from '../vision-execution/types'

export interface BriefProjectGroup {
  project: Project
  briefs: ContentBrief[]
}

export interface BriefInitiativeGroup {
  initiative: Initiative
  /** Projects under this initiative that carry at least one brief. */
  projects: BriefProjectGroup[]
  /** Briefs linked directly to the initiative (no resolvable project). */
  directBriefs: ContentBrief[]
}

export interface BriefGrouping {
  initiativeGroups: BriefInitiativeGroup[]
  /** Projects carrying briefs whose initiative is missing/unresolvable. */
  looseProjects: BriefProjectGroup[]
  /** Briefs with no resolvable initiative or project parent. */
  looseBriefs: ContentBrief[]
}

/** Expand/collapse state keys for the briefs list parents. */
export const initiativeParentKey = (id: string) => `initiative:${id}`
export const projectParentKey = (id: string) => `project:${id}`

/** Every parent key present in a grouping (for expand-all). */
export function allBriefParentKeys(grouping: BriefGrouping): string[] {
  const keys: string[] = []
  for (const g of grouping.initiativeGroups) {
    keys.push(initiativeParentKey(g.initiative.id))
    for (const pg of g.projects) keys.push(projectParentKey(pg.project.id))
  }
  for (const pg of grouping.looseProjects) keys.push(projectParentKey(pg.project.id))
  return keys
}

export function countBriefsInInitiativeGroup(g: BriefInitiativeGroup): number {
  return g.directBriefs.length + g.projects.reduce((n, pg) => n + pg.briefs.length, 0)
}

export function groupBriefs(
  briefs: ContentBrief[],
  initiatives: Initiative[],
  projects: Project[],
): BriefGrouping {
  const initiativeById = new Map(initiatives.map((i) => [i.id, i]))
  const projectById = new Map(projects.map((p) => [p.id, p]))

  const initiativeGroups = new Map<string, BriefInitiativeGroup>()
  const looseProjectGroups = new Map<string, BriefProjectGroup>()
  const looseBriefs: ContentBrief[] = []

  const initiativeGroupFor = (initiative: Initiative): BriefInitiativeGroup => {
    let g = initiativeGroups.get(initiative.id)
    if (!g) {
      g = { initiative, projects: [], directBriefs: [] }
      initiativeGroups.set(initiative.id, g)
    }
    return g
  }
  const projectGroupIn = (
    list: BriefProjectGroup[],
    project: Project,
  ): BriefProjectGroup => {
    let pg = list.find((x) => x.project.id === project.id)
    if (!pg) {
      pg = { project, briefs: [] }
      list.push(pg)
    }
    return pg
  }

  for (const brief of briefs) {
    const project = brief.linked_project_id
      ? projectById.get(brief.linked_project_id)
      : undefined
    if (project) {
      const initiative = project.initiative_id
        ? initiativeById.get(project.initiative_id)
        : undefined
      if (initiative) {
        projectGroupIn(initiativeGroupFor(initiative).projects, project).briefs.push(brief)
      } else {
        // Project stands on its own (no resolvable initiative): a loose parent.
        let pg = looseProjectGroups.get(project.id)
        if (!pg) {
          pg = { project, briefs: [] }
          looseProjectGroups.set(project.id, pg)
        }
        pg.briefs.push(brief)
      }
      continue
    }
    const initiative = brief.linked_initiative_id
      ? initiativeById.get(brief.linked_initiative_id)
      : undefined
    if (initiative) {
      initiativeGroupFor(initiative).directBriefs.push(brief)
      continue
    }
    looseBriefs.push(brief)
  }

  // Parents render in the order their source collections arrived.
  const orderedInitiativeGroups = initiatives
    .map((i) => initiativeGroups.get(i.id))
    .filter((g): g is BriefInitiativeGroup => !!g)
  const orderedLooseProjects = projects
    .map((p) => looseProjectGroups.get(p.id))
    .filter((g): g is BriefProjectGroup => !!g)

  return {
    initiativeGroups: orderedInitiativeGroups,
    looseProjects: orderedLooseProjects,
    looseBriefs,
  }
}
