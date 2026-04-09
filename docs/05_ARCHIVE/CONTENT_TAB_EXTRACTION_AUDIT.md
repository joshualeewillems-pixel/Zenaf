Status: Superseded  
Superseded by: docs/01_TRUTH/CODEBASE_INVENTORY.md

# Content tab — extraction audit

**Target module:** Content tab (content workspace: briefs, generation, export, VE linkage; plus Transcript Sorter).  
**Audit type:** Boundary definition and extraction feasibility. No implementation or refactors in this pass.

---

## 1. Functional surface

### User-facing features that belong to this module

- **Brief management:** List of content briefs; create new brief; select and edit a brief; persist via API (no single localStorage brief).
- **Brief lifecycle:** Status badge and transitions: Draft → Generated (after first script/newsletter run) → In production (manual “Mark brief in production”).
- **VE linkage:** Link a brief to an initiative and/or project; show “Supports: [initiative title]” / “Project: [project title]” in the UI.
- **Generation:** Generate script or newsletter from brief + source materials via LLM (`/run` with `content_script` / `content_newsletter`); regenerate; optional refinement (shorten, more direct).
- **Source distillation:** “Distill themes & claims” from source materials; pre-fill key themes and claims in the brief.
- **Export / handoff:** Copy script or newsletter; download script as file (e.g. ElevenLabs); create one or more VE tasks (Record narration, Produce video, Publish newsletter, Build landing page) attached to a chosen project.
- **Transcript Sorter (embedded):** Paste transcript → sort into topics and candidate tasks/decisions; promote candidates to VE tasks or decisions. Uses `/transcripts/sort` and VE `POST /tasks`, `POST /decisions`.

### MVP boundary (if module were isolated)

**Include:**

- Brief list, create, select, edit, save.
- Lifecycle states (draft / generated / in_production) and status display.
- Link to initiative/project (display and dropdowns).
- Generate script and newsletter; regenerate; refinement (shorten, more direct).
- Distill source (themes & claims).
- Export: copy, download script.
- Create VE tasks from suggested next actions (with project picker).

**Exclude from MVP (optional or separable):**

- **Transcript Sorter:** Functionally separate (transcript → structure → promote to VE). Could live in its own tab or app. Including it in “Content” increases backend and UI surface; excluding it keeps the Content module focused on brief → draft → handoff.
- Version history of generated outputs (not implemented today).
- Distribution planning or multi-format packaging beyond script/newsletter (design only).

---

## 2. Frontend dependencies

### Direct file/component dependencies

| File | Depends on |
|------|------------|
| `ContentView.tsx` | `./types`, `../vision-execution/types` (Initiative, Project), `ContentBriefEditor`, `ContentOutputsPane`, `ContentExportPane`, `TranscriptSorter` |
| `ContentBriefEditor.tsx` | `./types`, `../vision-execution/types` (Initiative, Project) |
| `ContentOutputsPane.tsx` | (none outside content) |
| `ContentExportPane.tsx` | `../vision-execution/types` (Project) |
| `TranscriptSorter.tsx` | (none from vision-execution types; uses `apiBase` and `/vision-execution` for tasks/decisions) |
| `types.ts` | (none) |

### Shared UI / state / utilities

- **App.tsx:** Renders `ContentView` when `mainView === 'content'`; passes `apiBase={API_BASE}` (hardcoded `http://127.0.0.1:8010`). No shared state (no Redux/context) with other views.
- **Styling:** Tailwind only; no shared design tokens or component library beyond what’s in the repo.
- **Routing:** No router; Content is one of several `mainView` values. No deep links or route params.

### What to keep shared vs duplicate/isolate

- **Keep shared (if extracted to separate app):** React, Tailwind, fetch. No need to duplicate.
- **Duplicate or isolate:** The only cross-module type imports are `Initiative` and `Project` from `../vision-execution/types`. For a standalone app, these could be replaced by a minimal local interface (e.g. `{ id: string; title: string }`) or a small shared types package. No VE components are used.
- **Config:** `apiBase` is the only injected dependency. For extraction, a single config (e.g. `apiBase`, optional `veApiBase`) would allow the same build to talk to different backends.

---

## 3. Backend dependencies

### Endpoints used by the Content tab

