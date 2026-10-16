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
 * The 7 strand agents (Voice, Logic, Eye, Ear, Hands, Heart, Compass) replaced the
 * old five council seats (strategist, operator, analyst, governance, brand). Legacy stored seats are
 * remapped on load — see `migrateLegacySeatIdsToStrandAgents`.
 */
import { GENERATED_BUILTIN_PERSONA_CONTENT } from './builtinPersonas.generated'

/**
 * Presentation-only metadata for built-in actors (icons, lanes).
 *
 * Persona CONTENT (purpose, values, tone, …) is generated from the backend
 * (`local_ai/zenaf_tools.py :: BUILT_IN_PERSONA_DEFINITIONS`) — see
 * `builtinPersonas.generated.ts`. Never hand-copy content here; the old
 * drift happened exactly that way. `skeptic` is the one frontend-only
 * archetype and stays hand-authored below (single-sourced, not duplicated).
 */
const BUILTIN_PRESENTATION: Record<string, { icon?: PerspectiveIconId; actor_kind: ActorKind }> = {
  zenaf: { actor_kind: 'synthesis' },
  storyteller: { actor_kind: 'archetype', icon: 'mask' },
  patternist: { actor_kind: 'archetype', icon: 'magnifier' },
  seer: { actor_kind: 'archetype', icon: 'spiral' },
  songwriter: { actor_kind: 'archetype', icon: 'note' },
  maker: { actor_kind: 'archetype', icon: 'gear' },
  mediator: { actor_kind: 'archetype', icon: 'scales' },
  guide: { actor_kind: 'archetype', icon: 'compass' },
}

/**
 * Display order of built-in actors. `thinking_partner` exists in the backend
 * definitions but the UI remaps it to `zenaf` (see
 * migrateThinkingPartnerAgentIdToZenaf), so it is not listed here.
 */
const BUILTIN_DISPLAY_ORDER = [
  'zenaf',
  'storyteller',
  'patternist',
  'seer',
  'songwriter',
  'maker',
  'mediator',
  'guide',
] as const

const BUILTIN_CREATED_AT = '2024-01-01T00:00:00.000Z'

function builtinFromGenerated(id: string): PerspectiveAgent {
  const c = GENERATED_BUILTIN_PERSONA_CONTENT[id]
  if (!c) throw new Error(`missing generated persona content for built-in '${id}'`)
  const p = BUILTIN_PRESENTATION[id] ?? { actor_kind: deriveActorKind(id) }
  return {
    id: c.id,
    name: c.name,
    icon: p.icon,
    actor_kind: p.actor_kind,
    strand: c.strand,
    role: c.role,
    purpose: c.purpose,
    values: [...c.values],
    aversions: [...c.aversions],
    reasoningStyle: [...c.reasoningStyle],
    tone: c.tone,
    domain: [...c.domain],
    decisionRule: c.decisionRule,
    worldview: c.worldview,
    constraints: c.constraints ? [...c.constraints] : undefined,
    examplePhrases: c.examplePhrases ? [...c.examplePhrases] : undefined,
    createdAt: BUILTIN_CREATED_AT,
  }
}

/**
 * Frontend-only archetype: the risk stress-test seat. The backend has no
 * skeptic definition; this entry is single-sourced here (not a copy of
 * anything), so it cannot drift.
 */
const SKEPTIC_PERSPECTIVE: PerspectiveAgent = {
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
  createdAt: BUILTIN_CREATED_AT,
}

/**
 * Built-in **actors** (voice / lens). Council **roles** (payload `mandate`) are separate — see `mandates.ts`.
 * Shown by default and fully editable.
 *
 * Content for the 7 strand agents (Voice, Logic, Eye, Ear, Hands, Heart, Compass)
 * plus the Zenaf synthesis seat is generated from the backend; only presentation metadata and the
 * frontend-only Skeptic live here.
 */
export const BUILT_IN_PERSPECTIVES: PerspectiveAgent[] = [
  ...BUILTIN_DISPLAY_ORDER.map(builtinFromGenerated),
  SKEPTIC_PERSPECTIVE,
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
      // The old Brand seat carried the legacy 'brand' lane; the Voice is a system archetype.
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
 * The Voice is not listed here: it inherited the old Brand seat's hero
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

/** Archetype seats that can spawn a personal copy (excludes Zenaf synthesis and the Voice core voice). */
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
