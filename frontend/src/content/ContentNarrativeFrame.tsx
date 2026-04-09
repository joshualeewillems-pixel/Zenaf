/**
 * Product framing for the Content tab: narrative registrar north star vs what ships today.
 * Future backend/UI: see docs/02_ACTIVE_DESIGN/CONTENT_NARRATIVE_REGISTRAR_ROADMAP.md
 */
export function ContentNarrativeFrame() {
  return (
    <div className="mt-4 space-y-4 text-sm text-slate-300">
      <p className="leading-relaxed text-slate-300">
        Content is where private narrative work can become <strong className="text-slate-200 font-medium">saved packages</strong>,
        optionally <strong className="text-slate-200 font-medium">shaped into outputs</strong>, and tied to execution. The long-term
        picture is journal + council dialogue as records, richer transforms (comic, film, song, …), personal and global
        narrative registries, and guidance framed through resonant metaphor — always as{' '}
        <strong className="text-slate-200 font-medium">interpretation</strong>, not verdict.
      </p>

      <div
        className="rounded-lg border border-amber-500/35 bg-amber-950/25 px-3 py-2.5 text-xs text-amber-100/90 leading-snug"
        role="note"
      >
        <strong className="text-amber-200/95">Caution:</strong> any future “narrative phase” or arc estimate is a{' '}
        <em>candidate read</em> — useful for framing, not a diagnosis of you or your situation.
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-600 bg-slate-900/60 p-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-emerald-400/90 mb-2">In this build</h2>
          <ul className="list-disc list-inside space-y-1.5 text-xs text-slate-400 leading-relaxed">
            <li>
              <span className="text-slate-300">Content briefs</span> as narrative packages (API:{' '}
              <code className="text-slate-500">/vision-execution/content-briefs</code>)
            </li>
            <li>Link initiatives, projects, and tasks from the brief</li>
            <li>Generate script and newsletter drafts via <code className="text-slate-500">/run</code></li>
            <li>Export / handoff and transcript tools where shown</li>
          </ul>
        </div>
        <div className="rounded-lg border border-slate-600 bg-slate-900/40 p-3">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">Roadmap (not wired yet)</h2>
          <ul className="list-disc list-inside space-y-1.5 text-xs text-slate-500 leading-relaxed">
            <li>In-tab journaling and “save council exchange as record”</li>
            <li>Transforms beyond script/newsletter (comic, short film, song, …)</li>
            <li>Token-candidate flow and valuation from narrative depth + form</li>
            <li>Personal registrar (including backlash / resistance patterns)</li>
            <li>Global resonance index (consent-first, anonymized patterns)</li>
            <li>Narrative-state hints for council and guidance</li>
          </ul>
        </div>
      </div>

      <details className="rounded-lg border border-slate-700 bg-slate-900/30 text-xs text-slate-400 group">
        <summary className="cursor-pointer select-none px-3 py-2 font-medium text-slate-300 hover:text-slate-200">
          Architecture layers (reference)
        </summary>
        <ol className="list-decimal list-inside space-y-2 px-3 pb-3 pt-1 leading-relaxed border-t border-slate-700/80">
          <li>
            <span className="text-slate-300">Origin</span> — journal, council chat, saved records, attach to VE entities
          </li>
          <li>
            <span className="text-slate-300">Transform</span> — expressive artifacts from a record
          </li>
          <li>
            <span className="text-slate-300">Token formation</span> — value from arc, coherence, form, and others’ reuse potential
          </li>
          <li>
            <span className="text-slate-300">Personal registrar</span> — records, artifacts, links, stylization, candidates,
            backlash patterns
          </li>
          <li>
            <span className="text-slate-300">Global registrar</span> — structural resonance, not public identity dump
          </li>
          <li>
            <span className="text-slate-300">Guidance loop</span> — metaphor from matched tokens / mythic structure
          </li>
          <li>
            <span className="text-slate-300">Narrative-state engine</span> — phase estimates and prompts (interpretive)
          </li>
        </ol>
      </details>

      <p className="text-[11px] text-slate-600 leading-snug">
        System notes for implementers:{' '}
        <code className="text-slate-500">docs/02_ACTIVE_DESIGN/CONTENT_NARRATIVE_REGISTRAR_ROADMAP.md</code>
      </p>
    </div>
  )
}
