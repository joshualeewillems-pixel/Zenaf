import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  InfluenceLink,
  InfluenceSourceKind,
  InfluenceTargetKind,
  InfluenceWeight,
} from './entityInfluences'
import { getInfluencesForSource, setInfluencesForSource, INFLUENCE_TARGET_KIND_LABEL } from './entityInfluences'

const WEIGHTS: InfluenceWeight[] = ['low', 'medium', 'high']

type EntityOption = { id: string; label: string }

function WeightPills({
  value,
  onChange,
  disabled,
}: {
  value: InfluenceWeight
  onChange: (w: InfluenceWeight) => void
  disabled?: boolean
}) {
  return (
    <div
      className="flex rounded-md border border-[color:var(--color-border)] bg-surface-sunken p-0.5 gap-0.5 shrink-0"
      role="group"
      aria-label="Shaping weight"
    >
      {WEIGHTS.map((w) => (
        <button
          key={w}
          type="button"
          disabled={disabled}
          onClick={() => onChange(w)}
          className={`px-2 py-0.5 rounded text-[10px] font-medium capitalize transition-colors ${
            value === w
              ? 'bg-accent text-warm-white'
              : 'text-warm-white/55 hover:text-warm-white hover:bg-surface-raised'
          } disabled:opacity-40`}
        >
          {w}
        </button>
      ))}
    </div>
  )
}

