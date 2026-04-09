# Zenaf Cockpit (frontend)



React + TypeScript + Vite + Tailwind. Single-page cockpit: workspace modes, perspectives, content, vision → execution, **Settings**, intake/queue.



## Setup



```bash

cd frontend

npm install

```



## Run (development)



```bash

npm run dev

```



Open **http://127.0.0.1:5173** (dev server binds to this host so cookies match `http://127.0.0.1:8010`). Start the Zenaf API on port **8010** (see `api/README.md`).



The dev server **proxies** these paths to the API (`vite.config.ts`): **`/run`**, **`/auth`**, **`/vision-execution`**, **`/settings`** → `http://127.0.0.1:8010`, so the browser can call them on the same origin with session cookies.



## Production build



```bash

npm run build

```



Runs **`tsc -b`** (TypeScript project build) then **`vite build`**. Output: **`frontend/dist/`**.



### TypeScript / build policy



- **`tsconfig.json`**: `strict: true`. **`noUnusedLocals`** and **`noUnusedParameters`** are **`false`** so the build is not blocked by unused symbols across the large app; fix real type errors and tighten unused checks when cleaning dead code.



## Settings (UI)



- Header **Settings** → account (email, display name via `PATCH /auth/me`, logout), LLM connections (keys masked; test via `POST /settings/llm/test`), notification prefs (stored JSON; UI states delivery may not be active yet).

- Relative fetches to `/auth/*` and `/settings/*` rely on the dev proxy or a production reverse proxy to the API.



## Further documentation



- Repo-wide inventory, build notes, and architecture: **`docs/01_TRUTH/CODEBASE_INVENTORY.md`**

- File tree: **`docs/FILE_TREE_OVERVIEW.md`**


