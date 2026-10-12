# Workspace Organizer — Folder advisor as self-contained subsystem (UI proposal)

**Goal:** Make the folder workflow a self-contained guided wizard. Refine Categories should call the folder advisor internally and show results in a dedicated "Folder review result" panel, without using the general council interface. No backend changes.

**Constraints:** Smallest safe UI refactor; keep existing backend (workflow_kind: 'folder', single seat, no synthesis).

---

## 1. Problems to fix

1. **Refine Categories routes through the AI agents panel** — User clicks Refine Categories → we set `activeMode = 'council'` and prefill the question → user must then click "Run Council" in the right panel. The folder workflow should trigger the folder advisor **directly** and show the result in a folder-specific UI, not in the council console.

2. **Council UI is visible during folder workflow** — Question input, agent list (strategist/operator/analyst), Run Council, and perspective switching are irrelevant when the only valid role is the folder advisor. They add confusion and suggest the user can change behavior.

3. **Folder advisor output is not actionable** — The streamed text is shown as raw prose. We should parse suggested folders and reasons, highlight them in the folder editor, and offer quick actions (Add suggestion, Replace list, Ignore).

4. **Right panel should reflect the task** — When the user is in the folder workflow, the right panel should show "Folder review result" (and only folder-review content), not the generic "AI agents" console.

5. **Wizard flow** — The sequence should read clearly as: Analyze → Recommend → Refine Categories → Simulation → Review, with Refine Categories as an inline step that doesn’t leave the workflow.

---

## 2. Proposed behavior (summary)

- **Refine Categories** (both in Step 3 header and inside SuggestedFoldersEditor) triggers a **direct** call to the same backend (`POST /run/stream`, `workflow_kind: 'folder'`). No switch to council mode; no question input or Run Council in the UI for this path.
- **When the user is in the folder workflow** (Workspace Organizer with a recommend result): the **right panel** shows **"Folder review result"** instead of the AI agents panel. Content: placeholder when no result; streaming then parsed result + quick actions when Refine Categories has been run.
- **Folder workflow** = `mainView === 'workspace' && lastRecommendResult && !lastRecommendResult.error`. Only in that state do we show the folder-review panel and hide the council console.
- **Parsed advisor output** is used to: (1) show a structured list (folder + short reason) in the right panel, (2) highlight those folders in SuggestedFoldersEditor, (3) offer **Add suggestion**, **Replace list**, **Ignore**.
- **Backend** unchanged: same endpoint, same `workflow_kind: 'folder'`, same single-seat folder advisor.

---

## 3. Smallest safe UI refactor

### 3.1 State (new or repurposed)

- **`folderAdvisorResult: string | null`** — Raw text from the last Refine Categories run. Set when the stream completes; cleared on Ignore or when starting a new Refine Categories run.
- **`folderAdvisorStreaming: string`** — Accumulated chunk text while the folder advisor is streaming. Cleared when stream ends.
- **`folderAdvisorLoading: boolean`** — True while the Refine Categories request is in flight. Can be the same as `loading` if we scope it (e.g. only set when the request was started from Refine Categories), or a dedicated flag so the main "Loading" state doesn’t affect other buttons.
- **Derived:** `folderAdvisorParsedSuggestions: { folder: string; reason?: string }[]` — Parsed from `folderAdvisorResult` when present (see §3.5). Used for display and for Add/Replace.

No change to `lastCouncilResult` or `lastCouncilWasFolderWorkflow` for the folder path; we stop using the council panel for this flow, so we can avoid writing to council state when the call was from Refine Categories.

### 3.2 Refine Categories: trigger folder advisor internally

- **New function: `runFolderAdvisor()`**
  - Builds the same request as the current folder branch in `runCouncil`: `POST /run/stream`, `mode: 'council'`, `params: { question }`, `context: { folder_path, context_block, workflow_kind: 'folder' }`.
  - Question = prefilled string (same as today): "From this list of candidate parent folders — [approvedFolders] — which would you keep or prioritize..."
  - Does **not** set `activeMode`, `question`, or `lastCouncilResult`. Does **not** append to `agentThread`.
  - Sets `folderAdvisorLoading = true`, `folderAdvisorStreaming = ''`, clears `folderAdvisorResult`.
  - On stream chunk: append to `folderAdvisorStreaming`.
  - On stream done: set `folderAdvisorResult = fullText`, clear `folderAdvisorStreaming`, set `folderAdvisorLoading = false`.
  - On error: set error state, clear streaming/result, set `folderAdvisorLoading = false`.

- **Refine Categories button(s)**
  - **Step 3 header** (primary actions): replace the current `onClick` that sets `activeMode('council')` and `setQuestion(...)` with `runFolderAdvisor()`.
  - **SuggestedFoldersEditor** (`onAskCouncil`): same — call `runFolderAdvisor()` instead of setting question and `activeMode('council')`.
  - No navigation to the right panel; user stays on the workspace. The right panel, when in folder workflow, will show the result (or placeholder) automatically.

### 3.3 Right panel: Folder workflow vs AI agents

