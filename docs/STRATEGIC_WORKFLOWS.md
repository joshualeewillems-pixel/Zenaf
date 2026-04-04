# Strategic Planning & Brainstorming — System Overview

**Status:** Living design / usage note  
**Scope:** How the current Atria cockpit supports strategic planning and brainstorming with the council, AI agents, Vision Execution, and Content.  
**Use:** This doc is intended to be kept up to date and used as the reference when you ask “explain the whole system” in the future.

---

## 1. High-level structure

Atria’s strategic layer is organized into three main surfaces, all sharing context and AI agents:

- **Workspace Organizer (Cockpit)** — Folder-oriented analysis and council workflow for *one current topic* (e.g. a project folder, desktop area).  
- **Perspectives / AI agents** — The **Profiles** (perspectives) and **Seats** (Profile × Mandate) used for council runs and advisory chat.  
- **Vision & Execution (VE)** — The durable system of record for ideas → initiatives → projects → tasks, plus strategic **Radar**.  
- **Content** — A production workspace for taking distilled strategy and VE context into briefs, scripts, and drafts.

The **AI Agents panel** on the right is the primary thinking interface: questions, council, web research, and “next step” all run there, using profiles + mandates configured in the council include list.

---

## 2. Core features for strategy & brainstorming

### 2.1 AI Agents panel (council & chat)

- **Question input** — “Question / how to process” field at the top of the AI Agents panel.  
- **Modes** (top of Workspace section, not the AI panel): analyze, recommend, assess, simulate, council, web_research, next_step.  
- **Council** (`mode = council`):
  - You choose which **profiles** (perspectives) to include (checkboxes in “Include in this run”).  
  - For each included profile, you can choose a **Mandate** (strategic, governance, operator, integrator, creative, analyst, or none). This forms a **seat** (Profile × Mandate).  
  - When you click **Run Council**, the backend:
    - Builds a context packet from the current topic, last results, and any VE decisions.
    - Runs all selected seats in parallel via `run_council_stream`.  
    - Each seat returns a **structured judgment**:
      - Position (proceed / pause / reject / revise)  
      - Primary reason  
      - Main risk  
      - Required guardrail  
      - Next step  
    - Optionally runs an Atria/Integrator **synthesis** if seats disagree (or if explicitly enabled), summarizing agreement, tension, and a recommended action.
  - Results are shown in the AI Agents thread with seat headers (Strategist, Operator, etc.) and a highlighted `Atria synthesis:` block when present.

- **Web Research** (`mode = web_research`) — For quick external context; outputs a short summary of findings.  
- **Next Step** (`mode = next_step`) — Uses current context and your question to suggest a single concrete next action (Recommendation / Rationale / Alternatives / Caution).

### 2.2 Workspace Organizer loop

The left/main side of the **Workspace Organizer** view is a vertical workflow:

1. **Select folder** — Choose a filesystem folder as the current topic. You can type a path, pick from **Recent folders**, or click **Browse** to open a native folder picker (API runs the dialog on the same machine and returns the path).  
2. **Get suggestions** — One action that runs **Analyze** then **Recommend**. Recommend uses internal two-level (latent-bucket) reasoning to improve the flat suggested list; the UI remains a single flat list.  
3. **Edit suggested folders** — Promote, reject, or add custom folders. The effective list is *suggested − rejected + custom* (**approved folders**).  
4. **Simulate** — Visual preview of simulated moves. Simulation uses only the **current approved folder list** (plus Unsorted). If you remove a suggested folder and re-run simulation, that folder is no longer a valid target; any prior overrides or assignments pointing to it are dropped or clamped, and affected items fall back to Unsorted.  
5. **Review plan** — Future hook for execution (Accept plan / Save for later).

At each stage, you can:

- Use **AI Agents (council)** to ask:
  - “Given these options, which strategy should we pursue and why?”  
  - “Where are the biggest risks or drifts?”  
- Use **Reassess with Perspective** (in Assess) to run a single profile seat over low-confidence assignments.

This creates a loop of **folder/context → analyze/assess → council → plan** for strategic organization or project scaffolding.

### 2.3 Vision & Execution (strategic engine)

