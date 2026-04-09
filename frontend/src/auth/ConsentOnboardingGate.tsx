import { useMemo, useState } from 'react'
import { USER_PERMISSION_DEFAULTS, type UserPermissionFlags } from '../settings/api'

const CONSENT_VERSION = 'permissions-v1'

const OPTIONAL_TOGGLES: { key: keyof UserPermissionFlags; label: string; hint: string }[] = [
  {
    key: 'behavioral_tracking',
    label: 'Behavioral tracking',
    hint: 'Store behavior events used for usage patterns and adaptive systems.',
  },
  {
    key: 'personalization',
    label: 'Personalization / adaptive responses',
    hint: 'Use your interaction history to tailor guidance and response style.',
  },
  {
    key: 'interaction_pattern_storage',
    label: 'Store interaction patterns',
    hint: 'Keep derived interaction-pattern summaries across sessions.',
  },
  {
    key: 'profile_learning',
    label: 'Profile/core profile learning from usage',
    hint: 'Allow profile-learning systems to update from your actions over time.',
  },
  {
    key: 'analytics_product_improvement',
    label: 'Optional analytics / product improvement',
    hint: 'Allow anonymized learning signals for product quality improvements.',
  },
  {
    key: 'aspiration_store_explicit',
    label: 'Store explicit aspirations',
    hint: 'Save your authored aspiration profile in Foundation.',
  },
  {
    key: 'aspiration_infer_suggestions',
    label: 'Infer aspiration suggestions',
    hint: 'Receive bounded suggestion themes you confirm before they affect your profile.',
  },
  {
    key: 'aspiration_use_in_guidance',
    label: 'Use aspirations in guidance',
    hint: 'Include compact aspiration orientation in guidance when enabled in Foundation.',
  },
]

export function ConsentOnboardingGate({
  submitting = false,
  onSubmit,
}: {
  submitting?: boolean
  onSubmit: (payload: {
    consent_acknowledged: boolean
    consent_version: string
    permissions: UserPermissionFlags
  }) => Promise<void>
}) {
  const [permissions, setPermissions] = useState<UserPermissionFlags>(USER_PERMISSION_DEFAULTS)
  const [ack, setAck] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canContinue = useMemo(() => ack && !submitting, [ack, submitting])

  const submit = async () => {
    if (!ack || submitting) return
    setError(null)
    try {
      await onSubmit({
        consent_acknowledged: true,
        consent_version: CONSENT_VERSION,
        permissions,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save consent')
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-2xl rounded-xl border border-slate-700 bg-slate-800/70 p-6 space-y-4">
        <div>
          <h1 className="text-xl font-semibold">Permissions and consent</h1>
          <p className="text-sm text-slate-300 mt-1">
            Before enabling behavior-based features, choose what Zenaf is allowed to store and use.
          </p>
          <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900/50 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-500">What data this can include</p>
            <ul className="mt-1 text-xs text-slate-400 space-y-1 list-disc pl-4">
              <li>Interaction events (e.g., when you rate responses or dismiss prompts)</li>
              <li>Context metadata (feature area, seat/context kind, timestamp)</li>
              <li>Derived pattern summaries (engagement trends, recurring preferences)</li>
              <li>Decision snapshots used for profile/core-profile learning</li>
            </ul>
          </div>
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4 space-y-2">
          <p className="text-xs uppercase tracking-wide text-slate-500">Required for service operation</p>
          <p className="text-sm text-slate-200">
            Account authentication, session cookies, and basic app operation while signed in.
          </p>
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4 space-y-3">
          <p className="text-xs uppercase tracking-wide text-slate-500">Optional (all default off)</p>
          {OPTIONAL_TOGGLES.map((row) => (
            <label key={row.key} className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                className="mt-1 rounded border-slate-600"
                checked={permissions[row.key]}
                onChange={(e) => setPermissions((p) => ({ ...p, [row.key]: e.target.checked }))}
              />
              <span>
                <span className="text-sm text-slate-200">{row.label}</span>
                <span className="block text-xs text-slate-500">{row.hint}</span>
              </span>
            </label>
          ))}
        </div>

        <label className="flex items-start gap-2 cursor-pointer rounded-lg border border-slate-700 bg-slate-900/50 p-3">
          <input
            type="checkbox"
            className="mt-1 rounded border-slate-600"
            checked={ack}
            onChange={(e) => setAck(e.target.checked)}
          />
          <span className="text-sm text-slate-200">
            I understand these categories and explicitly consent to the selected optional permissions.
          </span>
        </label>

        {error ? <p className="text-sm text-red-300">{error}</p> : null}

        <button
          type="button"
          disabled={!canContinue}
          onClick={() => void submit()}
          className="w-full rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-slate-600 py-2 text-sm font-medium"
        >
          {submitting ? 'Saving…' : 'Continue'}
        </button>
      </div>
    </div>
  )
}
