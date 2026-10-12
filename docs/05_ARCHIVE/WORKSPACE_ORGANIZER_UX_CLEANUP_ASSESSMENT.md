# Workspace Organizer — UX cleanup assessment

**Goal:** Refactor the Workspace Organizer UI so it reads as a **guided review wizard** rather than a multi-tool control panel, without changing the backend flow.

**Scope:** Assessment only. No implementation in this doc.

---

## 1. Main UX problems in the current layout

### 1.1 Multiple competing actions per step

- **Step 1 (Select Folder):** Primary slot shows "Change" when done; FolderSelector has "Use current focus", "Clear", and recent-folders dropdown in one row. The **primary** action (confirm folder and continue) is implied (user just proceeds); "Change" is the only visible action and reads like an afterthought.
- **Step 2 (Analyze & assess):** After analyze, the primary action becomes "Run Assess uncertainty"; after assess, **three** actions share the header: "Use as Current Focus", "Next Step", and (inside the card) Summary / Tree tabs, then "Reassess with Perspective" and "Web search for context". The user cannot tell which one advances the workflow.
- **Step 3 (Recommend folders):** After recommend, **three** header actions again: "Use as Current Focus", "Refine Categories", "Next Step". Inside the card, SuggestedFoldersEditor has **another** row: "Assess recommendations: Refine Categories | Web Research". So "Refine Categories" and "Next Step" appear in two places with different neighbors; "Use as Current Focus" appears in both Step 2 and Step 3.
- **Step 4 (Run simulation):** Single primary ("Run simulation" / "Re-run simulation") is clear, but there is no explicit "Continue to review" — user must scroll to Step 5.
- **Step 5 (Review plan):** Two equal-weight buttons: "Accept plan" and "Save for later". No single primary "confirm" for the most common path.

**Result:** No single obvious "do this next" per step. Secondary and optional actions compete with the main path.

### 1.2 Weak visual hierarchy

- **primaryAction** is right-aligned in the step header next to the state badge; it is a flex row of buttons with equal visual weight when there are 2–3 actions. Amber vs slate styling helps a bit but "Next Step" and "Use as Current Focus" look like siblings.
- **SummaryCard** and **SuggestedFoldersEditor** sit directly under the header with no clear "result" vs "actions" grouping. In Step 2, tabs (Summary / Tree preview) sit above the content; in Step 3, the editor and the "Assess recommendations" row are one long block.
- The intro line ("Choose folder → Analyze → optional Reassess/Web → …") is dense and does not map 1:1 to the five steps, so it doesn’t act as a clear progress guide.
- **State labels** ("Not started", "Ready", "Done", "Running…", "Error") are small and uppercase; they don’t strongly convey "you are here" or "next step is X".

### 1.3 Redundant and duplicated controls

- **"Refine Categories"** appears in (a) Step 3 card primary actions and (b) inside SuggestedFoldersEditor as "Assess recommendations: Refine Categories | Web Research". Same action, two places.
- **"Use as Current Focus"** appears in Step 2 and Step 3 primary actions. It’s a context/topic helper, not a step advance; putting it in the primary slot suggests it’s the main next action.
- **"Next Step"** appears in Step 2 and Step 3. It’s the real "continue" but is one of several buttons and doesn’t look like the main path.
- **Web Research** appears in Step 2 (Assess card: "Web search for context") and in Step 3 (SuggestedFoldersEditor: "Web Research"). Optional research is useful but doesn’t need to sit next to the primary flow in two steps.

### 1.4 Unclear step purpose and expectation

- Step titles are short ("Select Folder", "Analyze & assess uncertainty", "Recommend folders", "Run simulation", "Review plan") but there is no one-line "what you do here" or "what happens next" under the title.
- Step 2 mixes "analyze" and "assess" and optional "Reassess/Web" in one card; the primary button text switches from "Run Analyze" to "Run Assess uncertainty" to a row of three actions. The user may not understand that assess is optional or that "Next Step" is the normal path.
- Step 3 doesn’t say that the main job is "edit the list, then continue"; Refine Categories and Web Research read like required options.
- Step 5 says "Review plan" but doesn’t spell out "review the tree above, then accept or save."

### 1.5 Crowded controls in the card body

- Step 2 body: Summary vs Tree tabs, analysis summary, assess table, "Actions: Reassess with Perspective | Web search for context", reassess modal, reassess results with approve/deny per item, and (when low confidence) another "Web search for context" CTA. That’s a lot in one card.
- Step 3 body: Recommendations summary, full SuggestedFoldersEditor (pills, reject, add custom, Refine Categories, Web Research), notes. The editor is the main content but shares space with two CTAs that duplicate the header.

