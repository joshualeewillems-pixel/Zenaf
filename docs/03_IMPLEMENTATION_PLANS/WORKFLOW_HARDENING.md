# Workflow Hardening Pass — Commit Preview, UI Honesty, Person Assignment, Tests

This pass focuses on **workflow hardening, UI honesty, and end-to-end trust** after the commit-alignment fix. No backend structure expansion.

---

## 1. Files changed

| File | Change |
|------|--------|
| `frontend/src/meeting-intelligence/commitStaged.ts` | Exported `getDataTitle`, added `buildCommitPreview()`, `CommitPreviewLine` type, and in-code comment documenting **person assignment semantics** per entity type. |
| `frontend/src/meeting-intelligence/index.ts` | Export `buildCommitPreview` and `CommitPreviewLine`. |
| `frontend/src/meeting-intelligence/ReviewExtractionScreen.tsx` | **Commit summary** block when there are approved items: shows what will be created, as what type, use-existing, parent link, and people/asset counts. Clarifying copy under parent link: "Only this parent link is persisted." |
| `frontend/src/meeting-intelligence/LinkChooser.tsx` | Copy update: "Only this parent link is persisted." |
| `tests/test_vision_execution_commit_align.py` | **New.** Migration test (adds `required_assets`, `required_asset_ids`, `linked_asset_ids` when missing). Model tests: `ProjectCreate.required_assets`, `TaskCreate.required_asset_ids`, `SignalCreate.linked_asset_ids`. |
| `docs/03_IMPLEMENTATION_PLANS/WORKFLOW_HARDENING.md` | This document. |

---

## 2. How commit preview works

- **When:** When there is at least one approved item (including approved signals), a **Commit summary** block is shown above the commit error area and above the section grid.
- **Content:** For each approved item that would be committed:
  - **Create as &lt;type&gt;** or **Use existing** (no duplicate).
  - **Title** (truncated with tooltip).
  - **Parent:** "→ under initiative" (or project/task/idea) when the item has a parent link that will be persisted (parent/unset relationship type).
  - **People / assets:** Count of assigned people and assigned assets (e.g. "2 people · 1 asset").
- **Source of truth:** `buildCommitPreview(staging)` in `commitStaged.ts`:
  - Uses the same logic as commit: collects approved items from all sections, uses **effectiveType = overrideType ?? kind**, sorts by commit order, includes approved signals.
  - Does not call the API; it only reads staging and returns a list of `CommitPreviewLine` (kind, effectiveType, title, parent?, personCount, assetCount).
- **Placement:** Inline in the review screen, directly under the header/Close/Commit row, so users can verify the outcome before clicking **Commit accepted items**.

---

## 3. Relationship options: exposed vs hidden

- **Exposed and persisted:**  
  - **Use as existing (no duplicate):** Sets `acceptedExistingId`; commit skips creation.  
  - **Place under as child:** Sets `parentLink: { parentType, parentId }` with no `relationshipType` (treated as parent). Commit uses this for hierarchy (initiative_id, project_id, source_idea_id, signal linked_*_id).
- **Copy:** LinkChooser and the card text both state that **only this parent link is persisted**. No other relationship types are offered in the UI.
- **Hidden / not exposed:**  
  - **Related, depends_on, supports, informed_by** exist only in the TypeScript type `StagedRelationshipType`. They are **not** shown as options in LinkChooser or anywhere else, so users are not led to believe they are committed.  
- **Conclusion:** Only supported behavior (parent link + use existing) is exposed; unsupported relationship types are not shown and are therefore not misleading.

---

## 4. Person assignment: how it maps per entity type

From the review UI, **assignedPersonIds** is a single list; commit uses it consistently as below. Only the **first** selected person is used for owner/assignee; supporting/linked/required people are **not** set from the review UI.

| Entity   | API field(s) used      | Review behavior |
|----------|------------------------|------------------|
| **Idea** | —                      | No person field in create API; assignedPersonIds ignored. |
| **Initiative** | `owner_id`       | `assignedPersonIds[0]` → owner_id. |
| **Project** | `owner_id`         | `assignedPersonIds[0]` → owner_id. supporting_owner_ids not set from review. |
| **Task** | `assignee_id`          | `assignedPersonIds[0]` → assignee_id. |
| **Asset** | `owner_id`         | `assignedPersonIds[0]` → owner_id. |
| **Person** | —                   | N/A (entity is the person). |
| **Signal** | —                    | No person assignment. |

