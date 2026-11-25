import { useState, useCallback, type Dispatch, type SetStateAction } from 'react'
import { groupCandidatesBySegment } from './transcriptGrouping'

const VE_PATH = '/vision-execution'

export function TranscriptSorter({ apiBase }: { apiBase: string }) {
  const [transcriptText, setTranscriptText] = useState('')
  const [transcriptCallTitle, setTranscriptCallTitle] = useState('')
  const [transcriptCallDate, setTranscriptCallDate] = useState('')
  const [transcriptSorting, setTranscriptSorting] = useState(false)
  const [transcriptError, setTranscriptError] = useState<string | null>(null)
  const [transcriptResult, setTranscriptResult] = useState<any | null>(null)
  const [transcriptProjectId, setTranscriptProjectId] = useState('')
  const [transcriptTaskTitleEdits, setTranscriptTaskTitleEdits] = useState<Record<string, string>>({})
  const [dismissedTranscriptTaskIds, setDismissedTranscriptTaskIds] = useState<Set<string>>(new Set())
  const [expandedTranscriptTaskIds, setExpandedTranscriptTaskIds] = useState<Set<string>>(new Set())
  const [expandedTranscriptDecisionIds, setExpandedTranscriptDecisionIds] = useState<Set<string>>(new Set())
  const [expandedTranscriptIdeaIds, setExpandedTranscriptIdeaIds] = useState<Set<string>>(new Set())
  // Parents/loose rule: candidates start nested under their topic
  // segment; these sets hold the segments the user has un-nested.
  const [expandedTranscriptTaskSegments, setExpandedTranscriptTaskSegments] = useState<Set<string>>(new Set())
  const [expandedTranscriptDecisionSegments, setExpandedTranscriptDecisionSegments] = useState<Set<string>>(new Set())
  const [expandedTranscriptIdeaSegments, setExpandedTranscriptIdeaSegments] = useState<Set<string>>(new Set())

  const runTranscriptSorter = useCallback(async () => {
    const text = transcriptText.trim()
    setTranscriptError(null)
    setTranscriptResult(null)
    setTranscriptTaskTitleEdits({})
    setDismissedTranscriptTaskIds(new Set())
    setExpandedTranscriptTaskIds(new Set())
    setExpandedTranscriptDecisionIds(new Set())
    setExpandedTranscriptIdeaIds(new Set())
    setExpandedTranscriptTaskSegments(new Set())
    setExpandedTranscriptDecisionSegments(new Set())
    setExpandedTranscriptIdeaSegments(new Set())
    if (!text) {
      setTranscriptError('Paste a transcript first.')
      return
    }
    setTranscriptSorting(true)
    try {
      const body: any = { raw_transcript_text: text }
      const ctx: any = {}
      if (transcriptCallTitle.trim()) ctx.title = transcriptCallTitle.trim()
      if (transcriptCallDate.trim()) ctx.date = transcriptCallDate.trim()
      if (Object.keys(ctx).length > 0) body.call_context = ctx
      // ai-trace-exempt: heuristic_no_provider — backend sort_transcript() is deterministic/heuristic only (no LLM).
      const res = await fetch(`${apiBase}/transcripts/sort`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setTranscriptError(typeof data?.detail === 'string' ? data.detail : res.statusText || 'Request failed')
        return
      }
      setTranscriptResult(data)
    } catch (e) {
      setTranscriptError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setTranscriptSorting(false)
    }
  }, [apiBase, transcriptText, transcriptCallTitle, transcriptCallDate])

  const promoteTranscriptTask = useCallback(async (candidate: any) => {
    const projectId = transcriptProjectId.trim()
    if (!projectId) {
      setTranscriptError('Enter a Vision Execution project id before creating tasks.')
      return
    }
    setTranscriptError(null)
    try {
      const editedTitle = transcriptTaskTitleEdits[candidate.candidate_task_id]
      const title: string = (editedTitle || candidate.title || 'Task from transcript') as string
      const description: string = candidate.description || candidate.source_text || ''
      const notesLine = `[Zenaf lifecycle] transcript_id=${transcriptResult?.transcript_id || 'manual'} segment_id=${candidate.segment_id}`
      const payload = {
        project_id: projectId,
        parent_task_id: null,
        title,
        description,
        assignee_id: null,
        status: 'Todo',
        priority: '',
        estimated_hours: null,
        due_date: null,
        dependency_ids: [],
        completion_criteria: '',
        notes: notesLine,
      }
      const res = await fetch(`${apiBase}${VE_PATH}/tasks`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setTranscriptError(typeof data?.detail === 'string' ? data.detail : res.statusText || 'Failed to create task')
        return
      }
      setTranscriptError(null)
      alert(`Created task ${data.id || ''} in Vision Execution.`)
    } catch (e) {
      setTranscriptError(e instanceof Error ? e.message : 'Failed to create task')
    }
  }, [apiBase, transcriptProjectId, transcriptResult, transcriptTaskTitleEdits])

  const promoteTranscriptDecision = useCallback(async (candidate: any) => {
    setTranscriptError(null)
    try {
      const entityId = (transcriptResult?.transcript_id as string | null) || 'manual'
      const snapshot = {
        transcript_id: entityId,
        segment_id: candidate.segment_id,
        source_text: candidate.source_text,
        summary: candidate.summary,
      }
      const payload = {
        user_id: null,
        entity_type: 'transcript',
        entity_id: entityId,
        decision_type: 'transcript_candidate_decision',
        ai_proposal_snapshot: null,
        final_values_snapshot: snapshot,
      }
      const res = await fetch(`${apiBase}${VE_PATH}/decisions`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setTranscriptError(typeof data?.detail === 'string' ? data.detail : res.statusText || 'Failed to create decision')
        return
      }
      alert(`Recorded decision ${data.id || ''} in Vision Execution.`)
    } catch (e) {
      setTranscriptError(e instanceof Error ? e.message : 'Failed to create decision')
    }
  }, [apiBase, transcriptResult])

  // --- Parents/loose grouping (see transcriptGrouping.ts) ---
  const topics: any[] =
    transcriptResult && Array.isArray(transcriptResult.topics) ? transcriptResult.topics : []

  const visibleCandidateTasks: any[] =
    transcriptResult && Array.isArray(transcriptResult.candidate_tasks)
      ? ([...transcriptResult.candidate_tasks] as any[])
          .filter((ct) => !dismissedTranscriptTaskIds.has(ct.candidate_task_id))
          .sort((a, b) => {
            const segNum = (id: string) => {
              const m = /seg_(\d+)/.exec(id || '')
              return m ? parseInt(m[1], 10) : Number.MAX_SAFE_INTEGER
            }
            const confRank = (c: string | undefined) => {
              const v = (c || '').toLowerCase()
              if (v === 'high') return 0
              if (v === 'medium') return 1
              if (v === 'low') return 2
              return 3
            }
            const ca = confRank(a.confidence)
            const cb = confRank(b.confidence)
            if (ca !== cb) return ca - cb
            return segNum(a.segment_id) - segNum(b.segment_id)
          })
      : []
  const taskGrouping = groupCandidatesBySegment(visibleCandidateTasks, topics)
  const decisionGrouping = groupCandidatesBySegment(
    transcriptResult && Array.isArray(transcriptResult.candidate_decisions)
      ? (transcriptResult.candidate_decisions as any[])
      : [],
    topics,
  )
  const ideaGrouping = groupCandidatesBySegment(
    transcriptResult && Array.isArray(transcriptResult.candidate_ideas)
      ? (transcriptResult.candidate_ideas as any[])
      : [],
    topics,
  )

  const toggleSegmentIn =
    (setter: Dispatch<SetStateAction<Set<string>>>) => (segmentId: string) =>
      setter((prev) => {
        const next = new Set(prev)
        if (next.has(segmentId)) next.delete(segmentId)
        else next.add(segmentId)
        return next
      })
  const toggleTaskSegment = toggleSegmentIn(setExpandedTranscriptTaskSegments)
  const toggleDecisionSegment = toggleSegmentIn(setExpandedTranscriptDecisionSegments)
  const toggleIdeaSegment = toggleSegmentIn(setExpandedTranscriptIdeaSegments)

  /** Parent row for one topic segment inside a candidate pane. */
  const renderSegmentParent = (
    testidPrefix: string,
    segmentId: string,
    topicTitle: string | undefined,
    count: number,
    noun: string,
    expanded: boolean,
    onToggle: (segmentId: string) => void,
  ) => (
    <button
      type="button"
      data-testid={`${testidPrefix}-segment-${segmentId}`}
      aria-expanded={expanded}
      onClick={() => onToggle(segmentId)}
      className="w-full text-left px-2 py-1.5 rounded border border-slate-600 bg-slate-900/60 text-slate-200 hover:bg-slate-700/50"
    >
      <span className="font-medium">
        {expanded ? '▾' : '▸'} {topicTitle || segmentId}
      </span>{' '}
      <span className="text-[10px] text-slate-500">
        {segmentId} · {count} {count === 1 ? noun : `${noun}s`}
      </span>
    </button>
  )

  /** Expand-all / collapse-all row for one candidate pane. */
  const renderSegmentExpandAll = (
    testidPrefix: string,
    segmentIds: string[],
    expandedSet: Set<string>,
    setter: Dispatch<SetStateAction<Set<string>>>,
  ) => {
    if (segmentIds.length === 0) return null
    const allExpanded = segmentIds.every((id) => expandedSet.has(id))
    return (
      <div className="flex justify-end mb-2">
        <button
          type="button"
          data-testid={allExpanded ? `${testidPrefix}-collapse-all` : `${testidPrefix}-expand-all`}
          onClick={() => setter(allExpanded ? new Set() : new Set(segmentIds))}
          className="text-[10px] text-amber-300 hover:text-amber-200"
        >
          {allExpanded ? 'Collapse all topics' : 'Expand all topics'}
        </button>
      </div>
    )
  }

  const renderTaskCandidate = (ct: any) => {
    const editedTitle = transcriptTaskTitleEdits[ct.candidate_task_id]
    const displayTitle = editedTitle || ct.title || ct.candidate_task_id
    return (
      <li key={ct.candidate_task_id} className="border border-slate-700 rounded-lg p-2">
        <div className="flex items-center justify-between gap-2 mb-1">
          <div className="flex-1 min-w-0">
            <input
              type="text"
              value={displayTitle}
              onChange={(e) =>
                setTranscriptTaskTitleEdits((prev) => ({
                  ...prev,
                  [ct.candidate_task_id]: e.target.value,
                }))
              }
              className="w-full px-2 py-1 rounded bg-slate-900 border border-slate-700 text-slate-100 text-[11px]"
            />
          </div>
          <span className="text-[10px] text-slate-500 flex-shrink-0 text-right">
            {ct.segment_id} · conf {ct.confidence || '—'}
          </span>
        </div>
        {ct.evidence_excerpt && (
          <>
            <p className="text-slate-400 text-[11px] mb-1" title={ct.evidence_excerpt}>
              "
              {ct.evidence_excerpt.length > 140
                ? `${ct.evidence_excerpt.slice(0, 137)}…`
                : ct.evidence_excerpt}
              "
            </p>
            {ct.segment_text && (
              <button
                type="button"
                onClick={() =>
                  setExpandedTranscriptTaskIds((prev) => {
                    const next = new Set(prev)
                    if (next.has(ct.candidate_task_id)) next.delete(ct.candidate_task_id)
                    else next.add(ct.candidate_task_id)
                    return next
                  })
                }
                className="text-[10px] text-amber-300 hover:text-amber-200"
              >
                {expandedTranscriptTaskIds.has(ct.candidate_task_id)
                  ? 'Hide full segment'
                  : 'Show full segment'}
              </button>
            )}
            {ct.segment_text && expandedTranscriptTaskIds.has(ct.candidate_task_id) && (
              <pre className="mt-1 text-[10px] text-slate-300 bg-slate-900/80 border border-slate-700 rounded p-2 whitespace-pre-wrap max-h-40 overflow-auto">
                {ct.segment_text}
              </pre>
            )}
          </>
        )}
        <div className="flex items-center gap-2 mt-1">
          <button
            type="button"
            onClick={() => promoteTranscriptTask(ct)}
            className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-medium"
          >
            Create Vision Execution task
          </button>
          <button
            type="button"
            onClick={() =>
              setDismissedTranscriptTaskIds((prev) => {
                const next = new Set(prev)
                next.add(ct.candidate_task_id)
                return next
              })
            }
            className="px-2 py-1 rounded border border-slate-600 text-slate-400 hover:text-slate-200 hover:bg-slate-800 text-[11px]"
          >
            Dismiss
          </button>
        </div>
      </li>
    )
  }

  const renderDecisionCandidate = (cd: any) => (
    <li key={cd.candidate_decision_id} className="border border-slate-700 rounded px-2 py-1">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="font-medium truncate">{cd.summary || cd.candidate_decision_id}</span>
        <span className="text-[10px] text-slate-500">
          {cd.segment_id} · conf {cd.confidence || '—'}
        </span>
      </div>
      {cd.evidence_excerpt && (
        <>
          <p className="text-slate-400 text-[11px] mb-1">
            "
            {cd.evidence_excerpt.length > 120
              ? `${cd.evidence_excerpt.slice(0, 117)}…`
              : cd.evidence_excerpt}
            "
          </p>
          {cd.segment_text && (
            <button
              type="button"
              onClick={() =>
                setExpandedTranscriptDecisionIds((prev) => {
                  const next = new Set(prev)
                  if (next.has(cd.candidate_decision_id)) next.delete(cd.candidate_decision_id)
                  else next.add(cd.candidate_decision_id)
                  return next
                })
              }
              className="text-[10px] text-amber-300 hover:text-amber-200"
            >
              {expandedTranscriptDecisionIds.has(cd.candidate_decision_id)
                ? 'Hide full segment'
                : 'Show full segment'}
            </button>
          )}
          {cd.segment_text && expandedTranscriptDecisionIds.has(cd.candidate_decision_id) && (
            <pre className="mt-1 text-[10px] text-slate-300 bg-slate-900/80 border border-slate-700 rounded p-2 whitespace-pre-wrap max-h-40 overflow-auto">
              {cd.segment_text}
            </pre>
          )}
        </>
      )}
      <button
        type="button"
        onClick={() => promoteTranscriptDecision(cd)}
        className="px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white text-[11px] font-medium"
      >
        Record Vision Execution decision
      </button>
    </li>
  )

  const renderIdeaCandidate = (ci: any) => (
    <li key={ci.candidate_idea_id} className="border border-slate-700 rounded px-2 py-1">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="font-medium truncate">{ci.summary || ci.candidate_idea_id}</span>
        <span className="text-[10px] text-slate-500">
          {ci.segment_id} · conf {ci.confidence || '—'}
        </span>
      </div>
      {ci.evidence_excerpt && (
        <>
          <p className="text-slate-400 text-[11px] mb-1">
            "
            {ci.evidence_excerpt.length > 120
              ? `${ci.evidence_excerpt.slice(0, 117)}…`
              : ci.evidence_excerpt}
            "
          </p>
          {ci.segment_text && (
            <button
              type="button"
              onClick={() =>
                setExpandedTranscriptIdeaIds((prev) => {
                  const next = new Set(prev)
                  if (next.has(ci.candidate_idea_id)) next.delete(ci.candidate_idea_id)
                  else next.add(ci.candidate_idea_id)
                  return next
                })
              }
              className="text-[10px] text-amber-300 hover:text-amber-200"
            >
              {expandedTranscriptIdeaIds.has(ci.candidate_idea_id)
                ? 'Hide full segment'
                : 'Show full segment'}
            </button>
          )}
          {ci.segment_text && expandedTranscriptIdeaIds.has(ci.candidate_idea_id) && (
            <pre className="mt-1 text-[10px] text-slate-300 bg-slate-900/80 border border-slate-700 rounded p-2 whitespace-pre-wrap max-h-40 overflow-auto">
              {ci.segment_text}
            </pre>
          )}
        </>
      )}
    </li>
  )

  return (
    <section className="mt-8 pt-6 border-t border-slate-700">
      <h2 className="text-lg font-semibold text-slate-100 mb-2">Transcript Sorter</h2>
      <p className="text-slate-400 text-sm mb-4">
        Paste a call or meeting transcript to extract topics, deliverables, and candidate tasks/decisions. Review first; promote only confirmed items into Vision Execution.
      </p>
      {transcriptError && (
        <div className="mb-3 rounded-lg bg-red-900/30 border border-red-700 text-red-200 text-xs px-3 py-2">
          {transcriptError}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Call title (optional)</label>
            <input
              type="text"
              value={transcriptCallTitle}
              onChange={(e) => setTranscriptCallTitle(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
              placeholder="Weekly product sync"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Date (optional)</label>
            <input
              type="text"
              value={transcriptCallDate}
              onChange={(e) => setTranscriptCallDate(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
              placeholder="2026-03-11T15:00:00Z"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Transcript</label>
            <textarea
              value={transcriptText}
              onChange={(e) => setTranscriptText(e.target.value)}
              rows={10}
              className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500 font-mono"
              placeholder="Paste transcript text here…"
            />
          </div>
          <button
            type="button"
            onClick={runTranscriptSorter}
            disabled={transcriptSorting}
            className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-medium"
          >
            {transcriptSorting ? 'Sorting…' : 'Run transcript sorter'}
          </button>
        </div>
        <div className="space-y-4">
          {transcriptResult ? (
            <>
              <div className="rounded-lg bg-slate-800/70 border border-slate-600 p-3">
                <h3 className="text-slate-200 text-sm font-semibold mb-2">Topics</h3>
                {topics.length > 0 ? (
                  <ul className="space-y-1 text-xs text-slate-300 max-h-40 overflow-auto">
                    {topics.map((t: any) => (
                      <li key={t.segment_id} className="flex items-start gap-2">
                        <span className="text-slate-500">{t.segment_id}.</span>
                        <div>
                          <div className="font-medium">{t.topic_title}</div>
                          {t.substantive && (
                            <span className="text-emerald-400 text-[10px] uppercase tracking-wide">Substantive</span>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-slate-500 text-xs">No topics detected.</p>
                )}
              </div>
              <div className="rounded-lg bg-slate-800/70 border border-slate-600 p-3 max-h-72 overflow-auto">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-slate-200 text-sm font-semibold">Candidate tasks</h3>
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-slate-400">Project id</label>
                    <input
                      type="text"
                      value={transcriptProjectId}
                      onChange={(e) => setTranscriptProjectId(e.target.value)}
                      className="px-2 py-1 rounded bg-slate-900 border border-slate-600 text-slate-100 text-xs"
                      placeholder="Vision Execution project id"
                    />
                  </div>
                </div>
                {visibleCandidateTasks.length > 0 ? (
                  <>
                    {renderSegmentExpandAll(
                      'transcript-tasks',
                      taskGrouping.groups.map((g) => g.segment_id),
                      expandedTranscriptTaskSegments,
                      setExpandedTranscriptTaskSegments,
                    )}
                    <ul className="space-y-2 text-xs text-slate-300">
                      {taskGrouping.groups.map((g) => (
                        <li key={`task-seg-${g.segment_id}`}>
                          {renderSegmentParent(
                            'transcript-tasks',
                            g.segment_id,
                            g.topic?.topic_title,
                            g.items.length,
                            'task',
                            expandedTranscriptTaskSegments.has(g.segment_id),
                            toggleTaskSegment,
                          )}
                          {expandedTranscriptTaskSegments.has(g.segment_id) && (
                            <ul className="space-y-2 mt-2 ml-3">{g.items.map(renderTaskCandidate)}</ul>
                          )}
                        </li>
                      ))}
                      {taskGrouping.loose.map(renderTaskCandidate)}
                    </ul>
                  </>
                ) : (
                  <p className="text-slate-500 text-xs">No candidate tasks detected yet.</p>
                )}
              </div>
              <div className="rounded-lg bg-slate-800/70 border border-slate-600 p-3 max-h-48 overflow-auto">
                <h3 className="text-slate-200 text-sm font-semibold mb-2">Candidate decisions</h3>
                {decisionGrouping.groups.length > 0 || decisionGrouping.loose.length > 0 ? (
                  <>
                    {renderSegmentExpandAll(
                      'transcript-decisions',
                      decisionGrouping.groups.map((g) => g.segment_id),
                      expandedTranscriptDecisionSegments,
                      setExpandedTranscriptDecisionSegments,
                    )}
                    <ul className="space-y-1 text-xs text-slate-300">
                      {decisionGrouping.groups.map((g) => (
                        <li key={`decision-seg-${g.segment_id}`}>
                          {renderSegmentParent(
                            'transcript-decisions',
                            g.segment_id,
                            g.topic?.topic_title,
                            g.items.length,
                            'decision',
                            expandedTranscriptDecisionSegments.has(g.segment_id),
                            toggleDecisionSegment,
                          )}
                          {expandedTranscriptDecisionSegments.has(g.segment_id) && (
                            <ul className="space-y-1 mt-1 ml-3">{g.items.map(renderDecisionCandidate)}</ul>
                          )}
                        </li>
                      ))}
                      {decisionGrouping.loose.map(renderDecisionCandidate)}
                    </ul>
                  </>
                ) : (
                  <p className="text-slate-500 text-xs">No candidate decisions detected yet.</p>
                )}
              </div>
              <div className="rounded-lg bg-slate-800/70 border border-slate-600 p-3 max-h-48 overflow-auto">
                <h3 className="text-slate-200 text-sm font-semibold mb-2">Candidate ideas / follow-ups</h3>
                {ideaGrouping.groups.length > 0 || ideaGrouping.loose.length > 0 ? (
                  <>
                    {renderSegmentExpandAll(
                      'transcript-ideas',
                      ideaGrouping.groups.map((g) => g.segment_id),
                      expandedTranscriptIdeaSegments,
                      setExpandedTranscriptIdeaSegments,
                    )}
                    <ul className="space-y-1 text-xs text-slate-300">
                      {ideaGrouping.groups.map((g) => (
                        <li key={`idea-seg-${g.segment_id}`}>
                          {renderSegmentParent(
                            'transcript-ideas',
                            g.segment_id,
                            g.topic?.topic_title,
                            g.items.length,
                            'idea',
                            expandedTranscriptIdeaSegments.has(g.segment_id),
                            toggleIdeaSegment,
                          )}
                          {expandedTranscriptIdeaSegments.has(g.segment_id) && (
                            <ul className="space-y-1 mt-1 ml-3">{g.items.map(renderIdeaCandidate)}</ul>
                          )}
                        </li>
                      ))}
                      {ideaGrouping.loose.map(renderIdeaCandidate)}
                    </ul>
                  </>
                ) : (
                  <p className="text-slate-500 text-xs">No candidate ideas detected yet.</p>
                )}
              </div>
            </>
          ) : (
            <p className="text-slate-500 text-sm">Run the sorter to see topics and candidates here.</p>
          )}
        </div>
      </div>
    </section>
  )
}