**Result:** The workflow feels like a control panel with many levers instead of a linear "do this → then this" wizard.

---

## 2. Proposed simplified step structure (guided review wizard)

Each step should have:

- A **single sentence** of purpose ("What you do here").
- **One primary action** in the header: the "continue" or "confirm" for this step.
- **Secondary actions** grouped and visually demoted (links, secondary buttons, or "More options" collapse).
- Clear **result area** (what happened) and **next area** (what to do next).

| Step | Current title | Proposed user-facing label | Purpose (one line) | User expectation |
|------|----------------|-----------------------------|---------------------|------------------|
| 1 | Select Folder | **1. Select folder** | Choose the folder you want to organize. | Pick or type path; use recent/focus if helpful. Primary: proceed (implicit: step is "done" when path is set; show "Continue" or rely on Step 2 being obviously next). |
| 2 | Analyze & assess uncertainty | **2. Analyze folder** | See what’s in the folder and whether assignments are uncertain. | Run analyze (primary). Optionally run assess; then either continue or use optional reassess/web. Primary after result: **Continue to suggestions** (replacing "Next Step"). |
| 3 | Recommend folders | **3. Review suggested folders** | Get candidate parent folders and edit the list until it fits. | Run suggest (primary). Then edit list; optional Refine Categories / Web Research. Primary after result: **Continue to simulation** (replacing "Next Step"). |
| 4 | Run simulation | **4. Preview the plan** | See how files would move into your chosen folders. | Run simulation (primary). Review tree; optionally change assignments. Primary after result: **Review plan** (link or button to scroll/focus Step 5). |
| 5 | Review plan | **5. Accept or save** | Confirm the plan or save it for later. | One primary: **Accept plan** (or "Apply plan"). Secondary: **Save for later**. |

**Step progression copy (intro):** Replace the long sentence with a short wizard summary, e.g.  
"**Steps:** 1 Select folder → 2 Analyze → 3 Edit suggested folders → 4 Preview plan → 5 Accept or save."

---

## 3. Primary vs secondary controls (recommendations)

### 3.1 Step 1 — Select folder

| Control | Current | Proposed |
|--------|--------|----------|
| Folder path input + Recent dropdown | Body | **Keep**; main content. |
| "Use current focus" | Primary row (FolderSelector) | **Secondary:** link or small text button, e.g. "Use current focus" next to recent dropdown. |
| "Clear" | Same row | **Secondary:** keep as subtle button. |
| "Change" (when path set) | primaryAction | **Primary:** make it "Continue" or remove and rely on Step 2 as next (so no header button; or one "Continue" that scrolls/focuses Step 2). |

**Primary action:** One clear "Continue" when path is non-empty, or no header button and rely on visible Step 2.

### 3.2 Step 2 — Analyze folder

| Control | Current | Proposed |
|--------|--------|----------|
| "Run Analyze" | primaryAction | **Primary** (only action when no result). |
| "Run Assess uncertainty" | primaryAction | **Primary** (only action when analyze done, no assess). |
| "Use as Current Focus" | primaryAction (after assess) | **Secondary:** move into "More options" or a small link under the summary. |
| "Next Step" | primaryAction | **Primary** after analyze/assess: relabel to **"Continue to suggestions"** and make it the single main button. |
| Summary / Tree tabs | Body | **Keep**; result area. |
| "Reassess with Perspective" | Body, Actions row | **Secondary:** "More options" (collapsible) or link "Reassess low-confidence items". |
| "Web search for context" | Body, Actions row | **Secondary:** same "More options" or "Web search for context" link. |
| Reassess results (approve/deny) | Body | **Keep** when reassess was used; can live in same collapsible or below. |

**Primary action (after result):** Only **"Continue to suggestions"**. Demote "Use as Current Focus", Reassess, and Web search to secondary/collapsible.

### 3.3 Step 3 — Review suggested folders

| Control | Current | Proposed |
|--------|--------|----------|
| "Run Suggest Folders" | primaryAction | **Primary** (only when no recommend result). |
| "Use as Current Focus" | primaryAction | **Secondary:** move to "More options" or link. |
| "Refine Categories" | primaryAction + in SuggestedFoldersEditor | **Secondary:** keep only **one** instance, e.g. inside the card as "Refine categories (AI)" link or small button under the folder list. |
| "Next Step" | primaryAction | **Primary** after result: relabel **"Continue to preview"** and make it the single main button. |
| SuggestedFoldersEditor (edit list) | Body | **Keep**; main content. |
| "Assess recommendations: Refine Categories \| Web Research" | In SuggestedFoldersEditor | **Collapse or simplify:** e.g. "Optional: Refine categories (AI) · Web research" as links or one "More options" row. |

