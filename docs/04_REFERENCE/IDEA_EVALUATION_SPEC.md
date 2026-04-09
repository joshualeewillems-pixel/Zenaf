# Idea Evaluation — Design Spec & Implementation Brief

**Status:** Design / spec only. No backend or UI implementation in this document.  
**Scope:** Correct evaluation contract for Ideas in Zenaf; stage intent; MVP vs later; UI implications.

---

## 1. Current State vs Target State

### What the current idea-evaluate endpoint returns today

`POST /vision-execution/ideas/{idea_id}/evaluate` reuses **initiative** evaluation. It:

- Loads the idea (title, summary, description).
- Calls `initiative_evaluate.evaluate_initiative(title, brief=summary||description, core_profile_summary)`.
- Returns the **initiative** response shape:

| Backend key | Type   | Meaning |
|-------------|--------|--------|
| `estimated_cost_ai` | string | Short cost estimate or range |
| `estimated_timeframe_ai` | string | Short timeframe (e.g. 2–4 weeks) |
| `philosophical_alignment_ai` | string | One sentence on strategic fit |
| `next_step_ai` | string | One concrete next action |
| `recommendation` | string | Approve / Incubate / Park / Reject + reason |
| `error` | string | Present only on failure |

There is **no** idea-specific prompt, schema, or persistence for idea evaluation.

### Which current UI fields are real vs heuristic vs unsupported

| UI field (Decision Analysis) | Source today | Status |
|------------------------------|--------------|--------|
| **Estimated cost (range)** | `estimated_cost_ai` | **Real** — 1:1 from backend |
| **Time to build** | `estimated_timeframe_ai` | **Real** — 1:1 |
| **Time to ROI** | `estimated_timeframe_ai` + suffix "(or edit)" or "(not from AI)" | **Heuristic** — reuses build timeframe; no dedicated ROI horizon |
| **ROI potential** | Inferred from `recommendation` text (approve→high, reject/park→low, else expected) | **Heuristic** — no explicit ROI signal from backend |
| **Required roles** | Literal string `"(not from AI)"` | **Unsupported** — backend does not return this |
| **Dependencies** | `next_step_ai` | **Heuristic** — “next step” is not “dependencies”; semantic mismatch |
| **Risks** | `philosophical_alignment_ai` | **Heuristic** — alignment is not risks; semantic mismatch |

### Why this is semantically mismatched

- **Initiative evaluation** is about: cost, timeframe, strategic alignment, one next step, and a go/no-go recommendation for an **already-scoped effort**.
- **Idea evaluation** (as the UI suggests) is about: cost **range**, time to build, **time to ROI**, **ROI potential**, **required roles**, **dependencies**, and **risks** — i.e. **valuation and feasibility** to decide whether to promote, shelve, or attach to a parent.
- Reusing the initiative shape forces the frontend to:
  - Map “next step” → “dependencies” and “alignment” → “risks,” which misrepresents meaning.
  - Invent ROI potential from recommendation text.
  - Leave required roles and true time-to-ROI as unsupported and labeled “(not from AI).”
- Result: the UI promises a **decision-oriented evaluation** (cost, ROI, roles, dependencies, risks) but the backend only provides **initiative-style** (cost, timeframe, alignment, next step, recommendation). The contract is wrong for the Idea stage.

---

## 2. Proposed Idea Evaluation Contract

**Intent:** The backend should return a response shaped for **idea-stage decisions**: valuation, timeline, team, dependencies, risks, alignment, and recommendation — not the initiative schema.

### Ideal backend response shape (idea evaluation)

All fields optional string (or enum where noted). Empty string or omit = “not provided.”

| Field | Type | Description |
|-------|------|-------------|
| **estimated_cost_range** | string | Cost or range (e.g. “low,” “2–3 weeks budget,” “$X–Y”). Idea-appropriate granularity. |
| **time_to_build** | string | Time to deliver / implement (e.g. “2–4 weeks,” “Q2”). |
| **time_to_roi** | string | When value/ROI is expected (e.g. “3 months,” “within quarter”). |
| **roi_potential** | enum | `"conservative"` \| `"expected"` \| `"speculative"`. Explicit ROI stance, not inferred from recommendation. |
| **required_roles** | string | Roles or “team seats” (e.g. “1 eng, 0.5 PM,” “design + dev”). Free text for MVP. |
| **likely_dependencies** | string | What this idea depends on (other work, systems, decisions). |
| **major_risks** | string | Key risks (delivery, fit, capacity, etc.). |
| **strategic_alignment** | string | Fit with strategic direction (replaces philosophical_alignment_ai in meaning for ideas). |
| **suggested_next_step** | string | One concrete next action (clarify, prototype, attach to X, etc.). |
| **recommendation** | string | Go/no-go style: e.g. Promote / Incubate / Shelve / Reject, with brief reason. |
| **recommended_parent_type** | string (optional) | Hint: e.g. “initiative,” “existing initiative,” “project.” For “Decide” stage. |
| **error** | string | Present only on failure; user-facing message. |

**Naming:** Use the names above in the API and UI so the same contract drives backend, frontend, and docs. Avoid reusing initiative keys for different semantics (e.g. do not map alignment → risks in the contract).

---

## 3. Idea Stage Intent

### What an Idea is (vs Initiative / Project / Task)

| Entity | Role in Zenaf |
|--------|----------------|
| **Idea** | Raw possibility or hypothesis. Not yet committed. Supports capture → clarify → **evaluate** → **decide** (promote, attach, shelve, delete). |
| **Initiative** | Committed strategic effort. Has owner, status, scoring, projects. Source can be an idea (`source_idea_id`). |
| **Project** | Concrete work stream under an initiative (or unanchored). |
| **Task** | Actionable unit under a project. |

