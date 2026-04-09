# Frontend ↔ API “phantom call” audit

**Purpose:** List every browser `fetch` entry path used by the SPA, whether it is meant to hit FastAPI, and whether Vite dev (`127.0.0.1:5173`) forwards it to the API (`127.0.0.1:8010`). A **phantom** call is one that resolves to the dev server or wrong origin and never reaches the backend (typical symptom: **404 from Vite**).

**Convention:** Dev SPA should load from **`http://127.0.0.1:5173`** so session cookies align with **`http://127.0.0.1:8010`** (see `App.tsx` / `vite.config.ts` comments). `localhost` on the SPA host is a different cookie context.

## Vite proxy map (`frontend/vite.config.ts`)

| Path prefix | Proxied to 8010 | Backend area |
|-------------|-----------------|--------------|
| `/run` | Yes | Long-running LLM / council |
| `/auth` | Yes | Session |
| `/vision-execution` | Yes | Vision Execution router |
| `/settings` | Yes | Settings router (`prefix="/settings"` → e.g. `/settings/llm`) |
| `/studio/` | Yes | Studio router (`prefix="/studio"`) |
| `/api` | Yes | e.g. `POST /api/transcribe` |
| `/transcripts` | Yes | Transcript sorter (`POST /transcripts/sort`) |

## Intentionally **not** proxied (absolute `API_BASE`)

`App.tsx` defines `API_BASE = 'http://127.0.0.1:8010'`. All **`/intake/...`** and **`/folder-picker`** traffic uses that host directly (not same-origin). This is **by design** for intake/OAuth; it is **not** a Vite phantom as long as the API listens on 8010. If the API runs on another port, these calls fail with connection errors or 404 on 8010 — that is a **config mismatch**, not a missing proxy.

## Relative `fetch` bases (same-origin in dev → must match proxy)

| Client pattern | Example | Proxied? |
|----------------|---------|----------|
| `RUN_API_BASE` (`''`) | `POST /run`, `POST /run/stream` | Yes (`/run`) |
| `VISION_EXECUTION_API` (`/vision-execution`) | Many VE CRUD and reads | Yes |
| `AUTH_BASE` (`/auth`) | `/auth/me`, login, logout | Yes |
| `settings/api.ts` `BASE` (`/settings`) | `/settings/llm`, … | Yes |
| `/studio/...` | Studio UI | Yes (`/studio/`) |
| `/api/transcribe` | Voice transcription | Yes (`/api`) |
| `TranscriptSorter` with `apiBase=""` | `POST /transcripts/sort`, `/vision-execution/tasks`, `/vision-execution/decisions` | Yes after `/transcripts` proxy; VE paths were already proxied |

## Issues found and fixes

1. **`POST /transcripts/sort` in dev (fixed):** `TranscriptSorter` uses empty `apiBase`, so the browser called **`/transcripts/sort`** on the Vite origin. **`/transcripts` was not proxied** → Vite 404 (phantom). **Fix:** add `'/transcripts'` to `vite.config.ts` `server.proxy`.

2. **`ContentFrontDoor` `apiBase` prop:** `App.tsx` passes `apiBase={API_BASE}`, but the component builds `effectiveConfig` from `config ?? { apiBase: '', veApiBase: '' }` and does not use the prop for Content/Transcript URLs. The prop is currently **unused** (misleading for readers). Same-origin empty bases + proxy are intentional for cookie-friendly VE/`/run` usage; consider removing the prop or wiring it explicitly later for non-dev builds.

## Backend optional routers

In `api/main.py`, several routers are loaded inside `try/except`. If an import fails, the corresponding routes are **absent** at runtime; the frontend would then get **404 from FastAPI** (not a Vite phantom). Check server logs for messages like `Transcript routes not loaded`.

## Maintenance

When adding a new top-level API prefix, either:

- add a matching Vite proxy entry, or  
- use an absolute base that points at the real API host.

Re-audit hint: search `frontend/src` for `fetch(` and for string bases (`VISION_EXECUTION_API`, `API_BASE`, `RUN_API_BASE`, `/settings`, `/studio`).
