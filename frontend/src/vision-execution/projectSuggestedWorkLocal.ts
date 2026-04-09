/**
 * Phase 1: Suggested work (AI) — client-only checked state + last generated items per project.
 * Not synced; regenerating replaces items and clears checks.
 */

const STORAGE_KEY = 'zenaf-project-suggested-work-v1'

export type ProjectSuggestionKind =
  | 'missing_ownership'
  | 'uncovered_work'
  | 'coordination_gap'
  | 'unclear_scope'

export type ProjectSuggestionItem = {
  id: string
  kind: ProjectSuggestionKind
  text: string
}

export type ProjectSuggestionLocalState = {
  items: ProjectSuggestionItem[]
  checkedIds: string[]
}

type Store = Record<string, ProjectSuggestionLocalState>

function loadAll(): Store {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
    if (!raw) return {}
    const p = JSON.parse(raw) as unknown
    if (!p || typeof p !== 'object') return {}
    return p as Store
  } catch {
    return {}
  }
}

function saveAll(store: Store) {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    /* quota */
  }
}

export function loadProjectSuggestionState(projectId: string): ProjectSuggestionLocalState | null {
  const s = loadAll()[projectId]
  if (!s || !Array.isArray(s.items)) return null
  return {
    items: s.items.filter((x) => x && typeof x.id === 'string' && typeof x.text === 'string'),
    checkedIds: Array.isArray(s.checkedIds) ? s.checkedIds.filter((id) => typeof id === 'string') : [],
  }
}

export function saveProjectSuggestionState(projectId: string, state: ProjectSuggestionLocalState) {
  const all = loadAll()
  all[projectId] = {
    items: state.items,
    checkedIds: state.checkedIds,
  }
  saveAll(all)
}

/** New generation replaces items and clears checked IDs. */
export function setGeneratedSuggestions(projectId: string, items: ProjectSuggestionItem[]) {
  saveProjectSuggestionState(projectId, { items, checkedIds: [] })
}

/** Remove stored suggestions for a project (user dismissed the AI batch). */
export function clearProjectSuggestions(projectId: string) {
  const all = loadAll()
  delete all[projectId]
  saveAll(all)
}

export function toggleSuggestionChecked(projectId: string, suggestionId: string) {
  const cur = loadProjectSuggestionState(projectId)
  if (!cur) return
  const set = new Set(cur.checkedIds)
  if (set.has(suggestionId)) set.delete(suggestionId)
  else set.add(suggestionId)
  saveProjectSuggestionState(projectId, { ...cur, checkedIds: [...set] })
}

export const PROJECT_SUGGESTION_KIND_LABEL: Record<ProjectSuggestionKind, string> = {
  missing_ownership: 'Missing ownership',
  uncovered_work: 'Uncovered work',
  coordination_gap: 'Coordination gap',
  unclear_scope: 'Unclear scope',
}
