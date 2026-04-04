# Recommend Mode: Implementation Summary

Recommend Child Folders is wired in both the API and the cockpit frontend. This doc explains what was changed and how to test.

---

## Files changed

### 1. `api/main.py`

**What changed**

- **`_run_recommend(params)`** (new)
  - Requires `params.folder_path` (non-blank). If missing or blank, raises `ValueError` → API returns **400** with detail `"recommend requires params.folder_path"`.
  - Calls **`recommend_child_folders(folder_path)`** from `local_ai.atria_tools` (existing File Steward / Atria engine). No new business logic.
  - If the engine returns an `error` key (e.g. folder not found), returns that dict so the handler can respond with `ok: false` and `error`.
  - On success, returns a **compact** dict with only:
    - `folder_path`
    - `inferred_context_domain`
    - `suggested_child_folders`
    - `notes` (if present)

- **POST /run**
  - Handles **`mode == "recommend"`**: calls `_run_recommend(params)`, catches `ValueError` → 400, other exceptions → 200 with `ok: false`, engine errors → 200 with `ok: false` and `error`. Success → 200 with `ok: true` and compact `result`.

- **Docstring** for `run()` updated to list recommend as supported.

**Request shape**

```json
{
  "mode": "recommend",
  "params": {
    "folder_path": "C:\\some\\path"
  }
}
```

**Response (success)**

```json
{
  "ok": true,
  "result": {
    "folder_path": "C:\\some\\path",
    "inferred_context_domain": "UNSORTED",
    "suggested_child_folders": ["Archive", "Documents", "..."],
    "notes": ["Truncated at 100 items..."]
  },
  "error": null
}
```

---

### 2. `frontend/src/App.tsx`

**What changed**

- **`RecommendResult` interface** (new)  
  - `folder_path`, `inferred_context_domain`, `suggested_child_folders`, `notes?`, `error?`.

- **State**
  - **`lastRecommendResult`**: set when a Recommend run succeeds (same pattern as Analyze/Simulate/Assess).
  - **`lastFolderPath`** and **`lastMode`** are already set inside `runMode()` for all modes, including recommend.

- **`runMode()`**
  - Accepts **`'recommend'`**; sends **`mode: "recommend"`** and **`params: { folder_path }`** to POST /run.
  - On success, stores the response in **`lastRecommendResult`** (and updates `lastFolderPath`, `lastMode`).

- **`handleRun()`**
  - When **Recommend** is the active mode, calls **`runMode('recommend', path)`** with the current folder path (same input as Analyze / Simulate / Assess).

- **Human-readable Recommend view** (when last run was Recommend and there’s no error)
  - **Folder** path  
  - **Inferred context/domain**  
  - **Suggested child folders** as tags (wrapped pills)  
  - **Notes** (if present), joined in one line  

- **Raw JSON**
  - Existing “Result (JSON)” panel still shows the full API response below the summary.

- **Placeholder**
  - Text updated so Recommend is listed as wired alongside Analyze, Simulate, and Assess Uncertainty.

**Folder path input**

- Recommend uses the same folder path field as Analyze, Simulate, and Assess (`showFolderInput` already includes `'recommend'`). No new input.

---

## How to test

1. **Start API and frontend**  
   - From repo root: `python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8010`  
   - From `frontend/`: `npm run dev`  
   - Open http://localhost:5173

2. **Recommend with valid path**  
   - Click **Recommend**.  
   - Enter a folder path (e.g. `.` or `C:\Users\...\Atria`).  
   - Click **Run**.  
   - You should see: human-readable block (folder, inferred context, suggested child folders as tags, notes if any) and the raw JSON below.

3. **400 when folder_path is missing**  
   - Call POST /run directly with `{ "mode": "recommend", "params": {} }` or `"params": { "folder_path": "" }`.  
   - Expect **400** and a message like `"recommend requires params.folder_path"`.

4. **Workflow**  
   - Run **Analyze** → **Simulate** → **Assess Uncertainty** → **Recommend** on the same folder path. Each step should work and show its own summary + JSON; Recommend should show the compact recommend result and tags.

5. **Other modes unchanged**  
   - Analyze, Simulate, Assess Uncertainty behave as before. Council, Web Research, Next Step still show placeholders when Run is clicked.

---

## Backend / engine integration

- **Single source of truth:** `local_ai.atria_tools.recommend_child_folders(folder_path)`, which delegates to File Steward’s `recommend_child_folders`. No new recommendation logic in the API.
- **API role:** Validate input (folder_path required), call the engine, return compact JSON or forward engine errors. The API stays thin and does not duplicate business logic.
