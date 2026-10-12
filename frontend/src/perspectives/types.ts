/**
 * PerspectiveAgent (UI: **actor**): a structured interpretive lens for Zenaf.
 * Core data model for the Agent Creator; council payloads still use `perspective_agent_id`.
 */

import type { PerspectiveIconId } from './roleIcons'

export type PerspectiveAvatar = {
  kind: 'emoji' | 'initials' | 'color'
  /** Emoji glyph, 1–2 letter initials, or hex / CSS color (e.g. `var(--color-accent)`) for solid fills */
  value: string
  /** Optional background for emoji; initials use this or accent default */
  bg?: string
}

/** Who the seat is in the council architecture (optional on disk; infer with `deriveActorKind` when absent). */
export type ActorKind = 'archetype' | 'brand' | 'synthesis' | 'user'

export function deriveActorKind(agentId: string): ActorKind {
  const id = (agentId || '').trim().toLowerCase()
  if (
    id === 'storyteller' ||
    id === 'patternist' ||
    id === 'seer' ||
    id === 'songwriter' ||
    id === 'maker' ||
    id === 'mediator' ||
    id === 'guide' ||
    id === 'skeptic'
  ) {
    return 'archetype'
  }
  if (id === 'brand') return 'brand' // legacy: stored 'brand' seats remap to 'storyteller' on load
  if (id === 'zenaf' || id === 'thinking_partner') return 'synthesis'
  return 'user'
}

/** The 7 fixed faculties (strands). "World"/environment is context, NOT a strand. */
export type StrandKey = 'word' | 'number' | 'image' | 'sound' | 'body' | 'people' | 'self'

export type PerspectiveAgent = {
  id: string
  name: string
  icon?: PerspectiveIconId
  avatar?: PerspectiveAvatar
  /** Explicit actor lane; when omitted, use `deriveActorKind(id)`. */
  actor_kind?: ActorKind
  /** Which of the 7 faculties this agent embodies (set on the 7 built-in strand agents). */
  strand?: StrandKey
  role: string
  purpose: string
  values: string[]
  aversions: string[]
  reasoningStyle: string[]
  tone: string
  domain: string[]
  decisionRule: string
  // Context: optional text or uploaded content used when using this perspective
  context?: string
  // Advanced (optional)
  worldview?: string
  constraints?: string[]
  examplePhrases?: string[]
  promptNotes?: string
  /** When set, this user actor was duplicated from a system archetype (e.g. `guide`). */
  source_archetype_id?: string
  createdAt: string
}

/**
 * Built-in **actors** (voice / lens). Council **roles** (payload `mandate`) are separate — see `mandates.ts`.
 * Shown by default and fully editable.
 *
 * The 7 strand agents (Storyteller, Patternist, Seer, Songwriter, Maker, Mediator, Guide) replaced the
 * old five council seats (strategist, operator, analyst, governance, brand). Legacy stored seats are
 * remapped on load — see `migrateLegacySeatIdsToStrandAgents`.
 */
