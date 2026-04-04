# Context Action Bar (top system bar) — design note

**Status:** Phase 1 + cockpit extensions **implemented** (2026-03); design intent below remains the contract for new fields.  
**As-built truth:** `../01_TRUTH/ACTIVE_VS_PLANNED.md`, `../01_TRUTH/SYSTEM_REFERENCE.md` (Part II §2.3, Part IV, Part V §5.7).  
**Aligns with:** `../MEDIATION_OPERATIONAL_NOTE.md` (mediation quality bar on outputs), `../01_TRUTH/CODEBASE_TRUTH_RULES.md` (VE branch, no second trunk), `./VISION_EXECUTION_DESIGN.md`

---

## 1. Purpose of the top bar

**Role:** A **system-level Focus Context / Context Action Bar** — not a generic “AI anywhere” menu.

- **Focus representation:** The bar shows **what the user is attending to** in structured form: entity, field, and (when useful) short lineage. This replaces vague states like “No folder” when the user is actually inside Vision Execution with a real focus — or keeps a **quiet idle** state when focus is not actionable.
- **Action exposure:** Actions appear as **a small, labeled set of buttons or a compact menu** derived from a **declared capability map**, not from open-ended “ask AI anything.” Only **allowed action families** for the current `(entity, field)` are shown; everything else is omitted.

**Why not a generic right-click AI menu:** Right-click tends toward **one huge catalog** and **same actions everywhere**. The top bar can enforce **semantic relevance** and **mediation-friendly** outputs (clarify, surface tensions, support a human-owned next move) per field.

---

## 2. Focus model (minimal)

The app should track a single **optional** `FocusContext` (or push/pop stack later; Phase 1: single focus).

| Concept | Required Phase 1 | Notes |
|--------|------------------|--------|
| `entity_type` | yes | e.g. `initiative`, `project`, `idea`, `task` (Phase 1: VE entities only) |
| `entity_id` | yes | Stable server id |
| `field_key` | yes | Stable machine key, e.g. `strategic_summary`, `dependencies_text` |
| `field_label` | yes | Human string for the bar, e.g. “Strategic summary” |
| `parent` | optional | `{ type, id }` or minimal `lineage: string[]` for disambiguation in the bar |
| `surface` | optional | e.g. `vision_execution` — scopes registry and telemetry |

**Blur / idle:** When no registered field has focus, `FocusContext` is **null** or **`{ idle: true }`** with no field key (see §6).

### 2.1 Graph slice (resolved focus context) — not a field whitelist

**Intent:** “Focus context” for mediation, council, and future tools is the **neighborhood of the system graph** around the current pointer, not a curated list of field names.

- **`FocusContextCore`** — debounced pointer: `entity_type`, `entity_id`, `field_key`, labels, optional `parent` / `lineage_labels` (same as before).
- **`resolveGraphSlice(focus, veGraphData)`** — pure helper (`frontend/src/vision-execution/focus/graphSliceResolver.ts`) that returns **`graphSlice`**: anchor node, **`nodes`** map (each node’s **`data`** is the **full entity row** as `Record<string, unknown>`), **relationships** (parent / children / linked / matched), **`edges`**, and optional **`system`** (interpretation, matchConfidence, consolidationMeta, sourceExcerpt, segment ids, etc. when present on the row).
- **VE data** is published from **`VisionExecutionView`** via **`VisionExecutionGraphDataProvider`** (lists: core profiles, ideas, initiatives, projects, tasks, persons, assets, capacity profiles). No per-field schema in the resolver: **if a field exists on the API object, it is in `node.data`.**
- **`fieldCapabilityRegistry`** remains only for **which actions appear** in the bar — not for what data is visible in the graph slice.

**Council:** `council_preflight.ve_focus_graph` carries the resolved **`graphSlice`** when focus is set (in addition to the compact `ve_focus` line).

---

## 3. Relevance model (capability map, not freeform AI)

**Principle:** Relevance is **data-driven and enumerable**: a **field capability map** (and optionally entity-level defaults), not LLM-chosen menus.

