import { useCallback, useEffect, useState } from 'react'
import {
  fetchPermissionHome,
  setPermissionHomeControl,
  setPermissionHomeGroup,
  stanceLabel,
  type FrameworkStance,
  type PermissionHomeControl,
  type PermissionHomeGroup,
  type PermissionHomeIntent,
  type PermissionHomeState,
  type PermissionHomeWriteReport,
} from '../api'
import {
  GROUP_COPY,
  INTENT_COPY,
  LEARN_EXPLANATION,
  alwaysAsksText,
  controlLabel,
  flagCopy,
  intentOrder,
  repairFor,
  stateLabel,
  syncText,
} from '../permissionHomeLogic'

/**
 * The permission home (Permission Simplification P-2): one surface
 * over the existing engines — five intents plus the Outside Zenaf
 * disclosure grouping. The intents are views and writers over the
 * stance store and the account flags; enforcement never reads this
 * layer, and every write is answered with the read-back state, so
 * what is displayed is what the backend actually holds.
 *
 * Remember carries its two layers in the intent row itself
 * (refinement 2): Retention, and Ongoing story as a separate
 * authorization the simple choice never implies. Granular controls
 * — every row the legacy surfaces expose, plus the
 * fellowship_derivation row this program adds — live one expansion
 * down, unchanged in meaning.
 *
 * The fellowship row's wording was ruled by the founder
 * 2026-11-22 ("Cross-conversation noticing") and is carried in
 * permissionHomeLogic's copy table like every other flag's.
 *
 * Learn is a distinction, not a toggle (design §2): its control is
 * the per-claim review surface, so this block explains and does
 * not offer a switch.
 */
export function PermissionHomeSection() {
  const [state, setState] = useState<PermissionHomeState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingKey, setSavingKey] = useState<string | null>(null)
  const [lastWrite, setLastWrite] = useState<PermissionHomeWriteReport | null>(null)
  const [expandedIntent, setExpandedIntent] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setState(await fetchPermissionHome())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load permission home')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const writeGroup = async (groupId: string, target: 'on' | 'off' | 'ask_me') => {
    setError(null)
    setSavingKey(`group:${groupId}`)
    try {
      const resp = await setPermissionHomeGroup(groupId, target)
      setState(resp.state)
      setLastWrite(resp.write)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save permission')
    } finally {
      setSavingKey(null)
    }
  }

  const writeControl = async (control: PermissionHomeControl, value: boolean | FrameworkStance) => {
    setError(null)
    setSavingKey(`control:${control.id}`)
    try {
      const resp = await setPermissionHomeControl(control.id, value)
      setState(resp.state)
      setLastWrite(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save permission')
    } finally {
      setSavingKey(null)
    }
  }

  if (loading) {
    return (
      <section className="rounded-xl border border-slate-600/80 bg-slate-800/40 p-5">
        <p className="text-sm text-slate-400">Loading…</p>
      </section>
    )
  }

  if (!state) {
    return (
      <section className="rounded-xl border border-slate-600/80 bg-slate-800/40 p-5 space-y-3">
        <p className="text-sm text-red-300">{error ?? 'The permission home could not be loaded.'}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded-lg bg-slate-600 hover:bg-slate-500 px-3 py-1.5 text-sm"
        >
          Retry
        </button>
      </section>
    )
  }

  if (!state.enabled) {
    // Surface state 3 (design §6): operationally off, said plainly —
    // never disguised as a permission the visitor can change.
    return (
      <section className="rounded-xl border border-slate-600/80 bg-slate-800/40 p-5 space-y-2">
        <h2 className="text-lg font-medium text-slate-100">Permission home</h2>
        <p className="text-sm text-slate-400">
          The permission home is switched off operationally on this deployment. Your
          permissions themselves are unchanged and remain available in Data permissions
          below.
        </p>
      </section>
    )
  }

  const byId = new Map(state.intents.map((i) => [i.id, i]))

  return (
    <section className="rounded-xl border border-slate-600/80 bg-slate-800/40 p-5 space-y-4">
      <div>
        <h2 className="text-lg font-medium text-slate-100">Permission home</h2>
        <p className="text-sm text-slate-400 mt-1">
          One place for what Zenaf may do — organized by intent, with every detailed
          control one expansion down. Changing an intent sets the controls beneath it;
          what is shown afterwards is what the system actually holds.
        </p>
        {/* Correction 2 presentation: the acknowledgment is labeled
            as acknowledging the disclosure — it is not itself a
            permission, and setting capabilities never re-stamps it. */}
        <p className="text-xs text-slate-500 mt-2">
          Disclosure acknowledgment:{' '}
          {state.consent.given
            ? `recorded${state.consent.version ? ` (${state.consent.version})` : ''}. Recording it acknowledges the disclosure — by itself it authorizes nothing.`
            : 'not recorded. Capability choices below are still saved; several take effect only once the acknowledgment is recorded.'}
        </p>
      </div>

      {intentOrder(state).map((intentId) => {
        const intent = byId.get(intentId)
        if (!intent) return null
        return (
          <IntentBlock
            key={intentId}
            intent={intent}
            savingKey={savingKey}
            lastWrite={lastWrite}
            expanded={expandedIntent === intentId}
            onToggleExpanded={() =>
              setExpandedIntent((cur) => (cur === intentId ? null : intentId))
            }
            onWriteGroup={(groupId, target) => void writeGroup(groupId, target)}
            onWriteControl={(control, value) => void writeControl(control, value)}
          />
        )
      })}

      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
        <p className="text-xs uppercase tracking-wide text-slate-500">Learn</p>
        <p className="text-sm text-slate-300">{LEARN_EXPLANATION}</p>
      </div>

      <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
        <p className="text-xs uppercase tracking-wide text-slate-500">Outside Zenaf</p>
        <p className="text-sm text-slate-400">
          Standing permissions for anything that leaves your account live here. None
          exist yet — the external search consent will appear in this grouping when it
          ships, and it will be off until you turn it on.
        </p>
        <ul className="text-sm text-slate-300 space-y-1 list-disc pl-4">
          {state.outside_zenaf.always_asks.map((cls) => (
            <li key={cls}>{alwaysAsksText(cls)}</li>
          ))}
        </ul>
      </div>

      {error ? <p className="text-xs text-red-300">{error}</p> : null}
      <p className="text-xs text-slate-500">
        The previous Data permissions surface remains available below while this home
        is verified — no control exists in only one of the two.
      </p>
    </section>
  )
}

