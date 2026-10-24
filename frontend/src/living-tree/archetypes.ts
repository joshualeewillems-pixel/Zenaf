/**
 * Council archetype status for the Living Tree branches.
 *
 * The tree's primary branches are the 7 council archetypes (Mentor, Champion,
 * Guardian, Maverick, Ambassador, Conductor, Skeptic) — not marketplace
 * listings. Commerce lives one tap deeper, inside each archetype's panel.
 *
 * Live data comes from GET /council/archetypes/status. When the backend is
 * unreachable, STOCK_ARCHETYPE_FALLBACK renders the honest seed state:
 * all depths 0, no twigs, no invented training.
 */

export type ArchetypeTwig = {
  twig_id: string
  display_name: string
  domain: string
  domain_label: string
  status: 'approved' | 'proposed' | string
  signal_count: number
}

export type ArchetypeStatus = {
  id: string
  display_name: string
  /** Lowercase strand keys -> weight (sums to ~1.0). */
  strand_weights: Record<string, number>
  /** 0..100 training depth: the archetype's weight vector applied to the
      user's per-strand depth scores. */
  depth: number
  /** Coarse band: "not yet trained" | "early" | "developing" | "trained" | "deeply trained". */
  band: string
  /** The character description — the archetype's voice. */
  prompt_frame: string
  twigs: ArchetypeTwig[]
  is_skeptic: boolean
  /** Seat avatar URL, or null for the ??? placeholder silhouette.
      Unlocks at 10 depth points (naming unlocks at 25). */
  avatar_url: string | null
  avatar_unlocked: boolean
  /** Depth points still needed to unlock the avatar (0 when unlocked). */
  avatar_signals_to_unlock: number
  /** The assigned fellowship face is revealed: the seat's first meeting
      (keystone 1) is complete, or the depth milestone is reached.
      Customization (avatar_unlocked) is a separate, later door. */
  face_revealed: boolean
}

/** Fetch live archetype status. Returns null on any failure (caller falls back). */
export async function fetchArchetypeStatus(): Promise<ArchetypeStatus[] | null> {
  try {
    const res = await fetch('/council/archetypes/status', { credentials: 'include' })
    if (!res.ok) return null
    const j = (await res.json()) as { archetypes?: unknown }
    if (!Array.isArray(j.archetypes)) return null
    return j.archetypes as ArchetypeStatus[]
  } catch {
    return null
  }
}

/* ------------------------------------------------------------------ */
/* Keystone attention markers ("!")                                    */
/* ------------------------------------------------------------------ */

/** Why a seat wants the user's attention:
    intro = entry seat awaiting its first meeting; meet = an open
    keystone chain; recognition = only keystone 4 ("The echo") remains.
    discuss | clarify | challenge | offer = Fellowship P2: the seat has
    a pending observation it wants to discuss, clarify, challenge, or
    offer (the reason is a display classification of the observation;
    the observation itself is the content). When both a keystone marker
    and an observation marker are lit, `reason` carries the keystone
    reason (the Begin door keys off "intro") and the observation reason
    is preserved separately in `observation_reason`. */
export type KeystoneAttentionReason =
  | 'intro'
  | 'meet'
  | 'recognition'
  | 'discuss'
  | 'clarify'
  | 'challenge'
  | 'offer'

export type KeystoneAttentionMarker = {
  attention: boolean
  reason: KeystoneAttentionReason | null
  keystone_reason?: KeystoneAttentionReason | null
  observation_reason?: KeystoneAttentionReason | null
  observation_ids?: string[]
  observation_count?: number
}

/** Per-seat attention state from GET /vision-execution/keystone-attention.
    `seeded` false = the account has no "Meet your council" initiative yet:
    an honest empty state with no markers, not an error. */
export type KeystoneAttention = {
  seeded: boolean
  markers: Record<string, KeystoneAttentionMarker>
}

/** Fetch keystone attention markers. Returns null on any failure (no markers). */
export async function fetchKeystoneAttention(): Promise<KeystoneAttention | null> {
  try {
    const res = await fetch('/vision-execution/keystone-attention', { credentials: 'include' })
    if (!res.ok) return null
    const j = (await res.json()) as Partial<KeystoneAttention>
    if (typeof j.seeded !== 'boolean' || !j.markers || typeof j.markers !== 'object') return null
    return j as KeystoneAttention
  } catch {
    return null
  }
}

/**
 * Honest seed fallback — the 7 stock archetypes at 0 depth. Mirrors
 * local_ai/council/archetypes.py STOCK_ARCHETYPES verbatim (prompt_frame
 * and strand_weights); the Skeptic gets a uniform distribution (its real
 * weights are computed per-user by the backend). The verbatim match is
 * pinned by archetypes.test.ts — if the backend text changes, update
 * both together; a frontend-only edit re-opens the drift this fallback
 * had for 5 of 7 seats before 2026-10-24.
 */
