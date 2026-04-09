# AI action substrate — traces, routing, and outcomes (product-wide)

**Status:** Design direction + **partial client implementation** (`frontend/src/ai-actions/`).  
**Principle:** This is **not** a Vision & Execution–only pattern. VE is the **first surface** that emits traces and uses shared result UI; the **names and schema** apply across Perspectives, Team, Workspace Organizer, Content, Intake, and Settings.

---

## 1. System-wide AI action model

### 1.1 Surfaces (`ZenafSurface`)

Where the user invoked the action (analytics, routing defaults, UX context):

| Value | Typical AI work |
|--------|------------------|
| `vision_execution` | Entity panels, context bar, evaluations, project suggestions |
| `meeting_extraction` | Meeting capture extract → staging (`suggestion_batch` traces; VE tab UI) |
| `perspectives` | Perspective agents, lenses, council-adjacent assists |
| `team` | People & capacity, assignment hints, capacity copy |
| `workspace_organizer` | Folder analyze / recommend / council modes |
| `content` | Briefs, generation, transcript handoff |
| `intake` | Classification, lane correction, bridge |
| `settings` | LLM test, optional guided setup |

Surfaces are **not** entity types; they answer “which product area started this run?”

### 1.2 Action kinds (`AiActionKind`) — universal verbs

Stable across all surfaces (extend over time):

| Kind | Meaning |
|------|---------|
| `field_text_rewrite` | User-focused field or control; replace text with model output (same semantic contract everywhere). |
| `suggestion_batch` | One-to-many suggestions (checklist, bullets); user may acknowledge, dismiss, or copy — not always “apply to single field”. |
| `structured_evaluation` | Model returns a structured or multi-field assessment (initiative evaluate, idea evaluate, future “score this brief”). |

**Do not** encode surface names inside `action_kind`. Use **`surface` + `subject_type`** for locality.

### `action_kind` vs `action_intent`

- **`action_kind`** — Coarse **routing / review family** (the small closed `AiActionKind` union: how we bucket risk, UI patterns, and default policies).
- **`action_intent`** — Finer **pipeline / template identity**: optional `string | null`, **lowercase `snake_case`**, **not** a second TypeScript enum. Use it to distinguish implementations under the same kind (e.g. `idea_evaluate` vs `initiative_evaluate` under `structured_evaluation`). Add new intent strings as flows gain traces; keep the union of kinds stable until a kind truly splits.

**Model/provider routing:** Prefer resolving **provider, model, and fallback chain** from **`surface` + `action_kind` + `action_intent`** plus user prefs via a **single policy resolver** — not per-feature provider logic. See **`AI_EXECUTION_POLICY_ROUTING.md`**.

### 1.3 Subject (target of the action)

- **`subject_type`**: string, product-defined (`initiative`, `idea`, `project`, `task`, `content_brief`, `perspective_agent`, `person`, `workspace_job`, …).
- **`subject_id`**: string id for that subject.
- **`field_key`**: optional; `null` when the action is not bound to a single field (e.g. whole-subject evaluation).

This avoids VE-only `entity_type` naming in the **trace** while VE panels can still map their forms to the same fields.

### 1.4 Trace record (`AiActionTrace`) — client shape today

In-memory ring buffer; future DB row should align with this:

| Field | Purpose |
|--------|---------|
| `trace_id` | UUID |
| `surface` | `ZenafSurface` |
| `action_kind` | `AiActionKind` |
| `action_intent` | Optional finer intent (`snake_case` string); see above |
| `subject_type` / `subject_id` | What was targeted |
| `field_key` | Optional field scope |
| `input_snapshot` | Bounded text or route label — **never** full prompt |
| `model_used` | Nullable until resolver exposes id client-side |
| `prompt_version` | Logical template version (`field_text_rewrite_body_v1`, `ve_initiative_evaluate_v1`, …) |
| `output` | Primary deliverable or compact JSON summary |
| `user_outcome` | `applied` \| `dismissed` \| `edited` \| `copied` \| `none` |
| `created_at` | ISO timestamp |

**Not stored:** raw chain-of-thought, full prompts (unless a separate retention policy exists).

### 1.5 Result flow (product-wide)

For any action that returns user-visible model output:

1. **Show result** (read-only or editable preview).
2. **Apply** — commit into app state or subject (field apply, accept suggestions, etc.).
3. **Dismiss** — discard without commit; trace `user_outcome: dismissed`.
4. **Copy** (optional) — clipboard; may set `copied` when you want that signal.

Shared UI: **`AiActionResultPanel`** (`frontend/src/ai-actions/AiActionResultPanel.tsx`) — not VE-specific; VE uses it first.

---

## 2. Universal vs VE-specific

