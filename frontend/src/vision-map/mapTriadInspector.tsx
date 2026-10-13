import { memo, useState, type ReactNode } from 'react'
import type { ExecutionStep } from '../vision-execution/types'
import type { MapEntityRef, MapNodePayload } from './ontology'
import type { VisionMapEntityBundle } from './blockersFromVe'
import { veSelectionFromEntityRef } from './mapCouncilActions'

export type TriadInspectorSection = 'water' | 'soil' | 'fruit'

/** Row used for nested inspector (outcome nodes anchor on parent project). */
export function resolveInspectEntityRef(selected: MapNodePayload): MapEntityRef {
  if (selected.ref.veType === 'outcome' && selected.parentRef) {
    return selected.parentRef
  }
  if (selected.ref.veType === 'outcome') {
    const m = /^fruit-proj-(.+)-deliver$/.exec(selected.ref.id)
    if (m) return { veType: 'project', id: m[1]! }
  }
  return selected.ref
}

function FieldBlock({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] uppercase tracking-wide text-stone-500">{label}</div>
      <div className="text-xs text-stone-200 whitespace-pre-wrap break-words">{children ?? '—'}</div>
    </div>
  )
}

/**
 * Same interaction model as Vision Execution `DetailSection`: collapsible header + ▼/▶.
 * Stone palette matches the map shell; titles mirror initiative detail panel section names where applicable.
 */
function InspectorCollapsibleSection({
  title,
  hint,
  children,
  defaultOpen = true,
}: {
  title: string
  hint?: string
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-stone-800/80 last:border-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-2 py-2 text-left text-[10px] font-medium text-stone-500 uppercase tracking-wide hover:text-stone-300"
      >
        <span className="min-w-0">{title}</span>
        <span className="text-stone-600 shrink-0">{open ? '▼' : '▶'}</span>
      </button>
      {open && (
        <div className="pb-3 space-y-3">
          {hint ? <p className="text-[9px] text-stone-600 leading-snug -mt-1 mb-0.5">{hint}</p> : null}
          {children}
        </div>
      )}
    </div>
  )
}

function idList(label: string, ids: string[] | null | undefined) {
  const xs = (ids ?? []).filter(Boolean)
  if (!xs.length) return <FieldBlock label={label}>—</FieldBlock>
  return (
    <FieldBlock label={label}>
      {xs.map((id) => (
        <div key={id} className="font-mono text-[11px] text-stone-300">
          {id}
        </div>
      ))}
    </FieldBlock>
  )
}

const SECTION_HEADINGS: Record<TriadInspectorSection, { title: string; subtitle: string }> = {
  water: {
    title: 'Water',
    subtitle: 'What is feeding this row — people, ownership, attention, and capacity.',
  },
  soil: {
    title: 'Soil',
    subtitle: 'Definition, context, and grounding — what this row is and what holds it in place.',
  },
  fruit: {
    title: 'Fruit',
    subtitle: 'What has emerged or must ship — outputs, deliverables, and linked artifacts.',
  },
}

