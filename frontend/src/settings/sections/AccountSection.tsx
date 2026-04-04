import type { CurrentUser } from '../../auth/session'
import { updateDisplayName } from '../../auth/session'
import { useState } from 'react'

type Props = {
  user: CurrentUser
  onLogout: () => void
  onUserUpdated: (u: CurrentUser) => void
}

export function AccountSection({ user, onLogout, onUserUpdated }: Props) {
  const [name, setName] = useState(user.display_name || '')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const saveName = async () => {
    setErr(null)
    setMsg(null)
    setSaving(true)
    try {
      const u = await updateDisplayName(name.trim() || user.display_name)
      onUserUpdated(u)
      setMsg('Display name saved.')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="border border-slate-700 rounded-lg p-4 space-y-3">
      <h2 className="text-lg font-semibold text-slate-100">Account</h2>
      <p className="text-slate-500 text-xs">
        Profile photo: use the circle in the top-left header (upload or remove there).
      </p>
      <div className="text-sm space-y-2">
        <div>
          <div className="text-slate-500">Email</div>
          <div className="text-slate-200">{user.email}</div>
        </div>
        <div>
          <label className="block text-slate-500 mb-1">Display name</label>
          <input
            className="w-full max-w-md bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button
            type="button"
            disabled={saving}
            onClick={saveName}
            className="mt-2 px-3 py-1.5 rounded-lg text-sm bg-slate-600 text-slate-100 hover:bg-slate-500 disabled:opacity-50"
          >
            Save display name
          </button>
        </div>
      </div>
      {msg && <p className="text-emerald-400 text-sm">{msg}</p>}
      {err && <p className="text-red-400 text-sm">{err}</p>}
      <div className="pt-2 border-t border-slate-700">
        <button
          type="button"
          onClick={onLogout}
          className="px-3 py-1.5 rounded-lg text-sm font-medium text-slate-300 border border-slate-600 hover:bg-slate-800"
        >
          Logout
        </button>
      </div>
    </section>
  )
}
