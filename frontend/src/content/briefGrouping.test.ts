/**
 * Briefs grouping — the parents/loose display rule for the Content
 * briefs list: Initiative > Project > Brief, loose projects as
 * their own parents, unanchored briefs loose.
 */
import { describe, it, expect } from 'vitest'
import type { ContentBrief } from './types'
import { DEFAULT_BRIEF_PAYLOAD } from './types'
import type { Initiative, Project } from '../vision-execution/types'
import {
  allBriefParentKeys,
  countBriefsInInitiativeGroup,
  groupBriefs,
  initiativeParentKey,
  projectParentKey,
} from './briefGrouping'

function brief(partial: Partial<ContentBrief> & { id: string }): ContentBrief {
  return {
    ...DEFAULT_BRIEF_PAYLOAD,
    title: partial.id,
    status: 'draft',
    ...partial,
  }
}

function initiative(partial: Partial<Initiative> & { id: string }): Initiative {
  return {
    source_idea_id: null,
    title: partial.id,
    brief: '',
    status: 'Active',
    owner_id: null,
    evaluation_priority: null,
    estimated_cost_ai: '',
    estimated_timeframe_ai: '',
    philosophical_alignment_ai: '',
    next_step_ai: '',
    required_assets: [],
    dependencies: '',
    risks: '',
    recommendation: '',
    kill_criteria: '',
    notes: '',
    created_at: '2026-05-01T00:00:00',
    updated_at: '2026-05-01T00:00:00',
    ...partial,
  }
}

function project(partial: Partial<Project> & { id: string }): Project {
  return {
    initiative_id: null,
    title: partial.id,
    brief: '',
    status: 'Active',
    owner_id: null,
    supporting_owner_ids: [],
    priority: '',
    start_date: null,
    end_date: null,
    estimated_weekly_hours: null,
    next_step_ai: '',
    notes: '',
    created_at: '2026-05-01T00:00:00',
    updated_at: '2026-05-01T00:00:00',
    ...partial,
  }
}

const INITIATIVES = [initiative({ id: 'i1', title: 'Alpha' }), initiative({ id: 'i2', title: 'Empty' })]
const PROJECTS = [
  project({ id: 'p1', initiative_id: 'i1', title: 'Alpha Project' }),
  project({ id: 'p2', initiative_id: null, title: 'Loose Project' }),
]

describe('groupBriefs', () => {
  it('nests briefs under initiative > project, initiative-direct, loose project, and loose', () => {
    const grouping = groupBriefs(
      [
        brief({ id: 'b-nested', linked_project_id: 'p1' }),
        brief({ id: 'b-direct', linked_initiative_id: 'i1' }),
        brief({ id: 'b-loose-project', linked_project_id: 'p2' }),
        brief({ id: 'b-loose' }),
      ],
      INITIATIVES,
      PROJECTS,
    )
    expect(grouping.initiativeGroups).toHaveLength(1)
    const g = grouping.initiativeGroups[0]!
    expect(g.initiative.id).toBe('i1')
    expect(g.projects.map((pg) => pg.project.id)).toEqual(['p1'])
    expect(g.projects[0]!.briefs.map((b) => b.id)).toEqual(['b-nested'])
    expect(g.directBriefs.map((b) => b.id)).toEqual(['b-direct'])
    expect(countBriefsInInitiativeGroup(g)).toBe(2)
    expect(grouping.looseProjects.map((pg) => pg.project.id)).toEqual(['p2'])
    expect(grouping.looseProjects[0]!.briefs.map((b) => b.id)).toEqual(['b-loose-project'])
    expect(grouping.looseBriefs.map((b) => b.id)).toEqual(['b-loose'])
  })

  it('treats dangling links as loose and a project link as winning over the initiative link', () => {
    const grouping = groupBriefs(
      [
        brief({ id: 'b-dangling', linked_project_id: 'gone', linked_initiative_id: 'also-gone' }),
        brief({ id: 'b-both', linked_project_id: 'p2', linked_initiative_id: 'i1' }),
      ],
      INITIATIVES,
      PROJECTS,
    )
    expect(grouping.looseBriefs.map((b) => b.id)).toEqual(['b-dangling'])
    // p2 has no initiative, so the brief lands under the loose project parent.
    expect(grouping.looseProjects[0]!.briefs.map((b) => b.id)).toEqual(['b-both'])
    expect(grouping.initiativeGroups).toHaveLength(0)
  })

  it('omits parents that carry no briefs and lists every parent key for expand-all', () => {
    const grouping = groupBriefs(
      [brief({ id: 'b-nested', linked_project_id: 'p1' }), brief({ id: 'b-loose-project', linked_project_id: 'p2' })],
      INITIATIVES,
      PROJECTS,
    )
    // i2 ('Empty') carries no brief, so it is not a listing parent.
    expect(grouping.initiativeGroups.map((g) => g.initiative.id)).toEqual(['i1'])
    expect(allBriefParentKeys(grouping).sort()).toEqual(
      [initiativeParentKey('i1'), projectParentKey('p1'), projectParentKey('p2')].sort(),
    )
  })
})