So: **owner** (initiative, project, asset), **assignee** (task); no supporting/linked/required people from the review layer. This is documented in a comment in `commitStaged.ts` and here.

---

## 5. Test coverage added

| Test | Scope | What it covers |
|------|--------|----------------|
| `test_migration_adds_asset_columns` | Backend | Migration adds `required_assets` (projects), `required_asset_ids` (tasks), `linked_asset_ids` (signals) when columns are missing (e.g. existing DBs). |
| `test_project_create_model_accepts_required_assets` | Backend | `ProjectCreate` accepts and defaults `required_assets`. |
| `test_task_create_model_accepts_required_asset_ids` | Backend | `TaskCreate` accepts and defaults `required_asset_ids`. |
| `test_signal_create_model_accepts_linked_asset_ids` | Backend | `SignalCreate` accepts and defaults `linked_asset_ids`. |

**Test matrix (documented; E2E or integration tests can be added later):**

- **Cross-type override commit:** Card from one section with overrideType set to another type → commit creates the overridden type (covered by commit logic; no dedicated E2E yet).
- **Use existing = no duplicate:** `acceptedExistingId` set → commit skips creation (covered by commit logic; no dedicated E2E yet).
- **Parent placement:** parentLink with parent type → correct FK set (initiative_id, project_id, source_idea_id, signal linked_*; covered by commit logic).
- **Asset persistence:** assignedAssetIds → required_assets / required_asset_ids / linked_asset_ids (backend models and migration tested; full flow not E2E tested).
- **Person persistence:** assignedPersonIds[0] → owner_id / assignee_id (documented; no dedicated test).
- **Mixed commit batch:** Multiple types in one commit, order and resolution (covered by `collectApprovedByEffectiveType` and commit order; no dedicated E2E).
- **DB migration safety:** Old DBs get new columns without data loss (test_migration_adds_asset_columns).

Frontend unit tests for `buildCommitPreview` (e.g. with a test runner like Vitest) can be added when the frontend test setup exists.

---

## 6. Remaining limitations

- **Commit preview** is derived from the same staging state as commit but does not re-validate project_id resolution for tasks (e.g. missing parent may still error at commit time).
- **Person assignment:** Only the first selected person is used; supporting/linked/required people are not set from the review UI.
- **Relationship types:** Only parent (and use existing) are supported and shown; other types remain in the type system for possible future use.
- **E2E tests:** Full commit flow (API + UI) is not covered by automated E2E tests; coverage is backend model/migration plus documented matrix.

---
## 7. Merged legacy: Review Workflow Usability & Persistence Pass
This section consolidates UX honesty + reviewer usability improvements that were previously documented as a separate pass.

### 7.1 Summary / description never blank
- `getDisplaySummary()` ensures every review card gets a populated summary/description chain (structured summary → notes/rationale → source excerpt → fallback `"—"`).

### 7.2 People / Assets: replace native multi-selects with chip-based selector
- Introduced `EntityChipSelect` (searchable + chips UI) so people/assets edits are consistent and fast.

### 7.3 Link workflow: confirmation + chooser closes
- `LinkChooser` calls `onClose()` after `onChoose()` so the user doesn’t get stuck in an ambiguous state.
- Cards show a clear block for “Use existing” vs “Place under” with Change/Clear affordances.

### 7.4 Progressive review state (chunk failure / partial extraction)
- In `VisionExecutionView`, staging is updated after each chunk.
- Review state is preserved across tab switches via `sessionStorage` and cleared on successful commit.

### 7.5 Type distribution fix (avoid dropping chunks’ non-idea data)
- Frontend merge logic now preserves projects/assets/peopleReferences/signals from segment responses, rather than dropping them.

---
## 8. Merged legacy: Review UI ↔ Commit Alignment Pass
This section consolidates the “what the user edits is what gets committed” alignment rules.

### 8.1 Commit routing uses effectiveType (overrideType wins)
- Commit routing uses `effectiveType = overrideType ?? kind`, not the original section the card came from.

### 8.2 Relationship types: only parent relationship is persisted today
- Only “parent” (or unset) is used for hierarchy FKs during commit.
- Other relationship types remain in the type system but are not yet committed to a generic relationship store.

### 8.3 Assets persistence mapping is explicit by entity type
- Initiative → `required_assets`
- Project → `required_assets`
- Task → `required_asset_ids`
- Signal → `linked_asset_ids`

### 8.4 Person assignment semantics
- `assignedPersonIds[0]` is used for owner/assignee fields depending on entity type.
- Supporting/linked/required people are not set from the review layer in this MVP review/commit flow.