- **Condition:** `showFolderReviewPanel = mainView === 'workspace' && lastRecommendResult != null && !lastRecommendResult.error`.
- **When `showFolderReviewPanel` is true:** render **Folder review result** content in the right panel instead of the AI agents content.
  - **Header:** "Folder review result" (replace "AI agents").
  - **Body:**
    - If `folderAdvisorLoading || folderAdvisorStreaming`: show streaming text (same style as current council stream), with a short label "Refine Categories (AI)" or "Folder advisor".
    - Else if `folderAdvisorResult`: show parsed suggestions (see §3.5) and quick actions (Add suggestion, Replace list, Ignore). Optionally show raw text in a collapsible "Full response" for debugging.
    - Else: placeholder text: "Use **Refine Categories** in step 3 to get AI suggestions for your folder list."
  - **No** question input, **no** "Run Council" button, **no** agent list or perspective switching. The panel is read-only result + actions.

- **When `showFolderReviewPanel` is false:** render the current **AI agents** panel (question, thread, Run Council, agent list). No change to existing behavior.

- **Layout:** Same `<aside>`, same width. Only the inner content (header title + body) is conditional. The left column (Workspace Organizer) is unchanged.

### 3.4 Lock role and hide council UI in folder workflow

- When `showFolderReviewPanel` is true, the right panel does **not** render:
  - Question / "How to process" input
  - "Use current result as context" checkbox
  - "Run Council" button
  - "Include in this run" / seat checkboxes and mandate dropdowns
- So the user cannot switch to strategist/operator/analyst or run a second council; the only AI in this flow is the folder advisor, triggered only by Refine Categories in step 3.

### 3.5 Parse folder advisor output and make it actionable

- **Parser (client-side):**
  - Input: `folderAdvisorResult` (raw string).
  - Look for a block starting with "Suggested parent folders" (or "Folder advisor:" then that block). Then collect lines that match: `- <folder> — <reason>` (dash, folder name, em dash or hyphen, reason). Regex or line-by-line; allow optional trailing "Add to my recommendations: ...".
  - Output: `{ folder: string; reason?: string }[]`. If parsing fails, return empty array and optionally show raw text only.

- **Folder review result panel when result exists:**
  - Title: "Folder review result".
  - List: for each parsed item, show folder name and reason (e.g. one line or two-line card).
  - **Quick actions** (below the list or per item):
    - **Add suggestion** — Add the selected parsed folder(s) to the current list. Interpretation: add to `customRecommendations` (and remove from `rejectedRecommendations` if present). If we show one "Add" per suggestion, each adds that one folder. Optionally one "Add all" that adds all parsed folders to custom.
    - **Replace list** — Replace the current approved list with the parsed folder list. Interpretation: set `customRecommendations = parsed folders`, set `rejectedRecommendations` so that all original `suggested_child_folders` are rejected (so approved list = only custom = parsed). User sees the editor update immediately.
    - **Ignore** — Dismiss the advisor result. Set `folderAdvisorResult = null` (and clear streaming). Right panel returns to placeholder: "Use Refine Categories in step 3..."

- **Highlight in SuggestedFoldersEditor:**
  - New prop: `highlightedFolders?: string[]` (parsed folder names from the advisor).
  - When rendering a folder pill, if that folder is in `highlightedFolders`, add a visual cue: e.g. border (e.g. `border-amber-400`) or a small "AI" badge. So the user sees which folders the advisor suggested without changing behavior of reject/add.

### 3.6 Guided wizard flow

- **Copy (optional):** In the Workspace Organizer intro, use a single line: "**Steps:** 1 Select folder → 2 Analyze → 3 Suggest & edit folders → **Refine Categories (optional)** → 4 Preview plan → 5 Accept or save."
- **Behavior:** Refine Categories is a sub-step of step 3: user runs Recommend, edits the list, optionally clicks Refine Categories, sees result in the right panel, then uses Add/Replace/Ignore and continues to Simulation. No separate "council" step in the mental model.

---

## 4. Exact files and components to edit

**Single file:** `frontend/src/App.tsx`.

### 4.1 New state and function

- Add state: `folderAdvisorResult`, `folderAdvisorStreaming`, `folderAdvisorLoading` (or reuse `loading` with a guard so only Refine Categories sets it for the right panel).
- Add `runFolderAdvisor()` that builds the same body as the folder branch of `runCouncil`, POSTs to `/run/stream`, and updates only folder-advisor state (and generic `error`). Do not set `activeMode`, `lastCouncilResult`, or `agentThread`.

### 4.2 Refine Categories call sites

- **Step 3 primary actions:** The button that currently does `setFolderPath(lastFolderPath); setActiveMode('council'); setQuestion(...)`. Change to: `runFolderAdvisor()` (and optionally keep `setFolderPath(lastFolderPath)` if needed for context).
- **SuggestedFoldersEditor** `onAskCouncil`: change to call `runFolderAdvisor()`. The callback can be renamed to `onRefineCategories` for clarity; parent still passes a function that invokes `runFolderAdvisor()`.

