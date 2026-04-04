# Workspace Organizer / Folder-Sorting — Implementation Direction

**Product intent (refined):** This workflow is **not** primarily about sorting files correctly. It is about helping the user **gradually understand, trust, and adopt** a structure without losing their mental map. Human-in-the-loop and orientation-preserving.

**Design lesson:** Reorganizing everything at once caused disorientation. So: surface patterns → suggest candidates → user edits → optional AI refine/sanity-check → simulate before any move → preserve orientation and trust.

**Optimize for:** (1) Preserve user orientation (2) One-click thorough where possible (3) No broad/free-form council behavior in folder workflow (4) User reviews and confirms structure (5) Simple, operational outputs.

---

## 1. Short design recommendation

- **Keep** analyze and recommend fully algorithmic; keep simulation and review pattern.
- **Constrain** the AI layer in this workflow to a **single advisory role**: suggest parent folder options from the list, optionally use one level of content clues (tokens, extensions), give brief reasons only. No strategy, no long narrative, no restructuring proposals.
- **Reuse** the current council path with a **folder-workflow flag** (`workflow_kind: 'folder'`): when set, use folder-specific constraints, a folder-specific output format, **one seat** (folder advisor), **no synthesis**. Optionally omit operator priorities from the packet in this path.
- **Rename** the folder-workflow action from “Ask Council” to a task-specific label (e.g. **Refine Categories** or **AI Folder Review**) so the UI matches the job and does not imply a full strategic council.
- **Enrich** the context the AI sees when in folder workflow: include **suggested parent folder list**, **repeated tokens**, **extension/type clues** in the context block; avoid broad philosophy or operator priorities for this path.
- **Keep** the UI advisory and orientation-preserving: before/after and item→folder mapping stay clear; no automatic moves; user confirms.

---

## 2. Proposed next implementation order (3–5 steps)

| Step | What | Why first |
|------|------|------------|
| **1** | Backend: folder-workflow constraint + role_limit + single seat, no synthesis | Makes AI behavior scoped and predictable before any UI or context changes. |
| **2** | API: pass `workflow_kind: 'folder'` through; frontend: set it when invoking from recommend step | Enables the backend branch without new routes. |
| **3** | Frontend: enrich context for folder workflow (suggested folders list, repeated tokens, extensions) | Gives the AI minimal operational context; no strategy context. |
| **4** | UI: rename “Ask Council” to “Refine Categories” (or equivalent) in the folder workflow only; tighten prefilled question | Matches user mental model and keeps the prompt narrow. |
| **5** | Backend (optional): omit operator priorities from packet when `folder_workflow` | Keeps folder packet strictly operational; small, clear change. |

---

## 3. Exact files and functions to edit (first)

### Step 1 — Backend: folder constraint, role_limit, single seat, no synthesis

**File:** `local_ai/atria_tools.py`

- **Add** constants (e.g. near other `COUNCIL_*`):
  - `FOLDER_COUNCIL_CONSTRAINT`: text that limits the task to suggesting from the list, brief reasons only, no restructuring/strategy/long narrative.
  - `FOLDER_COUNCIL_ROLE_LIMIT`: output format “Suggested parent folders (from the list above only):” then “- &lt;folder&gt; — &lt;short reason&gt;” and optional “Add to my recommendations: …”.
  - `FOLDER_ADVISOR_SYSTEM`: one short system line for the single seat, e.g. “You are a folder categorization assistant. You suggest parent folder options from the given list and give one short reason per suggestion. You do not propose strategy or restructuring.”
- **Edit** `run_council_stream`:
  - Add parameter `folder_workflow: bool = False`.
  - When `folder_workflow` is True:
    - Set `key_constraints = FOLDER_COUNCIL_CONSTRAINT` (override incoming `key_constraints` for this call).
    - Use `role_limit = FOLDER_COUNCIL_ROLE_LIMIT` for the prompt.
    - **Do not** build multiple seats or perspective_definitions; build **one** task with system `FOLDER_ADVISOR_SYSTEM`, packet (context + question), and folder role_limit.
    - **Do not** run synthesis; yield the single response then `(full, True)`.
  - When `folder_workflow` is False, keep current behavior (multiple seats, synthesis, default role_limit).

**Leave alone for now:** `build_council_decision_packet` signature; general council path; provider/model selection.

---

### Step 2 — API + Frontend: pass and set `workflow_kind`

**File:** `api/main.py`

- **Edit** `_council_stream_gen(params, context)`:
  - After deriving `context_str`, set `folder_workflow = (context or {}).get('workflow_kind') == 'folder'`.
  - Pass `folder_workflow=folder_workflow` into `run_council_stream(...)`.

**File:** `frontend/src/App.tsx`

- **Edit** `runCouncil()` (where `body.context` is built for `POST /run/stream`):
  - When setting `body.context` (i.e. when `lastFolderPath || contextBlock`), set `body.context.workflow_kind = 'folder'` **only when** the run is from the folder workflow. Use: `lastMode === 'recommend' && !!lastFolderPath` (or a dedicated flag set when the user clicks the refine-categories button from the recommend step; prefer the same heuristic for minimal state).
  - Ensure the type for `body.context` allows `workflow_kind?: string`.

**Leave alone for now:** Other modes; council panel when not in folder workflow.

---

### Step 3 — Frontend: enrich context for folder workflow

**File:** `frontend/src/App.tsx`

