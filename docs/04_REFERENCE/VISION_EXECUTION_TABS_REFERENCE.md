# Vision Execution — Tabs, Fields, and Internal Behavior (Exhaustive Reference)

This document explains what sits behind each tab, which fields are editable, how weighting/valuation and related logic work, and where the design was heading when work was sidestepped.

---

## 1. Where the tabs live and how you get there

- **App top-level views:** `mainView` can be `'home'`, `'workspace'`, `'perspectives'`, `'content'`, or `'vision_execution'`.
- **Radar Home** (`mainView === 'home'`): Default landing. Renders `RadarHomePage` with role `anna-admin`. This view is **not** the same as the Vision Execution “Radar” tab (see below).
- **Vision Execution** (`mainView === 'vision_execution'`): Renders `VisionExecutionView`, which contains **all 11 tabs** (Meeting Capture, Core Profile, Ideas, Initiatives, Projects, Tasks, People & Capacity, Assets, Radar, Roadmap, Executive View).
- **Data source:** Vision Execution tabs (except the two placeholders) load from the **live Vision Execution API** (`/vision-execution`). Radar **Home** (the default landing page) is built from **seed domain data** via `DomainProvider` / `getSeedDomain()` in `frontend/src/domain/` — it does **not** call the VE API. So “Radar Home” and the “Radar” tab inside Vision Execution are different: Home = seed-based dashboard; Radar tab = API `/radar` + Layer 1 signals.

---

## 2. Core Profile tab

**Purpose:** Define the strategic lens (e.g. “Digital Phil”): how the organization sees itself, its goals, constraints, and kill philosophy. Used as context when evaluating initiatives.

**Backend:** `core_profiles` table. API: `GET/POST /core-profiles`, `GET/PATCH /core-profiles/{id}`. Service/storage in `local_ai/vision_execution/`.

**UI:** List of profiles (name + truncated core_definition) in a left panel; “Add profile” opens a create form. Clicking a profile opens **CoreProfileDetailPanel** on the right.

**Editable fields (all in detail panel):**

| Field | Type | Description |
|-------|------|-------------|
| name | text | Profile name |
| core_definition | textarea | Who we are / what we do |
| current_goals | textarea | Current goals |
| growth_focus_12_months | textarea | 12‑month growth focus |
| economic_engine | textarea | How we make money / sustain ourselves |
| non_negotiables | textarea | Non‑negotiables |
| strategic_filter | textarea | What we say yes/no to |
| current_constraints | textarea | Current constraints |
| capacity_limit | textarea | Capacity limits |
| kill_philosophy | textarea | When we kill or pause work |
| strength_positioning | textarea | Strengths and positioning |

**Internal use:** The **first** core profile (from `list_core_profiles()`) is passed to **initiative evaluate**: `core_definition` + `current_goals` are concatenated and sent as `core_profile_summary` to the LLM. So only one profile currently influences AI evaluation; the UI allows multiple for flexibility.

**Pricing/ROI/valuation:** None in Core Profile. It is narrative context only. Economic framing is in the text field `economic_engine`, not computed.

---

## 3. Ideas tab

**Purpose:** Raw possibilities and hypotheses before they become initiatives. Capture only; no scoring or valuation here.

**Backend:** `ideas` table. API: `GET/POST /ideas`, `GET/PATCH /ideas/{id}`.

**UI:** List of ideas (title + status); “Add idea” opens create form. Clicking an idea opens **IdeaDetailPanel**.

**Editable fields:**

| Field | Type | Description |
|-------|------|-------------|
| title | text | Short title |
| summary | textarea | Summary |
| description | textarea | Description |
| status | dropdown | Captured, Clarifying, Contextualized, Evaluated, Advanced, Parked, Archived |
| created_by | text | Who captured it |
| desired_outcome | textarea | Desired outcome |
| tags | text (comma-separated) | Tags |
| linked_people | text (comma-separated) | Linked people IDs/names |
| linked_assets | text (comma-separated) | Linked asset IDs/names |
| linked_ideas | text (comma-separated) | Linked idea IDs |

**Internal calls:** None for weighting or valuation. Ideas are referenced by initiatives via `source_idea_id` (dropdown in Initiative detail). No automatic promotion from Idea → Initiative; that’s manual.

---

## 4. Initiatives tab

