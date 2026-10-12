# Cockpit Progression & Council Refinement: Design Proposal

**Goal:** User-controlled workflow progression—one processor at a time by default, with explicit “what runs next” and optional use of previous result as context. No automatic chaining; everything visible and user-driven.

---

## 1. State Structure

### 1.1 Workflow state (frontend)

```ts
// Single source of truth for the session
interface WorkflowState {
  // Current focus: what the user is looking at / about to run
  activeMode: ModeId
  input: RunInput          // folder_path | question | query by mode

  // Step history: ordered list of completed runs (user can see and re-use)
  steps: Step[]

  // Optional: which step (if any) is selected as "context for next run"
  contextFromStepId: string | null

  // Pending: only one run in flight
  loading: boolean
  error: string | null
}

interface Step {
  id: string               // uuid or slug
  mode: ModeId
  input: RunInput           // snapshot of what was sent
  result: StepResult        // result + suggested next actions
  createdAt: number         // timestamp
}

interface RunInput {
  folder_path?: string
  question?: string
  query?: string
  // Council-specific (see §4)
  councilOptions?: CouncilRunOptions
}
```

- **Default:** User picks mode, fills input, runs → one new `Step` is appended; `steps` is the visible history.
- **Progression:** User picks a suggested “next action” from a step’s result card (or picks “Run [mode] with this as context”); that becomes the next run, with optional `contextFromStepId` so the API can receive “previous result” as context. No automatic follow-up run.
- **Single processor:** Only one `loading === true` at a time; no parallel runs.

### 1.2 What we don’t add (by design)

- No “pipeline” or fixed sequence.
- No automatic “after Analyze always run Recommend.”
- No hidden state: `steps`, `contextFromStepId`, and suggested next actions are all visible in the UI.

---

## 2. Result Card Structure

Each completed run is shown as a **result card** (one card per `Step`).

### 2.1 Step result (from API)

```ts
interface StepResult {
  // The actual payload (mode-specific)
  data: unknown

  // Optional: suggested next actions (user chooses one or ignores)
  suggestedNext?: SuggestedNextAction[]

  // Optional: short summary for use as context in next run (e.g. for council or next_step)
  contextSummary?: string
}

interface SuggestedNextAction {
  mode: ModeId
  label: string                    // e.g. "Recommend child folders"
  description?: string            // e.g. "Use this folder"
  useResultAsContext?: boolean     // if true, backend receives previous result as context
}
```

- **data:** Same as current API `result` (e.g. analyze dict, council text).
- **suggestedNext:** Defined per mode in the API/engine. Examples:
  - After **Analyze:** suggest `recommend`, `assess`, `simulate` with `useResultAsContext: true` (folder_path already known from the step).
  - After **Simulate:** suggest `assess` or **Council** with optional context.
  - After **Council** (without synthesis): suggest “Run synthesis” (same step, synthesis-only flag).
- **contextSummary:** Optional short text (e.g. “Folder X, 44 items, 28 unsorted”) so the next run (e.g. council or next_step) can receive a compact context block without sending the full payload.

### 2.2 Result card (UI)

- **Header:** Mode name, timestamp, input summary (e.g. folder path or question).
- **Body:** Rendered `data` (table, JSON, or formatted text by mode).
- **Footer (if `suggestedNext`):** List of buttons/chips: “Recommend”, “Assess uncertainty”, “Simulate”, “Council with this context”, etc. Click = set `activeMode`, optionally set `contextFromStepId` to this step, and optionally prefill input from the step. User still clicks **Run** to execute.
- Optional: “Use as context” checkbox or per-action “with context” so the user can choose whether the next run receives the previous result.

---

## 3. Next-Action Model

### 3.1 Who defines suggestions

- **Backend (recommended):** For each mode, the API returns `suggestedNext` in the same response (e.g. in `result.suggestedNext` or a top-level `suggestedNext`). Engine can be extended so that e.g. `analyze_file_steward_folder`’s response is wrapped with suggestions for recommend/assess/simulate for that folder.
- **Frontend (fallback):** If the API doesn’t send `suggestedNext`, the frontend can show a generic “Run another mode” list (all modes) with no “use as context” pre-checked.

### 3.2 What happens when the user picks a suggestion

1. **activeMode** is set to the suggested mode.
2. **input** is prefilled where possible (e.g. folder_path from the step’s input).
3. **contextFromStepId** is set to the step’s id if `useResultAsContext` is true (or user explicitly chooses “with context”).
4. User can edit input and click **Run**. On run, the API receives:
   - `mode`, `params` (folder_path / question / query),
   - optional `context_from_step`: step id or the previous result/summary (API resolves from id or receives a blob). Backend uses that only when building the next request (e.g. council context, or next_step context).

No automatic run; the user always triggers the next run with **Run**.

### 3.3 Context passed to the backend

- **Option A:** API accepts `context_from_step_id`; backend looks up the step (or the frontend sends the last step’s result in the request). Backend then passes that as `context` to e.g. `run_council(question, context=...)` or to a future “next_step” helper.
- **Option B:** Frontend sends `previous_result_summary` (and optionally `previous_result_full`) in the body so the API is stateless. Simpler for MVP.