export function InfluencesLinksSection({
  sourceKind,
  sourceId,
  coreProfiles,
  perspectiveAgents,
  emphasisNestedProfiles,
  onLinksChanged,
  /** When set, new core-profile links may only target this id (Brand core); existing legacy targets stay visible. */
  canonicalCoreProfileId,
}: {
  sourceKind: InfluenceSourceKind
  sourceId: string
  coreProfiles: EntityOption[]
  perspectiveAgents: EntityOption[]
  /** When true (e.g. core profile editor), group and highlight nested core-profile links. */
  emphasisNestedProfiles?: boolean
  /** Fired after any add, remove, weight change, or target/kind change (localStorage persisted). */
  onLinksChanged?: () => void
  canonicalCoreProfileId?: string | null
}) {
  const [links, setLinks] = useState<InfluenceLink[]>([])
  const [addKind, setAddKind] = useState<InfluenceTargetKind>('core_profile')
  const [addTargetId, setAddTargetId] = useState('')
  const [addWeight, setAddWeight] = useState<InfluenceWeight>('medium')
  const onLinksChangedRef = useRef(onLinksChanged)
  onLinksChangedRef.current = onLinksChanged

  useEffect(() => {
    setLinks(getInfluencesForSource(sourceKind, sourceId))
  }, [sourceKind, sourceId])

  const persist = useCallback(
    (next: InfluenceLink[]) => {
      setLinks(next)
      setInfluencesForSource(sourceKind, sourceId, next)
      onLinksChangedRef.current?.()
    },
    [sourceKind, sourceId],
  )

  const optionsForKind = useCallback(
    (kind: InfluenceTargetKind, coreProfileEditTargetId?: string | null) => {
      switch (kind) {
        case 'core_profile': {
          let list = coreProfiles.filter((o) => !(sourceKind === 'core_profile' && o.id === sourceId))
          const cid = (canonicalCoreProfileId || '').trim()
          if (cid) {
            const allow = new Set<string>([cid])
            const edit = (coreProfileEditTargetId || '').trim()
            if (edit) allow.add(edit)
            list = list.filter((o) => allow.has(o.id))
          }
          return list
        }
        case 'perspective':
          return perspectiveAgents.filter((o) => !(sourceKind === 'perspective' && o.id === sourceId))
        default:
          return []
      }
    },
    [canonicalCoreProfileId, coreProfiles, perspectiveAgents, sourceKind, sourceId],
  )

  const addOptions = useMemo(() => optionsForKind(addKind), [addKind, optionsForKind])

  const profileLinkIndices = useMemo(
    () => links.map((l, i) => (l.targetKind === 'core_profile' ? i : -1)).filter((i) => i >= 0),
    [links],
  )
  const perspectiveLinkIndices = useMemo(
    () => links.map((l, i) => (l.targetKind === 'perspective' ? i : -1)).filter((i) => i >= 0),
    [links],
  )

  const addLink = () => {
    const tid = addTargetId.trim()
    if (!tid) return
    const dup = links.some((l) => l.targetKind === addKind && l.targetId === tid)
    if (dup) return
    persist([...links, { targetKind: addKind, targetId: tid, weight: addWeight }])
    setAddTargetId('')
  }

  const removeAt = (idx: number) => {
    persist(links.filter((_, i) => i !== idx))
  }

  const setWeightAt = (idx: number, weight: InfluenceWeight) => {
    const next = links.map((l, i) => (i === idx ? { ...l, weight } : l))
    persist(next)
  }

  const setTargetAt = (idx: number, kind: InfluenceTargetKind, targetId: string) => {
    if (!targetId) return
    const dup = links.some((l, i) => i !== idx && l.targetKind === kind && l.targetId === targetId)
    if (dup) return
    const next = links.map((l, i) => (i === idx ? { ...l, targetKind: kind, targetId } : l))
    persist(next)
  }

  const labelForTarget = (kind: InfluenceTargetKind, id: string) => {
    const pool = kind === 'core_profile' ? coreProfiles : perspectiveAgents
    return pool.find((p) => p.id === id)?.label ?? id
  }

  const renderLinkRow = (i: number) => {
    const l = links[i]
    if (!l) return null
    const rowOpts = optionsForKind(
      l.targetKind,
      l.targetKind === 'core_profile' ? l.targetId : undefined,
    )
    const idInOpts = rowOpts.some((o) => o.id === l.targetId)
    const nestedStyle =
      emphasisNestedProfiles && l.targetKind === 'core_profile'
        ? 'border-l-2 border-accent/50 pl-2.5 ml-0.5 bg-surface-sunken/80'
        : ''
    return (
      <li
        key={`${i}-${l.targetKind}-${l.targetId}`}
        className={`flex flex-col gap-2 text-xs text-warm-white/80 bg-surface-raised/50 rounded px-2 py-2 border border-[color:var(--color-border)] sm:flex-row sm:flex-wrap sm:items-center ${nestedStyle}`}
      >
        <div className="flex flex-wrap items-center gap-2 min-w-0 flex-1">
          <select
            value={l.targetKind}
            onChange={(e) => {
              const nk = e.target.value as InfluenceTargetKind
              const opts = optionsForKind(nk, nk === 'core_profile' ? l.targetId : undefined)
              const keep = opts.some((o) => o.id === l.targetId)
              const nextId = keep ? l.targetId : opts[0]?.id
              if (nextId) setTargetAt(i, nk, nextId)
            }}
            className="max-w-[9rem] px-1.5 py-1 rounded bg-surface-sunken border border-[color:var(--color-border)] text-warm-white text-[11px] focus:outline-none focus:ring-2 focus:ring-accent/45 focus:border-accent/50"
            aria-label="Shaped by target type"
          >
            <option value="core_profile">{INFLUENCE_TARGET_KIND_LABEL.core_profile}</option>
            <option value="perspective">{INFLUENCE_TARGET_KIND_LABEL.perspective}</option>
          </select>
          <select
            value={l.targetId}
            onChange={(e) => setTargetAt(i, l.targetKind, e.target.value)}
            className="min-w-0 flex-1 max-w-[16rem] px-1.5 py-1 rounded bg-surface-sunken border border-[color:var(--color-border)] text-warm-white text-[11px] focus:outline-none focus:ring-2 focus:ring-accent/45 focus:border-accent/50"
            aria-label="Shaped by entity"
          >
            {!idInOpts && l.targetId ? (
              <option value={l.targetId}>{labelForTarget(l.targetKind, l.targetId)}</option>
            ) : null}
            {rowOpts.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2 justify-between sm:justify-end">
          <WeightPills value={l.weight} onChange={(w) => setWeightAt(i, w)} />
          <button
            type="button"
            onClick={() => removeAt(i)}
            className="text-red-400/90 hover:text-red-300 text-[11px] sm:ml-2"
          >
            Remove
          </button>
        </div>
      </li>
    )
  }

  return (
    <div className="rounded-lg border border-[color:var(--color-border)] bg-surface-sunken/50 p-3 space-y-3">
      <div>
        <h4 className="text-xs font-medium text-warm-white/60 uppercase tracking-wide">Shaped by</h4>
        <p className="text-[11px] text-warm-white/45 mt-1 leading-snug">
          This {sourceKind === 'core_profile' ? 'profile' : sourceKind === 'perspective' ? 'actor' : 'record'} is{' '}
          <span className="text-warm-white/55">partially shaped by</span> your{' '}
          <span className="text-warm-white/60">Brand core</span> (or a legacy row), and by{' '}
          <span className="text-warm-white/60">actor lenses</span> — not by other full identities. Weight is how strongly
          each link applies. Saved in this browser only for now.
        </p>
      </div>
      {links.length === 0 ? (
        <p className="text-[11px] text-warm-white/40">
          No shaping links yet — link your Brand core and/or actor lenses below.
        </p>
      ) : emphasisNestedProfiles ? (
        <div className="space-y-3">
          {profileLinkIndices.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-accent/90 uppercase tracking-wide mb-1.5">
                Brand core / legacy rows
              </p>
              <ul className="space-y-2">{profileLinkIndices.map((i) => renderLinkRow(i))}</ul>
            </div>
          )}
          {perspectiveLinkIndices.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-warm-white/50 uppercase tracking-wide mb-1.5">
                Actor lenses
              </p>
              <ul className="space-y-2">{perspectiveLinkIndices.map((i) => renderLinkRow(i))}</ul>
            </div>
          )}
        </div>
      ) : (
        <ul className="space-y-2">{links.map((_, i) => renderLinkRow(i))}</ul>
      )}
      <div className="flex flex-wrap items-end gap-2 pt-1 border-t border-[color:var(--color-border)]">
        <div className="space-y-0.5">
          <label className="block text-[10px] text-warm-white/45">Target type</label>
          <select
            value={addKind}
            onChange={(e) => {
              setAddKind(e.target.value as InfluenceTargetKind)
              setAddTargetId('')
            }}
            className="px-2 py-1 rounded bg-surface-sunken border border-[color:var(--color-border)] text-warm-white text-xs focus:outline-none focus:ring-2 focus:ring-accent/45 focus:border-accent/50"
          >
            <option value="core_profile">{INFLUENCE_TARGET_KIND_LABEL.core_profile}</option>
            <option value="perspective">{INFLUENCE_TARGET_KIND_LABEL.perspective}</option>
          </select>
        </div>
        <div className="space-y-0.5 flex-1 min-w-[8rem]">
          <label className="block text-[10px] text-warm-white/45">Brand core, legacy row, or actor</label>
          <select
            value={addTargetId}
            onChange={(e) => setAddTargetId(e.target.value)}
            className="w-full px-2 py-1 rounded bg-surface-sunken border border-[color:var(--color-border)] text-warm-white text-xs focus:outline-none focus:ring-2 focus:ring-accent/45 focus:border-accent/50"
          >
            <option value="">Select…</option>
            {addOptions.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-0.5">
          <label className="block text-[10px] text-warm-white/45">Weight</label>
          <WeightPills value={addWeight} onChange={setAddWeight} />
        </div>
        <button
          type="button"
          onClick={addLink}
          disabled={!addTargetId}
          className="px-2 py-1 rounded bg-accent hover:opacity-90 disabled:opacity-50 text-warm-white text-xs"
        >
          Add link
        </button>
      </div>
    </div>
  )
}