| Endpoint | Used by | Purpose |
|----------|--------|---------|
| `GET /vision-execution/content-briefs` | ContentView | List briefs |
| `GET /vision-execution/content-briefs/:id` | ContentView | Load one brief (when not in list cache) |
| `POST /vision-execution/content-briefs` | ContentView | Create brief |
| `PATCH /vision-execution/content-briefs/:id` | ContentView | Update brief (title, status, payload) |
| `POST /vision-execution/distill-source` | ContentBriefEditor (via ContentView) | Extract themes & claims from source text |
| `GET /vision-execution/initiatives` | ContentView | Populate initiative dropdown and “Supports” display |
| `GET /vision-execution/projects` | ContentView, ContentExportPane | Populate project dropdown and task-creation project picker |
| `POST /vision-execution/tasks` | ContentView (createVETask), TranscriptSorter | Create tasks (from next actions or from transcript promote) |
| `POST /run` (main app) | ContentView | Generate script/newsletter (mode: `content_script`, `content_newsletter`; params: `content_brief`, `content_source`, `content_output_type`, optional `content_refinement`) |
| `POST /transcripts/sort` (main app) | TranscriptSorter | Segment transcript and get candidate tasks/decisions |
| `POST /vision-execution/decisions` | TranscriptSorter | Create decision records for transcript candidates |

### Service / storage / schema

- **Content-owned:** `content_briefs` table (id, title, status, payload JSON, created_at, updated_at). CRUD in `local_ai.vision_execution.storage`; routes in `api.routes.vision_execution`. `distill_content_source` and `generate_content` in `local_ai.zenaf_tools`.
- **Shared with VE:** Same SQLite DB and `vision_execution` router. Initiatives, projects, tasks, decisions are VE entities; Content only reads initiatives/projects and writes tasks (and TranscriptSorter writes decisions).
- **Shared with app:** `POST /run` is on the main FastAPI app; content generation is one of many modes. LLM provider and zenaf_tools are shared.

### Core vs incidental

- **Core to Content:** content_briefs CRUD, distill-source, generate_content (script/newsletter), and the run modes `content_script` / `content_newsletter`.
- **Incidental but required for current UX:** initiatives and projects (for linkage and task creation), tasks (write-only). These are VE; a standalone Content app would need either the same backend or a thin proxy to a VE API.
- **TranscriptSorter:** Depends on `local_ai.transcripts` and transcript_routes; separate from the brief → generate → export flow. Could be a separate module or app.

---

## 4. Data model requirements

### Tables/fields required for this module

- **content_briefs (required):** The only table owned by Content. Fields: id, title, status, payload (JSON), created_at, updated_at. Payload holds all brief fields (linked_initiative_id, linked_project_id, audience, content_goal, key_themes, claims, etc.).

### Existing entities: essential vs optional

- **Initiatives:** Essential for “link to initiative” and “Supports: [initiative]” display. Content only needs list + id/title (and possibly status for display). No need for full initiative schema.
- **Projects:** Essential for project dropdown and for creating tasks. Content only needs list + id/title. No need for full project schema.
- **Tasks:** Essential only as a write target (POST to create). No read of tasks by Content except indirectly if the app showed “tasks created from this brief” (not implemented).
- **Decisions:** Used only by TranscriptSorter for promoting transcript decisions. Not required for the brief → generate → export flow.
- **Ideas, persons, assets, capacity, signals, radar:** Not used by the Content tab.

### Types required in the frontend

- **Content-owned:** ContentBrief, ContentBriefPayload, ContentBriefStatus, DEFAULT_BRIEF_PAYLOAD, apiBriefToBrief, briefToRunPayload, VE_TASK_TEMPLATES (or local list).
- **From VE (minimal):** Initiative and Project can be reduced to `{ id: string; title: string }` (and optionally status) for a standalone app.

---

## 5. Hidden coupling / risks

- **Single origin assumption:** All requests use the same base URL (apiBase). Vision-execution endpoints are relative to the same host. If Content were hosted on a different domain, CORS and base URL would need configuration (e.g. separate `veApiBase`).
- **No auth or tenancy:** Content does not pass tokens or tenant ids. Extraction would need to add auth if the standalone app is multi-tenant or restricted.
- **TranscriptSorter and apiBase:** TranscriptSorter uses `apiBase` for both `/transcripts/sort` and (with a path) for VE. So it assumes one backend. Splitting would require TranscriptSorter to accept a transcript API base and a VE API base.
- **Run endpoint:** Content generation goes through the global `/run` with mode and params. That endpoint is shared with council, web_research, etc. Extracting Content would still require either calling that same backend for `/run` or reimplementing generate_content (and optionally distill_content_source) in a new service.
- **DB shared with VE:** content_briefs lives in the same SQLite file as initiatives, projects, tasks. Extraction could either keep using that DB (same backend) or move content_briefs to a separate DB and then need to call VE APIs for initiatives/projects/tasks.
- **No shared cache or global state:** Content does not rely on other views’ state. Switching to Content doesn’t preload or invalidate other data. Low risk for extraction from a state perspective.