For **smallest safe MVP**, Option B is enough: frontend sends a small text summary (or a reference) in the run request when the user chose “with context.”

---

## 4. Council Role Selection Model

Council becomes a configurable run: who responds, and whether synthesis is included.

### 4.1 Council run options (state + API)

```ts
interface CouncilRunOptions {
  // Who responds
  scope: 'full' | 'single' | 'selected'
  singleRole?: 'strategist' | 'operator' | 'analyst' | 'governance' | 'brand'
  selectedRoles?: ('strategist' | 'operator' | 'analyst' | 'governance' | 'brand')[]

  // Synthesis
  includeSynthesis: boolean   // if false, synthesis can be run later as a separate step
}
```

- **full:** All five roles + optional synthesis (current behavior).
- **single:** Only `singleRole` responds; no synthesis in that run.
- **selected:** Only `selectedRoles` respond; optional synthesis.

### 4.2 UI for council

- **Mode card “Council”** → when selected, the focus panel shows:
  - Question input (as now).
  - **Scope:** Radio or dropdown: “Full council”, “Single role”, “Selected roles”.
  - If “Single role”: dropdown to pick one (Strategist, Operator, Analyst, Governance, Brand).
  - If “Selected roles”: multi-select or checkboxes for the five roles.
  - **Synthesis:** Checkbox “Include synthesis now” (default true for “Full council”, false for single/selected if you want synthesis to be a separate step).
- **Result card** for council:
  - If synthesis was included: show role outputs + synthesis as today.
  - If not: show only role outputs; suggested next action can be “Run synthesis” (same question + previous role outputs, backend returns only synthesis).

### 4.3 Backend support (for later)

- **POST /run** with `mode: "council"` and `params: { question, context?, council_options?: { scope, single_role?, selected_roles?, include_synthesis } }`.
- Engine: extend `run_council` (or add a wrapper) to accept `scope`, `single_role`, `selected_roles`, `include_synthesis`; call the provider only for the requested roles and optionally add a synthesis step. No change to the existing `run_council(question, context)` signature until you implement this.

---

## 5. Smallest Safe MVP (Progression + Council UI Only)

Implement the **UI and state model** first; keep backend behavior as today (single run, no chaining, full council only).

### 5.1 State

- Add **steps: Step[]** to the cockpit state. Each run appends one step; each step has `id`, `mode`, `input`, `result: { data }` (no `suggestedNext` from API yet).
- Add **contextFromStepId: string | null**. Not sent to the API in MVP; just stored so the UI can show “Next run will use Step 2 as context” when you implement chaining later.

### 5.2 Result cards

- Replace the single “result” area with a **list of result cards** (one per step). Each card shows:
  - Mode, timestamp, input summary.
  - Result body (current JSON/text).
  - **Placeholder “Suggested next” section:** static list of buttons: “Recommend”, “Assess”, “Simulate”, “Council”, etc. On click: set active mode and prefill folder_path (or question) from that step; do **not** send context to the API yet. User clicks Run to run the next step.
- No `suggestedNext` from API in MVP; no “use as context” yet.

### 5.3 Council options (UI only)

- When **Council** is the active mode, show:
  - Question input.
  - **Scope:** Dropdown “Full council” (only option in MVP).
  - **Include synthesis:** Checkbox (default true). Not sent to the API in MVP; backend always does full council + synthesis. Later, the API can respect these options.

### 5.4 No automatic chaining

- “Suggested next” only changes the focus (mode + input); user must click Run. No automatic run after a step completes.

### 5.5 Deliverables (MVP)

- **State:** `steps: Step[]`, `contextFromStepId`, and (optional) `councilOptions` in state.
- **UI:** Step history as result cards; placeholder “Run next: [Recommend] [Assess] …” on each card that sets mode + input; Council panel with scope/synthesis placeholders.
- **API:** Unchanged (still only analyze wired; council and others 501). No `suggestedNext` in response yet; no `context_from_step` in request yet.

This gives a visible, user-controlled workflow and a clear path to add backend support for suggested next actions and context in a follow-up.

---

## 6. Summary Table

| Item | Proposal |
|------|----------|
| **State** | `WorkflowState`: activeMode, input, steps[], contextFromStepId, loading, error. One step per run; no auto-chaining. |
| **Result card** | Per step: header (mode, time, input), body (data), footer with suggested next actions (buttons that set mode + input; Run stays manual). |
| **Next-action** | Backend returns optional `suggestedNext[]`; user clicks a suggestion → focus updates; user clicks Run → next request. Optional `previous_result_summary` in request for context. |
| **Council** | Options: scope (full / single / selected), singleRole, selectedRoles, includeSynthesis. UI in MVP; backend in follow-up. |
| **Smallest MVP** | Steps + result cards + placeholder “suggested next” (UI only); Council scope/synthesis UI placeholders; no API changes. |
