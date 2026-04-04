import { useCallback, useEffect, useState } from 'react'
import {
  fetchNotificationSettings,
  NOTIFICATION_PREFS_DEFAULT,
  saveNotificationSettings,
  type NotificationPrefs,
} from '../api'

const IN_APP_FIELDS: { key: keyof NotificationPrefs['in_app']; label: string }[] = [
  { key: 'task_activity', label: 'Task activity' },
  { key: 'matching', label: 'Matching' },
  { key: 'share_revoke', label: 'Share / revoke' },
  { key: 'sync_system', label: 'Sync / system' },
]

const EMAIL_CHILD_FIELDS: { key: keyof Pick<NotificationPrefs['email'], 'task_activity' | 'matching' | 'share_revoke' | 'sync_system'>; label: string }[] = [
  { key: 'task_activity', label: 'Task activity' },
  { key: 'matching', label: 'Matching' },
  { key: 'share_revoke', label: 'Share / revoke' },
  { key: 'sync_system', label: 'Sync / system' },
]

export function NotificationsSection() {
  const [prefs, setPrefs] = useState<NotificationPrefs>(NOTIFICATION_PREFS_DEFAULT)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    const d = await fetchNotificationSettings()
    setPrefs(d.prefs)
    setUpdatedAt(d.updated_at)
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        await load()
      } catch (e) {
        setLoadErr(e instanceof Error ? e.message : 'Load failed')
      }
    })()
  }, [load])

  const commit = async (next: NotificationPrefs) => {
    setErr(null)
    setMsg(null)
    setSaving(true)
    try {
      await saveNotificationSettings(next)
      setPrefs(next)
      await load()
      setMsg('Preferences saved.')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const setInApp = (key: keyof NotificationPrefs['in_app'], value: boolean) => {
    void commit({
      ...prefs,
      in_app: { ...prefs.in_app, [key]: value },
    })
  }

  const setEmailEnabled = (value: boolean) => {
    void commit({
      ...prefs,
      email: { ...prefs.email, enabled: value },
    })
  }

  const setEmailChild = (
    key: keyof Pick<NotificationPrefs['email'], 'task_activity' | 'matching' | 'share_revoke' | 'sync_system'>,
    value: boolean,
  ) => {
    void commit({
      ...prefs,
      email: { ...prefs.email, [key]: value },
    })
  }

  const emailChildrenDisabled = saving || !prefs.email.enabled

  return (
    <section className="border border-slate-700 rounded-lg p-4 space-y-3">
      <h2 className="text-lg font-semibold text-slate-100">Notifications</h2>
      <p className="text-xs text-amber-200/90 border border-amber-800/50 bg-amber-950/30 rounded px-2 py-1.5">
        Preferences are stored on the server, but delivery (in-app or email) may not yet be active.
      </p>
      {loadErr && <div className="text-sm text-red-300">{loadErr}</div>}
      {!loadErr && (
        <div className="text-sm space-y-5">
          <fieldset className="space-y-2">
            <legend className="text-slate-400 text-xs uppercase tracking-wide mb-2 block">In-app</legend>
            {IN_APP_FIELDS.map(({ key, label }) => (
              <label key={key} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={prefs.in_app[key]}
                  disabled={saving}
                  onChange={(e) => setInApp(key, e.target.checked)}
                  className="rounded border-slate-600"
                />
                <span className="text-slate-200">{label}</span>
              </label>
            ))}
          </fieldset>

          <fieldset className="space-y-2">
            <legend className="text-slate-400 text-xs uppercase tracking-wide mb-2 block">Email</legend>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={prefs.email.enabled}
                disabled={saving}
                onChange={(e) => setEmailEnabled(e.target.checked)}
                className="rounded border-slate-600"
              />
              <span className="text-slate-200 font-medium">Email notifications enabled</span>
            </label>
            <div className={`pl-1 space-y-2 border-l border-slate-600 ml-1 ${!prefs.email.enabled ? 'opacity-60' : ''}`}>
              <p className="text-xs text-slate-500 pl-2">Per-topic (saved even when email is off)</p>
              {EMAIL_CHILD_FIELDS.map(({ key, label }) => (
                <label key={key} className="flex items-center gap-2 cursor-pointer pl-2">
                  <input
                    type="checkbox"
                    checked={prefs.email[key]}
                    disabled={emailChildrenDisabled}
                    onChange={(e) => setEmailChild(key, e.target.checked)}
                    className="rounded border-slate-600"
                  />
                  <span className="text-slate-200">{label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          {updatedAt && <div className="text-xs text-slate-500">Last updated: {updatedAt}</div>}
          {msg && <div className="text-xs text-emerald-400">{msg}</div>}
          {err && <div className="text-xs text-red-300">{err}</div>}
        </div>
      )}
    </section>
  )
}
