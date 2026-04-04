# Singular core profile — audit & smallest shippable plan

<!--
Status: Convergence audit (implementation not started)
Last updated: 2026-04-03
-->

**Goal:** Product truth = **one canonical core profile** per signed-in user (workspace = user in VE DB today) and **perspectives as lenses**, without a large migration.

**Important discovery:** **`is_primary` already exists** on `core_profiles` (migration + `set_core_profile_primary` + `PATCH /core-profiles/{id}/set-primary`). First created profile per user is primary when count was 0; additional creates get `is_primary=0`. **Schema is largely done**; gaps are **UX/copy**, **deterministic resolution everywhere**, and **legacy rows** with multiple profiles and no primary set.

---

## A. File-by-file audit

### A.1 Backend — SQLite / storage

| Location | Role |
|----------|------|
| [`local_ai/vision_execution/storage.py`](../../local_ai/vision_execution/storage.py) | `core_profiles` CRUD; `list_core_profiles` ordered **`ORDER BY is_primary DESC, updated_at DESC`**; `create_core_profile` sets `is_primary=1` only when user had **zero** rows; `set_core_profile_primary`; migration `_migrate_core_profile_is_primary` backfills **only** users with exactly **one** row. |
| [`local_ai/vision_execution/models.py`](../../local_ai/vision_execution/models.py) | `CoreProfileCreate` / `Update`; `row_to_core_profile` includes `is_primary`. |
| [`local_ai/vision_execution/service.py`](../../local_ai/vision_execution/service.py) | Thin pass-through for list/get/create/update/`set_core_profile_primary`. |

### A.2 Backend — API

| Location | Role |
|----------|------|
| [`api/routes/vision_execution.py`](../../api/routes/vision_execution.py) | `GET/POST/PATCH /core-profiles`, `PATCH …/set-primary`, reconcile/conversation. **`evaluate_idea`** / **`evaluate_initiative`**: load `profiles = list_core_profiles`, then **`p = profiles[0]`** for `build_core_profile_summary` — **deterministic only because list order** puts primary first; **fails** if no row has `is_primary=1` and order falls back to `updated_at` only. **`_resolve_active_placement_profile`**: optional **`profile_id` / `active_profile`** from body — **ad hoc** profile selection for placement/suggest flows. |

### A.3 Backend — LLM / context (core profile as context)

| Location | Role |
|----------|------|
| [`local_ai/vision_execution/core_profile_reconcile.py`](../../local_ai/vision_execution/core_profile_reconcile.py) | Reconcile by explicit `profile_id` (route). |
| [`local_ai/vision_execution/core_profile_conversation.py`](../../local_ai/vision_execution/core_profile_conversation.py) | Conversation by explicit `profile_id`. |
| [`local_ai/delegation/core_profile_reconcile.py`](../../local_ai/delegation/core_profile_reconcile.py) | Delegation reconcile. |
| [`local_ai/vision_execution/core_profile_context.py`](../../local_ai/vision_execution/core_profile_context.py) | `build_core_profile_summary` — consumer passes **which** row. |
| [`local_ai/vision_execution/idea_evaluate.py`](../../local_ai/vision_execution/idea_evaluate.py) / [`initiative_evaluate.py`](../../local_ai/vision_execution/initiative_evaluate.py) | Accept `core_profile_summary` string from caller (no row pick). |

### A.4 Frontend — types & panels

| Location | Role |
|----------|------|
| [`frontend/src/vision-execution/types.ts`](../../frontend/src/vision-execution/types.ts) | `CoreProfile` + optional **`is_primary`**; comment already says canonical / at most one. |
| [`frontend/src/vision-execution/coreProfilePanels.tsx`](../../frontend/src/vision-execution/coreProfilePanels.tsx) | `BrandStructuredProfilePanel` (single `profileId`), `CreateCoreProfileForm`, conversation/reconcile wiring. **No** “set as primary” / multi-row switcher. |
| [`frontend/src/vision-execution/coreProfileTrace.ts`](../../frontend/src/vision-execution/coreProfileTrace.ts) | Trace helpers for reconcile/conversation. |

### A.5 Frontend — App shell / Foundation