- **Registry:** For each supported `(entity_type, field_key)` (or `field_key` with entity default), define **`allowed_action_ids: ActionId[]`** — a **small** list from a **fixed enum** of action families (§5).
- **Field “kinds” (optional layer):** Group fields by `field_kind` (e.g. `long_form_strategy`, `title`, `dependencies`, `evaluation`, `execution_steps`) and attach **default** `allowed_action_ids` to the kind. Specific fields **override** defaults when needed. This avoids duplicating rules for every textarea.
- **Trivial fields:** If `allowed_action_ids` is **empty**, the bar shows **context only** (optional) or **hides actions** entirely — e.g. task **title** does not get “summarize for council.”
- **Evolving without a giant system:** Add rows to the map incrementally; **version** the registry file or export a JSON snapshot. New actions = **new enum members** + **opt-in** on specific fields/kinds. Deprecation = remove from map first, then from enum. No automatic “enable all actions on all fields.”

---

## 4. Phase 1 scope (small) — original bar; extensions shipped

**Original Phase 1 (still the rule for new fields):**

- **Focus source:** **Explicitly focused fields only** — inputs/textareas that **register** on focus and **clear** on blur (debounced), via **`VeFocusRegion`** or an equivalent pattern (e.g. council textarea wrapper).
- **Bar behavior:** **Context line** + **only actions allowed** for that field (from **`fieldCapabilityRegistry`**); no global catalog.
- **Not automatic:** Unregistered fields do not get actions or voice targeting.

**Extensions now in the codebase:**

- **Universal header strip** (`App.tsx` `UniversalContextStrip`): visible across primary cockpit views; when there is no VE field focus and the user is not on Vision → Execution, optional **Where** crumbs (workspace topic, etc.).
- **Voice-to-field:** Single **record** control (**`FocusContextRecordButton`**) — circle when idle with focus, square while recording; **`POST /api/transcribe`** then insert at captured selection; **`VeVoiceRecordingProvider`** + **`VisionExecutionFocusProvider`**.
- **Vision Execution:** Detail panels + inline **create** forms for idea / initiative / project / task use **`VeFocusRegion`** and synthetic **`__ve_new_*__`** ids; registry includes initiative/project **title** and project **brief** where needed.
- **Workspace council:** **Your reply** registers **`council` / `__council_reply__` / `reply`** so the strip shows focus and voice targets the chat field; **`ATRIA_VOICE_TRANSCRIPT_DOM_FIRST`** (cancelable) consumes transcripts before the generic VE insert event when the textarea is active.
- **Still out of scope:** Settings, file tree, native context menus, registering every possible input in the app, dependency-engine automation.

---

## 5. Action families (starter set, semantically gated)

Shared **enum** of **action ids** (names illustrative; implement as stable strings):

| Action id | Typical fit | Avoid on |
|-----------|----------------|----------|
| `rewrite` | Long-form narrative fields where tone/clarity matters | Bare titles, single-line labels |
| `distill` | Dense prose, long summaries | Empty or trivially short fields |
| `expand_to_steps` | Strategic summary, problem framing, “what next” blobs | Task title, status pickers |
| `extract_constraints` | Strategy, dependencies, scope descriptions | Titles |
| `surface_tensions` | Strategic / stakeholder / tradeoff-heavy text | Mechanical fields |
| `compare_with_evaluation` | Where formal evaluation / scores exist alongside narrative | Fields with no evaluation artifact |
| `summarize_for_council` | Strategic summary, exec-level blurbs | Task title, ids, dates |
| `convert_to_task` | Explicit “next step” or execution-oriented text (if/when policy allows) | Strategic-only fields unless product explicitly allows |

**Rule:** Each field’s map lists **only** ids that pass a **semantic + product** check. Council-style actions require **field kind** and **content policy** (mediation: outputs must be actionable, auditable, disagreeable — see `MEDIATION_REVIEW_CHECKLIST.md`).

