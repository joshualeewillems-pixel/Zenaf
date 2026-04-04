# Project & Task detail panels — UI cleanup plan (Initiative-aligned)



**Goal:** Apply the same **design philosophy** as the refreshed Initiative panel (execution-centered, clearer hierarchy, less always-on clutter, safer destructive actions) **without** collapsing initiative / project / task into one template.



| Level | Role in UI |

|-------|------------|

| **Initiative** | Broadest — strategy, decision/evaluation, execution checklist, resourcing narrative |

| **Project** | Coordination container — cadence, ownership, **Brief (scope & outcomes)**, priority 1–5, task lens; **Suggested work (AI)** reserved (mediation) |

| **Task** | Sharpest unit — title, state, who/when, done-ness, minimal deps |



**Constraints:** Incremental edits inside existing panels; no ontology merge; no broad rewrite.



---



## Shipped UI (current truth) — Vision Execution detail panels



All three panels live in **`frontend/src/vision-execution/VisionExecutionView.tsx`** (`InitiativeDetailPanel`, `ProjectDetailPanel`, `TaskDetailPanel`).



### Summary / hero strip (aligned)



| Panel | First row | Second row | Third row |

|-------|-----------|------------|-----------|

| **Initiative** | Decision / recommendation chip (or “Decision pending”) | `readiness · {synthesis sentence}` | `Next: {content}` |

| **Project** | Status chip + owner (+ supporting count) | `Next: {first open task \| current_focus \| legacy AI \| fallback}` | `readiness · {synthesis}` (or green synthesis when high) |

| **Task** | Status chip + `readiness · {synthesis}` (or green when high) | — | — |



- Shared tokens: **`p-2.5`**, **`text-[11px]`** for secondary lines, **`Next:`** label only in Initiative + Project (Task has no separate “Next” line; execution is **Done** / status).

- **Project** hero **does not** repeat weekly hours (that field lives under **Plan & cadence**).

- **Project** “Next” priority (UI only): **first non-Done/non-Dropped task title** → **`next_step_ai`** (via `nextStepsPrimaryLine`, labeled *Earlier suggestion (AI)* in form) → quiet fallback string. **Deliverables** are edited inside **Brief**; legacy `deliverables` / `current_focus` / `complexity` columns are cleared on save (no API schema change).



### Footer (aligned)



| Panel | Order | Overflow **⋯** |

|-------|--------|------------------|

| **Initiative** | **Save** (primary) → **Cancel** (outline) → **⋯** | **Mark killed…**, **Delete…** |

| **Project** | **Save** → **Cancel** → **⋯** | **Archive (Park)…**, **Delete…** |

| **Task** | **Done** / **Reopen** → **Save** → **Cancel** → **⋯** | **Drop task…**, **Delete…** |



- **Save** uses **`font-medium`** where primary (Initiative, Project); Task **Save** stays secondary gray with **`font-medium`** for weight parity.

- Overflow menus use **`bottom-full`**, **`data-*-footer-overflow-root`**, and document **mousedown** (capture) to close — same pattern for all three.



### Hints above collapsed sections



- One-line **`text-[11px] text-slate-500`** hints use a consistent voice (short clauses, **em dash** or period where natural): e.g. Task **Dependencies**, **Completion criteria**; Project **Earlier suggestion (AI)**, **Radar**. Mediation direction: **`docs/02_ACTIVE_DESIGN/MEDIATION_EXECUTION_DIRECTION.md`**.

- **Metadata / debug** remains collapsed by default via shared **`MetadataSection`**.



### Initiative rename



- Section title **Identity / scope** (slash, not `&`) for parity with Project.



---



## 1. Project panel



### Keep (core value)

- **Summary strip** (status, owner, one-line “what’s next”) — **execution** language; tasks first, then earlier AI suggestion text.

- **Identity / scope:** title, **Brief (scope & outcomes)** — includes former deliverables (merged on load), status, initiative link.

- **Ownership:** primary owner + supporting owners — **Plan & cadence**.

- **Plan & cadence:** **Priority 1–5** slider (persisted as numeric string), dates, weekly hours; placeholder note for **Suggested work (AI)** (mediation — see `docs/02_ACTIVE_DESIGN/MEDIATION_EXECUTION_DIRECTION.md`). **No** complexity / separate deliverables / current_focus fields in UI.

- **Tasks in this project** — **always-on block** directly under hero; empty state explains how to add tasks.

- **Metadata** — collapsed by default (shared component).



### Merge (done)

- **“Execution summary”** + **“Deliverables / focus”** + **Owners** → **Plan & cadence**.



### Demote (done)

- Legacy **`next_step_ai`** → hint + **Earlier suggestion (AI)** (collapsed).

- **Derived / radar** → hint + **Radar (read-only)** (collapsed) when data exists.



### Make execution more prominent (done)

- **Tasks** block moved **up** under summary.



### Future

- **Suggested work (AI)** (mediation) on the project panel — not a clone of initiative checklist rows.

- Optional: **project `execution_steps`** UI if product chooses rows over suggestion objects.



---



## 2. Task panel



### Keep (done)

- Single **Task** section: title, description, assignee/due grid, priority/hours, status + hint pointing to **Done**.

- **Dependencies**, **Completion criteria**, **Notes** collapsed by default where applicable.

- **Done** / **Reopen** primary; **Drop** / **Delete** in **⋯**.



---



## 3. Ported interaction patterns (from Initiative)



| Pattern | Initiative | Project | Task |

|--------|------------|---------|------|

| **Overflow for destructive** | **Mark killed** + **Delete** → ⋯ | **Archive** + **Delete** → ⋯ | **Drop** + **Delete** → ⋯ |

| **Primary actions** | **Save** | **Save** | **Done** then **Save** |

| **Cleaner empty states** | Linked projects line | No tasks | No deps / criteria hints |



---



## 4. Explicit deletions / merges (by name)



**Project** — merged/demoted as in §1 **Shipped UI**.



**Task** — merged **Action** + **Assignment** into **Task**; footer destructive → overflow.



---



## 5. Phase order (implementation)



1. **Task** — done.  

2. **Project** — done.  

3. **Polish / coherence** — **done** (shared hero density, `Next:` wording, footer + overflow, hint copy, docs).



---



## Out of scope (for this plan)



- New radar/derived engines  

- Promoting execution steps to tasks  

- Global design system or new component library  

- Making Project/Task detail **identical** to Initiative layout

