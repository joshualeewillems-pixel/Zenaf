import { useCallback, useEffect, useState } from 'react'
import {
  fetchLLMSettings,
  saveCredential,
  saveLLMProfile,
  testLLM,
  updateProviderEnabled,
  type LLMSettingsResponse,
} from '../api'

const PROVIDERS = [
  { id: 'ollama', label: 'Ollama (local)', needsKey: false },
  { id: 'openai', label: 'OpenAI', needsKey: true },
  { id: 'anthropic', label: 'Anthropic', needsKey: true },
  { id: 'google', label: 'Google (Gemini)', needsKey: true },
  { id: 'xai', label: 'xAI', needsKey: true },
] as const

export function ModelConnectionsSection() {
  const [data, setData] = useState<LLMSettingsResponse | null>(null)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const [defaultProvider, setDefaultProvider] = useState('ollama')
  const [defaultModel, setDefaultModel] = useState('')
  const [ollamaUrl, setOllamaUrl] = useState('')
  const [ollamaModel, setOllamaModel] = useState('')
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const reload = useCallback(async () => {
    const d = await fetchLLMSettings()
    setData(d)
    setDefaultProvider(d.default_provider)
    setDefaultModel(d.default_model || '')
    setOllamaUrl(d.ollama_base_url || '')
    setOllamaModel(d.ollama_model || '')
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        await reload()
      } catch (e) {
        setLoadErr(e instanceof Error ? e.message : 'Load failed')
      }
    })()
  }, [reload])

  const saveProfile = async () => {
    setErr(null)
    setMsg(null)
    setBusy(true)
    try {
      await saveLLMProfile({
        default_provider: defaultProvider,
        default_model: defaultModel.trim() || null,
        ollama_base_url: ollamaUrl.trim() || null,
        ollama_model: ollamaModel.trim() || null,
      })
      await reload()
      setMsg('Profile saved.')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  const saveKey = async (provider: string) => {
    const k = keyInputs[provider]?.trim()
    if (!k) {
      setErr('Enter an API key first.')
      return
    }
    setErr(null)
    setMsg(null)
    setBusy(true)
    try {
      await saveCredential(provider, k)
      setKeyInputs((prev) => ({ ...prev, [provider]: '' }))
      await reload()
      setMsg(`Saved ${provider} key.`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save key failed')
    } finally {
      setBusy(false)
    }
  }

  const runTest = async (provider: string) => {
    setErr(null)
    setMsg(null)
    setBusy(true)
    try {
      const ephemeral = keyInputs[provider]?.trim() || undefined
      const r = await testLLM(provider, ephemeral, defaultModel.trim() || null)
      if (r.ok) setMsg(`Connection OK (${provider}).`)
      else setErr(r.error || 'Connection failed')
      await reload()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Test failed')
    } finally {
      setBusy(false)
    }
  }

  const rowFor = (id: string) => data?.providers?.find((x) => x.id === id)

  const toggleExecutionProvider = async (id: string, enabled: boolean) => {
    setErr(null)
    setMsg(null)
    setBusy(true)
    try {
      const next = await updateProviderEnabled(id, enabled)
      setData((prev) => (prev ? { ...prev, providers: next } : prev))
      setMsg(`Provider ${id} ${enabled ? 'enabled' : 'disabled'} for routed runs.`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Update failed')
    } finally {
      setBusy(false)
    }
  }

  if (loadErr) {
    return (
      <section className="border border-red-900/50 rounded-lg p-4 text-red-300 text-sm">
        Model settings: {loadErr}
      </section>
    )
  }
  if (!data) {
    return <section className="border border-slate-700 rounded-lg p-4 text-slate-400 text-sm">Loading…</section>
  }

  return (
    <section className="border border-slate-700 rounded-lg p-4 space-y-4">
      <h2 className="text-lg font-semibold text-slate-100">Model connections</h2>
      <p className="text-xs text-slate-500">
        For workflow execution (not a chat playground). The API encrypts saved keys using{' '}
        <code className="text-slate-400">ATRIA_SETTINGS_ENCRYPTION_KEY</code> if set, otherwise a key file at{' '}
        <code className="text-slate-400">~/.atria/settings_encryption.key</code> (created automatically). Routed
        modes use OpenAI as: <span className="text-slate-300">OPENAI_API_KEY</span> on the server first, then your
        saved key when signed in with cookies on <code className="text-slate-400">POST /run</code>.
        {!data.encryption_configured && (
          <span className="text-amber-400 block mt-1">
            Encryption unavailable (install the Python <code className="text-amber-300">cryptography</code> package on
            the API host) — Save key stays disabled until then.
          </span>
        )}
      </p>
      <div className="rounded bg-slate-800/50 border border-slate-600 px-3 py-2 text-sm">
        <span className="text-slate-500">Active for authenticated tools:</span>{' '}
        <span className="text-slate-200 font-medium">
          {data.active_summary.provider} / {data.active_summary.model}
        </span>
      </div>

      <div className="rounded bg-slate-800/50 border border-slate-600 px-3 py-3 text-sm space-y-3">
        <div>
          <h3 className="text-slate-300 text-sm font-medium">Provider registry</h3>
          <p className="text-[11px] text-slate-500 mt-1">
            Server-backed toggles: disabled providers are skipped by routed execution (Workspace / Vision Execution with
            routing context). Status reflects your keys and last connection test.
          </p>
        </div>
        <ul className="space-y-2">
          {PROVIDERS.map((p) => {
            const st = rowFor(p.id)
            const testLabel =
              st?.test_status === 'passed'
                ? 'Test OK'
                : st?.test_status === 'failed'
                  ? 'Test failed'
                  : 'Not tested'
            const testClass =
              st?.test_status === 'passed'
                ? 'text-emerald-400'
                : st?.test_status === 'failed'
                  ? 'text-red-400'
                  : 'text-slate-500'
            return (
              <li
                key={p.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs border-b border-slate-700/60 pb-2 last:border-0 last:pb-0"
              >
                <label className="flex items-center gap-2 text-slate-300 cursor-pointer min-w-[140px]">
                  <input
                    type="checkbox"
                    className="rounded border-slate-600 bg-slate-900 text-amber-500 disabled:opacity-40"
                    checked={st ? st.enabled : true}
                    disabled={busy || !st}
                    onChange={(e) => void toggleExecutionProvider(p.id, e.target.checked)}
                  />
                  {p.label}
                </label>
                <span className="text-slate-500">
                  {st?.configured ? (
                    <span className="text-emerald-500/90">Configured</span>
                  ) : (
                    <span className="text-slate-500">Not configured</span>
                  )}
                  {st && !st.available ? (
                    <span className="text-amber-400/90 ml-2" title={st.status_message || ''}>
                      Unavailable
                    </span>
                  ) : null}
                </span>
                <span className={`${testClass}`}>{testLabel}</span>
                <span className="text-slate-500 font-mono text-[11px]" title="Default model hint">
                  {st?.default_model ?? '—'}
                </span>
                {st?.status_message ? (
                  <span className="text-[10px] text-slate-500 w-full">{st.status_message}</span>
                ) : null}
                {st?.last_test_error && st.test_status === 'failed' ? (
                  <span className="text-[10px] text-red-400/90 w-full truncate" title={st.last_test_error}>
                    {st.last_test_error}
                  </span>
                ) : null}
              </li>
            )
          })}
        </ul>
      </div>

      {data.openai_execution && (
        <div className="rounded bg-slate-800/50 border border-slate-600 px-3 py-2 text-sm space-y-1">
          <div className="text-slate-400 text-xs font-medium">OpenAI — routed execution (Workspace / Council)</div>
          <ul className="text-xs text-slate-300 list-disc list-inside space-y-0.5">
            <li>
              <span className="text-slate-500">Env OPENAI_API_KEY:</span>{' '}
              {data.openai_execution.env_key_present ? 'set (overrides saved key)' : 'not set'}
            </li>
            <li>
              <span className="text-slate-500">Saved in Settings:</span>{' '}
              {data.openai_execution.settings_key_saved ? 'yes' : 'no'}
            </li>
            <li>
              <span className="text-slate-500">Effective source:</span>{' '}
              {data.openai_execution.effective_source === 'env' && 'environment'}
              {data.openai_execution.effective_source === 'settings' && 'saved Settings key'}
              {data.openai_execution.effective_source === 'none' && 'none — configure env or save a key'}
            </li>
            <li>
              <span className="text-slate-500">Status:</span>{' '}
              {data.openai_execution.status === 'no_key_configured' && 'no key configured'}
              {data.openai_execution.status === 'env_override_active' && 'env override active'}
              {data.openai_execution.status === 'saved_key_available' && 'saved key available (used when env unset)'}
            </li>
          </ul>
          <p className="text-[11px] text-slate-500 pt-1">{data.openai_execution.note}</p>
        </div>
      )}
      <div className="grid gap-2 max-w-xl">
        <label className="text-sm text-slate-400">Default provider</label>
        <select
          className="bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          value={defaultProvider}
          onChange={(e) => setDefaultProvider(e.target.value)}
        >
          {PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        <label className="text-sm text-slate-400">Default model (cloud providers)</label>
        <input
          className="bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          placeholder="e.g. gpt-4o-mini, claude-haiku-4-5"
          value={defaultModel}
          onChange={(e) => setDefaultModel(e.target.value)}
        />
        <label className="text-sm text-slate-400">Ollama base URL (optional, full generate URL)</label>
        <input
          className="bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          placeholder="http://localhost:11434/api/generate"
          value={ollamaUrl}
          onChange={(e) => setOllamaUrl(e.target.value)}
        />
        <label className="text-sm text-slate-400">Ollama model override (optional)</label>
        <input
          className="bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
          value={ollamaModel}
          onChange={(e) => setOllamaModel(e.target.value)}
        />
        <button
          type="button"
          disabled={busy}
          onClick={saveProfile}
          className="w-fit px-3 py-1.5 rounded-lg text-sm bg-amber-600 text-slate-900 font-medium hover:bg-amber-500 disabled:opacity-50"
        >
          Save profile
        </button>
      </div>

      <div className="space-y-3 pt-2 border-t border-slate-700">
        <h3 className="text-slate-300 text-sm font-medium">Provider keys</h3>
        {PROVIDERS.filter((p) => p.needsKey).map((p) => (
          <div key={p.id} className="flex flex-wrap items-end gap-2">
            <div className="flex-1 min-w-[200px]">
              <div className="text-xs text-slate-500 mb-1">
                {p.label}{' '}
                {data.credentials_present[p.id] ? (
                  <span className="text-emerald-500">· key stored</span>
                ) : (
                  <span className="text-slate-600">· no key</span>
                )}
              </div>
              <input
                type="password"
                autoComplete="off"
                className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
                placeholder="API key — not shown after save"
                value={keyInputs[p.id] || ''}
                onChange={(e) => setKeyInputs((prev) => ({ ...prev, [p.id]: e.target.value }))}
              />
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => saveKey(p.id)}
              className="px-2 py-1.5 rounded text-xs bg-slate-600 text-slate-100 disabled:opacity-40"
              title={
                data.encryption_configured
                  ? 'Save encrypted key on the server'
                  : 'Server reports encryption unavailable — click to try; check error message if save fails'
              }
            >
              Save key
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => runTest(p.id)}
              className="px-2 py-1.5 rounded text-xs border border-slate-600 text-slate-300"
            >
              Test
            </button>
          </div>
        ))}
        <div className="flex items-end gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => runTest('ollama')}
            className="px-2 py-1.5 rounded text-xs border border-slate-600 text-slate-300"
          >
            Test Ollama
          </button>
        </div>
      </div>
      {msg && <p className="text-emerald-400 text-sm">{msg}</p>}
      {err && <p className="text-red-400 text-sm">{err}</p>}
    </section>
  )
}
