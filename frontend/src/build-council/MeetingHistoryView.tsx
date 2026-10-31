import { useEffect, useState } from 'react'
import {
  parseArtifact,
  parseMeetingHistoryList,
  parseTranscript,
  type ArtifactSummary,
  type MeetingHistoryEntry,
  type TranscriptEntry,
} from './meetingHistory'

const PAGE_SIZE = 50

type Detail =
  | { state: 'loading' }
  | { state: 'loaded'; transcript: TranscriptEntry[] | null; transcriptError: string | null; summary: ArtifactSummary | null; artifactError: string | null; artifactRaw: string | null }
  | { state: 'error'; error: string }

/**
 * Read-only meeting-history view, embedded in the build-council
 * submit page (owner-only page; the server gate is authoritative).
 *
 * Retrieval only: this component issues GETs, never POSTs, so
 * refreshing, paging, or opening a detail view cannot start,
 * mutate, or re-submit a meeting. A meeting whose files are gone
 * or unreadable shows its error explicitly instead of vanishing
 * from the list.
 */
export function MeetingHistoryView() {
  const [entries, setEntries] = useState<MeetingHistoryEntry[]>([])
  const [total, setTotal] = useState<number | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)

  const loadList = async (offset: number, append: boolean) => {
    setLoadingList(true)
    setListError(null)
    try {
      const res = await fetch(`/build-room/meetings?offset=${offset}&limit=${PAGE_SIZE}`, {
        credentials: 'include',
      })
      const raw = await res.text()
      let data: unknown = null
      try {
        data = JSON.parse(raw)
      } catch {
        data = null
      }
      if (res.status !== 200) {
        setListError(`History request failed (HTTP ${res.status}): ${raw.slice(0, 300)}`)
        return
      }
      const parsed = parseMeetingHistoryList(data)
      if (!parsed.ok) {
        setListError(parsed.error)
        return
      }
      setTotal(parsed.list.total)
      setEntries((prev) => (append ? [...prev, ...parsed.list.meetings] : parsed.list.meetings))
    } catch (e) {
      setListError(`History request failed before a response arrived (${e instanceof Error ? e.message : 'network error'}).`)
    } finally {
      setLoadingList(false)
    }
  }

  useEffect(() => {
    void loadList(0, false)
    // Load once on mount; refresh is manual by design.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const openDetail = async (meetingId: string) => {
    setSelectedId(meetingId)
    setDetail({ state: 'loading' })
    try {
      const [transcriptRes, artifactRes] = await Promise.all([
        fetch(`/build-room/meetings/${encodeURIComponent(meetingId)}/transcript`, { credentials: 'include' }),
        fetch(`/build-room/meetings/${encodeURIComponent(meetingId)}/artifact`, { credentials: 'include' }),
      ])
      const transcriptRaw = await transcriptRes.text()
      const artifactRaw = await artifactRes.text()
      let transcriptData: unknown = null
      let artifactData: unknown = null
      try {
        transcriptData = JSON.parse(transcriptRaw)
      } catch {
        transcriptData = null
      }
      try {
        artifactData = JSON.parse(artifactRaw)
      } catch {
        artifactData = null
      }
      let transcript: TranscriptEntry[] | null = null
      let transcriptError: string | null = null
      if (transcriptRes.status !== 200) {
        transcriptError = `Transcript request failed (HTTP ${transcriptRes.status}): ${transcriptRaw.slice(0, 300)}`
      } else {
        const parsed = parseTranscript(transcriptData)
        if (!parsed.ok) transcriptError = parsed.error
        else transcript = parsed.transcript.entries
      }
      let summary: ArtifactSummary | null = null
      let artifactError: string | null = null
      let artifactJson: string | null = null
      if (artifactRes.status !== 200) {
        artifactError = `Artifact request failed (HTTP ${artifactRes.status}): ${artifactRaw.slice(0, 300)}`
      } else {
        const parsed = parseArtifact(artifactData)
        if (!parsed.ok) artifactError = parsed.error
        else {
          summary = parsed.summary
          artifactJson = JSON.stringify(parsed.raw, null, 2)
        }
      }
      setDetail({ state: 'loaded', transcript, transcriptError, summary, artifactError, artifactRaw: artifactJson })
    } catch (e) {
      setDetail({ state: 'error', error: `Detail request failed before a response arrived (${e instanceof Error ? e.message : 'network error'}).` })
    }
  }

  return (
    <div className="border border-slate-700 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-100">Meeting history</h2>
        <button
          type="button"
          disabled={loadingList}
          onClick={() => void loadList(0, false)}
          className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-slate-600 text-slate-100 hover:bg-slate-500 disabled:opacity-50"
        >
          {loadingList ? 'Loading…' : 'Refresh'}
        </button>
      </div>
      <p className="text-sm text-slate-400">
        Past build-council meetings, most recent first — standalone and program runs alike.
        Opening one shows its stored transcript and draft artifact. Nothing here starts or
        changes a meeting.
      </p>
      {listError && <p className="text-red-400 text-sm">{listError}</p>}
      {total !== null && (
        <p className="text-sm text-slate-300">
          {entries.length} of {total} shown
        </p>
      )}
      {entries.length === 0 && !loadingList && !listError && (
        <p className="text-sm text-slate-400">No stored meetings yet.</p>
      )}
      <ul className="space-y-2">
        {entries.map((entry) => (
          <li key={entry.meeting_id}>
            <button
              type="button"
              onClick={() => void openDetail(entry.meeting_id)}
              className="w-full text-left border border-slate-700 rounded-lg px-3 py-2 hover:border-slate-500"
            >
              <span className="block text-sm text-slate-100 font-mono">{entry.meeting_id}</span>
              <span className="block text-sm text-slate-300">
                {entry.work_item ?? 'No work item recorded'}
                {entry.ok !== null && ` — ok: ${entry.ok ? 'true' : 'false'}`}
                {entry.claim_count !== null && ` — ${entry.claim_count} claims`}
              </span>
              <span className="block text-xs text-slate-400">
                {entry.has_transcript ? 'transcript' : 'no transcript'}
                {' · '}
                {entry.has_artifact ? 'artifact' : 'no artifact'}
                {entry.has_capture ? ' · capture (program run)' : ''}
                {entry.error ? ` · error: ${entry.error}` : ''}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {total !== null && entries.length < total && (
        <button
          type="button"
          disabled={loadingList}
          onClick={() => void loadList(entries.length, true)}
          className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-slate-600 text-slate-100 hover:bg-slate-500 disabled:opacity-50"
        >
          Load more
        </button>
      )}
      {selectedId && detail && detail.state === 'loading' && (
        <p className="text-sm text-slate-300">Loading {selectedId}…</p>
      )}
      {selectedId && detail && detail.state === 'error' && (
        <p className="text-red-400 text-sm">{detail.error}</p>
      )}
      {selectedId && detail && detail.state === 'loaded' && (
        <div className="border border-slate-700 rounded-lg p-4 space-y-4">
          <h3 className="text-base font-semibold text-slate-100 font-mono">{selectedId}</h3>
          {detail.summary && (
            <div className="space-y-1">
              <p className="text-sm text-slate-300">Work item: {detail.summary.work_item ?? '—'}</p>
              <p className="text-sm text-slate-300">Question: {detail.summary.question ?? '—'}</p>
              <p className="text-sm text-slate-300">
                ok: {detail.summary.ok !== null ? String(detail.summary.ok) : '—'}
                {detail.summary.claim_count !== null && ` — ${detail.summary.claim_count} claims`}
                {detail.summary.transjective_conformant !== null &&
                  ` — transjective conformant: ${String(detail.summary.transjective_conformant)}`}
                {detail.summary.interim_report_count !== null &&
                  ` — ${detail.summary.interim_report_count} interim reports`}
              </p>
            </div>
          )}
          {detail.artifactError && <p className="text-red-400 text-sm">{detail.artifactError}</p>}
          <div>
            <h4 className="text-sm font-semibold text-slate-100 mb-1">Transcript</h4>
            {detail.transcriptError && <p className="text-red-400 text-sm">{detail.transcriptError}</p>}
            {detail.transcript && detail.transcript.length === 0 && (
              <p className="text-sm text-slate-400">No transcript entries.</p>
            )}
            {detail.transcript && detail.transcript.length > 0 && (
              <ul className="space-y-2 max-h-[480px] overflow-auto">
                {detail.transcript.map((entry, i) => (
                  <li key={i} className="text-sm text-slate-300">
                    <span className="text-slate-400 font-mono text-xs">[{entry.kind}]</span>{' '}
                    {entry.participant && <span className="text-slate-200">{entry.participant}: </span>}
                    <span className="whitespace-pre-wrap break-words">{entry.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {detail.artifactRaw && (
            <div>
              <h4 className="text-sm font-semibold text-slate-100 mb-1">Draft artifact (verbatim JSON)</h4>
              <pre className="w-full max-h-[480px] overflow-auto bg-slate-900 border border-slate-600 rounded px-3 py-2 text-slate-100 text-xs whitespace-pre-wrap break-words">
                {detail.artifactRaw}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
