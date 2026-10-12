# Content substrate — routing & trace prep

Prepared for the **second** execution-policy substrate after Workspace (Phase 1). No new `AiActionKind`; intents remain **snake_case strings** (not a TS enum).

## Centralized execution path

All LLM-backed Content generation in the cockpit goes through **`ContentView.runContentGenerate`** → `POST {runBase}/run` with `mode: content_script | content_newsletter`. Transcript tools and brief CRUD use other endpoints (`/transcript/...`, VE `content-briefs`); they are **not** the same seam.

The **emit-only trace pattern** used in Workspace (`createAiActionTrace` → `pushAiActionTrace`, optional `recordWorkspaceTraceOutcome`) applies cleanly here: call sites stay thin; trace payload can mirror brief id + output type + bounded snapshot (no full prompts).

## Action kind mapping (coarse)

| Content behavior | Suggested `action_kind` | Notes |
|------------------|-------------------------|--------|
| Brief → script / newsletter (generate, regenerate, refinement) | **`structured_evaluation`** | One structured “package” output; matches Workspace `/run` style. |
| Future: inline field rewrite in Content editor | **`field_text_rewrite`** | Not shipped in current Content UI. |
| Future: batched title/hook suggestions | **`suggestion_batch`** | Not shipped; would be a separate API shape. |

## Stable `action_intent` names (implemented for `/run`)

Used in **`routing_context.action_intent`** from `frontend/src/content/contentRoutingContext.ts`:

| Intent | When |
|--------|------|
| `content_brief_generate_script` | First successful script generation for the tab (no prior script text). |
| `content_brief_generate_newsletter` | First successful newsletter generation (no prior newsletter text). |
| `content_brief_regenerate_script` | Regenerate, or generation with `content_refinement` set, when output type is script. |
| `content_brief_regenerate_newsletter` | Same for newsletter. |

Policy overrides can target these keys in `overrides_by_action_intent` with `surface` aligned to routing metadata (`content` in the client payload today).

## Narrow Content routing seam (status)

**Implemented:** optional `routing_context` on the Content **`/run`** body from `ContentView` only; **omitted** behavior is unchanged for any client that does not send it. The API merges server-truth **`model_used` / `provider_used`** when `routing_context` is present (same as Workspace Phase 1).

**Shipped (brief `/run` path):** emit-only `AiActionTrace` after successful generate/regenerate (`contentRunWithTrace.ts`); bounded `input_snapshot`; server-truth `model_used` / `provider_used` when the API returns them; low-friction outcomes: copy script/newsletter → `copied`, export script → `applied`, mark in production → `applied`, Regenerate / Apply & regenerate → `edited` on the prior trace for that tab.

**Deferred:** TranscriptSorter and other non-`/run` Content-adjacent routes; optional outcome on “Create selected VE tasks.”

**Audit (routing truthfulness):** `contentRunRoutingContext` must keep `surface: 'content'`, `action_kind: 'structured_evaluation'`, and intents exactly from `CONTENT_ACTION_INTENTS` / `contentActionIntentForRun` so `POST /run` policy resolution matches traces (`emitContentBriefTraceFromRun` prefers server `model_used` / `provider_used`).

## References

- `frontend/src/content/ContentView.tsx` — `runContentGenerate`
- `frontend/src/content/contentRoutingContext.ts` — intents + `contentRunRoutingContext`
- `docs/02_ACTIVE_DESIGN/AI_ACTION_TRACE_AND_ROUTING_DESIGN.md` — trace model
- `api/main.py` — `POST /run` + `_begin_run_routing`