The **Vision & Execution** view exposes the longer-horizon strategic model:

- **Ideas** — Raw strategic or tactical ideas.  
- **Initiatives** — Structured bets with briefs, status, and derived scores.  
- **Projects & Tasks** — Execution units linked to initiatives.  
- **People, Capacity, Assets** — Who can do work, with what constraints.  
- **Radar** — Derived “what needs attention” buckets (act_now, blocked, overcapacity, unanchored, high_value_stalled, kill_candidates).

In VE you can:

- Capture outcomes from council or brainstorming as **ideas/initiatives/projects/tasks**.  
- Use council seats to reassess initiatives (via initiative_evaluate and future consult hooks).  
- Use Radar to orient “where to look” before a strategy session.

### 2.4 Content workspace (strategy → assets)

- **Content Brief** — A small object (see `CONTENT_PIPELINE.md`) capturing:
  - title  
  - linked initiative/project/task  
  - audience, content_goal  
  - key_themes, claims, CTA, tone/voice  
  - target_formats, source_materials, notes  
- **Generation** — From a brief + source materials, you can generate:
  - script  
  - newsletter draft  
- **Export / next actions** — Copy/export outputs and create VE tasks like “record narration”, “produce avatar video”, “build landing page”, “send newsletter”.

This lets you move from **strategy → narrative → production tasks** while staying anchored to VE initiatives/projects.

---

## 3. Profiles, mandates, and seats

The strategic/braindstorming system uses the **personality layer** described in `PERSONALITY_PROFILE.md` and `ROLE_MODEL.md`:

- **Profiles (Perspectives)** — Cognitive identities (Strategist, Operator, Analyst, Governance, Brand, custom personas). Each profile has voice, reasoning style, decision heuristics, values, constraints, and optional example phrases.  
- **Mandates** — Lightweight responsibilities (strategic, governance, operator, integrator, creative, analyst, etc.) with fields:
  - id, name  
  - core_question  
  - optimize_for  
  - watch_for  
  - failure_mode  
  - output_style  
- **Seats** — Runtime pairing **Profile × Mandate** plus capability/access settings (advisory vs active, memory lens, domain scope).

In the AI Agents panel:

- You choose which **profiles** to include for council.  
- For each profile, you can set a **Mandate** from a small built-in list (with sensible defaults for built-ins).  
- Each included profile+mandate becomes a **seat**, and council prompts are built from:
  - profile definition (name, purpose, values, decisionRule, tone, etc.), and  
  - mandate definition (core_question, optimize_for, watch_for, failure_mode, output_style).

This avoids multiple overlapping “role systems” and keeps strategy-focused behavior attached to profiles.

---

## 4. Typical strategic workflows

### 4.1 Folder → plan → council

1. Select a **folder** that represents a project or domain.  
2. Run **Analyze** and **Assess** to understand structure and uncertainty.  
3. Use **Recommend** and **Simulate** to propose and preview a folder plan.  
4. In AI Agents, set up a council (e.g. Strategist/Strategic, Operator/Operator, Analyst/Analyst, Governance/Governance).  
5. Ask: “Given these options and constraints, how should we stage this initiative or project?”  
6. Use the structured seat outputs + synthesis to decide and capture the plan (e.g. as notes or VE tasks).

### 4.2 Idea → Initiative → Council → Execution

1. In VE, record an **Idea** or promote to an **Initiative** with a brief.  
2. Use AI Agents council with seats tuned to the decision (Strategist, Analyst, Governance, etc.).  
3. Question examples:
   - “Should we promote this initiative now or defer?”  
   - “What are the main kill criteria and guardrails for this bet?”  
4. Convert outputs into:
   - updated initiative brief/notes,  
   - new **Projects/Tasks** attached to the initiative.

### 4.3 Strategy → Content

1. From an initiative/project or council result, create a **Content Brief** in the Content tab.  
2. Run generation for **script** or **newsletter** using the brief + source materials.  
3. Optionally, consult council about the brief itself (e.g. “Does this narrative fit our strategic position and constraints?”).  
4. Export scripts/drafts and create **VE tasks** for production/distribution.

### 4.4 Open-ended brainstorming with council