function MapTriadInspectorContentImpl({
  selected,
  bundle,
  section,
  onOpenInVisionExecution,
  initiativeExecutionSteps,
  initiativeExecutionStepsLoading,
}: {
  selected: MapNodePayload
  bundle: VisionMapEntityBundle | null
  section: TriadInspectorSection
  /** Single quiet jump to Vision & Execution for the inspected row (not shown if navigation is impossible). */
  onOpenInVisionExecution?: () => void
  /** Read-only mirror of checklist rows for the selected initiative (same data as VE Execution section). */
  initiativeExecutionSteps?: ExecutionStep[] | null
  initiativeExecutionStepsLoading?: boolean
}) {
  const ref = resolveInspectEntityRef(selected)
  const heading = SECTION_HEADINGS[section]
  const canOpenVe = veSelectionFromEntityRef(ref) != null && onOpenInVisionExecution != null

  if (!bundle) {
    return (
      <div
        data-testid="map-triad-inspector"
        data-section={section}
        className="rounded-lg border border-stone-800 bg-stone-900/40 px-3 py-2.5 space-y-2"
      >
        <div>
          <div className="text-[11px] font-semibold text-stone-200">{heading.title}</div>
          <p className="text-[10px] text-stone-500 mt-0.5 leading-snug">{heading.subtitle}</p>
        </div>
        <p className="text-[11px] text-stone-500">Map data is still loading — fields appear when lists sync.</p>
        {canOpenVe ? (
          <footer className="pt-2 border-t border-stone-800/80">
            <button
              type="button"
              onClick={onOpenInVisionExecution}
              className="text-[10px] text-stone-500 hover:text-stone-400 underline-offset-2 hover:underline decoration-stone-600"
            >
              Open in Vision &amp; Execution
            </button>
          </footer>
        ) : null}
      </div>
    )
  }

  const idea = ref.veType === 'idea' ? bundle.ideas.find((x) => x.id === ref.id) : null
  const ini = ref.veType === 'initiative' ? bundle.initiatives.find((x) => x.id === ref.id) : null
  const proj = ref.veType === 'project' ? bundle.projects.find((x) => x.id === ref.id) : null
  const task = ref.veType === 'task' ? bundle.tasks.find((x) => x.id === ref.id) : null

  const rowPresent =
    (ref.veType === 'idea' && idea) ||
    (ref.veType === 'initiative' && ini) ||
    (ref.veType === 'project' && proj) ||
    (ref.veType === 'task' && task)
  if (!rowPresent) {
    return (
      <div className="rounded-lg border border-stone-800 bg-stone-900/40 px-3 py-2.5 space-y-2">
        <p className="text-[11px] text-stone-500">
          No matching Vision &amp; Execution row in the current bundle for this selection.
        </p>
        {canOpenVe ? (
          <footer className="pt-2 border-t border-stone-800/80">
            <button
              type="button"
              onClick={onOpenInVisionExecution}
              className="text-[10px] text-stone-500 hover:text-stone-400 underline-offset-2 hover:underline decoration-stone-600"
            >
              Open in Vision &amp; Execution
            </button>
          </footer>
        ) : null}
      </div>
    )
  }

  let body: ReactNode = null

  if (section === 'water') {
    if (idea) {
      body = (
        <InspectorCollapsibleSection title="People & ownership" hint="Who created or is tied to this idea." defaultOpen>
          <FieldBlock label="Created by (id)">{idea.created_by || '—'}</FieldBlock>
          {idList('Linked people (ids)', idea.linked_people)}
        </InspectorCollapsibleSection>
      )
    } else if (ini) {
      body = (
        <>
          <InspectorCollapsibleSection title="Identity / scope" hint="Owner and status (same headings as Vision & Execution)." defaultOpen>
            <FieldBlock label="Owner id">{ini.owner_id || '—'}</FieldBlock>
            <FieldBlock label="Status">{ini.status || '—'}</FieldBlock>
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Resourcing reality" hint="Seats, dependencies, and capacity signals — read-only here." defaultOpen={false}>
            {(ini.seats?.length ?? 0) > 0 ? (
              <div className="space-y-1.5">
                <div className="text-[10px] uppercase tracking-wide text-stone-500">Seats (role · person · effort)</div>
                <ul className="text-[11px] text-stone-300 space-y-1 font-mono">
                  {(ini.seats ?? []).map((s, i) => (
                    <li key={`${s.role}-${i}`} className="border-l border-stone-700 pl-2">
                      {s.role || 'Role'} · {s.assigned_person_id || 'unassigned'} · {s.estimated_effort || '—'}
                      {s.notes?.trim() ? (
                        <span className="block text-stone-500 font-sans mt-0.5">{s.notes.trim()}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <FieldBlock label="Seats">—</FieldBlock>
            )}
            <FieldBlock label="Dependencies">{ini.dependencies}</FieldBlock>
          </InspectorCollapsibleSection>
        </>
      )
    } else if (proj) {
      body = (
        <>
          <InspectorCollapsibleSection title="Ownership" hint="Who carries the project and who backs them up." defaultOpen>
            <FieldBlock label="Owner id">{proj.owner_id || '—'}</FieldBlock>
            {idList('Supporting owner ids', proj.supporting_owner_ids)}
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Capacity" hint="Rough weekly load signal for this project." defaultOpen={false}>
            <FieldBlock label="Est. weekly hours">{proj.estimated_weekly_hours != null ? String(proj.estimated_weekly_hours) : '—'}</FieldBlock>
          </InspectorCollapsibleSection>
        </>
      )
    } else if (task) {
      body = (
        <>
          <InspectorCollapsibleSection title="Assignment" hint="Who is responsible and when it is due." defaultOpen>
            <FieldBlock label="Assignee id">{task.assignee_id || '—'}</FieldBlock>
            <FieldBlock label="Due date">{task.due_date || '—'}</FieldBlock>
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Effort" hint="Estimated work on this task." defaultOpen={false}>
            <FieldBlock label="Estimated hours">{task.estimated_hours != null ? String(task.estimated_hours) : '—'}</FieldBlock>
          </InspectorCollapsibleSection>
        </>
      )
    }
  } else if (section === 'soil') {
    if (idea) {
      body = (
        <>
          <InspectorCollapsibleSection title="Overview" hint="How this idea is summarized and described." defaultOpen>
            <FieldBlock label="Summary">{idea.summary}</FieldBlock>
            <FieldBlock label="Description">{idea.description}</FieldBlock>
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Status & tags" hint="Lifecycle and loose labels." defaultOpen={false}>
            <FieldBlock label="Status">{idea.status}</FieldBlock>
            <FieldBlock label="Tags">{(idea.tags ?? []).join(', ') || '—'}</FieldBlock>
          </InspectorCollapsibleSection>
        </>
      )
    } else if (ini) {
      const linkedProjects = bundle.projects.filter((p) => p.initiative_id === ini.id)
      const sourceIdea = ini.source_idea_id ? bundle.ideas.find((x) => x.id === ini.source_idea_id) : null
      body = (
        <>
          <InspectorCollapsibleSection title="Identity / scope" hint="Title, brief, lineage — mirrors Vision & Execution initiative panel." defaultOpen>
            <FieldBlock label="Title">{ini.title}</FieldBlock>
            <FieldBlock label="Brief">{ini.brief}</FieldBlock>
            <FieldBlock label="Source idea">
              {sourceIdea
                ? `${sourceIdea.title || sourceIdea.id} (${ini.source_idea_id})`
                : ini.source_idea_id || '—'}
            </FieldBlock>
            {linkedProjects.length > 0 ? (
              <FieldBlock label="Linked projects">{linkedProjects.map((p) => p.title || p.id).join(', ')}</FieldBlock>
            ) : (
              <FieldBlock label="Linked projects">—</FieldBlock>
            )}
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Decision / Summary" hint="Evaluation-shaped fields; checklist steps live under Fruit → Execution." defaultOpen={false}>
            <FieldBlock label="Recommendation">{ini.recommendation}</FieldBlock>
            <FieldBlock label="Next step (AI / draft)">{ini.next_step_ai}</FieldBlock>
            <FieldBlock label="Estimated cost (AI)">{ini.estimated_cost_ai}</FieldBlock>
            <FieldBlock label="Estimated timeframe (AI)">{ini.estimated_timeframe_ai}</FieldBlock>
            <FieldBlock label="Strategic alignment (AI)">{ini.philosophical_alignment_ai}</FieldBlock>
            {(ini.weightedScore != null || ini.approvalReady != null) && (
              <div className="text-[10px] text-stone-500 space-y-0.5 pt-1 border-t border-stone-800/60">
                {ini.weightedScore != null && (
                  <p>
                    Weighted score: <span className="text-stone-300">{ini.weightedScore}</span>
                  </p>
                )}
                {ini.approvalReady != null && (
                  <p>
                    Approval ready: <span className="text-stone-300">{ini.approvalReady ? 'Yes' : 'No'}</span>
                  </p>
                )}
              </div>
            )}
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Risks / admin" hint="Same section as Vision & Execution — read-only on the map." defaultOpen={false}>
            <FieldBlock label="Risks">{ini.risks}</FieldBlock>
            <FieldBlock label="Kill criteria">{ini.kill_criteria}</FieldBlock>
            <FieldBlock label="Diagnostics / admin notes">{ini.notes}</FieldBlock>
          </InspectorCollapsibleSection>
        </>
      )
    } else if (proj) {
      body = (
        <>
          <InspectorCollapsibleSection title="Definition" hint="What this project is and how long it runs." defaultOpen>
            <FieldBlock label="Brief">{proj.brief}</FieldBlock>
            <FieldBlock label="Start / end">{[proj.start_date, proj.end_date].filter(Boolean).join(' → ') || '—'}</FieldBlock>
            <FieldBlock label="Status">{proj.status}</FieldBlock>
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Working context" hint="Notes and draft next step — still grounding, not a shipped artifact." defaultOpen={false}>
            <FieldBlock label="Notes">{proj.notes}</FieldBlock>
            <FieldBlock label="Next step (AI / draft)">{proj.next_step_ai}</FieldBlock>
          </InspectorCollapsibleSection>
        </>
      )
    } else if (task) {
      body = (
        <>
          <InspectorCollapsibleSection title="What this task is" hint="Description and how you know it is done." defaultOpen>
            <FieldBlock label="Description">{task.description}</FieldBlock>
            <FieldBlock label="Completion criteria">{task.completion_criteria}</FieldBlock>
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Execution context" hint="Status, priority, and upstream task links." defaultOpen={false}>
            <FieldBlock label="Status">{task.status}</FieldBlock>
            <FieldBlock label="Priority">{task.priority}</FieldBlock>
            {idList('Dependency task ids', task.dependency_ids)}
            <FieldBlock label="Notes">{task.notes}</FieldBlock>
          </InspectorCollapsibleSection>
        </>
      )
    }
  } else {
    /* fruit */
    if (idea) {
      body = (
        <>
          <InspectorCollapsibleSection title="Intended impact" hint="The outcome this idea is aiming toward." defaultOpen>
            <FieldBlock label="Desired outcome">{idea.desired_outcome}</FieldBlock>
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Artifacts" hint="Assets already tied to this idea." defaultOpen={false}>
            {idList('Linked asset ids', idea.linked_assets)}
          </InspectorCollapsibleSection>
        </>
      )
    } else if (ini) {
      const steps = initiativeExecutionSteps ?? null
      const loadingSteps = initiativeExecutionStepsLoading === true
      body = (
        <>
          <InspectorCollapsibleSection title="Execution" hint="Checklist rows are canonical in Vision & Execution — same data, read-only here." defaultOpen>
            <p className="text-[10px] text-stone-600 leading-snug">
              Rows save immediately when edited in Vision &amp; Execution. Use{' '}
              {canOpenVe ? (
                <button
                  type="button"
                  onClick={onOpenInVisionExecution}
                  className="text-stone-400 hover:text-stone-300 underline-offset-2 hover:underline"
                >
                  Open in Vision &amp; Execution
                </button>
              ) : (
                'Vision & Execution'
              )}{' '}
              to add, complete, or reorder steps.
            </p>
            {loadingSteps ? (
              <p className="text-[11px] text-stone-500">Loading steps…</p>
            ) : steps && steps.length > 0 ? (
              <ul className="space-y-2">
                {steps.map((step) => (
                  <li
                    key={step.id}
                    className={`rounded border border-stone-800/90 bg-stone-950/40 px-2 py-1.5 text-[11px] ${step.is_done ? 'opacity-70' : ''}`}
                  >
                    <span className={step.is_done ? 'line-through text-stone-500' : 'text-stone-200'}>{step.title}</span>
                    <span className="block text-[10px] text-stone-600 mt-0.5">
                      {step.is_done ? 'Done' : 'Open'} · {step.source}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[11px] text-stone-500">
                No steps yet. Add steps in Vision &amp; Execution (or run evaluation / import legacy text there).
              </p>
            )}
            {canOpenVe ? (
              <button
                type="button"
                onClick={onOpenInVisionExecution}
                className="mt-1 px-2 py-1.5 rounded border border-dashed border-stone-600 text-stone-400 text-[11px] hover:border-stone-500 hover:bg-stone-800/40 w-full text-left"
              >
                + Add step…
              </button>
            ) : null}
          </InspectorCollapsibleSection>
          <InspectorCollapsibleSection title="Resourcing reality" hint="Required assets (same section family as Vision & Execution)." defaultOpen={false}>
            {idList('Required assets (ids)', ini.required_assets)}
          </InspectorCollapsibleSection>
        </>
      )
    } else if (proj) {
      body = (
        <>
          <InspectorCollapsibleSection title="Outputs" hint="Project brief plus required assets." defaultOpen>
            <FieldBlock label="Brief">{proj.brief}</FieldBlock>
            {idList('Required asset ids', proj.required_assets)}
          </InspectorCollapsibleSection>
        </>
      )
    } else if (task) {
      body = (
        <InspectorCollapsibleSection title="Artifacts" hint="Assets this task depends on; criteria and notes stay under Soil." defaultOpen>
          {idList('Required asset ids', task.required_asset_ids)}
        </InspectorCollapsibleSection>
      )
    }
  }

  if (selected.ref.veType === 'outcome') {
    body = (
      <div className="space-y-3">
        <p className="text-[10px] text-stone-500 border-b border-stone-800 pb-2 leading-snug">
          Outcome on the map — inspecting the linked project row. Label:{' '}
          <span className="text-stone-400">{selected.label}</span>
        </p>
        {body}
      </div>
    )
  }

  if (body === null) {
    body = <p className="text-[11px] text-stone-500">No fields for this section on this row type.</p>
  }

  const inspectKey = `${selected.ref.veType}-${selected.ref.id}-${section}`

  return (
    <div
      data-testid="map-triad-inspector"
      data-section={section}
      className="rounded-lg border border-stone-800 bg-stone-900/50 px-3 py-2.5 space-y-3"
    >
      <div>
        <div className="text-[11px] font-semibold text-stone-200">{heading.title}</div>
        <p className="text-[10px] text-stone-500 mt-0.5 leading-snug">{heading.subtitle}</p>
      </div>
      <div key={inspectKey}>{body}</div>
      <p className="text-[9px] text-stone-600 leading-snug pt-1 border-t border-stone-800/80">
        Meeting capture and other ingest flows update these fields over time in Vision &amp; Execution — use the left chat to work
        through changes; nothing here auto-saves.
      </p>
      {canOpenVe ? (
        <div className="pt-0.5">
          <button
            type="button"
            onClick={onOpenInVisionExecution}
            className="text-[10px] text-stone-500 hover:text-stone-400 underline-offset-2 hover:underline decoration-stone-600"
          >
            Open in Vision &amp; Execution
          </button>
        </div>
      ) : null}
    </div>
  )
}

export const MapTriadInspectorContent = memo(MapTriadInspectorContentImpl)
