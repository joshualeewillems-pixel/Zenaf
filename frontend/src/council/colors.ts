/**
 * Single source of truth for character + strand colors on the frontend.
 *
 * Adopted 2026-11-12 from the founder's "Zenaf Fellowship — Character Logo
 * Concepts" sheet (see seat-logos-colors, commit 4a53b8e): one canonical
 * color per character, one per strand. Every surface reads from this module —
 * do not hardcode a seat or strand hex anywhere else.
 *
 * Backend mirrors (canonical at runtime): `local_ai/council/archetypes.py`
 * VOICE_COLORS (+ `voice_color()`) and `local_ai/strands.py` STRANDS.
 * The `/demo/voices` endpoint serves the backend values; this module is the
 * offline fallback. Keep the two in sync; the pins are
 * `tests/test_strands.py` (strand values) and `tests/test_conversation_skeleton.py`
 * / `tests/test_demo_routes.py` (voice colors).
 *
 * Deliberately NOT here:
 * - `mandateSeatAccent.ts` — mandate-role accents (thinking_partner,
 *   strategist, ...), a separate material palette for job roles, not characters.
 * - `local_ai/pipeline/quote_cards.py` PALETTES — quote-card design palettes,
 *   not character colors.
 * - Stone / neutral UI tones (`#f5f0e8`, `#0b0a09`, ...) — neutrals, not colors.
 */

export type SeatId =
  | 'mentor'
  | 'champion'
  | 'guardian'
  | 'maverick'
  | 'ambassador'
  | 'conductor'
  | 'skeptic'

/** Canonical seat colors, adopted 2026-11-12 (founder's logo sheet). */
export const SEAT_COLORS: Record<SeatId, string> = {
  mentor: '#92b692',
  champion: '#e24e4e',
  guardian: '#ac7c5b',
  maverick: '#a55cce',
  ambassador: '#5c9cea',
  conductor: '#8892c3',
  skeptic: '#a29ac1',
}

/** Backwards-compatible alias for the pre-consolidation name. */
export const VOICE_COLORS: Record<string, string> = SEAT_COLORS

/** Fallback seat color: the Conductor (synthesis) — same fallback as backend `voice_color()`. */
export const DEFAULT_SEAT_COLOR = SEAT_COLORS.conductor

/** Canonical color for a seat id (case/whitespace tolerant); falls back to the Conductor. */
export function voiceColor(id: string): string {
  return SEAT_COLORS[(id || '').trim().toLowerCase() as SeatId] ?? DEFAULT_SEAT_COLOR
}

export type StrandKey = 'word' | 'number' | 'image' | 'sound' | 'body' | 'people' | 'self'

/** Canonical strand colors by taxonomy key (agent names in parentheses). */
export const STRAND_COLORS: Record<StrandKey, string> = {
  word: '#e7aa89', // Voice
  number: '#91b6d1', // Logic
  image: '#edc87c', // Eye
  sound: '#dea1b8', // Ear
  body: '#b3c98d', // Hands
  people: '#bfa1de', // Heart
  self: '#88b899', // Compass
}

/**
 * Strand palette in canonical STRANDS order (word, number, image, sound,
 * body, people, self). Index-addressed by hash in `vision-map/symbolicStone.tsx`;
 * keep the order stable — only values change.
 */
export const STRAND_PALETTE: string[] = (
  ['word', 'number', 'image', 'sound', 'body', 'people', 'self'] as StrandKey[]
).map((k) => STRAND_COLORS[k])

/** Canonical hex color for a strand key. */
export function strandColor(key: StrandKey): string {
  return STRAND_COLORS[key]
}

/**
 * Cairn stone stains: the subdued L2 wood-stain register sampled from the
 * founder's Fellowship artwork for the tree study (2026-11-13), NOT the
 * saturated STRAND_COLORS above. A cairn stone's stain is its own strand
 * weight vector mixed in CIELAB over these seven stains (founder's Blend
 * ruling, 2026-11-13): image is the warm wood gold, self the moss green,
 * sound the muted rust, word the walnut, number the slate, body the sage,
 * people the plum. Used only by the cairn renderer (vision-map/cairnTower).
 */
export const CAIRN_STAINS: Record<StrandKey, string> = {
  image: '#b98d55',
  self: '#5c7a64',
  sound: '#a06a63',
  word: '#96604a',
  number: '#5d6d80',
  body: '#7d8a64',
  people: '#77598a',
}

/** Accent for user/visitor words woven into a voice's reply ([[u]] spans). */
export const USER_WEAVE_COLOR = '#e8a33d'

/**
 * The Living Tree's generic gold accent. This is NOT a seat color — it is
 * the tree's own chrome (node defaults, chevrons, borders, section labels).
 * It happens to share the pre-adoption Mentor hex (#c9a86a); that is a
 * coincidence of the old palette, not a reference to the Mentor. Kept at its
 * legacy value so the tree's appearance does not change.
 */
export const TREE_DEFAULT_COLOR = '#c9a86a'

/** RGB triplet of TREE_DEFAULT_COLOR, for `rgba(...)` uses in style blocks. */
export const TREE_DEFAULT_RGB = '201, 168, 106'
