/**
 * Pure client logic for the build-council meeting-history view
 * (owner-only retrieval surface). Kept free of React so it is
 * testable under the repo's existing vitest setup (node
 * environment, *.test.ts): no rendering harness exists here, so
 * every rule the view depends on lives in this module and is
 * covered by meetingHistory.test.ts.
 *
 * Safety rules encoded here (the backend enforces them again —
 * this module is the UI's first line of defense, never the only one):
 * - Only GETs, never POSTs: history browsing cannot start, mutate,
 *   or re-submit a meeting. Refreshing or paging is always safe.
 * - Strict parsing: any shape deviation is an error, never a
 *   guess. The view shows the error rather than acting on an
 *   unknown shape.
 * - No server paths are ever rendered: entries carry ids, work
 *   items, and flags only.
 */

export type MeetingHistoryEntry = {
  meeting_id: string
  work_item: string | null
  question: string | null
  ok: boolean | null
  claim_count: number | null
  has_transcript: boolean
  has_artifact: boolean
  has_capture: boolean
  error?: string
}

export type MeetingHistoryList = {
  meetings: MeetingHistoryEntry[]
  total: number
  offset: number
  limit: number
  order: string
}

export type TranscriptEntry = {
  kind: string
  participant: string | null
  text: string
}

export type TranscriptDoc = {
  meeting_id: string
  entries: TranscriptEntry[]
}

export type ArtifactSummary = {
  meeting_id: string
  work_item: string | null
  question: string | null
  ok: boolean | null
  claim_count: number | null
  transjective_conformant: boolean | null
  interim_report_count: number | null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nullableString(value: unknown): string | null | undefined {
  if (value === null || value === undefined) return null
  return typeof value === 'string' ? value : undefined
}

function nullableNumber(value: unknown): number | null | undefined {
  if (value === null || value === undefined) return null
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function nullableBoolean(value: unknown): boolean | null | undefined {
  if (value === null || value === undefined) return null
  return typeof value === 'boolean' ? value : undefined
}

/**
 * Strictly parse a GET /build-room/meetings response. Any shape
 * deviation is an error, never a guess.
 */
export function parseMeetingHistoryList(
  data: unknown,
): { ok: true; list: MeetingHistoryList } | { ok: false; error: string } {
  if (!isRecord(data)) return { ok: false, error: 'History response is not an object.' }
  if (!Array.isArray(data.meetings)) {
    return { ok: false, error: 'History response meetings is not an array.' }
  }
  if (
    typeof data.total !== 'number' ||
    !Number.isInteger(data.total) ||
    data.total < 0
  ) {
    return { ok: false, error: 'History response has no valid total.' }
  }
  if (
    typeof data.offset !== 'number' ||
    !Number.isInteger(data.offset) ||
    data.offset < 0
  ) {
    return { ok: false, error: 'History response has no valid offset.' }
  }
  if (
    typeof data.limit !== 'number' ||
    !Number.isInteger(data.limit) ||
    data.limit < 0
  ) {
    return { ok: false, error: 'History response has no valid limit.' }
  }
  if (typeof data.order !== 'string') {
    return { ok: false, error: 'History response has no order string.' }
  }
  const meetings: MeetingHistoryEntry[] = []
  for (const entry of data.meetings) {
    if (!isRecord(entry)) {
      return { ok: false, error: 'History response has a non-object meeting entry.' }
    }
    if (typeof entry.meeting_id !== 'string' || entry.meeting_id.length === 0) {
      return { ok: false, error: 'History response has a meeting entry without an id.' }
    }
    const work_item = nullableString(entry.work_item)
    const question = nullableString(entry.question)
    const ok = nullableBoolean(entry.ok)
    const claim_count = nullableNumber(entry.claim_count)
    if (
      work_item === undefined ||
      question === undefined ||
      ok === undefined ||
      claim_count === undefined ||
      typeof entry.has_transcript !== 'boolean' ||
      typeof entry.has_artifact !== 'boolean' ||
      typeof entry.has_capture !== 'boolean' ||
      (entry.error !== undefined && typeof entry.error !== 'string')
    ) {
      return { ok: false, error: 'History response has a mistyped meeting entry.' }
    }
    meetings.push({
      meeting_id: entry.meeting_id,
      work_item,
      question,
      ok,
      claim_count,
      has_transcript: entry.has_transcript,
      has_artifact: entry.has_artifact,
      has_capture: entry.has_capture,
      ...(typeof entry.error === 'string' ? { error: entry.error } : {}),
    })
  }
  return {
    ok: true,
    list: {
      meetings,
      total: data.total,
      offset: data.offset,
      limit: data.limit,
      order: data.order,
    },
  }
}

/**
 * Strictly parse a GET /build-room/meetings/{id}/transcript
 * response: the stored transcript file, verbatim entries.
 */
export function parseTranscript(
  data: unknown,
): { ok: true; transcript: TranscriptDoc } | { ok: false; error: string } {
  if (!isRecord(data)) return { ok: false, error: 'Transcript response is not an object.' }
  if (typeof data.meeting_id !== 'string' || data.meeting_id.length === 0) {
    return { ok: false, error: 'Transcript response has no meeting id.' }
  }
  if (!Array.isArray(data.entries)) {
    return { ok: false, error: 'Transcript response entries is not an array.' }
  }
  const entries: TranscriptEntry[] = []
  for (const entry of data.entries) {
    if (!isRecord(entry)) {
      return { ok: false, error: 'Transcript response has a non-object entry.' }
    }
    if (typeof entry.kind !== 'string' || typeof entry.text !== 'string') {
      return { ok: false, error: 'Transcript response has an entry without kind or text.' }
    }
    const participant = nullableString(entry.participant)
    if (participant === undefined) {
      return { ok: false, error: 'Transcript response has a mistyped participant.' }
    }
    entries.push({ kind: entry.kind, participant, text: entry.text })
  }
  return { ok: true, transcript: { meeting_id: data.meeting_id, entries } }
}

/**
 * Summarize a GET /build-room/meetings/{id}/artifact response for
 * the detail view. The full artifact object is returned alongside
 * the summary so the view can render it verbatim; only the summary
 * fields are validated strictly.
 */
export function parseArtifact(
  data: unknown,
): { ok: true; summary: ArtifactSummary; raw: Record<string, unknown> } | { ok: false; error: string } {
  if (!isRecord(data)) return { ok: false, error: 'Artifact response is not an object.' }
  if (typeof data.meeting_id !== 'string' || data.meeting_id.length === 0) {
    return { ok: false, error: 'Artifact response has no meeting id.' }
  }
  const work_item = nullableString(data.work_item)
  const question = nullableString(data.question)
  const ok = nullableBoolean(data.ok)
  if (work_item === undefined || question === undefined || ok === undefined) {
    return { ok: false, error: 'Artifact response has mistyped summary fields.' }
  }
  const claim_count = Array.isArray(data.claim_registry) ? data.claim_registry.length : null
  let transjective_conformant: boolean | null = null
  if (isRecord(data.transjective_record)) {
    const conformant = nullableBoolean(data.transjective_record.conformant)
    if (conformant !== undefined) transjective_conformant = conformant
  }
  const interim_report_count = Array.isArray(data.transjective_validation_reports)
    ? data.transjective_validation_reports.length
    : null
  return {
    ok: true,
    summary: {
      meeting_id: data.meeting_id,
      work_item,
      question,
      ok,
      claim_count,
      transjective_conformant,
      interim_report_count,
    },
    raw: data,
  }
}
