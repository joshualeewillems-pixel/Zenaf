# Workspace Organizer — Single-step UI refactor proposal

**Goal:** Replace the current stacked step panels with a single stateful window that shows one step at a time and a clear progression: Analyze → Recommend → Refine Categories → Simulation → Review.

**Constraints:** Minimal UI refactor only; preserve all existing backend behavior; do not change analyze/recommend/simulation logic.

---

## 1. Current vs proposed

| Current | Proposed |
|--------|----------|
| All 5 steps visible as stacked `WorkflowStepCard`s | **One step visible at a time** in a single content area |
| Multiple actions per step (Use as Current Focus, Next Step, Refine Categories, etc.) | **One primary action per step**; advance via "Continue" or the step’s main action |
| Tree preview in Step 2 (assess tab) and Step 4 (simulation) | **Tree preview only after simulation** (Step 4/5 only) |
| "Use as Current Focus" and "Next Step" in steps 2 and 3 | **Removed**; progression is explicit step advance only |

---

## 2. Single visible step (stateful window)

- **State:** Add `workspaceOrganizerStep: 1 | 2 | 3 | 4 | 5` (or equivalent: e.g. `'select' | 'analyze' | 'recommend' | 'simulate' | 'review'`). Default `1`.
- **Render:** Inside the Workspace Organizer section, instead of rendering five `WorkflowStepCard`s in a column, render **only the card for the current step** (`workspaceOrganizerStep`). Same `WorkflowStepCard` component and same step content as today; only one is mounted at a time.
- **Stepper (optional):** Show a minimal progress indicator above the step content (e.g. "Step 2 of 5 — Analyze" or dots 1–5 with current highlighted) so the user knows where they are and that there are more steps. No need to show titles of all steps at once.
- **Back / Change:** For "go back" or "change folder", either:
  - Provide a single secondary "Back" or "Change folder" link that decrements `workspaceOrganizerStep` or resets to step 1 and clears path, or
  - Omit back navigation in the minimal refactor and rely on "Change" in step 1 when the user is on step 1. Optional: "Start over" that resets step to 1 and optionally clears folder path.

---

## 3. Progression: Analyze → Recommend → Refine Categories → Simulation → Review

- **Step 1 — Select folder**  
  - Content: `FolderSelector` only (no change to props or behavior).  
  - Primary action: **"Continue"** (enabled when `folderPath.trim()`). On click: set `lastFolderPath` from `folderPath`, advance `workspaceOrganizerStep` to `2`. Optionally keep a small "Change" link to clear path.  
  - Remove: any "Use as Current Focus" from this step if present in `FolderSelector`; or keep it as a small link (see §5).

- **Step 2 — Analyze**  
  - Content: Analysis summary only (no tree). Keep "Run Analyze" and optional "Run Assess uncertainty" as today; keep Summary (and optional Reassess/Web in a collapsible or link).  
  - Primary action: If no analyze yet → **"Run Analyze"**. If analyze done and no assess → **"Run Assess uncertainty"** (optional; can stay). If (analyze or assess) done → **"Continue"** only (no "Use as Current Focus", no "Next Step"). Continue advances to step 3.  
  - Remove: "Use as Current Focus", "Next Step". Remove the **"Tree preview (assess)"** tab and the block that renders `SimulateTreeGraphical` with `lastAssessResult?.simulate_tree`. Tree appears only in Simulation/Review.

- **Step 3 — Recommend**  
  - Content: Same as today (recommend result, `SuggestedFoldersEditor`, Refine Categories, Web Research).  
  - Primary action: If no recommend yet → **"Run Suggest Folders"**. If recommend done → **"Continue"** only (advance to step 4).  
  - Remove: "Use as Current Focus", "Next Step". Keep Refine Categories and Web Research as secondary (link or small button).

- **Step 4 — Simulation**  
  - Content: **Only place the tree is shown.** After "Run simulation", show `SimulateTreeGraphical` with `lastSimulateResult` (editable overrides) as today. Before run, show short copy: "Run simulation to see the file tree with your approved folders."  
  - Primary action: **"Run simulation"** (or "Re-run simulation"). After a successful run, show **"Continue"** to go to step 5.  
  - No tree from assess; only simulation result tree here.

- **Step 5 — Review**  
  - Content: Short line: "Review the tree above. Accept or save for later." If you show the tree again here, it can be a read-only summary or a link to "View tree" that scrolls or reuses the same data. For minimal refactor, step 5 can just show the two buttons and refer to "the tree above" (user saw it in step 4).  
  - Primary action: **"Accept plan"** (primary) and **"Save for later"** (secondary). No step advance after this.

---

## 4. One primary action per step

- **Step 1:** Continue (when path set).  
- **Step 2:** Run Analyze → then optionally Run Assess → then **Continue**.  
- **Step 3:** Run Suggest Folders → then **Continue**.  
- **Step 4:** Run simulation → then **Continue** (when result exists).  
- **Step 5:** Accept plan (primary), Save for later (secondary).

All other actions (Refine Categories, Web Research, Reassess, Change folder) are secondary: smaller buttons, links, or inside a "More options" collapse so the primary action is obvious.

