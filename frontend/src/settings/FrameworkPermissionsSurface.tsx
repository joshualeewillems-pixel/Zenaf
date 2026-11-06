import { useCallback, useEffect, useState } from 'react'
import {
  fetchFrameworkPermissions,
  setFrameworkPause,
  setFrameworkStance,
  stanceLabel,
  type FrameworkCapability,
  type FrameworkStance,
  type FrameworkState,
} from './api'
import {
  buildGroups,
  pluralize,
  retainedChoiceText,
  retainedItemNoun,
  reviewDestination,
  rowsForGroup,
  shouldOfferRetainedChoice,
} from './frameworkSurfaceLogic'
import { PauseBanner } from './PauseBanner'

/**
 * The grouped framework surface (Slice 2; Rev2 §2.2–§2.3): one group
 * per registered subsystem, three stances per row (two where the
 * registry supports only Just do it / Don't do it), coverage + a
 * same-size "does NOT allow" line, paused/quieted display, exception
 * membership, and the retained-information choice (R.1–R.4).
 *
 * ONE record, two displays (C3): the strand group and the general
 * noting group render rows of the same R1 capability object, so a
 * write through either control updates both — there is no second
 * record to disagree with. This component is shared by Settings and
 * the onboarding gate: same record, second display (§1.2).
 *
 * Symmetrical mechanics (Rev2 §5): every stance is one action on the
 * same control, no extra confirmation on revoke, no guilt or
 * celebration copy. Stance changes take effect immediately (R.1);
 * the retained-information choice is a contextual, dismissible line,
 * never a modal (R.2–R.4).
 *
 * Slice 2 deviation (D1, reported in the PR): the choice line offers
 * Keep (dismiss) always, and Review only for R6 (Today, the one real
 * per-item surface in Slice 2). Delete is offered nowhere in Slice 2:
 * no capability has a lawful bulk-erase for its retained items yet
 * (invitations cannot be dismissed by Capability C law; proposals
 * have decline, not delete; notes/threads have no erase path until
 * the Review queue). The full three-action choice lands with Slice 3.
 */