1. Without a specific folder or VE object, use AI Agents with `mode = council`.  
2. Configure seats (profiles + mandates) for the kind of thinking you want.  
3. Ask open questions:
   - “Given my next 12 months, what are 3 strategic directions we should explore?”  
   - “Where are we likely drifting from our mission in current projects?”  
4. Use structured outputs to:
   - spawn VE Ideas/Initiatives,  
   - capture constraints, guardrails, and next steps.

---

## 5. How this doc will be used

This document is meant to be the **single reference** for:

- Current features that support strategic planning and brainstorming.  
- How the AI Agents panel, council, VE, and Content work together.  
- How profiles, mandates, and seats shape behavior.

When you ask “explain the current system” in the future, I can pull from and update this doc so the explanation stays in sync with the actual implementation.

---

## 6. Machine-level architecture (summary)

This section captures the lower-level, code-oriented view of the same system.

### 6.1 Frontend surfaces

- `frontend/src/App.tsx` is the cockpit shell:
  - Manages `mainView` (`workspace`, `perspectives`, `content`, `vision_execution`), current topic, last run results, `agentThread`, etc.
  - Renders:
    - Left: `Workspace Organizer`, `PerspectivesView`, `ContentView`, `VisionExecutionView`.
    - Right: AI Agents panel (always visible).
- **AI Agents panel** (in `App.tsx`):
  - State: `question`, `activeMode`, `perspectiveAgents`, `includedPerspectiveIds`, `mandatesByPerspectiveId`, `agentThread`, `streamingCouncilText`, etc.
  - Council path:
    - `runSelectedAgent` gathers selected profiles (checkboxes) and calls `runCouncil`.
    - `runCouncil` builds `perspective_definitions` from `PerspectiveAgent` + optional `mandate` and calls `POST /run/stream` with `mode: "council"`.
    - SSE stream (`/run/stream`) yields `data: {"chunk": "...", "done": bool}`; chunks are rendered via `CouncilText` (seat headers + structured fields).
- **Perspectives** live in `frontend/src/perspectives/`:
  - `types.ts` defines `PerspectiveAgent` and `BUILT_IN_PERSPECTIVES`.
  - `PerspectivesView` manages localStorage persistence (`atria-perspective-agents`) and passes `perspectiveAgents` up to `App.tsx`.
- **Mandates** live in `frontend/src/mandates.ts`:
  - `Mandate` type + `BUILT_IN_MANDATES` (strategist, governance, operator, integrator, creative, analyst).
  - `DEFAULT_MANDATES_BY_PROFILE` in `App.tsx` maps built-in profiles → default mandate ids.
- **Workspace Organizer** (in `App.tsx`):
  - **Folder selection:** `FolderSelector` supports text path, Recent folders dropdown, and **Browse** (POST `/folder-picker` with optional `initial_dir`; native tkinter dialog in API subprocess returns `folder_path`).
  - **approvedFolders** = suggested − rejected + custom; **effectiveSimulateTargetFolders** = approvedFolders + `Unsorted` when needed; **filteredSimulationOverrides** = overrides whose target is in the effective list.
  - Simulation tree receives **targetFolders={effectiveSimulateTargetFolders}** and **overrides={filteredSimulationOverrides}**; `SimulateTreeGraphical` clamps each item’s displayed folder to the target list (fallback to Unsorted) and builds lane order from the target list only, so deleted folders never appear as lanes or valid targets.
- **Content** (`frontend/src/content/`) and **Vision Execution view** (`frontend/src/vision-execution/`) talk to `/run` and `/vision-execution` respectively for generation and VE CRUD.

### 6.2 API layer (`api/main.py`)

- **Folder picker:** `POST /folder-picker?initial_dir=<path>` runs a native folder dialog (subprocess, tkinter) and returns `{ folder_path: string | null }` or `{ error: string }`. Used by the cockpit when the user clicks Browse in Workspace Organizer.
- `RunRequest { mode, params, context }` → `POST /run`:
  - `RunParams` includes:
    - `folder_path`, `question`, `query`.
    - `included_agents`, `perspective_definitions`, `include_synthesis`.
    - VE-related params (ideas/initiatives/projects/tasks handled via `/vision-execution`), plus Content fields (`content_brief`, `content_source`, `content_output_type`).
  - Dispatch functions: `_run_analyze`, `_run_simulate`, `_run_recommend`, `_run_assess_uncertainty`, `_run_reassess_low_confidence`, `_run_web_research`, `_run_next_step`, `_run_council`, `_run_content_generate`.
