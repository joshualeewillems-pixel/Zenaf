/**
 * Entity id chips: run this on **raw** assistant text. Parent views must not run Markdown/HTML
 * conversion before `parseEntityMentions`, or `[ID: …]` patterns will not match.
 */
import { Fragment, useMemo } from 'react'

const UUID =
  '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

const UUID_RE = new RegExp(`\\b(${UUID})\\b`, 'gi')

/**
 * Models / clipboards sometimes emit fullwidth brackets or colons; those would
 * bypass `[ID: …]` regexes and look like “plain text” with no cyan chips.
 */
function normalizeForEntityMentionParse(raw: string): string {
  return (raw || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '')
    .replace(/\uFF3B/g, '[')
    .replace(/\uFF3D/g, ']')
    .replace(/\uFF1A/g, ':')
    .replace(/\uFF29/g, 'I')
    .replace(/\uFF24/g, 'D')
}

/**
 * CouncilTranscript uses this so rows with linkable ids are never mis-tagged as
 * “headers”, and the same normalization applies before chip parsing.
 */
export function councilRowHasLinkableEntityMarker(line: string): boolean {
  const n = normalizeForEntityMentionParse(line)
  if (/\[[Ii][Dd]\s*:/.test(n)) return true
  if (/\(\s*[Ii][Dd]\s*:/.test(n)) return true
  return new RegExp(`\\b(?:${UUID})\\b`, 'i').test(n)
}

/** e.g. `task: uuid`, `Initiative # uuid` */
const LABELED_ENTITY_RE = new RegExp(
  `\\b(idea|task|project|initiative)\\s*[:#]\\s*(${UUID})\\b`,
  'gi',
)

/** PRIMARY / Reference lines: `Focused entity: initiative (id: uuid)` */
const FOCUSED_ENTITY_RE = new RegExp(
  `Focused entity:\\s*([a-zA-Z_]+)\\s*\\(\\s*id:\\s*\`?(${UUID})\`?\\s*\\)`,
  'gi',
)

/** e.g. `initiative (id: uuid)` */
const TYPED_ID_PAREN_RE = new RegExp(
  `\\b(idea|task|project|initiative)\\s*\\(\\s*id:\\s*\`?(${UUID})\`?\\s*\\)`,
  'gi',
)

/** Navigation snapshot: `taskId=uuid`, `initiativeId=uuid` */
const SELECTION_KEY_RE = new RegExp(
  `\\b(initiativeId|projectId|taskId)\\s*=\\s*(${UUID})\\b`,
  'gi',
)

/**
 * [ID: …] capture for council chips. Tolerates:
 * - optional markdown (* _) around the token
 * - case-insensitive `id`
 * - extra bracket nesting from local models, e.g. `[ID: [uuid]]` or `[ID: [[uuid]]]`
 */
const BRACKET_ID_RE = new RegExp(
  '(?:\\*{1,2}|_)?\\[[Ii][Dd]\\s*:\\s*(?:\\[\\s*)*([0-9a-fA-F-]{36}|REDACTED_UUID|[a-zA-Z0-9_-]+)(?:\\s*\\])+(?:\\*{1,2}|_)?',
  'g',
)

/** e.g. `(ID: uuid)` when models avoid square brackets */
const PAREN_ID_RE = new RegExp(
  '(?:\\*{1,2}|_)?\\(\\s*[Ii][Dd]\\s*:\\s*(' +
    UUID +
    '|REDACTED_UUID|[a-zA-Z0-9_-]+)\\s*\\)(?:\\*{1,2}|_)?',
  'g',
)

/** Nearest VE fence above the bracket → chip entity type for dives */
function entityTypeForWorkingSetBracket(head: string): string {
  const markers: { needle: string; type: string }[] = [
    { needle: 'OTHER IDEAS (For reference only', type: 'idea' },
    { needle: 'OTHER INITIATIVES (For reference only', type: 'initiative' },
    { needle: 'OTHER OPEN ITEMS (For reference only', type: 'task' },
  ]
  let best = -1
  let t = 'task'
  for (const { needle, type } of markers) {
    const i = head.lastIndexOf(needle)
    if (i > best) {
      best = i
      t = type
    }
  }
  return t
}

function selectionKeyToEntityType(key: string): string {
  const k = key.toLowerCase()
  if (k === 'initiativeid') return 'initiative'
  if (k === 'projectid') return 'project'
  if (k === 'taskid') return 'task'
  return 'task'
}

function normalizeFocusedEntityType(raw: string): string {
  const t = (raw || '').toLowerCase().replace(/\s+/g, '_')
  if (t === 'initiative' || t === 'project' || t === 'task' || t === 'idea') return t
  return 'task'
}

export type EntityMentionOpenPayload = {
  entityId: string
  entityType: string
  label: string
}

type Segment =
  | { kind: 'text'; value: string }
  | { kind: 'chip'; entityId: string; entityType: string; label: string }

/** Fallback link label when prose before `[ID:…]` already states the same title. */
function entityShortLinkFallback(entityType: string): string {
  switch (entityType) {
    case 'idea':
      return 'this idea'
    case 'project':
      return 'this project'
    case 'initiative':
      return 'this initiative'
    default:
      return 'this task'
  }
}

function firstWordsEllipsis(text: string, maxWords: number): string {
  const w = text.split(/\s+/).filter(Boolean)
  if (w.length <= maxWords) return text.trim()
  return `${w.slice(0, maxWords).join(' ')}…`
}

function parseEntityMentions(text: string): Segment[] {
  const s = normalizeForEntityMentionParse(text || '')
  const segments: Segment[] = []
  let last = 0
  const matches: { start: number; end: number; id: string; type: string; label: string }[] = []

  const pushMatch = (
    start: number,
    end: number,
    id: string,
    type: string,
    label?: string,
  ) => {
    if (matches.some((x) => start < x.end && end > x.start)) return
    matches.push({
      start,
      end,
      id,
      type,
      label: label ?? `${type} ${id.slice(0, 8)}…`,
    })
  }

  let m: RegExpExecArray | null
  LABELED_ENTITY_RE.lastIndex = 0
  while ((m = LABELED_ENTITY_RE.exec(s)) !== null) {
    const type = String(m[1] || 'task').toLowerCase()
    const id = m[2]
    pushMatch(m.index, m.index + m[0].length, id, type)
  }

  FOCUSED_ENTITY_RE.lastIndex = 0
  while ((m = FOCUSED_ENTITY_RE.exec(s)) !== null) {
    const type = normalizeFocusedEntityType(String(m[1] || ''))
    const id = m[2]
    pushMatch(m.index, m.index + m[0].length, id, type)
  }

  TYPED_ID_PAREN_RE.lastIndex = 0
  while ((m = TYPED_ID_PAREN_RE.exec(s)) !== null) {
    const type = String(m[1] || 'task').toLowerCase()
    const id = m[2]
    pushMatch(m.index, m.index + m[0].length, id, type)
  }

  SELECTION_KEY_RE.lastIndex = 0
  while ((m = SELECTION_KEY_RE.exec(s)) !== null) {
    const type = selectionKeyToEntityType(String(m[1] || ''))
    const id = m[2]
    pushMatch(m.index, m.index + m[0].length, id, type)
  }

  const pushBracketStyleMatch = (m: RegExpExecArray) => {
    const id = m[1]
    const before = s.slice(0, m.index).trimEnd()
    const entityType = entityTypeForWorkingSetBracket(before)
    const lineStart = before.lastIndexOf('\n') + 1
    const lineBeforeTag = s.slice(lineStart, m.index).trim()
    const linePrefixNorm = lineBeforeTag
      .replace(/^\d+\.\s*/, '')
      .replace(/\*+/g, '')
      .replace(/_+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    const bullet = before.lastIndexOf('•')
    const nl = before.lastIndexOf('\n')
    const cut = Math.max(bullet, nl)
    let rawTitle = (cut >= 0 ? before.slice(cut + 1) : before).trim()
    rawTitle = rawTitle.replace(/^\d+\.\s*/, '').trim()
    rawTitle = rawTitle.replace(/^•\s*/, '').trim()
    rawTitle = rawTitle.replace(/\*+/g, '').replace(/_+/g, ' ').replace(/\s+/g, ' ').trim()
    let label =
      rawTitle.length > 0
        ? rawTitle.length > 72
          ? `${rawTitle.slice(0, 69)}…`
          : rawTitle
        : `Entity ${id.slice(0, 8)}…`
    const labelNorm = label.replace(/\s+/g, ' ').trim()
    if (linePrefixNorm && labelNorm && linePrefixNorm === labelNorm) {
      label = entityShortLinkFallback(entityType)
    } else if (linePrefixNorm && labelNorm && linePrefixNorm.length >= 12 && labelNorm.startsWith(linePrefixNorm)) {
      label = entityShortLinkFallback(entityType)
    } else if (labelNorm.length > 48) {
      label = firstWordsEllipsis(labelNorm, 4)
    }
    pushMatch(m.index, m.index + m[0].length, id, entityType, label)
  }

  BRACKET_ID_RE.lastIndex = 0
  while ((m = BRACKET_ID_RE.exec(s)) !== null) {
    pushBracketStyleMatch(m)
  }

  PAREN_ID_RE.lastIndex = 0
  while ((m = PAREN_ID_RE.exec(s)) !== null) {
    pushBracketStyleMatch(m)
  }

  UUID_RE.lastIndex = 0
  while ((m = UUID_RE.exec(s)) !== null) {
    const id = m[1]
    const start = m.index
    const end = start + m[0].length
    if (matches.some((x) => start >= x.start && end <= x.end)) continue
    pushMatch(start, end, id, 'task', `Entity ${id.slice(0, 8)}…`)
  }

  matches.sort((a, b) => a.start - b.start)
  const deduped: typeof matches = []
  for (const x of matches) {
    if (deduped.some((d) => x.start < d.end && x.end > d.start)) continue
    deduped.push(x)
  }
  deduped.sort((a, b) => a.start - b.start)

  for (const x of deduped) {
    if (x.start > last) segments.push({ kind: 'text', value: s.slice(last, x.start) })
    segments.push({ kind: 'chip', entityId: x.id, entityType: x.type, label: x.label })
    last = x.end
  }
  if (last < s.length) segments.push({ kind: 'text', value: s.slice(last) })
  return segments.length ? segments : [{ kind: 'text', value: s }]
}

/** Exported for unit tests (label dedupe / bracket parsing). */
export function parseEntityMentionsForTest(text: string): Segment[] {
  return parseEntityMentions(text)
}

export type EntityMentionPresentation = 'inline_link' | 'chip'

export function EntityMentionText({
  text,
  maxChars,
  onOpenEntity,
  className,
  presentation = 'inline_link',
}: {
  text: string
  maxChars?: number
  onOpenEntity: (p: EntityMentionOpenPayload) => void
  className?: string
  /** `inline_link`: subtle underlined text. `chip`: prominent pill (legacy). */
  presentation?: EntityMentionPresentation
}) {
  const display = maxChars != null && text.length > maxChars ? `${text.slice(0, maxChars)}\n…` : text
  const segments = useMemo(() => parseEntityMentions(display), [display])

  const chipClass =
    'inline align-baseline mx-0.5 px-1.5 py-0.5 rounded-md text-[11px] font-medium bg-cyan-950/80 text-cyan-200 border border-cyan-600/50 hover:bg-cyan-900/90 hover:border-cyan-500/60 focus:outline-none focus:ring-1 focus:ring-cyan-500'
  const linkClass =
    'inline align-baseline mx-0.5 border-b border-dotted border-cyan-500/55 text-cyan-300/95 hover:text-cyan-200 hover:border-cyan-400/75 bg-transparent p-0 font-inherit text-[11px] cursor-pointer focus:outline-none focus:ring-1 focus:ring-cyan-500 rounded-sm'

  return (
    <span className={className}>
      {segments.map((seg, i) =>
        seg.kind === 'text' ? (
          <Fragment key={i}>{seg.value}</Fragment>
        ) : (
          <button
            key={`${seg.entityId}-${i}`}
            type="button"
            className={presentation === 'chip' ? chipClass : linkClass}
            title="Open focused thread for this item"
            onClick={() =>
              onOpenEntity({
                entityId: seg.entityId,
                entityType: seg.entityType,
                label: seg.label,
              })
            }
          >
            {seg.label}
          </button>
        ),
      )}
    </span>
  )
}