function IntentBlock({
  intent,
  savingKey,
  lastWrite,
  expanded,
  onToggleExpanded,
  onWriteGroup,
  onWriteControl,
}: {
  intent: PermissionHomeIntent
  savingKey: string | null
  lastWrite: PermissionHomeWriteReport | null
  expanded: boolean
  onToggleExpanded: () => void
  onWriteGroup: (groupId: string, target: 'on' | 'off' | 'ask_me') => void
  onWriteControl: (control: PermissionHomeControl, value: boolean | FrameworkStance) => void
}) {
  const copy = INTENT_COPY[intent.id]
  const allControls = [
    ...intent.groups.flatMap((g) => g.controls),
    ...intent.granular,
  ]
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-3">
      <div>
        <p className="text-sm font-medium text-slate-100">{copy?.title ?? intent.id}</p>
        {copy ? <p className="text-sm text-slate-400 mt-0.5">{copy.summary}</p> : null}
      </div>
      {intent.groups.map((group) => (
        <GroupBlock
          key={group.id}
          group={group}
          saving={savingKey === `group:${group.id}`}
          lastWrite={lastWrite}
          onWriteGroup={onWriteGroup}
        />
      ))}
      {allControls.length > 0 ? (
        <div>
          <button
            type="button"
            onClick={onToggleExpanded}
            aria-expanded={expanded}
            className="text-sm text-slate-300 underline hover:text-slate-100"
          >
            {expanded ? 'Hide granular controls' : 'Granular controls'}
          </button>
          {expanded ? (
            <div className="mt-2 space-y-2">
              {allControls.map((control) => (
                <ControlRow
                  key={control.id}
                  control={control}
                  saving={savingKey === `control:${control.id}`}
                  onWriteControl={onWriteControl}
                />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function GroupBlock({
  group,
  saving,
  lastWrite,
  onWriteGroup,
}: {
  group: PermissionHomeGroup
  saving: boolean
  lastWrite: PermissionHomeWriteReport | null
  onWriteGroup: (groupId: string, target: 'on' | 'off' | 'ask_me') => void
}) {
  const copy = GROUP_COPY[group.id]
  const sync = syncText(group, lastWrite)
  const repair = repairFor(group, lastWrite)
  const diagnostics = group.diagnostics
    ? Object.values(group.diagnostics).filter((d) => d.state !== 'available')
    : []
  return (
    <div className="rounded-lg border border-slate-700/70 bg-slate-900/50 p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-slate-200">{copy?.title ?? group.id}</span>
        <span
          className={
            group.state === 'on'
              ? 'text-xs rounded bg-emerald-900/60 text-emerald-200 px-2 py-0.5'
              : group.state === 'custom'
                ? 'text-xs rounded bg-amber-900/60 text-amber-200 px-2 py-0.5'
                : 'text-xs rounded bg-slate-700 text-slate-300 px-2 py-0.5'
          }
        >
          {stateLabel(group.state)}
        </span>
        {!group.has_rows ? (
          <span className="text-xs text-slate-500">No rows yet</span>
        ) : null}
      </div>
      {copy ? <p className="text-sm text-slate-400">{copy.scope}</p> : null}
      <div className="flex gap-2 flex-wrap" role="group" aria-label={`${copy?.title ?? group.id} choice`}>
        {group.writable_states.map((target) => {
          const active = group.state === target
          return (
            <button
              key={target}
              type="button"
              disabled={saving || !group.has_rows}
              aria-pressed={active}
              onClick={() => onWriteGroup(group.id, target)}
              className={
                active
                  ? 'rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium text-white'
                  : 'rounded-lg bg-slate-700 hover:bg-slate-600 px-3 py-1.5 text-sm text-slate-200'
              }
            >
              {stateLabel(target)}
            </button>
          )
        })}
      </div>
      {sync ? (
        <p className="text-sm text-amber-300">
          {sync}{' '}
          {repair ? (
            <button
              type="button"
              disabled={saving}
              onClick={() =>
                onWriteGroup(repair.group, repair.state as 'on' | 'off' | 'ask_me')
              }
              className="underline text-amber-200 hover:text-amber-100"
            >
              Repair
            </button>
          ) : null}
        </p>
      ) : null}
      {diagnostics.map((d, idx) => (
        <p key={idx} className="text-xs text-slate-500">
          {d.detail}
        </p>
      ))}
    </div>
  )
}

function ControlRow({
  control,
  saving,
  onWriteControl,
}: {
  control: PermissionHomeControl
  saving: boolean
  onWriteControl: (control: PermissionHomeControl, value: boolean | FrameworkStance) => void
}) {
  if (control.kind === 'flag') {
    const copy = flagCopy(control)
    return (
      <label className="flex items-start gap-2 cursor-pointer rounded-lg border border-slate-700/70 bg-slate-900/50 p-3">
        <input
          type="checkbox"
          className="mt-1 rounded border-slate-600"
          checked={control.value === true}
          disabled={saving}
          onChange={(e) => onWriteControl(control, e.target.checked)}
        />
        <span>
          <span className="text-sm text-slate-200">
            {control.wording_pending ? control.key : (copy?.label ?? control.key)}
          </span>
          {control.wording_pending ? (
            <span className="block text-xs text-slate-500">
              This control works, but its description is pending a wording decision —
              it is shown by its key until then.
            </span>
          ) : copy ? (
            <span className="block text-xs text-slate-500">{copy.hint}</span>
          ) : null}
        </span>
      </label>
    )
  }
  return (
    <div className="rounded-lg border border-slate-700/70 bg-slate-900/50 p-3 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-slate-200">
          {control.capability ? `${control.capability} — ` : ''}
          {controlLabel(control)}
        </span>
        {control.stance_source === 'default' ? (
          <span className="text-xs text-slate-500">(default)</span>
        ) : null}
      </div>
      {control.covers ? <p className="text-xs text-slate-500">{control.covers}</p> : null}
      <div
        className="flex gap-2 flex-wrap"
        role="group"
        aria-label={`${controlLabel(control)} stance`}
      >
        {control.supported_stances.map((stance) => {
          const active = control.stance === stance
          return (
            <button
              key={stance}
              type="button"
              disabled={saving}
              aria-pressed={active}
              onClick={() => onWriteControl(control, stance)}
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
  )
}
