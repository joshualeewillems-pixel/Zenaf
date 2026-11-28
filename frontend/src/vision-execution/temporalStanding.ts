/**
 * Temporal standing — the client mirror of the backend fold
 * (local_ai/vision_execution/temporal_standing.py).
 *
 * Temporal Orchestration slice S1 (brief
 * zenaf-temporal-orchestration-slice-brief-2026-11-28.md §§1–2).
 * Span and allocation records ride the VE decisions store as
 * dedicated decision types; current standing is DERIVED by folding
 * the owner's decision rows — here over the rows the client already
 * fetches from GET /decisions, exactly as deriveDeclarations mirrors
 * fold_declarations for Rivers and Holds. The backend fold is
 * authoritative (it alone stamps the rowid-based fold_seq and
 * verifies assumption-set hashes against the full stream); this
 * mirror exists so the board and the Gantt resolve spans from the
 * same records with the same semantics.
 *
 * Every span record carries five orthogonal properties — origin,
 * standing, conditionality, confidence (derived from the effort
 * representation), temporal role. None implies another. Canonical
 * project start_date/end_date are never written by any of this.
 */

export type TemporalOrigin = 'visitor-recorded' | 'evidence-recovered' | 'derived' | 'proposed'

export type TemporalStanding =
  | 'historical observation'
  | 'evidence-recovered envelope'
  | 'provisional'
  | 'derived forecast'
  | 'visitor target'
  | 'established commitment'

export type TemporalRole = 'window' | 'deadline' | 'milestone' | 'hold'

export type EffortRepresentation =
  | { kind: 'exact'; hours: number }
  | { kind: 'interval'; low_hours: number; high_hours: number }
  | { kind: 'lower-bound'; hours: number }
  | { kind: 'upper-bound'; hours: number }
  | { kind: 'unknown' }

export interface TemporalAssumption {
  id: string
  type: string
  statement: string
}

export type TemporalConditionality =
  | { kind: 'unconditional' }
  | { kind: 'conditional'; assumption_set_id: string; assumptions: TemporalAssumption[] }

export interface TemporalSpanRecord {
  /** The recording decision's id — the span's name in the record. */
  id: string
  project_id: string
  /** ISO date/datetime, or null. A window with a null end is open-ended. */
  start: string | null
  end: string | null
  origin: TemporalOrigin
  standing: TemporalStanding
  role: TemporalRole
  conditionality: TemporalConditionality
  effort: EffortRepresentation
  /** Derived from the effort representation — never stored free text. */
  confidence_label: string
  basis: string[]
  method: string
  supersedes: string | null
  note: string
  recorded_at: string | null
}

export interface TemporalAllocationRecord {
  id: string
  person_id: string
  /** Monday of the allocation's ISO week (YYYY-MM-DD). */
  week_start: string
  hours: number
  project_id: string | null
  recorded_at: string | null
}

/** A decision row as returned by GET /decisions (owner-scoped). */
export interface TemporalDecisionRow {
  id: string
  entity_type: string
  entity_id: string
  decision_type: string
  final_values_snapshot: Record<string, unknown> | null
  created_at: string
}

export const SPAN_RECORDED = 'temporal_span_recorded'
export const SPAN_WITHDRAWN = 'temporal_span_withdrawn'
export const ALLOCATION_RECORDED = 'temporal_allocation_recorded'
export const ALLOCATION_WITHDRAWN = 'temporal_allocation_withdrawn'

const ORIGINS = new Set<string>(['visitor-recorded', 'evidence-recovered', 'derived', 'proposed'])
const STANDINGS = new Set<string>([
  'historical observation',
  'evidence-recovered envelope',
  'provisional',
  'derived forecast',
  'visitor target',
  'established commitment',
])
const ROLES = new Set<string>(['window', 'deadline', 'milestone', 'hold'])
const POINT_ROLES = new Set<string>(['deadline', 'milestone'])

const CONFIDENCE_LABELS: Record<string, string> = {
  exact: 'exact',
  interval: 'bounded interval',
  'lower-bound': 'lower bound only',
  'upper-bound': 'upper bound only',
  unknown: 'unknown',
}

