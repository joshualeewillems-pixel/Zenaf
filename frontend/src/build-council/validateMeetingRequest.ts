/**
 * Client-side validation for a pasted build-council meeting request.
 *
 * This runs BEFORE any POST to /build-room/meetings/r2. A failed
 * validation must never start a meeting or spend anything: the caller
 * shows the error and posts nothing.
 *
 * The shape mirrors the server's RunMeetingBody + R2 fields
 * (api/routes/build_room_routes.py): work_item and question are
 * required; context, constraints, excerpts, source_refs, and
 * nominated_paths are string arrays; tools_enabled is a boolean.
 * The client is deliberately stricter than the server on context:
 * the server defaults it to an empty list, but a meeting request
 * without context is almost certainly a paste mistake, so the
 * client requires a non-empty array of non-empty strings.
 *
 * Unknown extra fields are dropped from the body the caller sends
 * (the server ignores them regardless), so the posted body is
 * exactly the known schema.
 */

export interface MeetingRequestBody {
  work_item: string
  question: string
  context: string[]
  constraints?: string[]
  excerpts?: string[]
  source_refs?: string[]
  nominated_paths?: string[]
  tools_enabled?: boolean
}

export type MeetingRequestValidation =
  | { ok: true; body: MeetingRequestBody }
  | { ok: false; error: string }

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string')
}

const OPTIONAL_STRING_ARRAYS = ['constraints', 'excerpts', 'source_refs', 'nominated_paths'] as const

export function validateMeetingRequestJson(text: string): MeetingRequestValidation {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    return { ok: false, error: `Not valid JSON: ${e instanceof Error ? e.message : 'parse failed'}` }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: 'Request must be a JSON object, not an array or primitive.' }
  }
  const obj = parsed as Record<string, unknown>
  if (!isNonEmptyString(obj.work_item)) {
    return { ok: false, error: 'work_item is required and must be a non-empty string.' }
  }
  if (!isNonEmptyString(obj.question)) {
    return { ok: false, error: 'question is required and must be a non-empty string.' }
  }
  if (
    !Array.isArray(obj.context) ||
    obj.context.length === 0 ||
    !obj.context.every(isNonEmptyString)
  ) {
    return {
      ok: false,
      error: 'context is required and must be a non-empty array of non-empty strings.',
    }
  }
  for (const key of OPTIONAL_STRING_ARRAYS) {
    if (obj[key] !== undefined && !isStringArray(obj[key])) {
      return { ok: false, error: `${key} must be an array of strings when present.` }
    }
  }
  if (obj.tools_enabled !== undefined && typeof obj.tools_enabled !== 'boolean') {
    return { ok: false, error: 'tools_enabled must be a boolean when present.' }
  }
  const body: MeetingRequestBody = {
    work_item: obj.work_item as string,
    question: obj.question as string,
    context: obj.context as string[],
  }
  for (const key of OPTIONAL_STRING_ARRAYS) {
    if (obj[key] !== undefined) {
      body[key] = obj[key] as string[]
    }
  }
  if (obj.tools_enabled !== undefined) {
    body.tools_enabled = obj.tools_enabled as boolean
  }
  return { ok: true, body }
}