**Purpose:** Committed strategic efforts. Supports manual scoring, AI evaluation (cost/timeframe/alignment/next step/recommendation), and derived weighted score / approval readiness.

**Backend:** `initiatives` table. API: `GET/POST /initiatives`, `GET/PATCH /initiatives/{id}`, `POST /initiatives/{id}/evaluate`. Derived fields computed in `local_ai/vision_execution/derived.py` and attached on read (not stored).

**UI:** List or **timeline** view (initiative → projects → tasks). List: initiatives with title + status; “Add initiative” opens create form. Clicking an initiative opens **InitiativeDetailPanel**. Panel includes “Evaluate Initiative” and “Apply” for AI proposal.

**Editable fields (stored):**

| Field | Type | Description |
|-------|------|-------------|
| title | text | Initiative title |
| brief | textarea | Brief description |
| status | dropdown | Draft, Evaluating, Approved, Active, Paused, Complete, Killed |
| owner_id | dropdown | Person (from persons list) |
| source_idea_id | dropdown | Source idea or None |
| priority_rank_manual | number | 0–10 (normalized to 0–5 in formula) |
| strategic_value_manual | number | 0–10 (normalized to 0–5) |
| energy_impact_manual | number | 0–10 (normalized to 0–5) |
| estimated_cost_ai | text | AI-suggested cost (e.g. “low / 2–3 weeks budget”) |
| estimated_timeframe_ai | text | AI-suggested timeframe |
| philosophical_alignment_ai | text | AI alignment note |
| next_step_ai | text | AI next step |
| recommendation | text | AI recommendation (e.g. Approve/Incubate/Park/Reject) |
| required_people | text | Comma-separated |
| required_assets | text | Comma-separated |
| dependencies | textarea | Dependencies |
| risks | textarea | Risks |
| kill_criteria | textarea | When to kill |
| notes | textarea | Notes |
| counts_toward_capacity | number | 1 = counts toward capacity |
| manual_override | textarea | Override note |

**Weighting / valuation (internal):**

- **Manual scores:** The three manual inputs `priority_rank_manual`, `strategic_value_manual`, `energy_impact_manual` are each normalized to 0–5 (values &gt; 5 clamped to 5). If **all three** are present:
  - **weightedScore** = (0.4×priority + 0.4×strategic + 0.2×energy) × (100/5) → 0–100. If any of the three is null, `weightedScore` is null.
- **approvalReady** (derived boolean): true when `weightedScore` ≥ 60, `brief` is non-empty, and `status` is Draft or Evaluating.
- **returnOnTime** (derived 0–1): 1.0 if both `estimated_cost_ai` and `estimated_timeframe_ai` are non-empty; 0.5 if exactly one; 0.0 if neither. No monetary valuation or ROI formula — purely “do we have cost and time estimates?”

**Evaluate flow:** “Evaluate Initiative” → `POST /initiatives/{id}/evaluate`. Backend loads initiative (title, brief), optionally first core profile (core_definition + current_goals), calls `initiative_evaluate.evaluate_initiative()`. LLM returns: `estimated_cost_ai`, `estimated_timeframe_ai`, `philosophical_alignment_ai`, `next_step_ai`, `recommendation`. Response is **proposal only**; no DB write. User clicks “Apply” in UI → frontend PATCHes initiative with those values and POSTs a **decision** (`decision_type: 'evaluation_applied'`, `ai_proposal_snapshot` = proposal, `final_values_snapshot` = applied payload). So there is **no automatic pricing or return-on-investment calculation** — only free-text cost/timeframe and a single recommendation string.

**Unfinished direction:** Design doc mentioned Phase 4 `ai.py` for “assess valuation, next-step suggestions.” That module was never added. Valuation today is: (1) manual three scores → weightedScore, (2) AI narrative cost/timeframe/recommendation. No NPV, no ROI %, no pricing engine.

---

## 5. Projects tab

**Purpose:** Concrete workstreams under initiatives (or unanchored). Timeline or list; link to initiative and capacity.

**Backend:** `projects` table. API: `GET/POST /projects`, `GET/PATCH /projects/{id}`. Derived in `derived.py`.

**UI:** List grouped by initiative + “Unanchored” section, or timeline. “Add project” opens create form. Clicking a project opens **ProjectDetailPanel**. From Initiatives timeline, projects/tasks are selectable in the same view.