export function FrameworkPermissionsSurface({
  onOpenToday,
}: {
  /** Navigate to the Today deck (R6 Review). Absent in the onboarding gate. */
  onOpenToday?: () => void
}) {
  const [state, setState] = useState<FrameworkState | null>(null)
  const [loading, setLoading] = useState(true)
  const [savingKey, setSavingKey] = useState<string | null>(null)
  const [savingPause, setSavingPause] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [choiceFor, setChoiceFor] = useState<string | null>(null)
  const [lastChange, setLastChange] = useState<{ capability: string; stance: string } | null>(null)

  const load = useCallback(async () => {
    try {
      setState(await fetchFrameworkPermissions())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load permissions')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const changeStance = async (
    capability: FrameworkCapability,
    rowKey: string,
    stance: FrameworkStance,
  ) => {
    const key = `${capability.id}:${rowKey}`
    setError(null)
    setSavingKey(key)
    try {
      const resp = await setFrameworkStance(capability.id, rowKey, stance)
      setState(resp.state)
      setLastChange({ capability: capability.id, stance })
      if (resp.retained_choice_offered) {
        setChoiceFor(capability.id)
      } else if (stance !== 'dont_do_it') {
        setChoiceFor((current) => (current === capability.id ? null : current))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save stance')
    } finally {
      setSavingKey(null)
    }
  }

  const togglePause = async (paused: boolean) => {
    setError(null)
    setSavingPause(true)
    try {
      const resp = await setFrameworkPause(paused)
      setState(resp.state)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save pause')
    } finally {
      setSavingPause(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-slate-400">Loading permissions…</p>
  }

  if (!state) {
    return (
      <div className="rounded-xl border border-slate-600/80 bg-slate-800/40 p-5 space-y-3">
        <p className="text-sm text-red-300">{error ?? 'Permissions could not be loaded.'}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded-lg bg-slate-600 hover:bg-slate-500 px-3 py-1.5 text-sm"
        >
          Retry
        </button>
      </div>
    )
  }

  const groups = buildGroups(state)

  return (
    <div className="space-y-3">
      <PauseBanner
        state={state}
        onResume={() => void togglePause(false)}
      />
      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="mt-1 rounded border-slate-600"
            checked={state.paused}
            disabled={savingPause}
            onChange={(e) => void togglePause(e.target.checked)}
          />
          <span>
            <span className="text-sm text-slate-200">Pause all standing behavior</span>
            <span className="block text-sm text-slate-400">
              Stops anything new from starting. Your stances stay exactly as they are, and
              un-pausing restores them. Pausing never deletes, trains, publishes, or shares
              anything.
            </span>
          </span>
        </label>
      </div>

      {groups.map((group) => (
        <div
          key={group.key}
          className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-3"
        >
          <p className="text-xs uppercase tracking-wide text-slate-500">{group.title}</p>
          {group.note ? <p className="text-sm text-slate-400">{group.note}</p> : null}
          {group.capabilities.map((capability) => (
            <CapabilityBlock
              key={`${group.key}:${capability.id}`}
              capability={capability}
              rows={rowsForGroup(group, capability)}
              paused={state.paused}
              savingKey={savingKey}
              choiceOpen={choiceFor === capability.id}
              offerChoice={shouldOfferRetainedChoice(capability, lastChange)}
              onChoiceOpen={() => setChoiceFor(capability.id)}
              onChoiceKeep={() => setChoiceFor(null)}
              onReviewToday={onOpenToday}
              onStance={(rowKey, stance) => void changeStance(capability, rowKey, stance)}
            />
          ))}
        </div>
      ))}
      {error ? <p className="text-xs text-red-300">{error}</p> : null}
    </div>
  )
}

function CapabilityBlock({
  capability,
  rows,
  paused,
  savingKey,
  choiceOpen,
  offerChoice,
  onChoiceOpen,
  onChoiceKeep,
  onReviewToday,
  onStance,
}: {
  capability: FrameworkCapability
  rows: FrameworkCapability['rows']
  paused: boolean
  savingKey: string | null
  choiceOpen: boolean
  offerChoice: boolean
  onChoiceOpen: () => void
  onChoiceKeep: () => void
  onReviewToday?: () => void
  onStance: (rowKey: string, stance: FrameworkStance) => void
}) {
  const showChoice = choiceOpen || offerChoice
  const choiceText = retainedChoiceText(capability)
  const canReview = reviewDestination(capability.id) === 'today' && onReviewToday !== undefined
  return (
    <div className="space-y-2">
      <p className="text-sm text-slate-200">{capability.covers}</p>
      <p className="text-sm text-slate-400">{capability.does_not_allow}</p>
      {capability.exception_classes.length > 0 ? (
        <p className="text-sm text-slate-400">
          Always asks per transaction for: {capability.exception_classes.join(', ')} — here is why:
          these classes are never covered by a standing authorization.
        </p>
      ) : null}
      {capability.quieted ? (
        <p className="text-sm text-amber-300">
          Quieted — asking is paused after repeated deferrals. Your stance underneath is unchanged.
        </p>
      ) : null}
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">
          No rows yet — per-commitment reminders arrive with Slice 6 wiring.
        </p>
      ) : (
        rows.map((row) => (
          <div key={row.key} className="rounded-lg border border-slate-700/70 bg-slate-900/50 p-3 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-slate-200">{row.label}</span>
              {row.stance_source === 'default' ? (
                <span className="text-xs text-slate-500">(default)</span>
              ) : null}
              {paused ? (
                <span className="text-xs rounded bg-amber-900/60 text-amber-200 px-2 py-0.5">
                  Paused
                </span>
              ) : null}
            </div>
            <div className="flex gap-2 flex-wrap" role="group" aria-label={`${row.label} stance`}>
              {capability.supported_stances.map((stance) => {
                const key = `${capability.id}:${row.key}`
                const active = row.stance === stance
                return (
                  <button
                    key={stance}
                    type="button"
                    disabled={savingKey === key}
                    aria-pressed={active}
                    onClick={() => onStance(row.key, stance)}
                    className={
                      active
                        ? 'rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white'
                        : 'rounded-lg bg-slate-700 hover:bg-slate-600 px-3 py-1.5 text-sm text-slate-200'
                    }
                  >
                    {stanceLabel(stance)}
                  </button>
                )
              })}
            </div>
          </div>
        ))
      )}
      <p className="text-sm text-slate-400">
        {capability.retained_count > 0
          ? `${capability.retained_count} ${pluralize(
              capability.retained_count,
              retainedItemNoun(capability.id).singular,
              retainedItemNoun(capability.id).plural,
            )} retained.`
          : 'No retained items.'}{' '}
        {capability.retained_count > 0 ? (
          <button
            type="button"
            onClick={onChoiceOpen}
            className="underline text-slate-300 hover:text-slate-100"
          >
            Choose what happens to them
          </button>
        ) : null}
      </p>
      {showChoice && choiceText ? (
        <div className="rounded-lg border border-slate-600 bg-slate-800/60 p-3 space-y-2">
          <p className="text-sm text-slate-200">{choiceText}</p>
          <div className="flex gap-2 flex-wrap">
            <button
              type="button"
              onClick={onChoiceKeep}
              className="rounded-lg bg-slate-700 hover:bg-slate-600 px-3 py-1.5 text-sm text-slate-200"
            >
              Keep
            </button>
            {canReview ? (
              <button
                type="button"
                onClick={() => {
                  onReviewToday?.()
                  onChoiceKeep()
                }}
                className="rounded-lg bg-slate-700 hover:bg-slate-600 px-3 py-1.5 text-sm text-slate-200"
              >
                Review in Today
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