| Universal | VE-specific (today) |
|-----------|---------------------|
| `AiActionTrace`, `ZenafSurface`, `AiActionKind`, outcome enum | `VeFocusRegion`, `/vision-execution/...` routes, `ZENAF_VE_FOCUS_APPLY_REWRITE` event |
| `field_text_rewrite` + Apply/Dismiss/Copy pattern | Which fields are wrapped, `fieldCapabilityRegistry`, focus bar placement |
| `suggestion_batch` | Project “Suggested work (AI)” payload and checklist UX |
| `structured_evaluation` | Initiative/idea evaluate endpoints and proposal UI |
| `prompt_version` naming convention | Concrete strings like `ve_initiative_evaluate_v1` (prefix documents first consumer) |
| Routing by risk / action kind | Which VE routes call which adapter tier (future) |

Backend **task** names (e.g. `vision_focus_rewrite`) may stay implementation-specific; **trace `prompt_version`** should stay comparable across surfaces.

---

## 3. VE-first rollout plan (implementation)

1. **Done (pilot):** `frontend/src/ai-actions/` — trace types, ring sink, `AiActionResultPanel`, VE hooks for field rewrite, suggestion batch, structured evaluation (compact output only).
2. **Next:** Return `trace_id` from server on AI routes when traces persist; correlate client outcome to server row.
3. **Then:** Wire **Perspectives** or **Content** to `createAiActionTrace` + same panel (reuse `surface: 'perspectives' | 'content'`).
4. **Later:** Central routing table keyed by `(action_kind, surface, subject_type)` → `routing_tier`.

---

## 4. Future examples (same model)

### Perspectives (`surface: perspectives`)

- **Kind:** `field_text_rewrite` — refine a perspective **mission** or **system prompt** snippet.  
- **Subject:** `subject_type: 'perspective_agent'`, `subject_id: <agentId>`, `field_key: 'instructions'`.  
- **Outcome:** Apply writes local/agent store; Dismiss clears preview.

### Team / People & capacity (`surface: team`)

- **Kind:** `field_text_rewrite` — polish **strengths** or **availability** narrative on a person.  
- **Subject:** `subject_type: 'person'`, `field_key: 'strengths'`.  
- **Kind (later):** `suggestion_batch` — “overcapacity mitigations” list.

### Workspace Organizer (`surface: workspace_organizer`)

- **Kind:** `structured_evaluation` — analyze folder → structured summary + recommended modes.  
- **Subject:** `subject_type: 'workspace_job'`, `subject_id: <runId or path hash>`, `field_key: null`.  
- **Kind:** `suggestion_batch` — ranked actions (move, rename, tag).

### Content (`surface: content`)

- **Kind:** `field_text_rewrite` — brief **thesis** or **audience** line.  
- **Subject:** `subject_type: 'content_brief'`, `field_key: 'body'`.  
- **Kind:** `suggestion_batch` — outline bullets for script/newsletter.

---

## 5. Naming refactors already applied (avoid later churn)

| Avoid (VE-only) | Prefer (product-wide) |
|-----------------|-------------------------|
| `focus_rewrite` as trace `action_kind` | `field_text_rewrite` |
| `project_suggested_work` as kind | `suggestion_batch` (VE project flow is one instance) |
| `idea_evaluate` / `initiative_evaluate` as separate kinds | `structured_evaluation` + `subject_type` |
| `entity_type` / `entity_id` on trace | `subject_type` / `subject_id` |
| `VeAiActionTrace`, `pushVeAiTrace` | `AiActionTrace`, `pushAiActionTrace` |
| Module under `vision-execution/ai-actions/` only | **`frontend/src/ai-actions/`** as shared home |

**Prompt versions:** Prefer `ve_*` **suffix or prefix** only to tag the first implementing route (e.g. `ve_initiative_evaluate_v1`), not the whole identifier, so Content can add `content_brief_rewrite_v1` beside the same `action_kind`.

---

## 6. Routing (recap)

Prefer **lighter models** for low-risk `field_text_rewrite` on short text; **heavier** for `structured_evaluation` and long-context `suggestion_batch`. Policy keys: **`action_kind`**, **`surface`**, **input length bucket**, not “always largest model.”

---

## 7. Boundaries

| In scope | Out of scope |
|----------|----------------|
| Stable trace shape + outcomes | Raw CoT storage |
| In-memory / future DB row | Full telemetry platform |
| Per–action-kind routing intent | Auto global model escalation |

---

## Summary

- **One product-wide substrate:** `surface` + `action_kind` + `subject_*` + optional `field_key` + outcome.  
- **VE implements first** but **does not own** the vocabulary.  
- **Code:** `frontend/src/ai-actions/` holds shared types, trace sink, and `AiActionResultPanel`; Vision & Execution imports from there.

*See also: `docs/02_ACTIVE_DESIGN/CONTEXT_ACTION_BAR_DESIGN.md` (VE focus UX); this doc is the cross-product contract.*