Ideas are **pre-commitment**. Evaluation answers: “What would this take? What’s the ROI picture? What do we need? What could go wrong? Should we promote it, attach it, or shelve it?”

### What should happen in each stage

| Stage | Intent | Outcomes |
|-------|--------|----------|
| **Capture** | Jot down the idea with minimal friction. | Title + optional quick note. No tags, relationships, or deep fields. |
| **Clarify** | Expand and structure the idea (optionally AI-assisted). | Richer description, intent, desired outcome; editable suggestions. |
| **Evaluate** | Get a **decision-oriented** view: cost, time, ROI, roles, dependencies, risks, alignment, next step, recommendation. | AI evaluation using the **idea evaluation contract** (not initiative contract). User can edit and save. |
| **Decide** | Commit to an outcome. | Promote to Initiative; Attach to existing Initiative; Shelve; Delete. No scattered lifecycle controls. |

Evaluation in the Idea stage is therefore **valuation and feasibility for the idea**, not “initiative evaluation in disguise.”

---

## 4. MVP vs Later

### MVP — support next (backend + UI)

- **estimated_cost_range** — 1:1.
- **time_to_build** — 1:1.
- **time_to_roi** — 1:1 (backend to return explicitly; no reusing time_to_build).
- **roi_potential** — enum: `conservative` \| `expected` \| `speculative` (backend to return; no inferring from recommendation).
- **required_roles** — string (free text).
- **likely_dependencies** — string (can start as “suggested next step” style if needed, but name and prompt should aim at dependencies).
- **major_risks** — string.
- **strategic_alignment** — string.
- **suggested_next_step** — string.
- **recommendation** — string (Promote / Incubate / Shelve / Reject + reason).
- **error** — string (on failure).

MVP = one idea-specific evaluate prompt (and optionally a small idea_evaluate module) that returns this shape. No persistence of evaluation on the idea entity required for MVP; frontend can keep using local state and only persist when user promotes/attaches (same as today). Optional: store evaluation snapshot on the idea or in a separate “idea_evaluations” table later.

### Later — can wait

- **recommended_parent_type** — e.g. “initiative” vs “existing initiative”; useful for Decide UX but not required for Run evaluation to be correct.
- Storing evaluation result on the idea (e.g. `idea.evaluation_snapshot` or last-evaluated-at + fields).
- Structured required_roles (e.g. list of role types or links to people).
- Any NPV / monetary ROI calculation (keep as narrative for now).

---

## 5. UI Implications

### What the Idea screen should show (now vs later)

**Now (with MVP contract):**

- **Evaluate stage — Decision analysis:** Show only fields the backend actually returns and that match the contract. No heuristic mapping:
  - Estimated cost (range) ← `estimated_cost_range`
  - Time to build ← `time_to_build`
  - Time to ROI ← `time_to_roi`
  - ROI potential ← `roi_potential` (dropdown: conservative / expected / speculative)
  - Required roles ← `required_roles`
  - Dependencies ← `likely_dependencies`
  - Risks ← `major_risks`
  - Strategic alignment ← `strategic_alignment` (one line or short block)
  - Suggested next step ← `suggested_next_step`
  - Recommendation ← `recommendation` (read-only or editable short text)
- All of these **visible at Idea stage** because they are the outputs of “Evaluate” and feed “Decide.”
- Remove all “(not from AI)” placeholders and heuristic mappings once the backend returns the real contract.

**Later:**

- **recommended_parent_type** can drive a hint in the Decide step (e.g. “AI suggests: Promote to new initiative”).
- If evaluation is persisted on the idea, show “Last evaluated: …” and optionally “Re-run evaluation.”

### What should wait until Initiative or Project stage

- **Manual scoring** (priority, strategic value, energy impact) — Initiative.
- **Owner assignment** — Initiative (and Project/Task).
- **Required people / required assets** (entity links) — Initiative/Project; at Idea stage “required roles” is free text.
- **Capacity and allocation** — Initiative/Project/Task.
- **Kill criteria, deliverables, dates** — Initiative/Project.

So: Idea evaluation = **valuation and feasibility fields only**. Ownership, capacity, and execution details stay at Initiative and below.

---

## 6. Deliverable Summary

| Item | Description |
|------|-------------|
| **Contract** | Backend response for idea evaluation: `estimated_cost_range`, `time_to_build`, `time_to_roi`, `roi_potential`, `required_roles`, `likely_dependencies`, `major_risks`, `strategic_alignment`, `suggested_next_step`, `recommendation`, optional `recommended_parent_type`, `error`. |
| **Stage intent** | Capture = minimal; Clarify = expand; Evaluate = decision-oriented valuation/feasibility; Decide = promote / attach / shelve / delete. |
| **MVP** | New idea-specific evaluate prompt (and small backend path) returning the contract above; UI shows only contract fields, no heuristic remap. |
| **Later** | recommended_parent_type, persisting evaluation on idea, structured roles, any NPV/ROI math. |
| **UI** | Idea screen shows evaluation fields that match the contract; no “(not from AI)” for MVP fields. Initiative/Project keep ownership, scoring, capacity, kill criteria. |
| **Implementation** | Not in scope here: implement when ready as (1) backend idea-evaluate endpoint + prompt returning new shape, (2) frontend IdeaDecisionAnalysis and mapping updated to use that shape only. |

This spec is the implementation brief for the correct idea evaluation contract and how it fits the Idea stage and MVP vs later.