**Editable fields:**

| Field | Type | Description |
|-------|------|-------------|
| title | text | Project title |
| brief | textarea | Brief |
| status | dropdown | Draft, Ready, Active, Blocked, Complete, Parked |
| initiative_id | dropdown | Parent initiative or None |
| owner_id | dropdown | Person |
| supporting_owner_ids | text (comma-separated) | Other owners |
| priority | text | Priority label |
| start_date | date | Start |
| end_date | date | End |
| estimated_weekly_hours | number | Hours per week (for capacity) |
| deliverables | textarea | Deliverables |
| complexity | text | Complexity |
| current_focus | text | Current focus |
| next_step_ai | text | Next step |
| notes | textarea | Notes |

**Internal / derived:**

- **duration:** Calendar days between `start_date` and `end_date` (inclusive); null if either missing.
- **completionReadiness:** 0–1. +0.4 if status Ready or Active; +0.3 if deliverables non-empty; +0.3 if next_step_ai non-empty; capped at 1.0.
- **unanchoredFlag:** true when `initiative_id` is null. Used by Radar “unanchored” bucket.

**Pricing/ROI:** None. `estimated_weekly_hours` feeds **capacity** (person-level active hours), not pricing.

---

## 6. Tasks tab

**Purpose:** Smallest work units under a project. Status and assignee drive execution.

**Backend:** `tasks` table. API: `GET/POST /tasks`, `GET/PATCH /tasks/{id}`, `GET /tasks?project_id=...`.

**UI:** List (by project) or timeline. “Add task” opens create form (requires project). Clicking a task opens **TaskDetailPanel**.

**Editable fields:**

| Field | Type | Description |
|-------|------|-------------|
| title | text | Task title |
| description | textarea | Description |
| status | dropdown | Todo, In Progress, Blocked, Done, Dropped |
| assignee_id | dropdown | Person |
| priority | text | Priority |
| estimated_hours | number | Hours estimate |
| due_date | date | Due date |
| dependency_ids | text (comma-separated) | Task IDs |
| completion_criteria | textarea | Criteria |
| notes | textarea | Notes |

**Internal:** No scoring or valuation. Blocked tasks appear in Radar “blocked” bucket.

---

## 7. People & Capacity tab

**Purpose:** People (roles, contact, strengths/needs/wants) and their **weekly capacity**. Capacity is used to compute overcommitment.

**Backend:** `persons` table + `capacity_profiles` table (one row per person: `person_id`, `weekly_capacity_hours`). API: `GET/POST /persons`, `GET/PATCH /persons/{id}`; `GET/PUT /capacity-profiles`, `GET /capacity-profiles/{person_id}`. Capacity derived in `derived.add_capacity_derived()`.

**UI:** List of persons; “Add person” opens create form. Clicking a person opens **PersonDetailPanel**, which includes a **capacity** field (weekly hours) saved via PUT to capacity-profiles.

**Editable fields (person):**

| Field | Type | Description |
|-------|------|-------------|
| name | text | Name |
| role | text | Role |
| relationship_type | text | Relationship type |
| contact_info | text | Contact |
| strengths | textarea | Strengths |
| needs | textarea | Needs |
| wants | textarea | Wants |
| availability | textarea | Availability |
| notes | textarea | Notes |

**Capacity (separate upsert):** `weekly_capacity_hours` (number). Stored in `capacity_profiles` by `person_id`.

**Derived (per person, on read):**

- **activeWeeklyHours:** Sum of `project.estimated_weekly_hours` for projects where this person is `owner_id` or in `supporting_owner_ids`, and project status is Ready or Active.
- **capacityDelta:** activeWeeklyHours − weekly_capacity_hours. Positive = over-committed.
- **overcapacity:** true when capacityDelta &gt; 0. These feed the Radar “overcapacity” bucket.

**Pricing/ROI:** No pay rates or cost-of-capacity. Capacity is hours only.

---

## 8. Assets tab

**Purpose:** Resources and artifacts (tools, systems, documents, etc.) with optional cost and linkage to ideas/initiatives/projects.

**Backend:** `assets` table. API: `GET/POST /assets`, `GET/PATCH /assets/{id}`.

**UI:** List of assets; “Add asset” opens create form. Clicking an asset opens **AssetDetailPanel**.

