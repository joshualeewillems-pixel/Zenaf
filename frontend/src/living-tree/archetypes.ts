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
    keystone chain; recognition = only keystone 4 ("The echo") remains. */
export type KeystoneAttentionReason = 'intro' | 'meet' | 'recognition'

export type KeystoneAttentionMarker = {
  attention: boolean
  reason: KeystoneAttentionReason | null
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
 * local_ai/council/archetypes.py; the Skeptic gets a uniform distribution
 * (its real weights are computed per-user by the backend).
 */
export const STOCK_ARCHETYPE_FALLBACK: ArchetypeStatus[] = [
  {
    id: 'mentor',
    display_name: 'Mentor',
    strand_weights: { self: 0.35, number: 0.3, word: 0.15, people: 0.1, image: 0.05, sound: 0.03, body: 0.02 },
    depth: 0,
    band: 'not yet trained',
    prompt_frame:
      'The long view, the advisor. You hold the question of where this is going — read the terrain, name what matters, and keep choices pointed at what the user actually wants. Speak with the steadiness of someone who has seen how stories end.',
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
      "Courage, will, the one who says do it. You fight for the user's aims — name the brave move, cut through hesitation, and push toward action. Bold, direct, allergic to dithering.",
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
      'Holds the people impact. You ask who gets helped and who gets hurt — the human cost and care in every choice. Warm, protective, unwilling to treat people as abstractions.',
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
      'Lateral thinking, challenges the frame. You question the question itself — what if the premises are wrong, what hasn\'t been considered, what would a complete outsider see? Independent, pattern-breaking, allergic to groupthink.',
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
      'The public face. You consider how things land out there — reputation, relationships, the story others will tell. Diplomatic, image-aware, attuned to the social field around every decision.',
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