export function confidenceLabel(effort: EffortRepresentation): string {
  return CONFIDENCE_LABELS[effort.kind] ?? 'unknown'
}

/* ------------------------------------------------------------------ */
/* SHA-256 (sync) — assumption-set ids must recompute identically     */
/* here and in the backend fold, or the two folds would disagree on   */
/* conditional records. Verified against published test vectors in    */
/* temporalStanding.test.ts.                                          */
/* ------------------------------------------------------------------ */

const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]

export function sha256Hex(text: string): string {
  const bytes = new TextEncoder().encode(text)
  const bitLen = bytes.length * 8
  const paddedLen = (((bytes.length + 8) >> 6) + 1) << 6
  const buf = new Uint8Array(paddedLen)
  buf.set(bytes)
  buf[bytes.length] = 0x80
  const view = new DataView(buf.buffer)
  view.setUint32(paddedLen - 4, bitLen >>> 0)
  view.setUint32(paddedLen - 8, Math.floor(bitLen / 0x100000000))
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19
  const w = new Int32Array(64)
  const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n))
  for (let block = 0; block < paddedLen; block += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getInt32(block + i * 4)
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3)
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7
    for (let i = 0; i < 64; i++) {
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const t1 = (h + s1 + ch + SHA256_K[i] + w[i]) | 0
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (s0 + maj) | 0
      h = g; g = f; f = e; e = (d + t1) | 0
      d = c; c = b; b = a; a = (t1 + t2) | 0
    }
    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0
    h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((x) => (x >>> 0).toString(16).padStart(8, '0'))
    .join('')
}

/** The canonical id of an assumption set: sha256 over the sorted
 *  assumption ids, one per line — identical to the backend's
 *  temporal_standing.assumption_set_id. */
export function assumptionSetId(assumptionIds: string[]): string {
  return sha256Hex([...assumptionIds].sort().join('\n'))
}

/* ------------------------------------------------------------------ */
/* Record parsing — mirrors the backend's fail-closed validation: a   */
/* malformed row degrades to no record, never to a broken fold.       */
/* ------------------------------------------------------------------ */

const ISO_SHAPE = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/

function validIso(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const text = value.trim()
  if (!text || !ISO_SHAPE.test(text)) return null
  return Number.isNaN(Date.parse(text)) ? null : text
}

function isNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

function parseAssumptions(raw: unknown): TemporalAssumption[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null
  const out: TemporalAssumption[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') return null
    const a = item as Record<string, unknown>
    if (
      typeof a.id !== 'string' || !a.id.trim() ||
      typeof a.type !== 'string' || !a.type.trim() ||
      typeof a.statement !== 'string'
    ) return null
    out.push({ id: a.id, type: a.type, statement: a.statement })
  }
  return out
}

function parseConditionality(raw: unknown): TemporalConditionality | null {
  if (raw == null) return { kind: 'unconditional' }
  if (typeof raw !== 'object') return null
  const c = raw as Record<string, unknown>
  if (c.kind === 'unconditional') return { kind: 'unconditional' }
  if (c.kind !== 'conditional') return null
  const assumptions = parseAssumptions(c.assumptions)
  if (!assumptions) return null
  // Fail-closed, like the backend: the stamped set id must recompute.
  if (c.assumption_set_id !== assumptionSetId(assumptions.map((a) => a.id))) return null
  return {
    kind: 'conditional',
    assumption_set_id: c.assumption_set_id as string,
    assumptions,
  }
}

function parseEffort(raw: unknown): EffortRepresentation | null {
  if (raw == null) return { kind: 'unknown' }
  if (typeof raw !== 'object') return null
  const e = raw as Record<string, unknown>
  switch (e.kind) {
    case 'unknown':
      return { kind: 'unknown' }
    case 'interval': {
      if (!isNum(e.low_hours) || !isNum(e.high_hours)) return null
      if (e.low_hours < 0 || e.high_hours < e.low_hours) return null
      return { kind: 'interval', low_hours: e.low_hours, high_hours: e.high_hours }
    }
    case 'exact':
    case 'lower-bound':
    case 'upper-bound': {
      if (!isNum(e.hours) || e.hours < 0) return null
      return { kind: e.kind, hours: e.hours }
    }
    default:
      return null
  }
}

