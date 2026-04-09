import { useState } from 'react'
import type { ContentBrief } from './types'
import type { Initiative } from '../vision-execution/types'
import type { Project } from '../vision-execution/types'

function splitLines(s: string): string[] {
  return (s || '')
    .split(/\r?\n/)
    .map((t) => t.trim())
    .filter(Boolean)
}
function joinLines(arr: string[]): string {
  return (arr || []).join('\n')
}

export function ContentBriefEditor({
  brief,
  onChange,
  initiatives,
  projects,
  onDistillSource,
}: {
  brief: ContentBrief
  onChange: (next: ContentBrief) => void
  initiatives: Initiative[]
  projects: Project[]
  onDistillSource?: (source: string) => Promise<{ key_themes: string[]; claims: string[] }>
}) {
  const [distilling, setDistilling] = useState(false)
  const update = (partial: Partial<ContentBrief>) => onChange({ ...brief, ...partial })
  const handleDistill = async () => {
    if (!onDistillSource || !brief.source_materials?.trim()) return
    setDistilling(true)
    try {
      const result = await onDistillSource(brief.source_materials)
      if (result.key_themes?.length || result.claims?.length) {
        update({
          key_themes: result.key_themes?.length ? result.key_themes : brief.key_themes,
          claims: result.claims?.length ? result.claims : brief.claims,
        })
      }
    } finally {
      setDistilling(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Title</label>
        <input
          type="text"
          value={brief.title}
          onChange={(e) => update({ title: e.target.value })}
          placeholder="Content package name"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Linked initiative</label>
          <select
            value={brief.linked_initiative_id}
            onChange={(e) => update({ linked_initiative_id: e.target.value })}
            className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
          >
            <option value="">— None —</option>
            {initiatives.map((i) => (
              <option key={i.id} value={i.id}>
                {(i.title || i.id).slice(0, 50)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Linked project</label>
          <select
            value={brief.linked_project_id}
            onChange={(e) => update({ linked_project_id: e.target.value })}
            className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm"
          >
            <option value="">— None —</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {(p.title || p.id).slice(0, 50)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="text-[11px] text-slate-500 leading-snug">
        Tie this package to execution context when it matters — same pattern future journal and council records will use to
        attach narrative to initiatives and projects.
      </p>

      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Audience</label>
        <input
          type="text"
          value={brief.audience}
          onChange={(e) => update({ audience: e.target.value })}
          placeholder="e.g. newsletter subscribers, investors"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
        />
      </div>

      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Content goal</label>
        <input
          type="text"
          value={brief.content_goal}
          onChange={(e) => update({ content_goal: e.target.value })}
          placeholder="What should this content achieve?"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
        />
      </div>

      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Key themes (one per line)</label>
        <textarea
          value={joinLines(brief.key_themes)}
          onChange={(e) => update({ key_themes: splitLines(e.target.value) })}
          rows={2}
          placeholder="Theme 1&#10;Theme 2"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500 font-mono"
        />
      </div>

      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Claims / key messages (one per line)</label>
        <textarea
          value={joinLines(brief.claims)}
          onChange={(e) => update({ claims: splitLines(e.target.value) })}
          rows={2}
          placeholder="Claim 1&#10;Claim 2"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500 font-mono"
        />
      </div>

      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">CTA</label>
        <input
          type="text"
          value={brief.cta}
          onChange={(e) => update({ cta: e.target.value })}
          placeholder="Primary call-to-action"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
        />
      </div>

      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Tone / voice</label>
        <input
          type="text"
          value={brief.tone_voice}
          onChange={(e) => update({ tone_voice: e.target.value })}
          placeholder="e.g. warm, professional, conversational"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
        />
      </div>

      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Target formats (one per line)</label>
        <textarea
          value={joinLines(brief.target_formats)}
          onChange={(e) => update({ target_formats: splitLines(e.target.value) })}
          rows={2}
          placeholder="script&#10;newsletter&#10;landing_page"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500 font-mono"
        />
      </div>

      <div>
        <div className="flex items-center justify-between gap-2 mb-1">
          <label className="block text-xs text-slate-500 uppercase tracking-wide">Source materials</label>
          {onDistillSource && (
            <button
              type="button"
              onClick={handleDistill}
              disabled={distilling || !brief.source_materials?.trim()}
              className="px-2 py-1 rounded bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-slate-200 text-xs"
            >
              {distilling ? 'Distilling…' : 'Distill themes & claims'}
            </button>
          )}
        </div>
        <textarea
          value={brief.source_materials}
          onChange={(e) => update({ source_materials: e.target.value })}
          rows={6}
          placeholder="Paste distilled notes, research, or source text here…"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500 font-mono"
        />
      </div>

      <div>
        <label className="block text-xs text-slate-500 uppercase tracking-wide mb-1">Notes</label>
        <textarea
          value={brief.notes}
          onChange={(e) => update({ notes: e.target.value })}
          rows={2}
          placeholder="Optional notes"
          className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-600 text-slate-100 text-sm placeholder-slate-500"
        />
      </div>
    </div>
  )
}