---

## 5. Removals and tree preview

- **Remove everywhere in the workspace organizer:**  
  - "Use as Current Focus" buttons.  
  - "Next Step" buttons.  
  - Replace their behavior with a single **"Continue"** that advances `workspaceOrganizerStep` by 1.

- **Tree preview:**  
  - **Remove** from Step 2: the "Tree preview (assess)" tab and the content that renders `SimulateTreeGraphical data={lastAssessResult?.simulate_tree}`.  
  - **Keep** in Step 4 (and optionally in Step 5): `SimulateTreeGraphical` with `lastSimulateResult` only. So the only tree the user sees is the simulation result tree.

- **FolderSelector:**  
  - Remove or demote "Use current focus" to a small link so it doesn’t compete with the single primary "Continue" in step 1. Optional: keep as a text link "Use current focus" next to recent folders.

---

## 6. Files and components to change (minimal)

**Single file:** `frontend/src/App.tsx`.

- **State:** Add `workspaceOrganizerStep` (e.g. `useState<1 | 2 | 3 | 4 | 5>(1)`). Optionally reset this when the user clears the folder or clicks "Start over".
- **Workspace Organizer section:** The block that currently renders `{!workspaceCollapsed && ( <div className="space-y-4"> ... five WorkflowStepCards ... </div> )}`:
  - Replace with a single container that:
    - Optionally shows a stepper (e.g. "Step X of 5" or dots).
    - Renders **one** `WorkflowStepCard` based on `workspaceOrganizerStep` (e.g. `{workspaceOrganizerStep === 1 && <WorkflowStepCard ... step 1 ... />}`, etc.).
  - Reuse the same step content and handlers (runMode, runFolderAdvisor, etc.); only change which step is visible and what the primary action is (Continue vs Run X).
- **Step 2 content:** Remove the tabs (Summary / Tree preview) and the tree tab content. Keep only the summary (and Reassess/Web as secondary). Remove any `SimulateTreeGraphical` that uses `lastAssessResult?.simulate_tree`.
- **Step 2 primary action:** When (lastAnalyzeResult or lastAssessResult) exists, render a single **"Continue"** button that calls `setWorkspaceOrganizerStep(3)` (and does not call `useResultAsFocus` or `goToNextStep`). Remove the div that contains "Use as Current Focus" and "Next Step".
- **Step 3 primary action:** When lastRecommendResult exists, add a single **"Continue"** that calls `setWorkspaceOrganizerStep(4)`. Remove "Use as Current Focus" and "Next Step".
- **Step 4:** After simulation result exists, add **"Continue"** that calls `setWorkspaceOrganizerStep(5)`. Keep tree here only.
- **Step 1:** Primary action: **"Continue"** when path is set; onClick set `lastFolderPath` (if not already set) and `setWorkspaceOrganizerStep(2)`. "Change" can stay as secondary to clear path and stay on step 1.
- **FolderSelector:** Remove `onUseCurrentFocus` from the props passed to `FolderSelector` in step 1, or keep the prop but ensure the button is a small link so the only prominent action is "Continue". If removing, add a comment that "Use current focus" is omitted for the single-step flow; alternatively keep it in the selector as a text link.

---

## 7. What stays the same

- **Backend:** No changes to API or to `runMode`, `runFolderAdvisor`, simulate, or recommend.
- **Data:** Same state (folderPath, lastAnalyzeResult, lastAssessResult, lastRecommendResult, lastSimulateResult, approvedFolders, etc.). Same handlers. Only the **rendering** of steps and the **primary action** per step change.
- **Analyze / Assess / Recommend / Simulation logic:** Unchanged. Only the UI that triggers them and the way the user moves to the next step change.
- **Right panel (Folder review result / AI agents):** No change.
- **WorkflowStepCard component:** Can stay as-is; it still receives `stepNumber`, `title`, `state`, `primaryAction`, `children`. Only the parent renders one card at a time and passes a single primary action (often "Continue").

---

## 8. Summary

| Change | Where |
|--------|--------|
| Add `workspaceOrganizerStep` state (1–5) | App state |
| Render only one step at a time | Workspace Organizer section: conditional render by `workspaceOrganizerStep` |
| Primary action = "Continue" after each step (except step 5) | Each step’s `primaryAction` prop; Continue calls `setWorkspaceOrganizerStep(n + 1)` |
| Remove "Use as Current Focus" and "Next Step" | Step 2 and Step 3 (and any other occurrences in workspace organizer) |
| Remove tree from Step 2 (assess) | Step 2 content: remove "Tree preview (assess)" tab and `SimulateTreeGraphical` for assess |
| Tree only after simulation | Step 4 (and optionally Step 5) only; use `lastSimulateResult` |
| Optional stepper | Above the single step content: "Step X of 5" or dots |

Result: the workspace organizer becomes a single stateful window with one step visible, one primary action per step, and a clear linear flow: Analyze → Recommend → Refine Categories → Simulation → Review, with no change to backend or analyze/recommend/simulation logic.
