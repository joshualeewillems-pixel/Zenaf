/**
 * Jynx's Scroll — reads.
 *
 * The shelf reads the user's Vision Execution hierarchy through the
 * Vision Map's entity fetch — the same routes (and the same fetch)
 * the Campaign Board uses. No new endpoints, no new records; the
 * Scroll writes nothing anywhere.
 *
 * THE DRAWING FEED — the precise gap, named rather than papered
 * over. Two channels exist in the record; neither can deliver a
 * drawing to this surface today:
 *
 *  1. The pencil layer (PR #402, local_ai/narrative/context.py) is
 *     a server-side CONVERSATION channel: pencil-standing steward
 *     observations — pattern language (tensions, open questions
 *     from proposed readings) — rendered as TEXT into Jynx's chat
 *     prompt behind the ZENAF_STEWARD_PENCIL switch and consent
 *     gates. It carries no geometry, is deliberately not citable,
 *     and is never returned to any client. It feeds what Jynx
 *     notices; it is not, and was never shaped as, a drawing path.
 *
 *  2. The designed drawing channel is the `[[chalk]]` carriage
 *     (chalk investigation §§3–6; ledger item OPS-7): Jynx's turns
 *     would emit semantic marks the client renders in their hand.
 *     It is design-accepted and NOT built — Talk's only delimited
 *     tail today is `[[round-offer]]`; no chalk parsing, validation,
 *     or client wall store exists in the product.
 *
 * And no route in api/ serves drawing geometry to the frontend —
 * verified route by route against this branch. So
 * fetchScrollDrawings resolves to an empty list, and the unrolled
 * scroll stands honestly blank: no placeholder art, no invented
 * drawings. When either channel is built — a chalk client store
 * fed by the carriage, or a read route serving stored drawings in
 * the ScrollDrawing shape (scrollLogic.ts: ordered stamp/stroke
 * marks in their own coordinate space) — it lands at the seam
 * below and nothing else changes.
 */
import { fetchVisionMapEntities } from '../vision-map/veMapApi'
import type { Idea, Initiative, Project, Task } from '../vision-execution/types'
import type { ScrollDrawing } from './scrollLogic'

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

/**
 * Jynx's drawings, in the order they were made. Resolves to []
 * today — see the module header: no channel yet delivers drawing
 * geometry to the frontend, and the surface invents none.
 */
export async function fetchScrollDrawings(): Promise<ScrollDrawing[]> {
  return []
}
