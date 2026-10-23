import { useEffect, useState } from 'react'
import type { CoreProfile } from './types'
import { TranscribableFieldRegion, CORE_PROFILE_CREATE_ENTITY_ID } from './focus'
import { ZENAF_VE_FOCUS_INSERT_TEXT, insertTextAtSelection, type VeFocusInsertTextDetail } from './focus/insertTextEvent'
import { readPrivacyMode } from '../ai-actions/privacyModeBridge'
import type { PerspectiveAgent } from '../perspectives/types'
import { AvatarDisplay } from '../components/AvatarDisplay'
import { CORE_PROFILE_ACTION_INTENTS } from './coreProfileTrace'
import { STRANDS } from '../living-tree/strands'

/**
 * "Your core" — the honest replacement for the create-core-profile form
 * (Joshua, 2026-10-22). The old UI implied a single structured form defines
 * the user; that is no longer how the system works. What actually forms the
 * core: (1) material the user uploads, sorted into the seven strands and
 * trained only after review, and (2) the targets the user sets — the
 * philosophical / theological orientation authored by them, never inferred
 * (edited in the Aspirations panel, rendered alongside this one).
 */
export function CoreHowItWorksPanel({ onUpload }: { onUpload: () => void }) {
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-warm-white">Your core isn't a form</h3>
        <p className="text-[11px] text-warm-white/50 leading-relaxed mt-1">
          No single profile defines you here. Your core is woven from what you give the
          system — and from what you aim it at.
        </p>
      </div>
      <div>
        <div className="text-[11px] font-semibold text-warm-white/70 uppercase tracking-wide">
          What you upload, by strand
        </div>
        <p className="text-[11px] text-warm-white/50 leading-relaxed mt-1">
          Upload conversations and material, and the sorter files each piece under the
          strand it belongs to — your tastes under Ear and Eye, your reasoning under Logic,
          your beliefs under Compass. Everything arrives as a proposal; nothing trains
          until you review it.
        </p>
        <ul className="mt-2 space-y-1.5">
          {STRANDS.map((s) => (
            <li key={s.key} className="flex items-baseline gap-2 text-[11px] leading-snug">
              <span
                className="inline-block h-2 w-2 shrink-0 rounded-full translate-y-[1px]"
                style={{ background: s.color }}
                aria-hidden
              />
              <span className="font-medium text-warm-white/80 w-14 shrink-0">{s.agentName}</span>
              <span className="text-warm-white/45">{s.tagline}</span>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={onUpload}
          className="mt-3 min-h-[44px] px-4 rounded-full bg-amber-600 text-amber-50 text-sm font-semibold"
        >
          Upload source material →
        </button>
      </div>
      <div>
        <div className="text-[11px] font-semibold text-warm-white/70 uppercase tracking-wide">
          The targets you set
        </div>
        <p className="text-[11px] text-warm-white/50 leading-relaxed mt-1">
          Alongside what you upload, you set the direction yourself — the philosophical
          and theological orientation the council should grow toward. Authored by you,
          never inferred from you. Set them in the panel below.
        </p>
      </div>
    </div>
  )
}

/** localStorage key for Brand ↔ Zenaf training thread (ZenafPresence + any future senders). */
export function coreProfileConversationStorageKey(profileId: string) {
  return `zenaf-core-profile-conversation-${profileId}`
}

/** POST /core-profiles/:id/conversation body routing (Zenaf training voice). */
export function coreProfileConversationRouting() {
  return {
    surface: 'core_profile',
    action_kind: 'suggestion_batch',
    action_intent: CORE_PROFILE_ACTION_INTENTS.conversation,
    actor_kind: 'synthesis',
    perspective_voice: 'zenaf',
    streaming: false,
    privacy_mode: readPrivacyMode(),
  } as const
}

export function BrandStructuredProfilePanel({
  profileId,
  brandActor,
  displayName,
  apiGet,
  onTrainWithZenaf,
  onWorkout,
}: {
  profileId: string
  brandActor: PerspectiveAgent
  displayName: string
  apiGet: <T>(path: string) => Promise<T>
  onTrainWithZenaf: () => void
  onWorkout: () => void
}) {
  const [profile, setProfile] = useState<CoreProfile | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    apiGet<CoreProfile>(`/core-profiles/${profileId}`)
      .then((data) => {
        if (!cancelled) setProfile(data)
      })
      .catch(() => {
        if (!cancelled) setProfile(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [profileId, apiGet])

  const previewSource = (profile?.core_definition ?? '').trim()

  const title = displayName.trim() || brandActor.name || 'Voice'

  if (loading) {
    return (
      <div className="rounded-lg border border-stone-700 bg-stone-900/55 p-4">
        <p className="text-stone-500 text-sm">Loading…</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-stone-700 bg-stone-900/55 p-4 space-y-3">
      <div className="flex items-start gap-3">
        <AvatarDisplay agent={brandActor} size="lg" className="text-stone-200 shrink-0" />
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold text-stone-100 truncate" title={title}>
            {title}
          </h3>
          <p
            className="text-xs text-stone-400 whitespace-pre-wrap leading-relaxed line-clamp-2 mt-1"
            title={previewSource || undefined}
          >
            {previewSource ? (
              previewSource
            ) : (
              <span className="text-stone-500 italic">No core definition yet.</span>
            )}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 items-center">
        <button
          type="button"
          onClick={onTrainWithZenaf}
          className="text-sm font-medium text-red-500 hover:text-red-400 transition-colors"
        >
          Train with Zenaf →
        </button>
        <button
          type="button"
          onClick={onWorkout}
          className="text-sm font-medium text-red-500 hover:text-red-400 transition-colors"
        >
          Workout →
        </button>
      </div>
    </div>
  )
}

export function CreateCoreProfileForm({
  onSave,
  onCancel,
}: {
  onSave: (v: {
    name: string
    core_definition?: string
    current_goals?: string
    growth_focus_12_months?: string
    economic_engine?: string
    non_negotiables?: string
    strategic_filter?: string
    current_constraints?: string
    capacity_limit?: string
    kill_philosophy?: string
    strength_positioning?: string
  }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [core_definition, setCoreDefinition] = useState('')
  const [current_goals, setCurrentGoals] = useState('')

  useEffect(() => {
    const onInsert = (e: Event) => {
      const d = (e as CustomEvent<VeFocusInsertTextDetail>).detail
      if (!d?.text || d.entity_type !== 'core_profile' || d.entity_id !== CORE_PROFILE_CREATE_ENTITY_ID) return
      const { field_key, text, selectionStart, selectionEnd } = d
      const a = selectionStart ?? 0
      const b = selectionEnd ?? 0
      if (field_key === 'name') setName((p) => insertTextAtSelection(p, text, a, b))
      else if (field_key === 'core_definition') setCoreDefinition((p) => insertTextAtSelection(p, text, a, b))
      else if (field_key === 'current_goals') setCurrentGoals((p) => insertTextAtSelection(p, text, a, b))
    }
    window.addEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
    return () => window.removeEventListener(ZENAF_VE_FOCUS_INSERT_TEXT, onInsert)
  }, [])

  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4 space-y-3">
      <p className="text-[11px] text-warm-white/50 leading-relaxed">
        This becomes your <span className="text-warm-white/70">core profile</span> — the single structured source Zenaf uses
        for your voice and constraints. Perspectives are lenses on top, not competing identities.
      </p>
      <div>
        <label className="block text-xs font-medium text-warm-white/55 mb-1">Core profile name</label>
        <TranscribableFieldRegion
          surface="core_profile"
          entity_type="core_profile"
          entity_id={CORE_PROFILE_CREATE_ENTITY_ID}
          field_key="name"
          field_label="Core profile name"
          field_kind="idea_body"
          getCurrentText={() => name}
        >
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Your Name · Zenaf build"
            className="w-full px-3 py-2 rounded-lg bg-canvas border border-[color:var(--color-border-strong)] text-[color:var(--map-ink-primary)] placeholder:text-[color:var(--map-muted-ink)] text-sm"
          />
        </TranscribableFieldRegion>
      </div>
      <div>
        <label className="block text-xs font-medium text-warm-white/55 mb-1">Core definition</label>
        <TranscribableFieldRegion
          surface="core_profile"
          entity_type="core_profile"
          entity_id={CORE_PROFILE_CREATE_ENTITY_ID}
          field_key="core_definition"
          field_label="Core definition"
          field_kind="long_form_strategy"
          getCurrentText={() => core_definition}
        >
          <textarea
            value={core_definition}
            onChange={(e) => setCoreDefinition(e.target.value)}
            placeholder="Who you are in this product and how you prioritize (e.g. align execution with vision; ship by strategic value and energy impact)."
            rows={2}
            className="w-full px-3 py-2 rounded-lg bg-canvas border border-[color:var(--color-border-strong)] text-[color:var(--map-ink-primary)] placeholder:text-[color:var(--map-muted-ink)] text-sm resize-y focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent/60"
          />
        </TranscribableFieldRegion>
      </div>
      <div>
        <label className="block text-xs font-medium text-warm-white/55 mb-1">Current goals</label>
        <TranscribableFieldRegion
          surface="core_profile"
          entity_type="core_profile"
          entity_id={CORE_PROFILE_CREATE_ENTITY_ID}
          field_key="current_goals"
          field_label="Current goals"
          field_kind="long_form_strategy"
          getCurrentText={() => current_goals}
        >
          <textarea
            value={current_goals}
            onChange={(e) => setCurrentGoals(e.target.value)}
            placeholder="What you’re optimizing for right now (core profile)"
            rows={2}
            className="w-full px-3 py-2 rounded-lg bg-canvas border border-[color:var(--color-border-strong)] text-[color:var(--map-ink-primary)] placeholder:text-[color:var(--map-muted-ink)] text-sm resize-y"
          />
        </TranscribableFieldRegion>
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={() => onSave({ name, core_definition, current_goals })} className="px-3 py-1.5 rounded-lg bg-accent text-warm-white text-sm">
          Save
        </button>
        <button type="button" onClick={onCancel} className="px-3 py-1.5 rounded-lg bg-surface-raised border border-[color:var(--color-border)] text-warm-white/90 text-sm">
          Cancel
        </button>
      </div>
    </div>
  )
}