export function parseSpanRecord(row: TemporalDecisionRow): TemporalSpanRecord | null {
  if (row.decision_type !== SPAN_RECORDED) return null
  const snap = row.final_values_snapshot
  if (!snap || !row.entity_id || !row.id) return null
  const origin = snap.origin as string
  const standing = snap.standing as string
  const role = snap.role as string
  if (!ORIGINS.has(origin) || !STANDINGS.has(standing) || !ROLES.has(role)) return null
  let start = snap.start == null ? null : validIso(snap.start)
  let end = snap.end == null ? null : validIso(snap.end)
  if (snap.start != null && start == null) return null
  if (snap.end != null && end == null) return null
  if (start == null && end == null) return null
  if (POINT_ROLES.has(role)) {
    if (start == null) start = end
    if (end == null) end = start
  }
  if (start != null && end != null && Date.parse(end) < Date.parse(start)) return null
  const conditionality = parseConditionality(snap.conditionality)
  if (!conditionality) return null
  const effort = parseEffort(snap.effort)
  if (!effort) return null
  return {
    id: row.id,
    project_id: row.entity_id,
    start,
    end,
    origin: origin as TemporalOrigin,
    standing: standing as TemporalStanding,
    role: role as TemporalRole,
    conditionality,
    effort,
    confidence_label: confidenceLabel(effort),
    basis: Array.isArray(snap.basis) ? snap.basis.filter((b): b is string => typeof b === 'string') : [],
    method: typeof snap.method === 'string' ? snap.method : '',
    supersedes: typeof snap.supersedes === 'string' && snap.supersedes ? snap.supersedes : null,
    note: typeof snap.note === 'string' ? snap.note : '',
    recorded_at: row.created_at ?? null,
  }
}

