import { useState } from 'react'
import type { Project } from '../vision-execution/types'

const SUGGESTED_NEXT_ACTIONS = [
  { id: 'record_narration', label: 'Record narration', title: 'Record narration' },
  { id: 'produce_video', label: 'Produce video', title: 'Produce avatar video' },
  { id: 'publish_newsletter', label: 'Publish newsletter', title: 'Send newsletter' },
  { id: 'build_landing', label: 'Build landing page', title: 'Build landing page' },
] as const

export function ContentExportPane({
  scriptText,
  newsletterText,
  linkedProjectId,
  projects,
  onCreateVETasks,
  onMarkInProduction,
  onCopyScriptSuccess,
  onCopyNewsletterSuccess,
  onExportScriptSuccess,
  onCreateTasksSuccess,
}: {
  scriptText: string
  newsletterText: string
  linkedProjectId: string
  projects: Project[]
  onCreateVETasks: (projectId: string, title: string) => Promise<void>
  onMarkInProduction?: () => Promise<void>
  onCopyScriptSuccess?: () => void
  onCopyNewsletterSuccess?: () => void
  onExportScriptSuccess?: () => void
  /** After all selected VE tasks are created successfully. */
  onCreateTasksSuccess?: () => void
}) {
  const [copyFeedback, setCopyFeedback] = useState<'script' | 'newsletter' | null>(null)
  const [selectedActions, setSelectedActions] = useState<Set<string>>(new Set())
  const [veModalOpen, setVeModalOpen] = useState(false)
  const [veProjectId, setVeProjectId] = useState(linkedProjectId || '')
  const [veSaving, setVeSaving] = useState(false)
  const [veError, setVeError] = useState<string | null>(null)

  const copyToClipboard = async (text: string, kind: 'script' | 'newsletter') => {
    if (!text.trim()) return
    try {
      await navigator.clipboard.writeText(text)
      setCopyFeedback(kind)
      setTimeout(() => setCopyFeedback(null), 2000)
      if (kind === 'script') onCopyScriptSuccess?.()
      else onCopyNewsletterSuccess?.()
    } catch (_) {}
  }

  const toggleAction = (id: string) => {
    setSelectedActions((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const exportElevenLabsScript = () => {
    if (!scriptText.trim()) return
    const blob = new Blob([scriptText], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'elevenlabs-script.txt'
    a.click()
    URL.revokeObjectURL(url)
    onExportScriptSuccess?.()
  }

  const handleCreateSelectedTasks = async () => {
    if (!veProjectId || selectedActions.size === 0) {
      setVeError('Select a project and at least one next action.')
      return
    }
    setVeError(null)
    setVeSaving(true)
    try {
      for (const id of selectedActions) {
        const action = SUGGESTED_NEXT_ACTIONS.find((a) => a.id === id)
        if (action) await onCreateVETasks(veProjectId, action.title)
      }
      onCreateTasksSuccess?.()
      setVeModalOpen(false)
      setSelectedActions(new Set())
    } catch (e) {
      setVeError(e instanceof Error ? e.message : 'Failed to create tasks')
    } finally {
      setVeSaving(false)
    }
  }

  return (
    <div className="rounded-xl border border-slate-600 bg-slate-800/80 p-4 space-y-4">
      <h3 className="text-sm font-semibold text-slate-200">Export & next actions</h3>

      <div className="space-y-2">
        <button
          type="button"
          onClick={() => copyToClipboard(scriptText, 'script')}
          disabled={!scriptText.trim()}
          className="w-full px-3 py-2 rounded-lg border border-slate-600 text-slate-300 hover:text-slate-100 hover:bg-slate-700/50 disabled:opacity-50 text-xs font-medium text-left"
        >
          {copyFeedback === 'script' ? 'Copied!' : 'Copy script'}
        </button>
        <button
          type="button"
          onClick={exportElevenLabsScript}
          disabled={!scriptText.trim()}
          className="w-full px-3 py-2 rounded-lg border border-slate-600 text-slate-300 hover:text-slate-100 hover:bg-slate-700/50 disabled:opacity-50 text-xs font-medium text-left"
        >
          Export ElevenLabs script
        </button>
        <button
          type="button"
          onClick={() => copyToClipboard(newsletterText, 'newsletter')}
          disabled={!newsletterText.trim()}
          className="w-full px-3 py-2 rounded-lg border border-slate-600 text-slate-300 hover:text-slate-100 hover:bg-slate-700/50 disabled:opacity-50 text-xs font-medium text-left"
        >
          {copyFeedback === 'newsletter' ? 'Copied!' : 'Copy newsletter'}
        </button>
      </div>

      <div className="pt-2 border-t border-slate-700">
        <p className="text-xs text-slate-400 mb-2">Suggested next actions</p>
        <div className="space-y-1.5">
          {SUGGESTED_NEXT_ACTIONS.map((action) => (
            <label key={action.id} className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={selectedActions.has(action.id)}
                onChange={() => toggleAction(action.id)}
                className="rounded border-slate-600 bg-slate-900 text-amber-500"
              />
              {action.label}
            </label>
          ))}
        </div>
        <button
          type="button"
          onClick={() => {
            setVeProjectId((linkedProjectId || projects[0]?.id) ?? '')
            setVeError(null)
            setVeModalOpen(true)
          }}
          disabled={selectedActions.size === 0}
          className="mt-3 w-full px-3 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-medium"
        >
          Create selected tasks
        </button>
      </div>

      {onMarkInProduction && (
        <div className="pt-2 border-t border-slate-700">
          <button
            type="button"
            onClick={onMarkInProduction}
            className="w-full px-3 py-2 rounded-lg bg-slate-600 hover:bg-slate-500 text-slate-200 text-xs font-medium"
          >
            Mark brief in production
          </button>
        </div>
      )}

      {veModalOpen && (
        <div className="fixed inset-0 z-20 flex items-center justify-center p-4 bg-black/60" onClick={() => setVeModalOpen(false)}>
          <div className="bg-slate-800 border border-slate-600 rounded-xl shadow-xl max-w-md w-full p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-medium text-slate-100 mb-3">Create Vision Execution tasks</h3>
            <p className="text-xs text-slate-400 mb-4">Tasks will be attached to the selected project.</p>
            <div className="space-y-3 mb-4">
              <div>
                <label className="block text-xs text-slate-500 mb-1">Project</label>
                <select
                  value={veProjectId}
                  onChange={(e) => setVeProjectId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
                >
                  <option value="">— Select project —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {(p.title || p.id).slice(0, 60)}
                    </option>
                  ))}
                </select>
              </div>
              <p className="text-xs text-slate-500">
                Creating: {Array.from(selectedActions).map((id) => SUGGESTED_NEXT_ACTIONS.find((a) => a.id === id)?.label).filter(Boolean).join(', ')}
              </p>
            </div>
            {veError && <p className="text-red-400 text-xs mb-2">{veError}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setVeModalOpen(false)} className="px-4 py-2 rounded-lg border border-slate-600 text-slate-400 hover:text-slate-300 text-sm">
                Cancel
              </button>
              <button type="button" onClick={handleCreateSelectedTasks} disabled={veSaving} className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-sm font-medium">
                {veSaving ? 'Creating…' : 'Create tasks'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
