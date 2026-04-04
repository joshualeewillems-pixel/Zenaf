/**
 * Lightweight chooser for "Link": attach extracted candidate to an existing object
 * instead of creating a new one. Options: use as same item (match existing),
 * or place as child of selected parent.
 *
 * Workspace picker mirrors Execution list hierarchy (initiative → project → task),
 * same affordances as VisionExecutionView list mode.
 */

import { useCallback, useMemo, useState } from 'react'
import type { ExistingEntities } from './ReviewExtractionScreen'

export type LinkAction = 'use_existing' | 'child_of'

/** Section keys that contain linkable entities (ideas, initiatives, projects, tasks, assets, people, signals). */
export type LinkableSectionKey = 'ideas' | 'initiatives' | 'projects' | 'tasks' | 'assets' | 'people' | 'signals'

export type NoteTargetEntityType = 'idea' | 'initiative' | 'project' | 'task'

type EntityType = NoteTargetEntityType

type LinkChooserBaseProps = {
  existingEntities: ExistingEntities
  onClose: () => void
}

export type LinkChooserProps =
  | (LinkChooserBaseProps & {
      mode?: 'link'
      currentSectionKey: LinkableSectionKey
      onChoose: (action: LinkAction, entityType: EntityType, id: string) => void
    })
  | (LinkChooserBaseProps & {
      mode: 'pick_note_target'
      onPickNoteTarget: (entityType: EntityType, id: string) => void | Promise<void>
    })

/** Valid parent type for "place under" by current item kind. */
const VALID_PARENT_BY_KIND: Record<LinkableSectionKey, EntityType[] | null> = {
  /** Ideas can attach under execution tree (same as Suggest placement parent intent). */
  ideas: ['initiative', 'project', 'task'],
  initiatives: ['idea'],
  projects: ['initiative'],
  tasks: ['project'],
  assets: null,
  people: null,
  signals: ['initiative', 'project', 'task'],
}

/** Entity types that can be "use existing" for this section (same or compatible). */
const VALID_USE_EXISTING_BY_KIND: Record<LinkableSectionKey, EntityType[]> = {
  ideas: ['idea'],
  initiatives: ['initiative'],
  projects: ['project'],
  tasks: ['task'],
  assets: [],
  people: [],
  signals: [],
}

function truncateText(text: string | null | undefined, maxChars: number): string {
  const s = (text ?? '').replace(/\s+/g, ' ').trim()
  if (!s) return ''
  return s.length <= maxChars ? s : `${s.slice(0, Math.max(0, maxChars - 1))}…`
}

function normalizeQuery(q: string): string {
  return q.trim().toLowerCase()
}

function textMatches(queryNorm: string, ...parts: (string | null | undefined)[]): boolean {
  if (!queryNorm) return true
  for (const p of parts) {
    if (p != null && String(p).toLowerCase().includes(queryNorm)) return true
  }
  return false
}