**Primary action (after result):** Only **"Continue to preview"**. Refine Categories and Web Research demoted; single placement for Refine Categories.

### 3.4 Step 4 — Preview the plan

| Control | Current | Proposed |
|--------|--------|----------|
| "Run simulation" / "Re-run simulation" | primaryAction | **Primary** (only). |
| Editable tree + overrides | Body | **Keep**; main content. |
| (None) | — | **After result:** add one secondary "Review plan" link/button that scrolls or focuses Step 5, or rely on Step 5 being visible below. |

**Primary action:** Stay as single "Run simulation" / "Re-run simulation". Optional: small "Next: Review plan" link.

### 3.5 Step 5 — Accept or save

| Control | Current | Proposed |
|--------|--------|----------|
| "Accept plan" | primaryAction | **Primary:** keep as main CTA (emerald). |
| "Save for later" | primaryAction | **Secondary:** style as secondary button (border, not filled). |

**Primary action:** **Accept plan** only. "Save for later" clearly secondary.

---

## 4. Visual hierarchy recommendations

### 4.1 Per-step layout

- **Header row:** Step number + title + **one primary button** (or none if step is "just fill the form"). State badge stays but can be smaller or right of title.
- **Body:** Two clear zones where possible:
  - **Result / content:** SummaryCard, SuggestedFoldersEditor, SimulateTreeGraphical, etc. Use a single background (e.g. card or panel) so "what happened" reads as one block.
  - **Next / options:** One line under the result: primary "Continue to…" if not in header, then "More options" (collapsible) or 1–2 links (Use current focus, Refine categories, Web research, Reassess).
- **Tabs (Step 2):** Keep Summary / Tree preview; ensure they’re clearly part of "result" and not mixed with actions.

### 4.2 Demotion patterns

- **Secondary buttons:** Same border/slate style, smaller or text-sm, not in the main header row. E.g. "Use current focus", "Refine categories", "Web research" as text links or small buttons under the content.
- **Collapsible "More options":** One row or button "More options" that expands to show: Use as Current Focus, Reassess with Perspective, Web search for context (Step 2); Refine Categories, Web Research (Step 3). Reduces clutter and keeps the main path obvious.
- **Single placement:** Refine Categories only once per step (e.g. only inside Step 3 body, not in header). Same for Web Research.

### 4.3 Intro and progress

- Replace the long sentence with the short **Steps:** line (see §2).
- Optionally add a minimal progress indicator (e.g. 1–5 with current step highlighted) so "you are here" is obvious without reading state labels.

---

## 5. Human-in-the-loop preservation

- **No automation change:** No auto-advance, no skipping steps, no running analyze/recommend/simulate without user action.
- **Explicit confirmations:** Keep "Run simulation" and "Accept plan" as explicit user actions. "Save for later" remains optional.
- **Editing in place:** Step 3: user still edits the list (reject/add). Step 4: user can still override item→folder in the tree. No change to that.
- **Optional paths:** Reassess, Web search, Refine Categories stay available but **demoted** so the default path is: Analyze → (optional Assess) → Continue → Suggest → Edit list → Continue → Simulate → Review → Accept or Save.

---

## 6. Exact frontend files and components to edit (in order)

All in **`frontend/src/App.tsx`** unless a component is split out later.

### 6.1 Copy and structure (no new components)

1. **Workspace Organizer intro**
   - **Location:** Same `<section>` as the workflow, the `<p className="text-slate-400 text-sm mb-6">` under the "Workspace Organizer" heading.
   - **Change:** Replace the long "Choose folder → Analyze → …" sentence with the short **Steps:** line and, if desired, one line: "Each step has one main action; optional actions are under 'More options' or as links."

### 6.2 Step 1

2. **Step 1 primary action**
   - **Location:** `WorkflowStepCard` for step 1, `primaryAction` prop.
   - **Change:** When `folderPath.trim()` is set, show a single primary button **"Continue"** (or "Continue to Analyze") instead of "Change". Optionally keep "Change" as a small link next to it or in the body. Ensure FolderSelector’s "Use current focus" and "Clear" are visually secondary (already in body; can restyle as links).