- **Edit** `buildContextBlock()` (and/or the path that builds `context_block` when `workflow_kind === 'folder'`):
  - When building context for council and **folder workflow** (e.g. `lastMode === 'recommend'` and we have `lastRecommendResult`), include:
    - Folder: `lastFolderPath`
    - Mode: Recommend. Context: `lastRecommendResult.inferred_context_domain`. Suggested folders: `lastRecommendResult.suggested_child_folders?.length`
    - **Suggested parent folders:** comma-separated list of `approvedFolders` (or `lastRecommendResult.suggested_child_folders`) so the model sees the actual list, not only the count.
  - When **folder workflow** and we have **lastAnalyzeResult** (user ran analyze before recommend), append:
    - **Repeated tokens:** `lastAnalyzeResult.repeated_tokens?.slice(0, 15).join(', ')`
    - **File types (extensions):** one line from `lastAnalyzeResult.extension_breakdown`, e.g. “.pdf (5), .doc (3), …” (top 10).
  - Do **not** add narrative, operator priorities, or philosophy; keep this block short and operational.

**Leave alone for now:** Non-folder context building; API contract (context_block remains a string).

---

### Step 4 — UI labels and question (folder workflow only)

**File:** `frontend/src/App.tsx`

- **Labels to change (folder workflow only):**
  - In **SuggestedFoldersEditor**: change the button text from **“Ask Council (AI)”** to **“Refine Categories”** (or **“AI Folder Review”**). Prefer **“Refine Categories”** — it’s task-specific and does not imply a full council.
  - In the **Step 3 card** (Recommend folders), change the primary action button from **“Ask Council”** to **“Refine Categories”** (same label as above).
  - Optional: when the right-hand panel is showing the folder-workflow AI result, show a sublabel like “Folder review” instead of “Council” next to the streamed/result text, so the user sees this is the constrained advisor, not the full council. (Can be done by checking `lastMode === 'recommend'` when rendering the agent response header.)
- **Prefilled question:**
  - When the user clicks “Refine Categories”, set the question to something narrow, e.g.:  
    “From this list of candidate parent folders — [approvedFolders.join(', ')] — which would you keep or prioritize for this folder’s contents? One short reason per suggestion.”  
  - Avoid “which should I prioritize and why?” if it encourages long narrative; the new wording plus the backend role_limit keeps output short.

**Leave alone for now:** Labels in the general Council / AI agents panel (when not in folder workflow); “Run Council” and other council UI outside the Workspace Organizer.

---

### Step 5 (optional) — Omit operator priorities when folder_workflow

**File:** `local_ai/atria_tools.py`

- **Edit** `build_council_decision_packet`:
  - Add an optional parameter, e.g. `omit_operator_priorities: bool = False`.
  - When `omit_operator_priorities` is True, do **not** append the “Operator priorities” block (skip the `load_operator_priority()` block).
- **Edit** `run_council_stream`:
  - When `folder_workflow` is True, call `build_council_decision_packet(..., omit_operator_priorities=True)` (or pass through a new parameter from the caller). So the folder-workflow packet contains only: Context, Question, optional Working memory, Constraints (folder constraint), and no operator priorities.

**Leave alone for now:** Other packet blocks; general council path.

---

## 4. Labels / text to change in the UI

| Location | Current | Proposed (folder workflow) |
|---------|--------|----------------------------|
| SuggestedFoldersEditor, button | “Ask Council (AI)” | **Refine Categories** |
| Step 3 (Recommend) card, button | “Ask Council” | **Refine Categories** |
| Prefilled question when opening from recommend | “Given these folder options — A, B, C — which should I prioritize and why?” | “From this list of candidate parent folders — A, B, C — which would you keep or prioritize for this folder’s contents? One short reason per suggestion.” |
| Optional: Agent response header when last result is from folder workflow | “Council” | “Folder review” or “Refine categories” |

**Do not change** (outside folder workflow): “Run Council”, “Council”, “Strategist, Operator, Analyst…”, or other general council labels.

---

## 5. Summary by area

| Area | Recommendation |
|------|----------------|
| **A. Folder workflow behavior** | One refinement: AI layer only suggests parent folders from the list, optionally uses repeated tokens + extension clues (one level), brief reason per suggestion; no restructuring, no long narrative. Implement via folder constraint + folder role_limit + single seat. |
| **B. Human orientation / trust** | Keep workflow advisory and one-click thorough where possible. Enrich context so the AI sees the real list and clues (step 3). Keep simulate-before-move and user-editable approved list. No automatic moves. Optional later: explicit “before/after” or item→folder map in the step 4 summary. |
| **C. Council / AI for this workflow** | Use current council path with `workflow_kind: 'folder'`; **one constrained advisory seat**; **no synthesis**; rename in UI to “Refine Categories” so it doesn’t imply full strategic council. |
| **D. UI / wording** | “Ask Council” → **“Refine Categories”** in the folder workflow (Step 3 + SuggestedFoldersEditor). Tighten prefilled question. Optionally show “Folder review” when displaying that result. |
| **E. Working memory / context** | Minimal context for folder workflow: folder path, **suggested parent folders** (full list), **repeated tokens** (e.g. top 15), **extension/type clues** (e.g. top 10). Optionally omit operator priorities in packet for this path. No nested subfolder names in this iteration (analyze does not return child folder names, only counts and suggested_child_folders; can add later if we expose them). |
| **F. Implementation order** | (1) Backend: folder constraint + role_limit + single seat + no synthesis. (2) API + frontend: `workflow_kind`. (3) Frontend: enrich context block for folder. (4) UI: labels + prefilled question. (5) Optional: omit operator priorities when folder_workflow. |

---

## 6. What to leave alone for now

- Analyze and recommend algorithms (no model).
- General council path (multiple seats, synthesis, default role_limit) when **not** folder workflow.
- Simulation and step 4 UX (beyond any small copy tweaks).
- No new routes or `mode=council_folder`; same `POST /run/stream` and `run_council_stream`.
- No change to model selection (still use council provider).
- Parsing council output into structured “Add to recommendations” in the UI can follow once the format is stable (design doc Phase 2).
