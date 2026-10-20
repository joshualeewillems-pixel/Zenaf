import type { CurrentUser } from '../../auth/session'
import { createInvite, seedKeystones } from '../../auth/session'
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
  const [backfilling, setBackfilling] = useState(false)
  const [backfillMsg, setBackfillMsg] = useState<string | null>(null)
  const [backfillErr, setBackfillErr] = useState<string | null>(null)

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

  const backfill = async () => {
    setBackfillMsg(null)
    setBackfillErr(null)
    setBackfilling(true)
    try {
      const result = await seedKeystones()
      const created = result.seeded.filter((s) => s.created)
      if (created.length === 0) {
        setBackfillMsg('Everyone already has it — nothing to do.')
      } else {
        const names = created.map((s) => s.email ?? 'unknown account').join(', ')
        setBackfillMsg(
          `Seeded ${created.length} account${created.length === 1 ? '' : 's'}: ${names}`,
        )
      }
    } catch (e) {
      setBackfillErr(e instanceof Error ? e.message : 'Could not run the keystone backfill')
    } finally {
      setBackfilling(false)
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
      <div className="border-t border-slate-700 pt-3 space-y-3">
        <h3 className="text-base font-semibold text-slate-100">Keystone backfill</h3>
        <p className="text-sm text-slate-400">
          Give every existing account the &lsquo;Meet your council&rsquo; starting
          initiative. Safe to run more than once — accounts that already have
          it are skipped.
        </p>
        <button
          type="button"
          disabled={backfilling}
          onClick={backfill}
          className="min-h-[44px] px-4 py-2 rounded-lg text-sm bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50"
        >
          {backfilling ? 'Backfilling…' : 'Backfill keystone initiative'}
        </button>
        {backfillMsg && <p className="text-sm text-slate-300">{backfillMsg}</p>}
        {backfillErr && <p className="text-red-400 text-sm">{backfillErr}</p>}
      </div>
    </section>
  )
}