3. **FolderSelector**
   - **Location:** `function FolderSelector` (lines ~247–306).
   - **Change:** Optionally restyle "Use current focus" and "Clear" as text links or smaller secondary buttons so they don’t compete with the path input and (if added) Continue.

### 6.3 Step 2

4. **Step 2 title and primary actions**
   - **Location:** Step 2 `WorkflowStepCard`: `title` and `primaryAction`.
   - **Change:** Title to **"Analyze folder"** (or keep "Analyze & assess uncertainty" and add a subtitle "See what’s in the folder and where items might go"). When (lastAnalyzeResult or lastAssessResult) and not loading, **primaryAction** = single button **"Continue to suggestions"** (calling `goToNextStep`). Remove "Use as Current Focus" and "Next Step" from the same row.

5. **Step 2 body — demote Reassess and Web search**
   - **Location:** Inside Step 2, the "Actions:" row with "Reassess with Perspective" and "Web search for context".
   - **Change:** Replace with a collapsible **"More options"** (or "Optional actions") that expands to show Reassess and Web search. Or keep as two small links/text buttons under the assess summary so they’re clearly secondary.

### 6.4 Step 3

6. **Step 3 title and primary actions**
   - **Location:** Step 3 `WorkflowStepCard`: `title` and `primaryAction`.
   - **Change:** Title to **"Review suggested folders"** (or keep "Recommend folders" and add subtitle "Edit the list, then continue"). When lastRecommendResult and not error, **primaryAction** = single button **"Continue to preview"** (calling `goToNextStep`). Remove "Use as Current Focus", "Refine Categories", and "Next Step" from the header.

7. **SuggestedFoldersEditor**
   - **Location:** `function SuggestedFoldersEditor` (lines ~526–646).
   - **Change:** Keep "Refine Categories" and "Web Research" but as **secondary**: one row "Optional: Refine categories (AI) · Web research" as links or small buttons. Remove the duplicate "Refine Categories" from Step 3 header (so only one place). Ensure the row is visually below the folder list and demoted (smaller text, muted color).

### 6.5 Step 4

8. **Step 4 title**
   - **Location:** Step 4 `WorkflowStepCard`, `title`.
   - **Change:** To **"Preview the plan"** (or keep "Run simulation" and add subtitle "See how files would move"). No change to single primary button. Optionally add under the tree a small link "Next: Review plan" that scrolls to Step 5.

### 6.6 Step 5

9. **Step 5 primary vs secondary**
   - **Location:** Step 5 `WorkflowStepCard`, `primaryAction`.
   - **Change:** Keep "Accept plan" as the only primary (filled emerald). Style "Save for later" as secondary (border, slate). Optionally add one line above: "Review the tree above, then accept or save for later."

### 6.7 Optional: "Use as Current Focus" in one place

10. **Use as Current Focus**
    - **Location:** Currently in Step 2 and Step 3 `primaryAction` blocks.
    - **Change:** Remove from both step headers. Either: (a) add once in a shared "More options" for the workflow (e.g. at top under intro), or (b) add inside Step 1 as a small link in FolderSelector, or (c) keep inside a "More options" collapsible in Step 2 and Step 3. Recommendation: (c) or (a) so the main path never shows it as a primary action.

### 6.8 Component reuse

- **WorkflowStepCard:** No API change needed. It already takes `primaryAction` and `children`. Ensure only one primary control is passed per step; secondary controls live in `children`.
- **SummaryCard, SuggestedFoldersEditor, SimulateTreeGraphical:** Use as-is; only their call sites and surrounding layout (e.g. "More options" wrapper) change.

---

## 7. Summary table

| Step | Primary action (only one) | Demote to secondary / link / collapsible |
|------|---------------------------|------------------------------------------|
| 1 | Continue (when path set) or none | Use current focus, Clear |
| 2 | Run Analyze → Run Assess (when applicable) → **Continue to suggestions** | Use as Current Focus, Reassess, Web search for context |
| 3 | Run Suggest Folders → **Continue to preview** | Use as Current Focus, Refine Categories (one instance), Web Research |
| 4 | Run simulation / Re-run simulation | Optional "Next: Review plan" link |
| 5 | **Accept plan** | Save for later |

**Files to edit:** `frontend/src/App.tsx` only (WorkflowStepCard usages, FolderSelector, SuggestedFoldersEditor, intro paragraph). No backend or API changes.

**Out of scope for this pass:** Splitting WorkflowStepCard or SuggestedFoldersEditor into separate files; adding a formal "progress stepper" component; changing backend flow or adding new endpoints.