| Location | Role |
|----------|------|
| [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | Loads **`/core-profiles`** into `perspectivesCoreProfiles`. **`brandCoreProfileId`**: `find(is_primary)` else **`[0]`** — matches list order. **`CreateCoreProfileForm`** only when **`!brandCoreProfileId`** — **no second profile from Foundation** via happy path. **`POST /core-profiles`** in `handleCreateCoreProfile` still callable if UI ever exposed. **Influences:** `perspectiveInfluenceLinkLists.coreProfiles` maps **all** rows → implies **peer cores** in link UI. Copy: “Create a core profile row once”, “Brand is your trained core profile”. |

### A.6 Frontend — Perspectives list (Foundation)

| Location | Role |
|----------|------|
| [`frontend/src/perspectives/PerspectivesView.tsx`](../../frontend/src/perspectives/PerspectivesView.tsx) | Actor grid; **Brand** row shows `brandCoreProfileDisplayName`; **no** list of multiple core DB rows. |
| [`frontend/src/perspectives/InfluencesLinksSection.tsx`](../../frontend/src/perspectives/InfluencesLinksSection.tsx) | Picker for **`coreProfiles`** (all rows) when linking influences — **multi–core profile implied**. |
| [`frontend/src/perspectives/entityInfluences.ts`](../../frontend/src/perspectives/entityInfluences.ts) | Types/helpers for influence edges. |

### A.7 Frontend — Vision Execution (Team / graph)

| Location | Role |
|----------|------|
| [`frontend/src/vision-execution/VisionExecutionView.tsx`](../../frontend/src/vision-execution/VisionExecutionView.tsx) | **`loadCoreProfilesForInfluenceBundle`**: `GET /core-profiles` → **all** rows for person influence picklists / link lists (same as Foundation influences). Copy points users to **Foundation** for core profile. |
| [`frontend/src/vision-execution/focus/profileGraphSliceResolver.ts`](../../frontend/src/vision-execution/focus/profileGraphSliceResolver.ts) / [`graphSliceTypes.ts`](../../frontend/src/vision-execution/focus/graphSliceTypes.ts) | Graph snapshot includes **`profiles[]`** + **`activeProfileId`** — multi-node model. |
| [`frontend/src/vision-execution/focus/useCoreProfileVoiceInsert.ts`](../../frontend/src/vision-execution/focus/useCoreProfileVoiceInsert.ts) | Voice insert for core profile fields. |

### A.8 Frontend — misc

| Location | Role |
|----------|------|
| [`frontend/src/components/ZenafPresence.tsx`](../../frontend/src/components/ZenafPresence.tsx) | Uses `brandCoreProfileId` for conversation storage key. |
| [`frontend/src/foundation/AspirationsFoundationPanel.tsx`](../../frontend/src/foundation/AspirationsFoundationPanel.tsx) | VE API (aspirations); sits next to Brand panel. |
| [`frontend/src/vision-execution/recognitionDecisions.ts`](../../frontend/src/vision-execution/recognitionDecisions.ts) | `postCoreProfileIdentityRecognition` — check call sites for profile id. |
| [`frontend/src/auth/ConsentOnboardingGate.tsx`](../../frontend/src/auth/ConsentOnboardingGate.tsx) | Copy mentions “profile/core profile learning” (permission copy only). |
| [`frontend/src/settings/sections/PermissionsSection.tsx`](../../frontend/src/settings/sections/PermissionsSection.tsx) | Hint mentions core-profile guidance. |

### A.9 Scripts & tooling

| Location | Role |
|----------|------|
| [`scripts/seed_vision_execution_from_repo_docs.py`](../../scripts/seed_vision_execution_from_repo_docs.py) | Uses `list_core_profiles`, **`profiles[0]`** — should align with canonical helper when introduced. |

### A.10 Documentation (non-exhaustive; key truth)

| Location | Role |
|----------|------|
| [`docs/01_TRUTH/SYSTEM_REFERENCE.md`](../01_TRUTH/SYSTEM_REFERENCE.md) | §1.4a / §2.6 — target one core, many perspectives; as-built multi-row. |
| [`docs/01_TRUTH/ACTIVE_VS_PLANNED.md`](../01_TRUTH/ACTIVE_VS_PLANNED.md) | Planned slice: UI gates, auto-select canonical, optional `is_primary` — **partially obsolete** (column exists). |
| [`docs/01_TRUTH/CODEBASE_INVENTORY.md`](../01_TRUTH/CODEBASE_INVENTORY.md) | Notes multi `core_profiles` + product direction. |
| [`docs/02_ACTIVE_DESIGN/CORE_PROFILE_ARCHITECTURE.md`](CORE_PROFILE_ARCHITECTURE.md) | Ontology + prompts; says “Foundation UI lists” multiple — **slightly stale** vs current Foundation (single Brand path; multi exposed via influences). |
| [`docs/01_TRUTH/TRUTH_CONVERGENCE.md`](../01_TRUTH/TRUTH_CONVERGENCE.md) | User core vs archetypes. |
| [`api/routes/studio_routes.py`](../../api/routes/studio_routes.py) | API inventory mentions core-profile routes. |

---

## B. Current conflicts (product vs implementation)

1. **Multiple equal cores (implied)**  
   - API still allows **`POST /core-profiles`** for additional rows.  
   - **Influences** UI exposes **every** row as linkable (`coreProfiles` map from full list).  
   - **Vision Execution Team** loads full list for the same pickers.

2. **Ad hoc selection**  
   - **`_resolve_active_placement_profile`** honors client `profile_id` / `active_profile` — correct for “which snapshot”, but can **diverge** from “canonical core” if client sends another id.  
   - **`brandCoreProfileId`** uses `is_primary` OR first list element — if **no** primary flag on any row, “canonical” = **most recently updated**, which may not match user intent.

3. **Foundation vs VE vs Perspectives**  
   - **Foundation / Perspectives** view: Brand = one resolved id; good.  
   - **VE Team**: still surfaces **all** core rows for influences; doc says core lives on Foundation — **split brain** for “where do I manage the second row?”.  
   - **Graph / focus** types still model **`profiles[]`** + `activeProfileId` as a multi-profile graph.

4. **Docs vs UI**  
   - Some docs say Foundation “lists” multiple core profiles; **current UI** does not list them for editing, but **influences** still treat them as peers.

5. **Migration gap**  
   - Users with **multiple** profiles and **zero** `is_primary=1` (never backfilled) rely on **`updated_at`** ordering only — **fragile** canonical.

---

## C. Smallest safe patch sequence (recommended)

**Principle:** UI/copy and **one shared resolver** first; **avoid** new schema ( **`is_primary` is already enough** ).

### Phase 1 — Copy + UI gating (low risk)

1. **Foundation header / aside copy** in [`App.tsx`](../../frontend/src/App.tsx): explicit **“One core profile per account; perspectives are lenses.”** Replace any wording that suggests adding another full core.
2. **`CreateCoreProfileForm`**: when `brandCoreProfileId` is null, keep create; when **multiple rows already exist** (edge API path), show **short explanation** + link to settings/support — do **not** encourage a second “Brand”.
3. **Hide or narrow “core profile” targets in influences** when singularity is on: e.g. only offer **canonical** row in `InfluencesLinksSection` / VE influence pickers, **or** label non-primary rows “Legacy — merge or set primary” (lighter: **only show canonical** in v1 slice).
4. Update **[`CORE_PROFILE_ARCHITECTURE.md`](CORE_PROFILE_ARCHITECTURE.md)** Foundation bullet to match **current** UI + this plan (remove “lists them” if influences are gated).

### Phase 2 — Deterministic canonical resolution (shared, testable)

5. **Python helper** (e.g. `local_ai/vision_execution/core_profile_canonical.py`):  
   `def canonical_core_profile_for_user(user_id: str) -> dict | None`  
   - Prefer row with **`is_primary`** (if exactly one, or if any — define: **first** `is_primary=1` from `list_core_profiles` order).  
   - If **none** primary: **pick one deterministically** (e.g. `updated_at DESC` **documented**) **and optionally** call `set_core_profile_primary` once (auto-heal) — **or** run a **one-time** admin migration script; prefer **explicit auto-heal on read** only with logging if you want zero manual DB ops.

6. **Use helper** in [`vision_execution.py`](../../api/routes/vision_execution.py) **evaluate_idea** / **evaluate_initiative** instead of raw `profiles[0]` (keeps behavior but **names** the rule).

7. **Frontend helper** `selectCanonicalCoreProfile(profiles: CoreProfile[]): CoreProfile | null` — same rule as server; use for `brandCoreProfileId` and any picker reduction.

8. **`PATCH /core-profiles/{id}/set-primary`**: expose a minimal **“Use as canonical core”** control in UI **only when** `profiles.length > 1` (settings strip or Brand panel overflow) — no new API.

### Phase 3 — API policy (optional, slightly stronger)

9. **`POST /core-profiles`**: when user already has **≥1** row, return **409** with clear detail **or** allow but immediately **demote** to non-primary (current behavior) — **product choice**. Smallest slice: **409** if you want hard singularity; **softer**: allow for imports but hide in UI.

### Phase 4 — Placement / client body

10. **`_resolve_active_placement_profile`**: after resolving by `profile_id`, **optional** assert `profile_id == canonical.id` **or** merge canonical fields as base — only if placement must never use a “secondary” row; **defer** unless product requires.

---

## D. What not to change yet

- **Do not** merge or delete duplicate `core_profiles` rows automatically without user consent.  
- **Do not** change **perspectives** storage model (`user_council_workspace` / localStorage) in this slice.  
- **Do not** reroute **all** council/guidance to core profile in one go — **separate** convergence thread (trace/guidance).  
- **Do not** rename structured fields or break **`/core-profiles/{id}/reconcile|conversation`** contracts.  
- **Do not** require **workspace**-scoped cores until multi-tenant product definition exists (today VE is **per user id**).

---

## E. Success criteria (for this lane)

- User-facing copy consistently describes **one core**, **many perspectives**.  
- **Canonical row** is chosen by **one** function on server (and mirrored on client for display).  
- **Idea/initiative evaluate** always documents which profile summary was used (same as canonical).  
- **No** accidental second core from default Foundation flow; **API** behavior documented if second row still allowed.

---

## F. Relation to existing planned doc

Update **[`ACTIVE_VS_PLANNED.md`](../01_TRUTH/ACTIVE_VS_PLANNED.md)** “Singular core profile” bullet after implementation: note **`is_primary` shipped**, work remaining = **UI + canonical helper + optional POST gate**.
