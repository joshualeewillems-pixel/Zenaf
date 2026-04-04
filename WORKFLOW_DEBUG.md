# File Sorter Workflow — Debug Report

## A. Actual current execution path (after fixes)

1. **Select folder** — User sets `folderPath`. No API call.
2. **Analyze** — User clicks "Run Analyze" → `runMode('analyze', path)` → POST `/run` mode=analyze, params={ folder_path }. Backend `analyze_file_steward_folder(path)`. **Source of truth:** `lastAnalyzeResult`.
3. **Optional assess / reassess / web** — User clicks "Run Assess uncertainty" → `runMode('assess', path)` → POST mode=assess_uncertainty. Backend calls `_run_simulate(params)` (no suggested_folders), then filters low-confidence; returns `simulate_tree` in response. **Source of truth:** `lastAssessResult` (and `lastAssessResult.simulate_tree` for step 2 tree only). **Assess no longer writes to `lastSimulateResult`.**
4. **Recommend folders** — User clicks "Run Suggest Folders" → `runMode('recommend', path)` → POST mode=recommend, params={ folder_path }. Backend `recommend_child_folders(path)` — **does not receive analyze/assess context;** runs independently. **Source of truth:** `lastRecommendResult`. **Side effect:** `setLastSimulateResult(null)` so previous simulation is invalidated.
5. **User edits folder recommendations** — Reject/add custom. **Approved list:** `approvedFolders` = useMemo( suggested − rejected + custom ). Single derived source for step 4 button and any context that needs "current approved list".
6. **Simulate** — User clicks "Run simulation" → `runMode('simulate', path, { suggested_folders: approvedFolders })` → POST mode=simulate, params={ folder_path, suggested_folders }. Backend `simulate_folder_plan(path, allowed_folders=params.suggested_folders)`. **Source of truth:** `lastSimulateResult` (set only here).
7. **User reviews tree** — Step 4 shows `<SimulateTreeGraphical data={lastSimulateResult} />`. Step 5 shows Accept/Save when `lastSimulateResult` is set.
8. **Accept or save for later** — Buttons visible when `lastSimulateResult` exists; handlers are placeholders.

---

## B. Exact mismatch points (and how they were fixed)

| # | Mismatch | Fix applied |
|---|----------|-------------|
| 1 | **Assess wrote into `lastSimulateResult`** so step 4/5 showed assess tree until user clicked "Run simulation". | Removed the block in `runMode` that set `lastSimulateResult` when `mode === 'assess'`. Assess preview lives only in `lastAssessResult.simulate_tree`. |
| 2 | **Step 2 tree tab** used `lastSimulateResult ?? lastAssessResult?.simulate_tree`, conflating assess preview with simulation plan. | Step 2 tree now uses **only** `lastAssessResult?.simulate_tree`. Tab label: "Tree preview (assess)". |
| 3 | **Step 2 tab visibility** included `lastSimulateResult`, so a prior simulation could show step 2 tabs. | Tabs show when `(lastAnalyzeResult || lastAssessResult)` only. |
| 4 | **New Recommend run** did not clear `lastSimulateResult`, so step 4 could show a simulation from a previous recommend. | In `runMode` when `mode === 'recommend'`, added `setLastSimulateResult(null)`. |
| 5 | **Approved list** was computed inline in the simulate button; no single named source. | Added `approvedFolders` = useMemo(suggested − rejected + custom) and use it in the simulate button. |

---

## C. Minimum code changes made

1. **`runMode` (App.tsx):**  
   - In `mode === 'assess'`: do **not** set `lastSimulateResult`.  
   - In `mode === 'recommend'`: call `setLastSimulateResult(null)`.

2. **Step 2 (Analyze & assess):**  
   - Tab visibility: `(lastAnalyzeResult || lastAssessResult)` (removed `lastSimulateResult`).  
   - Tree tab content: `<SimulateTreeGraphical data={lastAssessResult?.simulate_tree ?? null} />`.  
   - Tab label: "Tree preview (assess)".

3. **Derived state:**  
   - `approvedFolders` = useMemo from `lastRecommendResult`, `rejectedRecommendations`, `customRecommendations`.  
   - Step 4 "Run simulation" button calls `runMode('simulate', lastFolderPath, approvedFolders.length > 0 ? { suggested_folders: approvedFolders } : undefined)`.

4. **Comments:**  
   - State declarations document: analysisResult, assessPreviewResult (tree in lastAssessResult.simulate_tree), folderRecommendations, simulationPlan (lastSimulateResult only from Run simulation).

---

## D. Stale/shared state — what was split or renamed

| State / concept | Role | Where set | Where read (key UI) |
|----------------|------|-----------|---------------------|
| **lastAnalyzeResult** | Analysis summary (step 2) | `runMode('analyze')` | Step 2 summary |
| **lastAssessResult** | Assess result; **tree preview** in `.simulate_tree` | `runMode('assess')` | Step 2 summary + step 2 tree tab only |
| **lastRecommendResult** | Raw folder recommendations (step 3) | `runMode('recommend')` | Step 3 editor; input to `approvedFolders` |
| **approvedFolders** | Derived: recommended − rejected + custom | useMemo | Step 4 simulate button, Council/context if needed |
| **lastSimulateResult** | **Simulation plan** (steps 4 & 5) | **Only** `runMode('simulate')` | Step 4 tree, Step 5 Accept/Save |

- **Removed:** Assess writing to `lastSimulateResult` (was shared; now assess tree only in `lastAssessResult.simulate_tree`).  
- **Cleared on Recommend:** `lastSimulateResult` so step 4 never shows a simulation from an old recommend run.

---

## Verification answers

1. **Does Recommend depend on fresh Analyze/Assess context?**  
   **No.** Recommend API only receives `folder_path`. It runs independently (File Steward re-scans folder). The UI order (Analyze → Recommend) is workflow-only; the backend does not take analysis or assess result. To make Recommend use analyze context would require a new API (e.g. pass analysis summary or suggested_child_folders from analyze).

2. **Does Simulate use ONLY the approved folder list?**  
   **Yes.** When the frontend sends `suggested_folders: approvedFolders`, the API passes `allowed_folders` to `simulate_folder_plan`. File Steward uses that list as the only target folders and maps any suggestion not in the list to "Unsorted". The **displayed** tree only contains approved folders (+ Unsorted). (Classification still uses internal logic; output is constrained to the list.)

3. **Did Assess populate tree state reused by simulation/review?**  
   **Previously yes; now no.** Assess no longer sets `lastSimulateResult`. Step 2 tree uses only `lastAssessResult?.simulate_tree`. Step 4/5 use only `lastSimulateResult`.

4. **Sources of truth:**  
   - Analyze: `lastAnalyzeResult`  
   - Assess: `lastAssessResult` (tree: `lastAssessResult.simulate_tree`)  
   - Recommend: `lastRecommendResult`  
   - Editable approved list: `approvedFolders` (derived)  
   - Simulation result: `lastSimulateResult`  
   - Displayed tree step 2: `lastAssessResult?.simulate_tree`  
   - Displayed tree step 4/5: `lastSimulateResult`

5. **Displayed tree from correct result?**  
   **Yes after fixes.** Step 2 = assess preview only. Step 4 = simulation plan only. No cross-step reuse.

6. **Approved list built and sent?**  
   **Yes.** `approvedFolders` = recommended − rejected + custom (useMemo). Sent as `params.suggested_folders` when calling `runMode('simulate', path, { suggested_folders: approvedFolders })`.
