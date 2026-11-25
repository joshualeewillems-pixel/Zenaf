/**
 * The refraction twins — dynamism spec §2.3, a GATED PROTOTYPE.
 *
 * A twin is a blurred, half-resolution copy of one stage image
 * (baked by stagegen/bake_twin.py), rendered beneath that stage's
 * ink so the ink reads as lying in the water. The founder's
 * review (2026-11-25) authorized ONE representative twin — not
 * the batch of 84 — to be judged on the actual water first; this
 * module is where twins are wired, and a batch rollout is a bake
 * step plus entries here, nothing more.
 *
 * The one prototype: Lucian, stage 6 (mid-ladder; his dendritic
 * channels are the densest continuous ink, so the smear survives
 * the downscale legibly).
 *
 * PROTOTYPE SEMANTICS, stated plainly: in the batch design every
 * stage's twin matches its own ink exactly. With one twin, the
 * stage-6 twin stands beneath Lucian's ink whenever his drawn
 * stage is at or beyond 6 — the formation has grown at least that
 * far — so the effect is present long enough (including at rest)
 * to be judged. It is the stage-6 shape throughout; stages 7–12
 * wear it as an underlay, not as their own refraction.
 */
import type { Voice } from './atelierLogic'

import lucian6Refr from './assets/stages/stage-lucian-6-refr.png'

export interface StageTwin {
  voice: Voice
  /** The stage this twin was baked from (1-based). */
  stage: number
  src: string
}

export const STAGE_TWINS: readonly StageTwin[] = [
  { voice: 'lucian', stage: 6, src: lucian6Refr },
]

/** The twin standing beneath a voice's ink at drawn stage
 *  `inkStage`: the baked twin with the greatest stage ≤ inkStage
 *  for that voice, or undefined when the voice has none there. */
export function twinForStage(voice: Voice, inkStage: number): StageTwin | undefined {
  let best: StageTwin | undefined
  for (const t of STAGE_TWINS) {
    if (t.voice !== voice || t.stage > inkStage) continue
    if (!best || t.stage > best.stage) best = t
  }
  return best
}
