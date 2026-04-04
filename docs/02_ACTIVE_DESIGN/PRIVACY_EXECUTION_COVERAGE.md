# Privacy: execution vs trace coverage

This document clarifies what is privacy-aware today and what is not.

## Execution privacy (provider / model policy)

**Applies only** when a request includes a **`routing_context`** payload that the server passes into `resolve_execution_policy_for_action` (with optional `privacy_mode` merged via `privacy_mode_to_partial`).

| Surface | How `routing_context` is sent | Notes |
|--------|-------------------------------|--------|
| Workspace organizer | `POST /run`, `POST /run/stream` | `workspaceRunRoutingContext` + `readPrivacyMode()` |
| Content brief generation | `POST /run` | `contentRunRoutingContext` + `readPrivacyMode()` |
| **Core profile** | `POST /vision-execution/core-profiles/{id}/reconcile` and `.../conversation` | Same fields: `surface`, `action_kind`, `action_intent`, `streaming`, `privacy_mode` |
| **Meeting extraction** | `POST /vision-execution/extract-meeting`, `extract-segment-summary`, `extract-meeting-segments`, `extract-meeting-synthesis` | `surface: meeting_extraction`, `action_kind: suggestion_batch`, intent per path; **one batch gate** for `extract-meeting-segments` (not per internal segment LLM call) |
| **Idea / initiative evaluate** | `POST /vision-execution/ideas/{id}/evaluate`, `.../initiatives/{id}/evaluate` | Body may include `routing_context` (`surface: vision_execution`, `action_kind: structured_evaluation`, `action_intent: idea_evaluate` \| `initiative_evaluate`); **client sends it** for policy + truthful provider metadata. Omitting it keeps **legacy** `get_provider_shim_for_legacy_generate` (user profile) behavior. |

**Intake** (`local_ai/intake`): classification is **rule-based** (no LLM); no `routing_context` seam in this pass.

If **`routing_context` is omitted**, the server uses the **legacy permissive** path for that route (no execution-policy gate from this bridge).

**Intents (Core profile):**

- `core_profile_reconcile` — `action_kind`: `structured_evaluation`
- `core_profile_conversation` — `action_kind`: `suggestion_batch` (LLM path only; heuristic loop replies do not call the provider and do not run this gate)

**Intents (Meeting extraction):**

- `meeting_extract_single` — short / single-shot `extract-meeting`
- `meeting_extract_chunks` — manual chunk `extract-meeting` per chunk, **`extract-meeting-segments`** (rolling segment batch), and standalone **`extract-segment-summary`**
- `meeting_extract_synthesis` — `extract-meeting-synthesis`

## Trace privacy (redaction / suppression)

**Applies** when traces are pushed with **`pushAiActionTrace(trace)`** and the **second argument is omitted** (`undefined`). In that case the sink uses **`getTracePrivacyFlagsForCurrentMode()`** (driven by the same `localStorage` privacy mode as execution).

If callers pass an **explicit** `TracePrivacyFlags` object (or `null` to skip auto-flags), that overrides the default-from-mode behavior for that push.

Traces are **not** a substitute for execution policy: a path can emit a redacted trace while still having run a model unless execution gating is also wired for that HTTP call.

## Related

- `privacyModeBridge.ts` — client mode storage and partial mapping  
- `local_ai/execution_policy/privacy_apply.py` — `privacy_mode_to_partial` (keep aligned with TS)  
- `CORE_PROFILE_SUBSTRATE_PREP.md` — Core profile trace emit points  
- `MEETING_EXTRACTION_TRACE_PREP.md` — meeting extraction trace (one trace per completed staging, not per chunk)  
