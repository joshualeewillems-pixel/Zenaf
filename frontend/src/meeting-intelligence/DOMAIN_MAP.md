# Step 1 — Existing domain structures (mapping for Meeting → Structure pipeline)

This document records where the system defines or stores operational entities so the new pipeline can map into them.

---

## Initiatives

| Where | Details |
|-------|--------|
| **Types** | `frontend/src/vision-execution/types.ts` — `Initiative` (snake_case: `source_idea_id`, `owner_id`, `created_at`, etc.) |
| **Domain** | `frontend/src/domain/domainTypes.ts` — re-exports from vision-execution; `DomainData.initiatives` |
| **Seed** | `frontend/src/domain/seedData.ts` — `seedInitiatives` |
| **State** | `VisionExecutionView.tsx` — `initiatives`, `setInitiatives`; hydrated from domain, merged with API `/initiatives` |
| **API** | `POST /vision-execution/initiatives`, `PATCH /vision-execution/initiatives/:id`, `GET /vision-execution/initiatives` |

---

## Projects

| Where | Details |
|-------|--------|
| **Types** | `frontend/src/vision-execution/types.ts` — `Project` (`initiative_id`, `start_date`, `end_date`, etc.) |
| **Domain** | `domainTypes.ts` — `DomainData.projects`; seed in `seedData.ts` |
| **State** | `VisionExecutionView.tsx` — `projects`, `setProjects`; merge with `domain.projects` on fetch |
| **API** | `GET/POST/PATCH` under `/vision-execution/projects` |

---

## Tasks

| Where | Details |
|-------|--------|
| **Types** | `frontend/src/vision-execution/types.ts` — `Task` (`project_id`, `assignee_id`, `due_date`, etc.) |
| **Domain** | `DomainData.tasks`; seed in `seedData.ts` |
| **State** | `VisionExecutionView.tsx` — `tasks`, `setTasks`; merge with `domain.tasks` |
| **API** | `GET/POST/PATCH` under `/vision-execution/tasks` (optional `?project_id=`) |

---

## Assets

| Where | Details |
|-------|--------|
| **Types** | `frontend/src/vision-execution/types.ts` — `Asset` (`asset_type`, `linked_initiative_ids`, `linked_project_ids`, etc.) |
| **Domain** | `DomainData.assets`; seed in `seedData.ts` |
| **State** | `VisionExecutionView.tsx` — `assets`, `setAssets` |
| **API** | `/vision-execution/assets` |

---

## People / capacity

| Where | Details |
|-------|--------|
| **Types** | `frontend/src/vision-execution/types.ts` — `Person`, `CapacityProfile` (`person_id`, `weekly_capacity_hours`) |
| **State** | `VisionExecutionView.tsx` — `persons`, `capacityProfiles`; no domain seed for people |
| **API** | `/vision-execution/persons`, `/vision-execution/capacity-profiles` |

---

## Radar summaries

| Where | Details |
|-------|--------|
| **Types** | `frontend/src/vision-execution/types.ts` — `RadarItem`, `RadarResponse` (act_now, blocked, overcapacity, unanchored, etc.) |
| **State** | `VisionExecutionView.tsx` — `radarData`, `radarLoading`; fetched when tab is `radar` |
| **API** | `GET /vision-execution/radar` |
| **Radar Home** | `frontend/src/radar-home/` — derives from domain (initiatives, projects, tasks, inventory, inbox); not the same as VE Radar API |

---

## Meeting capture (existing)

| Where | Details |
|-------|--------|
| **Tab** | `VisionExecutionView.tsx` — tab `meeting_capture`; textarea for notes, "Extract Items" button |
| **API** | `POST /vision-execution/extract-meeting` with body `{ notes: string }` |
| **Response type** | `vision-execution/types.ts` — `ExtractMeetingResponse`: `{ ideas: ExtractedIdea[], initiatives: ExtractedInitiative[], tasks: ExtractedTask[], error? }` |
| **Extracted types** | Same file: `ExtractedIdea`, `ExtractedInitiative`, `ExtractedTask` (title, optional description/brief, confidence, sourceExcerpt) |
| **Flow** | User approves ideas/initiatives by checkbox; "Save Approved Items" POSTs ideas to `/ideas`, initiatives to `/initiatives`. Tasks are preview-only and not saved from meeting capture. |

---

## Meeting review staging (consolidation contract)

| Concern | Source of truth |
|---------|-----------------|
| **Commit “use existing”** | `StagedItemBase.acceptedExistingId` — rows with this set skip create on commit and are dropped in per-card commit (`VisionExecutionView`). |
| **Batch presort** | `POST /vision-execution/presort-candidate-triage` returns `presort_bucket`, `presort_existing_id`, `presort_existing_title`, **`presort_existing_type`** (catalog kind). Client maps to staging via `mapPresortTriageApiToStagingPatch` — when bucket is **existing** with a valid id, also sets **`acceptedExistingId`** and **`overrideType`** so behavior matches per-card placement. |
| **Per-card placement** | `POST /vision-execution/suggest-candidate-placement` → `buildStagingPatchFromPlacementSuggestion` sets `acceptedExistingId` / `parentLink` / `overrideType`. |
| **Correlation** | Optional body field `client_correlation_id` (or `clientCorrelationId`) echoed on responses for placement, presort, and node-transform suggests. |

## Confidence semantics (do not mix scales)

| Source | Kind | Notes |
|--------|------|--------|
| Extracted rows (`types.ts`) | `high` / `medium` / `low` | Discrete extractor label. |
| Placement / presort / node-transform APIs | Float **0–1** | Model or heuristic confidence. |
| Review duplicate helper (`duplicateDetection.ts`) | Dice **0–1** on word tokens | Not the same math as server-side sequence/Jaccard helpers in Python. |
| Post-merge canonization (Python) | Sometimes `high` / `medium` **strings** on merged entities | Merge promotion, not UI placement. |

Do **not** compare numeric thresholds across these families without explicit mapping.

---

## Data flow summary

- **Domain** (`domain/`): single seed source; `DomainProvider` exposes `useDomain()`. Used by Radar Home and Vision Execution (merge with API).
- **Vision Execution**: state holds initiatives, projects, tasks, assets, persons, etc.; fetch from API and merge with `domain`; detail panels and list/timeline views read from state.
- **New pipeline**: should output **typed extracted structures** that map into the above via **staging** (review) then **commit** to API/domain. Reuse `Initiative`, `Project`, `Task`, `Asset`, `Person` shapes for the commit payloads.
