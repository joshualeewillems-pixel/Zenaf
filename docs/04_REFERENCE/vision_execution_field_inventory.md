# Vision Execution field contract (canonical inventory)

**Status:** Structural truth — foundation for future wiring (no runtime behavior change in the introducing PR).  
**Machine-readable source:** [`vision_execution_field_inventory.json`](./vision_execution_field_inventory.json)  
**Audit date:** 2026-04-05  

## Purpose

Single inventory of Vision Execution **API/storage fields** and **VE shell UI labels** (`VisionExecutionView.tsx` and related types). Use it for:

- Chat / council **grounding** (allowed names per `entity_type`)
- Structured fill **targeting** (`storage_key` ↔ `ui_label`)
- Focus / invite **labeling** (must match `ui_label` when surfacing a field)
- Future **CI** checks (diff UI vs JSON vs `ve_integration_schema.py`)

Extra columns in the JSON (not in the original task list): `ve_ui_exposed` — whether the Vision Execution detail shell exposes an editor for that column.

## Canonical precedence (recommended)

| Priority | Source | Role |
|----------|--------|------|
| 1 | `vision_execution_field_inventory.json` | **Contract** — allowed `(entity_type, storage_key, ui_label)` tuples |
| 2 | `frontend/src/vision-execution/VisionExecutionView.tsx` | **UI implementation** — if it drifts, either fix UI or bump contract |
| 3 | `local_ai/vision_execution/schema.sql` | **Persistence** — columns must exist for durable keys |
| 4 | `local_ai/vision_execution/ve_integration_schema.py` | **Integration slice** — must become a generated subset of (1) after wiring |

## Entity summaries (human view)

### Core profile (`core_profile`)

Full narrative fields live in SQLite (`core_profiles`). The **VE shell** does not currently ship a dedicated “Core Profile” tab (tabs are Meeting Capture, Ideas, Execution, Team, Assets, Radar, Matching (Internal), Roadmap, Executive). Editing is primarily **Perspectives / Foundation** (`App.tsx`) plus partial create flow (`coreProfilePanels.tsx`). See JSON rows for `storage_key` / labels.

### Idea (`idea`)

Stages: Capture → Clarify → Evaluate → Decide. Main labels: **Title**, **Short note**, **Expanded description**, **Intent / what this idea is trying to become**. Evaluation panel labels match `IdeaDecisionAnalysis` in `VisionExecutionView.tsx` (session state; **not** persisted on the `ideas` row today — see JSON `session:idea_evaluation:*`).

### Initiative (`initiative`)

Sections: **Identity / scope**, **Decision / Summary** (sliders + decision fields + evaluation proposal UI), **Execution** (canonical **Execution steps** checklist backed by `execution_steps`), **Resourcing reality** (required assets + **Required seats / roles** → `initiative_seats` via `seats` on PATCH), **Risks / admin** (**Diagnostics / admin notes** maps `notes`).

### Project (`project`)

Sections: **Identity / scope**, **Plan & cadence** (includes **Suggested work (AI)** — client `localStorage` + API generation; not a SQL column), **Earlier suggestion (AI)** (`next_step_ai`), **Notes / admin**, optional **Radar (read-only)** derived block. Legacy columns `deliverables`, `complexity`, `current_focus` exist in DB but are **not** exposed; brief fold/clear behavior is in `ProjectDetailPanel` save.

### Task (`task`)

Sections: **Task**, **Dependencies** (**Depends on (tasks)**), **Completion criteria**, **Notes / admin**.

### Person + capacity (`person`, `capacity_profile`)

Person fields under **Identity**, **Strengths / needs / wants**, **Notes**; **Weekly capacity (hours)** via `capacity_profiles` PUT. **Current participation** is derived display.

### Asset (`asset`)

**Identity**, **Operational use** (links + read-only “Required by”), **Availability & access**, **Notes**.

## Mismatch report (structural drift)

| Category | Finding | Layers involved |
|----------|---------|-----------------|
| Integration schema **incomplete** | `ve_integration_schema.py` lists only a handful of keys per entity (e.g. initiative omits `dependencies`, `risks`, `recommendation`, `estimated_*`, seats, execution steps). | UI + DB vs `ve_integration_schema.py` |
| Council hydration **stale for projects** | `_hydrated_structured_bullets` maps `Recommendation:`, `Dependencies:`, `Risks:` for **project**, but the **project** detail panel has no such `DetailField`s. | `council_preflight.py` vs `VisionExecutionView.tsx` |
| Reference doc **tab model** | `VISION_EXECUTION_TABS_REFERENCE.md` describes separate Core / Ideas / Initiatives / Projects / Tasks tabs; current VE uses **Execution** (combined hierarchy) + **Ideas** + **Team** + **Assets**, etc. | Docs vs `VisionExecutionView.tsx` TABS |
| Idea **API-only** columns | `tags`, `created_by`, `linked_*`, `notes` exist in schema/types but **IdeaDetailPanel** does not PATCH them. | `schema.sql` / `types.ts` vs `VisionExecutionView.tsx` |
| Project **API-only** columns | `required_assets` on `projects` not edited in project panel. | `schema.sql` vs UI |
| Task **API-only** columns | `parent_task_id`, `required_asset_ids` not in task detail form (parent used in promotion flow). | `schema.sql` vs UI |
| Label aliases | Initiative evaluation **proposal** copy uses inline **Cost:** / **Timeframe:** while form fields are **Estimated cost** / **Estimated timeframe**. | Same file; minor user-visible inconsistency |
| Idea vs initiative **“Strategic alignment”** | Idea evaluation: **Strategic alignment**; initiative: **Strategic alignment (AI)** (`philosophical_alignment_ai`). | Cross-entity naming |
| Field capability registry **partial** | `fieldCapabilityRegistry.ts` covers a curated subset (initiative/idea/project/task only). | Contract vs registry |

## Contract usage plan (no implementation in this step)

### 1. Council preflight grounding

- Replace or augment free-text `_ui_field_schema_block` with **materialized strings** from the JSON for each `entity_type` (or generate Python/TS at build time).
- Add a **lint**: every label in the narrative must appear as a `ui_label` for that `entity_type` in the contract.

### 2. Structured fill / integration commit

- `allowed_storage_keys()` and `ui_label_for_storage_key()` in `ve_integration_schema.py` should be **generated or asserted equal** to contract rows where `safe_for_chat_reference` is true (or a defined integration subset).
- Trunk token aliases (`_ALIASES`) remain separate but must **only** map into contract `storage_key`s.

### 3. Invite / focus labeling

- `field_label` passed to `VeFocusRegion` / invites should be **looked up** from the contract (`entity_type` + `storage_key` → `ui_label`) in a later PR, so focus and chat never invent strings.

### 4. Optional CI validation

- Script: parse `VisionExecutionView.tsx` `DetailField label="..."` and compare to contract for each panel (allow list for dynamic labels).
- Script: diff contract `ui_label` set vs `ve_integration_schema._UI_LABEL_BY_ENTITY_AND_KEY`.
- Script: fail if council preflight schema block mentions a label not in contract for that entity.

## Changelog

| Version | Date | Notes |
|---------|------|-------|
| 1.0.0 | 2026-04-05 | Initial audit; JSON + this document |
