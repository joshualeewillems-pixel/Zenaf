import { useCallback, useEffect, useState } from 'react'
import {
  fetchUserPermissionsSettings,
  saveUserPermissionsSettings,
  USER_PERMISSION_DEFAULTS,
  type UserPermissionFlags,
} from '../api'

const CONSENT_VERSION = 'permissions-v1'

type PermissionRow = {
  key: keyof UserPermissionFlags
  label: string
  hint: string
}

const OPTIONAL_PERMISSION_ROWS: PermissionRow[] = [
  {
    key: 'behavioral_tracking',
    label: 'Behavioral tracking',
    hint: 'Allow Zenaf to store interaction events used to understand usage patterns.',
  },
  {
    key: 'personalization',
    label: 'Personalization / adaptive responses',
    hint: 'Allow Zenaf to adapt guidance and response style from prior behavior signals.',
  },
  {
    key: 'interaction_pattern_storage',
    label: 'Store interaction patterns',
    hint: 'Allow storing derived interaction pattern summaries over time.',
  },
  {
    key: 'profile_learning',
    label: 'Profile learning from usage',
    hint: 'Allow updates to developmental/profile learning systems from your actions.',
  },
  {
    key: 'analytics_product_improvement',
    label: 'Optional analytics / product improvement',
    hint: 'Allow anonymized learning outcomes to improve product quality.',
  },
  {
    key: 'aspiration_store_explicit',
    label: 'Store explicit aspirations',
    hint: 'Allow saving your authored aspiration profile (Foundation).',
  },
  {
    key: 'aspiration_infer_suggestions',
    label: 'Infer aspiration suggestions',
    hint: 'Allow bounded, non-canonical aspiration theme suggestions you can accept or dismiss.',
  },
  {
    key: 'aspiration_use_in_guidance',
    label: 'Use aspirations in guidance',
    hint: 'Allow compact aspiration blocks in council / core-profile guidance when you opt in per profile.',
  },
]

export function PermissionsSection() {
  const [consentGiven, setConsentGiven] = useState(false)
  const [consentAt, setConsentAt] = useState<string | null>(null)
  const [permissions, setPermissions] = useState<UserPermissionFlags>(USER_PERMISSION_DEFAULTS)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(async () => {
    const data = await fetchUserPermissionsSettings()
    setConsentGiven(data.consent_given)
    setConsentAt(data.consent_at)
    setPermissions(data.permissions)
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        await load()
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load permissions')
      } finally {
        setLoading(false)
      }
    })()
  }, [load])

  const commit = async (nextPermissions: UserPermissionFlags) => {
    setError(null)
    setMessage(null)
    setSaving(true)
    try {
      const data = await saveUserPermissionsSettings({
        consent_acknowledged: consentGiven,
        consent_version: consentGiven ? CONSENT_VERSION : '',
        permissions: nextPermissions,
      })
      setPermissions(data.permissions)
      setConsentGiven(data.consent_given)
      setConsentAt(data.consent_at)
      setMessage('Permissions updated.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save permissions')
    } finally {
      setSaving(false)
    }
  }

  const commitConsent = async (nextConsent: boolean) => {
    setError(null)
    setMessage(null)
    setSaving(true)
    try {
      const data = await saveUserPermissionsSettings({
        consent_acknowledged: nextConsent,
        consent_version: nextConsent ? CONSENT_VERSION : '',
        permissions: nextConsent ? permissions : USER_PERMISSION_DEFAULTS,
      })
      setPermissions(data.permissions)
      setConsentGiven(data.consent_given)
      setConsentAt(data.consent_at)
      setMessage('Consent status updated.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save permissions')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="rounded-xl border border-slate-600/80 bg-slate-800/40 p-5 space-y-3">
      <div>
        <h2 className="text-lg font-medium text-slate-100">Data permissions</h2>
        <p className="text-sm text-slate-400 mt-1">
          Control what learning, tracking, and personalization systems can use from your activity.
        </p>
        <div className="mt-3 rounded-lg border border-slate-700 bg-slate-900/50 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-500">Data used by optional permissions</p>
          <ul className="mt-1 text-xs text-slate-400 space-y-1 list-disc pl-4">
            <li>Interaction events (response ratings, prompt actions, workflow actions)</li>
            <li>Feature context metadata (surface, seat/context kind, timestamps)</li>
            <li>Derived interaction-pattern summaries used for adaptive behavior</li>
            <li>Decision and profile snapshots used for developmental/profile learning</li>
          </ul>
        </div>
      </div>
      {loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {!loading ? (
        <>
          <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-500">Required</p>
            <p className="text-sm text-slate-200 mt-1">
              Basic account/session operation is always enabled while you are signed in.
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Consent status: {consentGiven ? `Granted${consentAt ? ` (${consentAt})` : ''}` : 'Not granted'}
            </p>
            <label className="mt-2 inline-flex items-center gap-2 text-sm text-slate-200 cursor-pointer">
              <input
                type="checkbox"
                className="rounded border-slate-600"
                checked={consentGiven}
                disabled={saving}
                onChange={(e) => {
                  setConsentGiven(e.target.checked)
                  void commitConsent(e.target.checked)
                }}
              />
              Enable consent for optional behavior permissions
            </label>
          </div>
          <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 space-y-2">
            <p className="text-xs uppercase tracking-wide text-slate-500">Optional (default off)</p>
            {OPTIONAL_PERMISSION_ROWS.map((row) => (
              <label key={row.key} className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="mt-1 rounded border-slate-600"
                  checked={permissions[row.key]}
                  disabled={saving || !consentGiven}
                  onChange={(e) => {
                    const next = { ...permissions, [row.key]: e.target.checked }
                    setPermissions(next)
                    void commit(next)
                  }}
                />
                <span>
                  <span className="text-sm text-slate-200">{row.label}</span>
                  <span className="block text-xs text-slate-500">{row.hint}</span>
                </span>
              </label>
            ))}
          </div>
          {message ? <p className="text-xs text-emerald-400">{message}</p> : null}
          {error ? <p className="text-xs text-red-300">{error}</p> : null}
        </>
      ) : null}
    </section>
  )
}