function mondayOf(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`)
  const shift = (d.getUTCDay() + 6) % 7 // days since Monday
  d.setUTCDate(d.getUTCDate() - shift)
  return d.toISOString().slice(0, 10)
}

export function parseAllocationRecord(row: TemporalDecisionRow): TemporalAllocationRecord | null {
  if (row.decision_type !== ALLOCATION_RECORDED) return null
  const snap = row.final_values_snapshot
  if (!snap || !row.entity_id || !row.id) return null
  const week = validIso(snap.week_start)
  if (week == null || !isNum(snap.hours) || snap.hours < 0) return null
  return {
    id: row.id,
    person_id: row.entity_id,
    week_start: mondayOf(week),
    hours: snap.hours,
    project_id: typeof snap.project_id === 'string' && snap.project_id ? snap.project_id : null,
    recorded_at: row.created_at ?? null,
  }
}

/* ------------------------------------------------------------------ */
/* The fold                                                           */
/* ------------------------------------------------------------------ */

export interface ProjectStanding {
  spans: TemporalSpanRecord[]
  byRole: Partial<Record<TemporalRole, TemporalSpanRecord[]>>
}

export interface TemporalFold {
  /** Client stamp: rows folded. The authoritative fold_seq is the
   *  backend's (rowid-based); consumers that must name a stamp for
   *  computation use the backend fold, not this mirror. */
  foldSeq: number
  byProject: Map<string, ProjectStanding>
  /** person_id → week_start → established hours + entries. */
  allocations: Map<string, Map<string, { established_hours: number; entries: TemporalAllocationRecord[] }>>
}

/**
 * Fold decision rows into current temporal standing. Input is in API
 * order (newest first, as GET /decisions returns); the replay is
 * oldest-first, mirroring the backend fold over the same rows.
 */
export function foldTemporalStanding(decisions: TemporalDecisionRow[]): TemporalFold {
  const spans = new Map<string, Map<string, TemporalSpanRecord>>()
  const allocations = new Map<string, Map<string, TemporalAllocationRecord>>()
  const rows = [...decisions].reverse()
  for (const row of rows) {
    const snap = row.final_values_snapshot
    if (row.decision_type === SPAN_RECORDED) {
      const span = parseSpanRecord(row)
      if (!span) continue
      let projectSpans = spans.get(span.project_id)
      if (!projectSpans) {
        projectSpans = new Map()
        spans.set(span.project_id, projectSpans)
      }
      if (span.supersedes) projectSpans.delete(span.supersedes)
      projectSpans.set(span.id, span)
    } else if (row.decision_type === SPAN_WITHDRAWN) {
      const spanId = typeof snap?.span_id === 'string' ? snap.span_id : ''
      if (row.entity_id && spanId) spans.get(row.entity_id)?.delete(spanId)
    } else if (row.decision_type === ALLOCATION_RECORDED) {
      const alloc = parseAllocationRecord(row)
      if (!alloc) continue
      let personAllocs = allocations.get(alloc.person_id)
      if (!personAllocs) {
        personAllocs = new Map()
        allocations.set(alloc.person_id, personAllocs)
      }
      personAllocs.set(alloc.id, alloc)
    } else if (row.decision_type === ALLOCATION_WITHDRAWN) {
      const allocId = typeof snap?.allocation_id === 'string' ? snap.allocation_id : ''
      if (row.entity_id && allocId) allocations.get(row.entity_id)?.delete(allocId)
    }
  }
  const byProject = new Map<string, ProjectStanding>()
  for (const [projectId, projectSpans] of spans) {
    if (projectSpans.size === 0) continue
    const ordered = [...projectSpans.values()].sort((a, b) =>
      (a.start == null ? 1 : 0) - (b.start == null ? 1 : 0) ||
      (a.start ?? '').localeCompare(b.start ?? '') ||
      a.role.localeCompare(b.role) ||
      a.id.localeCompare(b.id),
    )
    const byRole: Partial<Record<TemporalRole, TemporalSpanRecord[]>> = {}
    for (const span of ordered) {
      const list = byRole[span.role] ?? []
      list.push(span)
      byRole[span.role] = list
    }
    byProject.set(projectId, { spans: ordered, byRole })
  }
  const allocOut = new Map<string, Map<string, { established_hours: number; entries: TemporalAllocationRecord[] }>>()
  for (const [personId, personAllocs] of allocations) {
    if (personAllocs.size === 0) continue
    const weeks = new Map<string, { established_hours: number; entries: TemporalAllocationRecord[] }>()
    for (const alloc of [...personAllocs.values()].sort((a, b) =>
      a.week_start.localeCompare(b.week_start) || a.id.localeCompare(b.id),
    )) {
      let bucket = weeks.get(alloc.week_start)
      if (!bucket) {
        bucket = { established_hours: 0, entries: [] }
        weeks.set(alloc.week_start, bucket)
      }
      bucket.established_hours = Math.round((bucket.established_hours + alloc.hours) * 10000) / 10000
      bucket.entries.push(alloc)
    }
    allocOut.set(personId, weeks)
  }
  return { foldSeq: decisions.length, byProject, allocations: allocOut }
}

/* ------------------------------------------------------------------ */
/* Unified span resolution                                            */
/* ------------------------------------------------------------------ */

/**
 * Standing precedence for projecting ONE window onto a surface: an
 * established commitment outranks a recovered envelope, which
 * outranks a forecast, a target, and finally a provisional
 * hypothesis. The fold keeps them all; this picks the working
 * window a surface draws, and the record it picked stays inspectable
 * (id + standing ride along on the resolved span).
 */
export const WINDOW_PRECEDENCE: TemporalStanding[] = [
  'established commitment',
  'historical observation',
  'evidence-recovered envelope',
  'derived forecast',
  'visitor target',
  'provisional',
]

export function pickWindowSpan(spans: TemporalSpanRecord[] | undefined): TemporalSpanRecord | null {
  if (!spans || spans.length === 0) return null
  const windows = spans.filter((s) => s.role === 'window')
  if (windows.length === 0) return null
  return [...windows].sort((a, b) =>
    WINDOW_PRECEDENCE.indexOf(a.standing) - WINDOW_PRECEDENCE.indexOf(b.standing) ||
    (b.recorded_at ?? '').localeCompare(a.recorded_at ?? '') ||
    b.id.localeCompare(a.id),
  )[0]
}
