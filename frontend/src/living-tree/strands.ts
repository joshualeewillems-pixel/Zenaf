/**
 * Frontend mirror of the 7-strand taxonomy for the Living Tree view.
 *
 * CANONICAL SOURCE OF TRUTH: `local_ai/strands.py` — the strand keys, faculty
 * labels, agent names, colors, and Gardner mappings are defined there and must
 * not be changed here independently. This module exists so the tree can render
 * without a backend round-trip; if the Python table changes, update this file
 * to match.
 *
 * The 7 faculties are FIXED. "World"/environment is context, NOT a strand.
 */

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
    agentName: 'Storyteller',
    color: '#c98f6a',
    gardner: 'linguistic',
    tagline: 'Language, rhetoric, writing, voice — how things get said.',
  },
  {
    key: 'number',
    faculty: 'Number',
    agentName: 'Patternist',
    color: '#7aa3b8',
    gardner: 'logical-mathematical',
    tagline: 'Analysis, systems, evidence — how patterns get read.',
  },
  {
    key: 'image',
    faculty: 'Image',
    agentName: 'Seer',
    color: '#c9a86a',
    gardner: 'spatial',
    tagline: 'Visual taste, design, spatial thinking — how things get seen.',
  },
  {
    key: 'sound',
    faculty: 'Sound',
    agentName: 'Songwriter',
    color: '#b983a8',
    gardner: 'musical',
    tagline: 'Music, rhythm, listening — how things get heard.',
  },
  {
    key: 'body',
    faculty: 'Body',
    agentName: 'Maker',
    color: '#9db87a',
    gardner: 'bodily-kinesthetic',
    tagline: 'Craft, making, doing — how things get built.',
  },
  {
    key: 'people',
    faculty: 'People',
    agentName: 'Mediator',
    color: '#a88fc9',
    gardner: 'interpersonal',
    tagline: 'Leadership, teaching, care — how people get held.',
  },
  {
    key: 'self',
    faculty: 'Self',
    agentName: 'Guide',
    color: '#7ba889',
    gardner: 'intrapersonal',
    tagline: 'Judgment, values, direction — how choices get made.',
  },
]

/** Braid display order: keeps the original three demo strands first. */
export const BRAID_ORDER: StrandKey[] = ['image', 'self', 'sound', 'word', 'number', 'body', 'people']

const _BY_KEY: Record<StrandKey, Strand> = Object.fromEntries(
  STRANDS.map((s) => [s.key, s]),
) as Record<StrandKey, Strand>

export function strandColor(key: StrandKey): string {
  return _BY_KEY[key].color
}

/** Strand lookup by warm agent name (e.g. "Storyteller"). */
export function strandForAgentName(agentName: string): Strand | undefined {
  const n = agentName.trim().toLowerCase()
  return STRANDS.find((s) => s.agentName.toLowerCase() === n)
}