**Editable fields:**

| Field | Type | Description |
|-------|------|-------------|
| name | text | Asset name |
| asset_type | text | Type (e.g. tool, system, document) |
| owner_id | dropdown | Person |
| status | text | Status |
| availability | text | Availability |
| cost | text | Cost (free text; no numeric pricing engine) |
| time_availability | text | Time availability |
| linked_idea_ids | text (comma-separated) | Idea IDs |
| linked_initiative_ids | text (comma-separated) | Initiative IDs |
| linked_project_ids | text (comma-separated) | Project IDs |
| notes | textarea | Notes |

**Internal:** No weighting or valuation. `cost` is a string. No ROI or depreciation logic.

---

## 9. Radar tab (inside Vision Execution)

**Purpose:** Read-only “what needs attention” view: act now, blocked, overcapacity, unanchored, high-value stalled, kill candidates, plus **signals** from meeting extraction (with acknowledge/resolve/dismiss actions).

**Backend:** `GET /vision-execution/radar` implemented in `local_ai/vision_execution/radar.py`. It loads initiatives, projects, tasks, capacity; applies derived fields; builds buckets. **Signals** from Layer 1: `local_ai.signals.service.list_signals(status_not_in=['resolved','dismissed'])`. Signal updates: `PATCH /vision-execution/signals/{id}` (status, linked_*).

**Bucket rules (from design §12 and radar.py):**

| Bucket | Rule |
|--------|------|
| **act_now** | Initiatives status Approved or Active and (no owner **or** no next_step_ai **or** no linked projects). |
| **blocked** | Projects or tasks with status Blocked. |
| **overcapacity** | People with derived `overcapacity` true (activeWeeklyHours &gt; weekly_capacity_hours). |
| **unanchored** | Projects with initiative_id null. |
| **high_value_stalled** | Initiatives with weightedScore ≥ 70 and status not Active/Complete/Killed. |
| **kill_candidates** | Initiatives with weightedScore &lt; 45 and status not Complete/Killed. |
| **signals** | Layer 1 signals (status not resolved/dismissed); kind = attention, risk, opportunity, blocker. |

**Thresholds:** `HIGH_VALUE_THRESHOLD = 70`, `LOW_SCORE_KILL_THRESHOLD = 45` in radar.py.

**UI:** Six cards for the buckets; each item shows type, title/name, status, reason (for act_now), weighted_score (for initiative buckets), or hours (for overcapacity). Signals card lists each signal with Acknowledge / Resolve / Dismiss (and optional Link) that PATCH the signal and refetch radar.

**Pricing/ROI:** None. Radar is about attention and capacity, not money.

---

## 10. Roadmap tab

**Current state:** Placeholder only. Renders: “Roadmap view (Phase 5): timeline from initiatives and projects. Coming soon.”

**Intended direction (from design):** View-only timeline over approved/active path through the initiative → project → task tree. No roadmap-specific table; would be a view over existing entities. Phase 5 = not implemented.

---

## 11. Executive View tab

**Current state:** Placeholder only. Renders: “Executive view (Phase 5): summary, drift, opportunities, capacity warnings. Coming soon.”

**Intended direction (from design):** Summary, drift, opportunities, capacity warnings. Design doc mentioned **ExecutiveSnapshot** and deferred it to Phase 5. No table or API exists for it.

---

## 12. Meeting Capture tab

**Purpose:** Paste meeting notes → extract ideas, initiatives, projects, tasks, assets, people, signals. Optional context (existing entities) for linking. Supports single-shot extraction or long-meeting path (segment → rolling prior → synthesis). Commit flow creates entities in VE and optionally creates signals. Not a storage tab per se; it’s an extraction UI that **writes** into Ideas, Initiatives, Projects, Tasks, Assets, and Signals.

**Internal:** Uses `local_ai.vision_execution.meeting_extract` and canonization; POST to `/extract-meeting`, `/extract-meeting-segments`, `/extract-meeting-synthesis`; then commit via existing POST ideas/initiatives/projects/tasks and POST signals. No weighting or pricing in extraction.

---

## 13. Decisions (not a tab; used by tabs)

**Purpose:** Append-only log of user decisions for future “personality learning” and analysis. No UI tab; the frontend POSTs a decision when the user applies an initiative evaluation or approves/rejects an initiative.