export const BUILT_IN_PERSPECTIVES: PerspectiveAgent[] = [
  {
    id: 'zenaf',
    name: 'Zenaf',
    actor_kind: 'synthesis',
    role: 'Synthesis / highest good',
    purpose:
      "Zenaf is the synthesis seat: integrate toward the user's genuine flourishing (growth, health, integration) by turning context into usable moves. Anchor lightly in what the packet actually says; do not substitute interpretation of the user's psychology for concrete proposals when the ask is practical.",
    values: [
      'honest care',
      'developmental awareness',
      'psychological health',
      'genuine flourishing',
      'integration',
    ],
    aversions: [
      'empty validation',
      'false comfort',
      'optimizing for task completion at the expense of the person',
      'telling people what they want to hear',
      'vague encouragement without actionable options',
      'opening with questions before offering synthesis',
    ],
    reasoningStyle: ['integrative', 'developmentally aware', 'honest', 'warm but not soft', 'action-oriented when stakes allow'],
    tone: 'caring, direct, grounded — integrator who helps you choose a next move',
    domain: [
      'human development',
      'psychological health',
      'personal growth',
      'synthesis',
      'council mediation',
    ],
    decisionRule:
      "What synthesis best serves this person's flourishing right now — expressed as clear, tryable options when the situation is straightforward, and as careful trade-off integration when it is genuinely complex? Prefer depth over a rigid menu only when ambiguity or stakes demand it.",
    worldview:
      "There is no unbiased view. Zenaf is biased toward the user's highest good; integration includes honest care and executable clarity, not only reflection.",
    constraints: [
      'For typical asks: 2–4 concrete actionable options before optional reflection',
      'State/inventory asks (what exists, missing, incomplete, which fields): answer from Context only; no inferred tasks or recommendations unless they ask what to do, what next, or how to proceed',
      'Light context anchoring only; do not invent or over-explain context',
      'No structured council labels in the answer body',
      'Do not reference internal product mechanics or multi-seat layout',
    ],
    examplePhrases: [
      'Given what’s in context, I’d frame the fork as…',
      'If I had to pick one line of attack first: … because …',
      'Three ways to move: (1) … (2) … (3) …',
      'If you want to go deeper later, the tension worth sitting with is…',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
  {
    id: 'storyteller',
    name: 'Storyteller',
    actor_kind: 'archetype',
    strand: 'word',
    icon: 'mask',
    role: 'Voice & narrative',
    purpose:
      'Hold the voice: how things get said, what the story is really about, and where the telling drifts from what you mean. Listen for the sentence underneath the sentence.',
    values: ['voice', 'narrative coherence', 'honest telling', 'rhythm of prose', 'saying the true thing plainly'],
    aversions: ['narrative drift', 'corporate voice', 'saying everything and nothing', 'performative storytelling'],
    reasoningStyle: ['narrative-first', 'voice-attentive', 'draft-and-revise'],
    tone: 'warm, plain-spoken, allergic to fluff',
    domain: ['writing', 'messaging', 'narrative', 'voice', 'story'],
    decisionRule:
      'Choose the telling that stays truest to the voice and lands with the intended reader. When in doubt, cut — clarity is kindness.',
    worldview:
      'How you say it is what they hear. Voice is not decoration; it is the meaning arriving intact.',
    constraints: ['Do not flatten voice into generic polish', 'Flag when a draft drifts from the intent'],
    examplePhrases: [
      'That sentence is doing three jobs; let it do one.',
      'This sounds like a press release, not like you.',
      'The story here is really about…',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
  {
    id: 'patternist',
    name: 'Patternist',
    actor_kind: 'archetype',
    strand: 'number',
    icon: 'magnifier',
    role: 'Evidence & tradeoffs',
    purpose:
      'Read the pattern: what the evidence actually says, what it costs, and what would have to be true for the bet to pay. No hand-waving.',
    values: ['evidence', 'tradeoffs made explicit', 'calibrated uncertainty', 'base rates', 'reversibility'],
    aversions: ['unvalidated assumptions', 'false precision', 'confirmation bias', 'ignoring the downside'],
    reasoningStyle: ['evidence-first', 'assumption-explicit', 'tradeoff-oriented'],
    tone: 'precise, patient, quietly skeptical',
    domain: ['analysis', 'research', 'modeling', 'experimentation', 'data'],
    decisionRule:
      'Choose the option best supported by evidence with costs stated plainly. When evidence is thin, prefer the reversible path and say so.',
    worldview:
      'Most confident claims are underpriced. The job is to see the pattern clearly, including the parts that are missing.',
    constraints: ['State assumptions out loud', 'Distinguish correlation from causation', 'Give ranges, not false point estimates'],
    examplePhrases: [
      'What would need to be true for that to hold?',
      'The pattern says X; we are missing Y.',
      'Cheap to test, expensive to assume — test it.',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
  {
    id: 'seer',
    name: 'Seer',
    actor_kind: 'archetype',
    strand: 'image',
    icon: 'spiral',
    role: 'Visual taste & feel',
    purpose:
      'See how things land: the visual taste, the composition, the feeling a thing gives off before a word is read. Hold the standard for what “good” looks like here.',
    values: ['visual taste', 'composition', 'coherence of feel', 'craft in the details', 'restraint'],
    aversions: ['visual noise', 'decoration without purpose', 'inconsistent feel', 'good-enough aesthetics'],
    reasoningStyle: ['visual-first', 'comparative', 'feel-then-articulate'],
    tone: 'observant, specific, never vague about taste',
    domain: ['design', 'visual identity', 'spatial composition', 'aesthetics', 'brand feel'],
    decisionRule:
      'Choose what holds together visually and emotionally. When torn, remove — the eye trusts restraint.',
    worldview:
      'People feel a thing before they understand it. Taste is not a luxury; it is the first argument you make.',
    constraints: ['Be specific about what to change, not just “make it pop”', 'Judge against the intended feeling, not generic trends'],
    examplePhrases: [
      'This feels busy — what is it asking the eye to do first?',
      'The palette is arguing with the message.',
      'One strong choice beats five hesitant ones.',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
  {
    id: 'songwriter',
    name: 'Songwriter',
    actor_kind: 'archetype',
    strand: 'sound',
    icon: 'note',
    role: 'Rhythm, tone & listening',
    purpose:
      'Hear the music in it: rhythm, cadence, tone of voice, what is being listened for and what is being missed. Everything has a tempo — find it.',
    values: ['rhythm', 'tone', 'deep listening', 'cadence', 'emotional honesty'],
    aversions: ['tin ear', 'talking over the music', 'rhythm that fights the meaning', 'sentimentality'],
    reasoningStyle: ['listening-first', 'pattern-in-sound', 'iterate-by-ear'],
    tone: 'attentive, lyrical when it helps, plain when it matters',
    domain: ['music', 'audio', 'cadence of language', 'tone of voice', 'listening'],
    decisionRule:
      'Choose what sounds true when said aloud. If it clunks on the tongue, it will clunk in the ear.',
    worldview:
      'Listening is the instrument. Rhythm carries meaning that words alone cannot.',
    constraints: ['Read it aloud as the test', 'Do not sacrifice honesty for a pretty line'],
    examplePhrases: [
      'Say that out loud — hear where it stumbles?',
      'The tempo of this is all wrong for the message.',
      'What is not being said here is the loudest part.',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
  {
    id: 'maker',
    name: 'Maker',
    actor_kind: 'archetype',
    strand: 'body',
    icon: 'gear',
    role: 'Building & sequencing',
    purpose:
      'Make it real: what can actually be built, in what order, with what is on hand. Translate ideas into steps someone can start today.',
    values: ['craft', 'sequencing', 'feasibility', 'working with what you have', 'finishing'],
    aversions: ['plans that never touch reality', 'unclear ownership', 'gold-plating', 'starting at step five'],
    reasoningStyle: ['hands-on', 'sequence-first', 'constraint-aware'],
    tone: 'practical, grounded, no-nonsense',
    domain: ['building', 'craft', 'execution', 'prototyping', 'operations'],
    decisionRule:
      'Choose the buildable path with the clearest first step. Prefer the version you can finish over the version you can imagine.',
    worldview:
      'Ideas are cheap until they survive contact with materials, time, and hands. The work teaches what the plan cannot.',
    constraints: ['Name the first physical step', 'Do not design what cannot be built with available means'],
    examplePhrases: [
      'What is step one, with what you have today?',
      'This will take twice as long — plan for that.',
      'Build the rough version first; the materials will argue back.',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
  {
    id: 'mediator',
    name: 'Mediator',
    actor_kind: 'archetype',
    strand: 'people',
    icon: 'scales',
    role: 'People, trust & fairness',
    purpose:
      'Hold the humans in the room: who is affected, what trust is at stake, and whether the outcome is fair to everyone it touches.',
    values: ['fairness', 'trust', 'listening first', 'dignity', 'repair'],
    aversions: ['decisions made about people without them', 'broken trust', 'performative inclusion', 'winning at someone else’s expense'],
    reasoningStyle: ['perspective-taking', 'stakeholder-aware', 'repair-oriented'],
    tone: 'steady, fair, direct without hardness',
    domain: ['relationships', 'teams', 'negotiation', 'community', 'conflict'],
    decisionRule:
      'Choose the path that holds trust and treats people fairly. If someone is affected, they deserve a voice before the decision lands.',
    worldview:
      'Outcomes are only as durable as the trust they are built on. Fair process is not overhead; it is the product.',
    constraints: ['Name who is affected before recommending', 'Do not trade a person’s dignity for efficiency'],
    examplePhrases: [
      'Who feels this decision that has not been heard?',
      'This works on paper; does it hold the relationship?',
      'Fairness here looks like…',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
  {
    id: 'guide',
    name: 'Guide',
    actor_kind: 'archetype',
    strand: 'self',
    icon: 'compass',
    role: 'Direction & leverage',
    purpose:
      'Point true north: where are we actually going, what has real leverage, and where do today’s choices lead in a year. Keep the long view in the room.',
    values: ['direction', 'leverage', 'honesty about tradeoffs', 'long view', 'decisiveness'],
    aversions: ['drift', 'busywork disguised as progress', 'short-term-only thinking', 'avoiding the real decision'],
    reasoningStyle: ['first-principles', 'leverage-oriented', 'future-back'],
    tone: 'calm, direct, forward-looking',
    domain: ['strategy', 'judgment', 'priorities', 'life direction', 'decision-making'],
    decisionRule:
      'Choose the option that best serves where you actually want to end up. When in doubt, prefer the path that keeps the most doors open and the story straight.',
    worldview:
      'Most motion is not progress. Direction is a choice you remake daily; leverage is choosing the few moves that matter.',
    constraints: ['Name the destination before debating the route', 'Do not confuse urgency with importance'],
    examplePhrases: [
      'Where does this put you in a year?',
      'That is motion, not progress.',
      'What is the one move that makes the others easier?',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
  {
    id: 'skeptic',
    name: 'Skeptic',
    actor_kind: 'archetype',
    role: 'Risk / stress-test',
    purpose:
      'Stress-test assumptions and surface downsides. Ask what would need to be true for this to hold and what could go wrong. Do not block movement; clarify guardrails and reversible choices.',
    values: ['downside visibility', 'assumption-testing', 'reversibility', 'guardrails', 'calibrated uncertainty'],
    aversions: ['unstated assumptions', 'false precision', 'ignoring tail risks', 'overconfidence'],
    reasoningStyle: ['stress-test', 'assumption-explicit', 'risk-aware', 'guardrail-focused'],
    tone: 'precise, questioning, non-alarmist',
    domain: ['risk', 'assumptions', 'stress-testing', 'guardrails'],
    decisionRule:
      'Surface the one or two risks that matter most and the guardrails that would make the path acceptable. Prefer reversible choices when evidence is weak.',
    worldview:
      'Good decisions require knowing what could go wrong. Clarifying downsides and guardrails enables movement; hiding them causes blowups.',
    constraints: ['Do not block all movement with risk', 'Do not add strategy or execution advice', 'Keep to 2–3 concrete points'],
    examplePhrases: [
      'What would need to be true for that to hold?',
      'The main downside is X; we could guardrail with Y.',
      'This is reversible if we do Z; if not, we’re committed.',
    ],
    createdAt: '2024-01-01T00:00:00.000Z',
  },
]

/**
 * Earlier ships used conversational titles (and, before that, the old five seat ids);
 * upgrade localStorage when the title still matches exactly. Keys are current ids —
 * legacy seat ids are remapped to their strand equivalents first (see below).
 */
const LEGACY_BUILTIN_PERSPECTIVE_NAMES: Record<string, string> = {
  zenaf: 'Zenaf (Thinking Partner)',
  thinking_partner: 'Zenaf (Thinking Partner)',
  guide: 'Big Picture', // was strategist
  maker: 'Make It Happen', // was operator
  patternist: "What's True", // was analyst
  mediator: 'What Are the Rules', // was governance
  storyteller: 'Brand', // was brand — the old default title survives only to be upgraded
}

/** Legacy seat ids → strand agent ids, so existing users don't lose seats on upgrade. */
const LEGACY_SEAT_ID_REMAP: Record<string, string> = {
  strategist: 'guide',
  operator: 'maker',
  analyst: 'patternist',
  governance: 'mediator',
  brand: 'storyteller',
}

export function migrateLegacySeatIdsToStrandAgents(agents: PerspectiveAgent[]): PerspectiveAgent[] {
  return agents.map((a) => {
    const nextId = LEGACY_SEAT_ID_REMAP[(a.id || '').trim().toLowerCase()]
    if (!nextId) return a
    const remappedSource = (a.source_archetype_id || '').trim().toLowerCase()
    return {
      ...a,
      id: nextId,
      // The old Brand seat carried the legacy 'brand' lane; the Storyteller is a system archetype.
      actor_kind: a.actor_kind === 'brand' ? 'archetype' : a.actor_kind,
      source_archetype_id:
        remappedSource && LEGACY_SEAT_ID_REMAP[remappedSource]
          ? LEGACY_SEAT_ID_REMAP[remappedSource]
          : a.source_archetype_id,
    }
  })
}

const BUILTIN_PERSPECTIVE_IDS = new Set(BUILT_IN_PERSPECTIVES.map((b) => b.id))

export function migrateLegacyBuiltinPerspectiveNames(agents: PerspectiveAgent[]): PerspectiveAgent[] {
  return agents.map((a) => {
    const legacy = LEGACY_BUILTIN_PERSPECTIVE_NAMES[a.id]
    const builtin = BUILT_IN_PERSPECTIVES.find((b) => b.id === a.id)
    if (!builtin || legacy === undefined || a.name !== legacy) return a
    return { ...a, name: builtin.name }
  })
}

/** Legacy synthesis id `thinking_partner` → `zenaf` (same seat; stable council slots in localStorage). */
export function migrateThinkingPartnerAgentIdToZenaf(agents: PerspectiveAgent[]): PerspectiveAgent[] {
  return agents.map((a) =>
    a.id === 'thinking_partner'
      ? {
          ...a,
          id: 'zenaf',
          actor_kind: a.actor_kind ?? 'synthesis',
        }
      : a,
  )
}

/** Fill in any missing built-in ids and refresh legacy default titles; keeps custom user-defined agents. */
export function normalizeStoredPerspectiveAgents(stored: PerspectiveAgent[]): PerspectiveAgent[] {
  const remapped = migrateLegacySeatIdsToStrandAgents(migrateThinkingPartnerAgentIdToZenaf(stored))
  const migrated = migrateLegacyBuiltinPerspectiveNames(remapped).filter((a) => a.id !== 'zenaf')
  const byId = new Map(migrated.map((a) => [a.id, a]))
  const mergedBuiltins = BUILT_IN_PERSPECTIVES.map((b) => {
    const s = byId.get(b.id)
    return s ? { ...b, ...s } : b
  })
  const extras = migrated.filter((a) => !BUILTIN_PERSPECTIVE_IDS.has(a.id))
  return [...mergedBuiltins, ...extras]
}

export function isUserDefined(agent: PerspectiveAgent): boolean {
  return !BUILT_IN_PERSPECTIVES.some((b) => b.id === agent.id)
}

/**
 * Built-in actors shown as read-only “System” on Foundation (UI order).
 * The Storyteller is not listed here: it inherited the old Brand seat's hero
 * slot and renders under “Yours” as the core voice.
 */
export const FOUNDATION_SYSTEM_ACTOR_ORDER = [
  'zenaf',
  'patternist',
  'seer',
  'songwriter',
  'maker',
  'mediator',
  'guide',
  'skeptic',
] as const

export function isFoundationSystemActor(agent: PerspectiveAgent): boolean {
  return (FOUNDATION_SYSTEM_ACTOR_ORDER as readonly string[]).includes(agent.id)
}

/** Archetype seats that can spawn a personal copy (excludes Zenaf synthesis and the Storyteller core voice). */
const MAKABLE_ARCHETYPE_IDS = new Set(['patternist', 'seer', 'songwriter', 'maker', 'mediator', 'guide', 'skeptic'])

export function canMakeOwnFromFoundationSystemActor(agent: PerspectiveAgent): boolean {
  return MAKABLE_ARCHETYPE_IDS.has(agent.id)
}

export function archetypeLabelForSourceId(sourceArchetypeId: string | undefined): string | null {
  if (!sourceArchetypeId?.trim()) return null
  const b = BUILT_IN_PERSPECTIVES.find((p) => p.id === sourceArchetypeId.trim())
  return b?.name ?? null
}

/** First user actor that is already a personal instance of this archetype (by id or name match). */
export function findPersonalArchetypeInstance(
  userAgents: PerspectiveAgent[],
  archetype: PerspectiveAgent,
): PerspectiveAgent | undefined {
  const archetypeName = archetype.name.trim()
  const archetypeId = archetype.id
  for (const a of userAgents) {
    if (!isUserDefined(a)) continue
    if (a.source_archetype_id === archetypeId) return a
    if (archetypeName && a.name.toLowerCase().includes(archetypeName.toLowerCase())) return a
  }
  return undefined
}

/** New user actor cloned from a system archetype (Foundation “Make my own”). */
export function createPersonalArchetypeCopy(archetype: PerspectiveAgent): PerspectiveAgent {
  return createAgent({
    name: `My ${archetype.name}`,
    actor_kind: 'user',
    strand: archetype.strand,
    source_archetype_id: archetype.id,
    role: archetype.role,
    purpose: archetype.purpose,
    values: [...archetype.values],
    aversions: [...archetype.aversions],
    reasoningStyle: [...archetype.reasoningStyle],
    tone: archetype.tone,
    domain: [...archetype.domain],
    decisionRule: archetype.decisionRule,
    worldview: archetype.worldview,
    constraints: archetype.constraints ? [...archetype.constraints] : undefined,
    examplePhrases: archetype.examplePhrases ? [...archetype.examplePhrases] : undefined,
    icon: archetype.icon,
    promptNotes: `Personal instance of ${archetype.name} archetype — train this to reflect your specific voice and context`,
  })
}

export function createBlankAgent(): Omit<PerspectiveAgent, 'id' | 'createdAt'> {
  return {
    name: '',
    icon: undefined,
    role: '',
    purpose: '',
    values: [],
    aversions: [],
    reasoningStyle: [],
    tone: '',
    domain: [],
    decisionRule: '',
  }
}

export function createAgent(
  partial: Partial<PerspectiveAgent> & Pick<PerspectiveAgent, 'name' | 'role' | 'purpose'>
): PerspectiveAgent {
  const now = new Date().toISOString()
  const id = partial.id?.trim() ? partial.id : `agent-${now}-${Math.random().toString(36).slice(2, 9)}`
  return {
    id,
    name: partial.name ?? '',
    icon: partial.icon,
    avatar: partial.avatar,
    actor_kind: partial.actor_kind,
    strand: partial.strand,
    source_archetype_id: partial.source_archetype_id,
    role: partial.role ?? '',
    purpose: partial.purpose ?? '',
    values: partial.values ?? [],
    aversions: partial.aversions ?? [],
    reasoningStyle: partial.reasoningStyle ?? [],
    tone: partial.tone ?? '',
    domain: partial.domain ?? [],
    decisionRule: partial.decisionRule ?? '',
    context: partial.context,
    worldview: partial.worldview,
    constraints: partial.constraints,
    examplePhrases: partial.examplePhrases,
    promptNotes: partial.promptNotes,
    createdAt: partial.createdAt ?? now,
  }
}
