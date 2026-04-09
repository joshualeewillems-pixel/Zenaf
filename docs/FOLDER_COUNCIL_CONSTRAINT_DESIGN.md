# Design: Constrain council for folder-sorting / Workspace Organizer only

**Goal:** Limit council in this workflow to a narrow, operational task (suggest parent folders from the list + short reason; optional “add to recommendations”) and avoid broad strategy, long narrative, or general business-council behavior.

**Constraints:** No implementation in this doc. Scope limited to folder-sorting workflow. Smallest change that makes behavior predictable and useful. No redesign of the full council system.

---

## 1. Safest place to implement the constraint

**Recommended: council packet builder, driven by a folder-workflow flag.**

- **Primary mechanism:** When the request is for the **folder workflow**, pass a **folder-specific `key_constraints`** into the existing council path. The packet builder already supports `key_constraints` and renders them as a "Constraints:" block; the folder workflow currently does not set it.
- **Why this is safest:**
  - Single, explicit constraint block; no change to general council semantics.
  - No new routes or modes; same `POST /run/stream` and `run_council_stream`.
  - Constraint is visible in the packet so model and debugging stay clear.
- **Complement (recommended for predictable output):** Add a **role_limit override** when the folder workflow is active so the model is asked for a short, list-style response instead of Position/Primary reason/Main risk/etc. Without this, the model may still follow the default role_limit and produce mixed or long output even with constraints.

**Not recommended as primary:**

- **Frontend question shaping only:** Reduces ambiguity but does not constrain the model; it can still ignore the question and produce long narrative.
- **New folder-specific council mode (e.g. `mode=council_folder`):** Larger surface area and a second code path; only justified if we later want a different model or no synthesis.
- **Role_limit override only (no constraint block):** Format alone does not tell the model to avoid strategy/restructuring; combining with a constraint is safer.

**Conclusion:** Use **packet constraint + role_limit override** for the folder workflow, both gated on a single flag (e.g. `workflow_kind: 'folder'`) sent from the frontend and passed through the API into `run_council_stream`.

---

## 2. Recommended output shape for this workflow

Keep it minimal and operational.

**Target format (in the prompt instruction):**

```text
Suggested parent folders (from the list above only):
- <folder name> — <one short reason>
- <folder name> — <one short reason>

Optional: Add these to my recommendations: [yes / no, or list the ones to add]
```

**Rationale:**

- "From the list above only" ties output to the question/context and discourages inventing categories.
- One line per folder + one short reason keeps responses bounded.
- Optional "Add these to my recommendations" gives a clear, actionable hook for the UI later (e.g. a button that applies selected suggestions back into the approved list) without requiring it in v1.

**Minimal variant (if we want even shorter):**

```text
Suggestions (folder — reason, one per line):
- <folder> — <reason>

Add to recommendations: [optional one line]
```

**Implementation note:** This shape is enforced by the **folder-specific role_limit** string passed to the model when `workflow_kind === 'folder'`. The constraint block in the packet then tells the model to *only* suggest from the list, give brief reasons, and not propose restructuring or strategy.

---

## 3. Reuse current council path vs new folder-advisory mode

**Recommendation: Reuse the current council path with a folder-specific constraint.**

- Use the same `mode=council`, `POST /run/stream`, and `run_council_stream`.
- Differentiate behavior only by a **request-time flag** (`context.workflow_kind === 'folder'`):
  - When set: inject folder-specific `key_constraints` and use folder-specific `role_limit` (and optionally force single seat or skip synthesis—see below).
- **Do not** add a separate `mode=council_folder` or a separate endpoint unless we later need a different model or a fully different flow (e.g. no synthesis, single “folder advisor” seat).

**Optional simplification for folder workflow only:**

- **Single seat:** When `workflow_kind === 'folder'`, we could run only one “folder advisor” prompt (no multi-seat council) to avoid overlapping perspectives and keep output short. That would be a branch inside `run_council_stream` (e.g. if folder_workflow: build one task with packet + folder role_limit, no synthesis). This is a small, scoped addition rather than a new mode.

---

## 4. Model for this workflow

**Recommendation: Keep using the current council model.**

- No new provider or env var; behavior stays consistent with the rest of council.
- Folder task is narrow; token usage is already bounded by a short packet and a short role_limit.
- If we later want a smaller/faster model for this path only, we can add an optional override (e.g. `context.use_fast_model_for_folder` and a branch in the provider call) without changing this design.

**Avoid model use entirely:** Not recommended for the “Ask Council” button; the button is explicitly for AI input. The algorithmic recommend step remains model-free.

---

## 5. Exact files and functions to edit (in order)

**5.1 Backend: folder constraint constant and role_limit**

- **File:** `local_ai/zenaf_tools.py`
- **Add:** A constant for the folder-workflow constraint text, e.g. `FOLDER_COUNCIL_CONSTRAINT`, and a constant for the folder role_limit string (e.g. `FOLDER_COUNCIL_ROLE_LIMIT`).
- **Edit:** `run_council_stream`:
  - Add an optional parameter, e.g. `folder_workflow: bool = False`.
  - When `folder_workflow` is True:
    - Before calling `build_council_decision_packet`, set `key_constraints = FOLDER_COUNCIL_CONSTRAINT` (overriding or replacing the incoming `key_constraints` for this call only).
    - When building per-seat prompts, use `role_limit = FOLDER_COUNCIL_ROLE_LIMIT` instead of the default `role_limit`.
  - Leave synthesis and seat selection unchanged in the minimal version; optionally, when `folder_workflow` is True, run a single “folder advisor” task and skip synthesis (see §3).