**Backend:** `decisions` table. API: `POST /decisions`, `GET /decisions?entity_type=&entity_id=&limit=`. Columns: id, user_id, entity_type, entity_id, decision_type, ai_proposal_snapshot (JSON), final_values_snapshot (JSON), created_at.

**decision_type values in use:** `evaluation_applied`, `initiative_approved`, `initiative_rejected`, `intake_graduate_task`, `transcript_candidate_decision`, etc. Design doc also mentioned **evaluation_overridden**, **priority_change**, **manual_score_override** as planned but not wired.

---

## 14. Internal calls summary: weighting, valuation, pricing, ROI

- **Weighting:** Only initiatives have a numeric “score.” It is the **weighted average** of three manual scores (priority 0.4, strategic 0.4, energy 0.2), normalized to 0–5 each, then scaled to 0–100. Implemented in `derived.add_initiative_derived()`. No other entity has a comparable score.
- **Valuation:** Initiative “evaluate” returns **text** (estimated_cost_ai, estimated_timeframe_ai, recommendation). No monetary valuation, no NPV, no ROI percentage. `returnOnTime` is only “do we have cost + timeframe filled?”
- **Pricing:** Assets have a free-text `cost` field. Initiatives have `estimated_cost_ai` (text). No pricing engine, no currency, no rollups.
- **Return on investment:** Not computed anywhere. Design doc pointed to Phase 4 `ai.py` for “assess valuation” — not implemented.
- **Capacity:** People have `weekly_capacity_hours`. Projects have `estimated_weekly_hours`. Derived `activeWeeklyHours` and `overcapacity` are the only “capacity” math.

---

## 15. Unfinished direction (where it was heading when sidestepped)

- **Phase 4 (design):** `scoring.py` (derived) exists as `derived.py`. `council.py` and `ai.py` were listed for “council integration” and “assess valuation, next-step suggestions” — **not added**. So: no council-driven initiative scoring, no valuation module.
- **Phase 5:** Roadmap and Executive View are placeholders. ExecutiveSnapshot was deferred; no schema or API. Roadmap was intended as a view over the initiative/project/task tree (approved/active path).
- **Initiative tree (design §7):** The model is already a “sparse tree” (idea → initiative → project → task). No schema change was made; a future **view/abstraction** (e.g. parent_id, lineage_path) could sit on top. Not implemented.
- **Decision types:** evaluation_overridden, priority_change, manual_score_override were planned for the decisions table; only evaluation_applied and initiative_approved/rejected (and a few others) are used today.
- **Radar Home vs Vision Execution:** Radar **Home** (default landing) uses **seed data** from `getSeedDomain()`. Vision Execution (all tabs) uses the **live API**. So the home dashboard does not reflect the same data as the VE tabs unless the backend is seeded or the app is changed to feed Home from the API.

---

## 16. File and API reference (short)

| Area | Backend | API prefix | Frontend |
|------|---------|------------|----------|
| Core Profile | storage.py, service.py, models.py | /vision-execution/core-profiles | VisionExecutionView, CoreProfileDetailPanel |
| Ideas | same | /vision-execution/ideas | IdeaDetailPanel |
| Initiatives | same + derived.py + initiative_evaluate.py | /vision-execution/initiatives, .../evaluate | InitiativeDetailPanel, Evaluate/Apply |
| Projects | same + derived | /vision-execution/projects | ProjectDetailPanel |
| Tasks | same | /vision-execution/tasks | TaskDetailPanel |
| People | same | /vision-execution/persons | PersonDetailPanel |
| Capacity | same + derived | /vision-execution/capacity-profiles | PersonDetailPanel (capacity field) |
| Assets | same | /vision-execution/assets | AssetDetailPanel |
| Radar | radar.py, signals service | /vision-execution/radar, .../signals | Radar tab (VE), RadarHomePage (seed) |
| Decisions | storage | /vision-execution/decisions | Used by initiative Apply/Approved/Rejected |
| Roadmap / Executive | — | — | Placeholder “Phase 5” |

This is the exhaustive picture of what’s behind the Core Profile, Ideas, Initiatives, Projects, Tasks, People & Capacity, Assets, Radar, Roadmap, and Executive View tabs, their editable fields, and the internal weighting/valuation/pricing/ROI behavior (and its limits).
