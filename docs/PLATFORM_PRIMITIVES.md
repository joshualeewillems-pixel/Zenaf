# Platform Primitives

Which concepts in Zenaf are shared platform primitives today, which are intake-specific but likely to become shared, and which are aspirational. Source: current docs and `docs/codebase_manifest.json`. Reality over aspiration; integration is not overstated.

---

## 1. Policy / Data Access

| Field | Value |
|-------|--------|
| **Status** | `partially_shared` |
| **Where implemented** | `local_ai/policy/data_access.py`: `AccessLevel`, `DataTier`, `request_access()`, `require_access()`, `tier_satisfies()`, `access_level_to_tier()`, `Destination` (local/external). |
| **Who uses it today** | **Single consumer:** `local_ai/intake/mirror.py` → `get_item_with_content()`. That function calls `request_access(access_level, justification=...)` before returning item dict with Tier B (sanitized body) or Tier C (placeholder). No other module imports or calls the policy layer. |
| **Who should use it later** | Per `ZENAF_ARCHITECTURE.md`: intake, council/perspectives, File Steward, Idea Lab, future connectors—whenever they read Tier B/C content or send content to an external destination. |
| **Biggest gap** | Policy is implemented and lives in a shared package, but only one call site uses it. No API route or UI calls `get_item_with_content()`, so Tier B/C gating is unused in practice. Council, File Steward, and Idea Lab do not call `request_access`. The `destination=Destination.EXTERNAL` parameter exists for egress gating but is never passed. |

---

## 2. Judgment

| Field | Value |
|-------|--------|
| **Status** | `intake_specific` |
| **Where implemented** | `local_ai/judgment/__init__.py`: in-memory store; `JudgmentRecord`; `create_intake_judgment()`, `create_correction_record()`, `add_record()`, `get_record()`, `get_for_entity()`, `get_supersession_chain()`. Persistence: only via `local_ai/intake/mirror.py` (mirror_judgment table); judgment module has no persistence of its own. |
| **Who uses it today** | **Intake only.** Pipeline calls `create_intake_judgment()` per item; `queue_store.update_item()` calls `create_correction_record()` when lane_override + correction_note are set. Mirror reads/writes judgment records when loading or upserting. Domain is fixed as `DOMAIN_INTAKE`. |
| **Who should use it later** | Per `local_ai/judgment/README.md` and architecture: intake, vision→execution, council. No other domain currently creates or queries judgment records. |
| **Biggest gap** | No generic multi-domain persistence. The judgment layer is domain-agnostic in API shape, but only the intake mirror persists it; there is no shared “judgment store” or schema that vision-execution or council could use. Vision Execution has its own `decisions` table and does not use the judgment layer. |

---

## 3. Persistent Mirror Pattern

| Field | Value |
|-------|--------|
| **Status** | `intake_specific` |
| **Where implemented** | Intake: `local_ai/intake/mirror.py` (SQLite `intake_mirror.db`) + `queue_store.py` (in-memory `_items`, `_order`) + startup in `api/main.py` calling `mirror.load_into_memory()`. Pattern: external source of truth (mailbox, read-only) → durable local projection (mirror DB) → in-memory working set (queue + judgment store) rebuilt on startup; write-through on add/update. |
| **Who uses it today** | **Intake only.** Vision Execution uses `local_ai/vision_execution/storage.py` and its own SQLite DB but does not use a “mirror + load_into_memory” pattern; it is stateless read/write per request. |
| **Who should use it later** | Any domain that needs “external system of record + local working set + restart recovery” could adopt this pattern; architecture does not name other domains explicitly. |
| **Biggest gap** | Only intake implements the full pattern. Mirror tables `mirror_sync` and `mailbox_action` exist and have APIs but are not used by poll (no `set_sync_state` or `record_mailbox_action` after poll). So even within intake, the pattern is only partially exercised. |

---

## 4. Artifact / Content Access