**5.2 API: pass folder flag**

- **File:** `api/main.py`
- **Edit:** `_council_stream_gen(params, context)`:
  - After building `context_str`, set `folder_workflow = (context or {}).get('workflow_kind') == 'folder'`.
  - When calling `run_council_stream`, pass `folder_workflow=folder_workflow`.
  - Do **not** pass `key_constraints` from the API; the backend will set `key_constraints` and `role_limit` internally when `folder_workflow` is True, so the folder constraint constant lives only in `zenaf_tools`.
  - Ensure `request.context` is passed through as-is so `workflow_kind` is available (it already is).

**5.3 Frontend: set workflow_kind when invoking council from folder flow**

- **File:** `frontend/src/App.tsx`
- **Edit:** In `runCouncil()` (where `body.context` is built for `POST /run/stream`):
  - When `body.context` is set (i.e. when `lastFolderPath || contextBlock`), and the council run is for the **folder workflow**, set `body.context.workflow_kind = 'folder'`.
  - Heuristic for “folder workflow”: e.g. `lastMode === 'recommend' && !!lastFolderPath`, or a dedicated state set when the user clicks “Ask Council” from the recommend step. Prefer the latter if we have it (e.g. a `councilInvokedFromFolderWorkflow` flag set on “Ask Council” and cleared when switching mode or running another workflow).

**5.4 Optional: single-seat folder advisor**

- **File:** `local_ai/zenaf_tools.py`
- **Edit:** Inside `run_council_stream`, when `folder_workflow` is True, optionally:
  - Build one task with the folder packet and folder role_limit (no built-in role names; one generic “Folder advisor” system line or reuse a minimal system prompt).
  - Skip synthesis.
  - Yield that single response. This keeps the folder output short and avoids mixing multiple council voices.

---

## 6. UI: full council text vs structured result

**Recommendation: Keep showing council output as text for the first iteration; add light structure only if we standardize the format.**

- **Phase 1 (smallest change):** Continue to display the streamed council response in the same place (e.g. `CouncilText` in the AI agents panel). Rely on the **constraint + folder role_limit** to make the content short and list-like. No parsing or “Suggested folders” card yet.
- **Phase 2 (optional):** If we adopt the recommended output shape and it’s stable, we can add a **folder-workflow-specific renderer** that:
  - Detects folder workflow (e.g. `lastMode === 'recommend'` and council was just run, or a flag from the run).
  - Parses lines like `- <folder> — <reason>` and “Add to recommendations: …” and shows:
    - A simple list of “Folder — reason”.
    - An optional “Add these to recommendations” control that pushes parsed folder names into the approved list.
  - Falls back to raw text if the response doesn’t match the pattern.

**Why not structured-only from day one:** Parsing is brittle until the model consistently follows the format; constraining the prompt first makes the format reliable, then we can add a structured view and an “Add to recommendations” action without redesigning the rest of the council UI.

---

## 7. Summary table

| Item | Recommendation |
|------|----------------|
| **Safest place** | Council packet builder: folder-specific `key_constraints` + **role_limit override** when `workflow_kind === 'folder'`. |
| **Output shape** | “Suggested parent folders (from the list above only):” then “- &lt;folder&gt; — &lt;short reason&gt;” and optional “Add these to my recommendations: …”. |
| **Path** | Reuse current council path; no new mode; optional single-seat folder advisor when `folder_workflow` is True. |
| **Model** | Current council model. |
| **First edits** | 1) `zenaf_tools.py`: add `FOLDER_COUNCIL_CONSTRAINT` and `FOLDER_COUNCIL_ROLE_LIMIT`; in `run_council_stream` add `folder_workflow` and use them. 2) `api/main.py`: in `_council_stream_gen` set `folder_workflow` from `context.get('workflow_kind')` and pass to `run_council_stream`. 3) `frontend/src/App.tsx`: set `context.workflow_kind = 'folder'` when council is run from the recommend step. |
| **UI** | Keep full council text initially; add a structured “folder suggestions” view and “Add to recommendations” once the format is stable. |

---

## 8. Suggested constraint and role_limit text (for implementation)

**FOLDER_COUNCIL_CONSTRAINT (key_constraints block):**

```text
You are helping only with folder organization for the current folder. Limit your response to:
1. Suggest parent folder categories from the list provided in the question only (do not invent new categories).
2. Give at most one short reason per suggestion.
Do not: propose broad restructuring, strategy, long narrative, or general business advice. Do not simulate workflow redesign.
```

**FOLDER_COUNCIL_ROLE_LIMIT (role_limit when folder_workflow):**

```text
Return your answer in this exact format:

Suggested parent folders (from the list above only):
- <folder name> — <one short reason>
- <folder name> — <one short reason>

Add to my recommendations: [optional: yes/no or list folder names to add]
```

These can be tuned later (e.g. shorter or stricter) without changing the wiring.
