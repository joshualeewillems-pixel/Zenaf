# Zenaf Cockpit: Frontend Architecture & MVP Proposal

**Goal:** A polished, local-first workflow cockpit for Zenaf—visual operating surface, not a chatbot. One processing mode active at a time; Python remains the backend/engine.

---

## 1. Frontend Stack Recommendation

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **UI** | React 18 + TypeScript | Strong ecosystem, type safety, good for complex state and mode switching. |
| **Build** | Vite | Fast dev server and builds; minimal config. |
| **Styling** | Tailwind CSS | Rapid, consistent cockpit look; easy dark/light and “panel” styling. |
| **State** | React state + context (or Zustand later) | Single active mode + focus state is simple; avoid heavy Redux for MVP. |
| **Packaging** | **Tauri 2** | Thin Rust shell around the web view; small binaries, system WebView, no Node in prod. Better fit than Electron for a local-first, resource-light cockpit. |

**Why Tauri over Electron**

- Smaller binaries and memory use (important for “always available” local cockpit).
- Uses system WebView; no bundled Chromium.
- Strong security model and good desktop APIs (filesystem, etc.) for future local paths.
- First-class support for calling a local backend (e.g. Python sidecar or bundled server).

**Resulting stack:** React + TypeScript + Vite + Tailwind + Tauri 2.

---

## 2. App Architecture (High Level)

```
┌─────────────────────────────────────────────────────────────────┐
│  COCKPIT (React + Tauri)                                         │
│  - Single active mode (Analyze | Recommend | … | Next Step)      │
│  - Central focus (folder path / question / result)               │
│  - Mode cards → trigger backend, show result in focus            │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (localhost)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  ZENAF API (Python, thin layer)                                  │
│  - Small FastAPI/Flask server                                    │
│  - One route per mode (or /run with { mode, params })            │
│  - Calls existing zenaf_tools / File Steward / provider / council │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  EXISTING ENGINE (unchanged)                                     │
│  - local_ai/zenaf_tools.py                                       │
│  - tools/file_steward (analyze, recommend, assess, simulate)     │
│  - local_ai/providers, config, context, council, web_research    │
└─────────────────────────────────────────────────────────────────┘
```

- **Cockpit:** UI only; no business logic. Sends “run this mode with these params” to the API.
- **Zenaf API:** Thin adapter: maps HTTP requests to the right tool(s), returns JSON. Keeps all orchestration in Python.
- **Engine:** Current Zenaf + File Steward + provider + council + context; no change for cockpit MVP.

---

## 3. API / Backend Integration

**Option A (recommended for MVP): Single “run” endpoint**

- **POST /run**  
  Body: `{ "mode": "analyze" | "recommend" | "assess" | "simulate" | "council" | "web_research" | "next_step", "params": { ... } }`  
  Returns: `{ "ok": true, "result": { ... } }` or `{ "ok": false, "error": "..." }`.

- **Params by mode:**
  - **analyze / recommend / assess / simulate:** `{ "folder_path": "..." }` (and for simulate optionally `use_llm_second_pass`, etc.).
  - **council:** `{ "question": "...", "context": null }`.
  - **web_research:** `{ "query": "..." }`.
  - **next_step:** `{ "folder_path": "..." }` or similar (to be defined; could wrap “recommend + one concrete step” or a small dedicated helper).

- **Optional:** **GET /context** returning `{ "recent_folder": "...", "phil_context_loaded": true }` so the UI can show “current focus” and whether Phil context is in use.

**Option B (alternative): One route per mode**

- e.g. POST /analyze, POST /recommend, POST /council, …  
- Same request/response shape per mode; easier to document and to add mode-specific validation later.

**Implementation note:** The API server should import and call the same functions used by the CLI (e.g. `analyze_file_steward_folder`, `run_council`, `web_research`). No duplication of tool logic.

---

## 4. Main Screens & Components

**Single main screen: cockpit layout.**

- **Central “current focus” area (middle, largest)**
  - **Input:** Folder path (for file-steward modes) or question/query (council / web research / next step), depending on active mode.
  - **Output:** Current result (table, list, or text) for the active mode. One result at a time; replacing when a new mode runs.
  - Optional: small “current focus” label (e.g. “Folder: …” or “Question: …”).

