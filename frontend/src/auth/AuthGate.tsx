import { useState } from 'react'

interface AuthGateProps {
  onLogin: (email: string, password: string) => Promise<void>
  loading?: boolean
}

export function AuthGate({ onLogin, loading = false }: AuthGateProps) {
  const [email, setEmail] = useState('owner@local.atria')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setError(null)
    try {
      await onLogin(email.trim(), password)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Login failed')
    }
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-slate-700 bg-slate-800/70 p-6">
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="text-sm text-slate-400 mt-1">Local dev login for this workspace.</p>

        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1">Email</label>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm"
              autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm"
              autoComplete="current-password"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !loading) submit()
              }}
            />
          </div>
          {error && <p className="text-sm text-red-300">{error}</p>}
          <button
            type="button"
            onClick={submit}
            disabled={loading}
            className="w-full rounded-lg bg-amber-600 hover:bg-amber-500 disabled:bg-slate-600 py-2 text-sm font-medium"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </div>
      </div>
    </div>
  )
}