### 4.3 Right panel content switch

- **Condition:** `showFolderReviewPanel = mainView === 'workspace' && lastRecommendResult != null && !lastRecommendResult.error`.
- **Structure:** Where the right panel content is rendered (inside the `<aside>`):
  - If `showFolderReviewPanel`: render a fragment: header "Folder review result", then body (placeholder | streaming | parsed list + actions). No question input, no Run Council, no agent list.
  - Else: render the current AI agents content (header "AI agents", thread, streaming, question, Run Council, agent list).
- **Header:** Use the same `<h2>` but text = `showFolderReviewPanel ? 'Folder review result' : 'AI agents'`, and optional subtitle only for the non-folder case.

### 4.4 Parser and quick actions

- Add a small helper `parseFolderAdvisorResult(text: string): { folder: string; reason?: string }[]` (same file or a tiny util). Call it when `folderAdvisorResult` is set; store or derive parsed list for the panel and for SuggestedFoldersEditor highlight.
- In the Folder review result body when there is a result: render the list; add buttons "Add suggestion" (and/or "Add all"), "Replace list", "Ignore". Wire:
  - Add: call `addCustomRecommendation` for the chosen folder(s).
  - Replace: set `customRecommendations` to parsed folder names and `rejectedRecommendations` to the full set of `lastRecommendResult.suggested_child_folders` (so approved = custom only).
  - Ignore: set `folderAdvisorResult = null`.

### 4.5 SuggestedFoldersEditor highlight

- Add prop `highlightedFolders?: string[]` to `SuggestedFoldersEditor`. When rendering each folder pill, if `highlightedFolders?.includes(name)` apply a highlight class or small "AI" badge.
- Parent (Step 3) passes `highlightedFolders={folderAdvisorParsedSuggestions.map(p => p.folder)}` when `folderAdvisorResult` is set.

### 4.6 What not to change

- **Backend:** No changes to API or `zenaf_tools`. Same `POST /run/stream`, same `workflow_kind: 'folder'`.
- **runCouncil:** Keep as-is for non-folder use (Perspectives, other views). Only the **call sites** for Refine Categories switch to `runFolderAdvisor()`.
- **Left column:** Workspace Organizer steps, FolderSelector, SummaryCard, SuggestedFoldersEditor (except new prop and callback rename), SimulateTreeGraphical, Step 4 and 5 — no structural change beyond Refine Categories wiring and optional intro line.

---

## 5. Data flow (summary)

1. User is in Workspace Organizer with a recommend result → `showFolderReviewPanel === true` → right panel shows "Folder review result" (placeholder or previous result).
2. User clicks Refine Categories (Step 3 or inside editor) → `runFolderAdvisor()` runs → right panel shows streaming, then on done shows parsed list + Add / Replace / Ignore.
3. Parsed list is derived from `folderAdvisorResult`; same list is passed as `highlightedFolders` to SuggestedFoldersEditor so matching pills are highlighted.
4. Add suggestion → update `customRecommendations` (and possibly `rejectedRecommendations`). Replace list → set approved list to parsed list via custom + reject. Ignore → clear `folderAdvisorResult`.
5. When user leaves the folder workflow (e.g. no recommend result or switches view), `showFolderReviewPanel === false` → right panel shows the normal AI agents console again.

---

## 6. Edge cases

- **User runs Refine Categories twice:** Second run overwrites `folderAdvisorResult` and streaming; no need to keep history.
- **User switches to another view and back:** If `lastRecommendResult` is still there, folder review panel shows again; any previous `folderAdvisorResult` is still there unless they clicked Ignore.
- **Parse fails:** Show raw text in the panel and optionally "Could not parse suggestions"; hide or disable Replace list; Add suggestion can still work if we allow "add from raw" later, or leave Add disabled when parse is empty.
- **Loading state:** Use `folderAdvisorLoading` so only Refine Categories shows a spinner or disabled state; other buttons (e.g. Next Step, Run simulation) remain enabled if desired.

---

## 7. Deliverables summary

| Item | Action |
|------|--------|
| Refine Categories | Triggers `runFolderAdvisor()` only; no council mode, no question/agent UI. |
| Right panel in folder workflow | Show "Folder review result": placeholder or streaming or parsed list + Add / Replace / Ignore. Hide question, Run Council, agent list. |
| Folder workflow definition | `mainView === 'workspace' && lastRecommendResult && !lastRecommendResult.error`. |
| Parser | Client-side parse of "Suggested parent folders" and "- Folder — reason" lines. |
| Quick actions | Add suggestion (custom list), Replace list (approved = parsed), Ignore (clear result). |
| Editor highlight | `highlightedFolders` prop on SuggestedFoldersEditor; highlight parsed folders. |
| File to edit | `frontend/src/App.tsx` only. |
| Backend | No change. |

This yields a self-contained folder workflow: Refine Categories runs the folder advisor under the hood and surfaces the result in a dedicated panel with actionable suggestions, while the general council UI stays for non-folder use.