- **Surrounding action nodes / mode cards**
  - One card per mode: **Analyze**, **Recommend**, **Assess Uncertainty**, **Simulate**, **Council**, **Web Research**, **Next Step**.
  - Only one mode is “active” (selected) at a time; selecting a mode switches the focus area’s input type and the “Run” target.
  - Cards can show a short label and optionally a one-line description. In MVP they don’t need to show last result on the card; the central area is the single source of truth.

- **Global chrome**
  - Header: “Zenaf” + optional “Local” or “Offline” indicator.
  - Footer or sidebar: optional settings (e.g. folder defaults, “Phil context on/off” later).

**No separate “chat” screen in MVP.** The cockpit is mode + focus + result. If you add conversation later, it can be a separate tab or a slide-over, still backed by the same Python engine.

**Wireframe (conceptual):**

```
┌──────────────────────────────────────────────────────────────────┐
│  Zenaf · Local-first workflow cockpit                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│   │ Analyze │  │Recommend│  │ Assess  │  │Simulate │  …          │
│   └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘            │
│        │            │            │            │                   │
│        └────────────┴────────────┴────────────┘                  │
│                             │                                     │
│                    ┌────────▼────────┐                            │
│                    │  CURRENT FOCUS  │                            │
│                    │  [path/query]   │                            │
│                    │  [Run]          │                            │
│                    │  ─────────────  │                            │
│                    │  Result area    │                            │
│                    │  (one mode only)│                            │
│                    └─────────────────┘                            │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. Smallest Safe MVP

**Scope:** One mode working end-to-end + cockpit shell with all seven modes visible but only one wired.

**MVP 1 (minimal):**

1. **Backend**
   - Add a minimal **Zenaf API** (e.g. FastAPI) in the repo (e.g. `local_ai/api/` or `api/` at root).
   - Single route: **POST /run** with `{ "mode": "analyze", "params": { "folder_path": "..." } }`.
   - Implement only for **mode: "analyze"** (call `analyze_file_steward_folder`), return JSON (e.g. same dict the tool returns). All other modes return `501` or a clear “not implemented” message.

2. **Frontend (cockpit)**
   - **React + TypeScript + Vite + Tailwind** app (e.g. `cockpit/` or `frontend/`).
   - **One screen:** central focus + seven mode cards.
   - **State:** `activeMode` (e.g. `"analyze"`), `input` (string: path or question), `result` (object or string), `loading`, `error`.
   - **Analyze only:** When “Analyze” is selected, focus shows a folder path input and a “Run” button. On Run, POST /run with `mode: "analyze"`, show the returned result in the focus area (e.g. as JSON or a simple table/list).
   - Other six mode cards: clickable, switch `activeMode` and focus input label/placeholder, but “Run” for them can show “Coming soon” or still POST and show the 501 message.

3. **No Tauri in MVP 1.** Run the frontend with `npm run dev` and the API with `uvicorn` (or similar); use the browser. Add Tauri in a follow-up when the flow is stable.

4. **Deliverables**
   - Zenaf API server (one endpoint, analyze only).
   - Cockpit UI: layout, mode cards, focus area, Analyze flow end-to-end.
   - README or short doc: how to start API + cockpit and run “Analyze” on a folder.

**MVP 2 (next steps after MVP 1):**

- Implement **Recommend**, **Assess**, **Simulate** in the API and wire their cards (same focus area, different mode and params).
- Add **Council** and **Web Research** (params: question / query).
- Define and add **Next Step** (e.g. “one recommended action” from current folder).
- Optionally package with **Tauri** and add a “current focus” persistence (e.g. last folder path).

---

## 6. Summary

| Item | Recommendation |
|------|----------------|
| **Stack** | React, TypeScript, Vite, Tailwind; Tauri 2 for later desktop packaging. |
| **Architecture** | Cockpit (UI) → Zenaf API (thin Python) → existing engine (zenaf_tools, File Steward, provider, council, context). |
| **API** | POST /run with `mode` + `params`; optional GET /context. |
| **Layout** | Single cockpit screen: central “current focus” (input + result) + surrounding mode cards; one mode active at a time. |
| **Smallest MVP** | API with Analyze only; cockpit with all seven mode cards and Analyze working end-to-end; no Tauri yet. |

This keeps the current Python system as the single source of truth, avoids duplicating logic, and gives you a clear path from a minimal polished first version to a full workflow cockpit with all modes and, later, a packaged desktop app.
