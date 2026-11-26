/* ------------------------------------------------------------------ */
/* Capacity — the ONE frontend mirror of the backend derivation.       */
/*                                                                     */
/* local_ai/vision_execution/derived.py `add_capacity_derived` is the  */
/* record; this module restates its arithmetic step for step so every  */
/* surface that shows a capacity picture shows the SAME picture:       */
/*                                                                     */
/*   committed (activeWeeklyHours)                                     */
/*     Sum of estimated_weekly_hours over projects with status Ready   */
/*     or Active that the person owns or supports (owned-and-          */
/*     supported counts once; a null estimate counts 0). The sum is    */
/*     kept UNROUNDED through every judgement; the reported figure     */
/*     rounds to one decimal for display only.                         */
/*   capacityDelta                                                     */
/*     The UNROUNDED sum minus the recorded weekly capacity, rounded   */
/*     to one decimal for display. Null where no capacity profile is   */
/*     recorded — no figure, no judgement.                             */
/*   over (overcapacity)                                               */
/*     The UNROUNDED difference > 0. Never judged on rounded figures:  */
/*     10.04 committed against a capacity of 10 displays as            */
/*     10.0 committed and 0.0 delta, and IS over capacity, exactly     */
/*     as the backend rules it.                                        */
/*                                                                     */
/* Consumers: the Campaign Board's capacity picture (boardLogic) and   */
/* the Living Palace's Scales weighing (palaceLogic). Any new surface  */
/* needing this picture imports it from here — do not restate the      */
/* arithmetic a third time.                                            */
/* ------------------------------------------------------------------ */

import type { Project } from './types'

export interface CapacityDerived {
  /** activeWeeklyHours: the committed sum, rounded to one decimal
   *  for display. Judgements never read this figure. */
  committedHours: number
  /** capacityDelta: the unrounded difference, rounded to one decimal
   *  for display; null where no capacity is recorded. */
  capacityDelta: number | null
  /** overcapacity: the unrounded difference > 0; false where no
   *  capacity is recorded (no judgement is made). */
  over: boolean
}

function round1(x: number): number {
  return Math.round(x * 10) / 10
}

/** One person's capacity picture under a given body of projects —
 *  add_capacity_derived's arithmetic, step for step. */
export function capacityDerived(
  projects: Project[],
  capacityHours: number | null,
  personId: string,
): CapacityDerived {
  let active = 0
  for (const p of projects) {
    const status = (p.status ?? '').trim()
    if (status !== 'Ready' && status !== 'Active') continue
    const involved =
      p.owner_id === personId ||
      (Array.isArray(p.supporting_owner_ids) && p.supporting_owner_ids.includes(personId))
    if (involved) active += p.estimated_weekly_hours ?? 0
  }
  return {
    committedHours: round1(active),
    capacityDelta: capacityHours != null ? round1(active - capacityHours) : null,
    over: capacityHours != null ? active - capacityHours > 0 : false,
  }
}
