import { useEffect, useState } from 'react'
import type { CurrentUser } from './session'
import { getInvite, signupWithInvite } from './session'

interface InviteAcceptViewProps {
  code: string
  onSignedUp: (user: CurrentUser) => Promise<void>
  onBackToSignIn: () => void
}

/**
 * Invite landing for unauthenticated visitors arriving via ?invite=CODE.
 * Validates the code, then collects email + password and signs the user
 * up through POST /auth/signup (which lands them logged in).
 */
export function InviteAcceptView({ code, onSignedUp, onBackToSignIn }: InviteAcceptViewProps) {
  const [status, setStatus] = useState<'checking' | 'valid' | 'invalid'>('checking')
  const [inviter, setInviter] = useState<string | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const info = await getInvite(code)
        if (cancelled) return
        if (info.valid) {
          setStatus('valid')
          if (info.display_name) {
            setInviter(info.display_name)
            setDisplayName(info.display_name)
          }
        } else {
          setStatus('invalid')
        }
      } catch {
        if (!cancelled) setStatus('invalid')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [code])

  const submit = async () => {
    setError(null)
    if (!email.trim()) {
      setError('Email is required.')
      return
    }
    if (!password) {
      setError('Choose a password.')
      return
    }
    setSubmitting(true)
    try {
      const user = await signupWithInvite({
        email: email.trim(),
        password,
        display_name: displayName.trim(),
        invite_code: code,
      })
      await onSignedUp(user)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Signup failed')
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-800/70 p-6">
        {status === 'checking' && (
          <p className="text-sm text-slate-400">Checking your invite…</p>
        )}
        {status === 'invalid' && (
          <div className="space-y-4">
            <h1 className="text-xl font-semibold">This invite link isn't valid</h1>
            <p className="text-sm text-slate-400">
              It may have expired, already been used, or been typed wrong. Ask
              the person who invited you for a fresh link.
            </p>
            <button
              type="button"
              onClick={onBackToSignIn}
              className="w-full min-h-[44px] rounded-lg bg-slate-600 hover:bg-slate-500 py-2 text-sm font-medium"
            >
              Back to sign in
            </button>
          </div>
        )}
        {status === 'valid' && (
          <div>
            <h1 className="text-xl font-semibold">You've been invited</h1>
            <p className="text-sm text-slate-400 mt-1">
              {inviter ? `Invited by ${inviter}. ` : ''}Pick a password and your
              council is yours.
            </p>
            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Display name</label>
                <input
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full min-h-[44px] rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm"
                  autoComplete="nickname"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Email</label>
                <input
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full min-h-[44px] rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm"
                  autoComplete="username"
                  inputMode="email"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full min-h-[44px] rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm"
                  autoComplete="new-password"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !submitting) submit()
                  }}
                />
              </div>
              {error && <p className="text-sm text-red-300">{error}</p>}
              <button
                type="button"
                onClick={submit}
                disabled={submitting}
                className="w-full min-h-[44px] rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-slate-600 py-2 text-sm font-medium"
              >
                {submitting ? 'Creating your account…' : 'Create my account'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