---

## 6. UI behavior

- **Nothing meaningful focused:** Show a **quiet idle** state — e.g. “No focus” or app-level context only (folder/workspace if desired). **Do not** show a row of AI buttons.
- **Field focus:** After a **short debounce** (e.g. 100–200ms), update the bar to **entity + field label** (+ optional lineage snippet). Render **only allowed actions** (max **N** visible, e.g. 4–6; overflow → single “More” with same filtered list — still not a giant catalog).
- **Blur:** Debounce clearing focus so **clicking an action** on the bar does not drop context before the handler runs. If focus moves to another registered field, **replace** context once (same debounce rules).
- **Noise control:** No flashing on every keystroke; bar binds to **focus**, not **every input event**. Optional: subtle transition (opacity) rather than layout swap.

---

## 7. Constraints

- **No browser native menu hacks** — no overriding `contextmenu` as the primary action surface; top bar remains the contract.
- **No giant action catalog** — actions come **only** from the registry for the current focus.
- **No all-fields support** — unregistered fields do not show actions.
- **No broad rewrite** of Vision Execution — register fields incrementally; reuse existing VE APIs and `VISION_EXECUTION_API` patterns (`docs/01_TRUTH/CODEBASE_TRUTH_RULES.md`).
- **Mediation doctrine:** Prompts and response shapes for each action family should favor **clarification, tensions, constraints, human-owned next moves** over false certainty (`../MEDIATION_OPERATIONAL_NOTE.md`).

---

## Appendix A — Minimal metadata: `FocusContext`

```typescript
/** Stable action keys; subset shown per field via FieldCapabilities */
type ActionId =
  | 'rewrite'
  | 'distill'
  | 'expand_to_steps'
  | 'extract_constraints'
  | 'surface_tensions'
  | 'compare_with_evaluation'
  | 'summarize_for_council'
  | 'convert_to_task'

type EntityType = 'idea' | 'initiative' | 'project' | 'task' // Phase 1: VE subset as implemented

interface FocusContext {
  surface: 'vision_execution'
  entity_type: EntityType
  entity_id: string
  field_key: string
  field_label: string
  /** Optional: parent entity for one-line breadcrumb */
  parent?: { entity_type: EntityType; entity_id: string; label?: string }
  /** Optional: precomputed breadcrumb strings */
  lineage_labels?: string[]
  /** For debounce / stale closure guards */
  focus_version?: number
}
```

When idle: `FocusContext | null` (null = no actionable field focus).

---

## Appendix B — Minimal metadata: field capabilities (registry entry)

```typescript
interface FieldCapabilities {
  /** Matches FocusContext.field_key */
  field_key: string
  entity_type: EntityType
  /** Ordered list; UI may truncate with "More" */
  allowed_actions: ActionId[]
  /** Optional: for analytics and prompt selection */
  field_kind?: string
  /** If true, bar may show only label, no actions (same as empty allowed_actions) */
  actions_hidden?: boolean
}

/** Registry: array or map keyed by `${entity_type}:${field_key}` */
type FieldCapabilityRegistry = Record<string, FieldCapabilities>
```

**Example entries (illustrative):**

- `initiative:strategic_summary` → `distill`, `surface_tensions`, `summarize_for_council`, `expand_to_steps`, `compare_with_evaluation`
- `initiative:dependencies_text` → `extract_constraints`, `surface_tensions`, `expand_to_steps` (owners/suggestions only if product allows)
- `task:title` → `[]` or omit from registry (trivial — bar shows context only, no actions)

---

## Appendix C — Implementation hint (Phase 1)

- Single React context or small store: `focusContext`, `setFocusFromField(el)`.
- Vision Execution field components call `registerFieldFocus` on focus/blur with `FocusContext` payload.
- Top bar subscribes and looks up `allowed_actions` from **static registry** + optional `field_kind` defaults.

No new global LLM router required for Phase 1 if each action maps to an existing or single new VE endpoint; keep **one branch**, not a second trunk.