| Field | Value |
|-------|--------|
| **Status** | `intake_specific` |
| **Where implemented** | Tier A/B/C and content access are implemented in intake: `local_ai/intake/mirror.py` (schema with Tier A columns, `sanitized_body_text`, `raw_content_ref`); `get_item_with_content(item_id, access_level, justification)` uses `local_ai.policy.data_access.request_access()` and returns item dict with optional body content. Queue list/detail use only Tier A via `get_queue()` / `get_item()` (no policy call). |
| **Who uses it today** | **No consumer of Tier B/C.** `get_item_with_content()` exists but no API route or frontend calls it. So “artifact/content access” in the sense of “request Tier B or C through policy” is implemented in one place and unused. |
| **Who should use it later** | Any UI or module that needs to show or send body/sanitized content (e.g. “view body” in queue, council summarizing an item, Idea Lab with intake context) should go through this path with appropriate access level and justification. |
| **Biggest gap** | The primitive is intake-scoped (artifacts are intake items). There is no generic “artifact store” or “content access” API across domains. Tier C is a schema placeholder only (`raw_content_ref`); no code stores or retrieves full raw content. |

---

## 5. Adapters

| Field | Value |
|-------|--------|
| **Status** | `aspirational` |
| **Where implemented** | `local_ai/adapters/__init__.py`: registry (`register_adapter`, `get_adapter`, `list_adapters`), protocols `LLMAdapter` and `MailboxAdapter`. Default registration: `llm.ollama` → `OllamaProvider`. No Mailbox adapter implementation is registered. |
| **Who uses it today** | **No module uses the registry for runtime behavior.** Intake uses `local_ai.intake.email_ingestion` and `gmail_oauth` directly for mailbox fetch. Council, next step, reassess, and other tools use `local_ai.providers.get_default_provider()` for LLM, not `get_adapter("llm", "ollama")`. So the adapter layer exists but is bypassed. |
| **Who should use it later** | Per architecture: mailbox/comms, docs/files, workflow trackers, LLM providers, etc., should be integrated via thin adapters; core owns routing and decision logic. Intake would use a mailbox adapter for fetch; tools would use an LLM adapter (or providers behind it) for generation. |
| **Biggest gap** | Full gap: no integration. Registry and one LLM registration are dead code from the perspective of the current request path. No mailbox adapter exists; no code path calls `get_adapter()` for either kind. |

---

## 6. Observations / Actions

| Field | Value |
|-------|--------|
| **Status** | **Conceptual / intake-only in practice.** There is no platform-wide “observations” or “actions” primitive. What exists is domain-specific and partially stubbed. |
| **Where implemented** | **Observations:** As a **field** on `JudgmentRecord` only: `observation_ref` (dict with e.g. `subject_preview`, `body_length`, `matched_signals`). Set in `local_ai/intake/pipeline.py` when creating the intake judgment; no raw content. There is no separate observation store or observation API shared across domains. **Actions:** (1) `proposed_action` on `JudgmentRecord` (e.g. `{"lane": "needs_attention"}`)—intake-only. (2) `mailbox_action` table in intake mirror: schema and `record_mailbox_action()` exist for auditing future mailbox mutations (action_type, payload, applied_at, etc.). No code calls `record_mailbox_action()` today; mailbox is read-only. There is no shared “action bus” or “action log” used by multiple modules. |
| **Who uses it today** | Intake pipeline (writes `observation_ref` and `proposed_action` on judgment). Intake mirror (persists them). No other domain uses observation_ref or proposed_action. Nobody writes to mailbox_action. |
| **Who should use it later** | Architecture describes judgment as “observations, interpretation, proposed action”; that is the conceptual model. For actions that affect external systems (e.g. “mark read”, “move to folder”), the intended path is audit via something like mailbox_action and drive mutations from mirror/audit—not yet built. |
| **Biggest gap** | “Observations” and “actions” are not first-class platform primitives. They exist as fields inside the intake judgment flow and as a conceptual/audit table (mailbox_action) with no writer. No shared observation or action protocol exists for council, Vision Execution, or other domains. |

---

## Summary Table

| Concept | Status | Single consumer / scope |
|---------|--------|--------------------------|
| Policy / data access | partially_shared | Only intake mirror `get_item_with_content()` |
| Judgment | intake_specific | Intake only; persistence via intake mirror only |
| Persistent mirror pattern | intake_specific | Intake only; Vision Execution is plain DB |
| Artifact/content access | intake_specific | Implemented for intake items; no caller of `get_item_with_content` |
| Adapters | aspirational | Registry exists; no runtime use for LLM or mailbox |
| Observations / actions | conceptual (intake-only in code) | observation_ref and proposed_action on judgment; mailbox_action table unused |
