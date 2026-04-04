# Truth convergence (charter)

<!--
Status: Canonical — locked decisions for source-of-truth ownership.
Last updated: 2026-04-03
-->

Short record of **what the system is allowed to treat as true**. When code or docs disagree, update the code **or** revise this file explicitly.

---

## Locked decisions

| Topic | Decision | One-sentence truth |
|-------|----------|--------------------|
| **Ideas / old Idea Lab** | Removed | **Vision Execution** (`/vision-execution`, SQLite `ideas`) is the only idea product path. |
| **Intake mirror sync / mailbox_action** | Not a product story until wired | **Intake truth** is queue + judgments only; no implied sync/mailbox observability without real writers. |
| **Intake tiers** | Defer honestly (2c) | **Product** exposes **Tier A** only; Tier B/C may exist in code but are **not** part of the public contract. |
| **Council perspective agents** | Server-owned (4a) | **Server** owns definitions when signed in (`user_council_workspace` + `GET`/`PUT /vision-execution/council-workspace/perspectives`); **client** edits and sends payloads built from hydrated state; **`localStorage`** is cache + anonymous fallback. |
| **AI traces** | Full coverage or exempt (6a) | **Every** AI-touching path emits a trace **or** is listed in `frontend/src/ai-actions/aiTraceExemptRegistry.ts` with a stable exempt id. |
| **Field naming** | DB/API tokens are law (7a) | **Schema + models** define canonical JSON keys; UI copy is labels only. |

---

## Related implementation

- Council workspace persistence: `local_ai/vision_execution/schema.sql` → `user_council_workspace`; `api/routes/vision_execution.py` routes above.
- Trace exempt registry: `frontend/src/ai-actions/aiTraceExemptRegistry.ts`.

---

## Core profile note (directional)

**User-level core** (`core_profiles` per account) vs **system-level archetypes** (built-in perspective actors in `frontend/src/perspectives/types.ts`) remains the product split; optional future **server-published core templates** would be documented here when added.
