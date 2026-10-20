import type { CurrentUser } from '../../auth/session'
import { createInvite } from '../../auth/session'
import { useState } from 'react'

type Props = {
  user: CurrentUser
}

/**
 * Admin-only: mint a single-use invite link and copy it. Each link works
 * once and expires in 7 days. Rendered only for admin users.
 */
export function InvitesSection({ user }: Props) {
  const [label, setLabel] = useState('')
  const [inviteUrl, setInviteUrl] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  if (!user.is_admin) return null

  const make = async () => {
    setErr(null)
    setCopied(false)
    setCreating(true)
    try {
      const inv = await createInvite(label.trim() || undefined)
      setInviteUrl(inv.invite_url)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not create an invite link')
    } finally {
      setCreating(false)
    }
  }

  const copy = async () => {
    if (!inviteUrl) return
    try {
      await navigator.clipboard.writeText(inviteUrl)
      setCopied(true)
    } catch {
      setErr('Copy failed — long-press the link to copy it manually.')
    }
  }

  return (
    <section className="border border-slate-700 rounded-lg p-4 space-y-3">
      <h2 className="text-lg font-semibold text-slate-100">Invites</h2>
      <p className="text-sm text-slate-400">
        An invite link lets one person create their own account. Each link
        works once and expires in 7 days.
      </p>
      <div>
        <label className="block text-slate-500 text-sm mb-1">
          Who is it for? (optional — prefill their display name)
        </label>
        <input
          className="w-full max-w-md min-h-[44px] bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="e.g. Marisol"
        />
      </div>
      <button
        type="button"
        disabled={creating}
        onClick={make}
        className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
      >
        {creating ? 'Creating…' : 'Create invite link'}
      </button>
      {inviteUrl && (
        <div className="space-y-2">
          <input
            readOnly
            value={inviteUrl}
            onFocus={(e) => e.target.select()}
            className="w-full min-h-[44px] bg-slate-900 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          />
          <button
            type="button"
            onClick={copy}
            className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-slate-600 text-slate-100 hover:bg-slate-500"
          >
            {copied ? 'Copied ✓' : 'Copy link'}
          </button>
        </div>
      )}
      {err && <p className="text-red-400 text-sm">{err}</p>}
    </section>
  )
}
