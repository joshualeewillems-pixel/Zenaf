/**
 * Jynx's Scroll — reads.
 *
 * The shelf reads the user's Vision Execution hierarchy through the
 * Vision Map's entity fetch — the same routes (and the same fetch)
 * the Campaign Board uses.
 *
 * THE DRAWING FEED — the `[[chalk]]` carriage (chalk investigation
 * §§3–6; ledger item OPS-7), built as its own increment. Jynx's
 * Talk turns may end with a `[[chalk]]` bookkeeping tail carrying
 * drawings in their hand — stencil-kit stamps and freehand sumi
 * strokes, in the drawing's own coordinate space. The conversation
 * service parses the tail at its seam (the visitor never sees the
 * markup), validates it fail-closed, and persists the drawings
 * owner-scoped, keyed to the conversation and its selected
 * subject. GET /conversation/drawings serves the caller's drawings
 * in the order they were made, and fetchScrollDrawings below reads
 * them — keyed, since the founder's 2026-11-25 ruling, to ONE
 * conversation: a scroll's sheet carries only the drawings born in
 * that scroll's own conversation. The endpoint filters on its
 * ``conversation_id`` parameter and the surface filters again on
 * the served provenance, so a drawing from another conversation
 * never stands on this scroll's sheet. The carriage is gated by
 * the server-side ZENAF_CHALK_CARRIAGE rollout flag (default off
 * everywhere): with it off, no drawings are made and the feed is
 * honestly empty — the unrolled scroll stands blank, with no
 * placeholder art and no invented drawings.
 *
 * Not this channel: the pencil layer (PR #402,
 * local_ai/narrative/context.py) is a server-side CONVERSATION
 * channel — pencil-standing steward observations rendered as TEXT
 * into Jynx's chat prompt. It feeds what Jynx notices; it carries
 * no geometry and is never returned to any client.
 */
import { apiBase } from '../apiBase'
import { fetchVisionMapEntities } from '../vision-map/veMapApi'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import type { ScrollDrawing, ScrollMark } from './scrollLogic'

export interface ScrollEntities {
  initiatives: Initiative[]
  projects: Project[]
  tasks: Task[]
  ideas: Idea[]
}

export async function fetchScrollEntities(): Promise<ScrollEntities> {
  const all = await fetchVisionMapEntities()
  return {
    initiatives: all.initiatives,
    projects: all.projects,
    tasks: all.tasks,
    ideas: all.ideas,
  }
}

function formatFetchFailure(res: Response, bodyText: string): string {
  if (res.status === 401 || res.status === 403) {
    return 'Your session expired or you are not signed in. Open Home and sign in again, then reopen the Scroll.'
  }
  const raw = (bodyText || '').trim()
  if (raw.startsWith('{')) {
    try {
      const j = JSON.parse(raw) as { detail?: unknown }
      if (typeof j.detail === 'string' && j.detail.trim()) return j.detail.trim()
    } catch {
      /* fall through */
    }
  }
  return raw || `Request failed (${res.status})`
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const t = await res.text().catch(() => '')
    throw new Error(formatFetchFailure(res, t))
  }
  return res.json() as Promise<T>
}

function asArray<T>(x: unknown): T[] {
  return Array.isArray(x) ? (x as T[]) : []
}

/** One drawing as the endpoint serves it, narrowed to the
 *  ScrollDrawing shape the surface renders — the rendered fields
 *  plus the carriage provenance the sheet is keyed by. The server
 *  validates marks at carriage time; an item without an id, a
 *  space, or a marks list is not a drawing and is dropped, never
 *  repaired. */
function toScrollDrawing(x: unknown): ScrollDrawing | null {
  if (typeof x !== 'object' || x === null) return null
  const d = x as {
    id?: unknown
    title?: unknown
    space?: { w?: unknown; h?: unknown }
    marks?: unknown
    conversation_id?: unknown
  }
  if (typeof d.id !== 'string' || !d.id) return null
  const w = typeof d.space?.w === 'number' ? d.space.w : NaN
  const h = typeof d.space?.h === 'number' ? d.space.h : NaN
  if (!Number.isFinite(w) || !Number.isFinite(h)) return null
  if (!Array.isArray(d.marks)) return null
  return {
    id: d.id,
    title: typeof d.title === 'string' ? d.title : null,
    space: { w, h },
    marks: d.marks as ScrollMark[],
    conversationId: typeof d.conversation_id === 'string' ? d.conversation_id : null,
  }
}

/**
 * Jynx's drawings for the signed-in user, in the order they were
 * made — GET /conversation/drawings, the read side of the
 * [[chalk]] carriage (see the module header). With a conversation
 * id, the read is that conversation's drawings only: the endpoint
 * filters server-side, and the caller filters again on the served
 * provenance (drawingsForConversation), so the sheet's keying
 * does not rest on one seam alone. An owner with no drawings gets
 * an empty list and the scroll stands honestly blank; a failed
 * read throws, so the surface shows its error state rather than
 * a false blank.
 */
export async function fetchScrollDrawings(conversationId?: string): Promise<ScrollDrawing[]> {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ''
  const res = await fetch(`${apiBase()}/conversation/drawings${query}`, {
    credentials: 'include',
  })
  const data = await readJson<{ drawings?: unknown }>(res)
  return asArray<unknown>(data.drawings)
    .map(toScrollDrawing)
    .filter((d): d is ScrollDrawing => d !== null)
}
