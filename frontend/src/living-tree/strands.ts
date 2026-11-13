/**
 * Frontend mirror of the 7-strand taxonomy for the Living Tree view.
 *
 * CANONICAL SOURCE OF TRUTH: `local_ai/strands.py` — the strand keys, faculty
 * labels, agent names, colors, and Gardner mappings are defined there and must
 * not be changed here independently. This module exists so the tree can render
 * without a backend round-trip; if the Python table changes, update this file
 * to match.
 *
 * Colors: the `color` values below come from `../council/colors`
 * (STRAND_COLORS) — the frontend's single source of truth for character +
 * strand colors. Do not hardcode a strand hex here.
 *
 * The 7 faculties are FIXED. "World"/environment is context, NOT a strand.
 */

import { STRAND_COLORS, strandColor } from '../council/colors'

import heartLogo from '../assets/strands/heart-logo.png'
import handsLogo from '../assets/strands/hands-logo.png'
import logicLogo from '../assets/strands/logic-logo.png'
import voiceLogo from '../assets/strands/voice-logo.png'
import earLogo from '../assets/strands/ear-logo.png'
import compassLogo from '../assets/strands/compass-logo.png'
import eyeLogo from '../assets/strands/eye-logo.png'

export { strandColor }

export type StrandKey = 'word' | 'number' | 'image' | 'sound' | 'body' | 'people' | 'self'

export type Strand = {
  /** Stable taxonomy key */
  key: StrandKey
  /** Faculty label */
  faculty: string
  /** Warm handshake name of the trainable agent embodying the strand */
  agentName: string
  /** Canonical hex color (drives braid + branch + node coloring) */
  color: string
  /** Gardner's multiple-intelligences mapping (reference only) */
  gardner: string
  /** One-line description */
  tagline: string
}

/** Canonical strand order (matches local_ai/strands.py STRANDS). */
export const STRANDS: Strand[] = [
  {
    key: 'word',
    faculty: 'Word',
    agentName: 'Voice',
    color: STRAND_COLORS.word,
    gardner: 'linguistic',
    tagline: 'Language, rhetoric, writing, voice — how things get said.',
  },
  {
    key: 'number',
    faculty: 'Number',
    agentName: 'Logic',
    color: STRAND_COLORS.number,
    gardner: 'logical-mathematical',
    tagline: 'Analysis, systems, evidence — how patterns get read.',
  },
  {
    key: 'image',
    faculty: 'Image',
    agentName: 'Eye',
    color: STRAND_COLORS.image,
    gardner: 'spatial',
    tagline: 'Visual taste, design, spatial thinking — how things get seen.',
  },
  {
    key: 'sound',
    faculty: 'Sound',
    agentName: 'Ear',
    color: STRAND_COLORS.sound,
    gardner: 'musical',
    tagline: 'Music, rhythm, listening — how things get heard.',
  },
  {
    key: 'body',
    faculty: 'Body',
    agentName: 'Hands',
    color: STRAND_COLORS.body,
    gardner: 'bodily-kinesthetic',
    tagline: 'Craft, making, doing — how things get built.',
  },
  {
    key: 'people',
    faculty: 'People',
    agentName: 'Heart',
    color: STRAND_COLORS.people,
    gardner: 'interpersonal',
    tagline: 'Leadership, teaching, care — how people get held.',
  },
  {
    key: 'self',
    faculty: 'Self',
    agentName: 'Compass',
    color: STRAND_COLORS.self,
    gardner: 'intrapersonal',
    tagline: 'Judgment, values, direction — how choices get made.',
  },
]

/** Braid display order: keeps the original three demo strands first. */
export const BRAID_ORDER: StrandKey[] = ['image', 'self', 'sound', 'word', 'number', 'body', 'people']

/** Strand lookup by warm agent name (e.g. "Voice"). */
export function strandForAgentName(agentName: string): Strand | undefined {
  const n = agentName.trim().toLowerCase()
  return STRANDS.find((s) => s.agentName.toLowerCase() === n)
}

/* ------------------------------------------------------------------ */
/* Weaver strand interviews (rev2) — design keys                       */
/* ------------------------------------------------------------------ */

/**
 * Founder-facing strand names for the strand interviews: Heart, Hands,
 * Logic, Voice, Ear, Compass, Eye. These are the lowercase agent
 * names — NOT the canonical taxonomy keys above. The backend strand
 * interview API speaks design keys only; reconciling the two key
 * systems is Slice 3 noting work, not strand work. The mapping lives
 * here, in one place, so no other module guesses it.
 */
export type DesignStrandKey =
  | 'heart'
  | 'hands'
  | 'logic'
  | 'voice'
  | 'ear'
  | 'compass'
  | 'eye'

export const DESIGN_STRAND_KEYS: DesignStrandKey[] = [
  'heart',
  'hands',
  'logic',
  'voice',
  'ear',
  'compass',
  'eye',
]

/** Design key → canonical taxonomy key. */
export const DESIGN_TO_TAXONOMY: Record<DesignStrandKey, StrandKey> = {
  heart: 'people',
  hands: 'body',
  logic: 'number',
  voice: 'word',
  ear: 'sound',
  compass: 'self',
  eye: 'image',
}

/** Canonical taxonomy key → design key. */
export const TAXONOMY_TO_DESIGN: Record<StrandKey, DesignStrandKey> = {
  people: 'heart',
  body: 'hands',
  number: 'logic',
  word: 'voice',
  sound: 'ear',
  self: 'compass',
  image: 'eye',
}

/** The design strand key for a tree strand root's taxonomy key. */
export function designStrandKeyForTaxonomy(key: StrandKey): DesignStrandKey {
  return TAXONOMY_TO_DESIGN[key]
}

/* ------------------------------------------------------------------ */
/* Strand logos (Living Tree root nodes)                               */
/* ------------------------------------------------------------------ */

/**
 * Strand logos — the founder's strand logo concepts (2026-11-12):
 * circular emblems in each strand's color, cropped from the concept
 * sheet, keyed by design key (the asset names). These are the tree's
 * ROOT marks: a strand root node shows its logo instead of its
 * two-letter monogram. Unlike the seat logos there is NO reveal
 * gate — strand roots carry no discovered/undiscovered state, so
 * the logos show always.
 */
export const STRAND_LOGOS: Record<DesignStrandKey, string> = {
  heart: heartLogo,
  hands: handsLogo,
  logic: logicLogo,
  voice: voiceLogo,
  ear: earLogo,
  compass: compassLogo,
  eye: eyeLogo,
}

/**
 * The strand's logo for its Living Tree root node, by taxonomy key.
 * Always resolves — no reveal gate for strands (see STRAND_LOGOS).
 */
export function resolveStrandLogo(key: StrandKey): string {
  return STRAND_LOGOS[TAXONOMY_TO_DESIGN[key]]
}