**What would break if extracted “as is” today:**

- Hardcoded `API_BASE` in App and relative `/vision-execution` paths: a standalone build would need a configurable API base (and possibly a separate VE base).
- Type imports from `../vision-execution/types`: the new app would need those types in its own tree or a tiny shared package.
- TranscriptSorter would need to know two backends if transcript sort and VE are split.

---

## 6. Recommended boundary

**Recommendation: Keep as an internal module for now.**

**Reasons:**

1. **Designed to be VE-linked.** Briefs link to initiatives/projects; “Create selected tasks” and “Mark in production” are execution handoffs. The value is tight integration with Vision Execution, not a generic content tool.
2. **Single backend keeps deployment simple.** One DB, one API host; no CORS or multi-origin setup. Fits “one Zenaf app” today.
3. **Extraction is feasible later** if we introduce clear seams: configurable API base(s), minimal types for Initiative/Project, and an optional separate deploy of “Content-only” backend that still calls VE (or proxies) for initiatives/projects/tasks.
4. **Publishing as an internal route** is already the case: Content is one main view in the same app. “Publish online as one route/view” could mean serving the same SPA with a route like `/content` and a nav that highlights Content; that’s a small change (e.g. add a router and route `/content`).

**Not recommended at this stage:**

- **Extract into a standalone app now:** Would duplicate config, types, and possibly backend logic without a clear product need. Better to keep one app and add seams for a future extraction.
- **Publish as a separate hosted “micro-frontend”** without extraction: Possible but adds operational complexity (two deploys, CORS, base URLs) for limited benefit until there is a concrete need (e.g. separate team, separate domain, or white-label).

---

## 7. Minimal isolation plan

### If kept inside the current system

- **Refactor for modularity and publishability:**
  1. **Route and deep link:** Add a simple router (or hash/query) so Content is reachable at a stable URL (e.g. `/content`). Keeps it “one view” but shareable and bookmarkable.
  2. **Config:** Allow `apiBase` (and optionally a separate `veApiBase`) to be set via env or runtime config so the same build can target different backends (e.g. staging vs prod, or a future Content-only host that still calls VE).
  3. **Document the boundary:** List Content-specific files, env vars, and API contract (this audit plus a short “Content module boundary” section in code or docs). Optionally move TranscriptSorter to its own top-level nav item so “Content” is strictly briefs + generate + export + VE tasks; Transcript Sorter becomes a sibling module.

### If extracted later

- **Seams to create now:**
  1. **Single config object:** e.g. `ContentConfig = { apiBase: string; veApiBase?: string }`. Default `veApiBase` to `apiBase`. ContentView (and TranscriptSorter if it stays) read from this. Makes it obvious what the module needs from the host.
  2. **Minimal VE types:** Add a small file (e.g. `content/ve-types.ts`) that defines only `{ id: string; title: string }` for Initiative and Project, and use those in the Content UI. Keep importing from vision-execution for now, but the option to switch to local minimal types is one file change.
  3. **API boundary:** Ensure all Content-specific backend surface is under a clear prefix: already the case (`/vision-execution/content-briefs`, `/vision-execution/distill-source`). Document that `/run` is shared and that Content needs only `content_script` and `content_newsletter` modes.

---

## 8. Concrete next implementation step

**Safest path:**

1. **Add a one-page “Content module boundary” note** (can live in `docs/CONTENT_MODULE_BOUNDARY.md` or in `frontend/src/content/README.md`) that lists:
   - Frontend: all files under `frontend/src/content/` and the fact that ContentView is mounted when `mainView === 'content'`.
   - Backend: table `content_briefs`; routes under vision_execution for content-briefs and distill-source; dependency on `/run` with content_script/content_newsletter; read of initiatives/projects; write of tasks (and, if included, TranscriptSorter’s use of transcripts and decisions).
   - Config: today only `apiBase`; document that a future `veApiBase` would allow a different host for VE.

2. **Introduce a single config prop** for the Content view: e.g. `ContentConfig` with `apiBase` and optional `veApiBase`, defaulting `veApiBase` to `apiBase`. Use it inside ContentView and TranscriptSorter instead of hardcoding relative paths. This is a small, low-risk change that makes future extraction or multi-backend support a config change rather than a code hunt.

No broader refactors, no extraction, no new app. This keeps the Content tab as an internal module while making the boundary explicit and the next step (route, or later extraction) straightforward.