export function LinkChooser(props: LinkChooserProps) {
  const { existingEntities, onClose } = props
  const isPickNote = props.mode === 'pick_note_target'
  const currentSectionKey = isPickNote ? ('tasks' as LinkableSectionKey) : props.currentSectionKey
  const onChoose = !isPickNote ? props.onChoose : undefined
  const onPickNoteTarget = isPickNote ? props.onPickNoteTarget : undefined

  const [query, setQuery] = useState('')
  const [selectedType, setSelectedType] = useState<EntityType>('initiative')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [collapsedInitiatives, setCollapsedInitiatives] = useState<Set<string>>(() => new Set())
  const [collapsedProjects, setCollapsedProjects] = useState<Set<string>>(() => new Set())
  const [pickBusy, setPickBusy] = useState(false)

  const validUseExisting = VALID_USE_EXISTING_BY_KIND[currentSectionKey] ?? []
  const validParents = VALID_PARENT_BY_KIND[currentSectionKey] ?? []
  const canUseExisting = validUseExisting.length > 0
  const canPlaceUnder = validParents.length > 0

  const ideas = existingEntities.ideas ?? []
  const initiatives = existingEntities.initiatives ?? []
  const projects = existingEntities.projects ?? []
  const tasks = existingEntities.tasks ?? []

  const qn = useMemo(() => normalizeQuery(query), [query])

  const taskMatches = useCallback(
    (t: (typeof tasks)[number]) => textMatches(qn, t.title, t.description),
    [qn],
  )
  const projectMatches = useCallback(
    (p: (typeof projects)[number]) => {
      if (textMatches(qn, p.title, p.brief)) return true
      return tasks.some((t) => t.project_id === p.id && taskMatches(t))
    },
    [qn, tasks, taskMatches],
  )
  const initiativeMatches = useCallback(
    (i: (typeof initiatives)[number]) => {
      if (textMatches(qn, i.title, i.brief)) return true
      return projects.some((p) => p.initiative_id === i.id && projectMatches(p))
    },
    [qn, projects, projectMatches],
  )

  const visibleIdeas = useMemo(
    () => ideas.filter((i) => textMatches(qn, i.title, i.summary, i.description)),
    [ideas, qn],
  )

  const visibleInitiatives = useMemo(
    () => initiatives.filter((i) => initiativeMatches(i)),
    [initiatives, initiativeMatches],
  )

  const projectsForInitiative = useCallback(
    (initiativeId: string) => projects.filter((p) => p.initiative_id === initiativeId && projectMatches(p)),
    [projects, projectMatches],
  )

  const tasksForProject = useCallback(
    (projectId: string) => tasks.filter((t) => t.project_id === projectId && taskMatches(t)),
    [tasks, taskMatches],
  )

  const unanchoredProjects = useMemo(
    () => projects.filter((p) => !p.initiative_id && projectMatches(p)),
    [projects, projectMatches],
  )

  const orphanTasks = useMemo(
    () => tasks.filter((t) => !t.project_id && taskMatches(t)),
    [tasks, taskMatches],
  )

  const selectedTitle = useMemo(() => {
    if (!selectedId) return null
    const idea = ideas.find((x) => x.id === selectedId)
    if (idea && selectedType === 'idea') return idea.title || selectedId
    const init = initiatives.find((x) => x.id === selectedId)
    if (init && selectedType === 'initiative') return init.title || selectedId
    const proj = projects.find((x) => x.id === selectedId)
    if (proj && selectedType === 'project') return proj.title || selectedId
    const task = tasks.find((x) => x.id === selectedId)
    if (task && selectedType === 'task') return task.title || selectedId
    return selectedId
  }, [selectedId, selectedType, ideas, initiatives, projects, tasks])

  const showUseExisting = canUseExisting && validUseExisting.includes(selectedType)
  const showPlaceUnder = canPlaceUnder && validParents.includes(selectedType)

  const toggleInitiativeCollapsed = useCallback((id: string) => {
    setCollapsedInitiatives((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleProjectCollapsed = useCallback((id: string) => {
    setCollapsedProjects((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const handlePickItem = (entityType: EntityType, id: string) => {
    setSelectedType(entityType)
    setSelectedId(selectedId === id && selectedType === entityType ? null : id)
  }

  const handleAccept = () => {
    if (!selectedId || !selectedTitle || pickBusy) return
    if (isPickNote) {
      if (!onPickNoteTarget) return
      setPickBusy(true)
      void Promise.resolve(onPickNoteTarget(selectedType, selectedId))
        .then(() => onClose())
        .finally(() => setPickBusy(false))
      return
    }
    if (!onChoose) return
    if (showUseExisting) {
      onChoose('use_existing', selectedType, selectedId)
    } else {
      onChoose('child_of', selectedType, selectedId)
    }
    onClose()
  }

  const rowSelected = (type: EntityType, id: string) => selectedId === id && selectedType === type

  const renderIdeaRow = (idea: (typeof ideas)[number]) => (
    <div
      key={idea.id}
      role="button"
      tabIndex={0}
      onClick={() => handlePickItem('idea', idea.id)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          handlePickItem('idea', idea.id)
        }
      }}
      className={`rounded-lg border p-2.5 text-sm cursor-pointer ${
        rowSelected('idea', idea.id) ? 'border-amber-500 bg-amber-900/20' : 'border-slate-600 bg-slate-800/50'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-slate-200 truncate">{idea.title}</span>
        <span className="text-slate-500 text-[11px] shrink-0">Idea</span>
      </div>
      <p className="text-slate-400 text-xs mt-0.5 truncate">
        {truncateText(idea.summary ?? idea.description, 72) || 'No details yet'}
      </p>
    </div>
  )

  const hasExecutionBlock =
    visibleInitiatives.length > 0 || unanchoredProjects.length > 0 || orphanTasks.length > 0

  const hasAnyExecutionData = initiatives.length > 0 || projects.length > 0 || tasks.length > 0

  return (
    <div className="rounded-lg border border-slate-600 bg-slate-800 p-4 shadow-xl min-w-[320px] max-w-[28rem] flex flex-col max-h-[85vh]">
      <div className="flex justify-between items-center gap-2 mb-3 shrink-0">
        <h4 className="text-sm font-medium text-slate-200">
          {isPickNote ? 'Add note to…' : 'Link to existing'}
        </h4>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleAccept}
            disabled={!selectedId || pickBusy}
            className={`px-2.5 py-1 rounded disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium ${
              isPickNote ? 'bg-violet-600 hover:bg-violet-500' : 'bg-emerald-600 hover:bg-emerald-500'
            }`}
          >
            {pickBusy ? 'Saving…' : isPickNote ? 'Append note' : 'Accept'}
          </button>
          <button
            type="button"
            disabled={pickBusy}
            onClick={onClose}
            className="px-2.5 py-1 rounded border border-slate-500 text-slate-300 hover:bg-slate-700 text-sm disabled:opacity-50"
          >
            Close
          </button>
        </div>
      </div>
      <p className="text-slate-500 text-xs mb-3 shrink-0">
        {isPickNote ? (
          <>
            Pick an <strong className="text-slate-400">idea</strong>, or a row in <strong className="text-slate-400">Execution</strong>{' '}
            (initiative → project → task). Append adds a dated block to that record&apos;s notes; the review row is removed — nothing new is created.
          </>
        ) : (
          <>
            Start under <strong className="text-slate-400">Execution</strong> — expand initiatives to see projects and tasks, pick where this item belongs, then Accept.
            Use <strong className="text-slate-400">Ideas</strong> below only when it should match an existing idea record.
          </>
        )}
      </p>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search execution tree and ideas…"
        className="w-full px-2 py-1.5 rounded bg-slate-900 border border-slate-600 text-slate-100 text-sm mb-2 shrink-0"
      />
      <div className="min-h-0 max-h-[min(50vh,26rem)] overflow-y-auto space-y-3 mb-2 pr-0.5">
        {/* Execution tree first: where extracted work usually lands (initiative → project → task). */}
        <div>
          <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">Execution</div>
          {hasExecutionBlock ? (
            <div className="space-y-1">
              {visibleInitiatives.map((init) => {
                const childProjs = projectsForInitiative(init.id)
                const initExpanded = !collapsedInitiatives.has(init.id)
                const summaryText = truncateText(init.brief, 72) || 'No brief'
                return (
                  <div key={init.id}>
                    <div
                      className={`rounded-lg border p-2.5 text-sm cursor-pointer flex items-start gap-2 ${
                        rowSelected('initiative', init.id)
                          ? 'border-amber-500 bg-amber-900/20'
                          : 'border-slate-600 bg-slate-800/50'
                      }`}
                      onClick={() => handlePickItem('initiative', init.id)}
                    >
                      <span
                        className="text-slate-400 select-none shrink-0"
                        onClick={(e) => {
                          e.stopPropagation()
                          toggleInitiativeCollapsed(init.id)
                        }}
                      >
                        {childProjs.length > 0 ? (initExpanded ? '▼' : '▶') : '·'}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-slate-200 truncate">{init.title}</span>
                          <span className="text-slate-500 text-[11px] shrink-0">Initiative · {init.status || '—'}</span>
                        </div>
                        <p className="text-slate-400 text-xs mt-0.5 truncate">{summaryText}</p>
                      </div>
                    </div>
                    {initExpanded && childProjs.length > 0 && (
                      <div className="ml-4 mt-1 space-y-1 border-l border-slate-600 pl-2">
                        {childProjs.map((p) => {
                          const projTasks = tasksForProject(p.id)
                          const projExpanded = !collapsedProjects.has(p.id)
                          const pSummary = truncateText(p.brief, 60) || 'No brief'
                          return (
                            <div key={p.id}>
                              <div
                                className={`rounded border p-2 text-sm cursor-pointer flex items-start gap-2 ${
                                  rowSelected('project', p.id)
                                    ? 'border-amber-500 bg-amber-900/20'
                                    : 'border-slate-600 bg-slate-700/30'
                                }`}
                                onClick={() => handlePickItem('project', p.id)}
                              >
                                <span
                                  className="text-slate-500 select-none shrink-0"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    toggleProjectCollapsed(p.id)
                                  }}
                                >
                                  {projTasks.length > 0 ? (projExpanded ? '▼' : '▶') : '·'}
                                </span>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between gap-2">
                                    <span className="font-medium text-slate-200 truncate">{p.title}</span>
                                    <span className="text-slate-500 text-[11px] shrink-0">Project · {p.status || '—'}</span>
                                  </div>
                                  <p className="text-slate-400 text-xs mt-0.5 truncate">{pSummary}</p>
                                </div>
                              </div>
                              {projExpanded && projTasks.length > 0 && (
                                <div className="ml-4 mt-1 space-y-1 border-l border-slate-600 pl-2">
                                  {projTasks.map((t) => (
                                    <div
                                      key={t.id}
                                      role="button"
                                      tabIndex={0}
                                      onClick={() => handlePickItem('task', t.id)}
                                      onKeyDown={(e) => {
                                        if (e.key === 'Enter' || e.key === ' ') {
                                          e.preventDefault()
                                          handlePickItem('task', t.id)
                                        }
                                      }}
                                      className={`rounded border p-2 text-sm cursor-pointer ${
                                        rowSelected('task', t.id)
                                          ? 'border-amber-500 bg-amber-900/20'
                                          : 'border-slate-600 bg-slate-700/20'
                                      }`}
                                    >
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="font-medium text-slate-200 truncate">{t.title}</span>
                                        <span className="text-slate-500 text-[11px] shrink-0">Task · {t.status || '—'}</span>
                                      </div>
                                      <p className="text-slate-400 text-xs mt-0.5 truncate">
                                        {truncateText(t.description || t.title, 56) || 'No description'}
                                      </p>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}

              {unanchoredProjects.length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-600">
                  <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">Unanchored projects</div>
                  {unanchoredProjects.map((p) => {
                    const projTasks = tasksForProject(p.id)
                    const projExpanded = !collapsedProjects.has(p.id)
                    const pSummary = truncateText(p.brief, 60) || 'No brief'
                    return (
                      <div key={p.id} className="mb-1">
                        <div
                          className={`rounded border p-2 text-sm cursor-pointer flex items-start gap-2 ${
                            rowSelected('project', p.id)
                              ? 'border-amber-500 bg-amber-900/20'
                              : 'border-slate-600 bg-slate-700/30'
                          }`}
                          onClick={() => handlePickItem('project', p.id)}
                        >
                          <span
                            className="text-slate-500 select-none shrink-0"
                            onClick={(e) => {
                              e.stopPropagation()
                              toggleProjectCollapsed(p.id)
                            }}
                          >
                            {projTasks.length > 0 ? (projExpanded ? '▼' : '▶') : '·'}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium text-slate-200 truncate">{p.title}</span>
                              <span className="text-slate-500 text-[11px] shrink-0">Project · {p.status || '—'}</span>
                            </div>
                            <p className="text-slate-400 text-xs mt-0.5 truncate">{pSummary}</p>
                          </div>
                        </div>
                        {projExpanded && projTasks.length > 0 && (
                          <div className="ml-4 mt-1 space-y-1 border-l border-slate-600 pl-2">
                            {projTasks.map((t) => (
                              <div
                                key={t.id}
                                role="button"
                                tabIndex={0}
                                onClick={() => handlePickItem('task', t.id)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault()
                                    handlePickItem('task', t.id)
                                  }
                                }}
                                className={`rounded border p-2 text-sm cursor-pointer ${
                                  rowSelected('task', t.id)
                                    ? 'border-amber-500 bg-amber-900/20'
                                    : 'border-slate-600 bg-slate-700/20'
                                }`}
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-medium text-slate-200 truncate">{t.title}</span>
                                  <span className="text-slate-500 text-[11px] shrink-0">Task · {t.status || '—'}</span>
                                </div>
                                <p className="text-slate-400 text-xs mt-0.5 truncate">
                                  {truncateText(t.description || t.title, 56) || 'No description'}
                                </p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

              {orphanTasks.length > 0 && (
                <div className="mt-2 pt-2 border-t border-slate-600">
                  <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">Tasks without project</div>
                  <div className="space-y-1">
                    {orphanTasks.map((t) => (
                      <div
                        key={t.id}
                        role="button"
                        tabIndex={0}
                        onClick={() => handlePickItem('task', t.id)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            handlePickItem('task', t.id)
                          }
                        }}
                        className={`rounded border p-2 text-sm cursor-pointer ${
                          rowSelected('task', t.id)
                            ? 'border-amber-500 bg-amber-900/20'
                            : 'border-slate-600 bg-slate-700/20'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-slate-200 truncate">{t.title}</span>
                          <span className="text-slate-500 text-[11px] shrink-0">Task · {t.status || '—'}</span>
                        </div>
                        <p className="text-slate-400 text-xs mt-0.5 truncate">
                          {truncateText(t.description || t.title, 56) || 'No description'}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : hasAnyExecutionData ? (
            <p className="text-slate-500 text-xs py-2 px-1 leading-relaxed">
              No initiatives, projects, or tasks match this search. Clear the filter to see the full execution tree.
            </p>
          ) : (
            <p className="text-slate-500 text-xs py-2 px-1 leading-relaxed">
              No initiatives, projects, or tasks yet. Add them in the <strong className="text-slate-400">Execution</strong> tab,
              then link this item under the right row.
            </p>
          )}
        </div>

        {visibleIdeas.length > 0 && (
          <div>
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1.5">Ideas</div>
            <div className="space-y-1">{visibleIdeas.map(renderIdeaRow)}</div>
          </div>
        )}

        {!hasExecutionBlock && visibleIdeas.length === 0 && (
          <p className="text-slate-500 text-xs py-1">
            {qn ? 'Nothing matches that search in Execution or Ideas.' : 'No ideas to show.'}
          </p>
        )}
      </div>

      <div className="border-t border-slate-600 pt-3 mt-auto shrink-0 min-h-[72px]">
        {selectedId && selectedTitle ? (
          <div className="space-y-2">
            <p className="text-slate-400 text-xs">
              Selected: <strong className="text-slate-200">{selectedTitle}</strong>{' '}
              <span className="text-slate-500">
                (
                {selectedType === 'idea'
                  ? 'Idea'
                  : selectedType === 'initiative'
                    ? 'Initiative'
                    : selectedType === 'project'
                      ? 'Project'
                      : 'Task'}
                )
              </span>
            </p>
            {!isPickNote && (
              <p className="text-slate-500 text-xs">
                {showUseExisting ? 'Accept will use as same item (no duplicate).' : 'Accept will place under as child.'}
              </p>
            )}
            <div className="flex flex-wrap gap-2 items-center">
              <button
                type="button"
                disabled={pickBusy}
                onClick={handleAccept}
                className={`px-3 py-1.5 rounded text-white text-sm font-medium disabled:opacity-50 ${
                  isPickNote ? 'bg-violet-600 hover:bg-violet-500' : 'bg-emerald-600 hover:bg-emerald-500'
                }`}
              >
                {pickBusy ? 'Saving…' : isPickNote ? 'Append note' : 'Accept'}
              </button>
              {!isPickNote && showUseExisting && showPlaceUnder && onChoose && (
                <button
                  type="button"
                  onClick={() => {
                    onChoose('child_of', selectedType, selectedId)
                    onClose()
                  }}
                  className="px-3 py-1.5 rounded border border-slate-500 text-slate-300 hover:bg-slate-700 text-sm"
                >
                  Place under as child instead
                </button>
              )}
            </div>
          </div>
        ) : (
          <p className="text-slate-500 text-xs">
            {isPickNote
              ? 'Select a row above, then Append note (or Close to cancel).'
              : 'Select a row above, then Accept (or Close to cancel).'}
          </p>
        )}
      </div>
    </div>
  )
}