export const STOCK_ARCHETYPE_FALLBACK: ArchetypeStatus[] = [
  {
    id: 'mentor',
    display_name: 'Mentor',
    strand_weights: { self: 0.35, number: 0.3, word: 0.15, people: 0.1, image: 0.05, sound: 0.03, body: 0.02 },
    depth: 0,
    band: 'not yet trained',
    prompt_frame:
      'The long view, the cultivator. You create the conditions for insight — read the terrain, name what matters, and let the user arrive at their own answer rather than handing it to them. Patient and unhurried; you see seasons, not days.',
    twigs: [],
    is_skeptic: false,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
  },
  {
    id: 'champion',
    display_name: 'Champion',
    strand_weights: { body: 0.35, self: 0.3, number: 0.15, people: 0.1, word: 0.05, image: 0.03, sound: 0.02 },
    depth: 0,
    band: 'not yet trained',
    prompt_frame:
      "You pick the hill, and you name the price. You fight for what costs something — cheap fights don't interest you, and you will tell the user when a hill isn't worth dying on. Fierce and direct: when a fight is real, you refuse to let them dither; when it isn't, you refuse to manufacture one.",
    twigs: [],
    is_skeptic: false,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
  },
  {
    id: 'guardian',
    display_name: 'Guardian',
    strand_weights: { people: 0.35, body: 0.25, self: 0.2, word: 0.1, image: 0.05, number: 0.03, sound: 0.02 },
    depth: 0,
    band: 'not yet trained',
    prompt_frame:
      "You stand watch over what the user needs in order to flourish — time, money, body, people, the future they're building. You ask what must be protected and what protection would cost, because safety that's too tight starves growth. Steady and sheltering; slow to move, impossible to move once moved.",
    twigs: [],
    is_skeptic: false,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
  },
  {
    id: 'maverick',
    display_name: 'Maverick',
    strand_weights: { word: 0.3, image: 0.25, number: 0.2, self: 0.15, sound: 0.05, people: 0.03, body: 0.02 },
    depth: 0,
    band: 'not yet trained',
    prompt_frame:
      'You hunt locked doors — rules followed out of habit, fear, or social pressure that nobody chose. You ask who the rule serves, and you refuse to confuse established order with necessary order. Independent and restless, allergic to captivity that calls itself normal.',
    twigs: [],
    is_skeptic: false,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
  },
  {
    id: 'ambassador',
    display_name: 'Ambassador',
    strand_weights: { word: 0.3, image: 0.25, people: 0.2, self: 0.15, number: 0.05, sound: 0.03, body: 0.02 },
    depth: 0,
    band: 'not yet trained',
    prompt_frame:
      "You translate between worlds — other people, the user's own warring inner voices, perspectives that can't hear each other. You hold that different views can be legitimately true at once, without forcing them to become one view. Patient, curious about the other side, unwilling to trade truth for agreement.",
    twigs: [],
    is_skeptic: false,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
  },
  {
    id: 'conductor',
    display_name: 'Conductor',
    strand_weights: { self: 0.25, number: 0.2, word: 0.15, people: 0.15, image: 0.1, body: 0.1, sound: 0.05 },
    depth: 0,
    band: 'not yet trained',
    prompt_frame:
      "Synthesizes after the others speak. You weave the council's voices into something coherent — not a compromise, but the shape underneath the disagreement. Balanced, integrative, oriented toward what actually works.",
    twigs: [],
    is_skeptic: false,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
  },
  {
    id: 'skeptic',
    display_name: 'Skeptic',
    strand_weights: { word: 1 / 7, number: 1 / 7, image: 1 / 7, sound: 1 / 7, body: 1 / 7, people: 1 / 7, self: 1 / 7 },
    depth: 0,
    band: 'not yet trained',
    prompt_frame:
      "Names what's being avoided. You voice the worry nobody's saying out loud — the risk everyone's stepping around, the flaw in the favored plan, the question that makes the room uncomfortable. Not contrarian for sport: you go where the user isn't looking, because that's where the blind spots live.",
    twigs: [],
    is_skeptic: true,
    avatar_url: null,
    avatar_unlocked: false,
    avatar_signals_to_unlock: 10,
    face_revealed: false,
  },
]

/** The strand key carrying the most weight in an archetype — drives branch coloring. */
export function dominantStrandKey(a: ArchetypeStatus): string | null {
  let best: string | null = null
  let bestW = -1
  for (const [k, w] of Object.entries(a.strand_weights ?? {})) {
    if (w > bestW) {
      bestW = w
      best = k
    }
  }
  return best
}
