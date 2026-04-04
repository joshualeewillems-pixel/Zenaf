import { useState, useCallback, useEffect } from 'react'
import type { PerspectiveAgent } from './types'
import { AvatarPicker } from '../components/AvatarPicker'
import { exportPerspective, parsePerspective, type PerspectiveFormState } from './importExport'
import { PERSPECTIVE_ICON_OPTIONS, PerspectiveRoleIcon, type PerspectiveIconId } from './roleIcons'

const LABELS = {
  name: 'Name',
  icon: 'Role Symbol',
  role: 'Archetype / actor type',
  purpose: 'Core Purpose',
  values: 'Top Values',
  aversions: 'What it avoids',
  reasoningStyle: 'Reasoning Style',
  tone: 'Tone of Voice',
  domain: 'Domain / Use Case',
  decisionRule: 'Decision Rule',
  context: 'Context / reference material',
  worldview: 'Worldview notes',
  constraints: 'Constraints / boundaries',
  examplePhrases: 'Example phrases',
  promptNotes: 'Custom prompt notes',
} as const

function parseCsv(line: string): string[] {
  return line
    .split(/[,;]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function AgentCreatorForm({
  initial,
  onSubmit,
  onCancel,
}: {
  initial?: Partial<PerspectiveAgent> | null
  onSubmit: (agent: PerspectiveAgent) => void
  onCancel?: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [icon, setIcon] = useState<PerspectiveIconId | ''>(initial?.icon ?? '')
  const [role, setRole] = useState(initial?.role ?? '')
  const [purpose, setPurpose] = useState(initial?.purpose ?? '')
  const [valuesText, setValuesText] = useState((initial?.values ?? []).join(', '))
  const [aversionsText, setAversionsText] = useState((initial?.aversions ?? []).join(', '))
  const [reasoningText, setReasoningText] = useState((initial?.reasoningStyle ?? []).join(', '))
  const [tone, setTone] = useState(initial?.tone ?? '')
  const [domainText, setDomainText] = useState((initial?.domain ?? []).join(', '))
  const [decisionRule, setDecisionRule] = useState(initial?.decisionRule ?? '')
  const [context, setContext] = useState(initial?.context ?? '')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [worldview, setWorldview] = useState(initial?.worldview ?? '')
  const [constraintsText, setConstraintsText] = useState((initial?.constraints ?? []).join(', '))
  const [examplePhrasesText, setExamplePhrasesText] = useState((initial?.examplePhrases ?? []).join(', '))
  const [promptNotes, setPromptNotes] = useState(initial?.promptNotes ?? '')
  const [avatar, setAvatar] = useState<PerspectiveAgent['avatar']>(initial?.avatar)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [importPasteText, setImportPasteText] = useState('')
  const [toastMessage, setToastMessage] = useState<string | null>(null)

  const getCurrentFormState = useCallback((): PerspectiveFormState => ({
    name,
    role,
    purpose,
    valuesText,
    aversionsText,
    reasoningText,
    tone,
    domainText,
    decisionRule,
    context,
    worldview: worldview || undefined,
    constraintsText: constraintsText || undefined,
    examplePhrasesText: examplePhrasesText || undefined,
    promptNotes: promptNotes || undefined,
  }), [name, role, purpose, valuesText, aversionsText, reasoningText, tone, domainText, decisionRule, context, worldview, constraintsText, examplePhrasesText, promptNotes])

  const handleExport = useCallback(() => {
    const state = getCurrentFormState()
    const text = exportPerspective(state)
    navigator.clipboard.writeText(text).then(
      () => {
        setToastMessage('Actor copied to clipboard')
        const t = setTimeout(() => setToastMessage(null), 2500)
        return () => clearTimeout(t)
      },
      () => setToastMessage('Could not copy to clipboard')
    )
  }, [getCurrentFormState])

  const handleImportApply = useCallback(() => {
    const parsed = parsePerspective(importPasteText)
    if (parsed.name !== undefined) setName(String(parsed.name))
    if (parsed.role !== undefined) setRole(String(parsed.role))
    if (parsed.purpose !== undefined) setPurpose(String(parsed.purpose))
    if (parsed.values !== undefined) setValuesText(parsed.values.join(', '))
    if (parsed.aversions !== undefined) setAversionsText(parsed.aversions.join(', '))
    if (parsed.reasoningStyle !== undefined) setReasoningText(parsed.reasoningStyle.join(', '))
    if (parsed.tone !== undefined) setTone(String(parsed.tone))
    if (parsed.domain !== undefined) setDomainText(parsed.domain.join(', '))
    if (parsed.decisionRule !== undefined) setDecisionRule(String(parsed.decisionRule))
    if (parsed.context !== undefined) setContext(String(parsed.context))
    if (parsed.worldview !== undefined) setWorldview(String(parsed.worldview))
    if (parsed.constraints !== undefined) setConstraintsText(parsed.constraints.join(', '))
    if (parsed.examplePhrases !== undefined) setExamplePhrasesText(parsed.examplePhrases.join(', '))
    if (parsed.promptNotes !== undefined) setPromptNotes(String(parsed.promptNotes))
    setImportModalOpen(false)
    setImportPasteText('')
  }, [importPasteText])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const agent: PerspectiveAgent = {
      id: initial?.id ?? '',
      name: name.trim(),
      icon: icon || undefined,
      avatar,
      actor_kind: initial?.actor_kind,
      source_archetype_id: initial?.source_archetype_id,
      role: role.trim(),
      purpose: purpose.trim(),
      values: parseCsv(valuesText),
      aversions: parseCsv(aversionsText),
      reasoningStyle: parseCsv(reasoningText),
      tone: tone.trim(),
      domain: parseCsv(domainText),
      decisionRule: decisionRule.trim(),
      context: context.trim() || undefined,
      worldview: worldview.trim() || undefined,
      constraints: parseCsv(constraintsText).length ? parseCsv(constraintsText) : undefined,
      examplePhrases: parseCsv(examplePhrasesText).length ? parseCsv(examplePhrasesText) : undefined,
      promptNotes: promptNotes.trim() || undefined,
      createdAt: initial?.createdAt ?? new Date().toISOString(),
    }
    onSubmit(agent)
  }

  const inputClass =
    'w-full px-3 py-2 rounded-lg bg-surface-sunken border border-[color:var(--color-border)] text-warm-white text-sm placeholder:text-warm-white/35 focus:outline-none focus:ring-2 focus:ring-accent/45 focus:border-accent/50'
  const labelClass = 'block text-sm font-medium text-warm-white/70 mb-1'

  return (
    <div className="relative">
      <div className="flex justify-end gap-2 mb-4">
        <button
          type="button"
          onClick={() => setImportModalOpen(true)}
          className="px-3 py-1.5 rounded-lg border border-[color:var(--color-border)] text-warm-white/80 hover:bg-surface-raised text-sm font-medium"
        >
          Import
        </button>
        <button
          type="button"
          onClick={handleExport}
          className="px-3 py-1.5 rounded-lg border border-[color:var(--color-border)] text-warm-white/80 hover:bg-surface-raised text-sm font-medium"
        >
          Export
        </button>
      </div>
      {toastMessage && (
        <div
          className="absolute top-12 right-0 px-3 py-2 rounded-lg bg-surface-raised border border-[color:var(--color-border)] text-warm-white text-sm shadow-lg z-10"
          role="status"
        >
          {toastMessage}
        </div>
      )}
      {importModalOpen && (
        <div className="fixed inset-0 z-20 flex items-center justify-center p-4 bg-black/60" onClick={() => setImportModalOpen(false)}>
          <div
            className="bg-surface-raised border border-[color:var(--color-border)] rounded-xl shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-medium text-warm-white p-4 border-b border-[color:var(--color-border)]">Import actor</h3>
            <textarea
              value={importPasteText}
              onChange={(e) => setImportPasteText(e.target.value)}
              placeholder="Paste an actor definition here. The system will attempt to map it to the fields."
              className="flex-1 min-h-[200px] w-full p-4 resize-none bg-surface-sunken border-0 border-b border-[color:var(--color-border)] text-warm-white text-sm placeholder:text-warm-white/35 focus:outline-none focus:ring-2 focus:ring-accent/45 rounded-none"
              autoFocus
            />
            <div className="flex justify-end gap-2 p-4 border-t border-[color:var(--color-border)]">
              <button
                type="button"
                onClick={() => {
                  setImportModalOpen(false)
                  setImportPasteText('')
                }}
                className="px-4 py-2 rounded-lg border border-[color:var(--color-border)] text-warm-white/60 hover:text-warm-white text-sm"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleImportApply}
                className="px-4 py-2 rounded-lg bg-accent hover:opacity-90 text-warm-white text-sm font-medium"
              >
                Import
              </button>
            </div>
          </div>
        </div>
      )}
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className={labelClass}>{LABELS.name}</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. The Pragmatic Editor"
          className={inputClass}
          required
        />
      </div>
      <AvatarPicker agentName={name} value={avatar} onChange={setAvatar} />
      <div>
        <label className={labelClass}>{LABELS.icon}</label>
        <div className="flex items-center gap-2">
          <select
            value={icon}
            onChange={(e) => setIcon((e.target.value as PerspectiveIconId | '') ?? '')}
            className={inputClass}
          >
            <option value="">Auto (from role/name)</option>
            {PERSPECTIVE_ICON_OPTIONS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
          {icon ? (
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[color:var(--color-border)] bg-surface-sunken text-warm-white/90">
              <PerspectiveRoleIcon icon={icon} className="h-4 w-4" />
            </span>
          ) : null}
        </div>
        <p className="text-xs text-warm-white/40 mt-1">Used in council seat list and actor cards.</p>
      </div>
      <div>
        <label className={labelClass}>{LABELS.role}</label>
        <input
          type="text"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          placeholder="e.g. Editor, Critic, Big Picture"
          className={inputClass}
          required
        />
      </div>
      <div>
        <label className={labelClass}>{LABELS.purpose}</label>
        <textarea
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
          placeholder="What is this actor trying to achieve?"
          className={`${inputClass} min-h-[80px]`}
          rows={3}
          required
        />
      </div>
      <div>
        <label className={labelClass}>{LABELS.values}</label>
        <input
          type="text"
          value={valuesText}
          onChange={(e) => setValuesText(e.target.value)}
          placeholder="Comma-separated, e.g. clarity, honesty, impact"
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>{LABELS.aversions}</label>
        <input
          type="text"
          value={aversionsText}
          onChange={(e) => setAversionsText(e.target.value)}
          placeholder="What it avoids or fears"
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>{LABELS.reasoningStyle}</label>
        <input
          type="text"
          value={reasoningText}
          onChange={(e) => setReasoningText(e.target.value)}
          placeholder="e.g. evidence-first, principle-driven, iterative"
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>{LABELS.tone}</label>
        <input
          type="text"
          value={tone}
          onChange={(e) => setTone(e.target.value)}
          placeholder="e.g. direct, warm, formal"
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>{LABELS.domain}</label>
        <input
          type="text"
          value={domainText}
          onChange={(e) => setDomainText(e.target.value)}
          placeholder="e.g. writing, product, research"
          className={inputClass}
        />
      </div>
      <div>
        <label className={labelClass}>{LABELS.decisionRule}</label>
        <textarea
          value={decisionRule}
          onChange={(e) => setDecisionRule(e.target.value)}
          placeholder="When forced to choose, how does it decide?"
          className={`${inputClass} min-h-[60px]`}
          rows={2}
        />
      </div>
      <div>
        <label className={labelClass}>{LABELS.context}</label>
        <p className="text-xs text-warm-white/40 mb-1">Reference material or background this actor should use (text or upload).</p>
        <textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          placeholder="Paste or type context, or use Upload below"
          className={`${inputClass} min-h-[100px]`}
          rows={4}
        />
        <label className="mt-2 flex items-center gap-2 text-xs text-warm-white/50 cursor-pointer">
          <input
            type="file"
            accept=".txt,.md,.json,.csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (!file) return
              const reader = new FileReader()
              reader.onload = () => setContext((prev) => prev + (prev ? '\n\n' : '') + String(reader.result ?? ''))
              reader.readAsText(file)
              e.target.value = ''
            }}
          />
          <span className="px-2 py-1.5 rounded border border-[color:var(--color-border)] hover:bg-surface-raised">Upload file (.txt, .md, .json, .csv)</span>
        </label>
      </div>

      <div className="border-t border-[color:var(--color-border)] pt-4">
        <button
          type="button"
          onClick={() => setAdvancedOpen((o) => !o)}
          className="text-sm text-warm-white/50 hover:text-warm-white/75 flex items-center gap-2"
        >
          {advancedOpen ? '▼' : '▶'} Advanced options
        </button>
        {advancedOpen && (
          <div className="mt-3 space-y-4 pl-0">
            <div>
              <label className={labelClass}>{LABELS.worldview}</label>
              <textarea
                value={worldview}
                onChange={(e) => setWorldview(e.target.value)}
                placeholder="Underlying assumptions or worldview"
                className={`${inputClass} min-h-[60px]`}
                rows={2}
              />
            </div>
            <div>
              <label className={labelClass}>{LABELS.constraints}</label>
              <input
                type="text"
                value={constraintsText}
                onChange={(e) => setConstraintsText(e.target.value)}
                placeholder="Comma-separated boundaries"
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass}>{LABELS.examplePhrases}</label>
              <input
                type="text"
                value={examplePhrasesText}
                onChange={(e) => setExamplePhrasesText(e.target.value)}
                placeholder="How it might phrase things"
                className={inputClass}
              />
            </div>
            <div>
              <label className={labelClass}>{LABELS.promptNotes}</label>
              <textarea
                value={promptNotes}
                onChange={(e) => setPromptNotes(e.target.value)}
                placeholder="Optional technical notes (hidden from main view)"
                className={`${inputClass} min-h-[60px]`}
                rows={2}
              />
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-accent hover:opacity-90 text-warm-white text-sm font-medium"
        >
          {initial?.id ? 'Update actor' : 'Create actor'}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-lg border border-[color:var(--color-border)] text-warm-white/65 hover:text-warm-white text-sm"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
    </div>
  )
}
