/**
 * Living Sky — painted-scene geometry: the hit-overlay table.
 *
 * DERIVATION (reproduced by script, not hand-copied — port plan §11):
 * medallion centres are `medallions[]` + `disc` in
 * `rendering-test-assets/derived/r5-render-signify-eyegold.json`
 * (R9c model units, medallion r 30, YOU disc r 34). Layer-frame px =
 * model × 2 (the 800×1320 painted-layer frame); scene units =
 * (placement + S × layerPx) / 2 with `painted-placement.json`
 * (S = 0.846917, tx = 61.233, ty = 202.069). Re-deriving all 15
 * centres reproduces port plan §5's table within ±0.05 scene units.
 * Painted disc radii in scene units: medallions 0.846917 × 60 / 2 =
 * 25.4; YOU 0.846917 × 68 / 2 = 28.8. The hit radius is 30 scene
 * units (≈ 61 px diameter at the card's rendered width — above the
 * 44 px tap minimum).
 *
 * The paintstack CSS transform is the study's own: percentages of
 * the scene box (400×660), origin 0 0.
 */

export const PAINTSTACK_TRANSFORM = 'translate(7.65%, 15.31%) scale(0.8469)'

export interface SkyHitNode {
  /** Production datum id — the exact id `onTap` has always received. */
  id: string
  /** Accessible name for the tap group (datum names, as on the old tree). */
  name: string
  /** Archetype id for seat nodes — the badge lookup key. */
  archetypeId?: string
  x: number
  y: number
  /** Painted disc radius (scene units): badge offsets + YOU photo size. */
  discR: number
  /** Tap-target radius (scene units). */
  hitR: number
}

const SEAT_R = 25.4
const YOU_R = 28.8
const HIT_R = 30

export const HIT_NODES: SkyHitNode[] = [
  { id: 'arch-mentor', name: 'Mentor', archetypeId: 'mentor', x: 63.5, y: 278.1, discR: SEAT_R, hitR: HIT_R },
  { id: 'arch-champion', name: 'Champion', archetypeId: 'champion', x: 79.1, y: 204.2, discR: SEAT_R, hitR: HIT_R },
  { id: 'arch-guardian', name: 'Guardian', archetypeId: 'guardian', x: 138.7, y: 148.3, discR: SEAT_R, hitR: HIT_R },
  { id: 'arch-maverick', name: 'Maverick', archetypeId: 'maverick', x: 211.4, y: 136.1, discR: SEAT_R, hitR: HIT_R },
  { id: 'arch-ambassador', name: 'Ambassador', archetypeId: 'ambassador', x: 274.2, y: 155.0, discR: SEAT_R, hitR: HIT_R },
  { id: 'arch-conductor', name: 'Conductor', archetypeId: 'conductor', x: 319.7, y: 201.5, discR: SEAT_R, hitR: HIT_R },
  { id: 'arch-skeptic', name: 'Skeptic', archetypeId: 'skeptic', x: 335.5, y: 280.2, discR: SEAT_R, hitR: HIT_R },
  { id: 'you', name: 'You', x: 200.0, y: 372.0, discR: YOU_R, hitR: HIT_R },
  { id: 'agent-number', name: 'Logic', x: 57.7, y: 492.3, discR: SEAT_R, hitR: HIT_R },
  { id: 'agent-body', name: 'Hands', x: 76.4, y: 541.4, discR: SEAT_R, hitR: HIT_R },
  { id: 'agent-word', name: 'Voice', x: 138.2, y: 576.1, discR: SEAT_R, hitR: HIT_R },
  { id: 'agent-image', name: 'Eye', x: 200.0, y: 610.9, discR: SEAT_R, hitR: HIT_R },
  { id: 'agent-people', name: 'Heart', x: 261.8, y: 576.1, discR: SEAT_R, hitR: HIT_R },
  { id: 'agent-sound', name: 'Ear', x: 323.6, y: 541.4, discR: SEAT_R, hitR: HIT_R },
  { id: 'agent-self', name: 'Compass', x: 342.3, y: 492.3, discR: SEAT_R, hitR: HIT_R },
]