- **Council (non-stream)**:
  - `_run_council(params, context)`:
    - Normalizes `context_str` from `context.context_block` / `context.folder_path`.
    - Passes `question`, `included_agents`, `perspective_definitions`, and `include_synthesis` into `local_ai.atria_tools.run_council(...)`.
- **Council streaming**:
  - `_council_stream_gen(params, context)` calls `run_council_stream` and wraps each `(chunk, done)` as SSE `data: {...}` lines for `/run/stream`.
- `/vision-execution` router proxies to `local_ai.vision_execution.service` for VE CRUD and radar.

### 6.3 Council runtime (`local_ai/atria_tools.py`)

- **Providers** (`local_ai/providers/__init__.py`):
  - `get_default_provider()` → `OllamaProvider` by default.
  - `get_council_provider()` currently delegates to `get_default_provider()`, but isolates council from other modes for future model changes.
- **System prompts**:
  - Built-in council seats use `BUILT_IN_PERSONA_DEFINITIONS` in `atria_tools.py` (strategist, operator, analyst, governance, brand, …), composed into seat prompts; not separate `COUNCIL_*_PROMPT` constants per role.
  - `_build_perspective_system_prompt(defn)` merges profile fields and optional `mandate` for custom seats.
- **Decision packet**:
  - `build_council_decision_packet(question, context, recent_tool_summary, key_constraints)` composes a base text block including question and relevant context.
- **Seat prompt tail**:

  ```text
  Position: <proceed | pause | reject | revise>
  Primary reason: <...>
  Main risk: <...>
  Required guardrail: <...>
  Next step: <...>
  ```

- **Parallel execution and diagnostics**:
  - Seats (built-in or `perspective_definitions`) are fanned out via `ThreadPoolExecutor`.
  - `_run_one_role`:
    - Calls `provider.generate(prompt, timeout=COUNCIL_SEAT_TIMEOUT)` (per-seat timeout).
    - Returns `(role_index, "<Name>:\\n<structured response>\\n")` or an error chunk.
    - Logs per-seat timing and status to `debug-5581d2.log` (`role_index`, `name`, `status`, `duration_ms`, `error`).
- **Synthesis control**:
  - As seat chunks are collected, council parses `Position:` lines and tracks a `positions` set.
  - `include_synthesis` + `positions_disagree` determine whether Atria/Integrator synthesis runs.
- **Seat accounting**:
  - After seats (and optional synthesis), council compares:
    - `expected_seats` (derived from requested roles/definitions),
    - actual seat chunks (non-synthesis).
  - If mismatched, appends a diagnostic line such as:

    ```text
    [Council diagnostic: produced 2 of 4 seat responses. See debug log for seat diagnostics.]
    ```

  - Applies to both non-streaming `run_council` and streaming `run_council_stream`.

### 6.4 File Steward (Workspace Organizer backend)

- **tools/file_steward/app.py**: `analyze_folder_structure`, `recommend_child_folders`, `simulate_folder_plan`. Recommend uses **infer_latent_buckets** and **assign_children_to_buckets** for internal two-level reasoning (flat output; optional `hierarchy_proposal` in response). Simulate, when given `allowed_folders`, sets `suggested_child_folders` to that list (+ Unsorted) and clamps every proposed assignment to the allowed set.

### 6.5 Vision Execution + Content runtime

- VE: `local_ai/vision_execution/` holds:
  - `storage.py` (SQLite), `service.py` (derived fields + business logic), `radar.py` (bucketed attention, used by `/vision-execution/radar`).
- Content: `generate_content(brief, source_text, output_type)` uses the provider to generate scripts/newsletters from the Content Brief and source, with no extra coordination logic.

This machine-level section is the reference for how components interact when you ask for a “machine view” of the strategic system. It will be kept in sync with code changes over time.


